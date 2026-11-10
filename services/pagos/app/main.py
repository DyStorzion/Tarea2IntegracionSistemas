"""Servicio Pagos: simulador de la pasarela de pago EXTERNA (cobra y reembolsa).

Las rutas de abajo son una PROPUESTA de contrato. Responden 501 hasta implementarse.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app
from pydantic import BaseModel

SERVICE_NAME = "pagos"
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="Servicio Pagos (pasarela simulada)", version="0.1.0")
app.mount("/metrics", make_asgi_app())


class CobroIn(BaseModel):
    saga_id: str
    cliente_id: str
    monto: int  # en pesos


class ChaosIn(BaseModel):
    mode: str  # "ok" | "slow" | "error" | "down"
    delay_ms: int = 0


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/cobros")
async def cobrar(body: CobroIn):
    """Paso 2 de la Saga. Idempotente: el mismo saga_id nunca genera dos cobros."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.post("/cobros/{saga_id}/reembolso")
async def reembolsar(saga_id: str):
    """Compensación del paso 2. Idempotente: reembolsar algo ya reembolsado no hace nada."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.get("/cobros/{saga_id}")
async def obtener(saga_id: str):
    """Consulta usada por el BFF."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.post("/admin/chaos")
async def chaos(body: ChaosIn):
    """Inyección de fallas: ok, slow (con delay_ms), error, down."""
    raise HTTPException(status_code=501, detail="No implementado")
