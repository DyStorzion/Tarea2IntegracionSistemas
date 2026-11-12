"""Tablas del servicio Acceso."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Estados de un acceso. ANULADO registra una saga cuya revocación llegó antes que la
# habilitación: una habilitación posterior con ese saga_id se rechaza.
HABILITADO = "HABILITADO"
REVOCADO = "REVOCADO"
ANULADO = "ANULADO"


class Acceso(Base):
    __tablename__ = "accesos"

    # La clave primaria es el saga_id: una saga nunca genera dos QR.
    saga_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    estado: Mapped[str] = mapped_column(String(20))
    # Nulos solo en un registro ANULADO, que no tiene datos de acceso.
    qr: Mapped[str | None] = mapped_column(String(32), unique=True)
    cliente_id: Mapped[str | None] = mapped_column(String(100))
    espacio_id: Mapped[str | None] = mapped_column(String(50))
    fecha: Mapped[date | None] = mapped_column(Date)
    bloque: Mapped[int | None] = mapped_column(Integer)
    valido_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valido_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
