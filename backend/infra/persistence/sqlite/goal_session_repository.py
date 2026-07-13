from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from config import DATA_DIR


class SqliteGoalSessionRepository:
    """SQLite-backed persistence for Goal conversation sessions."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    user_id,
                    collection_id,
                    focused_material_id,
                    focused_paper_id,
                    focused_objective_id,
                    focused_goal_id,
                    goal_text,
                    goal_brief_json,
                    answer_mode,
                    rolling_summary,
                    last_evidence_ids,
                    last_material_ids,
                    last_paper_ids,
                    collection_data_version,
                    created_at,
                    updated_at
                FROM goal_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._session_from_row(row)

    def read_message_context(self, message_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    message_id,
                    session_id,
                    role,
                    content,
                    source_mode,
                    used_evidence_ids,
                    warnings,
                    links,
                    source_links,
                    created_at
                FROM goal_messages
                WHERE message_id = ?
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        message = self._message_from_row(row)
        session = self.read_session(message["session_id"])
        if session is None:
            return None
        return {
            "message": message,
            "session": session,
        }

    def write_session(self, payload: Mapping[str, Any]) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO goal_sessions (
                    session_id,
                    user_id,
                    collection_id,
                    focused_material_id,
                    focused_paper_id,
                    focused_objective_id,
                    focused_goal_id,
                    goal_text,
                    goal_brief_json,
                    answer_mode,
                    rolling_summary,
                    last_evidence_ids,
                    last_material_ids,
                    last_paper_ids,
                    collection_data_version,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    collection_id = excluded.collection_id,
                    focused_material_id = excluded.focused_material_id,
                    focused_paper_id = excluded.focused_paper_id,
                    focused_objective_id = excluded.focused_objective_id,
                    focused_goal_id = excluded.focused_goal_id,
                    goal_text = excluded.goal_text,
                    goal_brief_json = excluded.goal_brief_json,
                    answer_mode = excluded.answer_mode,
                    rolling_summary = excluded.rolling_summary,
                    last_evidence_ids = excluded.last_evidence_ids,
                    last_material_ids = excluded.last_material_ids,
                    last_paper_ids = excluded.last_paper_ids,
                    collection_data_version = excluded.collection_data_version,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                self._session_values(payload),
            )

    def read_messages(self, session_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    message_id,
                    session_id,
                    role,
                    content,
                    source_mode,
                    used_evidence_ids,
                    warnings,
                    links,
                    source_links,
                    created_at
                FROM goal_messages
                WHERE session_id = ?
                ORDER BY position ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def write_messages(
        self,
        session_id: str,
        messages: list[Mapping[str, Any]],
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM goal_messages WHERE session_id = ?",
                (session_id,),
            )
            connection.executemany(
                """
                INSERT INTO goal_messages (
                    message_id,
                    session_id,
                    position,
                    role,
                    content,
                    source_mode,
                    used_evidence_ids,
                    warnings,
                    links,
                    source_links,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    self._message_values(session_id, index, message)
                    for index, message in enumerate(messages)
                ],
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
                """
                CREATE TABLE IF NOT EXISTS goal_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    focused_material_id TEXT,
                    focused_paper_id TEXT,
                    focused_objective_id TEXT,
                    focused_goal_id TEXT,
                    goal_text TEXT,
                    goal_brief_json TEXT NOT NULL,
                    answer_mode TEXT NOT NULL,
                    rolling_summary TEXT NOT NULL,
                    last_evidence_ids TEXT NOT NULL,
                    last_material_ids TEXT NOT NULL,
                    last_paper_ids TEXT NOT NULL,
                    collection_data_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            try:
                connection.execute(
                    """
                    ALTER TABLE goal_sessions
                    ADD COLUMN focused_objective_id TEXT
                    """
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
            try:
                connection.execute(
                    """
                    ALTER TABLE goal_sessions
                    ADD COLUMN focused_goal_id TEXT
                    """
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS goal_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_mode TEXT,
                    used_evidence_ids TEXT NOT NULL,
                    warnings TEXT NOT NULL,
                    links TEXT NOT NULL,
                    source_links TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id)
                        REFERENCES goal_sessions(session_id)
                        ON DELETE CASCADE,
                    UNIQUE(session_id, position)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_goal_messages_session_position
                ON goal_messages(session_id, position)
                """
            )

    def _session_values(self, payload: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            str(payload["session_id"]),
            str(payload["user_id"]),
            str(payload["collection_id"]),
            _optional_text(payload.get("focused_material_id")),
            _optional_text(payload.get("focused_paper_id")),
            _optional_text(payload.get("focused_objective_id")),
            _optional_text(payload.get("focused_goal_id")),
            _optional_text(payload.get("goal_text")),
            _dump_json_object(payload.get("goal_brief_json")),
            str(payload["answer_mode"]),
            str(payload.get("rolling_summary") or ""),
            _dump_json_list(payload.get("last_evidence_ids")),
            _dump_json_list(payload.get("last_material_ids")),
            _dump_json_list(payload.get("last_paper_ids")),
            _optional_text(payload.get("collection_data_version")),
            str(payload["created_at"]),
            str(payload["updated_at"]),
        )

    def _message_values(
        self,
        session_id: str,
        index: int,
        payload: Mapping[str, Any],
    ) -> tuple[Any, ...]:
        return (
            str(payload["message_id"]),
            session_id,
            index,
            str(payload["role"]),
            str(payload.get("content") or payload.get("answer") or ""),
            _optional_text(payload.get("source_mode")),
            _dump_json_list(payload.get("used_evidence_ids")),
            _dump_json_list(payload.get("warnings")),
            _dump_json_object(payload.get("links")),
            _dump_json_list(payload.get("source_links")),
            str(payload["created_at"]),
        )

    def _session_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "collection_id": row["collection_id"],
            "focused_material_id": row["focused_material_id"],
            "focused_paper_id": row["focused_paper_id"],
            "focused_objective_id": row["focused_objective_id"],
            "focused_goal_id": row["focused_goal_id"],
            "goal_text": row["goal_text"],
            "goal_brief_json": _load_json_object(row["goal_brief_json"]),
            "answer_mode": row["answer_mode"],
            "rolling_summary": row["rolling_summary"],
            "last_evidence_ids": _load_json_list(row["last_evidence_ids"]),
            "last_material_ids": _load_json_list(row["last_material_ids"]),
            "last_paper_ids": _load_json_list(row["last_paper_ids"]),
            "collection_data_version": row["collection_data_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _message_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        record: dict[str, Any] = {
            "message_id": row["message_id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        if row["role"] == "assistant":
            record.update(
                {
                    "answer": row["content"],
                    "source_mode": row["source_mode"],
                    "used_evidence_ids": _load_json_list(row["used_evidence_ids"]),
                    "warnings": _load_json_list(row["warnings"]),
                    "links": _load_json_object(row["links"]),
                    "source_links": _load_json_list(row["source_links"]),
                }
            )
        return record


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dump_json_list(value: Any) -> str:
    payload = value if isinstance(value, list) else []
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
