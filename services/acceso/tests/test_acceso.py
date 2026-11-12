"""Comportamiento de Acceso según su contrato (docs/api/acceso.json)."""

import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from conftest import BASE_URL


def acceso(saga_id: str, fecha: str = "2026-11-20", bloque: int = 9) -> dict:
    return {"saga_id": saga_id, "cliente_id": "cliente-pruebas", "espacio_id": "SALA-A", "fecha": fecha, "bloque": bloque}


# ------------------------------------------------------------------ Paso 3: habilitar
def test_habilitar_responde_201_con_qr(cliente, saga_id):
    r = cliente.post("/accesos", json=acceso(saga_id))
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["saga_id"] == saga_id
    assert cuerpo["estado"] == "HABILITADO"
    assert re.fullmatch(r"QR-[0-9A-F]{4}-[0-9A-F]{4}", cuerpo["qr"])


def test_qr_valido_solo_durante_el_bloque_en_hora_local(cliente, saga_id):
    """En noviembre Chile continental está en UTC-3: el bloque 9 es de 09:00 a 10:00 local."""
    cuerpo = cliente.post("/accesos", json=acceso(saga_id, fecha="2026-11-20", bloque=9)).json()
    assert cuerpo["valido_desde"] == "2026-11-20T09:00:00-03:00"
    assert cuerpo["valido_hasta"] == "2026-11-20T10:00:00-03:00"


def test_repetir_habilitacion_no_genera_otro_qr(cliente, saga_id):
    primero = cliente.post("/accesos", json=acceso(saga_id))
    repetido = cliente.post("/accesos", json=acceso(saga_id))
    assert (primero.status_code, repetido.status_code) == (201, 200)
    assert repetido.json()["qr"] == primero.json()["qr"]


def test_habilitaciones_simultaneas_con_mismo_saga_id_generan_un_solo_qr(saga_id):
    def enviar(_):
        return httpx.post(f"{BASE_URL}/accesos", json=acceso(saga_id), timeout=10)

    with ThreadPoolExecutor(max_workers=10) as pool:
        respuestas = list(pool.map(enviar, range(10)))

    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [200] * 9 + [201]
    assert len({r.json()["qr"] for r in respuestas}) == 1


def test_bloque_fuera_de_horario_responde_422(cliente, saga_id):
    assert cliente.post("/accesos", json=acceso(saga_id, bloque=20)).status_code == 422
    assert cliente.post("/accesos", json=acceso(saga_id, bloque=7)).status_code == 422


# ------------------------------------------------------------------ Consulta
def test_consultar_acceso(cliente, saga_id):
    qr = cliente.post("/accesos", json=acceso(saga_id)).json()["qr"]
    r = cliente.get(f"/accesos/{saga_id}")
    assert r.status_code == 200
    assert r.json()["qr"] == qr
    assert r.json()["estado"] == "HABILITADO"


def test_consultar_acceso_inexistente_responde_404(cliente, saga_id):
    r = cliente.get(f"/accesos/{saga_id}")
    assert r.status_code == 404
    assert r.json()["detail"]["codigo"] == "ACCESO_NO_EXISTE"


# ------------------------------------------------------------------ Compensación: revocar
def test_revocar_un_acceso(cliente, saga_id):
    cliente.post("/accesos", json=acceso(saga_id))
    r = cliente.post(f"/accesos/{saga_id}/revocar")
    assert r.status_code == 200
    assert r.json() == {"saga_id": saga_id, "estado": "REVOCADO"}
    assert cliente.get(f"/accesos/{saga_id}").json()["estado"] == "REVOCADO"


def test_revocacion_repetida_no_tiene_efecto(cliente, saga_id):
    cliente.post("/accesos", json=acceso(saga_id))
    primero = cliente.post(f"/accesos/{saga_id}/revocar")
    repetido = cliente.post(f"/accesos/{saga_id}/revocar")
    assert primero.json() == repetido.json() == {"saga_id": saga_id, "estado": "REVOCADO"}


def test_revocar_antes_de_habilitar_anula_la_saga(cliente, saga_id):
    """La habilitación hizo timeout, el orquestador compensa y la habilitación llega tarde: no debe abrir la puerta."""
    r = cliente.post(f"/accesos/{saga_id}/revocar")
    assert r.json() == {"saga_id": saga_id, "estado": "ANULADO"}

    tardia = cliente.post("/accesos", json=acceso(saga_id))
    assert tardia.status_code == 409
    assert tardia.json()["detail"]["codigo"] == "SAGA_ANULADA"
    assert cliente.get(f"/accesos/{saga_id}").status_code == 404


def test_habilitacion_repetida_tras_revocar_no_reabre_la_puerta(cliente, saga_id):
    cliente.post("/accesos", json=acceso(saga_id))
    cliente.post(f"/accesos/{saga_id}/revocar")
    r = cliente.post("/accesos", json=acceso(saga_id))
    assert r.status_code == 200
    assert r.json()["estado"] == "REVOCADO"


# ------------------------------------------------------------------ Inyección de fallas
def test_modo_error_responde_500_sin_habilitar(cliente, saga_id):
    cliente.post("/admin/chaos", json={"modo": "error"})
    r = cliente.post("/accesos", json=acceso(saga_id))
    assert r.status_code == 500
    assert r.json()["detail"]["codigo"] == "ERROR_SIMULADO"

    cliente.post("/admin/chaos", json={"modo": "ok"})
    assert cliente.get(f"/accesos/{saga_id}").status_code == 404


def test_modo_down_responde_503_sin_habilitar(cliente, saga_id):
    cliente.post("/admin/chaos", json={"modo": "down"})
    r = cliente.post("/accesos", json=acceso(saga_id))
    assert r.status_code == 503
    assert r.json()["detail"]["codigo"] == "SERVICIO_NO_DISPONIBLE"

    cliente.post("/admin/chaos", json={"modo": "ok"})
    assert cliente.get(f"/accesos/{saga_id}").status_code == 404


def test_modo_slow_retrasa_pero_habilita(cliente, saga_id):
    cliente.post("/admin/chaos", json={"modo": "slow", "delay_ms": 400})
    inicio = time.perf_counter()
    r = cliente.post("/accesos", json=acceso(saga_id))
    assert time.perf_counter() - inicio >= 0.4
    assert r.status_code == 201


def test_modo_slow_habilita_aunque_el_cliente_abandone(cliente, saga_id):
    """Resultado incierto: el cliente se rinde por timeout, pero el controlador habilita igual (tarde)."""
    cliente.post("/admin/chaos", json={"modo": "slow", "delay_ms": 600})
    try:
        httpx.post(f"{BASE_URL}/accesos", json=acceso(saga_id), timeout=0.2)
        raise AssertionError("se esperaba un timeout del cliente")
    except httpx.TimeoutException:
        pass
    cliente.post("/admin/chaos", json={"modo": "ok"})
    time.sleep(0.8)
    assert cliente.get(f"/accesos/{saga_id}").json()["estado"] == "HABILITADO"


def test_fallas_no_afectan_health_ni_admin(cliente):
    cliente.post("/admin/chaos", json={"modo": "down"})
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/admin/chaos").json() == {"modo": "down", "delay_ms": 0}


def test_delay_solo_se_guarda_en_modo_slow(cliente):
    r = cliente.post("/admin/chaos", json={"modo": "error", "delay_ms": 3000})
    assert r.json() == {"modo": "error", "delay_ms": 0}
