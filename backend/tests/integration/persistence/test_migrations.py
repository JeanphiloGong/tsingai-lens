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
    UniqueConstraint,
)
from sqlalchemy.engine import URL

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


BACKEND_ROOT = Path(__file__).resolve().parents[3]
HEAD_REVISION = "20260908_0052"


def test_ordered_chat_migration_preserves_scalar_history_and_refuses_loss(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'chat-history.sqlite'}")
    metadata = MetaData()
    messages = Table("chat_messages", metadata,
        Column("message_id", String, primary_key=True), Column("session_id", String),
        Column("role", String), Column("content", String), Column("tool_call_id", String),
        Column("tool_name", String), Column("tool_arguments", JSON))
    calls = Table("chat_tool_calls", metadata,
        Column("tool_call_id", String, primary_key=True), Column("session_id", String),
        Column("assistant_message_id", String), Column("name", String), Column("arguments", JSON),
        UniqueConstraint("assistant_message_id", name="uq_chat_tool_calls_assistant_message"))
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        metadata.create_all(connection)
        command.stamp(config, "20260908_0046")
        connection.execute(messages.insert().values(message_id="m1", session_id="s1", role="assistant", content="", tool_call_id="c1", tool_name="read_source", tool_arguments={"document_id": "p1"}))
        connection.execute(calls.insert().values(tool_call_id="c1", session_id="s1", assistant_message_id="m1", name="read_source", arguments={"document_id": "p1"}))
        command.upgrade(config, "7f4a0a872e9d")
        target_calls = Table("chat_tool_calls", MetaData(), autoload_with=connection)
        assert connection.execute(select(target_calls.c.position)).scalar_one() == 0
        assert "tool_arguments" not in {c["name"] for c in inspect(connection).get_columns("chat_messages")}
        connection.execute(target_calls.insert().values(tool_call_id="c2", session_id="s1", assistant_message_id="m1", position=1, name="read_source", arguments={"document_id": "p2"}))
        with pytest.raises(RuntimeError, match="multiple calls would be lost"):
            command.downgrade(config, "20260908_0046")
        target_calls = Table("chat_tool_calls", MetaData(), autoload_with=connection)
        assert len(connection.execute(select(target_calls)).all()) == 2
        connection.execute(target_calls.delete().where(target_calls.c.tool_call_id == "c2"))
        command.downgrade(config, "20260908_0046")
        old_message = connection.execute(select(messages)).mappings().one()
        assert old_message["tool_call_id"] == "c1"
        assert old_message["tool_arguments"] == {"document_id": "p1"}
        connection.execute(messages.update().values(tool_arguments={"document_id": "wrong"}))
        with pytest.raises(RuntimeError, match="does not match durable calls"):
            command.upgrade(config, "7f4a0a872e9d")
    engine.dispose()


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
        assert "paper_maps" not in expected
        assert "evaluation_gold_items" not in expected
        assert "evaluation_prediction_items" not in expected
        assert "evaluation_scores" not in expected
        assert "evaluation_failures" not in expected
        assert {
            "items",
        }.issubset(
            {column["name"] for column in inspect(connection).get_columns("evaluation_gold_sets")}
        )
        assert {
            "items",
        }.issubset(
            {column["name"] for column in inspect(connection).get_columns("evaluation_prediction_snapshots")}
        )
        assert {"scores", "failures"}.issubset(
            {column["name"] for column in inspect(connection).get_columns("evaluation_runs")}
        )
        assert {
            "paper_map_payload",
            "paper_map_input_fingerprint",
            "paper_map_version",
            "paper_map_generated_at",
        }.issubset(profile_columns)
        assert "document_sources" in expected
        collection_columns = {
            column["name"]
            for column in inspect(connection).get_columns("collections")
        }
        assert "paper_count" not in collection_columns
        assert {
            "document_id",
            "source_format",
            "parser_name",
            "parser_version",
            "source_fingerprint",
            "artifact_json",
            "created_at",
            "updated_at",
        } == {
            column["name"]
            for column in inspect(connection).get_columns("document_sources")
        }
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

        with pytest.raises(RuntimeError, match="irreversible"):
            command.downgrade(config, "20260827_0037")

    engine.dispose()


