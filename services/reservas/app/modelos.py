"""Tablas del servicio Reservas: el saga log.

Una fila en `sagas` por saga y una fila en `pasos_saga` por cada paso o compensación
ejecutado, en el orden en que ocurrió. Cada paso se guarda apenas termina, así que si el
orquestador se cae a mitad de camino queda registrado hasta dónde llegó.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Saga(Base):
    __tablename__ = "sagas"
    __table_args__ = (
        # Una Idempotency-Key repetida por el mismo cliente devuelve la misma saga. Postgres
        # permite varias filas con clave nula, así que las peticiones sin clave no chocan.
        UniqueConstraint("cliente_id", "idempotency_key", name="una_saga_por_clave"),
    )

    saga_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID v4 (D-37)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    estado: Mapped[str] = mapped_column(String(30))  # EstadoSaga del contrato
    cliente_id: Mapped[str] = mapped_column(String(100))
    espacio_id: Mapped[str] = mapped_column(String(50))
    fecha: Mapped[date] = mapped_column(Date)
    bloque: Mapped[int] = mapped_column(Integer)
    precio: Mapped[int | None] = mapped_column(Integer)  # lo informa Espacios en el paso 1
    qr: Mapped[str | None] = mapped_column(String(32))  # lo informa Acceso en el paso 3
    error_codigo: Mapped[str | None] = mapped_column(String(50))
    error_mensaje: Mapped[str | None] = mapped_column(String(300))
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PasoSaga(Base):
    __tablename__ = "pasos_saga"

    saga_id: Mapped[str] = mapped_column(ForeignKey("sagas.saga_id"), primary_key=True)
    orden: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1, 2, 3... en orden de ejecución
    nombre: Mapped[str] = mapped_column(String(30))  # NombrePaso del contrato
    resultado: Mapped[str] = mapped_column(String(20))  # ResultadoPaso del contrato
    codigo_http: Mapped[int | None] = mapped_column(Integer)
    detalle: Mapped[str | None] = mapped_column(String(50))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duracion_ms: Mapped[int] = mapped_column(Integer)
