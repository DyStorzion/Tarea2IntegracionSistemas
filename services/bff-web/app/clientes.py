"""Clientes HTTP hacia las tres fuentes: uno por dependencia, cada uno con su timeout y su pool.

Con un pool por dependencia, una fuente lenta (p. ej. Acceso) solo puede agotar sus propias
conexiones: Espacios y Pagos siguen respondiendo (aislamiento tipo bulkhead).
"""
from dataclasses import dataclass

import httpx

from app import config


@dataclass
class Clientes:
    espacios: httpx.AsyncClient
    pagos: httpx.AsyncClient
    acceso: httpx.AsyncClient

    async def cerrar(self) -> None:
        for cliente in (self.espacios, self.pagos, self.acceso):
            await cliente.aclose()


def _cliente(base_url: str, timeout_respuesta_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(timeout_respuesta_s, connect=config.TIMEOUT_CONEXION_S),
        limits=httpx.Limits(max_connections=config.MAX_CONEXIONES_POR_FUENTE),
    )


def crear_clientes() -> Clientes:
    return Clientes(
        espacios=_cliente(config.ESPACIOS_URL, config.TIMEOUT_ESPACIOS_S),
        pagos=_cliente(config.PAGOS_URL, config.TIMEOUT_PAGOS_S),
        acceso=_cliente(config.ACCESO_URL, config.TIMEOUT_ACCESO_S),
    )
