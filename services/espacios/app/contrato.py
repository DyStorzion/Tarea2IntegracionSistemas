"""Contrato de la API del servicio Espacios (modelos de entrada y salida).

Convenciones comunes a todos los servicios:
- Rutas en kebab-case; campos JSON en snake_case; valores de enumeraciones en MAYÚSCULAS.
- Franja = `fecha` (AAAA-MM-DD) + `bloque` (hora de inicio, 8 a 19; cada bloque dura una hora).
- Montos en pesos chilenos, enteros.
- Errores: {"detail": {"codigo": "...", "mensaje": "..."}}.
- Pasos y compensaciones de la Saga son idempotentes por `saga_id`:
  repetir un paso devuelve 200 con el mismo resultado; repetir una compensación no hace nada.
- Una compensación que llega antes que su paso registra la saga como ANULADA, y un paso posterior
  con ese `saga_id` responde 409 SAGA_ANULADA (evita, p. ej., reservar después de haber liberado).
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

BLOQUE_MIN = 8
BLOQUE_MAX = 19


# ------------------------------------------------------------------ Errores
class CodigoError(str, Enum):
    ESPACIO_NO_EXISTE = "ESPACIO_NO_EXISTE"
    FRANJA_OCUPADA = "FRANJA_OCUPADA"
    FRANJA_PASADA = "FRANJA_PASADA"
    SAGA_ANULADA = "SAGA_ANULADA"
    RESERVA_NO_EXISTE = "RESERVA_NO_EXISTE"
    NO_IMPLEMENTADO = "NO_IMPLEMENTADO"


class Error(BaseModel):
    codigo: str = Field(examples=["FRANJA_OCUPADA"])
    mensaje: str = Field(examples=["SALA-A ya está reservada el 2026-11-20 en el bloque 9"])


class ErrorRespuesta(BaseModel):
    detail: Error


# ------------------------------------------------------------------ Enumeraciones
class TipoEspacio(str, Enum):
    PUESTO = "PUESTO"
    SALA = "SALA"


class EstadoReservaEspacio(str, Enum):
    RESERVADA = "RESERVADA"
    LIBERADA = "LIBERADA"


class EstadoLiberacion(str, Enum):
    LIBERADA = "LIBERADA"  # la reserva existía y quedó (o ya estaba) liberada
    ANULADA = "ANULADA"  # no existía reserva para ese saga_id: se registra la anulación


# ------------------------------------------------------------------ Disponibilidad
class EspacioDisponible(BaseModel):
    espacio_id: str = Field(examples=["SALA-A"])
    nombre: str = Field(examples=["Sala de reuniones A"])
    tipo: TipoEspacio
    precio: int = Field(description="Precio de un bloque, en pesos", examples=[15000])
    bloques_disponibles: list[int] = Field(examples=[[8, 10, 11, 15]])


class DisponibilidadOut(BaseModel):
    fecha: date
    espacios: list[EspacioDisponible]


# ------------------------------------------------------------------ Paso 1 de la Saga
class ReservaEspacioIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "saga_id": "3f6c2a9e-8d1b-4c1e-9a57-2b0f6f1d7c42",
                    "cliente_id": "cliente-demo",
                    "espacio_id": "SALA-A",
                    "fecha": "2026-11-20",
                    "bloque": 9,
                }
            ]
        }
    )

    saga_id: str
    cliente_id: str
    espacio_id: str
    fecha: date
    bloque: int = Field(ge=BLOQUE_MIN, le=BLOQUE_MAX, description="Hora de inicio; el bloque cubre [bloque:00, bloque+1:00)")


class ReservaEspacioOut(BaseModel):
    saga_id: str
    cliente_id: str
    espacio_id: str
    fecha: date
    bloque: int
    precio: int = Field(description="Precio que el orquestador debe cobrar, en pesos")
    estado: EstadoReservaEspacio
    actualizada_en: datetime


# ------------------------------------------------------------------ Compensación del paso 1
class LiberacionOut(BaseModel):
    saga_id: str
    estado: EstadoLiberacion
