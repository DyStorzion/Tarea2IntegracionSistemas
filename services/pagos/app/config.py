"""Configuración del servicio Pagos, leída de variables de entorno."""

import os

SERVICE_NAME = "pagos"


def _url_asyncpg(url: str) -> str:
    """El Compose entrega `postgresql://...`; SQLAlchemy asíncrono necesita el driver asyncpg."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _url_asyncpg(os.getenv("DATABASE_URL", "postgresql://pagos:cowork@db-pagos:5432/pagos"))

# La pasarela simulada rechaza (402 PAGO_RECHAZADO) los cobros por sobre este monto, en pesos.
MONTO_MAXIMO = int(os.getenv("PAGOS_MONTO_MAXIMO", "100000"))
