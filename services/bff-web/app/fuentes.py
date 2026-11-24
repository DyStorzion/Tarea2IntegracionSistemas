"""Consulta a una fuente de datos y clasificación de su resultado.

Ninguna excepción de red sale de aquí: cada consulta termina en un `Resultado` que el
endpoint sabe interpretar.
"""
from dataclasses import dataclass
from enum import Enum

import httpx
from pydantic import BaseModel, ValidationError


class Resultado(str, Enum):
    OK = "OK"  # 200 con un cuerpo válido
    NO_EXISTE = "NO_EXISTE"  # 404 con el código de "no existe" de esa fuente
    ERROR = "ERROR"  # conexión rechazada, 5xx, 501, 404 de otra causa, cuerpo inválido
    TIMEOUT = "TIMEOUT"  # no respondió dentro del plazo


@dataclass
class Consulta:
    resultado: Resultado
    datos: BaseModel | None = None

    @property
    def fallo(self) -> bool:
        return self.resultado in (Resultado.ERROR, Resultado.TIMEOUT)


def _codigo_de_error(respuesta: httpx.Response) -> str | None:
    """Código del formato de error común {"detail": {"codigo": ...}} (D-36), si lo trae."""
    try:
        detalle = respuesta.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detalle.get("codigo") if isinstance(detalle, dict) else None


async def consultar(
    cliente: httpx.AsyncClient, ruta: str, codigo_no_existe: str, modelo: type[BaseModel]
) -> Consulta:
    try:
        respuesta = await cliente.get(ruta)
    except httpx.TimeoutException:
        return Consulta(Resultado.TIMEOUT)
    except httpx.HTTPError:
        return Consulta(Resultado.ERROR)

    if respuesta.status_code == 200:
        try:
            return Consulta(Resultado.OK, modelo.model_validate(respuesta.json()))
        except (ValueError, ValidationError):
            return Consulta(Resultado.ERROR)
    # Un 404 solo significa "no existe" si trae el código esperado; uno sin él (p. ej. una
    # ruta inexistente) es un fallo, no una reserva ausente.
    if respuesta.status_code == 404 and _codigo_de_error(respuesta) == codigo_no_existe:
        return Consulta(Resultado.NO_EXISTE)
    return Consulta(Resultado.ERROR)
