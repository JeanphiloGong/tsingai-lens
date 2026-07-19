"""Synchronous PostgreSQL engine and session construction."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from config import ENV_FILE_PATH


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        env_prefix="LENS_",
        extra="ignore",
    )

    database_url: SecretStr


def build_database_engine(settings: DatabaseSettings) -> Engine:
    try:
        database_url = make_url(settings.database_url.get_secret_value())
    except ArgumentError as exc:
        raise ValueError("LENS_DATABASE_URL must be a valid SQLAlchemy URL.") from exc
    if database_url.drivername != "postgresql+psycopg":
        raise ValueError("LENS_DATABASE_URL must use postgresql+psycopg.")
    if not database_url.database:
        raise ValueError("LENS_DATABASE_URL must include a database name.")
    return create_engine(database_url)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)
