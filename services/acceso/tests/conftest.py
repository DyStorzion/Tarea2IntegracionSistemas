"""Pruebas de contrato del servicio Acceso.

Son de caja negra: hablan HTTP con el servicio en marcha y su Postgres real.
Se ejecutan dentro del contenedor:

    docker compose exec acceso pytest -q -p no:cacheprovider tests
"""

import os
import uuid

import httpx
import pytest

BASE_URL = os.getenv("ACCESO_URL_PRUEBAS", "http://localhost:8000")


@pytest.fixture
def cliente():
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c
        # Pase lo que pase en la prueba, el servicio queda sin fallas inyectadas.
        c.post("/admin/chaos", json={"modo": "ok"})


@pytest.fixture
def saga_id() -> str:
    """Cada prueba usa un saga_id nuevo, así no depende de datos de otras pruebas."""
    return str(uuid.uuid4())
