from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    ConfirmedGoal,
    ComparisonRowRecord,
    CoreFactSet,
    PairwiseComparisonRelation,
    ResearchUnderstanding,
)


@dataclass(frozen=True)
class _TableSpec:
    table_name: str
    attr_name: str
    record_cls: type
    id_column: str
    columns: tuple[str, ...]
    json_columns: frozenset[str] = frozenset()
    integer_columns: frozenset[str] = frozenset()
    real_columns: frozenset[str] = frozenset()
    boolean_columns: frozenset[str] = frozenset()
    index_columns: tuple[str, ...] = ()


_COMPARISON_TABLES: tuple[_TableSpec, ...] = (
    _TableSpec(
        table_name="core_comparable_results",
        attr_name="comparable_results",
        record_cls=ComparableResult,
        id_column="comparable_result_id",
        columns=(
            "comparable_result_id",
            "source_result_id",
            "source_document_id",
            "binding",
            "normalized_context",
            "axis",
            "value",
            "evidence",
            "variant_label",
            "baseline_reference",
            "result_source_type",
            "epistemic_status",
            "normalization_version",
        ),
        json_columns=frozenset(
            {"binding", "normalized_context", "axis", "value", "evidence"}
        ),
        index_columns=("source_document_id", "source_result_id"),
    ),
    _TableSpec(
        table_name="core_collection_comparable_results",
        attr_name="collection_comparable_results",
        record_cls=CollectionComparableResult,
        id_column="comparable_result_id",
        columns=(
            "collection_id",
            "comparable_result_id",
            "assessment",
            "epistemic_status",
            "included",
            "sort_order",
            "policy_family",
            "policy_version",
            "comparable_result_normalization_version",
            "assessment_input_fingerprint",
            "reassessment_triggers",
        ),
        json_columns=frozenset({"assessment", "reassessment_triggers"}),
        integer_columns=frozenset({"sort_order"}),
        boolean_columns=frozenset({"included"}),
        index_columns=("comparable_result_id", "included", "sort_order"),
    ),
    _TableSpec(
        table_name="core_pairwise_comparison_relations",
        attr_name="pairwise_comparison_relations",
        record_cls=PairwiseComparisonRelation,
        id_column="relation_id",
        columns=(
            "relation_id",
            "collection_id",
            "document_id",
            "current_variant_id",
            "reference_variant_id",
            "comparison_axis",
            "property_normalized",
            "current_result_id",
            "reference_result_id",
            "current_value",
            "reference_value",
            "unit",
            "direction",
            "evidence_anchor_ids",
            "relation_payload",
            "confidence",
            "epistemic_status",
            "relation_version",
        ),
        json_columns=frozenset({"evidence_anchor_ids", "relation_payload"}),
        real_columns=frozenset({"current_value", "reference_value", "confidence"}),
        index_columns=(
            "document_id",
            "current_variant_id",
            "reference_variant_id",
            "property_normalized",
        ),
    ),
    _TableSpec(
        table_name="core_comparison_rows",
        attr_name="comparison_rows",
        record_cls=ComparisonRowRecord,
        id_column="row_id",
        columns=(
            "row_id",
            "collection_id",
            "comparable_result_id",
            "source_document_id",
            "variant_id",
            "variant_label",
            "variable_axis",
            "variable_value",
            "baseline_reference",
            "result_source_type",
            "result_type",
            "result_summary",
            "supporting_evidence_ids",
            "supporting_anchor_ids",
            "characterization_observation_ids",
            "structure_feature_ids",
            "material_system_normalized",
            "process_normalized",
            "property_normalized",
            "baseline_normalized",
            "test_condition_normalized",
            "comparability_status",
            "comparability_warnings",
            "comparability_basis",
            "requires_expert_review",
            "assessment_epistemic_status",
            "missing_critical_context",
            "value",
            "unit",
        ),
        json_columns=frozenset(
            {
                "variable_value",
                "supporting_evidence_ids",
                "supporting_anchor_ids",
                "characterization_observation_ids",
                "structure_feature_ids",
                "comparability_warnings",
                "comparability_basis",
                "missing_critical_context",
            }
        ),
        real_columns=frozenset({"value"}),
        boolean_columns=frozenset({"requires_expert_review"}),
        index_columns=(
            "comparable_result_id",
            "source_document_id",
            "variant_id",
            "material_system_normalized",
            "property_normalized",
            "baseline_normalized",
            "test_condition_normalized",
        ),
    ),
)

_ALL_TABLES = _COMPARISON_TABLES
_STATUS_TABLE = "core_fact_collection_status"
_RESEARCH_UNDERSTANDING_TABLE = "core_research_understanding_artifacts"
_CONFIRMED_GOAL_TABLE = "core_confirmed_goals"


