"""Real PostgreSQL forward cutover, atomic import and restore checks."""
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from infra.llm.model_credentials import decrypt_api_key
from scripts.import_model_connection_keys import import_keys

pytestmark = pytest.mark.anyio


def legacy_table(engine):
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE model_connections CASCADE"))
        connection.execute(text("""
            CREATE TABLE model_connections (
                connection_id varchar(64) PRIMARY KEY, display_name text NOT NULL,
                base_url text NOT NULL, model text NOT NULL, api_key_ref text,
                enabled boolean NOT NULL DEFAULT false, priority integer NOT NULL DEFAULT 0,
                context_window_tokens integer, max_output_tokens integer,
                request_timeout_seconds double precision,
                created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
            )
        """))
        connection.execute(text("CREATE INDEX ix_model_connections_enabled ON model_connections(enabled)"))
        config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.stamp(config, "20261104_0099")
    return config


def migrate(engine, config, target):
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, target)


async def test_legacy_import_is_atomic_and_final_migration_refuses_missing_keys(postgres_sync_engine, monkeypatch):
    engine = postgres_sync_engine
    config = legacy_table(engine)
    with engine.begin() as connection:
        for identity in ("a", "b"):
            connection.execute(text("""
                INSERT INTO model_connections(connection_id,display_name,base_url,model,api_key_ref,enabled,priority,created_at,updated_at)
                VALUES (:id,:name,'http://127.0.0.1:9999/v1','local-model',:ref,true,7,now(),now())
            """), {"id":identity,"name":identity,"ref":"env:TEST_MODEL_"+identity.upper()})
    migrate(engine, config, "20261114_0100")
    with pytest.raises(RuntimeError, match="Import all"):
        migrate(engine, config, "20261114_0101")
    monkeypatch.setenv("TEST_MODEL_A", "synthetic-a")
    monkeypatch.delenv("TEST_MODEL_B", raising=False)
    async_engine = create_async_engine(engine.url, poolclass=NullPool)
    try:
        with pytest.raises(RuntimeError, match="no credentials were changed"):
            await import_keys(async_engine, bytes(range(32)))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM model_connections WHERE api_key_ciphertext IS NOT NULL")).scalar_one() == 0
        monkeypatch.setenv("TEST_MODEL_B", "synthetic-b")
        assert await import_keys(async_engine, bytes(range(32))) == 2
        assert await import_keys(async_engine, bytes(range(32))) == 0
    finally:
        await async_engine.dispose()
    migrate(engine, config, "20261114_0101")
    with engine.connect() as connection:
        assert "api_key_ref" not in {column["name"] for column in inspect(connection).get_columns("model_connections")}
        rows = connection.execute(text("SELECT connection_id,api_key_ciphertext,priority,enabled,version FROM model_connections ORDER BY connection_id")).all()
        assert [tuple(row[2:]) for row in rows] == [(7,True,1),(7,True,1)]
        assert [decrypt_api_key(bytes(range(32)),row[0],row[1]) for row in rows] == ["synthetic-a","synthetic-b"]


def test_fresh_replay_has_final_schema_and_rejects_nonfinite_limits(postgres_sync_engine):
    from sqlalchemy.exc import IntegrityError
    with postgres_sync_engine.connect() as connection:
        columns={column["name"] for column in inspect(connection).get_columns("model_connections")}
        assert {"api_key_ciphertext","version"} <= columns and "api_key_ref" not in columns
    for timeout in ("NaN", "Infinity", "-1"):
        with pytest.raises(IntegrityError), postgres_sync_engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO model_connections(connection_id,display_name,base_url,model,created_at,updated_at,request_timeout_seconds)
                VALUES ('invalid','Invalid','http://localhost/v1','local',now(),now(),:timeout)
            """), {"timeout":float(timeout)})
