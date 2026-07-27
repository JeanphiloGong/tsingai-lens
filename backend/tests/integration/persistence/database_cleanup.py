from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def reset_postgres_schema(engine: Engine) -> None:
    """Reset the dedicated *_test database without invoking irreversible migrations."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
