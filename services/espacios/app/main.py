"""Servicio Espacios: reserva y libera un puesto o sala por franja.

Las rutas definen el contrato (ver app/contrato.py). Responden 501 hasta implementarse.
"""

import logging
import os
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from prometheus_client import make_asgi_app

from app.contrato import (
    CodigoError,
    DisponibilidadOut,
    ErrorRespuesta,
    LiberacionOut,
    ReservaEspacioIn,
    ReservaEspacioOut,
)

SERVICE_NAME = "espacios"
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="Servicio Espacios", version="0.2.0")
app.mount("/metrics", make_asgi_app())


def no_implementado() -> HTTPException:
    return HTTPException(
        status_code=501,
        detail={"codigo": CodigoError.NO_IMPLEMENTADO, "mensaje": "Definido en el contrato, pendiente de implementación"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/espacios", response_model=DisponibilidadOut)
async def listar_espacios(fecha: date = Query(description="Día a consultar (AAAA-MM-DD)")):
    """Lista los espacios y sus bloques libres en una fecha.

    Expuesto por el gateway como `GET /api/espacios?fecha=...`. No depende de Acceso,
    por lo que sirve para mostrar que el sistema sigue respondiendo cuando Acceso falla.
    """
    raise no_implementado()


@app.post(
    "/reservas-espacio",
    response_model=ReservaEspacioOut,
    status_code=201,
    responses={
        200: {"model": ReservaEspacioOut, "description": "Repetición con el mismo saga_id: devuelve la reserva existente"},
        404: {"model": ErrorRespuesta, "description": "ESPACIO_NO_EXISTE"},
        409: {"model": ErrorRespuesta, "description": "FRANJA_OCUPADA (otra saga tiene el bloque) o SAGA_ANULADA"},
    },
)
async def reservar(body: ReservaEspacioIn):
    """Paso 1 de la Saga. Reserva el bloque y devuelve el precio a cobrar.

    Idempotente por `saga_id`. La regla "un bloque, un cliente" se garantiza con un índice
    único (espacio_id, fecha, bloque) sobre las reservas en estado RESERVADA.
    """
    raise no_implementado()


@app.post("/reservas-espacio/{saga_id}/liberar", response_model=LiberacionOut)
async def liberar(saga_id: str):
    """Compensación del paso 1. Siempre responde 200.

    - Reserva existente: queda LIBERADA (si ya lo estaba, no hace nada).
    - Sin reserva para ese saga_id: registra la saga como ANULADA.
    """
    raise no_implementado()


@app.get(
    "/reservas-espacio/{saga_id}",
    response_model=ReservaEspacioOut,
    responses={404: {"model": ErrorRespuesta, "description": "RESERVA_NO_EXISTE"}},
)
async def obtener(saga_id: str):
    """Consulta usada por el BFF."""
    raise no_implementado()
