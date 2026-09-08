"""Embed public Evidence and Findings in their versioned analysis aggregate."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0055"
down_revision: str | Sequence[str] | None = "20260908_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "objective_analyses" not in tables:
        return

    metadata = sa.MetaData()
    analyses = sa.Table("objective_analyses", metadata, autoload_with=bind)
    evidence = (
        sa.Table("objective_evidence", metadata, autoload_with=bind)
        if "objective_evidence" in tables
        else None
    )
    findings = (
        sa.Table("objective_findings", metadata, autoload_with=bind)
        if "objective_findings" in tables
        else None
    )
    grouped: dict[tuple[str, str, int], dict[str, list[dict[str, Any]]]] = {}
    if evidence is not None:
        for row in bind.execute(sa.select(evidence)).mappings():
            key = (str(row["collection_id"]), str(row["objective_id"]), int(row["analysis_version"]))
            grouped.setdefault(key, {"evidence_records": [], "findings": []})[
                "evidence_records"
            ].append(dict(row.get("payload") or {}))
    if findings is not None:
        for row in bind.execute(sa.select(findings)).mappings():
            key = (str(row["collection_id"]), str(row["objective_id"]), int(row["analysis_version"]))
            payload = dict(row.get("payload") or {})
            payload.setdefault("display_rank", row.get("display_rank"))
            grouped.setdefault(key, {"evidence_records": [], "findings": []})[
                "findings"
            ].append(payload)

    for row in bind.execute(sa.select(analyses)).mappings():
        key = (str(row["collection_id"]), str(row["objective_id"]), int(row["analysis_version"]))
        payload = dict(row.get("payload") or {})
        values = grouped.get(key, {"evidence_records": [], "findings": []})
        payload.setdefault("evidence_records", values["evidence_records"])
        payload.setdefault("findings", values["findings"])
        bind.execute(
            analyses.update()
            .where(
                (analyses.c.collection_id == row["collection_id"])
                & (analyses.c.objective_id == row["objective_id"])
                & (analyses.c.analysis_version == row["analysis_version"])
            )
            .values(payload=payload)
        )

    _drop_finding_foreign_keys(bind)
    if "objective_evidence" in _tables(bind):
        op.drop_table("objective_evidence")
    if "objective_findings" in _tables(bind):
        op.drop_table("objective_findings")


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0055 is an irreversible merge of Objective result records"
    )


def _drop_finding_foreign_keys(bind: sa.Connection) -> None:
    for table_name in ("finding_feedback_records", "finding_curation_records"):
        if table_name not in _tables(bind):
            continue
        names = [
            str(foreign_key["name"])
            for foreign_key in sa.inspect(bind).get_foreign_keys(table_name)
            if foreign_key.get("name")
            and foreign_key.get("referred_table") == "objective_findings"
        ]
        if not names:
            continue
        with op.batch_alter_table(table_name, recreate="always") as batch:
            for name in names:
                batch.drop_constraint(name, type_="foreignkey")


def _tables(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())
