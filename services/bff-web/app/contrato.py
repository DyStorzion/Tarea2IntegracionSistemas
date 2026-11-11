"""Contrato de la API del BFF Web.

Kong lo expone bajo /bff/web. Compone en una sola respuesta datos de Espacios, Pagos y Acceso;
no contiene reglas de negocio.

Convenciones comunes a todos los servicios:
- Rutas en kebab-case; campos JSON en snake_case; valores de enumeraciones en MAYÚSCULAS.
- Errores: {"detail": {"codigo": "...", "mensaje": "..."}}.
"""

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

QR_NO_DISPONIBLE = "no disponible"


# ------------------------------------------------------------------ Errores
class CodigoError(str, Enum):
    RESERVA_NO_EXISTE = "RESERVA_NO_EXISTE"
    NO_IMPLEMENTADO = "NO_IMPLEMENTADO"


class Error(BaseModel):
    codigo: str = Field(examples=["RESERVA_NO_EXISTE"])
    mensaje: str = Field(examples=["No hay una reserva con ese saga_id"])


class ErrorRespuesta(BaseModel):
    detail: Error


# ------------------------------------------------------------------ Vista agregada
class FuenteDatos(str, Enum):
    ESPACIOS = "ESPACIOS"
    PAGOS = "PAGOS"
    ACCESO = "ACCESO"


class EspacioVista(BaseModel):
    espacio_id: str
    fecha: date
    bloque: int
    estado: str = Field(description="Estado informado por Espacios (RESERVADA, LIBERADA)")


class PagoVista(BaseModel):
    monto: int
    estado: str = Field(description="Estado informado por Pagos (COBRADO, REEMBOLSADO)")


class AccesoVista(BaseModel):
    qr: str | None = Field(description=f'QR de la puerta; "{QR_NO_DISPONIBLE}" si Acceso no respondió; null si no se habilitó')
    estado: str | None = Field(default=None, description="Estado informado por Acceso (HABILITADO, REVOCADO)")


class MiReservaOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "saga_id": "3f6c2a9e-8d1b-4c1e-9a57-2b0f6f1d7c42",
                    "espacio": {"espacio_id": "SALA-A", "fecha": "2026-11-20", "bloque": 9, "estado": "RESERVADA"},
                    "pago": {"monto": 15000, "estado": "COBRADO"},
                    "acceso": {"qr": QR_NO_DISPONIBLE, "estado": None},
                    "degradado": True,
                    "no_disponibles": ["ACCESO"],
                }
            ]
        }
    )

    saga_id: str
    espacio: EspacioVista | None = Field(description="null si Espacios no respondió")
    pago: PagoVista | None = Field(description="null si no hubo cobro o si Pagos no respondió")
    acceso: AccesoVista
    degradado: bool = Field(description="true si alguna fuente no respondió y la vista está incompleta")
    no_disponibles: list[FuenteDatos] = Field(default_factory=list)
