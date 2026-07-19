from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from domain.core import ResearchUnderstanding

_RESEARCH_UNDERSTANDING_TABLE = "core_research_understanding_artifacts"


class SqliteResearchUnderstandingRepository:
    """SQLite-backed persistence for research-understanding records."""

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


__all__ = ["SqliteResearchUnderstandingRepository"]
