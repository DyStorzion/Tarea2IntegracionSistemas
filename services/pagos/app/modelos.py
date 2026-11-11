"""Tablas del servicio Pagos."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Estados de un cobro. ANULADO registra una saga cuyo reembolso llegó antes que el cobro:
# un cobro posterior con ese saga_id se rechaza.
COBRADO = "COBRADO"
REEMBOLSADO = "REEMBOLSADO"
ANULADO = "ANULADO"


class Cobro(Base):
    __tablename__ = "cobros"

    # La clave primaria es el saga_id: es lo que garantiza que una saga no se cobre dos veces.
    saga_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    estado: Mapped[str] = mapped_column(String(20))
    # Nulos solo en un registro ANULADO, que no tiene datos de cobro.
    cobro_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    cliente_id: Mapped[str | None] = mapped_column(String(100))
    monto: Mapped[int | None] = mapped_column(Integer)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
