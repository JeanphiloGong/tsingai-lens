from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


BACKEND_ROOT = Path(__file__).resolve().parents[3]
HEAD_REVISION = "20260827_0039"


def test_empty_database_upgrades_to_current_document_schema(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == HEAD_REVISION

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

        assert MigrationContext.configure(connection).get_current_revision() == (
            HEAD_REVISION
        )
        expected = sorted({*Base.metadata.tables, "alembic_version"})
        assert inspect(connection).get_table_names() == expected
        assert "collection_builds" not in expected
        assert "document_versions" not in expected
        assert "paper_fact_builds" not in expected
        assert "comparison_builds" not in expected
        assert {
            "document_id",
            "collection_id",
            "sha256",
            "status",
            "source_fingerprint",
            "profile_fingerprint",
            "preparation_fingerprint",
        }.issubset(
            {
                column["name"]
                for column in inspect(connection).get_columns("documents")
            }
        )
        assert {
            "document_id",
            "input_fingerprint",
            "task_type",
        }.issubset(
            {
                column["name"]
                for column in inspect(connection).get_columns("tasks")
            }
        )
        assert "payload" in {
            column["name"]
            for column in inspect(connection).get_columns("objective_analyses")
        }

        with pytest.raises(RuntimeError, match="irreversible destructive cutover"):
            command.downgrade(config, "20260827_0037")

    engine.dispose()


def test_postgres_migration_head_matches_current_metadata(postgres_sync_engine) -> None:
    expected = sorted({*Base.metadata.tables, "alembic_version"})
    assert sorted(inspect(postgres_sync_engine).get_table_names()) == expected

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
