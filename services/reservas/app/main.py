"""Servicio Reservas: orquestador de la Saga «Reservar un espacio de cowork».

Pasos (y compensación en orden inverso):
  1. Espacios: reservar       -> liberar
  2. Pagos:    cobrar         -> reembolsar
  3. Acceso:   habilitar (QR) -> revocar

Las rutas definen el contrato (ver app/contrato.py). Responden 501 hasta implementarse.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from prometheus_client import make_asgi_app

from app import resiliencia
from app.config import SERVICE_NAME
from app.contrato import CodigoError, ErrorRespuesta, ReservaIn, SagaOut
from app.db import crear_tablas, engine
from app import modelos  # noqa: F401  registra las tablas del saga log antes de crear_tablas()

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await crear_tablas()
    await resiliencia.iniciar()  # cliente HTTP compartido (D-43, D-54)
    yield
    await resiliencia.cerrar()
    await engine.dispose()


app = FastAPI(title="Servicio Reservas (orquestador de la Saga)", version="0.2.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


def no_implementado() -> HTTPException:
    return HTTPException(
        status_code=501,
        detail={"codigo": CodigoError.NO_IMPLEMENTADO, "mensaje": "Definido en el contrato, pendiente de implementación"},
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
    x_consumer_username: str = Header(description="Cliente autenticado; lo agrega Kong tras validar el JWT"),
    idempotency_key: str | None = Header(
        default=None, description="Opcional. Si se repite, devuelve la misma saga en vez de crear otra (evita dobles cobros)"
    ),
):
    """Ejecuta la Saga completa y responde con su resultado final (respuesta síncrona).

    El cuerpo de la respuesta es siempre SagaOut, también cuando la saga no se confirma:
    el código HTTP y el campo `error` indican el motivo, y `pasos` contiene el saga log.
    """
    raise no_implementado()


@app.get(
    "/reservas/{saga_id}",
    response_model=SagaOut,
    responses={404: {"model": ErrorRespuesta, "description": "SAGA_NO_EXISTE"}},
)
async def obtener_reserva(saga_id: str):
    """Estado de la saga y su saga log."""
    raise no_implementado()