class SqliteCoreFactRepository:
    """SQLite-backed persistence for Core semantic fact records."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def replace_collection_comparison_artifacts(
        self,
        collection_id: str,
        comparable_results: tuple[ComparableResult, ...],
        collection_comparable_results: tuple[CollectionComparableResult, ...],
        comparison_rows: tuple[ComparisonRowRecord, ...],
        pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = (),
    ) -> None:
        self._ensure_schema()
        records_by_attr = {
            "comparable_results": comparable_results,
            "collection_comparable_results": collection_comparable_results,
            "pairwise_comparison_relations": pairwise_comparison_relations,
            "comparison_rows": comparison_rows,
        }
        with self._connection() as connection:
            for spec in _COMPARISON_TABLES:
                self._delete_collection(connection, spec, collection_id)
            for spec in _COMPARISON_TABLES:
                self._insert_records(
                    connection,
                    spec,
                    collection_id,
                    records_by_attr[spec.attr_name],
                )
            self._upsert_status(
                connection,
                collection_id,
                comparison_artifacts_ready=True,
            )

    def read_collection_facts(self, collection_id: str) -> CoreFactSet:
        self._ensure_schema()
        with self._connection() as connection:
            records_by_attr = {
                spec.attr_name: self._read_records(connection, spec, collection_id)
                for spec in _ALL_TABLES
            }
            status = self._read_status(connection, collection_id, records_by_attr)
        return CoreFactSet(**status, **records_by_attr)

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
            ConfirmedGoal.from_mapping(self._load_json(row["payload"]))
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
            self._create_status_table(connection)
            for spec in _ALL_TABLES:
                self._create_table(connection, spec)
                self._create_indexes(connection, spec)
            self._create_research_understanding_table(connection)
            self._create_confirmed_goal_table(connection)

    def _create_status_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_STATUS_TABLE} (
                collection_id TEXT PRIMARY KEY,
                comparison_artifacts_ready INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def _upsert_status(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        *,
        comparison_artifacts_ready: bool | None = None,
    ) -> None:
        current = connection.execute(
            f"""
            SELECT comparison_artifacts_ready
            FROM {_STATUS_TABLE}
            WHERE collection_id = ?
            """,
            (collection_id,),
        ).fetchone()
        next_comparison_artifacts_ready = (
            bool(current["comparison_artifacts_ready"]) if current else False
        )
        if comparison_artifacts_ready is not None:
            next_comparison_artifacts_ready = bool(comparison_artifacts_ready)
        connection.execute(
            f"""
            INSERT INTO {_STATUS_TABLE} (
                collection_id,
                comparison_artifacts_ready
            )
            VALUES (?, ?)
            ON CONFLICT(collection_id) DO UPDATE SET
                comparison_artifacts_ready = excluded.comparison_artifacts_ready
            """,
            (
                collection_id,
                int(next_comparison_artifacts_ready),
            ),
        )

    def _read_status(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        records_by_attr: dict[str, tuple[Any, ...]],
    ) -> dict[str, bool]:
        row = connection.execute(
            f"""
            SELECT comparison_artifacts_ready
            FROM {_STATUS_TABLE}
            WHERE collection_id = ?
            """,
            (collection_id,),
        ).fetchone()
        if row is not None:
            return {
                "comparison_artifacts_ready": bool(
                    row["comparison_artifacts_ready"]
                ),
            }
        return {
            "comparison_artifacts_ready": any(
                records_by_attr[spec.attr_name] for spec in _COMPARISON_TABLES
            ),
        }

    def _create_table(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
    ) -> None:
        columns = [
            self._column_definition(spec, column)
            for column in self._storage_columns(spec)
        ]
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {spec.table_name} (
                {", ".join(columns)},
                PRIMARY KEY(collection_id, {spec.id_column})
            )
            """
        )

    def _create_indexes(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
    ) -> None:
        for column in spec.index_columns:
            if column == "collection_id":
                continue
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{spec.table_name}_{column}
                ON {spec.table_name}(collection_id, {column})
                """
            )

    def _create_research_understanding_table(self, connection: sqlite3.Connection) -> None:
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

    def _column_definition(self, spec: _TableSpec, column: str) -> str:
        if column == "collection_id" or column == spec.id_column:
            return f"{column} TEXT NOT NULL"
        return f"{column} {self._column_type(spec, column)}"

    def _column_type(self, spec: _TableSpec, column: str) -> str:
        if column in spec.integer_columns or column in spec.boolean_columns:
            return "INTEGER"
        if column in spec.real_columns:
            return "REAL"
        return "TEXT"

    def _insert_records(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
        collection_id: str,
        records: tuple[Any, ...],
    ) -> None:
        if not records:
            return
        columns = self._storage_columns(spec)
        placeholders = ", ".join("?" for _ in columns)
        connection.executemany(
            f"""
            INSERT INTO {spec.table_name} ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            [
                self._record_values(spec, collection_id, record)
                for record in records
            ],
        )

    def _record_values(
        self,
        spec: _TableSpec,
        collection_id: str,
        record: Any,
    ) -> tuple[Any, ...]:
        payload = record.to_record()
        values: list[Any] = []
        for column in self._storage_columns(spec):
            value = collection_id if column == "collection_id" else payload.get(column)
            values.append(self._store_value(spec, column, value))
        return tuple(values)

    def _read_records(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
        collection_id: str,
    ) -> tuple[Any, ...]:
        rows = connection.execute(
            f"""
            SELECT {", ".join(spec.columns)}
            FROM {spec.table_name}
            WHERE collection_id = ?
            ORDER BY {spec.id_column} ASC
            """,
            (collection_id,),
        ).fetchall()
        return tuple(
            spec.record_cls.from_mapping(self._payload_from_row(spec, row))
            for row in rows
        )

    def _payload_from_row(
        self,
        spec: _TableSpec,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        payload = dict(row)
        for column in spec.json_columns:
            if column in payload:
                payload[column] = self._load_json(payload[column])
        return payload

    def _delete_collection(
        self,
        connection: sqlite3.Connection,
        spec: _TableSpec,
        collection_id: str,
    ) -> None:
        connection.execute(
            f"DELETE FROM {spec.table_name} WHERE collection_id = ?",
            (collection_id,),
        )

    def _storage_columns(self, spec: _TableSpec) -> tuple[str, ...]:
        return ("collection_id",) + tuple(
            column for column in spec.columns if column != "collection_id"
        )

    def _store_value(self, spec: _TableSpec, column: str, value: Any) -> Any:
        if column in spec.json_columns:
            return json.dumps(
                self._normalize_json_value(value),
                ensure_ascii=False,
                sort_keys=True,
            )
        if column in spec.boolean_columns:
            return int(bool(value))
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

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
