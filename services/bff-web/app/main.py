"""BFF Web: compone en una sola respuesta datos de varios servicios para el cliente web.

No contiene lógica de negocio: solo agrega y adapta respuestas.
Las rutas de abajo son una PROPUESTA de contrato. Responden 501 hasta implementarse.
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

SERVICE_NAME = "bff-web"
RESERVAS_URL = os.getenv("RESERVAS_URL", "http://reservas:8000")
ESPACIOS_URL = os.getenv("ESPACIOS_URL", "http://espacios:8000")
PAGOS_URL = os.getenv("PAGOS_URL", "http://pagos:8000")
ACCESO_URL = os.getenv("ACCESO_URL", "http://acceso:8000")

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {SERVICE_NAME} %(levelname)s %(message)s")
log = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="BFF Web", version="0.1.0")
app.mount("/metrics", make_asgi_app())


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/mis-reservas/{saga_id}")
async def mi_reserva(saga_id: str):
    """Agrega espacio (Espacios) + pago (Pagos) + QR (Acceso).

    Si Acceso no responde, devuelve igual la respuesta con "qr": "no disponible".
    """
    raise HTTPException(status_code=501, detail="No implementado")
