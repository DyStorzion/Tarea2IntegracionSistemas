"""Pruebas unitarias del módulo de resiliencia (app/resiliencia.py).

No necesitan los demás servicios: las dependencias se simulan con httpx.MockTransport, el reloj
del Circuit Breaker es falso y las esperas entre reintentos no duermen. Se ejecutan dentro del
contenedor:

    docker compose exec reservas pytest -q -p no:cacheprovider tests
"""

import asyncio

import httpx
import pytest
from prometheus_client import REGISTRY

from app import resiliencia as r
from app.contrato import ResultadoPaso as RP


# ------------------------------------------------------------------ Utilidades
class Reloj:
    """Reloj falso para el Circuit Breaker: el tiempo solo avanza cuando la prueba lo pide."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


class Dependencia:
    """Dependencia simulada: responde según una lista de respuestas o excepciones y cuenta las llamadas.

    El último elemento de la lista se repite para las llamadas siguientes.
    """

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.peticiones: list[httpx.Request] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion)
        respuesta = self.respuestas[min(len(self.peticiones), len(self.respuestas)) - 1]
        if isinstance(respuesta, type) and issubclass(respuesta, Exception):
            raise respuesta("simulado", request=peticion)
        # Una respuesta nueva por llamada: httpx no está pensado para reutilizar el mismo objeto.
        return httpx.Response(respuesta.status_code, headers=respuesta.headers, content=respuesta.content)

    @property
    def llamadas(self) -> int:
        return len(self.peticiones)


def respuesta(status: int, codigo: str | None = None, **cuerpo) -> httpx.Response:
    if codigo is not None:
        return httpx.Response(status, json={"detail": {"codigo": codigo, "mensaje": "simulado"}})
    return httpx.Response(status, json=cuerpo)


def ejecutar(manejador, escenario):
    """Corre `escenario()` con el cliente compartido apuntando a `manejador` en vez de la red.

    Con `manejador=None`, el escenario crea el cliente (cuando el manejador necesita el event loop).
    """

    async def principal():
        if manejador is not None:
            r._cliente = httpx.AsyncClient(transport=httpx.MockTransport(manejador))
        try:
            return await escenario()
        finally:
            await r.cerrar()

    return asyncio.run(principal())


def llamar(manejador, *llamadas):
    """Ejecuta en orden varias llamadas (funciones sin argumentos que devuelven una corrutina)."""

    async def escenario():
        return [await c() for c in llamadas]

    return ejecutar(manejador, escenario)


def paso_acceso():
    return r.paso("acceso", "POST", "/accesos", json={"saga_id": "s"})


@pytest.fixture
def reloj():
    return Reloj()


@pytest.fixture
def esperas(monkeypatch, reloj):
    """Circuito y Bulkhead nuevos con los valores acordados, resiliencia activada y sin esperas reales.

    Devuelve la lista de esperas que se habrían hecho entre reintentos.
    """
    anotadas: list[float] = []

    async def dormir(segundos: float) -> None:
        anotadas.append(segundos)

    monkeypatch.setattr(r, "ACTIVADA", True)
    monkeypatch.setattr(r, "RETRY_PASOS_INTENTOS", 2)
    monkeypatch.setattr(r, "RETRY_COMPENSACION_INTENTOS", 3)
    monkeypatch.setattr(r, "RETRY_COMPENSACION_ESPERA_S", 0.2)
    monkeypatch.setattr(
        r, "_circuitos",
        {"acceso": r.CircuitBreaker("acceso", ventana=10, minimo=5, umbral=0.5, espera_s=10, reloj=reloj)},
    )
    monkeypatch.setattr(r, "_bulkheads", {"acceso": r.Bulkhead("acceso", cupos=5)})
    monkeypatch.setattr(r, "_dormir", dormir)
    return anotadas


def circuito() -> r.CircuitBreaker:
    return r._circuitos["acceso"]


# ------------------------------------------------------------------ Clasificación de resultados
def test_respuesta_2xx_es_ok_y_trae_el_cuerpo(esperas):
    dep = Dependencia(respuesta(201, precio=15000))
    [res] = llamar(dep, lambda: r.paso("espacios", "POST", "/reservas-espacio", json={}))
    assert (res.resultado, res.codigo_http, res.detalle, res.incierto, res.intentos) == (RP.OK, 201, None, False, 1)
    assert res.cuerpo == {"precio": 15000}


def test_error_de_negocio_trae_su_codigo_y_no_se_reintenta(esperas):
    dep = Dependencia(respuesta(409, "FRANJA_OCUPADA"))
    [res] = llamar(dep, lambda: r.paso("espacios", "POST", "/reservas-espacio", json={}))
    assert (res.resultado, res.codigo_http, res.detalle, res.incierto) == (RP.ERROR, 409, "FRANJA_OCUPADA", False)
    assert dep.llamadas == 1


def test_error_sin_el_formato_comun_usa_el_codigo_http(esperas):
    dep = Dependencia(httpx.Response(500, text="Internal Server Error"))
    [res] = llamar(dep, lambda: r.paso("pagos", "POST", "/cobros", json={}))
    assert (res.resultado, res.detalle, res.cuerpo) == (RP.ERROR, "HTTP_500", None)


@pytest.mark.parametrize(
    "excepcion, resultado, detalle, incierto, llamadas",
    [
        # La petición no salió: no es incierto. Solo la conexión rechazada es un error rápido y se reintenta.
        (httpx.ConnectError, RP.ERROR, r.CONEXION_RECHAZADA, False, 2),
        (httpx.ConnectTimeout, RP.TIMEOUT, r.TIMEOUT_CONEXION, False, 1),
        (httpx.PoolTimeout, RP.TIMEOUT, r.POOL_AGOTADO, False, 1),
        # La petición salió: no se sabe si la dependencia la aplicó.
        (httpx.ReadTimeout, RP.TIMEOUT, r.TIMEOUT_RESPUESTA, True, 1),
        (httpx.WriteTimeout, RP.TIMEOUT, r.TIMEOUT_RESPUESTA, True, 1),
        (httpx.RemoteProtocolError, RP.ERROR, r.CONEXION_CORTADA, True, 1),
        (httpx.ReadError, RP.ERROR, r.CONEXION_CORTADA, True, 1),
    ],
)
def test_fallas_de_red_se_clasifican_sin_lanzar_excepciones(esperas, excepcion, resultado, detalle, incierto, llamadas):
    dep = Dependencia(excepcion)
    [res] = llamar(dep, lambda: r.paso("pagos", "POST", "/cobros", json={}))
    assert (res.resultado, res.detalle, res.incierto, res.codigo_http, res.cuerpo) == (resultado, detalle, incierto, None, None)
    assert dep.llamadas == llamadas == res.intentos


def test_reenvia_el_request_id(esperas):
    dep = Dependencia(respuesta(200))
    llamar(
        dep,
        lambda: r.paso("pagos", "GET", "/cobros/s", request_id="req-123"),
        lambda: r.paso("pagos", "GET", "/cobros/s"),
    )
    assert dep.peticiones[0].headers["X-Request-ID"] == "req-123"
    assert "X-Request-ID" not in dep.peticiones[1].headers


def test_errores_de_programacion_si_lanzan(esperas):
    with pytest.raises(RuntimeError):
        asyncio.run(r.paso("pagos", "GET", "/cobros/s"))  # sin iniciar()
    with pytest.raises(ValueError):
        llamar(Dependencia(respuesta(200)), lambda: r.paso("pago", "GET", "/x"))


# ------------------------------------------------------------------ Reintentos de los pasos
def test_paso_se_reintenta_ante_5xx_y_puede_salir_bien(esperas):
    dep = Dependencia(respuesta(503, "SERVICIO_NO_DISPONIBLE"), respuesta(201))
    [res] = llamar(dep, lambda: r.paso("pagos", "POST", "/cobros", json={}))
    assert (res.resultado, res.intentos, res.incierto) == (RP.OK, 2, False)
    assert esperas == []  # los pasos reintentan sin esperar


def test_paso_hace_como_maximo_dos_intentos(esperas):
    dep = Dependencia(respuesta(500, "ERROR_SIMULADO"))
    [res] = llamar(dep, lambda: r.paso("pagos", "POST", "/cobros", json={}))
    assert (res.resultado, res.detalle, res.intentos) == (RP.ERROR, "ERROR_SIMULADO", 2)
    assert dep.llamadas == 2


# ------------------------------------------------------------------ Compensaciones
def test_compensacion_reintenta_timeouts_con_esperas_crecientes(esperas):
    dep = Dependencia(httpx.ReadTimeout)
    [res] = llamar(dep, lambda: r.compensacion("acceso", "POST", "/accesos/s/revocar"))
    assert (res.resultado, res.detalle, res.intentos, res.incierto) == (RP.TIMEOUT, r.TIMEOUT_RESPUESTA, 3, True)
    assert dep.llamadas == 3
    assert len(esperas) == 2
    assert 0.2 <= esperas[0] <= 0.3 and 0.4 <= esperas[1] <= 0.6  # 0,2 y 0,4 s más hasta la mitad al azar


def test_compensacion_que_sale_bien_al_segundo_intento_no_es_incierta(esperas):
    dep = Dependencia(httpx.ReadTimeout, respuesta(200, estado="REVOCADO"))
    [res] = llamar(dep, lambda: r.compensacion("acceso", "POST", "/accesos/s/revocar"))
    assert (res.resultado, res.intentos, res.incierto, res.cuerpo) == (RP.OK, 2, False, {"estado": "REVOCADO"})


def test_compensacion_no_reintenta_un_4xx(esperas):
    dep = Dependencia(respuesta(404))
    [res] = llamar(dep, lambda: r.compensacion("pagos", "POST", "/cobros/s/reembolso"))
    assert (res.resultado, res.intentos) == (RP.ERROR, 1)


def test_la_duda_de_un_intento_anterior_se_mantiene(esperas):
    dep = Dependencia(httpx.ReadTimeout, respuesta(500, "ERROR_SIMULADO"))
    [res] = llamar(dep, lambda: r.compensacion("pagos", "POST", "/cobros/s/reembolso"))
    assert (res.resultado, res.detalle, res.incierto) == (RP.ERROR, "ERROR_SIMULADO", True)


def test_compensacion_no_pasa_por_el_circuito_ni_el_bulkhead(esperas):
    registrar(circuito(), *[True] * 5)  # circuito abierto
    r._bulkheads["acceso"].en_uso = 5  # Bulkhead lleno
    dep = Dependencia(respuesta(200, estado="REVOCADO"))
    pasos, compensa = llamar(dep, paso_acceso, lambda: r.compensacion("acceso", "POST", "/accesos/s/revocar"))
    assert pasos.detalle == r.CIRCUITO_ABIERTO
    assert compensa.resultado == RP.OK and dep.llamadas == 1


# ------------------------------------------------------------------ Circuit Breaker (unidad)
def nuevo_circuito(reloj) -> r.CircuitBreaker:
    return r.CircuitBreaker("acceso", ventana=10, minimo=5, umbral=0.5, espera_s=10, reloj=reloj)


def registrar(cb: r.CircuitBreaker, *fallos: bool) -> None:
    for fallo in fallos:
        cb.registrar(fallo, cb.permitir())


def test_circuito_no_abre_con_menos_del_minimo_de_llamadas(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, True, True, True, True)
    assert cb.estado == r.CERRADO


def test_circuito_abre_con_la_mitad_de_fallos(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, False, False, False, True, True)  # 2 de 5: 40 %
    assert cb.estado == r.CERRADO
    registrar(cb, True)  # 3 de 6: 50 %
    assert cb.estado == r.ABIERTO


def test_circuito_mira_solo_las_ultimas_diez_llamadas(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, *[False] * 10, True, True, True, True)  # ventana: 6 éxitos y 4 fallos
    assert cb.estado == r.CERRADO
    registrar(cb, True)  # ventana: 5 y 5
    assert cb.estado == r.ABIERTO


def test_circuito_abierto_rechaza_durante_la_espera(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, *[True] * 5)
    assert cb.permitir() is None and not cb.disponible()
    reloj.avanzar(9)
    assert cb.permitir() is None and not cb.disponible()
    reloj.avanzar(1)
    assert cb.disponible() and cb.estado == r.SEMIABIERTO


def test_semiabierto_deja_pasar_una_sola_prueba_y_cierra_si_sale_bien(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, *[True] * 5)
    reloj.avanzar(10)
    permiso = cb.permitir()
    assert permiso == r.PRUEBA
    assert cb.permitir() is None  # la prueba sigue en curso
    cb.registrar(False, permiso)
    assert cb.estado == r.CERRADO
    registrar(cb, True, True, True, True)  # la ventana empezó de cero: 4 fallos no bastan
    assert cb.estado == r.CERRADO


def test_semiabierto_vuelve_a_abrir_si_la_prueba_falla(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, *[True] * 5)
    reloj.avanzar(10)
    cb.registrar(True, cb.permitir())
    assert cb.estado == r.ABIERTO
    reloj.avanzar(9)
    assert cb.permitir() is None  # la espera se cuenta de nuevo desde que reabrió


def test_prueba_descartada_libera_el_semiabierto(reloj):
    cb = nuevo_circuito(reloj)
    registrar(cb, *[True] * 5)
    reloj.avanzar(10)
    cb.descartar(cb.permitir())  # p. ej. el Bulkhead la rechazó
    assert cb.permitir() == r.PRUEBA


def test_resultado_de_una_llamada_anterior_a_la_apertura_no_cuenta(reloj):
    cb = nuevo_circuito(reloj)
    vieja = cb.permitir()
    registrar(cb, *[True] * 5)
    reloj.avanzar(10)
    prueba = cb.permitir()
    cb.registrar(False, vieja)  # termina tarde una llamada que empezó con el circuito cerrado
    assert cb.estado == r.SEMIABIERTO
    cb.registrar(False, prueba)
    assert cb.estado == r.CERRADO


# ------------------------------------------------------------------ Capas sobre Acceso
def test_circuito_abre_por_fallos_de_acceso_y_deja_de_llamarlo(esperas):
    dep = Dependencia(respuesta(500, "ERROR_SIMULADO"))
    res = llamar(dep, paso_acceso, paso_acceso, paso_acceso, paso_acceso)
    # Cada intento cuenta: 2 + 2 + 1 fallos abren el circuito; el reintento del tercer paso ya no llama.
    assert [x.intentos for x in res[:3]] == [2, 2, 2]
    assert (res[2].resultado, res[2].detalle) == (RP.RECHAZADO, r.CIRCUITO_ABIERTO)
    assert (res[3].resultado, res[3].detalle, res[3].intentos) == (RP.RECHAZADO, r.CIRCUITO_ABIERTO, 1)
    assert dep.llamadas == 5
    assert not r.acceso_disponible()
    assert REGISTRY.get_sample_value("circuito_estado", {"dependencia": "acceso"}) == 2


def test_timeouts_de_acceso_abren_el_circuito_sin_reintentos(esperas):
    dep = Dependencia(httpx.ReadTimeout)
    res = llamar(dep, *[paso_acceso] * 6)
    assert dep.llamadas == 5
    assert all(x.intentos == 1 for x in res)
    assert res[5].detalle == r.CIRCUITO_ABIERTO and not res[5].incierto


def test_circuito_se_recupera_tras_la_espera(esperas, reloj):
    dep = Dependencia(*[respuesta(500, "ERROR_SIMULADO")] * 5, respuesta(201))
    llamar(dep, paso_acceso, paso_acceso, paso_acceso)
    assert not r.acceso_disponible()
    reloj.avanzar(10)
    assert r.acceso_disponible()  # semiabierto: el rechazo previo deja iniciar la saga
    assert REGISTRY.get_sample_value("circuito_estado", {"dependencia": "acceso"}) == 1
    [res] = llamar(dep, paso_acceso)
    assert res.resultado == RP.OK and circuito().estado == r.CERRADO


def test_errores_de_negocio_y_pool_agotado_no_abren_el_circuito(esperas):
    dep = Dependencia(*[respuesta(409, "SAGA_ANULADA")] * 6, httpx.PoolTimeout)
    llamar(dep, *[paso_acceso] * 12)
    assert circuito().estado == r.CERRADO


def test_bulkhead_rechaza_al_instante_el_exceso_sin_reintentar_ni_contarlo_como_fallo(esperas):
    async def escenario():
        liberar = asyncio.Event()
        llamadas = 0

        async def lenta(peticion):
            nonlocal llamadas
            llamadas += 1
            if peticion.url.host == "acceso":  # Acceso tarda hasta que la prueba lo libere
                await liberar.wait()
            return respuesta(201)

        r._cliente = httpx.AsyncClient(transport=httpx.MockTransport(lenta))
        en_curso = [asyncio.create_task(paso_acceso()) for _ in range(5)]
        while llamadas < 5:
            await asyncio.sleep(0)
        assert REGISTRY.get_sample_value("bulkhead_en_uso", {"dependencia": "acceso"}) == 5
        excedidas = [await paso_acceso() for _ in range(6)]  # 6 rechazos: más que el mínimo del circuito
        espacios = await r.paso("espacios", "POST", "/reservas-espacio", json={})  # Espacios no usa el Bulkhead
        liberar.set()
        return await asyncio.gather(*en_curso), excedidas, espacios, llamadas

    terminadas, excedidas, espacios, llamadas = ejecutar(None, escenario)
    assert all(x.resultado == RP.OK for x in terminadas)
    assert all((x.resultado, x.detalle, x.intentos) == (RP.RECHAZADO, r.BULKHEAD_LLENO, 1) for x in excedidas)
    assert espacios.resultado == RP.OK
    assert llamadas == 6  # 5 a Acceso + 1 a Espacios: los rechazados no llamaron
    assert r._bulkheads["acceso"].en_uso == 0
    assert circuito().estado == r.CERRADO


def test_bulkhead_lleno_no_deja_tomada_la_prueba_del_semiabierto(esperas, reloj):
    registrar(circuito(), *[True] * 5)
    reloj.avanzar(10)
    bulkhead = r._bulkheads["acceso"]
    dep = Dependencia(respuesta(201))
    bulkhead.en_uso = 5
    [rechazada] = llamar(dep, paso_acceso)
    bulkhead.en_uso = 0
    [prueba] = llamar(dep, paso_acceso)
    assert rechazada.detalle == r.BULKHEAD_LLENO
    assert prueba.resultado == RP.OK and circuito().estado == r.CERRADO


def test_sin_resiliencia_no_hay_circuito_ni_bulkhead(esperas, monkeypatch):
    monkeypatch.setattr(r, "ACTIVADA", False)
    r._bulkheads["acceso"].en_uso = 5  # aunque estuviera lleno, no se consulta
    dep = Dependencia(respuesta(500, "ERROR_SIMULADO"))
    res = llamar(dep, *[paso_acceso] * 6)
    assert all(x.resultado == RP.ERROR and x.intentos == 2 for x in res)  # los reintentos se mantienen
    assert dep.llamadas == 12
    assert r.acceso_disponible()
    assert REGISTRY.get_sample_value("resiliencia_activada") == 0


# ------------------------------------------------------------------ Métricas
def test_cada_intento_queda_en_las_metricas(esperas):
    etiquetas = {"dependencia": "pagos", "tipo": "paso", "resultado": "ERROR", "detalle": "ERROR_SIMULADO"}
    antes = REGISTRY.get_sample_value("dependencia_llamadas_total", etiquetas) or 0
    llamar(Dependencia(respuesta(500, "ERROR_SIMULADO")), lambda: r.paso("pagos", "POST", "/cobros", json={}))
    assert REGISTRY.get_sample_value("dependencia_llamadas_total", etiquetas) == antes + 2
    assert REGISTRY.get_sample_value("dependencia_en_curso", {"dependencia": "pagos"}) == 0
