"""Servicio Acceso: simulador del controlador EXTERNO de puerta con QR (la dependencia frágil).

El contrato de la API está en app/contrato.py y en docs/api/acceso.json.

Idempotencia: la clave primaria de la tabla `accesos` es el saga_id. Cada operación es
una sola sentencia atómica en Postgres (INSERT ... ON CONFLICT / UPDATE condicionado),
así que dos peticiones simultáneas con el mismo saga_id no pueden generar dos QR.
"""

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta

from fastapi import Depends, FastAPI, HTTPException, Response
from prometheus_client import Counter, make_asgi_app
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import chaos as fallas
from app.config import SERVICE_NAME, ZONA_HORARIA
from app.contrato import (
    AccesoIn,
    AccesoOut,
    ChaosIn,
    ChaosOut,
    CodigoError,
    ErrorRespuesta,
    RevocacionOut,
)
from app.db import crear_tablas, engine, obtener_sesion
from app.modelos import ANULADO, HABILITADO, REVOCADO, Acceso

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

OPERACIONES = Counter("acceso_operaciones_total", "Operaciones del controlador de puerta por resultado", ["operacion", "resultado"])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await crear_tablas()
    yield
    await engine.dispose()


app = FastAPI(title="Servicio Acceso (controlador de puerta simulado)", version="0.2.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())
app.middleware("http")(fallas.middleware)

# Respuestas que puede producir la inyección de fallas en las rutas de negocio.
RESPUESTAS_CHAOS = {
    500: {"model": ErrorRespuesta, "description": "ERROR_SIMULADO (modo error)"},
    503: {"model": ErrorRespuesta, "description": "SERVICIO_NO_DISPONIBLE (modo down)"},
}


def error(status: int, codigo: CodigoError, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})


def nuevo_qr() -> str:
    """Código aleatorio del tipo QR-1A2B-3C4D."""
    hexa = secrets.token_hex(4).upper()
    return f"QR-{hexa[:4]}-{hexa[4:]}"


def ventana_de_validez(fecha: date, bloque: int) -> tuple[datetime, datetime]:
    """El QR abre la puerta solo durante el bloque reservado, en hora local del cowork."""
    desde = datetime.combine(fecha, time(hour=bloque), tzinfo=ZONA_HORARIA)
    return desde, desde + timedelta(hours=1)


def a_salida(acceso: Acceso) -> AccesoOut:
    return AccesoOut(
        saga_id=acceso.saga_id,
        cliente_id=acceso.cliente_id,
        espacio_id=acceso.espacio_id,
        fecha=acceso.fecha,
        bloque=acceso.bloque,
        qr=acceso.qr,
        estado=acceso.estado,
        # Postgres devuelve las fechas en UTC; para la puerta se muestran en hora local.
        valido_desde=acceso.valido_desde.astimezone(ZONA_HORARIA),
        valido_hasta=acceso.valido_hasta.astimezone(ZONA_HORARIA),
        actualizado_en=acceso.actualizado_en,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post(
    "/accesos",
    response_model=AccesoOut,
    status_code=201,
    responses={
        200: {"model": AccesoOut, "description": "Repetición con el mismo saga_id: devuelve el acceso existente"},
        409: {"model": ErrorRespuesta, "description": "SAGA_ANULADA"},
        **RESPUESTAS_CHAOS,
    },
)
async def habilitar(body: AccesoIn, response: Response, sesion: AsyncSession = Depends(obtener_sesion)):
    """Paso 3 de la Saga: habilita la puerta y devuelve el QR. Idempotente por saga_id."""
    desde, hasta = ventana_de_validez(body.fecha, body.bloque)
    # Inserta solo si no hay registro para este saga_id (ni acceso previo ni anulación).
    insercion = (
        insert(Acceso)
        .values(
            saga_id=body.saga_id,
            estado=HABILITADO,
            qr=nuevo_qr(),
            cliente_id=body.cliente_id,
            espacio_id=body.espacio_id,
            fecha=body.fecha,
            bloque=body.bloque,
            valido_desde=desde,
            valido_hasta=hasta,
        )
        .on_conflict_do_nothing(index_elements=[Acceso.saga_id])
        .returning(Acceso.saga_id)
    )
    creado = (await sesion.execute(insercion)).scalar_one_or_none() is not None
    await sesion.commit()
    acceso = await sesion.get(Acceso, body.saga_id)

    if acceso.estado == ANULADO:
        OPERACIONES.labels("habilitar", "saga_anulada").inc()
        log.info("habilitación rechazada por saga anulada saga_id=%s", body.saga_id)
        raise error(409, CodigoError.SAGA_ANULADA, "La saga ya fue compensada; no se habilita el acceso")

    OPERACIONES.labels("habilitar", "habilitado" if creado else "repetido").inc()
    log.info("acceso %s saga_id=%s qr=%s", "habilitado" if creado else "repetido", acceso.saga_id, acceso.qr)
    response.status_code = 201 if creado else 200
    return a_salida(acceso)


@app.post("/accesos/{saga_id}/revocar", response_model=RevocacionOut, responses=RESPUESTAS_CHAOS)
async def revocar(saga_id: str, sesion: AsyncSession = Depends(obtener_sesion)):
    """Compensación del paso 3. Responde 200 salvo falla inyectada.

    - Acceso existente: queda REVOCADO (si ya lo estaba, no hace nada).
    - Sin acceso para ese saga_id: registra la saga como ANULADA.
    """
    # 1) Si no hay registro, deja la saga ANULADA: una habilitación que llegue después será rechazada.
    await sesion.execute(
        insert(Acceso).values(saga_id=saga_id, estado=ANULADO).on_conflict_do_nothing(index_elements=[Acceso.saga_id])
    )
    # 2) Si había un acceso vigente, lo revoca. Si ya estaba revocado o anulado, no cambia nada.
    await sesion.execute(
        update(Acceso).where(Acceso.saga_id == saga_id, Acceso.estado == HABILITADO).values(estado=REVOCADO)
    )
    await sesion.commit()
    acceso = await sesion.get(Acceso, saga_id)

    OPERACIONES.labels("revocar", acceso.estado.lower()).inc()
    log.info("revocación saga_id=%s estado=%s", saga_id, acceso.estado)
    return RevocacionOut(saga_id=saga_id, estado=acceso.estado)


@app.get(
    "/accesos/{saga_id}",
    response_model=AccesoOut,
    responses={404: {"model": ErrorRespuesta, "description": "ACCESO_NO_EXISTE"}, **RESPUESTAS_CHAOS},
)
async def obtener(saga_id: str, sesion: AsyncSession = Depends(obtener_sesion)):
    """Consulta usada por el BFF."""
    # Una saga ANULADA no tiene acceso asociado: para quien consulta, no existe.
    acceso = await sesion.get(Acceso, saga_id)
    if acceso is None or acceso.estado == ANULADO:
        raise error(404, CodigoError.ACCESO_NO_EXISTE, f"No hay un acceso para la saga {saga_id}")
    return a_salida(acceso)


@app.get("/admin/chaos", response_model=ChaosOut)
async def ver_chaos():
    """Modo de falla activo."""
    return fallas.actual()


@app.post("/admin/chaos", response_model=ChaosOut)
async def chaos(body: ChaosIn):
    """Cambia el modo de falla. Afecta solo a las rutas de negocio (no a /health, /metrics ni /admin)."""
    return fallas.cambiar(body)
