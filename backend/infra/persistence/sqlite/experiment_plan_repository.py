from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from config import DATA_DIR
from domain.goal import ExperimentPlanRecord


class SqliteExperimentPlanRepository:
    """SQLite-backed persistence for goal-scoped experiment plan drafts."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord:
        self._ensure_schema()
        payload = plan.to_record()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO goal_experiment_plans (
                    plan_id,
                    collection_id,
                    goal_id,
                    title,
                    content,
                    status,
                    source_message_id,
                    source_links,
                    metadata,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    goal_id = excluded.goal_id,
                    title = excluded.title,
                    content = excluded.content,
                    status = excluded.status,
                    source_message_id = excluded.source_message_id,
                    source_links = excluded.source_links,
                    metadata = excluded.metadata,
                    created_by = excluded.created_by,
                    updated_at = excluded.updated_at
                """,
                self._plan_values(payload),
            )
        stored = self.read_plan(plan.collection_id, plan.goal_id, plan.plan_id)
        if stored is None:
            raise RuntimeError("failed to persist experiment plan")
        return stored

    def read_plan(
        self,
        collection_id: str,
        goal_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM goal_experiment_plans
                WHERE collection_id = ? AND goal_id = ? AND plan_id = ?
                """,
                (collection_id, goal_id, plan_id),
            ).fetchone()
        return self._plan_from_row(row) if row is not None else None

    def list_plans(
        self,
        collection_id: str,
        goal_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM goal_experiment_plans
                WHERE collection_id = ? AND goal_id = ?
                ORDER BY updated_at DESC, created_at DESC, plan_id ASC
                """,
                (collection_id, goal_id),
            ).fetchall()
        return tuple(self._plan_from_row(row) for row in rows)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS goal_experiment_plans (
                    plan_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_message_id TEXT,
                    source_links TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_goal_experiment_plans_goal
                ON goal_experiment_plans(collection_id, goal_id, updated_at)
                """
            )

    def _plan_values(self, payload: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            str(payload["plan_id"]),
            str(payload["collection_id"]),
            str(payload["goal_id"]),
            str(payload["title"]),
            str(payload["content"]),
            str(payload["status"]),
            _optional_text(payload.get("source_message_id")),
            _dump_json_list(payload.get("source_links")),
            _dump_json_object(payload.get("metadata")),
            _optional_text(payload.get("created_by")),
            str(payload["created_at"]),
            str(payload["updated_at"]),
        )

    def _plan_from_row(self, row: sqlite3.Row) -> ExperimentPlanRecord:
        return ExperimentPlanRecord.from_mapping(
            {
                "plan_id": row["plan_id"],
                "collection_id": row["collection_id"],
                "goal_id": row["goal_id"],
                "title": row["title"],
                "content": row["content"],
                "status": row["status"],
                "source_message_id": row["source_message_id"],
                "source_links": _load_json_list(row["source_links"]),
                "metadata": _load_json_object(row["metadata"]),
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dump_json_list(value: Any) -> str:
    payload = value if isinstance(value, list | tuple) else []
    return json.dumps(payload, ensure_ascii=True)


def _dump_json_object(value: Any) -> str:
    payload = value if isinstance(value, Mapping) else {}
    return json.dumps(payload, ensure_ascii=True)


def _load_json_list(value: str) -> list[Any]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _load_json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}
