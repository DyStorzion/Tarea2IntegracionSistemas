"""BFF Web (D-23, D-54).

Backend-for-frontend del cliente web: compone en una sola respuesta datos de
varios servicios. No contiene reglas de negocio ni orquesta la saga. La autenticación ya la hizo Kong.
"""
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request

from app.clientes import Clientes, crear_clientes
from app.contrato import (
    QR_NO_DISPONIBLE,
    AccesoVista,
    CodigoError,
    ErrorRespuesta,
    EspacioVista,
    FuenteDatos,
    MiReservaOut,
    PagoVista,
)
from app.fuentes import Resultado, consultar


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    app.state.clientes = crear_clientes()
    yield
    await app.state.clientes.cerrar()


app = FastAPI(title="BFF Web", version="0.3.0", lifespan=ciclo_de_vida)


def obtener_clientes(request: Request) -> Clientes:
    return request.app.state.clientes


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "bff-web"}


def _error(status: int, codigo: CodigoError, mensaje: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje})


@app.get(
    "/mis-reservas/{saga_id}",
    response_model=MiReservaOut,
    responses={
        404: {"model": ErrorRespuesta, "description": "RESERVA_NO_EXISTE (Espacios no conoce ese saga_id)"},
        502: {"model": ErrorRespuesta, "description": "ESPACIOS_FALLO o PAGOS_FALLO: una fuente obligatoria no respondió"},
    },
)
async def mi_reserva(saga_id: str, clientes: Clientes = Depends(obtener_clientes)):
    """Vista de una reserva para el cliente web.

    Consulta en paralelo, cada una con su timeout:
      GET espacios /reservas-espacio/{saga_id}, GET pagos /cobros/{saga_id}, GET acceso /accesos/{saga_id}.

    Espacios y Pagos son obligatorias: si fallan, 502 (D-54). Acceso es opcional: si no
    responde, la vista se entrega con `degradado: true` y `acceso.qr` vale "no disponible".
    """
    id_ = quote(saga_id, safe="")
    # Los códigos "no existe" son los de cada servicio (cada uno define los suyos en su contrato).
    espacios, pagos, acceso = await asyncio.gather(
        consultar(clientes.espacios, f"/reservas-espacio/{id_}", "RESERVA_NO_EXISTE", EspacioVista),
        consultar(clientes.pagos, f"/cobros/{id_}", "COBRO_NO_EXISTE", PagoVista),
        consultar(clientes.acceso, f"/accesos/{id_}", "ACCESO_NO_EXISTE", AccesoVista),
    )

    if espacios.resultado is Resultado.NO_EXISTE:
        raise _error(404, CodigoError.RESERVA_NO_EXISTE, "No hay una reserva con ese saga_id")
    if espacios.fallo:
        raise _error(502, CodigoError.ESPACIOS_FALLO, "Espacios no respondió; no se puede armar la vista")
    if pagos.fallo:
        raise _error(502, CodigoError.PAGOS_FALLO, "Pagos no respondió; no se puede armar la vista")

    no_disponibles: list[FuenteDatos] = []
    if acceso.resultado is Resultado.OK:
        vista_acceso = acceso.datos
    elif acceso.resultado is Resultado.NO_EXISTE:  # la saga no llegó a habilitar la puerta
        vista_acceso = AccesoVista(qr=None, estado=None)
    else:  # degradación elegante: la vista sigue siendo útil sin el QR
        vista_acceso = AccesoVista(qr=QR_NO_DISPONIBLE, estado=None)
        no_disponibles.append(FuenteDatos.ACCESO)

    return MiReservaOut(
        saga_id=saga_id,
        espacio=espacios.datos,
        pago=pagos.datos,  # None si Pagos respondió COBRO_NO_EXISTE
        acceso=vista_acceso,
        degradado=bool(no_disponibles),
        no_disponibles=no_disponibles,
    )
