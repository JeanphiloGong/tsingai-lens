"""Replace duplicate Task persistence with one PipelineRun aggregate.

Revision ID: 20260908_0045
Revises: 20260908_0044
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260908_0045"
down_revision: str | Sequence[str] | None = "20260908_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "pipeline_runs" not in existing:
        _create_pipeline_runs()
    if "tasks" in existing:
        _backfill_runs(bind, has_stages="task_stages" in existing)
    if "task_stages" in existing:
        op.drop_table("task_stages")
    if "tasks" in existing:
        op.drop_table("tasks")


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0045 is an irreversible destructive cutover to PipelineRun storage"
    )


def _create_pipeline_runs() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("pipeline_name", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("record_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial_success', 'failed')",
            name=op.f("ck_pipeline_runs_valid_status"),
        ),
        sa.CheckConstraint(
            "pipeline_name <> ''",
            name=op.f("ck_pipeline_runs_pipeline_name_not_empty"),
        ),
        sa.CheckConstraint(
            "scope_type <> ''",
            name=op.f("ck_pipeline_runs_scope_type_not_empty"),
        ),
        sa.CheckConstraint(
            "scope_id <> ''",
            name=op.f("ck_pipeline_runs_scope_id_not_empty"),
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name=op.f("ck_pipeline_runs_valid_timestamps"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_pipeline_runs_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_pipeline_runs")),
    )
    for column in ("collection_id", "pipeline_name", "scope_type", "scope_id", "status"):
        op.create_index(
            op.f(f"ix_pipeline_runs_{column}"),
            "pipeline_runs",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_pipeline_runs_active_scope",
        "pipeline_runs",
        ["pipeline_name", "scope_type", "scope_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def _backfill_runs(bind: sa.Connection, *, has_stages: bool) -> None:
    metadata = sa.MetaData()
    names = ["tasks", "pipeline_runs"]
    if has_stages:
        names.append("task_stages")
    metadata.reflect(bind=bind, only=names)
    tasks = metadata.tables["tasks"]
    pipeline_runs = metadata.tables["pipeline_runs"]
    stages = metadata.tables.get("task_stages")
    existing_ids = set(
        bind.execute(sa.select(pipeline_runs.c.run_id)).scalars().all()
    )
    for task in bind.execute(sa.select(tasks)).mappings():
        run_id = str(task["task_id"])
        if run_id in existing_ids:
            continue
        document_id = _text(task.get("document_id"))
        scope_type = "document" if document_id else "collection"
        scope_id = document_id or str(task["collection_id"])
        nodes = _stage_nodes(bind, stages, run_id) if stages is not None else {}
        record = {
            "pipeline_name": str(task.get("task_type") or "document_preparation"),
            "mode": str(task.get("mode") or "standard"),
            "run_id": run_id,
            "collection_id": str(task["collection_id"]),
            "scope_type": scope_type,
            "scope_id": scope_id,
            "input_fingerprint": _text(task.get("input_fingerprint")),
            "status": str(task.get("status") or "queued"),
            "current_node": _text(task.get("current_stage")),
            "progress_percent": int(task.get("progress_percent") or 0),
            "progress_detail": _mapping_or_none(task.get("progress_detail")),
            "nodes": nodes,
            "errors": _string_list(task.get("errors")),
            "warnings": _string_list(task.get("warnings")),
            "stats": _empty_stats(),
            "timestamps": {
                "created_at": _iso(task["created_at"]),
                "updated_at": _iso(task["updated_at"]),
                "started_at": _iso(task.get("started_at")),
                "finished_at": _iso(task.get("finished_at")),
            },
            "context": _mapping(task.get("details")),
            "resumed_from_run_id": None,
        }
        bind.execute(
            pipeline_runs.insert().values(
                run_id=run_id,
                collection_id=task["collection_id"],
                pipeline_name=record["pipeline_name"],
                scope_type=scope_type,
                scope_id=scope_id,
                mode=record["mode"],
                input_fingerprint=record["input_fingerprint"],
                status=record["status"],
                record_json=record,
                created_at=task["created_at"],
                updated_at=task["updated_at"],
            )
        )


def _stage_nodes(
    bind: sa.Connection,
    stages: sa.Table,
    run_id: str,
) -> dict[str, dict[str, Any]]:
    rows = bind.execute(
        sa.select(stages)
        .where(stages.c.task_id == run_id)
        .order_by(stages.c.stage_order, stages.c.stage_id)
    ).mappings()
    return {
        str(row["stage_kind"]): {
            "name": str(row["stage_kind"]),
            "dependencies": _string_list(row.get("dependencies")),
            "status": str(row.get("status") or "queued"),
            "errors": _string_list(row.get("errors")),
            "warnings": _string_list(row.get("warnings")),
            "stats": _mapping(row.get("stats")) or _empty_stats(),
            "timestamps": {
                "started_at": _iso(row.get("started_at")),
                "finished_at": _iso(row.get("finished_at")),
            },
            "output_summary": _mapping(row.get("output_summary")),
        }
        for row in rows
    }


def _empty_stats() -> dict[str, Any]:
    return {
        "duration_ms": None,
        "token_usage": None,
        "model_usage": [],
        "unreported_request_count": 0,
        "prompt_versions": {},
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        resolved = value
        if resolved.tzinfo is None:
            resolved = resolved.replace(tzinfo=timezone.utc)
        return resolved.astimezone(timezone.utc).isoformat()
    return str(value)
