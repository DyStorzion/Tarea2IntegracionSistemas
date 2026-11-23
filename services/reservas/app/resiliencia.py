"""Capa de resiliencia: única salida del orquestador hacia Espacios, Pagos y Acceso.

El orquestador no usa httpx directamente. Llama a `paso()` o `compensacion()` y recibe un
`Resultado` que dice qué pasó (OK, ERROR, TIMEOUT o RECHAZADO) y si quedó la duda de que la
dependencia haya aplicado la operación (`incierto`). Ninguna de las dos lanza excepciones por
fallas de red: el orquestador decide solo con el `Resultado`.

Uso desde main.py:

    @asynccontextmanager
    async def lifespan(app):
        await resiliencia.iniciar()
        yield
        await resiliencia.cerrar()

    r = await resiliencia.paso("pagos", "POST", "/cobros", json={...}, request_id=request_id)
    if r.resultado == ResultadoPaso.OK:
        ...
    elif r.incierto:
        ...  # no se sabe si se cobró: compensar también este paso

Versión actual: cada llamada se hace una vez, con timeout, sobre un cliente HTTP compartido.
Circuit Breaker, Bulkhead y retry se agregan sin cambiar esta interfaz.
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.contrato import ResultadoPaso

log = logging.getLogger("reservas.resiliencia")

DEPENDENCIAS = ("espacios", "pagos", "acceso")
URLS = {
    "espacios": os.getenv("ESPACIOS_URL", "http://espacios:8000"),
    "pagos": os.getenv("PAGOS_URL", "http://pagos:8000"),
    "acceso": os.getenv("ACCESO_URL", "http://acceso:8000"),
}

POOL_CONEXIONES = int(os.getenv("POOL_CONEXIONES", "20"))
TIMEOUT_CONEXION_S = float(os.getenv("TIMEOUT_CONEXION_S", "0.5"))
TIMEOUT_PASO_S = {
    "espacios": float(os.getenv("TIMEOUT_ESPACIOS_S", "1")),
    "pagos": float(os.getenv("TIMEOUT_PAGOS_S", "2")),
    "acceso": float(os.getenv("TIMEOUT_ACCESO_S", "1.5")),
}
TIMEOUT_COMPENSACION_S = float(os.getenv("TIMEOUT_COMPENSACION_S", "5"))

# Valores de `Resultado.detalle` cuando la dependencia no respondió o no se la llamó.
# Si respondió con error, `detalle` es el `codigo` de ese error (p. ej. FRANJA_OCUPADA).
CIRCUITO_ABIERTO = "CIRCUITO_ABIERTO"  # no se llamó: circuito de Acceso abierto
BULKHEAD_LLENO = "BULKHEAD_LLENO"  # no se llamó: sin cupo para llamadas a Acceso
POOL_AGOTADO = "POOL_AGOTADO"  # no se llamó: no hubo conexión libre en el pool compartido a tiempo
CONEXION_RECHAZADA = "CONEXION_RECHAZADA"  # la petición no salió: nadie escucha en ese puerto
TIMEOUT_CONEXION = "TIMEOUT_CONEXION"  # la petición no salió: no se pudo conectar a tiempo (también un contenedor detenido, cuyo nombre no se resuelve)
TIMEOUT_RESPUESTA = "TIMEOUT_RESPUESTA"  # la petición salió y no llegó respuesta a tiempo
CONEXION_CORTADA = "CONEXION_CORTADA"  # la petición salió y la conexión se cortó sin respuesta


@dataclass(frozen=True)
class Resultado:
    """Qué pasó con una llamada. Los campos coinciden con los de `Paso` del contrato."""

    resultado: ResultadoPaso
    codigo_http: int | None  # None si la dependencia no respondió
    cuerpo: Any  # JSON de la respuesta (p. ej. `precio` de Espacios); None si no respondió o no era JSON
    detalle: str | None  # None si salió bien
    incierto: bool  # True si no se sabe si la dependencia aplicó la operación
    intentos: int
    inicio: datetime  # momento del primer intento (UTC)
    duracion_ms: int  # duración total, contando todos los intentos


_cliente: httpx.AsyncClient | None = None


async def iniciar() -> None:
    """Crea el cliente HTTP compartido por las tres dependencias. Va en el lifespan de main.py."""
    global _cliente
    if _cliente is None:
        _cliente = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=POOL_CONEXIONES, max_keepalive_connections=POOL_CONEXIONES)
        )
        log.info("cliente HTTP compartido creado (pool de %d conexiones)", POOL_CONEXIONES)


async def cerrar() -> None:
    """Cierra el cliente HTTP compartido. Va en el lifespan de main.py, al apagar."""
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
        _cliente = None


def acceso_disponible() -> bool:
    """False si el circuito de Acceso está abierto: la saga se puede rechazar antes de empezar.

    Mientras no exista el Circuit Breaker, siempre es True.
    """
    return True


async def paso(
    dependencia: str, metodo: str, ruta: str, json: Any = None, request_id: str | None = None
) -> Resultado:
    """Llamada de un paso de la saga (reservar, cobrar, habilitar), con el timeout de esa dependencia."""
    _validar(dependencia)
    return await _llamar(dependencia, metodo, ruta, json, request_id, TIMEOUT_PASO_S[dependencia])


async def compensacion(
    dependencia: str, metodo: str, ruta: str, json: Any = None, request_id: str | None = None
) -> Resultado:
    """Llamada de una compensación (liberar, reembolsar, revocar), con un timeout más holgado."""
    _validar(dependencia)
    return await _llamar(dependencia, metodo, ruta, json, request_id, TIMEOUT_COMPENSACION_S)


def _validar(dependencia: str) -> None:
    if dependencia not in DEPENDENCIAS:
        raise ValueError(f"Dependencia desconocida: {dependencia!r} (válidas: {', '.join(DEPENDENCIAS)})")
    if _cliente is None:
        raise RuntimeError("Falta llamar a resiliencia.iniciar() en el lifespan de main.py")


async def _llamar(
    dependencia: str, metodo: str, ruta: str, json: Any, request_id: str | None, timeout_s: float
) -> Resultado:
    inicio = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    try:
        respuesta = await _cliente.request(
            metodo,
            URLS[dependencia] + ruta,
            json=json,
            headers={"X-Request-ID": request_id} if request_id else None,
            # El timeout de conexión es el mismo para todas; `pool` es la espera por una conexión libre.
            timeout=httpx.Timeout(timeout_s, connect=TIMEOUT_CONEXION_S),
        )
    except httpx.RequestError as e:
        resultado, detalle, incierto = _clasificar_falla(e)
        codigo_http = cuerpo = None
    else:
        codigo_http = respuesta.status_code
        cuerpo = _json(respuesta)
        if respuesta.is_success:
            resultado, detalle = ResultadoPaso.OK, None
        else:
            resultado, detalle = ResultadoPaso.ERROR, _codigo_error(cuerpo, codigo_http)
        incierto = False

    r = Resultado(
        resultado=resultado,
        codigo_http=codigo_http,
        cuerpo=cuerpo,
        detalle=detalle,
        incierto=incierto,
        intentos=1,
        inicio=inicio,
        duracion_ms=round((time.perf_counter() - t0) * 1000),
    )
    if r.resultado != ResultadoPaso.OK:
        log.log(
            logging.WARNING if r.incierto else logging.INFO,
            "%s %s %s -> %s %s http=%s incierto=%s %dms request_id=%s",
            dependencia, metodo, ruta, r.resultado.value, r.detalle, r.codigo_http, r.incierto, r.duracion_ms, request_id,
        )
    return r


def _clasificar_falla(e: httpx.RequestError) -> tuple[ResultadoPaso, str, bool]:
    """(resultado, detalle, incierto) de una llamada que no recibió respuesta.

    Es incierta solo si la petición alcanzó a salir: la dependencia pudo haberla aplicado.
    El orden importa: los timeouts de pool y de conexión son subclases de TimeoutException.
    """
    if isinstance(e, httpx.PoolTimeout):
        return ResultadoPaso.TIMEOUT, POOL_AGOTADO, False
    if isinstance(e, httpx.ConnectTimeout):
        return ResultadoPaso.TIMEOUT, TIMEOUT_CONEXION, False
    if isinstance(e, httpx.ConnectError):
        return ResultadoPaso.ERROR, CONEXION_RECHAZADA, False
    if isinstance(e, httpx.TimeoutException):  # lectura o escritura: la petición ya salió
        return ResultadoPaso.TIMEOUT, TIMEOUT_RESPUESTA, True
    # Conexión cortada a mitad de camino y cualquier otro caso: ante la duda, incierto
    # (compensar de más es inofensivo porque las compensaciones son idempotentes).
    return ResultadoPaso.ERROR, CONEXION_CORTADA, True


def _codigo_error(cuerpo: Any, codigo_http: int) -> str:
    """El `codigo` de un error con el formato común {"detail": {"codigo", "mensaje"}}.

    Si la respuesta no trae ese formato (p. ej. un 500 no controlado), devuelve HTTP_<código>.
    """
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("detail"), dict):
        codigo = cuerpo["detail"].get("codigo")
        if isinstance(codigo, str):
            return codigo
    return f"HTTP_{codigo_http}"


def _json(respuesta: httpx.Response) -> Any:
    try:
        return respuesta.json()
    except ValueError:
        return None
