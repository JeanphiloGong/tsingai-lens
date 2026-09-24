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
        payload = dict(row["payload"] or {})
        checkpoints = payload.pop("document_evidence_checkpoints", None)
        if not isinstance(checkpoints, dict) or not checkpoints:
            continue
        for legacy_key, checkpoint in checkpoints.items():
            checkpoint_payload = (
                checkpoint if isinstance(checkpoint, dict) else {"value": checkpoint}
            )
            encoded = json.dumps(
                checkpoint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            document_id = checkpoint_payload.get("document_id")
            fingerprint = checkpoint_payload.get("input_fingerprint")
            bind.execute(
                sa.insert(legacy).values(
                    collection_id=row["collection_id"],
                    objective_id=row["objective_id"],
                    analysis_version=row["analysis_version"],
                    legacy_key=str(legacy_key),
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
        bind.execute(
            sa.update(analyses)
            .where(
                analyses.c.collection_id == row["collection_id"],
                analyses.c.objective_id == row["objective_id"],
                analyses.c.analysis_version == row["analysis_version"],
            )
            .values(payload=payload)
        )


def downgrade() -> None:
    op.drop_index(
        "ix_objective_analysis_legacy_checkpoints_objective",
        table_name="objective_analysis_legacy_checkpoints",
    )
    op.drop_table("objective_analysis_legacy_checkpoints")
