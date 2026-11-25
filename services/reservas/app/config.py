"""Configuración del servicio Reservas, leída de variables de entorno.

Los parámetros de resiliencia (URLs, timeouts, Circuit Breaker, Bulkhead) los lee app/resiliencia.py.
"""

import os

SERVICE_NAME = "reservas"


def _url_asyncpg(url: str) -> str:
    """El Compose entrega `postgresql://...`; SQLAlchemy asíncrono necesita el driver asyncpg."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _url_asyncpg(os.getenv("DATABASE_URL", "postgresql://reservas:cowork@db-reservas:5432/reservas"))
