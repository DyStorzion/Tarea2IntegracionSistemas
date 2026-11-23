"""Configuración del servicio Espacios, leída de variables de entorno."""

import os

SERVICE_NAME = "espacios"


def _url_asyncpg(url: str) -> str:
    """El Compose entrega `postgresql://...`; SQLAlchemy asíncrono necesita el driver asyncpg."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _url_asyncpg(os.getenv("DATABASE_URL", "postgresql://espacios:cowork@db-espacios:5432/espacios"))
