from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import URL

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


BACKEND_ROOT = Path(__file__).resolve().parents[3]
HEAD_REVISION = "20260908_0044"


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
        }.issubset(
            {
                column["name"]
                for column in inspect(connection).get_columns("documents")
            }
        )
        document_columns = {
            column["name"] for column in inspect(connection).get_columns("documents")
        }
        assert {
            "parser_version",
            "document_analysis_version",
            "source_fingerprint",
            "profile_fingerprint",
            "preparation_fingerprint",
        }.isdisjoint(document_columns)
        assert {
            "source_fingerprint",
            "profile_version",
            "profile_fingerprint",
            "generated_at",
        }.issubset(
            {
                column["name"]
                for column in inspect(connection).get_columns("document_profiles")
            }
        )
        assert "document_sources" in expected
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
        assert {
            "plan_version",
            "parent_plan_id",
            "structured_plan",
            "updated_by",
        }.issubset(
            {
                column["name"]
                for column in inspect(connection).get_columns(
                    "objective_experiment_plans"
                )
            }
        )

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


def test_existing_0041_plan_becomes_an_unstructured_first_revision(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration-plan-from-0041.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260901_0041")
        assert MigrationContext.configure(connection).get_current_revision() == (
            "20260901_0041"
        )
        metadata = MetaData()
        auth_users = Table("auth_users", metadata, autoload_with=connection)
        collections = Table("collections", metadata, autoload_with=connection)
        objectives = Table("research_objectives", metadata, autoload_with=connection)
        plans = Table(
            "objective_experiment_plans", metadata, autoload_with=connection
        )
        connection.execute(
            auth_users.insert().values(
                user_id="legacy-user",
                email="legacy@example.com",
                display_name=None,
                password_hash="synthetic-password-hash",
                created_at=now,
            )
        )
        connection.execute(
            collections.insert().values(
                collection_id="legacy-collection",
                owner_user_id="legacy-user",
                name="Legacy collection",
                description=None,
                status="idle",
                paper_count=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            objectives.insert().values(
                collection_id="legacy-collection",
                objective_id="legacy-objective",
                rank=1,
                origin="system_discovered",
                created_by_tool_call_id=None,
                payload={"question": "Legacy question"},
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            plans.insert().values(
                plan_id="legacy-plan",
                collection_id="legacy-collection",
                objective_id="legacy-objective",
                title="Legacy plan",
                content="Previously approved prose.",
                status="draft",
                source_message_id=None,
                source_links=[],
                metadata_json={"source": "manual"},
                created_by="legacy-user",
                created_at=now,
                updated_at=now,
            )
        )

        command.upgrade(config, "head")

        upgraded_plans = Table(
            "objective_experiment_plans", MetaData(), autoload_with=connection
        )
        row = connection.execute(
            select(upgraded_plans).where(upgraded_plans.c.plan_id == "legacy-plan")
        ).mappings().one()
        assert row["plan_version"] == 1
        assert row["parent_plan_id"] is None
        assert row["structured_plan"] is None
        assert row["updated_by"] is None

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
