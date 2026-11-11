"""BFF Web (D-23).

Backend-for-frontend del cliente web: compone en una sola respuesta datos de
varios servicios. No contiene reglas de negocio ni orquesta la saga. La autenticación ya la hizo Kong.
"""
import os

from fastapi import FastAPI

app = FastAPI(title="BFF Web", version="0.1.0")

# URLs de los servicios internos (inyectadas por docker-compose)
ESPACIOS_URL = os.environ.get("ESPACIOS_URL", "http://espacios:8000")
PAGOS_URL = os.environ.get("PAGOS_URL", "http://pagos:8000")
ACCESO_URL = os.environ.get("ACCESO_URL", "http://acceso:8000")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "bff-web"}
