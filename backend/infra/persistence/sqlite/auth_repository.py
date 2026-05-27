from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from config import DATA_DIR


class SqliteAuthRepository:
    """SQLite-backed users and browser sessions."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def read_user_by_email(self, email: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, created_at
                FROM auth_users
                WHERE lower(email) = lower(?)
                """,
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def read_user(self, user_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, created_at
                FROM auth_users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def write_user(self, payload: Mapping[str, Any]) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO auth_users (
                    user_id,
                    email,
                    display_name,
                    password_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name,
                    password_hash = excluded.password_hash
                """,
                (
                    str(payload["user_id"]),
                    str(payload["email"]),
                    _optional_text(payload.get("display_name")),
                    str(payload["password_hash"]),
                    str(payload["created_at"]),
                ),
            )

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT session_id, user_id, created_at, expires_at, revoked_at
                FROM auth_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def write_session(self, payload: Mapping[str, Any]) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (
                    session_id,
                    user_id,
                    created_at,
                    expires_at,
                    revoked_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    expires_at = excluded.expires_at,
                    revoked_at = excluded.revoked_at
                """,
                (
                    str(payload["session_id"]),
                    str(payload["user_id"]),
                    str(payload["created_at"]),
                    str(payload["expires_at"]),
                    _optional_text(payload.get("revoked_at")),
                ),
            )

    def revoke_session(self, session_id: str, revoked_at: str) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE session_id = ?
                """,
                (revoked_at, session_id),
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
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id)
                        REFERENCES auth_users(user_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
                ON auth_sessions(user_id)
                """
            )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["SqliteAuthRepository"]
