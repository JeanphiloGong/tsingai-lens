"""Asynchronous PostgreSQL engine and session construction."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import ENV_FILE_PATH


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        env_prefix="LENS_",
        extra="ignore",
    )

    database_url: SecretStr
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: float = Field(default=30, gt=0, allow_inf_nan=False)


def build_database_engine(settings: DatabaseSettings) -> AsyncEngine:
    try:
        database_url = make_url(settings.database_url.get_secret_value())
    except ArgumentError as exc:
        raise ValueError("LENS_DATABASE_URL must be a valid SQLAlchemy URL.") from exc
    if database_url.drivername != "postgresql+psycopg":
        raise ValueError("LENS_DATABASE_URL must use postgresql+psycopg.")
    if not database_url.database:
        raise ValueError("LENS_DATABASE_URL must include a database name.")
    return create_async_engine(
        database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
    )


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine)
