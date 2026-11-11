"""Servicio Acceso: simulador del controlador EXTERNO de puerta con QR (la dependencia frágil).

Las rutas definen el contrato (ver app/contrato.py). Responden 501 hasta implementarse.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

from app.contrato import (
    AccesoIn,
    AccesoOut,
    ChaosIn,
    ChaosOut,
    CodigoError,
    ErrorRespuesta,
    RevocacionOut,
)

SERVICE_NAME = "acceso"
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="Servicio Acceso (controlador de puerta simulado)", version="0.2.0")
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
    "/accesos",
    response_model=AccesoOut,
    status_code=201,
    responses={
        200: {"model": AccesoOut, "description": "Repetición con el mismo saga_id: devuelve el acceso existente"},
        409: {"model": ErrorRespuesta, "description": "SAGA_ANULADA"},
        **RESPUESTAS_CHAOS,
    },
)
async def habilitar(body: AccesoIn):
    """Paso 3 de la Saga: habilita la puerta y devuelve el QR. Idempotente por saga_id."""
    raise no_implementado()


@app.post("/accesos/{saga_id}/revocar", response_model=RevocacionOut, responses=RESPUESTAS_CHAOS)
async def revocar(saga_id: str):
    """Compensación del paso 3. Responde 200 salvo falla inyectada.

    - Acceso existente: queda REVOCADO (si ya lo estaba, no hace nada).
    - Sin acceso para ese saga_id: registra la saga como ANULADA.
    """
    raise no_implementado()


@app.get(
    "/accesos/{saga_id}",
    response_model=AccesoOut,
    responses={404: {"model": ErrorRespuesta, "description": "ACCESO_NO_EXISTE"}, **RESPUESTAS_CHAOS},
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
