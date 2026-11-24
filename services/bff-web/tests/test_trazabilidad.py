import json
import logging

import httpx
from fastapi.testclient import TestClient

from app.logs import FormatoJson
from app.main import app
from tests.conftest import ACCESO, COBRO, ESPACIO, SAGA, responde, sin_respuesta

URL = f"/mis-reservas/{SAGA}"


def espia(cuerpo, vistos):
    def manejador(request):
        vistos.append(request.headers.get("x-request-id"))
        return httpx.Response(200, json=cuerpo)
    return manejador


def test_reenvia_x_request_id_a_las_tres_fuentes(bff):
    vistos = []
    cliente = bff(espacios=espia(ESPACIO, vistos), pagos=espia(COBRO, vistos), acceso=espia(ACCESO, vistos))
    r = cliente.get(URL, headers={"X-Request-ID": "req-123"})
    assert r.status_code == 200
    assert vistos == ["req-123"] * 3


def test_sin_x_request_id_no_envia_el_header(bff):
    vistos = []
    bff(espacios=espia(ESPACIO, vistos), pagos=espia(COBRO, vistos), acceso=espia(ACCESO, vistos)).get(URL)
    assert vistos == [None] * 3


def test_logs_json_con_request_id(bff, caplog):
    with caplog.at_level(logging.INFO, logger="bff-web"):
        bff(acceso=sin_respuesta).get(URL, headers={"X-Request-ID": "req-9"})
    campos = [r.campos for r in caplog.records if hasattr(r, "campos")]
    assert all(c["request_id"] == "req-9" for c in campos)
    acceso = next(c for c in campos if c.get("fuente") == "ACCESO")
    assert acceso["resultado"] == "TIMEOUT"
    final = next(c for c in campos if "fuente" not in c)
    assert final["resultado"] == "DEGRADADA"


def test_el_formato_de_log_es_json_valido():
    registro = logging.LogRecord("bff-web", logging.INFO, __file__, 1, "respuesta", None, None)
    registro.campos = {"request_id": "req-1", "fuente": "ACCESO"}
    linea = json.loads(FormatoJson().format(registro))
    assert {"ts", "nivel", "servicio", "evento", "request_id", "fuente"} <= set(linea)
    assert linea["servicio"] == "bff-web" and linea["evento"] == "respuesta"


def test_metricas_cuentan_resultados_y_degradaciones(bff):
    cliente = bff(acceso=sin_respuesta)
    cliente.get(URL)
    cuerpo = cliente.get("/metrics/").text
    assert 'bff_consultas_fuente_total{fuente="ACCESO",resultado="TIMEOUT"}' in cuerpo
    assert 'bff_respuestas_total{resultado="DEGRADADA"}' in cuerpo
    assert 'bff_latencia_fuente_segundos_bucket{fuente="ESPACIOS"' in cuerpo


def test_health_sigue_respondiendo():
    assert TestClient(app).get("/health").json() == {"status": "ok", "service": "bff-web"}
