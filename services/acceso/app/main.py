"""Servicio Acceso: simulador del controlador EXTERNO de puerta con QR (la dependencia frágil).

Las rutas de abajo son una PROPUESTA de contrato. Responden 501 hasta implementarse.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app
from pydantic import BaseModel

SERVICE_NAME = "acceso"
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="Servicio Acceso (controlador de puerta simulado)", version="0.1.0")
app.mount("/metrics", make_asgi_app())


class AccesoIn(BaseModel):
    saga_id: str
    cliente_id: str
    espacio_id: str
    franja: str


class ChaosIn(BaseModel):
    mode: str  # "ok" | "slow" | "error" | "down"
    delay_ms: int = 0


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/accesos")
async def habilitar(body: AccesoIn):
    """Paso 3 de la Saga: habilita la puerta y devuelve el QR. Idempotente por saga_id."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.post("/accesos/{saga_id}/revocar")
async def revocar(saga_id: str):
    """Compensación del paso 3. Idempotente: revocar algo ya revocado no hace nada."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.get("/accesos/{saga_id}")
async def obtener(saga_id: str):
    """Consulta usada por el BFF."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.post("/admin/chaos")
async def chaos(body: ChaosIn):
    """Inyección de fallas: ok, slow (con delay_ms), error, down."""
    raise HTTPException(status_code=501, detail="No implementado")
