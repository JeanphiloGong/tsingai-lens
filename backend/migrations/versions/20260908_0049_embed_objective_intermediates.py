"""Embed resumable Objective intermediates in the analysis aggregate."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0049"
down_revision: str | Sequence[str] | None = "20260908_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    if "objective_analyses" not in tables:
        return

    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=("objective_analyses",))
    analyses = metadata.tables["objective_analyses"]
    if "objective_paper_contributions" in tables:
        metadata.reflect(bind=bind, only=("objective_paper_contributions",))
        contributions = metadata.tables["objective_paper_contributions"]
        grouped: dict[tuple[str, str, int], list[dict]] = {}
        for row in bind.execute(sa.select(contributions)).mappings():
            key = (row["collection_id"], row["objective_id"], row["analysis_version"])
            grouped.setdefault(key, []).append(dict(row["payload"] or {}))
        for key, items in grouped.items():
            _merge_payload(
                bind,
                analyses,
                key,
                "paper_contributions",
                sorted(items, key=lambda item: str(item.get("document_id") or "")),
            )

    if "objective_document_evidence_checkpoints" in tables:
        metadata.reflect(bind=bind, only=("objective_document_evidence_checkpoints",))
        checkpoints = metadata.tables["objective_document_evidence_checkpoints"]
        grouped_checkpoints: dict[tuple[str, str, int], dict[str, dict]] = {}
        for row in bind.execute(sa.select(checkpoints)).mappings():
            payload = dict(row["payload"] or {})
            analysis_version = int(payload.get("analysis_version") or 0)
            key = (row["collection_id"], row["objective_id"], analysis_version)
            storage_key = f"{row['document_id']}:{row['input_fingerprint']}"
            grouped_checkpoints.setdefault(key, {})[storage_key] = payload
        for key, items in grouped_checkpoints.items():
            _merge_payload(bind, analyses, key, "document_evidence_checkpoints", items)

    if "objective_evidence" in tables:
        constraints = {
            item["name"]
            for item in sa.inspect(bind).get_foreign_keys("objective_evidence")
        }
        if "fk_objective_evidence_contribution" in constraints:
            with op.batch_alter_table("objective_evidence") as batch:
                batch.drop_constraint("fk_objective_evidence_contribution", type_="foreignkey")
    if "objective_document_evidence_checkpoints" in _tables():
        op.drop_table("objective_document_evidence_checkpoints")
    if "objective_paper_contributions" in _tables():
        op.drop_table("objective_paper_contributions")


def downgrade() -> None:
    # The embedded records remain valid in the analysis payload. Recreating the
    # old tables without knowing which historical payloads were intentionally
    # deleted would create misleading relational rows, so downgrade is refused.
    if "objective_analyses" not in _tables():
        return
    raise RuntimeError(
        "20260908_0049 is an irreversible consolidation of private Objective intermediates"
    )


def _merge_payload(
    bind: sa.Connection,
    analyses: sa.Table,
    key: tuple[str, str, int],
    field: str,
    value: object,
) -> None:
    row = bind.execute(
        sa.select(analyses).where(
            analyses.c.collection_id == key[0],
            analyses.c.objective_id == key[1],
            analyses.c.analysis_version == key[2],
        )
    ).mappings().first()
    if row is None:
        return
    payload = dict(row["payload"] or {})
    payload[field] = value
    bind.execute(
        analyses.update()
        .where(
            analyses.c.collection_id == key[0],
            analyses.c.objective_id == key[1],
            analyses.c.analysis_version == key[2],
        )
        .values(payload=payload)
    )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())
