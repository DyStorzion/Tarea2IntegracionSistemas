"""Contrato de la API del BFF Web.

Kong lo expone bajo /bff/web. Compone en una sola respuesta datos de Espacios, Pagos y Acceso;
no contiene reglas de negocio.

Fuentes obligatorias y opcionales (D-54): si Espacios o Pagos no responden, el BFF contesta 502
(la vista sin el espacio o sin el estado del pago podría leerse como "no hay reserva" o "no pagó").
Solo Acceso es opcional: si no responde, la vista se entrega con `degradado: true`.

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
    ESPACIOS_FALLO = "ESPACIOS_FALLO"
    PAGOS_FALLO = "PAGOS_FALLO"
    NO_IMPLEMENTADO = "NO_IMPLEMENTADO"


class Error(BaseModel):
    codigo: str = Field(examples=["RESERVA_NO_EXISTE"])
    mensaje: str = Field(examples=["No hay una reserva con ese saga_id"])


class ErrorRespuesta(BaseModel):
    detail: Error


# ------------------------------------------------------------------ Vista agregada
class FuenteDatos(str, Enum):
    ACCESO = "ACCESO"  # la única fuente que puede faltar en una respuesta 200 (D-54)


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
    espacio: EspacioVista = Field(description="Siempre presente: si Espacios no responde, el BFF contesta 502")
    pago: PagoVista | None = Field(description="null si Pagos informa que no hubo cobro; si Pagos no responde, el BFF contesta 502")
    acceso: AccesoVista
    degradado: bool = Field(description="true si Acceso no respondió y la vista está incompleta")
    no_disponibles: list[FuenteDatos] = Field(default_factory=list)
