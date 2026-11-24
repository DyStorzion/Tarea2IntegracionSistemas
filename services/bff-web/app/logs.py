"""Logs en JSON, una línea por evento (D-19, D-37): cada línea lleva el request_id para poder
seguir una petición entre Kong, el BFF y los servicios."""
import json
import logging
import sys
from datetime import datetime, timezone

SERVICIO = "bff-web"


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        linea = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "servicio": SERVICIO,
            "evento": record.getMessage(),
        }
        linea.update(getattr(record, "campos", {}))
        return json.dumps(linea, ensure_ascii=False)


def configurar_logs() -> logging.Logger:
    logger = logging.getLogger(SERVICIO)
    if not logger.handlers:  # evita duplicar líneas si se importa dos veces
        manejador = logging.StreamHandler(sys.stdout)
        manejador.setFormatter(FormatoJson())
        logger.addHandler(manejador)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


log = configurar_logs()
