"""Servicio Espacios: reserva y libera un puesto o sala por franja.

Las rutas definen el contrato (ver app/contrato.py). Responden 501 hasta implementarse.
"""

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, time

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from prometheus_client import Counter, make_asgi_app
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SERVICE_NAME, ZONA_HORARIA
from app.contrato import (
    CodigoError,
    DisponibilidadOut,
    ErrorRespuesta,
    LiberacionOut,
    ReservaEspacioIn,
    ReservaEspacioOut,
)
from app.db import Sesion, crear_tablas, engine, obtener_sesion
from app.modelos import ANULADA, CATALOGO, RESERVADA, Espacio, ReservaEspacio

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

OPERACIONES = Counter("espacios_operaciones_total", "Operaciones de Espacios por resultado", ["operacion", "resultado"])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await crear_tablas()
    async with Sesion() as sesion:
        # ON CONFLICT DO NOTHING: reiniciar el servicio no duplica ni pisa el catálogo.
        await sesion.execute(insert(Espacio).values(CATALOGO).on_conflict_do_nothing())
        await sesion.commit()
    yield
    await engine.dispose()


app = FastAPI(title="Servicio Espacios", version="0.2.0", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


def no_implementado() -> HTTPException:
    return HTTPException(
        status_code=501,
        detail={"codigo": CodigoError.NO_IMPLEMENTADO, "mensaje": "Definido en el contrato, pendiente de implementación"},
    )


def error(status: int, codigo: CodigoError, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})


def bloque_iniciado(fecha: date, bloque: int) -> bool:
    """True si el bloque ya empezó en hora local del cowork."""
    return datetime.combine(fecha, time(hour=bloque), tzinfo=ZONA_HORARIA) <= datetime.now(ZONA_HORARIA)


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
        422: {"model": ErrorRespuesta, "description": "FRANJA_PASADA (el bloque ya empezó, hora local del cowork)"},
    },
)
async def reservar(body: ReservaEspacioIn, response: Response, sesion: AsyncSession = Depends(obtener_sesion)):
    """Paso 1 de la Saga. Reserva el bloque y devuelve el precio a cobrar.

    Idempotente por `saga_id`: una repetición devuelve la reserva original (200), aunque
    traiga otros datos. La regla "un bloque, un cliente" se garantiza con un índice
    único (espacio_id, fecha, bloque) sobre las reservas en estado RESERVADA.
    """
    espacio = await sesion.get(Espacio, body.espacio_id)
    if espacio is None:
        OPERACIONES.labels("reservar", "espacio_no_existe").inc()
        raise error(404, CodigoError.ESPACIO_NO_EXISTE, f"No existe el espacio {body.espacio_id}")

    # Una repetición de una reserva ya hecha no se rechaza aunque el bloque haya empezado entretanto.
    if bloque_iniciado(body.fecha, body.bloque) and await sesion.get(ReservaEspacio, body.saga_id) is None:
        OPERACIONES.labels("reservar", "franja_pasada").inc()
        raise error(422, CodigoError.FRANJA_PASADA, f"El bloque {body.bloque} del {body.fecha} ya empezó")

    # ON CONFLICT solo cubre el saga_id (repetición). Si el bloque está tomado por otra saga,
    # Postgres rechaza el INSERT por el índice un_cliente_por_bloque: una sola sentencia atómica.
    insercion = (
        insert(ReservaEspacio)
        .values(
            saga_id=body.saga_id,
            estado=RESERVADA,
            cliente_id=body.cliente_id,
            espacio_id=body.espacio_id,
            fecha=body.fecha,
            bloque=body.bloque,
            precio=espacio.precio,
        )
        .on_conflict_do_nothing(index_elements=[ReservaEspacio.saga_id])
        .returning(ReservaEspacio.saga_id)
    )
    try:
        creada = (await sesion.execute(insercion)).scalar_one_or_none() is not None
        await sesion.commit()
    except IntegrityError as e:
        await sesion.rollback()
        if "un_cliente_por_bloque" not in str(e.orig):
            raise
        OPERACIONES.labels("reservar", "franja_ocupada").inc()
        log.info("franja ocupada saga_id=%s espacio=%s fecha=%s bloque=%s", body.saga_id, body.espacio_id, body.fecha, body.bloque)
        raise error(409, CodigoError.FRANJA_OCUPADA, f"{body.espacio_id} ya está reservada el {body.fecha} en el bloque {body.bloque}")

    reserva = await sesion.get(ReservaEspacio, body.saga_id)
    if reserva.estado == ANULADA:
        OPERACIONES.labels("reservar", "saga_anulada").inc()
        log.info("reserva rechazada por saga anulada saga_id=%s", body.saga_id)
        raise error(409, CodigoError.SAGA_ANULADA, "La saga ya fue compensada; no se reserva")

    OPERACIONES.labels("reservar", "reservada" if creada else "repetida").inc()
    log.info("reserva %s saga_id=%s espacio=%s fecha=%s bloque=%s", "creada" if creada else "repetida", reserva.saga_id, reserva.espacio_id, reserva.fecha, reserva.bloque)
    response.status_code = 201 if creada else 200
    return ReservaEspacioOut.model_validate(reserva, from_attributes=True)


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
