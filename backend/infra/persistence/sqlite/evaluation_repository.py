from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from domain.evaluation import (
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)


class SqliteEvaluationRepository:
    """SQLite-backed persistence for collection-bound evaluation records."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_gold_sets (
                    gold_id,
                    collection_id,
                    version,
                    target_layer,
                    metric_profile,
                    description,
                    metadata_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gold_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    version = excluded.version,
                    target_layer = excluded.target_layer,
                    metric_profile = excluded.metric_profile,
                    description = excluded.description,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    gold_set.gold_id,
                    gold_set.collection_id,
                    gold_set.version,
                    gold_set.target_layer,
                    gold_set.metric_profile,
                    gold_set.description,
                    _dump_json(gold_set.metadata or {}),
                    _now_iso(),
                ),
            )
            connection.execute(
                "DELETE FROM evaluation_gold_items WHERE gold_id = ?",
                (gold_set.gold_id,),
            )
            connection.executemany(
                """
                INSERT INTO evaluation_gold_items (
                    gold_item_id,
                    gold_id,
                    document_id,
                    family,
                    item_key,
                    payload_json,
                    evidence_refs_json,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.gold_item_id,
                        item.gold_id,
                        item.document_id,
                        item.family,
                        item.item_key,
                        _dump_json(item.payload),
                        _dump_json(item.evidence_refs),
                        _dump_json(item.metadata or {}),
                    )
                    for item in gold_items
                ],
            )

    def read_gold_set(self, gold_id: str) -> EvaluationGoldSet | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    gold_id,
                    collection_id,
                    version,
                    target_layer,
                    metric_profile,
                    description,
                    metadata_json
                FROM evaluation_gold_sets
                WHERE gold_id = ?
                """,
                (gold_id,),
            ).fetchone()
        if row is None:
            return None
        return EvaluationGoldSet.from_mapping(
            {
                "gold_id": row["gold_id"],
                "collection_id": row["collection_id"],
                "version": row["version"],
                "target_layer": row["target_layer"],
                "metric_profile": row["metric_profile"],
                "description": row["description"],
                "metadata": _load_json(row["metadata_json"]) or {},
            }
        )

    def list_gold_items(self, gold_id: str) -> tuple[EvaluationGoldItem, ...]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    gold_item_id,
                    gold_id,
                    document_id,
                    family,
                    item_key,
                    payload_json,
                    evidence_refs_json,
                    metadata_json
                FROM evaluation_gold_items
                WHERE gold_id = ?
                ORDER BY document_id ASC, family ASC, item_key ASC, gold_item_id ASC
                """,
                (gold_id,),
            ).fetchall()
        return tuple(self._gold_item_from_row(row) for row in rows)

    def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_prediction_snapshots (
                    snapshot_id,
                    collection_id,
                    target_layer,
                    fact_source,
                    system_context_json,
                    artifact_counts_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    target_layer = excluded.target_layer,
                    fact_source = excluded.fact_source,
                    system_context_json = excluded.system_context_json,
                    artifact_counts_json = excluded.artifact_counts_json
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.collection_id,
                    snapshot.target_layer,
                    snapshot.fact_source,
                    _dump_json(snapshot.system_context),
                    _dump_json(snapshot.artifact_counts),
                    _now_iso(),
                ),
            )
            connection.execute(
                "DELETE FROM evaluation_prediction_items WHERE snapshot_id = ?",
                (snapshot.snapshot_id,),
            )
            connection.executemany(
                """
                INSERT INTO evaluation_prediction_items (
                    snapshot_id,
                    item_id,
                    document_id,
                    family,
                    item_key,
                    payload_json,
                    source_refs_json,
                    confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot.snapshot_id,
                        item.item_id,
                        item.document_id,
                        item.family,
                        item.item_key,
                        _dump_json(item.payload),
                        _dump_json(item.source_refs),
                        item.confidence,
                    )
                    for item in snapshot.items
                ],
            )

    def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    snapshot_id,
                    collection_id,
                    target_layer,
                    fact_source,
                    system_context_json,
                    artifact_counts_json
                FROM evaluation_prediction_snapshots
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            if row is None:
                return None
            item_rows = connection.execute(
                """
                SELECT
                    item_id,
                    document_id,
                    family,
                    item_key,
                    payload_json,
                    source_refs_json,
                    confidence
                FROM evaluation_prediction_items
                WHERE snapshot_id = ?
                ORDER BY document_id ASC, family ASC, item_key ASC, item_id ASC
                """,
                (snapshot_id,),
            ).fetchall()
        return EvaluationPredictionSnapshot.from_mapping(
            {
                "snapshot_id": row["snapshot_id"],
                "collection_id": row["collection_id"],
                "target_layer": row["target_layer"],
                "fact_source": row["fact_source"],
                "system_context": _load_json(row["system_context_json"]) or {},
                "artifact_counts": _load_json(row["artifact_counts_json"]) or {},
                "items": [self._prediction_item_from_row(item) for item in item_rows],
            }
        )

    def upsert_evaluation_run(self, run: EvaluationRun) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_runs (
                    evaluation_run_id,
                    collection_id,
                    gold_id,
                    prediction_snapshot_id,
                    target_layer,
                    fact_source,
                    metric_profile,
                    status,
                    summary_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_run_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    gold_id = excluded.gold_id,
                    prediction_snapshot_id = excluded.prediction_snapshot_id,
                    target_layer = excluded.target_layer,
                    fact_source = excluded.fact_source,
                    metric_profile = excluded.metric_profile,
                    status = excluded.status,
                    summary_json = excluded.summary_json
                """,
                (
                    run.evaluation_run_id,
                    run.collection_id,
                    run.gold_id,
                    run.prediction_snapshot_id,
                    run.target_layer,
                    run.fact_source,
                    run.metric_profile,
                    run.status,
                    _dump_json(run.summary),
                    _now_iso(),
                ),
            )
            connection.execute(
                "DELETE FROM evaluation_scores WHERE evaluation_run_id = ?",
                (run.evaluation_run_id,),
            )
            connection.execute(
                "DELETE FROM evaluation_failures WHERE evaluation_run_id = ?",
                (run.evaluation_run_id,),
            )
            connection.executemany(
                """
                INSERT INTO evaluation_scores (
                    score_id,
                    evaluation_run_id,
                    document_id,
                    family,
                    metric,
                    value,
                    numerator,
                    denominator
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        score.score_id,
                        run.evaluation_run_id,
                        score.document_id,
                        score.family,
                        score.metric,
                        score.value,
                        score.numerator,
                        score.denominator,
                    )
                    for score in run.scores
                ],
            )
            connection.executemany(
                """
                INSERT INTO evaluation_failures (
                    failure_id,
                    evaluation_run_id,
                    document_id,
                    family,
                    failure_type,
                    likely_layer,
                    severity,
                    gold_item_id,
                    prediction_item_id,
                    gold_json,
                    prediction_json,
                    reason,
                    source_refs_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        failure.failure_id,
                        run.evaluation_run_id,
                        failure.document_id,
                        failure.family,
                        failure.failure_type,
                        failure.likely_layer,
                        failure.severity,
                        failure.gold_item_id,
                        failure.prediction_item_id,
                        _dump_json(failure.gold),
                        _dump_json(failure.prediction),
                        failure.reason,
                        _dump_json(failure.source_refs),
                    )
                    for failure in run.failures
                ],
            )

    def read_evaluation_run(self, evaluation_run_id: str) -> EvaluationRun | None:
        self._ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    evaluation_run_id,
                    collection_id,
                    gold_id,
                    prediction_snapshot_id,
                    target_layer,
                    fact_source,
                    metric_profile,
                    status,
                    summary_json
                FROM evaluation_runs
                WHERE evaluation_run_id = ?
                """,
                (evaluation_run_id,),
            ).fetchone()
            if row is None:
                return None
            return self._evaluation_run_from_row(connection, row)

    def list_evaluation_runs(self, collection_id: str) -> tuple[EvaluationRun, ...]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    evaluation_run_id,
                    collection_id,
                    gold_id,
                    prediction_snapshot_id,
                    target_layer,
                    fact_source,
                    metric_profile,
                    status,
                    summary_json
                FROM evaluation_runs
                WHERE collection_id = ?
                ORDER BY created_at DESC, evaluation_run_id DESC
                """,
                (collection_id,),
            ).fetchall()
            return tuple(self._evaluation_run_from_row(connection, row) for row in rows)

    def upsert_research_understanding_feedback(
        self,
        feedback: ResearchUnderstandingFeedback,
    ) -> ResearchUnderstandingFeedback:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_understanding_feedback (
                    feedback_id,
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    claim_id,
                    review_status,
                    issue_type,
                    note,
                    reviewer,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feedback_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    scope_type = excluded.scope_type,
                    scope_id = excluded.scope_id,
                    finding_id = excluded.finding_id,
                    claim_id = excluded.claim_id,
                    review_status = excluded.review_status,
                    issue_type = excluded.issue_type,
                    note = excluded.note,
                    reviewer = excluded.reviewer,
                    created_at = excluded.created_at
                """,
                (
                    feedback.feedback_id,
                    feedback.collection_id,
                    feedback.scope_type,
                    feedback.scope_id,
                    feedback.finding_id,
                    feedback.claim_id,
                    feedback.review_status,
                    feedback.issue_type,
                    feedback.note,
                    feedback.reviewer,
                    feedback.created_at,
                ),
            )
        return feedback

    def list_research_understanding_feedback(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingFeedback, ...]:
        self._ensure_schema()
        filters = ["collection_id = ?"]
        params: list[str] = [collection_id]
        if scope_type:
            filters.append("scope_type = ?")
            params.append(scope_type)
        if scope_id:
            filters.append("scope_id = ?")
            params.append(scope_id)
        if finding_id:
            filters.append("finding_id = ?")
            params.append(finding_id)
        if claim_id:
            filters.append("claim_id = ?")
            params.append(claim_id)
        where_clause = " AND ".join(filters)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    feedback_id,
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    claim_id,
                    review_status,
                    issue_type,
                    note,
                    reviewer,
                    created_at
                FROM research_understanding_feedback
                WHERE {where_clause}
                ORDER BY created_at DESC, feedback_id DESC
                """,
                tuple(params),
            ).fetchall()
        return tuple(self._feedback_from_row(row) for row in rows)

    def upsert_research_understanding_curation(
        self,
        curation: ResearchUnderstandingCuration,
    ) -> ResearchUnderstandingCuration:
        self._ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO research_understanding_curations (
                    curation_id,
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    claim_id,
                    curated_claim_type,
                    curated_status,
                    curated_statement,
                    curated_support_grade,
                    curated_review_status,
                    curated_variables_json,
                    curated_mediators_json,
                    curated_outcomes_json,
                    curated_direction,
                    curated_scope_summary,
                    curated_evidence_ref_ids_json,
                    curated_context_ids_json,
                    note,
                    reviewer,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(curation_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    scope_type = excluded.scope_type,
                    scope_id = excluded.scope_id,
                    finding_id = excluded.finding_id,
                    claim_id = excluded.claim_id,
                    curated_claim_type = excluded.curated_claim_type,
                    curated_status = excluded.curated_status,
                    curated_statement = excluded.curated_statement,
                    curated_support_grade = excluded.curated_support_grade,
                    curated_review_status = excluded.curated_review_status,
                    curated_variables_json = excluded.curated_variables_json,
                    curated_mediators_json = excluded.curated_mediators_json,
                    curated_outcomes_json = excluded.curated_outcomes_json,
                    curated_direction = excluded.curated_direction,
                    curated_scope_summary = excluded.curated_scope_summary,
                    curated_evidence_ref_ids_json = excluded.curated_evidence_ref_ids_json,
                    curated_context_ids_json = excluded.curated_context_ids_json,
                    note = excluded.note,
                    reviewer = excluded.reviewer,
                    updated_at = excluded.updated_at
                """,
                (
                    curation.curation_id,
                    curation.collection_id,
                    curation.scope_type,
                    curation.scope_id,
                    curation.finding_id,
                    curation.claim_id,
                    curation.curated_claim_type,
                    curation.curated_status,
                    curation.curated_statement,
                    curation.curated_support_grade,
                    curation.curated_review_status,
                    _dump_json(curation.curated_variables),
                    _dump_json(curation.curated_mediators),
                    _dump_json(curation.curated_outcomes),
                    curation.curated_direction,
                    curation.curated_scope_summary,
                    _dump_json(curation.curated_evidence_ref_ids),
                    _dump_json(curation.curated_context_ids),
                    curation.note,
                    curation.reviewer,
                    curation.updated_at,
                ),
            )
        return curation

    def list_research_understanding_curations(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingCuration, ...]:
        self._ensure_schema()
        filters = ["collection_id = ?"]
        params: list[str] = [collection_id]
        if scope_type:
            filters.append("scope_type = ?")
            params.append(scope_type)
        if scope_id:
            filters.append("scope_id = ?")
            params.append(scope_id)
        if finding_id:
            filters.append("finding_id = ?")
            params.append(finding_id)
        if claim_id:
            filters.append("claim_id = ?")
            params.append(claim_id)
        where_clause = " AND ".join(filters)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    curation_id,
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    claim_id,
                    curated_claim_type,
                    curated_status,
                    curated_statement,
                    curated_support_grade,
                    curated_review_status,
                    curated_variables_json,
                    curated_mediators_json,
                    curated_outcomes_json,
                    curated_direction,
                    curated_scope_summary,
                    curated_evidence_ref_ids_json,
                    curated_context_ids_json,
                    note,
                    reviewer,
                    updated_at
                FROM research_understanding_curations
                WHERE {where_clause}
                ORDER BY updated_at DESC, curation_id DESC
                """,
                tuple(params),
            ).fetchall()
        return tuple(self._curation_from_row(row) for row in rows)

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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evaluation_gold_sets (
                    gold_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    target_layer TEXT NOT NULL,
                    metric_profile TEXT NOT NULL,
                    description TEXT,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluation_gold_items (
                    gold_item_id TEXT PRIMARY KEY,
                    gold_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(gold_id) REFERENCES evaluation_gold_sets(gold_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_evaluation_gold_items_gold_family
                ON evaluation_gold_items(gold_id, family, document_id);

                CREATE TABLE IF NOT EXISTS evaluation_prediction_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    target_layer TEXT NOT NULL,
                    fact_source TEXT NOT NULL,
                    system_context_json TEXT NOT NULL,
                    artifact_counts_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_evaluation_snapshots_collection
                ON evaluation_prediction_snapshots(collection_id, fact_source);

                CREATE TABLE IF NOT EXISTS evaluation_prediction_items (
                    snapshot_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    confidence REAL,
                    PRIMARY KEY(snapshot_id, item_id),
                    FOREIGN KEY(snapshot_id)
                        REFERENCES evaluation_prediction_snapshots(snapshot_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_evaluation_prediction_items_family
                ON evaluation_prediction_items(snapshot_id, family, document_id);

                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    evaluation_run_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    gold_id TEXT NOT NULL,
                    prediction_snapshot_id TEXT NOT NULL,
                    target_layer TEXT NOT NULL,
                    fact_source TEXT NOT NULL,
                    metric_profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_evaluation_runs_collection
                ON evaluation_runs(collection_id, created_at);

                CREATE TABLE IF NOT EXISTS evaluation_scores (
                    score_id TEXT PRIMARY KEY,
                    evaluation_run_id TEXT NOT NULL,
                    document_id TEXT,
                    family TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    numerator REAL,
                    denominator REAL,
                    FOREIGN KEY(evaluation_run_id)
                        REFERENCES evaluation_runs(evaluation_run_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evaluation_failures (
                    failure_id TEXT PRIMARY KEY,
                    evaluation_run_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    likely_layer TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    gold_item_id TEXT,
                    prediction_item_id TEXT,
                    gold_json TEXT,
                    prediction_json TEXT,
                    reason TEXT,
                    source_refs_json TEXT NOT NULL,
                    FOREIGN KEY(evaluation_run_id)
                        REFERENCES evaluation_runs(evaluation_run_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_evaluation_failures_family
                ON evaluation_failures(evaluation_run_id, family, failure_type);

                CREATE TABLE IF NOT EXISTS research_understanding_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    finding_id TEXT,
                    claim_id TEXT,
                    review_status TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    note TEXT,
                    reviewer TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_understanding_feedback_scope
                ON research_understanding_feedback(
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    claim_id,
                    created_at
                );

                CREATE TABLE IF NOT EXISTS research_understanding_curations (
                    curation_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    finding_id TEXT,
                    claim_id TEXT,
                    curated_claim_type TEXT NOT NULL,
                    curated_status TEXT NOT NULL,
                    curated_statement TEXT NOT NULL,
                    curated_support_grade TEXT,
                    curated_review_status TEXT,
                    curated_variables_json TEXT NOT NULL DEFAULT '[]',
                    curated_mediators_json TEXT NOT NULL DEFAULT '[]',
                    curated_outcomes_json TEXT NOT NULL DEFAULT '[]',
                    curated_direction TEXT,
                    curated_scope_summary TEXT,
                    curated_evidence_ref_ids_json TEXT NOT NULL,
                    curated_context_ids_json TEXT NOT NULL,
                    note TEXT,
                    reviewer TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_understanding_curations_scope
                ON research_understanding_curations(
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    claim_id,
                    updated_at
                );
                """
            )
            self._ensure_column(
                connection,
                "research_understanding_feedback",
                "finding_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "finding_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_support_grade",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_review_status",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_variables_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_mediators_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_outcomes_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_direction",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "research_understanding_curations",
                "curated_scope_summary",
                "TEXT",
            )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column_name in existing:
            return
        try:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
            rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            if column_name not in {str(row["name"]) for row in rows}:
                raise

    def _gold_item_from_row(self, row: sqlite3.Row) -> EvaluationGoldItem:
        return EvaluationGoldItem.from_mapping(
            {
                "gold_item_id": row["gold_item_id"],
                "gold_id": row["gold_id"],
                "document_id": row["document_id"],
                "family": row["family"],
                "item_key": row["item_key"],
                "payload": _load_json(row["payload_json"]) or {},
                "evidence_refs": _load_json(row["evidence_refs_json"]) or [],
                "metadata": _load_json(row["metadata_json"]) or {},
            }
        )

    def _prediction_item_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return EvaluationPredictionItem.from_mapping(
            {
                "item_id": row["item_id"],
                "document_id": row["document_id"],
                "family": row["family"],
                "item_key": row["item_key"],
                "payload": _load_json(row["payload_json"]) or {},
                "source_refs": _load_json(row["source_refs_json"]) or [],
                "confidence": row["confidence"],
            }
        ).to_record()

    def _evaluation_run_from_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> EvaluationRun:
        run_id = row["evaluation_run_id"]
        scores = connection.execute(
            """
            SELECT
                score_id,
                evaluation_run_id,
                document_id,
                family,
                metric,
                value,
                numerator,
                denominator
            FROM evaluation_scores
            WHERE evaluation_run_id = ?
            ORDER BY family ASC, metric ASC, score_id ASC
            """,
            (run_id,),
        ).fetchall()
        failures = connection.execute(
            """
            SELECT
                failure_id,
                evaluation_run_id,
                document_id,
                family,
                failure_type,
                likely_layer,
                severity,
                gold_item_id,
                prediction_item_id,
                gold_json,
                prediction_json,
                reason,
                source_refs_json
            FROM evaluation_failures
            WHERE evaluation_run_id = ?
            ORDER BY document_id ASC, family ASC, failure_id ASC
            """,
            (run_id,),
        ).fetchall()
        return EvaluationRun.from_mapping(
            {
                "evaluation_run_id": row["evaluation_run_id"],
                "collection_id": row["collection_id"],
                "gold_id": row["gold_id"],
                "prediction_snapshot_id": row["prediction_snapshot_id"],
                "target_layer": row["target_layer"],
                "fact_source": row["fact_source"],
                "metric_profile": row["metric_profile"],
                "status": row["status"],
                "summary": _load_json(row["summary_json"]) or {},
                "scores": [
                    {
                        "score_id": score["score_id"],
                        "evaluation_run_id": score["evaluation_run_id"],
                        "document_id": score["document_id"],
                        "family": score["family"],
                        "metric": score["metric"],
                        "value": score["value"],
                        "numerator": score["numerator"],
                        "denominator": score["denominator"],
                    }
                    for score in scores
                ],
                "failures": [
                    {
                        "failure_id": failure["failure_id"],
                        "evaluation_run_id": failure["evaluation_run_id"],
                        "document_id": failure["document_id"],
                        "family": failure["family"],
                        "failure_type": failure["failure_type"],
                        "likely_layer": failure["likely_layer"],
                        "severity": failure["severity"],
                        "gold_item_id": failure["gold_item_id"],
                        "prediction_item_id": failure["prediction_item_id"],
                        "gold": _load_json(failure["gold_json"]),
                        "prediction": _load_json(failure["prediction_json"]),
                        "reason": failure["reason"],
                        "source_refs": _load_json(failure["source_refs_json"]) or [],
                    }
                    for failure in failures
                ],
            }
        )

    def _feedback_from_row(self, row: sqlite3.Row) -> ResearchUnderstandingFeedback:
        return ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": row["feedback_id"],
                "collection_id": row["collection_id"],
                "scope_type": row["scope_type"],
                "scope_id": row["scope_id"],
                "finding_id": row["finding_id"],
                "claim_id": row["claim_id"],
                "review_status": row["review_status"],
                "issue_type": row["issue_type"],
                "note": row["note"],
                "reviewer": row["reviewer"],
                "created_at": row["created_at"],
            }
        )

    def _curation_from_row(self, row: sqlite3.Row) -> ResearchUnderstandingCuration:
        return ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": row["curation_id"],
                "collection_id": row["collection_id"],
                "scope_type": row["scope_type"],
                "scope_id": row["scope_id"],
                "finding_id": row["finding_id"],
                "claim_id": row["claim_id"],
                "curated_claim_type": row["curated_claim_type"],
                "curated_status": row["curated_status"],
                "curated_statement": row["curated_statement"],
                "curated_support_grade": row["curated_support_grade"],
                "curated_review_status": row["curated_review_status"],
                "curated_variables": _load_json(row["curated_variables_json"]) or [],
                "curated_mediators": _load_json(row["curated_mediators_json"]) or [],
                "curated_outcomes": _load_json(row["curated_outcomes_json"]) or [],
                "curated_direction": row["curated_direction"],
                "curated_scope_summary": row["curated_scope_summary"],
                "curated_evidence_ref_ids": (
                    _load_json(row["curated_evidence_ref_ids_json"]) or []
                ),
                "curated_context_ids": _load_json(row["curated_context_ids_json"])
                or [],
                "note": row["note"],
                "reviewer": row["reviewer"],
                "updated_at": row["updated_at"],
            }
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump_json(value: Any) -> str:
    return json.dumps(_normalize_json_value(value), ensure_ascii=False, sort_keys=True)


def _load_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    return json.loads(text)


def _normalize_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json_value(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return _normalize_json_value(converted)
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return _normalize_json_value(value.item())
        except Exception:
            return value
    return value


__all__ = ["SqliteEvaluationRepository"]
