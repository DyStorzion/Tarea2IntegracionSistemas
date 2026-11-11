"""Servicio Pagos: simulador de la pasarela de pago EXTERNA (cobra y reembolsa).

El contrato de la API está en app/contrato.py y en docs/api/pagos.json.

Idempotencia: la clave primaria de la tabla `cobros` es el saga_id. Cada operación es
una sola sentencia atómica en Postgres (INSERT ... ON CONFLICT / UPDATE condicionado),
así que dos peticiones simultáneas con el mismo saga_id no pueden generar dos cobros.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from prometheus_client import Counter, make_asgi_app
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import chaos as fallas
from app.config import MONTO_MAXIMO, SERVICE_NAME
from app.contrato import (
    ChaosIn,
    ChaosOut,
    CobroIn,
    CobroOut,
    CodigoError,
    ErrorRespuesta,
    ReembolsoOut,
)
from app.db import crear_tablas, engine, obtener_sesion
from app.modelos import ANULADO, COBRADO, REEMBOLSADO, Cobro

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

OPERACIONES = Counter("pagos_operaciones_total", "Operaciones de la pasarela por resultado", ["operacion", "resultado"])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await crear_tablas()
    yield
    await engine.dispose()


app = FastAPI(title="Servicio Pagos (pasarela simulada)", version="0.2.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())
app.middleware("http")(fallas.middleware)

# Respuestas que puede producir la inyección de fallas en las rutas de negocio.
RESPUESTAS_CHAOS = {
    500: {"model": ErrorRespuesta, "description": "ERROR_SIMULADO (modo error)"},
    503: {"model": ErrorRespuesta, "description": "SERVICIO_NO_DISPONIBLE (modo down)"},
}


def error(status: int, codigo: CodigoError, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})


def a_salida(cobro: Cobro) -> CobroOut:
    return CobroOut(
        saga_id=cobro.saga_id,
        cobro_id=cobro.cobro_id,
        cliente_id=cobro.cliente_id,
        monto=cobro.monto,
        estado=cobro.estado,
        actualizado_en=cobro.actualizado_en,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post(
    "/cobros",
    response_model=CobroOut,
    status_code=201,
    responses={
        200: {"model": CobroOut, "description": "Repetición con el mismo saga_id: devuelve el cobro existente, sin cobrar de nuevo"},
        402: {"model": ErrorRespuesta, "description": "PAGO_RECHAZADO"},
        409: {"model": ErrorRespuesta, "description": "SAGA_ANULADA"},
        **RESPUESTAS_CHAOS,
    },
)
async def cobrar(body: CobroIn, response: Response, sesion: AsyncSession = Depends(obtener_sesion)):
    """Paso 2 de la Saga. Idempotente: el mismo saga_id nunca genera dos cobros."""
    if body.monto > MONTO_MAXIMO:
        OPERACIONES.labels("cobrar", "rechazado").inc()
        log.info("cobro rechazado saga_id=%s monto=%s", body.saga_id, body.monto)
        raise error(402, CodigoError.PAGO_RECHAZADO, f"La pasarela rechazó el cobro: ${body.monto} supera el máximo de ${MONTO_MAXIMO}")

    # Inserta solo si no hay registro para este saga_id (ni cobro previo ni anulación).
    insercion = (
        insert(Cobro)
        .values(
            saga_id=body.saga_id,
            estado=COBRADO,
            cobro_id=f"COB-{uuid.uuid4().hex[:12].upper()}",
            cliente_id=body.cliente_id,
            monto=body.monto,
        )
        .on_conflict_do_nothing(index_elements=[Cobro.saga_id])
        .returning(Cobro.saga_id)
    )
    creado = (await sesion.execute(insercion)).scalar_one_or_none() is not None
    await sesion.commit()
    cobro = await sesion.get(Cobro, body.saga_id)

    if cobro.estado == ANULADO:
        OPERACIONES.labels("cobrar", "saga_anulada").inc()
        log.info("cobro rechazado por saga anulada saga_id=%s", body.saga_id)
        raise error(409, CodigoError.SAGA_ANULADA, "La saga ya fue compensada; no se cobra")

    OPERACIONES.labels("cobrar", "cobrado" if creado else "repetido").inc()
    log.info("cobro %s saga_id=%s cobro_id=%s monto=%s", "creado" if creado else "repetido", cobro.saga_id, cobro.cobro_id, cobro.monto)
    response.status_code = 201 if creado else 200
    return a_salida(cobro)


@app.post("/cobros/{saga_id}/reembolso", response_model=ReembolsoOut, responses=RESPUESTAS_CHAOS)
async def reembolsar(saga_id: str, sesion: AsyncSession = Depends(obtener_sesion)):
    """Compensación del paso 2. Responde 200 salvo falla inyectada.

    - Cobro existente: queda REEMBOLSADO (si ya lo estaba, no hace nada).
    - Sin cobro para ese saga_id: registra la saga como ANULADA.
    """
    # 1) Si no hay registro, deja la saga ANULADA: un cobro que llegue después será rechazado.
    await sesion.execute(
        insert(Cobro).values(saga_id=saga_id, estado=ANULADO).on_conflict_do_nothing(index_elements=[Cobro.saga_id])
    )
    # 2) Si había un cobro vigente, lo reembolsa. Si ya estaba reembolsado o anulado, no cambia nada.
    await sesion.execute(update(Cobro).where(Cobro.saga_id == saga_id, Cobro.estado == COBRADO).values(estado=REEMBOLSADO))
    await sesion.commit()
    cobro = await sesion.get(Cobro, saga_id)

    OPERACIONES.labels("reembolsar", cobro.estado.lower()).inc()
    log.info("reembolso saga_id=%s estado=%s", saga_id, cobro.estado)
    return ReembolsoOut(saga_id=saga_id, estado=cobro.estado)


@app.get(
    "/cobros/{saga_id}",
    response_model=CobroOut,
    responses={404: {"model": ErrorRespuesta, "description": "COBRO_NO_EXISTE"}, **RESPUESTAS_CHAOS},
)
async def obtener(saga_id: str, sesion: AsyncSession = Depends(obtener_sesion)):
    """Consulta usada por el BFF."""
    # Una saga ANULADA no tiene cobro asociado: para quien consulta, no existe.
    cobro = await sesion.get(Cobro, saga_id)
    if cobro is None or cobro.estado == ANULADO:
        raise error(404, CodigoError.COBRO_NO_EXISTE, f"No hay un cobro para la saga {saga_id}")
    return a_salida(cobro)


@app.get("/admin/chaos", response_model=ChaosOut)
async def ver_chaos():
    """Modo de falla activo."""
    return fallas.actual()


@app.post("/admin/chaos", response_model=ChaosOut)
async def chaos(body: ChaosIn):
    """Cambia el modo de falla. Afecta solo a las rutas de negocio (no a /health, /metrics ni /admin)."""
    return fallas.cambiar(body)
