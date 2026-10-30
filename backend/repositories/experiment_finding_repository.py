"""PostgreSQL repository for experiment finding."""

from __future__ import annotations

from domain.core.finding import Finding, FindingMechanismRelation
from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificContext,
)
from infra.persistence.postgres.models.comparison_group import (
    ComparisonGroupMemberRow,
    ComparisonGroupRow,
)
from infra.persistence.postgres.models.experiment_finding import (
    ExperimentFindingRow,
    FindingComparisonGroupRow,
    FindingSelectionRow,
)
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord
from infra.persistence.postgres.models.objective_experiment_selection import (
    ObjectiveExperimentSelectionRow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ExperimentFindingRepository:
    """Write and read Findings whose scientific inputs are explicit selections."""

    backend_name = "postgresql"

    async def add_finding(
        self,
        db: AsyncSession,
        finding: Finding,
    ) -> Finding:
        return await _add_finding(db, finding)

    async def read_finding(
        self,
        db: AsyncSession,
        collection_id: str,
        finding_id: str,
    ) -> Finding | None:
        row = await db.scalar(
            select(ExperimentFindingRow).where(
                ExperimentFindingRow.collection_id == collection_id,
                ExperimentFindingRow.finding_id == finding_id,
            )
        )
        return await load_experiment_finding(db, row) if row is not None else None

    async def list_findings(
        self,
        db: AsyncSession,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[Finding, ...]:
        rows = tuple(
            await db.scalars(
                select(ExperimentFindingRow)
                .where(
                    ExperimentFindingRow.collection_id == collection_id,
                    ExperimentFindingRow.objective_id == objective_id,
                    ExperimentFindingRow.analysis_version == analysis_version,
                )
                .order_by(ExperimentFindingRow.display_rank, ExperimentFindingRow.finding_id)
            )
        )
        records: list[Finding] = []
        for row in rows:
            records.append(await load_experiment_finding(db, row))
        return tuple(records)


async def _add_finding(
    db: AsyncSession,
    finding: Finding,
) -> Finding:
    if not finding.selection_ids:
        raise ValueError("experiment-backed Finding requires selections")
    if finding.paper_contributions:
        raise ValueError("experiment-backed Finding cannot copy legacy evidence")

    existing = await db.scalar(
        select(ExperimentFindingRow).where(
            ExperimentFindingRow.finding_id == finding.finding_id
        )
    )
    if existing is not None:
        restored = await load_experiment_finding(db, existing)
        if restored == finding:
            return restored
        raise ValueError("finding identity already exists")

    selections, groups = await _validate_context(db, finding)
    row = ExperimentFindingRow(
        finding_id=finding.finding_id,
        collection_id=finding.collection_id,
        objective_id=finding.objective_id,
        analysis_version=finding.analysis_version,
        statement=finding.statement,
        factors_json=list(finding.factors),
        outcome=finding.outcome,
        direction=finding.direction,
        assertion_strength=finding.assertion_strength,
        attribution_scope=finding.attribution_scope,
        synthesis_status=finding.synthesis_status,
        certainty=finding.certainty,
        display_rank=finding.display_rank,
        mechanisms_json=[
            {
                "source_term": item.source_term,
                "relation_type": item.relation_type,
                "target_term": item.target_term,
                "direction": item.direction,
                "assertion_strength": item.assertion_strength,
                "supporting_evidence_ids": list(item.supporting_evidence_ids),
            }
            for item in finding.mechanisms
        ],
        scientific_context_json={
            "material": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.material
            ],
            "sample": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.sample
            ],
            "process": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.process
            ],
            "test": [
                {
                    "name": attribute.name,
                    "value": attribute.value,
                    "unit": attribute.unit,
                    **(
                        {"context_scope": attribute.context_scope}
                        if attribute.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.test
            ],
        },
        limitations_json=list(finding.limitations),
        origin=finding.origin,
        source_analysis_version=finding.source_analysis_version,
        parent_finding_id=finding.parent_finding_id,
        created_by_user_id=finding.created_by_user_id,
        created_by_tool_call_id=finding.created_by_tool_call_id,
        created_at=finding.created_at,
        warnings_json=list(finding.warnings),
    )
    db.add(row)
    db.add_all(
        FindingSelectionRow(
            finding_id=finding.finding_id,
            selection_id=selection.selection_id,
        )
        for selection in selections
    )
    db.add_all(
        FindingComparisonGroupRow(
            finding_id=finding.finding_id,
            group_id=group.group_id,
        )
        for group in groups
    )
    await db.flush()
    return finding


async def _validate_context(
    db: AsyncSession,
    finding: Finding,
) -> tuple[tuple[ObjectiveExperimentSelectionRow, ...], tuple[ComparisonGroupRow, ...]]:
    analysis = await db.scalar(
        select(ObjectiveAnalysisRecord).where(
            ObjectiveAnalysisRecord.collection_id == finding.collection_id,
            ObjectiveAnalysisRecord.objective_id == finding.objective_id,
            ObjectiveAnalysisRecord.analysis_version == finding.analysis_version,
        )
    )
    if analysis is None:
        raise ValueError("finding analysis snapshot was not found")

    selection_rows = tuple(
        await db.scalars(
            select(ObjectiveExperimentSelectionRow).where(
                ObjectiveExperimentSelectionRow.collection_id == finding.collection_id,
                ObjectiveExperimentSelectionRow.selection_id.in_(finding.selection_ids),
            )
        )
    )
    by_selection_id = {row.selection_id: row for row in selection_rows}
    if len(by_selection_id) != len(finding.selection_ids):
        raise ValueError("finding references an unknown selection")
    if any(
        row.objective_id != finding.objective_id
        or row.analysis_version != finding.analysis_version
        or row.outcome != finding.outcome
        for row in selection_rows
    ):
        raise ValueError("finding selections do not share analysis and outcome")

    group_rows: tuple[ComparisonGroupRow, ...] = ()
    if finding.comparison_group_ids:
        group_rows = tuple(
            await db.scalars(
                select(ComparisonGroupRow).where(
                    ComparisonGroupRow.collection_id == finding.collection_id,
                    ComparisonGroupRow.group_id.in_(finding.comparison_group_ids),
                )
            )
        )
        by_group_id = {row.group_id: row for row in group_rows}
        if len(by_group_id) != len(finding.comparison_group_ids):
            raise ValueError("finding references an unknown comparison group")
        if any(
            row.objective_id != finding.objective_id
            or row.analysis_version != finding.analysis_version
            or row.outcome != finding.outcome
            for row in group_rows
        ):
            raise ValueError("finding groups do not share analysis and outcome")

    finding.validate_experiment_support(
        frozenset(row.experiment_id for row in selection_rows)
    )

    if group_rows:
        group_members = tuple(
            await db.scalars(
                select(ComparisonGroupMemberRow).where(
                    ComparisonGroupMemberRow.group_id.in_(finding.comparison_group_ids)
                )
            )
        )
        member_ids = {item.selection_id for item in group_members}
        if not set(finding.selection_ids) <= member_ids:
            raise ValueError("finding selection is not a member of its comparison group")

    return selection_rows, group_rows


async def load_experiment_finding(
    db: AsyncSession,
    row: ExperimentFindingRow,
) -> Finding:
    selection_rows = tuple(
        await db.scalars(
            select(FindingSelectionRow)
            .where(FindingSelectionRow.finding_id == row.finding_id)
            .order_by(FindingSelectionRow.selection_id)
        )
    )
    group_rows = tuple(
        await db.scalars(
            select(FindingComparisonGroupRow)
            .where(FindingComparisonGroupRow.finding_id == row.finding_id)
            .order_by(FindingComparisonGroupRow.group_id)
        )
    )
    return Finding(
        collection_id=row.collection_id,
        objective_id=row.objective_id,
        analysis_version=row.analysis_version,
        finding_id=row.finding_id,
        statement=row.statement,
        factors=tuple(row.factors_json),
        outcome=row.outcome,
        direction=row.direction,
        assertion_strength=row.assertion_strength,
        attribution_scope=row.attribution_scope,
        synthesis_status=row.synthesis_status,
        certainty=row.certainty,
        display_rank=row.display_rank,
        mechanisms=tuple(
            FindingMechanismRelation(
                source_term=item["source_term"],
                relation_type=item["relation_type"],
                target_term=item["target_term"],
                direction=item["direction"],
                assertion_strength=item["assertion_strength"],
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
            )
            for item in row.mechanisms_json
        ),
        scientific_context=ScientificContext(
            material=tuple(
                ScientificAttribute(
                    name=item["name"],
                    value=item["value"],
                    unit=item["unit"],
                    context_scope=item.get("context_scope", "unknown"),
                    applies_to_outcomes=tuple(item.get("applies_to_outcomes", ())),
                )
                for item in row.scientific_context_json["material"]
            ),
            sample=tuple(
                ScientificAttribute(
                    name=item["name"],
                    value=item["value"],
                    unit=item["unit"],
                    context_scope=item.get("context_scope", "unknown"),
                    applies_to_outcomes=tuple(item.get("applies_to_outcomes", ())),
                )
                for item in row.scientific_context_json["sample"]
            ),
            process=tuple(
                ScientificAttribute(
                    name=item["name"],
                    value=item["value"],
                    unit=item["unit"],
                    context_scope=item.get("context_scope", "unknown"),
                    applies_to_outcomes=tuple(item.get("applies_to_outcomes", ())),
                )
                for item in row.scientific_context_json["process"]
            ),
            test=tuple(
                ScientificAttribute(
                    name=item["name"],
                    value=item["value"],
                    unit=item["unit"],
                    context_scope=item.get("context_scope", "unknown"),
                    applies_to_outcomes=tuple(item.get("applies_to_outcomes", ())),
                )
                for item in row.scientific_context_json["test"]
            )
        ),
        limitations=tuple(row.limitations_json),
        paper_contributions=(),
        origin=row.origin,
        source_analysis_version=row.source_analysis_version,
        parent_finding_id=row.parent_finding_id,
        created_by_user_id=row.created_by_user_id,
        created_by_tool_call_id=row.created_by_tool_call_id,
        created_at=row.created_at,
        warnings=tuple(row.warnings_json),
        selection_ids=tuple(item.selection_id for item in selection_rows),
        comparison_group_ids=tuple(item.group_id for item in group_rows),
    )


__all__ = ['ExperimentFindingRepository']


ExperimentFindingRepo = ExperimentFindingRepository()
