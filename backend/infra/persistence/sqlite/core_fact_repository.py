from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from domain.core import (
    ConfirmedGoal,
    ResearchUnderstanding,
)

_RESEARCH_UNDERSTANDING_TABLE = "core_research_understanding_artifacts"
_CONFIRMED_GOAL_TABLE = "core_confirmed_goals"


class SqliteCoreFactRepository:
    """SQLite-backed persistence for Core semantic fact records."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def replace_collection_research_understandings(
        self,
        collection_id: str,
        understandings: tuple[ResearchUnderstanding, ...],
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                f"DELETE FROM {_RESEARCH_UNDERSTANDING_TABLE} WHERE collection_id = ?",
                (collection_id,),
            )
            for understanding in understandings:
                self._upsert_research_understanding_row(
                    connection,
                    collection_id,
                    understanding,
                )

    def upsert_research_understanding(
        self,
        collection_id: str,
        understanding: ResearchUnderstanding,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            self._upsert_research_understanding_row(
                connection,
                collection_id,
                understanding,
            )

    def read_research_understanding(
        self,
        collection_id: str,
        scope_type: str,
        scope_id: str,
    ) -> ResearchUnderstanding | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT payload
                FROM {_RESEARCH_UNDERSTANDING_TABLE}
                WHERE collection_id = ? AND scope_type = ? AND scope_id = ?
                """,
                (collection_id, scope_type, scope_id),
            ).fetchone()
        if row is None:
            return None
        return ResearchUnderstanding.from_mapping(self._load_json(row["payload"]))

    def list_research_understandings(
        self,
        collection_id: str,
        scope_type: str | None = None,
    ) -> tuple[ResearchUnderstanding, ...]:
        self._ensure_schema()
        params: tuple[str, ...]
        where_clause = "collection_id = ?"
        if scope_type:
            where_clause = "collection_id = ? AND scope_type = ?"
            params = (collection_id, scope_type)
        else:
            params = (collection_id,)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT payload
                FROM {_RESEARCH_UNDERSTANDING_TABLE}
                WHERE {where_clause}
                ORDER BY scope_type ASC, scope_id ASC
                """,
                params,
            ).fetchall()
        return tuple(
            ResearchUnderstanding.from_mapping(self._load_json(row["payload"]))
            for row in rows
        )

    def upsert_confirmed_goal(self, goal: ConfirmedGoal) -> ConfirmedGoal:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT created_at
                FROM {_CONFIRMED_GOAL_TABLE}
                WHERE collection_id = ? AND goal_id = ?
                """,
                (goal.collection_id, goal.goal_id),
            ).fetchone()
            created_at = (
                goal.created_at
                or (str(row["created_at"]) if row is not None else None)
                or self._sqlite_utc_now(connection)
            )
            updated_at = goal.updated_at or self._sqlite_utc_now(connection)
            normalized = ConfirmedGoal.from_mapping(
                {
                    **goal.to_record(),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
            payload = normalized.to_record()
            connection.execute(
                f"""
                INSERT INTO {_CONFIRMED_GOAL_TABLE} (
                    collection_id,
                    goal_id,
                    question,
                    source_type,
                    material_hints,
                    process_hints,
                    property_hints,
                    source_objective_id,
                    status,
                    analysis_error,
                    created_at,
                    updated_at,
                    payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id, goal_id)
                DO UPDATE SET
                    question = excluded.question,
                    source_type = excluded.source_type,
                    material_hints = excluded.material_hints,
                    process_hints = excluded.process_hints,
                    property_hints = excluded.property_hints,
                    source_objective_id = excluded.source_objective_id,
                    status = excluded.status,
                    analysis_error = excluded.analysis_error,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    normalized.collection_id,
                    normalized.goal_id,
                    normalized.question,
                    normalized.source_type,
                    json.dumps(list(normalized.material_hints), ensure_ascii=False),
                    json.dumps(list(normalized.process_hints), ensure_ascii=False),
                    json.dumps(list(normalized.property_hints), ensure_ascii=False),
                    normalized.source_objective_id,
                    normalized.status,
                    normalized.analysis_error,
                    normalized.created_at,
                    normalized.updated_at,
                    json.dumps(
                        self._normalize_json_value(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
        return normalized

    def read_confirmed_goal(
        self,
        collection_id: str,
        goal_id: str,
    ) -> ConfirmedGoal | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT payload
                FROM {_CONFIRMED_GOAL_TABLE}
                WHERE collection_id = ? AND goal_id = ?
                """,
                (collection_id, goal_id),
            ).fetchone()
        if row is None:
            return None
        return ConfirmedGoal.from_mapping(self._load_json(row["payload"]))

    def list_confirmed_goals(self, collection_id: str) -> tuple[ConfirmedGoal, ...]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT payload
                FROM {_CONFIRMED_GOAL_TABLE}
                WHERE collection_id = ?
                ORDER BY created_at ASC, goal_id ASC
                """,
                (collection_id,),
            ).fetchall()
        return tuple(
            ConfirmedGoal.from_mapping(self._load_json(row["payload"])) for row in rows
        )

    def _upsert_research_understanding_row(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        understanding: ResearchUnderstanding,
    ) -> None:
        payload = understanding.to_record()
        scope = understanding.scope
        connection.execute(
            f"""
            INSERT INTO {_RESEARCH_UNDERSTANDING_TABLE} (
                collection_id,
                scope_type,
                scope_id,
                schema_version,
                state,
                payload
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_id, scope_type, scope_id)
            DO UPDATE SET
                schema_version = excluded.schema_version,
                state = excluded.state,
                payload = excluded.payload
            """,
            (
                collection_id,
                scope.scope_type,
                understanding.scope_id,
                understanding.schema_version,
                understanding.state,
                json.dumps(
                    self._normalize_json_value(payload),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
            self._create_research_understanding_table(connection)
            self._create_confirmed_goal_table(connection)

    def _create_research_understanding_table(
        self, connection: sqlite3.Connection
    ) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_RESEARCH_UNDERSTANDING_TABLE} (
                collection_id TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                state TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(collection_id, scope_type, scope_id)
            )
            """
        )
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{_RESEARCH_UNDERSTANDING_TABLE}_scope_type
            ON {_RESEARCH_UNDERSTANDING_TABLE}(collection_id, scope_type)
            """
        )

    def _create_confirmed_goal_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_CONFIRMED_GOAL_TABLE} (
                collection_id TEXT NOT NULL,
                goal_id TEXT NOT NULL,
                question TEXT NOT NULL,
                source_type TEXT NOT NULL,
                material_hints TEXT NOT NULL,
                process_hints TEXT NOT NULL,
                property_hints TEXT NOT NULL,
                source_objective_id TEXT,
                status TEXT NOT NULL,
                analysis_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(collection_id, goal_id)
            )
            """
        )
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{_CONFIRMED_GOAL_TABLE}_status
            ON {_CONFIRMED_GOAL_TABLE}(collection_id, status)
            """
        )
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{_CONFIRMED_GOAL_TABLE}_source_objective
            ON {_CONFIRMED_GOAL_TABLE}(collection_id, source_objective_id)
            """
        )

    def _sqlite_utc_now(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS now"
        ).fetchone()
        return str(row["now"])

    def _load_json(self, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return None
        return json.loads(text)

    def _normalize_json_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, dict):
            return {
                str(key): self._normalize_json_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_json_value(item) for item in value]
        if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
            converted = value.tolist()
            if converted is not value:
                return self._normalize_json_value(converted)
        if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
            try:
                return self._normalize_json_value(value.item())
            except Exception:
                return value
        return value


__all__ = ["SqliteCoreFactRepository"]