def test_redundant_source_and_collection_fields_are_removed_without_data_loss(tmp_path) -> None:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "compact-source.sqlite"))
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    now = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260908_0051")
        metadata = MetaData()
        auth_users = Table("auth_users", metadata, autoload_with=connection)
        collections = Table("collections", metadata, autoload_with=connection)
        documents = Table("documents", metadata, autoload_with=connection)
        sources = Table("document_sources", metadata, autoload_with=connection)
        connection.exec_driver_sql(
            "ALTER TABLE collections ADD COLUMN paper_count INTEGER NOT NULL DEFAULT 0"
        )
        connection.exec_driver_sql(
            "ALTER TABLE document_sources ADD COLUMN source_id VARCHAR(128)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE document_sources ADD COLUMN collection_id VARCHAR(64)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE document_sources ADD COLUMN tree_json JSON"
        )
        metadata.clear()
        auth_users = Table("auth_users", metadata, autoload_with=connection)
        collections = Table("collections", metadata, autoload_with=connection)
        documents = Table("documents", metadata, autoload_with=connection)
        sources = Table("document_sources", metadata, autoload_with=connection)
        connection.execute(
            auth_users.insert().values(
                user_id="compact-user",
                email="compact@example.com",
                display_name=None,
                password_hash="synthetic-password-hash",
                created_at=now,
            )
        )
        connection.execute(
            collections.insert().values(
                collection_id="compact-collection",
                owner_user_id="compact-user",
                name="Compact collection",
                description=None,
                status="uploaded",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            documents.insert().values(
                document_id="compact-document",
                collection_id="compact-collection",
                original_filename="paper.pdf",
                stored_filename="paper.pdf",
                storage_key="compact-collection/paper.pdf",
                sha256="a" * 64,
                media_type="application/pdf",
                status="ready",
                size_bytes=10,
                document_order=0,
                created_at=now,
                updated_at=now,
            )
        )
        artifact = {"document": {"document_id": "compact-document"}, "blocks": []}
        connection.execute(
            sources.insert().values(
                source_id="src_compact-document",
                document_id="compact-document",
                collection_id="compact-collection",
                source_format="pdf",
                parser_name="legacy-parser",
                parser_version="legacy.v1",
                source_fingerprint="b" * 64,
                artifact_json=artifact,
                tree_json={"nodes": {"root": {}}},
                created_at=now,
                updated_at=now,
            )
        )

        command.upgrade(config, "head")
        compact_sources = Table("document_sources", MetaData(), autoload_with=connection)
        source = connection.execute(select(compact_sources)).mappings().one()
        assert source["document_id"] == "compact-document"
        assert source["artifact_json"] == artifact
        assert "source_id" not in compact_sources.c
        assert "collection_id" not in compact_sources.c
        assert "tree_json" not in compact_sources.c
        assert "paper_count" not in {
            column["name"]
            for column in inspect(connection).get_columns("collections")
        }
    engine.dispose()


def test_evaluation_children_are_embedded_before_tables_are_removed(tmp_path) -> None:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "evaluation-merge.sqlite"))
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260908_0050")
        metadata = MetaData()
        gold_sets = Table("evaluation_gold_sets", metadata, autoload_with=connection)
        gold_items = Table(
            "evaluation_gold_items",
            metadata,
            Column("gold_item_id", String, primary_key=True),
            Column("gold_id", String, nullable=False),
            Column("document_id", String, nullable=False),
            Column("family", String, nullable=False),
            Column("item_key", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("evidence_refs", JSON, nullable=False),
            Column("metadata_json", JSON, nullable=False),
        )
        snapshots = Table(
            "evaluation_prediction_snapshots", metadata, autoload_with=connection
        )
        prediction_items = Table(
            "evaluation_prediction_items",
            metadata,
            Column("snapshot_id", String, primary_key=True),
            Column("item_id", String, primary_key=True),
            Column("document_id", String, nullable=False),
            Column("family", String, nullable=False),
            Column("item_key", String, nullable=False),
            Column("payload", JSON, nullable=False),
            Column("source_refs", JSON, nullable=False),
            Column("confidence", Integer, nullable=True),
        )
        runs = Table("evaluation_runs", metadata, autoload_with=connection)
        scores = Table(
            "evaluation_scores",
            metadata,
            Column("score_id", String, primary_key=True),
            Column("evaluation_run_id", String, nullable=False),
            Column("document_id", String, nullable=True),
            Column("family", String, nullable=False),
            Column("metric", String, nullable=False),
            Column("value", Integer, nullable=False),
            Column("numerator", Integer, nullable=True),
            Column("denominator", Integer, nullable=True),
        )
        failures = Table(
            "evaluation_failures",
            metadata,
            Column("failure_id", String, primary_key=True),
            Column("evaluation_run_id", String, nullable=False),
            Column("document_id", String, nullable=False),
            Column("family", String, nullable=False),
            Column("failure_type", String, nullable=False),
            Column("likely_layer", String, nullable=False),
            Column("severity", String, nullable=False),
            Column("gold_item_id", String, nullable=True),
            Column("prediction_item_id", String, nullable=True),
            Column("gold", JSON, nullable=True),
            Column("prediction", JSON, nullable=True),
            Column("reason", String, nullable=True),
            Column("source_refs", JSON, nullable=False),
        )
        gold_items.create(connection)
        prediction_items.create(connection)
        scores.create(connection)
        failures.create(connection)

        connection.execute(
            gold_sets.insert().values(
                gold_id="gold-migrate",
                collection_id="collection-migrate",
                version="v1",
                target_layer="core",
                metric_profile="profile",
                metadata_json={},
                updated_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
            )
        )
        connection.execute(
            gold_items.insert().values(
                gold_item_id="gold-item-migrate",
                gold_id="gold-migrate",
                document_id="doc-1",
                family="facts",
                item_key="doc-1:key",
                payload={"value": 1},
                evidence_refs=[],
                metadata_json={},
            )
        )
        connection.execute(
            snapshots.insert().values(
                snapshot_id="snapshot-migrate",
                collection_id="collection-migrate",
                target_layer="core",
                fact_source="source",
                system_context={},
                artifact_counts={},
                created_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
            )
        )
        connection.execute(
            prediction_items.insert().values(
                snapshot_id="snapshot-migrate",
                item_id="prediction-migrate",
                document_id="doc-1",
                family="facts",
                item_key="doc-1:key",
                payload={"value": 2},
                source_refs=[],
                confidence=0.5,
            )
        )
        connection.execute(
            runs.insert().values(
                evaluation_run_id="run-migrate",
                collection_id="collection-migrate",
                gold_id="gold-migrate",
                prediction_snapshot_id="snapshot-migrate",
                target_layer="core",
                fact_source="source",
                metric_profile="profile",
                status="ready",
                summary={},
                created_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
            )
        )
        connection.execute(
            scores.insert().values(
                score_id="score-migrate",
                evaluation_run_id="run-migrate",
                family="facts",
                metric="accuracy",
                value=0.5,
            )
        )
        connection.execute(
            failures.insert().values(
                failure_id="failure-migrate",
                evaluation_run_id="run-migrate",
                document_id="doc-1",
                family="facts",
                failure_type="numeric_value_mismatch",
                likely_layer="core_extraction",
                severity="medium",
                source_refs=[],
            )
        )

        command.upgrade(config, "head")
        merged_gold = Table("evaluation_gold_sets", MetaData(), autoload_with=connection)
        merged_snapshot = Table(
            "evaluation_prediction_snapshots", MetaData(), autoload_with=connection
        )
        merged_run = Table("evaluation_runs", MetaData(), autoload_with=connection)
        assert connection.execute(
            select(merged_gold.c["items"]).where(merged_gold.c.gold_id == "gold-migrate")
        ).scalar_one()[0]["gold_item_id"] == "gold-item-migrate"
        assert connection.execute(
            select(merged_snapshot.c["items"]).where(
                merged_snapshot.c.snapshot_id == "snapshot-migrate"
            )
        ).scalar_one()[0]["item_id"] == "prediction-migrate"
        run_row = connection.execute(
            select(merged_run).where(merged_run.c.evaluation_run_id == "run-migrate")
        ).mappings().one()
        assert run_row["scores"][0]["score_id"] == "score-migrate"
        assert run_row["failures"][0]["failure_id"] == "failure-migrate"
        assert not {
            "evaluation_gold_items",
            "evaluation_prediction_items",
            "evaluation_scores",
            "evaluation_failures",
        }.intersection(inspect(connection).get_table_names())
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
            "CREATE TABLE paper_maps ("
            "document_id VARCHAR(128) PRIMARY KEY, "
            "collection_id VARCHAR(64) NOT NULL, "
            "payload JSON NOT NULL)"
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
        profile = connection.execute(select(upgraded_profiles)).mappings().one()
        assert profile["profile_warnings"] == ["classification_uncertain"]
        assert {"collection_id", "source_filename", "parsing_warnings"}.isdisjoint(
            upgraded_profiles.c.keys()
        )
        assert profile["paper_map_input_fingerprint"] == "d" * 64
        assert profile["paper_map_payload"] == {
            "doc_role": "experimental",
            "studies": [],
        }

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
