import asyncio
import time

import httpx

from tests.conftest import ACCESO, COBRO, ESPACIO, SAGA, conexion_rechazada, falla_http, responde, sin_respuesta

URL = f"/mis-reservas/{SAGA}"


def codigo(r):
    return r.json()["detail"]["codigo"]


def test_camino_feliz(bff):
    r = bff().get(URL)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["saga_id"] == SAGA
    assert cuerpo["espacio"] == {"espacio_id": "SALA-A", "fecha": "2026-11-20", "bloque": 9, "estado": "RESERVADA"}
    assert cuerpo["pago"] == {"monto": 15000, "estado": "COBRADO"}
    assert cuerpo["acceso"] == {"qr": "QR-7Q2M-91XK", "estado": "HABILITADO"}
    assert cuerpo["degradado"] is False
    assert cuerpo["no_disponibles"] == []


# ---------------------------------------------------------- Acceso: degradación elegante
def test_acceso_lento_degrada(bff):
    r = bff(acceso=sin_respuesta).get(URL)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["acceso"] == {"qr": "no disponible", "estado": None}
    assert cuerpo["degradado"] is True
    assert cuerpo["no_disponibles"] == ["ACCESO"]
    assert cuerpo["espacio"]["estado"] == "RESERVADA" and cuerpo["pago"]["estado"] == "COBRADO"


def test_acceso_caido_degrada(bff):
    r = bff(acceso=conexion_rechazada).get(URL)
    assert r.status_code == 200 and r.json()["acceso"]["qr"] == "no disponible"


def test_acceso_con_error_degrada(bff):
    r = bff(acceso=falla_http(500, "ERROR_SIMULADO")).get(URL)
    assert r.status_code == 200 and r.json()["degradado"] is True


def test_acceso_no_habilitado_no_es_degradacion(bff):
    r = bff(acceso=falla_http(404, "ACCESO_NO_EXISTE")).get(URL)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["acceso"] == {"qr": None, "estado": None}
    assert cuerpo["degradado"] is False


# ---------------------------------------------------------- Pagos y Espacios: 502 / 404
def test_sin_cobro_devuelve_pago_nulo(bff):
    r = bff(pagos=falla_http(404, "COBRO_NO_EXISTE")).get(URL)
    assert r.status_code == 200 and r.json()["pago"] is None


def test_reserva_inexistente_es_404(bff):
    r = bff(espacios=falla_http(404, "RESERVA_NO_EXISTE")).get(URL)
    assert r.status_code == 404 and codigo(r) == "RESERVA_NO_EXISTE"


def test_espacios_lento_es_502(bff):
    r = bff(espacios=sin_respuesta).get(URL)
    assert r.status_code == 502 and codigo(r) == "ESPACIOS_FALLO"


def test_pagos_con_error_es_502(bff):
    r = bff(pagos=falla_http(500, "ERROR_SIMULADO")).get(URL)
    assert r.status_code == 502 and codigo(r) == "PAGOS_FALLO"


def test_pagos_caido_es_502(bff):
    r = bff(pagos=conexion_rechazada).get(URL)
    assert r.status_code == 502 and codigo(r) == "PAGOS_FALLO"


def test_si_fallan_espacios_y_pagos_se_informa_espacios(bff):
    r = bff(espacios=sin_respuesta, pagos=sin_respuesta).get(URL)
    assert r.status_code == 502 and codigo(r) == "ESPACIOS_FALLO"


def test_404_sin_el_codigo_esperado_es_fallo_no_ausencia(bff):
    # p. ej. una ruta inexistente: FastAPI responde {"detail": "Not Found"}
    r = bff(espacios=lambda req: httpx.Response(404, json={"detail": "Not Found"})).get(URL)
    assert r.status_code == 502 and codigo(r) == "ESPACIOS_FALLO"


def test_servicio_no_implementado_es_fallo(bff):
    r = bff(pagos=falla_http(501, "NO_IMPLEMENTADO")).get(URL)
    assert r.status_code == 502 and codigo(r) == "PAGOS_FALLO"


def test_cuerpo_invalido_es_fallo(bff):
    r = bff(espacios=responde({"saga_id": SAGA})).get(URL)  # faltan campos
    assert r.status_code == 502 and codigo(r) == "ESPACIOS_FALLO"


# ---------------------------------------------------------- Paralelismo
def test_las_fuentes_se_consultan_en_paralelo(bff):
    async def lenta(cuerpo):
        async def manejador(request):
            await asyncio.sleep(0.3)
            return httpx.Response(200, json=cuerpo)
        return manejador

    espacios, pagos, acceso = (
        asyncio.run(lenta(c)) for c in (ESPACIO, COBRO, ACCESO)
    )
    t0 = time.perf_counter()
    r = bff(espacios=espacios, pagos=pagos, acceso=acceso).get(URL)
    duracion = time.perf_counter() - t0
    assert r.status_code == 200
    assert duracion < 0.7, f"tardó {duracion:.2f} s: las consultas no van en paralelo"
