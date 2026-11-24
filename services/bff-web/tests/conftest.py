"""Pruebas del BFF sin red: las tres fuentes se simulan con httpx.MockTransport.

Ejecutar desde services/bff-web:   pip install -r requirements.txt pytest && pytest
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.clientes import Clientes
from app.main import app, obtener_clientes

SAGA = "3f6c2a9e-8d1b-4c1e-9a57-2b0f6f1d7c42"

ESPACIO = {
    "saga_id": SAGA, "cliente_id": "cliente-demo", "espacio_id": "SALA-A", "fecha": "2026-11-20",
    "bloque": 9, "precio": 15000, "estado": "RESERVADA", "actualizada_en": "2026-11-20T08:00:00Z",
}
COBRO = {
    "saga_id": SAGA, "cobro_id": "COB-1", "cliente_id": "cliente-demo", "monto": 15000,
    "estado": "COBRADO", "actualizado_en": "2026-11-20T08:00:01Z",
}
ACCESO = {
    "saga_id": SAGA, "cliente_id": "cliente-demo", "espacio_id": "SALA-A", "fecha": "2026-11-20",
    "bloque": 9, "qr": "QR-7Q2M-91XK", "estado": "HABILITADO",
    "valido_desde": "2026-11-20T08:00:00Z", "valido_hasta": "2026-11-20T10:00:00Z",
    "actualizado_en": "2026-11-20T08:00:02Z",
}


# ---- comportamientos de una fuente
def responde(cuerpo):
    return lambda r: httpx.Response(200, json=cuerpo)


def falla_http(status, codigo):
    return lambda r: httpx.Response(status, json={"detail": {"codigo": codigo, "mensaje": "simulado"}})


def sin_respuesta(r):
    raise httpx.ReadTimeout("demasiado lento", request=r)


def conexion_rechazada(r):
    raise httpx.ConnectError("conexión rechazada", request=r)


def _cliente(comportamiento):
    return httpx.AsyncClient(transport=httpx.MockTransport(comportamiento), base_url="http://fuente")


@pytest.fixture
def bff():
    """Fábrica: bff(espacios=..., pagos=..., acceso=...) devuelve un TestClient del BFF."""

    def crear(espacios=None, pagos=None, acceso=None):
        clientes = Clientes(
            espacios=_cliente(espacios or responde(ESPACIO)),
            pagos=_cliente(pagos or responde(COBRO)),
            acceso=_cliente(acceso or responde(ACCESO)),
        )
        app.dependency_overrides[obtener_clientes] = lambda: clientes
        return TestClient(app)

    yield crear
    app.dependency_overrides.clear()
