"""PostgreSQL repository for paper experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import (
    Any,
)

from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
    ReportedInterpretation,
    SourceReference,
)
from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificVariable,
)
from infra.persistence.postgres.models.paper_experiment import (
    ExperimentalVariantRow,
    ExperimentComparisonMeasurementRow,
    ExperimentComparisonRow,
    ExperimentMeasurementResultRow,
    ExperimentTestConditionRow,
    PaperExperimentRow,
    ReportedInterpretationRow,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class PaperExperimentRevisionConflictError(ValueError):
    """Raised when an existing experiment version would be overwritten."""


@dataclass(frozen=True)
class StoredPaperExperimentRevision:
    revision_id: int
    revision: PaperExperimentRevision
    created_at: datetime
    created_by: str | None = None
    archived_at: datetime | None = None


class PaperExperimentRepository:
    backend_name = "postgresql"

    async def lock_document(
        self,
        db: AsyncSession,
        document_id: str,
    ) -> None:
        """Serialize experiment identity resolution for one source document.

        A reread can change the content hash while still resolving to the
        same physical experiment.  Locking the document before per-identity
        reads keeps those fallback resolutions serialized and gives concurrent
        writers a deterministic document-level lock order.
        """

        if not document_id.strip():
            raise ValueError("paper experiment document lock requires document_id")
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"paper-experiment-document:{document_id}", 0)
                )
            )
        )

    async def add_revision(
        self,
        db: AsyncSession,
        revision: PaperExperimentRevision,
        *,
        created_by: str | None = None,
        created_at: datetime | None = None,
    ) -> StoredPaperExperimentRevision:
        return await _add_revision(
            db,
            revision,
            created_by=created_by,
            created_at=created_at,
        )

    async def read_revision(
        self,
        db: AsyncSession,
        experiment_id: str,
        experiment_version: int,
    ) -> StoredPaperExperimentRevision | None:
        row = await db.scalar(
            select(PaperExperimentRow).where(
                PaperExperimentRow.experiment_id == experiment_id,
                PaperExperimentRow.experiment_version == experiment_version,
            )
        )
        return await load_experiment_revision(db, row) if row is not None else None

    async def read_revision_by_id(
        self,
        db: AsyncSession,
        revision_id: int,
    ) -> StoredPaperExperimentRevision | None:
        row = await db.get(PaperExperimentRow, revision_id)
        return await load_experiment_revision(db, row) if row is not None else None

    async def read_latest_revision(
        self,
        db: AsyncSession,
        experiment_id: str,
    ) -> StoredPaperExperimentRevision | None:
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(experiment_id, 0)))
        )
        row = await db.scalar(
            select(PaperExperimentRow)
            .where(PaperExperimentRow.experiment_id == experiment_id)
            .order_by(PaperExperimentRow.experiment_version.desc())
            .limit(1)
        )
        return await load_experiment_revision(db, row) if row is not None else None

    async def list_latest_for_document(
        self,
        db: AsyncSession,
        document_id: str,
    ) -> tuple[StoredPaperExperimentRevision, ...]:
        rows = tuple(
            await db.scalars(
                select(PaperExperimentRow)
                .where(PaperExperimentRow.document_id == document_id)
                .order_by(
                    PaperExperimentRow.experiment_id,
                    PaperExperimentRow.experiment_version.desc(),
                )
            )
        )
        latest_rows: list[PaperExperimentRow] = []
        seen: set[str] = set()
        for row in rows:
            if row.experiment_id in seen:
                continue
            seen.add(row.experiment_id)
            latest_rows.append(row)
        return tuple([await load_experiment_revision(db, row) for row in latest_rows])


async def _add_revision(
    db: AsyncSession,
    revision: PaperExperimentRevision,
    *,
    created_by: str | None = None,
    created_at: datetime | None = None,
) -> StoredPaperExperimentRevision:
    validated = revision
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    existing = await db.scalar(
        select(PaperExperimentRow).where(
            PaperExperimentRow.experiment_id == validated.experiment_id,
            PaperExperimentRow.experiment_version == validated.experiment_version,
        )
    )
    if existing is not None:
        stored = await load_experiment_revision(db, existing)
        if stored.revision == validated:
            return stored
        raise PaperExperimentRevisionConflictError(
            "paper experiment revisions are immutable"
        )

    row = PaperExperimentRow(
        experiment_id=validated.experiment_id,
        experiment_version=validated.experiment_version,
        document_id=validated.document_id,
        source_fingerprint=validated.source_fingerprint,
        label=validated.label,
        scope_description=validated.scope_description,
        design_type=validated.design_type,
        identity_status=validated.identity_status,
        binding_status=validated.binding_status,
        source_refs_json=[
            {
                "document_id": item.document_id,
                "source_fingerprint": item.source_fingerprint,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "quote": item.quote,
            }
            for item in validated.source_refs
        ],
        unresolved_issues_json=[dict(item) for item in validated.unresolved_issues],
        created_at=timestamp,
        created_by=created_by,
        archived_at=None,
    )
    db.add(row)
    try:
        await db.flush()
        await _add_components(db, row.id, validated)
        await db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) == "uq_paper_experiment_identity_version":
            raise PaperExperimentRevisionConflictError(
                "paper experiment revision identity already exists"
            ) from exc
        raise
    return await load_experiment_revision(db, row)


async def _add_components(
    db: AsyncSession,
    paper_experiment_id: int,
    revision: PaperExperimentRevision,
) -> None:
    db.add_all(
        [
            ExperimentalVariantRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                variant_key=item.variant_key,
                variant_label=item.variant_label,
                subject_attributes_json=[
                    {
                        "name": value.name,
                        "value": value.value,
                        "unit": value.unit,
                        **(
                            {"context_scope": value.context_scope}
                            if value.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(value.applies_to_outcomes)}
                            if value.applies_to_outcomes
                            else {}
                        ),
                    }
                    for value in item.subject_attributes
                ],
                intervention_attributes_json=[
                    {
                        "name": value.name,
                        "value": value.value,
                        "unit": value.unit,
                        **(
                            {"context_scope": value.context_scope}
                            if value.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(value.applies_to_outcomes)}
                            if value.applies_to_outcomes
                            else {}
                        ),
                    }
                    for value in item.intervention_attributes
                ],
                state_json=[
                    {
                        "name": value.name,
                        "value": value.value,
                        "unit": value.unit,
                        **(
                            {"context_scope": value.context_scope}
                            if value.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(value.applies_to_outcomes)}
                            if value.applies_to_outcomes
                            else {}
                        ),
                    }
                    for value in item.state
                ],
                population_scope_json=(
                    dict(item.population_scope)
                    if item.population_scope is not None
                    else None
                ),
                source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.source_refs
                ],
                binding_source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.binding_source_refs
                ],
                binding_status=item.binding_status,
                notes_json=list(item.notes),
                identity_specificity=item.identity_specificity,
                missing_dimensions_json=list(item.missing_dimensions),
                identity_evidence_json=list(item.identity_evidence),
            )
            for position, item in enumerate(revision.variants)
        ]
    )
    db.add_all(
        [
            ExperimentTestConditionRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                test_key=item.test_key,
                test_type=item.test_type,
                parameters_json=[
                    {
                        "name": value.name,
                        "value": value.value,
                        "unit": value.unit,
                        **(
                            {"context_scope": value.context_scope}
                            if value.context_scope != "unknown"
                            else {}
                        ),
                        **(
                            {"applies_to_outcomes": list(value.applies_to_outcomes)}
                            if value.applies_to_outcomes
                            else {}
                        ),
                    }
                    for value in item.parameters
                ],
                population_scope_json=(
                    dict(item.population_scope)
                    if item.population_scope is not None
                    else None
                ),
                source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.source_refs
                ],
                binding_status=item.binding_status,
                notes_json=list(item.notes),
                protocol_specificity=item.protocol_specificity,
                test_identity_status=item.test_identity_status,
                protocol_completeness=item.protocol_completeness,
                missing_parameters_json=list(item.missing_parameters),
                method=item.method,
                standard=item.standard,
                outcome_scope_json=list(item.outcome_scope),
                binding_source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.binding_source_refs
                ],
                protocol_evidence_json=list(item.protocol_evidence),
            )
            for position, item in enumerate(revision.test_conditions)
        ]
    )
    await db.flush()

    measurement_rows: list[ExperimentMeasurementResultRow] = []
    for position, item in enumerate(revision.measurements):
        value_numeric, value_text = _stored_value(item.value)
        measurement_rows.append(
            ExperimentMeasurementResultRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                measurement_key=item.measurement_key,
                variant_key=item.variant_key,
                test_key=item.test_key,
                outcome=item.outcome,
                value_numeric=value_numeric,
                value_text=value_text,
                result_text=item.result_text,
                unit=item.unit,
                statistics_json=dict(item.statistics),
                measurement_scope_json=dict(item.measurement_scope),
                result_kind=item.result_kind,
                source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.source_refs
                ],
                binding_source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.binding_source_refs
                ],
                binding_status=item.binding_status,
                notes_json=list(item.notes),
            )
        )
    db.add_all(measurement_rows)

    comparison_rows = [
        ExperimentComparisonRow(
            paper_experiment_id=paper_experiment_id,
            position=position,
            comparison_key=item.comparison_key,
            baseline_variant_key=item.baseline_variant_key,
            target_variant_key=item.target_variant_key,
            outcome=item.outcome,
            changed_variables_json=[
                {
                    "name": value.name,
                    "baseline_value": value.baseline_value,
                    "target_value": value.target_value,
                    "unit": value.unit,
                }
                for value in item.changed_variables
            ],
            matched_conditions_json=[
                {
                    "name": value.name,
                    "value": value.value,
                    "unit": value.unit,
                    **(
                        {"context_scope": value.context_scope}
                        if value.context_scope != "unknown"
                        else {}
                    ),
                    **(
                        {"applies_to_outcomes": list(value.applies_to_outcomes)}
                        if value.applies_to_outcomes
                        else {}
                    ),
                }
                for value in item.matched_conditions
            ],
            basis=item.basis,
            direction=item.direction,
            reported_statement=item.reported_statement,
            attribution_scope=item.attribution_scope,
            status=item.status,
            reasons_json=list(item.reasons),
            source_refs_json=[
                {
                    "document_id": value.document_id,
                    "source_fingerprint": value.source_fingerprint,
                    "source_kind": value.source_kind,
                    "source_ref": value.source_ref,
                    "quote": value.quote,
                }
                for value in item.source_refs
            ],
            binding_source_refs_json=[
                {
                    "document_id": value.document_id,
                    "source_fingerprint": value.source_fingerprint,
                    "source_kind": value.source_kind,
                    "source_ref": value.source_ref,
                    "quote": value.quote,
                }
                for value in item.binding_source_refs
            ],
            relation_status=item.relation_status,
        )
        for position, item in enumerate(revision.comparisons)
    ]
    db.add_all(comparison_rows)
    await db.flush()

    links: list[ExperimentComparisonMeasurementRow] = []
    for comparison in revision.comparisons:
        for side, measurement_keys in (
            ("baseline", comparison.baseline_measurement_keys),
            ("target", comparison.target_measurement_keys),
        ):
            links.extend(
                ExperimentComparisonMeasurementRow(
                    paper_experiment_id=paper_experiment_id,
                    comparison_key=comparison.comparison_key,
                    side=side,
                    position=position,
                    measurement_key=measurement_key,
                )
                for position, measurement_key in enumerate(measurement_keys)
            )
    db.add_all(links)
    db.add_all(
        [
            ReportedInterpretationRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                statement=item.statement,
                kind=item.kind,
                measurement_keys_json=list(item.measurement_keys),
                comparison_keys_json=list(item.comparison_keys),
                source_refs_json=[
                    {
                        "document_id": value.document_id,
                        "source_fingerprint": value.source_fingerprint,
                        "source_kind": value.source_kind,
                        "source_ref": value.source_ref,
                        "quote": value.quote,
                    }
                    for value in item.source_refs
                ],
            )
            for position, item in enumerate(revision.reported_interpretations)
        ]
    )


async def load_experiment_revision(
    db: AsyncSession,
    row: PaperExperimentRow,
) -> StoredPaperExperimentRevision:
    revision_id = row.id
    variants = tuple(
        await db.scalars(
            select(ExperimentalVariantRow)
            .where(ExperimentalVariantRow.paper_experiment_id == revision_id)
            .order_by(ExperimentalVariantRow.position)
        )
    )
    tests = tuple(
        await db.scalars(
            select(ExperimentTestConditionRow)
            .where(ExperimentTestConditionRow.paper_experiment_id == revision_id)
            .order_by(ExperimentTestConditionRow.position)
        )
    )
    measurements = tuple(
        await db.scalars(
            select(ExperimentMeasurementResultRow)
            .where(ExperimentMeasurementResultRow.paper_experiment_id == revision_id)
            .order_by(ExperimentMeasurementResultRow.position)
        )
    )
    comparisons = tuple(
        await db.scalars(
            select(ExperimentComparisonRow)
            .where(ExperimentComparisonRow.paper_experiment_id == revision_id)
            .order_by(ExperimentComparisonRow.position)
        )
    )
    links = tuple(
        await db.scalars(
            select(ExperimentComparisonMeasurementRow)
            .where(
                ExperimentComparisonMeasurementRow.paper_experiment_id == revision_id
            )
            .order_by(
                ExperimentComparisonMeasurementRow.comparison_key,
                ExperimentComparisonMeasurementRow.side,
                ExperimentComparisonMeasurementRow.position,
            )
        )
    )
    interpretations = tuple(
        await db.scalars(
            select(ReportedInterpretationRow)
            .where(ReportedInterpretationRow.paper_experiment_id == revision_id)
            .order_by(ReportedInterpretationRow.position)
        )
    )

    links_by_comparison: dict[str, dict[str, list[str]]] = {}
    for link in links:
        sides = links_by_comparison.setdefault(
            link.comparison_key, {"baseline": [], "target": []}
        )
        sides[link.side].append(link.measurement_key)

    return StoredPaperExperimentRevision(
        revision_id=revision_id,
        revision=PaperExperimentRevision(
            experiment_id=row.experiment_id,
            document_id=row.document_id,
            experiment_version=row.experiment_version,
            source_fingerprint=row.source_fingerprint,
            label=row.label,
            scope_description=row.scope_description,
            design_type=row.design_type,
            identity_status=row.identity_status,
            binding_status=row.binding_status,
            variants=tuple(
                ExperimentalVariant(
                    variant_key=item.variant_key,
                    variant_label=item.variant_label,
                    subject_attributes=tuple(
                        ScientificAttribute(
                            name=value["name"],
                            value=value["value"],
                            unit=value["unit"],
                            context_scope=value.get("context_scope", "unknown"),
                            applies_to_outcomes=tuple(
                                value.get("applies_to_outcomes", ())
                            ),
                        )
                        for value in item.subject_attributes_json
                    ),
                    intervention_attributes=tuple(
                        ScientificAttribute(
                            name=value["name"],
                            value=value["value"],
                            unit=value["unit"],
                            context_scope=value.get("context_scope", "unknown"),
                            applies_to_outcomes=tuple(
                                value.get("applies_to_outcomes", ())
                            ),
                        )
                        for value in item.intervention_attributes_json
                    ),
                    state=tuple(
                        ScientificAttribute(
                            name=value["name"],
                            value=value["value"],
                            unit=value["unit"],
                            context_scope=value.get("context_scope", "unknown"),
                            applies_to_outcomes=tuple(
                                value.get("applies_to_outcomes", ())
                            ),
                        )
                        for value in item.state_json
                    ),
                    population_scope=item.population_scope_json,
                    source_refs=tuple(
                        SourceReference(**value) for value in item.source_refs_json
                    ),
                    binding_source_refs=tuple(
                        SourceReference(**value)
                        for value in item.binding_source_refs_json
                    ),
                    binding_status=item.binding_status,
                    notes=tuple(item.notes_json),
                    identity_specificity=item.identity_specificity,
                    missing_dimensions=tuple(item.missing_dimensions_json),
                    identity_evidence=tuple(item.identity_evidence_json),
                )
                for item in variants
            ),
            test_conditions=tuple(
                ExperimentTestCondition(
                    test_key=item.test_key,
                    test_type=item.test_type,
                    parameters=tuple(
                        ScientificAttribute(
                            name=value["name"],
                            value=value["value"],
                            unit=value["unit"],
                            context_scope=value.get("context_scope", "unknown"),
                            applies_to_outcomes=tuple(
                                value.get("applies_to_outcomes", ())
                            ),
                        )
                        for value in item.parameters_json
                    ),
                    population_scope=item.population_scope_json,
                    source_refs=tuple(
                        SourceReference(**value) for value in item.source_refs_json
                    ),
                    binding_status=item.binding_status,
                    notes=tuple(item.notes_json),
                    protocol_specificity=item.protocol_specificity,
                    test_identity_status=item.test_identity_status,
                    protocol_completeness=item.protocol_completeness,
                    missing_parameters=tuple(item.missing_parameters_json),
                    method=item.method,
                    standard=item.standard,
                    outcome_scope=tuple(item.outcome_scope_json),
                    binding_source_refs=tuple(
                        SourceReference(**value)
                        for value in item.binding_source_refs_json
                    ),
                    protocol_evidence=tuple(item.protocol_evidence_json),
                )
                for item in tests
            ),
            measurements=tuple(
                ExperimentMeasurementResult(
                    measurement_key=item.measurement_key,
                    outcome=item.outcome,
                    variant_key=item.variant_key,
                    test_key=item.test_key,
                    value=_domain_value(item.value_numeric, item.value_text),
                    unit=item.unit,
                    result_text=item.result_text,
                    statistics=item.statistics_json,
                    measurement_scope=item.measurement_scope_json,
                    result_kind=item.result_kind,
                    source_refs=tuple(
                        SourceReference(**value) for value in item.source_refs_json
                    ),
                    binding_source_refs=tuple(
                        SourceReference(**value)
                        for value in item.binding_source_refs_json
                    ),
                    binding_status=item.binding_status,
                    notes=tuple(item.notes_json),
                )
                for item in measurements
            ),
            comparisons=tuple(
                ExperimentComparison(
                    comparison_key=item.comparison_key,
                    baseline_variant_key=item.baseline_variant_key,
                    target_variant_key=item.target_variant_key,
                    outcome=item.outcome,
                    baseline_measurement_keys=tuple(
                        links_by_comparison[item.comparison_key]["baseline"]
                    ),
                    target_measurement_keys=tuple(
                        links_by_comparison[item.comparison_key]["target"]
                    ),
                    changed_variables=tuple(
                        ScientificVariable(**value)
                        for value in item.changed_variables_json
                    ),
                    matched_conditions=tuple(
                        ScientificAttribute(
                            name=value["name"],
                            value=value["value"],
                            unit=value["unit"],
                            context_scope=value.get("context_scope", "unknown"),
                            applies_to_outcomes=tuple(
                                value.get("applies_to_outcomes", ())
                            ),
                        )
                        for value in item.matched_conditions_json
                    ),
                    basis=item.basis,
                    direction=item.direction,
                    reported_statement=item.reported_statement,
                    attribution_scope=item.attribution_scope,
                    status=item.status,
                    reasons=tuple(item.reasons_json),
                    source_refs=tuple(
                        SourceReference(**value) for value in item.source_refs_json
                    ),
                    binding_source_refs=tuple(
                        SourceReference(**value)
                        for value in item.binding_source_refs_json
                    ),
                    relation_status=item.relation_status,
                )
                for item in comparisons
            ),
            reported_interpretations=tuple(
                ReportedInterpretation(
                    statement=item.statement,
                    kind=item.kind,
                    measurement_keys=tuple(item.measurement_keys_json),
                    comparison_keys=tuple(item.comparison_keys_json),
                    source_refs=tuple(
                        SourceReference(**value) for value in item.source_refs_json
                    ),
                )
                for item in interpretations
            ),
            source_refs=tuple(
                SourceReference(**value) for value in row.source_refs_json
            ),
            unresolved_issues=tuple(row.unresolved_issues_json),
        ),
        created_at=_aware(row.created_at),
        created_by=row.created_by,
        archived_at=_aware(row.archived_at) if row.archived_at is not None else None,
    )


def _stored_value(value: Any) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, str(value)
    if not isinstance(value, (int, float, Decimal)):
        return None, str(value)
    return Decimal(str(value)), None


def _domain_value(value_numeric: Decimal | None, value_text: str | None) -> Any:
    if value_numeric is None:
        return value_text
    if value_numeric == value_numeric.to_integral_value():
        return int(value_numeric)
    return float(value_numeric)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return str(value) if value else None


__all__ = [
    "PaperExperimentRepository",
    "PaperExperimentRevisionConflictError",
    "StoredPaperExperimentRevision",
]


PaperExperimentRepo = PaperExperimentRepository()
