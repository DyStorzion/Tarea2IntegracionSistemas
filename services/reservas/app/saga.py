"""Orquestador de la Saga «Reservar un espacio de cowork» (D-06, D-09).

Pasos, en orden, y su compensación:
  1. Espacios: reservar el bloque  -> liberar     (devuelve el precio)
  2. Pagos:    cobrar el precio    -> reembolsar
  3. Acceso:   habilitar la puerta -> revocar     (devuelve el QR)

Si un paso falla, se compensan en orden inverso los pasos ya aplicados. El paso que falló
se compensa solo si su resultado es incierto (D-45). Si el circuito de Acceso está abierto
antes de empezar, la saga se rechaza sin ejecutar nada (D-10).

Toda llamada pasa por app/resiliencia.py (D-54): aquí solo se decide qué significa cada
resultado para la saga. El saga log se escribe a medida que avanza (D-60, D-61).
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

# Compensación de cada paso: nombre en el saga log, dependencia y ruta.
COMPENSACIONES = {
    NombrePaso.RESERVAR_ESPACIO: (NombrePaso.LIBERAR_ESPACIO, "espacios", "/reservas-espacio/{}/liberar"),
    NombrePaso.COBRAR: (NombrePaso.REEMBOLSAR, "pagos", "/cobros/{}/reembolso"),
    NombrePaso.HABILITAR_ACCESO: (NombrePaso.REVOCAR_ACCESO, "acceso", "/accesos/{}/revocar"),
}


class Ejecucion:
    """Una saga en curso: ejecuta pasos y compensaciones y los anota en el saga log."""

    def __init__(self, sesion: AsyncSession, saga: Saga, request_id: str | None):
        self.sesion = sesion
        self.saga = saga
        self.request_id = request_id
        self.orden = 0
        self.a_compensar: list[NombrePaso] = []  # pasos aplicados (o inciertos), en orden de ejecución

    async def paso(self, nombre: NombrePaso, dependencia: str, ruta: str, cuerpo: dict) -> resiliencia.Resultado:
        r = await resiliencia.paso(dependencia, "POST", ruta, json=cuerpo, request_id=self.request_id)
        # D-45: se compensa lo que se aplicó y lo que quedó en duda; un error certero no se aplicó.
        if r.resultado == ResultadoPaso.OK or r.incierto:
            self.a_compensar.append(nombre)
        await self.anotar(nombre, r)
        return r

    async def anotar(self, nombre: NombrePaso, r: resiliencia.Resultado) -> None:
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
            "saga_id=%s request_id=%s paso=%s resultado=%s http=%s detalle=%s incierto=%s intentos=%s ms=%s",
            self.saga.saga_id, self.request_id, nombre.value, r.resultado.value, r.codigo_http, r.detalle, r.incierto, r.intentos, r.duracion_ms,
        )

    async def fallar(self, status: int, codigo: CodigoError, mensaje: str) -> int:
        """Compensa en orden inverso y cierra la saga como COMPENSADA, o COMPENSACION_PENDIENTE si alguna falló."""
        fallidas = []
        for nombre in reversed(self.a_compensar):
            compensacion, dependencia, ruta = COMPENSACIONES[nombre]
            r = await resiliencia.compensacion(dependencia, "POST", ruta.format(self.saga.saga_id), request_id=self.request_id)
            await self.anotar(compensacion, r)
            # Si falla, se siguen intentando las demás: cada una deshace un efecto distinto (D-44).
            if r.resultado != ResultadoPaso.OK:
                fallidas.append(compensacion.value)
        if fallidas:
            detalle = f"No se pudo {', '.join(fallidas)} tras reintentar. Causa original: {mensaje}"
            return await self.terminar(EstadoSaga.COMPENSACION_PENDIENTE, 502, CodigoError.COMPENSACION_FALLIDA, detalle)
        return await self.terminar(EstadoSaga.COMPENSADA, status, codigo, mensaje)

    async def terminar(self, estado: EstadoSaga, status: int, codigo: CodigoError | None = None, mensaje: str | None = None) -> int:
        self.saga.estado = estado.value
        self.saga.error_codigo = codigo.value if codigo else None
        self.saga.error_mensaje = mensaje[:300] if mensaje else None  # largo de la columna
        await self.sesion.commit()
        await self.sesion.refresh(self.saga)  # trae actualizada_en, que la pone la base
        SAGAS.labels(estado.value).inc()
        log.info("saga_id=%s request_id=%s estado=%s error=%s", self.saga.saga_id, self.request_id, estado.value, codigo.value if codigo else None)
        return status


def describir(dependencia: str, r: resiliencia.Resultado) -> str:
    if r.codigo_http is not None:
        return f"{dependencia} respondió {r.codigo_http} ({r.detalle})"
    return f"{dependencia} no respondió ({r.detalle})"


async def ejecutar(sesion: AsyncSession, saga: Saga, request_id: str | None) -> int:
    """Ejecuta la saga y devuelve el código HTTP de la respuesta (D-35)."""
    e = Ejecucion(sesion, saga, request_id)

    # Rechazo previo (D-10): con el circuito de Acceso abierto, el paso 3 fallaría seguro.
    # No se reserva ni se cobra nada; la saga queda RECHAZADA sin pasos.
    if not resiliencia.acceso_disponible():
        return await e.terminar(
            EstadoSaga.RECHAZADA, 503, CodigoError.ACCESO_NO_DISPONIBLE, "Reservas suspendidas: el control de acceso no responde"
        )

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
        return await e.fallar(502, CodigoError.ESPACIOS_FALLO, describir("Espacios", r))
    saga.precio = r.cuerpo["precio"]

    # Paso 2: cobrar el precio que informó Espacios (D-33).
    r = await e.paso(NombrePaso.COBRAR, "pagos", "/cobros", {"saga_id": saga.saga_id, "cliente_id": saga.cliente_id, "monto": saga.precio})
    if r.resultado != ResultadoPaso.OK:
        if r.detalle == CodigoError.PAGO_RECHAZADO.value:
            return await e.fallar(402, CodigoError.PAGO_RECHAZADO, r.cuerpo["detail"]["mensaje"])
        return await e.fallar(502, CodigoError.PAGOS_FALLO, describir("Pagos", r))

    # Paso 3: habilitar la puerta en Acceso (la dependencia frágil).
    r = await e.paso(
        NombrePaso.HABILITAR_ACCESO,
        "acceso",
        "/accesos",
        {"saga_id": saga.saga_id, "cliente_id": saga.cliente_id, "espacio_id": saga.espacio_id, "fecha": saga.fecha.isoformat(), "bloque": saga.bloque},
    )
    if r.resultado != ResultadoPaso.OK:
        # 503: el patrón cortó la llamada (fail-fast); 502: Acceso falló de verdad (D-35).
        if r.detalle == resiliencia.CIRCUITO_ABIERTO:
            return await e.fallar(503, CodigoError.ACCESO_NO_DISPONIBLE, "El circuito de Acceso está abierto")
        if r.detalle == resiliencia.BULKHEAD_LLENO:
            return await e.fallar(503, CodigoError.ACCESO_SATURADO, "Acceso tiene todos sus cupos ocupados")
        return await e.fallar(502, CodigoError.ACCESO_FALLO, describir("Acceso", r))
    saga.qr = r.cuerpo["qr"]

    return await e.terminar(EstadoSaga.CONFIRMADA, 201)
