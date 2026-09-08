from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.engine import URL

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


BACKEND_ROOT = Path(__file__).resolve().parents[3]
HEAD_REVISION = "20260908_0046"


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
        profile_columns = {
            column["name"]
            for column in inspect(connection).get_columns("document_profiles")
        }
        assert "profile_warnings" in profile_columns
        assert {"collection_id", "source_filename", "parsing_warnings"}.isdisjoint(
            profile_columns
        )
        paper_map_columns = {
            column["name"]
            for column in inspect(connection).get_columns("paper_maps")
        }
        assert {"input_fingerprint", "map_version", "generated_at"}.issubset(
            paper_map_columns
        )
        assert "collection_id" not in paper_map_columns
        assert "document_sources" in expected
        pipeline_run_columns = {
            column["name"]
            for column in inspect(connection).get_columns("pipeline_runs")
        }
        assert {
            "run_id",
            "pipeline_name",
            "scope_type",
            "scope_id",
            "input_fingerprint",
            "record_json",
        }.issubset(pipeline_run_columns)
        assert "tasks" not in expected
        assert "task_stages" not in expected
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


def test_existing_profile_and_paper_map_rows_are_simplified(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration-profile-map.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    now = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260908_0045")
        connection.exec_driver_sql(
            "ALTER TABLE document_profiles ADD COLUMN collection_id VARCHAR(64)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE document_profiles ADD COLUMN source_filename TEXT"
        )
        connection.exec_driver_sql(
            "ALTER TABLE document_profiles RENAME COLUMN profile_warnings "
            "TO parsing_warnings"
        )
        connection.exec_driver_sql(
            "ALTER TABLE paper_maps ADD COLUMN collection_id VARCHAR(64)"
        )
        for column_name in ("input_fingerprint", "map_version", "generated_at"):
            connection.exec_driver_sql(
                f"ALTER TABLE paper_maps DROP COLUMN {column_name}"
            )

        metadata = MetaData()
        auth_users = Table("auth_users", metadata, autoload_with=connection)
        collections = Table("collections", metadata, autoload_with=connection)
        documents = Table("documents", metadata, autoload_with=connection)
        profiles = Table("document_profiles", metadata, autoload_with=connection)
        paper_maps = Table("paper_maps", metadata, autoload_with=connection)
        connection.execute(
            auth_users.insert().values(
                user_id="profile-map-user",
                email="profile-map@example.com",
                display_name=None,
                password_hash="synthetic-password-hash",
                created_at=now,
            )
        )
        connection.execute(
            collections.insert().values(
                collection_id="profile-map-collection",
                owner_user_id="profile-map-user",
                name="Profile map migration",
                description=None,
                status="idle",
                paper_count=1,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            documents.insert().values(
                document_id="profile-map-document",
                collection_id="profile-map-collection",
                original_filename="paper.pdf",
                stored_filename="stored-paper.pdf",
                storage_key="profile-map-collection/inputs/paper.pdf",
                sha256="a" * 64,
                media_type="application/pdf",
                status="ready",
                size_bytes=42,
                document_order=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            profiles.insert().values(
                document_id="profile-map-document",
                collection_id="profile-map-collection",
                title="Profile Map Paper",
                source_filename="paper.pdf",
                doc_type="experimental",
                parsing_warnings=["classification_uncertain"],
                confidence=0.75,
                source_fingerprint="b" * 64,
                profile_version="profile.v1",
                profile_fingerprint="c" * 64,
                generated_at=now,
            )
        )
        connection.execute(
            paper_maps.insert().values(
                document_id="profile-map-document",
                collection_id="profile-map-collection",
                payload={
                    "document_id": "profile-map-document",
                    "doc_role": "experimental",
                    "studies": [],
                    "input_fingerprint": "d" * 64,
                },
            )
        )

        command.upgrade(config, "head")

        upgraded_profiles = Table(
            "document_profiles", MetaData(), autoload_with=connection
        )
        upgraded_maps = Table("paper_maps", MetaData(), autoload_with=connection)
        profile = connection.execute(select(upgraded_profiles)).mappings().one()
        paper_map = connection.execute(select(upgraded_maps)).mappings().one()
        assert profile["profile_warnings"] == ["classification_uncertain"]
        assert {"collection_id", "source_filename", "parsing_warnings"}.isdisjoint(
            upgraded_profiles.c.keys()
        )
        assert paper_map["input_fingerprint"] == "d" * 64
        assert paper_map["payload"] == {
            "doc_role": "experimental",
            "studies": [],
        }
        assert "collection_id" not in upgraded_maps.c

        command.downgrade(config, "20260908_0045")

        restored_profiles = Table(
            "document_profiles", MetaData(), autoload_with=connection
        )
        restored_maps = Table("paper_maps", MetaData(), autoload_with=connection)
        restored_profile = connection.execute(select(restored_profiles)).mappings().one()
        restored_map = connection.execute(select(restored_maps)).mappings().one()
        assert restored_profile["collection_id"] == "profile-map-collection"
        assert restored_profile["source_filename"] == "paper.pdf"
        assert restored_profile["parsing_warnings"] == ["classification_uncertain"]
        assert restored_map["collection_id"] == "profile-map-collection"
        assert restored_map["payload"]["document_id"] == "profile-map-document"
        assert restored_map["payload"]["input_fingerprint"] == "d" * 64

    engine.dispose()


def test_existing_0040_database_replaces_retired_task_tables(tmp_path) -> None:
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
        command.upgrade(config, "head")

        assert MigrationContext.configure(connection).get_current_revision() == (
            HEAD_REVISION
        )
        assert "pipeline_runs" in inspect(connection).get_table_names()
        assert "tasks" not in inspect(connection).get_table_names()
        assert "task_stages" not in inspect(connection).get_table_names()

    engine.dispose()


def test_existing_0044_task_history_is_backfilled_as_one_pipeline_run(tmp_path) -> None:
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "migration-task-history.sqlite"),
        )
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    now = datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 9, 8, 8, 1, tzinfo=timezone.utc)

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260908_0044")
        _create_legacy_task_tables(connection)
        metadata = MetaData()
        auth_users = Table("auth_users", metadata, autoload_with=connection)
        collections = Table("collections", metadata, autoload_with=connection)
        documents = Table("documents", metadata, autoload_with=connection)
        tasks = Table("tasks", metadata, autoload_with=connection)
        task_stages = Table("task_stages", metadata, autoload_with=connection)
        connection.execute(
            auth_users.insert().values(
                user_id="migration-user",
                email="migration@example.com",
                display_name=None,
                password_hash="synthetic-password-hash",
                created_at=now,
            )
        )
        connection.execute(
            collections.insert().values(
                collection_id="migration-collection",
                owner_user_id="migration-user",
                name="Migration collection",
                description=None,
                status="processing",
                paper_count=1,
                created_at=now,
                updated_at=finished,
            )
        )
        connection.execute(
            documents.insert().values(
                document_id="migration-document",
                collection_id="migration-collection",
                original_filename="paper.pdf",
                stored_filename="paper.pdf",
                storage_key="migration-collection/inputs/paper.pdf",
                sha256="a" * 64,
                media_type="application/pdf",
                status="processing",
                size_bytes=100,
                document_order=0,
                created_at=now,
                updated_at=finished,
            )
        )
        connection.execute(
            tasks.insert().values(
                task_id="task-migration",
                collection_id="migration-collection",
                task_type="document_preparation",
                document_id="migration-document",
                mode="standard",
                input_fingerprint="b" * 64,
                status="failed",
                current_stage="document_profile",
                progress_percent=45,
                progress_detail={"phase": "document_profile"},
                errors=["profile extraction failed"],
                warnings=["parser warning"],
                details={"requested_by": "upload"},
                created_at=now,
                updated_at=finished,
                started_at=now,
                finished_at=finished,
            )
        )
        connection.execute(
            task_stages.insert().values(
                stage_id="stage-migration",
                task_id="task-migration",
                stage_kind="document_profile",
                stage_order=1,
                status="failed",
                started_at=now,
                finished_at=finished,
                errors=["profile extraction failed"],
                warnings=[],
                dependencies=[],
                stats={"duration_ms": 60000},
                output_summary={"profile_count": 0},
            )
        )

        command.upgrade(config, "head")

        pipeline_runs = Table(
            "pipeline_runs", MetaData(), autoload_with=connection
        )
        row = connection.execute(
            select(pipeline_runs).where(
                pipeline_runs.c.run_id == "task-migration"
            )
        ).mappings().one()
        assert row["pipeline_name"] == "document_preparation"
        assert row["scope_type"] == "document"
        assert row["scope_id"] == "migration-document"
        assert row["record_json"]["context"] == {"requested_by": "upload"}
        assert row["record_json"]["nodes"]["document_profile"] == {
            "name": "document_profile",
            "dependencies": [],
            "status": "failed",
            "errors": ["profile extraction failed"],
            "warnings": [],
            "stats": {"duration_ms": 60000},
            "timestamps": {
                "started_at": now.isoformat(),
                "finished_at": finished.isoformat(),
            },
            "output_summary": {"profile_count": 0},
        }
        assert "tasks" not in inspect(connection).get_table_names()
        assert "task_stages" not in inspect(connection).get_table_names()

    engine.dispose()


