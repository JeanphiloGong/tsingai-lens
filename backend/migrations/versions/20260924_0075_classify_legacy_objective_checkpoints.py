"""Classify retired per-document Objective checkpoints and remove them from snapshots.

The automatic analysis path now persists PaperExperiment revisions.  Older
analysis payloads may still contain the embedded
``document_evidence_checkpoints`` map created before that cutover.  Those
records cannot be promoted without re-checking their sample/test bindings, so
the migration keeps a hash and review state instead of guessing a mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0075"
down_revision = "20260924_0074"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_AUTOINCREMENT_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_RECORD_SOURCE_KEY = "scientific_record_source"


def _bounded_legacy_key(value: object) -> str:
    text = str(value)
    if len(text) <= 400:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{text[:335]}:{digest}"


def _checkpoint_payloads(value: object) -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [(str(key), item) for key, item in value.items()]
    if value is None:
        return []
    return [("__invalid_checkpoint_payload__", value)]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "objective_analyses" not in tables:
        return

    if "objective_analysis_legacy_checkpoints" not in tables:
        op.create_table(
            "objective_analysis_legacy_checkpoints",
            sa.Column("id", _AUTOINCREMENT_ID, autoincrement=True, nullable=False),
            sa.Column("collection_id", sa.String(length=64), nullable=False),
            sa.Column("objective_id", sa.String(length=128), nullable=False),
            sa.Column("analysis_version", sa.Integer(), nullable=False),
            sa.Column("legacy_key", sa.String(length=400), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=True),
            sa.Column("input_fingerprint", sa.String(length=128), nullable=True),
            sa.Column("checkpoint_status", sa.String(length=32), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("classification", sa.String(length=40), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint(
                "id", name="pk_objective_analysis_legacy_checkpoints"
            ),
            sa.UniqueConstraint(
                "collection_id",
                "objective_id",
                "analysis_version",
                "legacy_key",
                name="uq_objective_analysis_legacy_checkpoint_key",
            ),
        )
        op.create_index(
            "ix_objective_analysis_legacy_checkpoints_objective",
            "objective_analysis_legacy_checkpoints",
            ["collection_id", "objective_id", "analysis_version"],
        )

    metadata = sa.MetaData()
    analyses = sa.Table("objective_analyses", metadata, autoload_with=bind)
    legacy = sa.Table(
        "objective_analysis_legacy_checkpoints", metadata, autoload_with=bind
    )
    rows = bind.execute(
        sa.select(
            analyses.c.collection_id,
            analyses.c.objective_id,
            analyses.c.analysis_version,
            analyses.c.payload,
        )
    ).mappings()
    now = datetime.now(timezone.utc)
    for row in rows:
        raw_payload = row["payload"]
        if isinstance(raw_payload, dict):
            payload = dict(raw_payload)
        else:
            # Keep malformed historical JSON available for manual inspection
            # while giving the runtime a valid ObjectiveAnalysis mapping.
            payload = {"legacy_payload": raw_payload}
        had_checkpoint_key = "document_evidence_checkpoints" in payload
        checkpoints = payload.pop("document_evidence_checkpoints", None)
        for legacy_key, checkpoint in _checkpoint_payloads(checkpoints):
            checkpoint_payload = (
                checkpoint if isinstance(checkpoint, dict) else {"value": checkpoint}
            )
            bounded_key = _bounded_legacy_key(legacy_key)
            encoded = json.dumps(
                checkpoint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            document_id = checkpoint_payload.get("document_id")
            fingerprint = checkpoint_payload.get("input_fingerprint")
            already_classified = bind.execute(
                sa.select(legacy.c.id).where(
                    legacy.c.collection_id == row["collection_id"],
                    legacy.c.objective_id == row["objective_id"],
                    legacy.c.analysis_version == row["analysis_version"],
                    legacy.c.legacy_key == bounded_key,
                )
            ).first()
            if already_classified is None:
                bind.execute(
                    sa.insert(legacy).values(
                        collection_id=row["collection_id"],
                        objective_id=row["objective_id"],
                        analysis_version=row["analysis_version"],
                        legacy_key=bounded_key,
                        document_id=str(document_id) if document_id else None,
                        input_fingerprint=(
                            str(fingerprint) if fingerprint else None
                        ),
                        checkpoint_status=(
                            str(checkpoint_payload.get("status"))
                            if checkpoint_payload.get("status")
                            else None
                        ),
                        payload_hash=hashlib.sha256(encoded).hexdigest(),
                        classification="manual_review_required",
                        reason=(
                            "Retired per-document checkpoint cannot be promoted to a "
                            "PaperExperiment without rechecking source bindings."
                        ),
                        created_at=now,
                    )
                )
        origin = payload.get("origin")
        if origin in (None, "system_generated"):
            # Every row that predates the experiment writer is an explicit
            # read-only legacy snapshot, including a valid scientific abstention
            # with no checkpoint or result rows. New automatic rows write the
            # experiment_graph marker themselves.
            if payload.get(_RECORD_SOURCE_KEY) not in {
                "experiment_graph",
                "legacy_snapshot",
            }:
                payload[_RECORD_SOURCE_KEY] = "legacy_snapshot"
        elif origin in {"human_authored", "agent_authored", "hybrid"}:
            if payload.get(_RECORD_SOURCE_KEY) != "authored_snapshot":
                payload[_RECORD_SOURCE_KEY] = "authored_snapshot"
        if had_checkpoint_key or payload != (raw_payload if isinstance(raw_payload, dict) else {}):
            bind.execute(
                sa.update(analyses)
                .where(
                    analyses.c.collection_id == row["collection_id"],
                    analyses.c.objective_id == row["objective_id"],
                    analyses.c.analysis_version == row["analysis_version"],
                )
                .values(payload=payload, updated_at=now)
            )


def downgrade() -> None:
    raise RuntimeError(
        "20260924_0075 is irreversible: legacy checkpoint payloads were removed "
        "after their audit hashes were retained"
    )
