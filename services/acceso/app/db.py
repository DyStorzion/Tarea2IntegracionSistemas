"""Conexión a la base de datos del servicio (SQLAlchemy asíncrono sobre asyncpg)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=10, pool_pre_ping=True)
Sesion = async_sessionmaker(engine, expire_on_commit=False)


async def crear_tablas() -> None:
    """Crea las tablas que falten. El esquema es fijo, así que no se usan migraciones."""
    async with engine.begin() as conexion:
        await conexion.run_sync(Base.metadata.create_all)


async def obtener_sesion() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: una sesión por petición."""
    async with Sesion() as sesion:
        yield sesion
