from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from config import DATA_DIR
from domain.protocol import ProtocolArtifactSet, ProtocolArtifactStatus


_TABLE = "derived_protocol_artifacts"
_PROCEDURE_BLOCK = "procedure_block"
_PROTOCOL_STEP = "protocol_step"


class SqliteProtocolArtifactRepository:
    """SQLite-backed persistence for derived protocol artifacts."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def replace_collection_artifacts(
        self,
        collection_id: str,
        artifacts: ProtocolArtifactSet,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                f"DELETE FROM {_TABLE} WHERE collection_id = ?",
                (collection_id,),
            )
            rows = [
                *self._artifact_rows(
                    collection_id,
                    _PROCEDURE_BLOCK,
                    artifacts.procedure_blocks,
                ),
                *self._artifact_rows(
                    collection_id,
                    _PROTOCOL_STEP,
                    artifacts.protocol_steps,
                ),
            ]
            connection.executemany(
                f"""
                INSERT INTO {_TABLE} (
                    collection_id,
                    artifact_type,
                    record_id,
                    sort_order,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    def read_collection_artifacts(self, collection_id: str) -> ProtocolArtifactSet:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT artifact_type, payload_json
                FROM {_TABLE}
                WHERE collection_id = ?
                ORDER BY artifact_type ASC, sort_order ASC, record_id ASC
                """,
                (collection_id,),
            ).fetchall()
        procedure_blocks: list[Mapping[str, Any]] = []
        protocol_steps: list[Mapping[str, Any]] = []
        for row in rows:
            payload = self._load_payload(row["payload_json"])
            if row["artifact_type"] == _PROCEDURE_BLOCK:
                procedure_blocks.append(payload)
            elif row["artifact_type"] == _PROTOCOL_STEP:
                protocol_steps.append(payload)
        return ProtocolArtifactSet(
            procedure_blocks=tuple(procedure_blocks),
            protocol_steps=tuple(protocol_steps),
        )

    def get_collection_status(self, collection_id: str) -> ProtocolArtifactStatus:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT artifact_type, COUNT(*) AS count
                FROM {_TABLE}
                WHERE collection_id = ?
                GROUP BY artifact_type
                """,
                (collection_id,),
            ).fetchall()
        counts = {str(row["artifact_type"]): int(row["count"]) for row in rows}
        procedure_blocks = counts.get(_PROCEDURE_BLOCK, 0)
        protocol_steps = counts.get(_PROTOCOL_STEP, 0)
        return ProtocolArtifactStatus(
            procedure_blocks_generated=procedure_blocks > 0,
            procedure_blocks_ready=procedure_blocks > 0,
            protocol_steps_generated=protocol_steps > 0,
            protocol_steps_ready=protocol_steps > 0,
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
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    collection_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(collection_id, artifact_type, record_id)
                )
                """
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{_TABLE}_collection_type_order
                ON {_TABLE}(collection_id, artifact_type, sort_order)
                """
            )

    def _artifact_rows(
        self,
        collection_id: str,
        artifact_type: str,
        records: tuple[Mapping[str, Any], ...],
    ) -> list[tuple[str, str, str, int, str]]:
        rows: list[tuple[str, str, str, int, str]] = []
        for position, record in enumerate(records):
            payload = _jsonable_mapping(record)
            record_id = _record_id(payload, artifact_type, position)
            rows.append(
                (
                    collection_id,
                    artifact_type,
                    record_id,
                    _sort_order(payload, position),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                )
            )
        return rows

    def _load_payload(self, payload_json: str) -> Mapping[str, Any]:
        payload = json.loads(payload_json)
        return payload if isinstance(payload, dict) else {}


def _record_id(payload: Mapping[str, Any], artifact_type: str, position: int) -> str:
    key = "step_id" if artifact_type == _PROTOCOL_STEP else "block_id"
    value = _text(payload.get(key))
    if value:
        return value
    return f"{artifact_type}_{position + 1}"


def _sort_order(payload: Mapping[str, Any], position: int) -> int:
    try:
        return int(payload.get("order") or position)
    except (TypeError, ValueError):
        return position


def _jsonable_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _jsonable(value)
        for key, value in payload.items()
    }


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray, dict)):
        try:
            return _jsonable(value.tolist())
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["SqliteProtocolArtifactRepository"]
