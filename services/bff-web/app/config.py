"""Configuración del BFF (D-48): variables de entorno con los valores acordados por defecto.

Los plazos son los mismos que usa `reservas` en sus pasos (D-40); compartir los nombres
permite cambiarlos todos con una sola variable en el .env.
"""
import os


def _decimal(nombre: str, defecto: float) -> float:
    return float(os.environ.get(nombre, defecto))


# URLs de los servicios internos (inyectadas por docker-compose)
ESPACIOS_URL = os.environ.get("ESPACIOS_URL", "http://espacios:8000")
PAGOS_URL = os.environ.get("PAGOS_URL", "http://pagos:8000")
ACCESO_URL = os.environ.get("ACCESO_URL", "http://acceso:8000")

# Timeouts en segundos: conexión y espera de la respuesta, por fuente
TIMEOUT_CONEXION_S = _decimal("TIMEOUT_CONEXION_S", 0.5)
TIMEOUT_ESPACIOS_S = _decimal("TIMEOUT_ESPACIOS_S", 1.0)
TIMEOUT_PAGOS_S = _decimal("TIMEOUT_PAGOS_S", 2.0)
TIMEOUT_ACCESO_S = _decimal("TIMEOUT_ACCESO_S", 1.5)

# Tope de conexiones simultáneas por fuente (un pool por dependencia)
MAX_CONEXIONES_POR_FUENTE = int(os.environ.get("MAX_CONEXIONES_POR_FUENTE", "20"))
