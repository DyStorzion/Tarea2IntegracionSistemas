"""Servicio Reservas: orquestador de la Saga «Reservar un espacio de cowork».

Pasos (y compensación en orden inverso):
  1. Espacios: reservar       -> liberar
  2. Pagos:    cobrar         -> reembolsar
  3. Acceso:   habilitar (QR) -> revocar

Las rutas de abajo son una PROPUESTA de contrato. Responden 501 hasta implementarse.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from prometheus_client import make_asgi_app
from pydantic import BaseModel

SERVICE_NAME = "reservas"
DATABASE_URL = os.getenv("DATABASE_URL", "")
ESPACIOS_URL = os.getenv("ESPACIOS_URL", "http://espacios:8000")
PAGOS_URL = os.getenv("PAGOS_URL", "http://pagos:8000")
ACCESO_URL = os.getenv("ACCESO_URL", "http://acceso:8000")
RESILIENCE_ENABLED = os.getenv("RESILIENCE_ENABLED", "true").lower() == "true"

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("resiliencia %s", "ACTIVADA" if RESILIENCE_ENABLED else "DESACTIVADA")
    yield


app = FastAPI(title="Servicio Reservas (orquestador de la Saga)", version="0.1.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


class ReservaIn(BaseModel):
    espacio_id: str
    franja: str
    monto: int


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "resilience_enabled": RESILIENCE_ENABLED}


@app.post("/reservas")
async def crear_reserva(
    body: ReservaIn,
    x_consumer_username: str | None = Header(default=None),  # Kong lo agrega tras validar el JWT
    idempotency_key: str | None = Header(default=None),
):
    """Inicia la Saga. Devuelve el saga_id y el estado final (CONFIRMADA / COMPENSADA / RECHAZADA)."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.get("/reservas/{saga_id}")
async def obtener_reserva(saga_id: str):
    """Estado de la saga y su historial de pasos (saga log)."""
    raise HTTPException(status_code=501, detail="No implementado")
