"""Orquestador de la Saga «Reservar un espacio de cowork» (D-06, D-09).

Pasos, en orden:
  1. Espacios: reservar el bloque  -> devuelve el precio
  2. Pagos:    cobrar el precio
  3. Acceso:   habilitar la puerta -> devuelve el QR

Toda llamada pasa por app/resiliencia.py (D-54): aquí solo se decide qué significa cada
resultado para la saga. El saga log se escribe a medida que avanza (D-60): la saga se
guarda EN_CURSO antes del paso 1 y cada paso apenas termina.
"""

import logging

from prometheus_client import Counter
from sqlalchemy.ext.asyncio import AsyncSession

from app import resiliencia
from app.config import SERVICE_NAME
from app.contrato import CodigoError, EstadoSaga, NombrePaso, ResultadoPaso
from app.modelos import PasoSaga, Saga

log = logging.getLogger(SERVICE_NAME)

SAGAS = Counter("saga_resultados_total", "Sagas terminadas por estado final", ["estado"])

# Rechazos de negocio del paso 1: no se aplicó nada, no hay que compensar (D-35).
RECHAZOS_PASO_1 = {
    CodigoError.ESPACIO_NO_EXISTE.value: 404,
    CodigoError.FRANJA_OCUPADA.value: 409,
    CodigoError.FRANJA_PASADA.value: 422,
}


class Ejecucion:
    """Una saga en curso: ejecuta sus pasos y los anota en el saga log."""

    def __init__(self, sesion: AsyncSession, saga: Saga, request_id: str | None):
        self.sesion = sesion
        self.saga = saga
        self.request_id = request_id
        self.orden = 0

    async def paso(self, nombre: NombrePaso, dependencia: str, ruta: str, cuerpo: dict) -> resiliencia.Resultado:
        r = await resiliencia.paso(dependencia, "POST", ruta, json=cuerpo, request_id=self.request_id)
        self.orden += 1
        self.sesion.add(
            PasoSaga(
                saga_id=self.saga.saga_id,
                orden=self.orden,
                nombre=nombre.value,
                resultado=r.resultado.value,
                codigo_http=r.codigo_http,
                detalle=r.detalle,
                inicio=r.inicio,
                duracion_ms=r.duracion_ms,
            )
        )
        await self.sesion.commit()
        log.info(
            "saga_id=%s request_id=%s paso=%s resultado=%s http=%s detalle=%s intentos=%s ms=%s",
            self.saga.saga_id, self.request_id, nombre.value, r.resultado.value, r.codigo_http, r.detalle, r.intentos, r.duracion_ms,
        )
        return r

    async def terminar(self, estado: EstadoSaga, status: int, codigo: CodigoError | None = None, mensaje: str | None = None) -> int:
        self.saga.estado = estado.value
        self.saga.error_codigo = codigo.value if codigo else None
        self.saga.error_mensaje = mensaje
        await self.sesion.commit()
        await self.sesion.refresh(self.saga)  # trae actualizada_en, que la pone la base
        SAGAS.labels(estado.value).inc()
        log.info("saga_id=%s request_id=%s estado=%s error=%s", self.saga.saga_id, self.request_id, estado.value, codigo.value if codigo else None)
        return status

    async def pendiente(self, codigo: CodigoError, r: resiliencia.Resultado, dependencia: str) -> int:
        # shortcut: todavía no se compensa; la saga queda marcada para compensar. El commit
        # siguiente agrega las compensaciones en orden inverso (D-45) y el rechazo previo (D-10).
        return await self.terminar(EstadoSaga.COMPENSACION_PENDIENTE, 502, codigo, describir(dependencia, r))


def describir(dependencia: str, r: resiliencia.Resultado) -> str:
    if r.codigo_http is not None:
        return f"{dependencia} respondió {r.codigo_http} ({r.detalle})"
    return f"{dependencia} no respondió ({r.detalle})"


async def ejecutar(sesion: AsyncSession, saga: Saga, request_id: str | None) -> int:
    """Ejecuta la saga y devuelve el código HTTP de la respuesta (D-35)."""
    e = Ejecucion(sesion, saga, request_id)

    # Paso 1: reservar el bloque en Espacios.
    r = await e.paso(
        NombrePaso.RESERVAR_ESPACIO,
        "espacios",
        "/reservas-espacio",
        {"saga_id": saga.saga_id, "cliente_id": saga.cliente_id, "espacio_id": saga.espacio_id, "fecha": saga.fecha.isoformat(), "bloque": saga.bloque},
    )
    if r.resultado != ResultadoPaso.OK:
        if r.detalle in RECHAZOS_PASO_1:
            mensaje = r.cuerpo["detail"]["mensaje"]  # el que explicó Espacios, p. ej. "SALA-A ya está reservada..."
            return await e.terminar(EstadoSaga.RECHAZADA, RECHAZOS_PASO_1[r.detalle], CodigoError(r.detalle), mensaje)
        if r.incierto:  # timeout: Espacios pudo haber reservado igual
            return await e.pendiente(CodigoError.ESPACIOS_FALLO, r, "Espacios")
        # Falla certera (D-45): no se aplicó nada, no hay nada que compensar.
        return await e.terminar(EstadoSaga.COMPENSADA, 502, CodigoError.ESPACIOS_FALLO, describir("Espacios", r))
    saga.precio = r.cuerpo["precio"]

    # Paso 2: cobrar el precio que informó Espacios (D-33).
    r = await e.paso(NombrePaso.COBRAR, "pagos", "/cobros", {"saga_id": saga.saga_id, "cliente_id": saga.cliente_id, "monto": saga.precio})
    if r.resultado != ResultadoPaso.OK:
        codigo = CodigoError.PAGO_RECHAZADO if r.detalle == CodigoError.PAGO_RECHAZADO.value else CodigoError.PAGOS_FALLO
        return await e.pendiente(codigo, r, "Pagos")

    # Paso 3: habilitar la puerta en Acceso.
    r = await e.paso(
        NombrePaso.HABILITAR_ACCESO,
        "acceso",
        "/accesos",
        {"saga_id": saga.saga_id, "cliente_id": saga.cliente_id, "espacio_id": saga.espacio_id, "fecha": saga.fecha.isoformat(), "bloque": saga.bloque},
    )
    if r.resultado != ResultadoPaso.OK:
        return await e.pendiente(CodigoError.ACCESO_FALLO, r, "Acceso")
    saga.qr = r.cuerpo["qr"]

    return await e.terminar(EstadoSaga.CONFIRMADA, 201)
