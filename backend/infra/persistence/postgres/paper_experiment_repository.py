"""PostgreSQL persistence for immutable PaperExperiment revisions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.paper_experiment_repository import (
    PaperExperimentRevisionConflictError,
    StoredPaperExperimentRevision,
)
from application.repositories.transaction import RepositoryTransaction
from domain.core.paper_experiment import PaperExperimentRevision
from infra.persistence.postgres.models.paper_experiment import (
    ExperimentComparisonMeasurementRow,
    ExperimentComparisonRow,
    ExperimentMeasurementResultRow,
    ExperimentTestConditionRow,
    ExperimentalVariantRow,
    PaperExperimentRow,
    ReportedInterpretationRow,
)
from infra.persistence.postgres.transaction import database_session_scope


class PostgresPaperExperimentRepository:
    backend_name = "postgresql"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def add_revision(
        self,
        revision: PaperExperimentRevision,
        *,
        created_by: str | None = None,
        created_at: datetime | None = None,
        transaction: RepositoryTransaction | None = None,
    ) -> StoredPaperExperimentRevision:
        async with database_session_scope(
            self.session_factory, transaction, write=True
        ) as session:
            return await _add_revision(
                session,
                revision,
                created_by=created_by,
                created_at=created_at,
            )

    async def read_revision(
        self,
        experiment_id: str,
        experiment_version: int,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> StoredPaperExperimentRevision | None:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            row = await session.scalar(
                select(PaperExperimentRow).where(
                    PaperExperimentRow.experiment_id == experiment_id,
                    PaperExperimentRow.experiment_version == experiment_version,
                )
            )
            return await _stored_revision(session, row) if row is not None else None

    async def read_revision_by_id(
        self,
        revision_id: int,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> StoredPaperExperimentRevision | None:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            row = await session.get(PaperExperimentRow, revision_id)
            return await _stored_revision(session, row) if row is not None else None

    async def read_latest_revision(
        self,
        experiment_id: str,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> StoredPaperExperimentRevision | None:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            row = await session.scalar(
                select(PaperExperimentRow)
                .where(PaperExperimentRow.experiment_id == experiment_id)
                .order_by(PaperExperimentRow.experiment_version.desc())
                .limit(1)
            )
            return await _stored_revision(session, row) if row is not None else None

    async def list_latest_for_document(
        self,
        document_id: str,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> tuple[StoredPaperExperimentRevision, ...]:
        async with database_session_scope(
            self.session_factory, transaction, write=False
        ) as session:
            rows = tuple(
                await session.scalars(
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
            return tuple(
                [await _stored_revision(session, row) for row in latest_rows]
            )


async def _add_revision(
    session: AsyncSession,
    revision: PaperExperimentRevision,
    *,
    created_by: str | None = None,
    created_at: datetime | None = None,
) -> StoredPaperExperimentRevision:
    # Rebuild at the trust boundary so even a mutated frozen instance cannot
    # bypass cross-component domain validation.
    validated = PaperExperimentRevision.from_mapping(revision.to_record())
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    existing = await session.scalar(
        select(PaperExperimentRow).where(
            PaperExperimentRow.experiment_id == validated.experiment_id,
            PaperExperimentRow.experiment_version == validated.experiment_version,
        )
    )
    if existing is not None:
        stored = await _stored_revision(session, existing)
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
        source_refs_json=[item.to_record() for item in validated.source_refs],
        unresolved_issues_json=[dict(item) for item in validated.unresolved_issues],
        created_at=timestamp,
        created_by=created_by,
        archived_at=None,
    )
    session.add(row)
    try:
        await session.flush()
        await _add_components(session, row.id, validated)
        await session.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) == "uq_paper_experiment_identity_version":
            raise PaperExperimentRevisionConflictError(
                "paper experiment revision identity already exists"
            ) from exc
        raise
    return await _stored_revision(session, row)


async def _add_components(
    session: AsyncSession,
    paper_experiment_id: int,
    revision: PaperExperimentRevision,
) -> None:
    session.add_all(
        [
            ExperimentalVariantRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                variant_key=item.variant_key,
                variant_label=item.variant_label,
                subject_attributes_json=[
                    value.to_record() for value in item.subject_attributes
                ],
                intervention_attributes_json=[
                    value.to_record() for value in item.intervention_attributes
                ],
                state_json=[value.to_record() for value in item.state],
                population_scope_json=(
                    dict(item.population_scope)
                    if item.population_scope is not None
                    else None
                ),
                source_refs_json=[value.to_record() for value in item.source_refs],
                binding_source_refs_json=[
                    value.to_record() for value in item.binding_source_refs
                ],
                binding_status=item.binding_status,
                notes_json=list(item.notes),
            )
            for position, item in enumerate(revision.variants)
        ]
    )
    session.add_all(
        [
            ExperimentTestConditionRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                test_key=item.test_key,
                test_type=item.test_type,
                parameters_json=[value.to_record() for value in item.parameters],
                population_scope_json=(
                    dict(item.population_scope)
                    if item.population_scope is not None
                    else None
                ),
                source_refs_json=[value.to_record() for value in item.source_refs],
                binding_status=item.binding_status,
                notes_json=list(item.notes),
            )
            for position, item in enumerate(revision.test_conditions)
        ]
    )
    await session.flush()

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
                source_refs_json=[value.to_record() for value in item.source_refs],
                binding_source_refs_json=[
                    value.to_record() for value in item.binding_source_refs
                ],
                binding_status=item.binding_status,
                notes_json=list(item.notes),
            )
        )
    session.add_all(measurement_rows)

    comparison_rows = [
        ExperimentComparisonRow(
            paper_experiment_id=paper_experiment_id,
            position=position,
            comparison_key=item.comparison_key,
            baseline_variant_key=item.baseline_variant_key,
            target_variant_key=item.target_variant_key,
            outcome=item.outcome,
            changed_variables_json=[
                value.to_record() for value in item.changed_variables
            ],
            matched_conditions_json=[
                value.to_record() for value in item.matched_conditions
            ],
            basis=item.basis,
            direction=item.direction,
            reported_statement=item.reported_statement,
            attribution_scope=item.attribution_scope,
            status=item.status,
            reasons_json=list(item.reasons),
            source_refs_json=[value.to_record() for value in item.source_refs],
            binding_source_refs_json=[
                value.to_record() for value in item.binding_source_refs
            ],
            relation_status=item.relation_status,
        )
        for position, item in enumerate(revision.comparisons)
    ]
    session.add_all(comparison_rows)
    await session.flush()

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
    session.add_all(links)
    session.add_all(
        [
            ReportedInterpretationRow(
                paper_experiment_id=paper_experiment_id,
                position=position,
                statement=item.statement,
                kind=item.kind,
                measurement_keys_json=list(item.measurement_keys),
                comparison_keys_json=list(item.comparison_keys),
                source_refs_json=[value.to_record() for value in item.source_refs],
            )
            for position, item in enumerate(revision.reported_interpretations)
        ]
    )


async def _stored_revision(
    session: AsyncSession,
    row: PaperExperimentRow,
) -> StoredPaperExperimentRevision:
    revision_id = row.id
    variants = tuple(
        await session.scalars(
            select(ExperimentalVariantRow)
            .where(ExperimentalVariantRow.paper_experiment_id == revision_id)
            .order_by(ExperimentalVariantRow.position)
        )
    )
    tests = tuple(
        await session.scalars(
            select(ExperimentTestConditionRow)
            .where(ExperimentTestConditionRow.paper_experiment_id == revision_id)
            .order_by(ExperimentTestConditionRow.position)
        )
    )
    measurements = tuple(
        await session.scalars(
            select(ExperimentMeasurementResultRow)
            .where(ExperimentMeasurementResultRow.paper_experiment_id == revision_id)
            .order_by(ExperimentMeasurementResultRow.position)
        )
    )
    comparisons = tuple(
        await session.scalars(
            select(ExperimentComparisonRow)
            .where(ExperimentComparisonRow.paper_experiment_id == revision_id)
            .order_by(ExperimentComparisonRow.position)
        )
    )
    links = tuple(
        await session.scalars(
            select(ExperimentComparisonMeasurementRow)
            .where(
                ExperimentComparisonMeasurementRow.paper_experiment_id
                == revision_id
            )
            .order_by(
                ExperimentComparisonMeasurementRow.comparison_key,
                ExperimentComparisonMeasurementRow.side,
                ExperimentComparisonMeasurementRow.position,
            )
        )
    )
    interpretations = tuple(
        await session.scalars(
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

    payload = {
        "experiment_id": row.experiment_id,
        "document_id": row.document_id,
        "experiment_version": row.experiment_version,
        "source_fingerprint": row.source_fingerprint,
        "label": row.label,
        "scope_description": row.scope_description,
        "design_type": row.design_type,
        "identity_status": row.identity_status,
        "binding_status": row.binding_status,
        "source_refs": list(row.source_refs_json),
        "unresolved_issues": list(row.unresolved_issues_json),
        "variants": [
            {
                "variant_key": item.variant_key,
                "variant_label": item.variant_label,
                "subject_attributes": list(item.subject_attributes_json),
                "intervention_attributes": list(
                    item.intervention_attributes_json
                ),
                "state": list(item.state_json),
                "population_scope": item.population_scope_json,
                "source_refs": list(item.source_refs_json),
                "binding_source_refs": list(item.binding_source_refs_json),
                "binding_status": item.binding_status,
                "notes": list(item.notes_json),
            }
            for item in variants
        ],
        "test_conditions": [
            {
                "test_key": item.test_key,
                "test_type": item.test_type,
                "parameters": list(item.parameters_json),
                "population_scope": item.population_scope_json,
                "source_refs": list(item.source_refs_json),
                "binding_status": item.binding_status,
                "notes": list(item.notes_json),
            }
            for item in tests
        ],
        "measurements": [
            {
                "measurement_key": item.measurement_key,
                "variant_key": item.variant_key,
                "test_key": item.test_key,
                "outcome": item.outcome,
                "value": _domain_value(item.value_numeric, item.value_text),
                "result_text": item.result_text,
                "unit": item.unit,
                "statistics": dict(item.statistics_json),
                "measurement_scope": dict(item.measurement_scope_json),
                "result_kind": item.result_kind,
                "source_refs": list(item.source_refs_json),
                "binding_source_refs": list(item.binding_source_refs_json),
                "binding_status": item.binding_status,
                "notes": list(item.notes_json),
            }
            for item in measurements
        ],
        "comparisons": [
            {
                "comparison_key": item.comparison_key,
                "baseline_variant_key": item.baseline_variant_key,
                "target_variant_key": item.target_variant_key,
                "outcome": item.outcome,
                "baseline_measurement_keys": links_by_comparison.get(
                    item.comparison_key, {}
                ).get("baseline", []),
                "target_measurement_keys": links_by_comparison.get(
                    item.comparison_key, {}
                ).get("target", []),
                "changed_variables": list(item.changed_variables_json),
                "matched_conditions": list(item.matched_conditions_json),
                "basis": item.basis,
                "direction": item.direction,
                "reported_statement": item.reported_statement,
                "attribution_scope": item.attribution_scope,
                "status": item.status,
                "reasons": list(item.reasons_json),
                "source_refs": list(item.source_refs_json),
                "binding_source_refs": list(item.binding_source_refs_json),
                "relation_status": item.relation_status,
            }
            for item in comparisons
        ],
        "reported_interpretations": [
            {
                "statement": item.statement,
                "kind": item.kind,
                "measurement_keys": list(item.measurement_keys_json),
                "comparison_keys": list(item.comparison_keys_json),
                "source_refs": list(item.source_refs_json),
            }
            for item in interpretations
        ],
    }
    return StoredPaperExperimentRevision(
        revision_id=revision_id,
        revision=PaperExperimentRevision.from_mapping(payload),
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


__all__ = ["PostgresPaperExperimentRepository"]
