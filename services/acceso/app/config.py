"""Configuración del servicio Acceso, leída de variables de entorno."""

import os
from zoneinfo import ZoneInfo

SERVICE_NAME = "acceso"


def _url_asyncpg(url: str) -> str:
    """El Compose entrega `postgresql://...`; SQLAlchemy asíncrono necesita el driver asyncpg."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _url_asyncpg(os.getenv("DATABASE_URL", "postgresql://acceso:cowork@db-acceso:5432/acceso"))

# Zona horaria del cowork: la ventana de validez del QR se calcula en hora local.
ZONA_HORARIA = ZoneInfo(os.getenv("ACCESO_ZONA_HORARIA", "America/Santiago"))
