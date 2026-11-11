"""Contrato de la API del servicio Acceso (simulador del controlador externo de puerta con QR).

Convenciones comunes a todos los servicios:
- Rutas en kebab-case; campos JSON en snake_case; valores de enumeraciones en MAYÚSCULAS
  (excepto los modos de inyección de fallas: ok, slow, error, down).
- Franja = `fecha` (AAAA-MM-DD) + `bloque` (hora de inicio, 8 a 19; cada bloque dura una hora).
- Errores: {"detail": {"codigo": "...", "mensaje": "..."}}.
- Pasos y compensaciones de la Saga son idempotentes por `saga_id`:
  repetir un paso devuelve 200 con el mismo resultado; repetir una compensación no hace nada.
- Una compensación que llega antes que su paso registra la saga como ANULADA, y un paso posterior
  con ese `saga_id` responde 409 SAGA_ANULADA (evita habilitar la puerta después de haberla revocado).
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

BLOQUE_MIN = 8
BLOQUE_MAX = 19


# ------------------------------------------------------------------ Errores
class CodigoError(str, Enum):
    SAGA_ANULADA = "SAGA_ANULADA"
    ACCESO_NO_EXISTE = "ACCESO_NO_EXISTE"
    ERROR_SIMULADO = "ERROR_SIMULADO"
    SERVICIO_NO_DISPONIBLE = "SERVICIO_NO_DISPONIBLE"
    NO_IMPLEMENTADO = "NO_IMPLEMENTADO"


class Error(BaseModel):
    codigo: str = Field(examples=["SAGA_ANULADA"])
    mensaje: str = Field(examples=["La saga ya fue compensada; no se habilita el acceso"])


class ErrorRespuesta(BaseModel):
    detail: Error


# ------------------------------------------------------------------ Enumeraciones
class EstadoAcceso(str, Enum):
    HABILITADO = "HABILITADO"
    REVOCADO = "REVOCADO"


class EstadoRevocacion(str, Enum):
    REVOCADO = "REVOCADO"  # el acceso existía y quedó (o ya estaba) revocado
    ANULADO = "ANULADO"  # no existía acceso para ese saga_id: se registra la anulación


class ModoChaos(str, Enum):
    OK = "ok"  # comportamiento normal
    SLOW = "slow"  # espera delay_ms antes de responder normalmente
    ERROR = "error"  # responde 500 ERROR_SIMULADO
    DOWN = "down"  # responde 503 SERVICIO_NO_DISPONIBLE


# ------------------------------------------------------------------ Paso 3 de la Saga
class AccesoIn(BaseModel):
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
    bloque: int = Field(ge=BLOQUE_MIN, le=BLOQUE_MAX)


class AccesoOut(BaseModel):
    saga_id: str
    cliente_id: str
    espacio_id: str
    fecha: date
    bloque: int
    qr: str = Field(description="Código que abre la puerta", examples=["QR-7Q2M-91XK"])
    estado: EstadoAcceso
    valido_desde: datetime
    valido_hasta: datetime
    actualizado_en: datetime


# ------------------------------------------------------------------ Compensación del paso 3
class RevocacionOut(BaseModel):
    saga_id: str
    estado: EstadoRevocacion


# ------------------------------------------------------------------ Inyección de fallas
class ChaosIn(BaseModel):
    modo: ModoChaos
    delay_ms: int = Field(default=0, ge=0, le=60000, description="Solo aplica al modo slow")


class ChaosOut(BaseModel):
    modo: ModoChaos
    delay_ms: int
