"""Tablas del servicio Espacios."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Estados de una reserva. ANULADA registra una saga cuya liberación llegó antes que la
# reserva (D-39): una reserva posterior con ese saga_id se rechaza.
RESERVADA = "RESERVADA"
LIBERADA = "LIBERADA"
ANULADA = "ANULADA"

# Catálogo inicial. Se siembra al arrancar sin pisar lo que ya exista en la base.
CATALOGO = [
    {"espacio_id": "SALA-A", "nombre": "Sala de reuniones A", "tipo": "SALA", "precio": 15000},
    {"espacio_id": "SALA-B", "nombre": "Sala de reuniones B", "tipo": "SALA", "precio": 20000},
    {"espacio_id": "PUESTO-01", "nombre": "Puesto 01", "tipo": "PUESTO", "precio": 5000},
    {"espacio_id": "PUESTO-02", "nombre": "Puesto 02", "tipo": "PUESTO", "precio": 5000},
    {"espacio_id": "PUESTO-03", "nombre": "Puesto 03", "tipo": "PUESTO", "precio": 5000},
]


class Espacio(Base):
    __tablename__ = "espacios"

    espacio_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(10))
    precio: Mapped[int] = mapped_column(Integer)  # precio de un bloque, en pesos


class ReservaEspacio(Base):
    __tablename__ = "reservas_espacio"
    __table_args__ = (
        # Regla "un bloque, un cliente" (D-12): solo cuentan las reservas vigentes, así un
        # bloque liberado se puede volver a reservar.
        Index(
            "un_cliente_por_bloque",
            "espacio_id",
            "fecha",
            "bloque",
            unique=True,
            postgresql_where=text(f"estado = '{RESERVADA}'"),
        ),
    )

    # La clave primaria es el saga_id: una saga nunca reserva dos veces.
    saga_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    estado: Mapped[str] = mapped_column(String(20))
    # Nulos solo en un registro ANULADA, que no tiene datos de reserva.
    cliente_id: Mapped[str | None] = mapped_column(String(100))
    espacio_id: Mapped[str | None] = mapped_column(ForeignKey("espacios.espacio_id"))
    fecha: Mapped[date | None] = mapped_column(Date)
    bloque: Mapped[int | None] = mapped_column(Integer)
    # Copia del precio al reservar: lo cobrado no cambia si después cambia el catálogo.
    precio: Mapped[int | None] = mapped_column(Integer)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
