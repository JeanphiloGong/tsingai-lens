"""Alembic environment for synchronous PostgreSQL migrations."""

from alembic import context
from sqlalchemy.engine import Connection

from infra.persistence.database import DatabaseSettings, build_database_engine
from infra.persistence.postgres import models as _postgres_models  # noqa: F401
from infra.persistence.postgres.base import Base


config = context.config


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        run_migrations(supplied_connection)
        return

    engine = build_database_engine(DatabaseSettings())
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported.")
run_migrations_online()
