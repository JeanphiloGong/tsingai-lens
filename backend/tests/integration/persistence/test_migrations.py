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
HEAD_REVISION = "20260901_0041"


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
        task_columns = {
            column["name"] for column in inspect(connection).get_columns("tasks")
        }
        assert {
            "document_id",
            "input_fingerprint",
            "task_type",
        }.issubset(task_columns)
        assert "output_path" not in task_columns
        assert "payload" in {
            column["name"]
            for column in inspect(connection).get_columns("objective_analyses")
        }
        assert "source_contexts" in {
            column["name"]
            for column in inspect(connection).get_columns("chat_messages")
        }

        with pytest.raises(RuntimeError, match="irreversible destructive cutover"):
            command.downgrade(config, "20260827_0037")

    engine.dispose()


def test_existing_0040_database_removes_retired_task_output_path(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration-from-0040.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260831_0040")
        if "output_path" not in {
            column["name"] for column in inspect(connection).get_columns("tasks")
        }:
            connection.exec_driver_sql(
                "ALTER TABLE tasks ADD COLUMN output_path TEXT"
            )
        assert "output_path" in {
            column["name"] for column in inspect(connection).get_columns("tasks")
        }

        command.upgrade(config, "head")

        assert MigrationContext.configure(connection).get_current_revision() == (
            HEAD_REVISION
        )
        assert "output_path" not in {
            column["name"] for column in inspect(connection).get_columns("tasks")
        }

    engine.dispose()


def test_existing_0039_database_adds_chat_source_context(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration-from-0039.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260827_0039")
        connection.exec_driver_sql(
            "ALTER TABLE chat_messages DROP COLUMN source_contexts"
        )
        assert "source_contexts" not in {
            column["name"]
            for column in inspect(connection).get_columns("chat_messages")
        }

        command.upgrade(config, "head")

        assert MigrationContext.configure(connection).get_current_revision() == (
            HEAD_REVISION
        )
        assert "source_contexts" in {
            column["name"]
            for column in inspect(connection).get_columns("chat_messages")
        }

    engine.dispose()


def test_v01211_database_upgrades_to_current_document_schema(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration-from-v01211.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260825_0036")
        assert MigrationContext.configure(connection).get_current_revision() == (
            "20260825_0036"
        )

        command.upgrade(config, "head")

        assert MigrationContext.configure(connection).get_current_revision() == (
            HEAD_REVISION
        )
        assert sorted(inspect(connection).get_table_names()) == sorted(
            {*Base.metadata.tables, "alembic_version"}
        )

    engine.dispose()


def test_postgres_migration_head_matches_current_metadata(postgres_sync_engine) -> None:
    expected = sorted({*Base.metadata.tables, "alembic_version"})
    assert sorted(inspect(postgres_sync_engine).get_table_names()) == expected

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with postgres_sync_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
