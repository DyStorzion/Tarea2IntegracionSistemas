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

    if not resiliencia.acceso_disponible():
        ...  # circuito de Acceso abierto: rechazar la saga antes de empezar

    r = await resiliencia.paso("pagos", "POST", "/cobros", json={...}, request_id=request_id)
    if r.resultado == ResultadoPaso.OK:
        ...
    elif r.incierto:
        ...  # no se sabe si se cobró: compensar también este paso

Capas de cada paso, de afuera hacia adentro:

    reintentos -> Circuit Breaker -> Bulkhead -> timeout -> llamada HTTP

- Reintentos de los pasos: solo ante errores rápidos (conexión rechazada o 5xx), nunca ante un
  timeout, un 4xx, el circuito abierto o el Bulkhead lleno.
- Circuit Breaker y Bulkhead protegen solo a Acceso.
- Las compensaciones no pasan por el Circuit Breaker ni por el Bulkhead (tienen que intentarse
  aunque el circuito esté abierto); se reintentan también ante timeouts, con esperas crecientes.

Con RESILIENCE_ENABLED=false se quitan el Circuit Breaker y el Bulkhead. Los timeouts, los
reintentos y el pool compartido se mantienen, para comparar el sistema con y sin los patrones.
"""

import asyncio
import logging
import os
import random
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from prometheus_client import Counter, Gauge, Histogram

from app.contrato import ResultadoPaso

log = logging.getLogger("reservas.resiliencia")


def _entero(nombre: str, defecto: int) -> int:
    return int(os.getenv(nombre, str(defecto)))


def _real(nombre: str, defecto: float) -> float:
    return float(os.getenv(nombre, str(defecto)))


# ------------------------------------------------------------------ Configuración
ACTIVADA = os.getenv("RESILIENCE_ENABLED", "true").lower() == "true"

DEPENDENCIAS = ("espacios", "pagos", "acceso")
URLS = {
    "espacios": os.getenv("ESPACIOS_URL", "http://espacios:8000"),
    "pagos": os.getenv("PAGOS_URL", "http://pagos:8000"),
    "acceso": os.getenv("ACCESO_URL", "http://acceso:8000"),
}

POOL_CONEXIONES = _entero("POOL_CONEXIONES", 20)
TIMEOUT_CONEXION_S = _real("TIMEOUT_CONEXION_S", 0.5)
TIMEOUT_PASO_S = {
    "espacios": _real("TIMEOUT_ESPACIOS_S", 1),
    "pagos": _real("TIMEOUT_PAGOS_S", 2),
    "acceso": _real("TIMEOUT_ACCESO_S", 1.5),
}
TIMEOUT_COMPENSACION_S = _real("TIMEOUT_COMPENSACION_S", 5)

RETRY_PASOS_INTENTOS = _entero("RETRY_PASOS_INTENTOS", 2)
RETRY_COMPENSACION_INTENTOS = _entero("RETRY_COMPENSACION_INTENTOS", 3)
RETRY_COMPENSACION_ESPERA_S = _real("RETRY_COMPENSACION_ESPERA_S", 0.2)  # la siguiente espera es el doble

CB_VENTANA = _entero("CB_VENTANA", 10)
CB_MINIMO_LLAMADAS = _entero("CB_MINIMO_LLAMADAS", 5)
CB_UMBRAL_FALLOS = _real("CB_UMBRAL_FALLOS", 0.5)
CB_ESPERA_ABIERTO_S = _real("CB_ESPERA_ABIERTO_S", 10)  # sirve también como Retry-After

BULKHEAD_ACCESO_CUPOS = _entero("BULKHEAD_ACCESO_CUPOS", 5)

# Valores de `Resultado.detalle` cuando la dependencia no respondió o no se la llamó.
# Si respondió con error, `detalle` es el `codigo` de ese error (p. ej. FRANJA_OCUPADA).
CIRCUITO_ABIERTO = "CIRCUITO_ABIERTO"  # no se llamó: circuito de Acceso abierto
BULKHEAD_LLENO = "BULKHEAD_LLENO"  # no se llamó: sin cupo para llamadas a Acceso
POOL_AGOTADO = "POOL_AGOTADO"  # no se llamó: no hubo conexión libre en el pool compartido a tiempo
CONEXION_RECHAZADA = "CONEXION_RECHAZADA"  # la petición no salió: nadie escucha en ese puerto
TIMEOUT_CONEXION = "TIMEOUT_CONEXION"  # la petición no salió: no se pudo conectar a tiempo (también un contenedor detenido, cuyo nombre no se resuelve)
TIMEOUT_RESPUESTA = "TIMEOUT_RESPUESTA"  # la petición salió y no llegó respuesta a tiempo
CONEXION_CORTADA = "CONEXION_CORTADA"  # la petición salió y la conexión se cortó sin respuesta


# ------------------------------------------------------------------ Métricas
LLAMADAS = Counter(
    "dependencia_llamadas_total",
    "Intentos de llamada a cada dependencia por resultado. Cada reintento cuenta aparte; "
    "incluye los rechazados por el Circuit Breaker o el Bulkhead, que no llegan a la dependencia",
    ["dependencia", "tipo", "resultado", "detalle"],
)
DURACION = Histogram(
    "dependencia_duracion_segundos",
    "Duración de cada intento que llegó a llamar a la dependencia (incluye la espera por una conexión libre)",
    ["dependencia", "tipo"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 7.5, 10),
)
EN_CURSO = Gauge(
    "dependencia_en_curso",
    "Llamadas HTTP en curso por dependencia, incluidas las que esperan una conexión libre del pool",
    ["dependencia"],
)
POOL = Gauge("dependencia_pool_conexiones", "Conexiones del pool HTTP compartido por las tres dependencias")
CIRCUITO_ESTADO = Gauge("circuito_estado", "Estado del Circuit Breaker: 0 cerrado, 1 semiabierto, 2 abierto", ["dependencia"])
CIRCUITO_TRANSICIONES = Counter("circuito_transiciones_total", "Cambios de estado del Circuit Breaker", ["dependencia", "hacia"])
BULKHEAD_EN_USO = Gauge("bulkhead_en_uso", "Cupos del Bulkhead ocupados por llamadas en curso", ["dependencia"])
BULKHEAD_CUPOS = Gauge("bulkhead_cupos", "Cupos configurados del Bulkhead", ["dependencia"])
RESILIENCIA_ACTIVADA = Gauge("resiliencia_activada", "1 si el Circuit Breaker y el Bulkhead están activos (RESILIENCE_ENABLED)")


# ------------------------------------------------------------------ Resultado
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
    duracion_ms: int  # duración total, contando todos los intentos y las esperas entre ellos


# ------------------------------------------------------------------ Circuit Breaker
CERRADO, SEMIABIERTO, ABIERTO = "cerrado", "semiabierto", "abierto"
_VALOR_ESTADO = {CERRADO: 0, SEMIABIERTO: 1, ABIERTO: 2}
NORMAL, PRUEBA = "normal", "prueba"  # tipos de permiso que entrega CircuitBreaker.permitir()


class CircuitBreaker:
    """Circuit Breaker por tasa de fallos en una ventana deslizante de llamadas.

    - Cerrado: deja pasar todo y guarda el resultado de las últimas `ventana` llamadas. Abre si
      fallan al menos `umbral` de ellas, siempre que haya `minimo` llamadas registradas.
    - Abierto: rechaza todo durante `espera_s`.
    - Semiabierto: deja pasar una sola llamada de prueba y rechaza las demás mientras está en
      curso. Si la prueba sale bien, cierra; si falla, vuelve a abrir.

    No usa locks: en asyncio nada se intercala entre una comprobación y su actualización.
    """

    def __init__(self, nombre: str, ventana: int, minimo: int, umbral: float, espera_s: float,
                 reloj: Callable[[], float] = time.monotonic):
        self.nombre = nombre
        self.minimo = minimo
        self.umbral = umbral
        self.espera_s = espera_s
        self._reloj = reloj
        self._ventana: deque[bool] = deque(maxlen=ventana)  # True = la llamada falló
        self._estado = CERRADO
        self._abierto_desde = 0.0
        self._prueba_en_curso = False

    @property
    def estado(self) -> str:
        """Estado visto desde afuera: abierto con la espera cumplida ya cuenta como semiabierto."""
        if self._estado == ABIERTO and self._espera_cumplida():
            return SEMIABIERTO
        return self._estado

    def disponible(self) -> bool:
        return self.estado != ABIERTO

    def permitir(self) -> str | None:
        """None si la llamada se rechaza; si no, NORMAL o PRUEBA (la llamada de prueba del semiabierto)."""
        if self._estado == ABIERTO:
            if not self._espera_cumplida():
                return None
            self._cambiar(SEMIABIERTO, f"pasaron {self.espera_s:g} s")
        if self._estado == SEMIABIERTO:
            if self._prueba_en_curso:
                return None
            self._prueba_en_curso = True
            return PRUEBA
        return NORMAL

    def registrar(self, fallo: bool, permiso: str) -> None:
        """Anota el resultado de una llamada que se hizo con `permiso`."""
        if permiso == PRUEBA:
            self._prueba_en_curso = False
            if self._estado == SEMIABIERTO:
                if fallo:
                    self._cambiar(ABIERTO, "falló la llamada de prueba")
                else:
                    self._cambiar(CERRADO, "la llamada de prueba salió bien")
            return
        if self._estado != CERRADO:
            return  # llamada que empezó antes de que el circuito abriera: ya no cuenta
        self._ventana.append(fallo)
        fallos = sum(self._ventana)
        if len(self._ventana) >= self.minimo and fallos / len(self._ventana) >= self.umbral:
            self._cambiar(ABIERTO, f"{fallos} fallos en las últimas {len(self._ventana)} llamadas")

    def descartar(self, permiso: str) -> None:
        """La llamada permitida no llegó a la dependencia: no cuenta, pero libera la prueba."""
        if permiso == PRUEBA:
            self._prueba_en_curso = False

    def _espera_cumplida(self) -> bool:
        return self._reloj() - self._abierto_desde >= self.espera_s

    def _cambiar(self, nuevo: str, motivo: str) -> None:
        anterior, self._estado = self._estado, nuevo
        if nuevo == ABIERTO:
            self._abierto_desde = self._reloj()
        if nuevo in (ABIERTO, CERRADO):
            self._ventana.clear()  # al volver a cerrar, la ventana empieza de cero
        CIRCUITO_TRANSICIONES.labels(self.nombre, nuevo).inc()
        log.warning("circuito %s: %s -> %s (%s)", self.nombre, anterior, nuevo, motivo)


# ------------------------------------------------------------------ Bulkhead
class Bulkhead:
    """Limita las llamadas simultáneas a una dependencia. Sin cupo, rechaza al instante: no espera."""

    def __init__(self, nombre: str, cupos: int):
        self.nombre = nombre
        self.cupos = cupos
        self.en_uso = 0

    def tomar(self) -> bool:
        if self.en_uso >= self.cupos:
            return False
        self.en_uso += 1
        return True

    def soltar(self) -> None:
        self.en_uso -= 1


# Circuit Breaker y Bulkhead solo sobre Acceso, la dependencia frágil.
_circuitos: dict[str, CircuitBreaker] = {
    "acceso": CircuitBreaker("acceso", CB_VENTANA, CB_MINIMO_LLAMADAS, CB_UMBRAL_FALLOS, CB_ESPERA_ABIERTO_S),
}
_bulkheads: dict[str, Bulkhead] = {"acceso": Bulkhead("acceso", BULKHEAD_ACCESO_CUPOS)}

# Los gauges se calculan al momento de leer /metrics, así muestran el estado real
# (p. ej. el paso de abierto a semiabierto, que ocurre por tiempo y no por una llamada).
RESILIENCIA_ACTIVADA.set_function(lambda: 1 if ACTIVADA else 0)
POOL.set_function(lambda: POOL_CONEXIONES)
for _dep in _circuitos:
    CIRCUITO_ESTADO.labels(_dep).set_function(lambda d=_dep: _VALOR_ESTADO[_circuitos[d].estado] if ACTIVADA else 0)
for _dep in _bulkheads:
    BULKHEAD_EN_USO.labels(_dep).set_function(lambda d=_dep: _bulkheads[d].en_uso)
    BULKHEAD_CUPOS.labels(_dep).set_function(lambda d=_dep: _bulkheads[d].cupos)


# ------------------------------------------------------------------ Interfaz
_cliente: httpx.AsyncClient | None = None
_dormir: Callable[[float], Awaitable[None]] = asyncio.sleep  # las pruebas lo reemplazan


async def iniciar() -> None:
    """Crea el cliente HTTP compartido por las tres dependencias. Va en el lifespan de main.py."""
    global _cliente
    if _cliente is None:
        _cliente = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=POOL_CONEXIONES, max_keepalive_connections=POOL_CONEXIONES)
        )
        log.info(
            "resiliencia %s · pool de %d conexiones",
            "ACTIVADA (Circuit Breaker y Bulkhead sobre Acceso)" if ACTIVADA else "DESACTIVADA (solo timeouts y reintentos)",
            POOL_CONEXIONES,
        )


async def cerrar() -> None:
    """Cierra el cliente HTTP compartido. Va en el lifespan de main.py, al apagar."""
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
        _cliente = None


def acceso_disponible() -> bool:
    """False si el circuito de Acceso está abierto: la saga se puede rechazar antes de empezar.

    En semiabierto devuelve True: la saga empieza y su paso 3 puede ser la llamada de prueba.
    """
    return not ACTIVADA or _circuitos["acceso"].disponible()


async def paso(
    dependencia: str, metodo: str, ruta: str, json: Any = None, request_id: str | None = None
) -> Resultado:
    """Llamada de un paso de la saga (reservar, cobrar, habilitar).

    Timeout de la dependencia; en Acceso, además Circuit Breaker y Bulkhead. Se reintenta
    solo ante errores rápidos: conexión rechazada o 5xx.
    """
    _validar(dependencia)
    return await _con_reintentos(
        lambda n: _intento_paso(dependencia, metodo, ruta, json, request_id, n),
        maximo=RETRY_PASOS_INTENTOS,
        reintentable=_reintentable_paso,
        espera_s=0,
    )


async def compensacion(
    dependencia: str, metodo: str, ruta: str, json: Any = None, request_id: str | None = None
) -> Resultado:
    """Llamada de una compensación (liberar, reembolsar, revocar).

    Timeout más holgado que los pasos y sin Circuit Breaker ni Bulkhead. Se reintenta ante
    cualquier falla salvo un 4xx, con esperas crecientes.
    """
    _validar(dependencia)
    return await _con_reintentos(
        lambda n: _llamar(dependencia, "compensacion", metodo, ruta, json, request_id, TIMEOUT_COMPENSACION_S, n),
        maximo=RETRY_COMPENSACION_INTENTOS,
        reintentable=_reintentable_compensacion,
        espera_s=RETRY_COMPENSACION_ESPERA_S,
    )


# ------------------------------------------------------------------ Reintentos
def _reintentable_paso(r: Resultado) -> bool:
    # Un timeout no se reintenta: la lentitud persistente la maneja el Circuit Breaker, y cada
    # reintento pagaría el timeout completo. Tampoco un 4xx, el circuito abierto ni el Bulkhead lleno.
    return r.detalle == CONEXION_RECHAZADA or (r.codigo_http is not None and r.codigo_http >= 500)


def _reintentable_compensacion(r: Resultado) -> bool:
    return r.codigo_http is None or r.codigo_http >= 500  # todo menos una respuesta 4xx


def _espera_antes_de(intento: int, base_s: float) -> float:
    """Espera antes del intento 2, 3...: base, 2·base... más hasta la mitad al azar, para que las
    sagas que fallaron juntas no reintenten todas en el mismo instante."""
    s = base_s * 2 ** (intento - 2)
    return s + random.uniform(0, s / 2)


async def _con_reintentos(
    intentar: Callable[[int], Awaitable[Resultado]],
    maximo: int,
    reintentable: Callable[[Resultado], bool],
    espera_s: float,
) -> Resultado:
    inicio = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    hechos: list[Resultado] = []
    for n in range(1, max(1, maximo) + 1):
        if n > 1 and espera_s > 0:
            await _dormir(_espera_antes_de(n, espera_s))
        r = await intentar(n)
        hechos.append(r)
        if r.resultado == ResultadoPaso.OK or not reintentable(r):
            break
    ultimo = hechos[-1]
    return replace(
        ultimo,
        intentos=len(hechos),
        inicio=inicio,
        duracion_ms=round((time.perf_counter() - t0) * 1000),
        # Si un intento anterior quedó incierto, la duda sigue aunque el último haya fallado de forma explícita.
        incierto=ultimo.resultado != ResultadoPaso.OK and any(h.incierto for h in hechos),
    )


# ------------------------------------------------------------------ Un intento de un paso
async def _intento_paso(
    dependencia: str, metodo: str, ruta: str, json: Any, request_id: str | None, n: int
) -> Resultado:
    """Circuit Breaker -> Bulkhead -> llamada con timeout."""
    circuito = _circuitos.get(dependencia) if ACTIVADA else None
    bulkhead = _bulkheads.get(dependencia) if ACTIVADA else None

    permiso = NORMAL
    if circuito is not None:
        permiso = circuito.permitir()
        if permiso is None:
            return _rechazado(dependencia, metodo, ruta, CIRCUITO_ABIERTO, request_id, n)
    if bulkhead is not None and not bulkhead.tomar():
        if circuito is not None:
            circuito.descartar(permiso)  # el rechazo del Bulkhead no dice nada de la salud de Acceso
        return _rechazado(dependencia, metodo, ruta, BULKHEAD_LLENO, request_id, n)

    try:
        r = await _llamar(dependencia, "paso", metodo, ruta, json, request_id, TIMEOUT_PASO_S[dependencia], n)
    except BaseException:
        # Cancelación o error de programación: que la llamada de prueba no quede tomada para siempre.
        if circuito is not None:
            circuito.descartar(permiso)
        raise
    finally:
        if bulkhead is not None:
            bulkhead.soltar()

    if circuito is not None:
        if r.detalle == POOL_AGOTADO:
            circuito.descartar(permiso)  # la petición no llegó a Acceso: no dice nada de su salud
        else:
            circuito.registrar(_es_fallo(r), permiso)
    return r


def _es_fallo(r: Resultado) -> bool:
    """Para el Circuit Breaker: timeouts, errores de conexión y 5xx. Un 4xx de negocio no es fallo."""
    if r.resultado == ResultadoPaso.TIMEOUT or r.detalle in (CONEXION_RECHAZADA, CONEXION_CORTADA):
        return True
    return r.codigo_http is not None and r.codigo_http >= 500


def _rechazado(dependencia: str, metodo: str, ruta: str, motivo: str, request_id: str | None, n: int) -> Resultado:
    r = Resultado(ResultadoPaso.RECHAZADO, None, None, motivo, False, 1, datetime.now(timezone.utc), 0)
    _anotar(dependencia, "paso", metodo, ruta, r, request_id, n)
    return r


# ------------------------------------------------------------------ Llamada HTTP con timeout
async def _llamar(
    dependencia: str, tipo: str, metodo: str, ruta: str, json: Any, request_id: str | None, timeout_s: float, n: int
) -> Resultado:
    inicio = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    EN_CURSO.labels(dependencia).inc()
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
    finally:
        EN_CURSO.labels(dependencia).dec()

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
    DURACION.labels(dependencia, tipo).observe(time.perf_counter() - t0)
    _anotar(dependencia, tipo, metodo, ruta, r, request_id, n)
    return r


def _anotar(dependencia: str, tipo: str, metodo: str, ruta: str, r: Resultado, request_id: str | None, n: int) -> None:
    """Métrica de cada intento y una línea de log si no salió bien."""
    LLAMADAS.labels(dependencia, tipo, r.resultado.value, r.detalle or "").inc()
    if r.resultado != ResultadoPaso.OK:
        log.log(
            logging.WARNING if r.incierto else logging.INFO,
            "%s %s %s %s intento %d -> %s %s http=%s incierto=%s %dms request_id=%s",
            tipo, dependencia, metodo, ruta, n, r.resultado.value, r.detalle, r.codigo_http, r.incierto,
            r.duracion_ms, request_id,
        )


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


def _validar(dependencia: str) -> None:
    if dependencia not in DEPENDENCIAS:
        raise ValueError(f"Dependencia desconocida: {dependencia!r} (válidas: {', '.join(DEPENDENCIAS)})")
    if _cliente is None:
        raise RuntimeError("Falta llamar a resiliencia.iniciar() en el lifespan de main.py")