def _create_legacy_task_tables(connection) -> None:
    if "tasks" in inspect(connection).get_table_names():
        return
    metadata = MetaData()
    tasks = Table(
        "tasks",
        metadata,
        Column("task_id", String(64), primary_key=True),
        Column("collection_id", String(64), nullable=False),
        Column("task_type", String(64), nullable=False),
        Column("document_id", String(64)),
        Column("mode", String(64), nullable=False),
        Column("input_fingerprint", String(64)),
        Column("status", String(32), nullable=False),
        Column("current_stage", String(128), nullable=False),
        Column("progress_percent", Integer, nullable=False),
        Column("progress_detail", JSON),
        Column("errors", JSON, nullable=False),
        Column("warnings", JSON, nullable=False),
        Column("details", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("started_at", DateTime(timezone=True)),
        Column("finished_at", DateTime(timezone=True)),
    )
    Table(
        "task_stages",
        metadata,
        Column("stage_id", String(64), primary_key=True),
        Column("task_id", String(64), nullable=False),
        Column("stage_kind", String(128), nullable=False),
        Column("stage_order", Integer, nullable=False),
        Column("status", String(32), nullable=False),
        Column("started_at", DateTime(timezone=True)),
        Column("finished_at", DateTime(timezone=True)),
        Column("errors", JSON, nullable=False),
        Column("warnings", JSON, nullable=False),
        Column("dependencies", JSON, nullable=False),
        Column("stats", JSON, nullable=False),
        Column("output_summary", JSON, nullable=False),
    )
    metadata.create_all(connection, tables=[tasks, metadata.tables["task_stages"]])


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
