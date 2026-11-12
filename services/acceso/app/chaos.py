"""Inyección de fallas del simulador.

Modos (POST /admin/chaos):
- ok:    comportamiento normal.
- slow:  espera `delay_ms` y luego atiende la petición normalmente.
- error: responde 500 ERROR_SIMULADO sin ejecutar nada.
- down:  responde 503 SERVICIO_NO_DISPONIBLE sin ejecutar nada.

La falla se aplica ANTES de ejecutar la ruta: con error o down el servicio no alcanza a
hacer ningún cambio, por eso un 5xx significa "no se aplicó". Con slow, la petición sí se
aplica, pero tarde (como un controlador de puerta lento real).

Solo afecta a las rutas de negocio. El modo vive en memoria: al reiniciar vuelve a ok.
"""

import asyncio
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Gauge

from app.contrato import ChaosIn, ChaosOut, CodigoError, ModoChaos

log = logging.getLogger(__name__)

RUTAS_SIN_FALLAS = ("/health", "/metrics", "/admin", "/docs", "/openapi.json")

MODO_ACTIVO = Gauge("chaos_modo_activo", "Modo de falla activo (1) e inactivos (0)", ["modo"])
DELAY_MS = Gauge("chaos_delay_ms", "Retardo configurado para el modo slow, en milisegundos")

_estado = ChaosOut(modo=ModoChaos.OK, delay_ms=0)


def _publicar_metricas() -> None:
    for modo in ModoChaos:
        MODO_ACTIVO.labels(modo=modo.value).set(1 if modo == _estado.modo else 0)
    DELAY_MS.set(_estado.delay_ms)


def actual() -> ChaosOut:
    return _estado


def cambiar(cambio: ChaosIn) -> ChaosOut:
    global _estado
    delay = cambio.delay_ms if cambio.modo == ModoChaos.SLOW else 0
    _estado = ChaosOut(modo=cambio.modo, delay_ms=delay)
    _publicar_metricas()
    log.warning("inyección de fallas: modo=%s delay_ms=%s", _estado.modo.value, _estado.delay_ms)
    return _estado


def _error(status: int, codigo: CodigoError, mensaje: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"codigo": codigo.value, "mensaje": mensaje}})


async def middleware(request: Request, call_next):
    if _estado.modo == ModoChaos.OK or request.url.path.startswith(RUTAS_SIN_FALLAS):
        return await call_next(request)
    if _estado.modo == ModoChaos.SLOW:
        # Se lee el cuerpo antes de esperar: si el cliente se va por timeout durante la espera,
        # la petición se procesa igual (tarde), como en un controlador lento real. Sin esto, el
        # servidor detecta la desconexión al leer el cuerpo y descarta la petición.
        await request.body()
        await asyncio.sleep(_estado.delay_ms / 1000)
        return await call_next(request)
    if _estado.modo == ModoChaos.ERROR:
        return _error(500, CodigoError.ERROR_SIMULADO, "Falla inyectada: modo error")
    return _error(503, CodigoError.SERVICIO_NO_DISPONIBLE, "Falla inyectada: modo down")


_publicar_metricas()
