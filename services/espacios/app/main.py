"""Servicio Espacios: reserva y libera un puesto o sala por franja.

Las rutas de abajo son una PROPUESTA de contrato. Responden 501 hasta implementarse.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app
from pydantic import BaseModel

SERVICE_NAME = "espacios"
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="Servicio Espacios", version="0.1.0")
app.mount("/metrics", make_asgi_app())


class ReservaEspacioIn(BaseModel):
    saga_id: str
    espacio_id: str
    franja: str  # p. ej. "2026-11-20T09:00/2026-11-20T11:00" (formato por definir)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/espacios")
async def listar_espacios():
    """Lista espacios y su disponibilidad. Útil para mostrar que el sistema sigue respondiendo con Acceso caído."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.post("/reservas-espacio")
async def reservar(body: ReservaEspacioIn):
    """Paso 1 de la Saga. Idempotente por saga_id."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.post("/reservas-espacio/{saga_id}/liberar")
async def liberar(saga_id: str):
    """Compensación del paso 1. Idempotente: liberar algo ya liberado no hace nada."""
    raise HTTPException(status_code=501, detail="No implementado")


@app.get("/reservas-espacio/{saga_id}")
async def obtener(saga_id: str):
    """Consulta usada por el BFF."""
    raise HTTPException(status_code=501, detail="No implementado")
