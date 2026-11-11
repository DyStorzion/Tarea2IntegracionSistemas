"""Comportamiento de Pagos según su contrato (docs/api/pagos.json)."""

import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from conftest import BASE_URL

MONTO = 15000


def cobro(saga_id: str, monto: int = MONTO) -> dict:
    return {"saga_id": saga_id, "cliente_id": "cliente-pruebas", "monto": monto}


# ------------------------------------------------------------------ Paso 2: cobrar
def test_cobro_nuevo_responde_201(cliente, saga_id):
    r = cliente.post("/cobros", json=cobro(saga_id))
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["saga_id"] == saga_id
    assert cuerpo["estado"] == "COBRADO"
    assert cuerpo["monto"] == MONTO
    assert cuerpo["cobro_id"].startswith("COB-")


def test_repetir_cobro_no_cobra_dos_veces(cliente, saga_id):
    primero = cliente.post("/cobros", json=cobro(saga_id))
    repetido = cliente.post("/cobros", json=cobro(saga_id))
    assert (primero.status_code, repetido.status_code) == (201, 200)
    assert repetido.json()["cobro_id"] == primero.json()["cobro_id"]


def test_cobros_simultaneos_con_mismo_saga_id_generan_un_solo_cobro(saga_id):
    def enviar(_):
        return httpx.post(f"{BASE_URL}/cobros", json=cobro(saga_id), timeout=10)

    with ThreadPoolExecutor(max_workers=10) as pool:
        respuestas = list(pool.map(enviar, range(10)))

    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [200] * 9 + [201]
    assert len({r.json()["cobro_id"] for r in respuestas}) == 1


def test_monto_sobre_el_maximo_es_rechazado(cliente, saga_id):
    r = cliente.post("/cobros", json=cobro(saga_id, monto=10_000_000))
    assert r.status_code == 402
    assert r.json()["detail"]["codigo"] == "PAGO_RECHAZADO"


def test_monto_invalido_responde_422(cliente, saga_id):
    assert cliente.post("/cobros", json=cobro(saga_id, monto=0)).status_code == 422


# ------------------------------------------------------------------ Consulta
def test_consultar_cobro(cliente, saga_id):
    cliente.post("/cobros", json=cobro(saga_id))
    r = cliente.get(f"/cobros/{saga_id}")
    assert r.status_code == 200
    assert r.json()["estado"] == "COBRADO"


def test_consultar_cobro_inexistente_responde_404(cliente, saga_id):
    r = cliente.get(f"/cobros/{saga_id}")
    assert r.status_code == 404
    assert r.json()["detail"]["codigo"] == "COBRO_NO_EXISTE"


# ------------------------------------------------------------------ Compensación: reembolsar
def test_reembolsar_un_cobro(cliente, saga_id):
    cliente.post("/cobros", json=cobro(saga_id))
    r = cliente.post(f"/cobros/{saga_id}/reembolso")
    assert r.status_code == 200
    assert r.json() == {"saga_id": saga_id, "estado": "REEMBOLSADO"}
    assert cliente.get(f"/cobros/{saga_id}").json()["estado"] == "REEMBOLSADO"


def test_reembolso_repetido_no_tiene_efecto(cliente, saga_id):
    cliente.post("/cobros", json=cobro(saga_id))
    primero = cliente.post(f"/cobros/{saga_id}/reembolso")
    repetido = cliente.post(f"/cobros/{saga_id}/reembolso")
    assert primero.json() == repetido.json() == {"saga_id": saga_id, "estado": "REEMBOLSADO"}


def test_reembolso_antes_del_cobro_anula_la_saga(cliente, saga_id):
    """El cobro hizo timeout, el orquestador compensa y el cobro llega tarde: no debe cobrarse."""
    r = cliente.post(f"/cobros/{saga_id}/reembolso")
    assert r.json() == {"saga_id": saga_id, "estado": "ANULADO"}

    tardio = cliente.post("/cobros", json=cobro(saga_id))
    assert tardio.status_code == 409
    assert tardio.json()["detail"]["codigo"] == "SAGA_ANULADA"
    assert cliente.get(f"/cobros/{saga_id}").status_code == 404


def test_cobro_repetido_tras_reembolso_no_vuelve_a_cobrar(cliente, saga_id):
    cliente.post("/cobros", json=cobro(saga_id))
    cliente.post(f"/cobros/{saga_id}/reembolso")
    r = cliente.post("/cobros", json=cobro(saga_id))
    assert r.status_code == 200
    assert r.json()["estado"] == "REEMBOLSADO"


# ------------------------------------------------------------------ Inyección de fallas
def test_modo_error_responde_500_sin_cobrar(cliente, saga_id):
    cliente.post("/admin/chaos", json={"modo": "error"})
    r = cliente.post("/cobros", json=cobro(saga_id))
    assert r.status_code == 500
    assert r.json()["detail"]["codigo"] == "ERROR_SIMULADO"

    cliente.post("/admin/chaos", json={"modo": "ok"})
    assert cliente.get(f"/cobros/{saga_id}").status_code == 404


def test_modo_down_responde_503_sin_cobrar(cliente, saga_id):
    cliente.post("/admin/chaos", json={"modo": "down"})
    r = cliente.post("/cobros", json=cobro(saga_id))
    assert r.status_code == 503
    assert r.json()["detail"]["codigo"] == "SERVICIO_NO_DISPONIBLE"

    cliente.post("/admin/chaos", json={"modo": "ok"})
    assert cliente.get(f"/cobros/{saga_id}").status_code == 404


def test_modo_slow_retrasa_pero_cobra(cliente, saga_id):
    cliente.post("/admin/chaos", json={"modo": "slow", "delay_ms": 400})
    inicio = time.perf_counter()
    r = cliente.post("/cobros", json=cobro(saga_id))
    assert time.perf_counter() - inicio >= 0.4
    assert r.status_code == 201


def test_modo_slow_aplica_el_cobro_aunque_el_cliente_abandone(cliente, saga_id):
    """Resultado incierto: el cliente se rinde por timeout, pero la pasarela cobra igual (tarde)."""
    cliente.post("/admin/chaos", json={"modo": "slow", "delay_ms": 600})
    try:
        httpx.post(f"{BASE_URL}/cobros", json=cobro(saga_id), timeout=0.2)
        raise AssertionError("se esperaba un timeout del cliente")
    except httpx.TimeoutException:
        pass
    cliente.post("/admin/chaos", json={"modo": "ok"})
    time.sleep(0.8)
    assert cliente.get(f"/cobros/{saga_id}").json()["estado"] == "COBRADO"


def test_fallas_no_afectan_health_ni_admin(cliente):
    cliente.post("/admin/chaos", json={"modo": "down"})
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/admin/chaos").json() == {"modo": "down", "delay_ms": 0}


def test_delay_solo_se_guarda_en_modo_slow(cliente):
    r = cliente.post("/admin/chaos", json={"modo": "error", "delay_ms": 3000})
    assert r.json() == {"modo": "error", "delay_ms": 0}
