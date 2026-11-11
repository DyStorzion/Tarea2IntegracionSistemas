"""Servicio Pagos: simulador de la pasarela de pago EXTERNA (cobra y reembolsa).

Las rutas definen el contrato (ver app/contrato.py). Responden 501 hasta implementarse.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

from app.contrato import (
    ChaosIn,
    ChaosOut,
    CobroIn,
    CobroOut,
    CodigoError,
    ErrorRespuesta,
    ReembolsoOut,
)

SERVICE_NAME = "pagos"
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="Servicio Pagos (pasarela simulada)", version="0.2.0")
app.mount("/metrics", make_asgi_app())

# Respuestas que puede producir la inyección de fallas en las rutas de negocio.
RESPUESTAS_CHAOS = {
    500: {"model": ErrorRespuesta, "description": "ERROR_SIMULADO (modo error)"},
    503: {"model": ErrorRespuesta, "description": "SERVICIO_NO_DISPONIBLE (modo down)"},
}


def no_implementado() -> HTTPException:
    return HTTPException(
        status_code=501,
        detail={"codigo": CodigoError.NO_IMPLEMENTADO, "mensaje": "Definido en el contrato, pendiente de implementación"},
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
async def cobrar(body: CobroIn):
    """Paso 2 de la Saga. Idempotente: el mismo saga_id nunca genera dos cobros."""
    raise no_implementado()


@app.post("/cobros/{saga_id}/reembolso", response_model=ReembolsoOut, responses=RESPUESTAS_CHAOS)
async def reembolsar(saga_id: str):
    """Compensación del paso 2. Responde 200 salvo falla inyectada.

    - Cobro existente: queda REEMBOLSADO (si ya lo estaba, no hace nada).
    - Sin cobro para ese saga_id: registra la saga como ANULADA.
    """
    raise no_implementado()


@app.get(
    "/cobros/{saga_id}",
    response_model=CobroOut,
    responses={404: {"model": ErrorRespuesta, "description": "COBRO_NO_EXISTE"}, **RESPUESTAS_CHAOS},
)
async def obtener(saga_id: str):
    """Consulta usada por el BFF."""
    raise no_implementado()


@app.get("/admin/chaos", response_model=ChaosOut)
async def ver_chaos():
    """Modo de falla activo."""
    raise no_implementado()


@app.post("/admin/chaos", response_model=ChaosOut)
async def chaos(body: ChaosIn):
    """Cambia el modo de falla. Afecta solo a las rutas de negocio (no a /health, /metrics ni /admin)."""
    raise no_implementado()
