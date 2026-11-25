"""Servicio Reservas: orquestador de la Saga «Reservar un espacio de cowork».

Pasos (y compensación en orden inverso):
  1. Espacios: reservar       -> liberar
  2. Pagos:    cobrar         -> reembolsar
  3. Acceso:   habilitar (QR) -> revocar

Las rutas están aquí; la lógica de la saga, en app/saga.py; las llamadas a las
dependencias, en app/resiliencia.py (D-54). El contrato está en app/contrato.py.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from prometheus_client import make_asgi_app
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import resiliencia, saga
from app.config import SERVICE_NAME
from app.contrato import CodigoError, Error, ErrorRespuesta, EstadoSaga, Paso, ReservaIn, SagaOut
from app.db import crear_tablas, engine, obtener_sesion
from app.modelos import PasoSaga, Saga

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await crear_tablas()
    await resiliencia.iniciar()  # cliente HTTP compartido (D-43, D-54)
    yield
    await resiliencia.cerrar()
    await engine.dispose()


app = FastAPI(title="Servicio Reservas (orquestador de la Saga)", version="0.3.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


async def a_salida(sesion: AsyncSession, s: Saga) -> SagaOut:
    pasos = (await sesion.scalars(select(PasoSaga).where(PasoSaga.saga_id == s.saga_id).order_by(PasoSaga.orden))).all()
    return SagaOut(
        saga_id=s.saga_id,
        estado=s.estado,
        cliente_id=s.cliente_id,
        espacio_id=s.espacio_id,
        fecha=s.fecha,
        bloque=s.bloque,
        precio=s.precio,
        qr=s.qr,
        error=Error(codigo=s.error_codigo, mensaje=s.error_mensaje) if s.error_codigo else None,
        pasos=[Paso.model_validate(p, from_attributes=True) for p in pasos],
        creada_en=s.creada_en,
        actualizada_en=s.actualizada_en,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "resilience_enabled": resiliencia.ACTIVADA}


@app.post(
    "/reservas",
    response_model=SagaOut,
    status_code=201,
    responses={
        200: {"model": SagaOut, "description": "Repetición con la misma Idempotency-Key: devuelve la saga ya ejecutada"},
        402: {"model": SagaOut, "description": "COMPENSADA · PAGO_RECHAZADO: se liberó el espacio"},
        404: {"model": SagaOut, "description": "RECHAZADA · ESPACIO_NO_EXISTE"},
        409: {"model": SagaOut, "description": "RECHAZADA · FRANJA_OCUPADA: no hubo nada que compensar"},
        422: {"model": SagaOut, "description": "RECHAZADA · FRANJA_PASADA: el bloque ya empezó (D-53)"},
        502: {
            "model": SagaOut,
            "description": "Una dependencia falló o no respondió a tiempo (ESPACIOS_FALLO, PAGOS_FALLO, ACCESO_FALLO): "
            "COMPENSADA. Si además falló una compensación: COMPENSACION_PENDIENTE · COMPENSACION_FALLIDA",
        },
        503: {
            "model": SagaOut,
            "description": "Fail-fast de resiliencia, con encabezado Retry-After. ACCESO_NO_DISPONIBLE (circuito abierto): "
            "RECHAZADA si se detectó antes de empezar, COMPENSADA si ocurrió en el paso 3. "
            "ACCESO_SATURADO (Bulkhead sin cupo en el paso 3): COMPENSADA",
        },
    },
)
async def crear_reserva(
    body: ReservaIn,
    response: Response,
    x_consumer_username: str = Header(description="Cliente autenticado; lo agrega Kong tras validar el JWT"),
    idempotency_key: str | None = Header(
        default=None, description="Opcional. Si se repite, devuelve la misma saga en vez de crear otra (evita dobles cobros)"
    ),
    x_request_id: str | None = Header(default=None, description="Lo genera Kong (D-28); se reenvía a las dependencias"),
    sesion: AsyncSession = Depends(obtener_sesion),
):
    """Ejecuta la Saga completa y responde con su resultado final (respuesta síncrona).

    El cuerpo de la respuesta es siempre SagaOut, también cuando la saga no se confirma:
    el código HTTP y el campo `error` indican el motivo, y `pasos` contiene el saga log.
    """
    # La saga se guarda EN_CURSO antes del paso 1 (D-60). Si la Idempotency-Key ya la usó este
    # cliente, la restricción única lo detecta en la misma sentencia y no se ejecuta nada.
    saga_id = (
        await sesion.execute(
            insert(Saga)
            .values(
                saga_id=str(uuid.uuid4()),
                idempotency_key=idempotency_key,
                estado=EstadoSaga.EN_CURSO.value,
                cliente_id=x_consumer_username,
                espacio_id=body.espacio_id,
                fecha=body.fecha,
                bloque=body.bloque,
            )
            .on_conflict_do_nothing(index_elements=[Saga.cliente_id, Saga.idempotency_key])
            .returning(Saga.saga_id)
        )
    ).scalar_one_or_none()
    await sesion.commit()

    if saga_id is None:  # repetición: se devuelve la saga original tal como esté, incluso EN_CURSO
        original = await sesion.scalar(
            select(Saga).where(Saga.cliente_id == x_consumer_username, Saga.idempotency_key == idempotency_key)
        )
        log.info("saga_id=%s request_id=%s repeticion idempotency_key=%s", original.saga_id, x_request_id, idempotency_key)
        response.status_code = 200
        return await a_salida(sesion, original)

    nueva = await sesion.get(Saga, saga_id)
    log.info("saga_id=%s request_id=%s inicio cliente=%s espacio=%s fecha=%s bloque=%s", saga_id, x_request_id, x_consumer_username, body.espacio_id, body.fecha, body.bloque)
    response.status_code = await saga.ejecutar(sesion, nueva, x_request_id)
    return await a_salida(sesion, nueva)


@app.get(
    "/reservas/{saga_id}",
    response_model=SagaOut,
    responses={404: {"model": ErrorRespuesta, "description": "SAGA_NO_EXISTE"}},
)
async def obtener_reserva(saga_id: str, sesion: AsyncSession = Depends(obtener_sesion)):
    """Estado de la saga y su saga log."""
    s = await sesion.get(Saga, saga_id)
    if s is None:
        raise HTTPException(status_code=404, detail={"codigo": CodigoError.SAGA_NO_EXISTE, "mensaje": f"No existe la saga {saga_id}"})
    return await a_salida(sesion, s)
