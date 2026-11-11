"""BFF Web (D-23).

Backend-for-frontend del cliente web: compone en una sola respuesta datos de
varios servicios. No contiene reglas de negocio ni orquesta la saga. La autenticación ya la hizo Kong.
"""
import os

from fastapi import FastAPI, HTTPException

from app.contrato import CodigoError, ErrorRespuesta, MiReservaOut

app = FastAPI(title="BFF Web", version="0.2.0")

# URLs de los servicios internos (inyectadas por docker-compose)
ESPACIOS_URL = os.environ.get("ESPACIOS_URL", "http://espacios:8000")
PAGOS_URL = os.environ.get("PAGOS_URL", "http://pagos:8000")
ACCESO_URL = os.environ.get("ACCESO_URL", "http://acceso:8000")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "bff-web"}


@app.get(
    "/mis-reservas/{saga_id}",
    response_model=MiReservaOut,
    responses={404: {"model": ErrorRespuesta, "description": "RESERVA_NO_EXISTE (Espacios no conoce ese saga_id)"}},
)
async def mi_reserva(saga_id: str):
    """Vista de una reserva para el cliente web (contrato; responde 501 hasta implementarse).

    Consulta en paralelo, cada una con timeout:
      GET espacios /reservas-espacio/{saga_id}, GET pagos /cobros/{saga_id}, GET acceso /accesos/{saga_id}.
    Si una fuente no responde, la vista se entrega igual con `degradado: true`;
    si la que falla es Acceso, `acceso.qr` vale "no disponible".
    """
    raise HTTPException(
        status_code=501,
        detail={"codigo": CodigoError.NO_IMPLEMENTADO, "mensaje": "Definido en el contrato, pendiente de implementación"},
    )
