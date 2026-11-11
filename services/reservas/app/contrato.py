"""Contrato de la API del servicio Reservas (orquestador de la Saga).

Es la API pública de negocio: Kong la expone como /api/reservas.

Convenciones comunes a todos los servicios:
- Rutas en kebab-case; campos JSON en snake_case; valores de enumeraciones en MAYÚSCULAS.
- Franja = `fecha` (AAAA-MM-DD) + `bloque` (hora de inicio, 8 a 19; cada bloque dura una hora).
- Montos en pesos chilenos, enteros. El precio lo define Espacios, nunca el cliente.
- El cliente se identifica con el encabezado X-Consumer-Username, que agrega Kong al validar el JWT.
- Errores de petición: {"detail": {"codigo": "...", "mensaje": "..."}}.
- El resultado de una saga (confirmada, compensada o rechazada) NO es un error de la petición:
  POST /reservas responde siempre con el modelo SagaOut, que incluye `error` cuando la saga no se confirmó.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

BLOQUE_MIN = 8
BLOQUE_MAX = 19


# ------------------------------------------------------------------ Errores
class CodigoError(str, Enum):
    # Resultado de la saga (campo `error` de SagaOut)
    ESPACIO_NO_EXISTE = "ESPACIO_NO_EXISTE"  # 404, RECHAZADA
    FRANJA_OCUPADA = "FRANJA_OCUPADA"  # 409, RECHAZADA
    PAGO_RECHAZADO = "PAGO_RECHAZADO"  # 402, COMPENSADA
    ESPACIOS_FALLO = "ESPACIOS_FALLO"  # 502, COMPENSADA
    PAGOS_FALLO = "PAGOS_FALLO"  # 502, COMPENSADA
    ACCESO_FALLO = "ACCESO_FALLO"  # 502, COMPENSADA
    ACCESO_NO_DISPONIBLE = "ACCESO_NO_DISPONIBLE"  # 503, Circuit Breaker abierto
    ACCESO_SATURADO = "ACCESO_SATURADO"  # 503, Bulkhead sin cupo
    COMPENSACION_FALLIDA = "COMPENSACION_FALLIDA"  # 502, COMPENSACION_PENDIENTE
    # Errores de petición
    SAGA_NO_EXISTE = "SAGA_NO_EXISTE"
    NO_IMPLEMENTADO = "NO_IMPLEMENTADO"


class Error(BaseModel):
    codigo: str = Field(examples=["FRANJA_OCUPADA"])
    mensaje: str = Field(examples=["SALA-A ya está reservada el 2026-11-20 en el bloque 9"])


class ErrorRespuesta(BaseModel):
    detail: Error


# ------------------------------------------------------------------ Enumeraciones
class EstadoSaga(str, Enum):
    EN_CURSO = "EN_CURSO"
    CONFIRMADA = "CONFIRMADA"  # los tres pasos quedaron firmes
    COMPENSANDO = "COMPENSANDO"
    COMPENSADA = "COMPENSADA"  # algún paso falló y los anteriores se deshicieron en orden inverso
    RECHAZADA = "RECHAZADA"  # no se ejecutó ningún paso con efecto (franja ocupada, circuito abierto...)
    COMPENSACION_PENDIENTE = "COMPENSACION_PENDIENTE"  # una compensación falló y debe reintentarse


class NombrePaso(str, Enum):
    RESERVAR_ESPACIO = "RESERVAR_ESPACIO"
    COBRAR = "COBRAR"
    HABILITAR_ACCESO = "HABILITAR_ACCESO"
    REVOCAR_ACCESO = "REVOCAR_ACCESO"
    REEMBOLSAR = "REEMBOLSAR"
    LIBERAR_ESPACIO = "LIBERAR_ESPACIO"


class ResultadoPaso(str, Enum):
    OK = "OK"
    ERROR = "ERROR"  # la dependencia respondió con error
    TIMEOUT = "TIMEOUT"  # la dependencia no respondió a tiempo
    RECHAZADO = "RECHAZADO"  # no se llamó: Circuit Breaker abierto o Bulkhead sin cupo


# ------------------------------------------------------------------ Entrada
class ReservaIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"espacio_id": "SALA-A", "fecha": "2026-11-20", "bloque": 9}]})

    espacio_id: str
    fecha: date
    bloque: int = Field(ge=BLOQUE_MIN, le=BLOQUE_MAX, description="Hora de inicio; el bloque cubre [bloque:00, bloque+1:00)")


# ------------------------------------------------------------------ Salida
class Paso(BaseModel):
    nombre: NombrePaso
    resultado: ResultadoPaso
    codigo_http: int | None = Field(default=None, description="Código que respondió la dependencia, si respondió")
    detalle: str | None = None
    inicio: datetime
    duracion_ms: int


class SagaOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "saga_id": "3f6c2a9e-8d1b-4c1e-9a57-2b0f6f1d7c42",
                    "estado": "COMPENSADA",
                    "cliente_id": "cliente-demo",
                    "espacio_id": "SALA-A",
                    "fecha": "2026-11-20",
                    "bloque": 9,
                    "precio": 15000,
                    "qr": None,
                    "error": {"codigo": "ACCESO_FALLO", "mensaje": "Acceso respondió 500"},
                    "pasos": [
                        {"nombre": "RESERVAR_ESPACIO", "resultado": "OK", "codigo_http": 201, "detalle": None, "inicio": "2026-11-11T14:00:00.010Z", "duracion_ms": 12},
                        {"nombre": "COBRAR", "resultado": "OK", "codigo_http": 201, "detalle": None, "inicio": "2026-11-11T14:00:00.025Z", "duracion_ms": 18},
                        {"nombre": "HABILITAR_ACCESO", "resultado": "ERROR", "codigo_http": 500, "detalle": "ERROR_SIMULADO", "inicio": "2026-11-11T14:00:00.045Z", "duracion_ms": 9},
                        {"nombre": "REEMBOLSAR", "resultado": "OK", "codigo_http": 200, "detalle": None, "inicio": "2026-11-11T14:00:00.056Z", "duracion_ms": 11},
                        {"nombre": "LIBERAR_ESPACIO", "resultado": "OK", "codigo_http": 200, "detalle": None, "inicio": "2026-11-11T14:00:00.069Z", "duracion_ms": 8},
                    ],
                    "creada_en": "2026-11-11T14:00:00.005Z",
                    "actualizada_en": "2026-11-11T14:00:00.078Z",
                }
            ]
        }
    )

    saga_id: str
    estado: EstadoSaga
    cliente_id: str
    espacio_id: str
    fecha: date
    bloque: int
    precio: int | None = Field(default=None, description="Lo informa Espacios en el paso 1")
    qr: str | None = Field(default=None, description="Solo si la saga quedó CONFIRMADA")
    error: Error | None = Field(default=None, description="Motivo cuando la saga no quedó CONFIRMADA")
    pasos: list[Paso] = Field(description="Saga log: pasos y compensaciones en el orden en que se ejecutaron")
    creada_en: datetime
    actualizada_en: datetime
