"""Contrato de la API del servicio Pagos (simulador de la pasarela externa).

Convenciones comunes a todos los servicios:
- Rutas en kebab-case; campos JSON en snake_case; valores de enumeraciones en MAYÚSCULAS
  (excepto los modos de inyección de fallas: ok, slow, error, down).
- Montos en pesos chilenos, enteros.
- Errores: {"detail": {"codigo": "...", "mensaje": "..."}}.
- Pasos y compensaciones de la Saga son idempotentes por `saga_id`:
  repetir un paso devuelve 200 con el mismo resultado; repetir una compensación no hace nada.
- Una compensación que llega antes que su paso registra la saga como ANULADA, y un paso posterior
  con ese `saga_id` responde 409 SAGA_ANULADA (evita cobrar después de haber reembolsado).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------ Errores
class CodigoError(str, Enum):
    PAGO_RECHAZADO = "PAGO_RECHAZADO"
    SAGA_ANULADA = "SAGA_ANULADA"
    COBRO_NO_EXISTE = "COBRO_NO_EXISTE"
    ERROR_SIMULADO = "ERROR_SIMULADO"
    SERVICIO_NO_DISPONIBLE = "SERVICIO_NO_DISPONIBLE"
    NO_IMPLEMENTADO = "NO_IMPLEMENTADO"


class Error(BaseModel):
    codigo: str = Field(examples=["PAGO_RECHAZADO"])
    mensaje: str = Field(examples=["La pasarela rechazó el cobro"])


class ErrorRespuesta(BaseModel):
    detail: Error


# ------------------------------------------------------------------ Enumeraciones
class EstadoCobro(str, Enum):
    COBRADO = "COBRADO"
    REEMBOLSADO = "REEMBOLSADO"


class EstadoReembolso(str, Enum):
    REEMBOLSADO = "REEMBOLSADO"  # el cobro existía y quedó (o ya estaba) reembolsado
    ANULADO = "ANULADO"  # no existía cobro para ese saga_id: se registra la anulación


class ModoChaos(str, Enum):
    OK = "ok"  # comportamiento normal
    SLOW = "slow"  # espera delay_ms antes de responder normalmente
    ERROR = "error"  # responde 500 ERROR_SIMULADO
    DOWN = "down"  # responde 503 SERVICIO_NO_DISPONIBLE


# ------------------------------------------------------------------ Paso 2 de la Saga
class CobroIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"saga_id": "3f6c2a9e-8d1b-4c1e-9a57-2b0f6f1d7c42", "cliente_id": "cliente-demo", "monto": 15000}
            ]
        }
    )

    saga_id: str
    cliente_id: str
    monto: int = Field(gt=0, description="Monto en pesos; lo informa Espacios al reservar")


class CobroOut(BaseModel):
    saga_id: str
    cobro_id: str = Field(description="Identificador del cobro en la pasarela")
    cliente_id: str
    monto: int
    estado: EstadoCobro
    actualizado_en: datetime


# ------------------------------------------------------------------ Compensación del paso 2
class ReembolsoOut(BaseModel):
    saga_id: str
    estado: EstadoReembolso


# ------------------------------------------------------------------ Inyección de fallas
class ChaosIn(BaseModel):
    modo: ModoChaos
    delay_ms: int = Field(default=0, ge=0, le=60000, description="Solo aplica al modo slow")


class ChaosOut(BaseModel):
    modo: ModoChaos
    delay_ms: int
