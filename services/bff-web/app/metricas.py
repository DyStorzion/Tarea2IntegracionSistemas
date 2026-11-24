"""Métricas Prometheus del BFF (D-19). Prometheus las lee en /metrics/ (observability/prometheus.yml)."""
from prometheus_client import Counter, Histogram

CONSULTAS = Counter(
    "bff_consultas_fuente_total",
    "Consultas del BFF a cada fuente, por resultado (OK, NO_EXISTE, ERROR, TIMEOUT)",
    ["fuente", "resultado"],
)
LATENCIA = Histogram(
    "bff_latencia_fuente_segundos",
    "Tiempo que tarda cada fuente en responder (o en agotar su timeout)",
    ["fuente"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0),
)
RESPUESTAS = Counter(
    "bff_respuestas_total",
    "Respuestas de GET /mis-reservas por resultado (COMPLETA, DEGRADADA, NO_EXISTE, ERROR_FUENTE)",
    ["resultado"],
)
