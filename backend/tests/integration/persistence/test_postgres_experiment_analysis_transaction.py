from __future__ import annotations

from dataclasses import replace

import pytest

from application.core.objectives.analysis.experiment_finding_publisher import (
    ExperimentFindingPublisher,
)
from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision
from infra.persistence.postgres.comparison_group_repository import (
    PostgresComparisonGroupRepository,
)
from infra.persistence.postgres.experiment_analysis_transaction import (
    PostgresExperimentAnalysisTransactionFactory,
)
from infra.persistence.postgres.experiment_finding_repository import (
    PostgresExperimentFindingRepository,
)
from infra.persistence.postgres.objective_experiment_selection_repository import (
    PostgresObjectiveExperimentSelectionRepository,
)
from infra.persistence.postgres.paper_experiment_repository import (
    PostgresPaperExperimentRepository,
)
from tests.integration.persistence.test_postgres_objectives import (
    COLLECTION_ID,
    OBJECTIVE_ID,
    _contribution,
    _queue_and_claim,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_objectives",)
pytestmark = pytest.mark.anyio


def _revision() -> PaperExperimentRevision:
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": "experiment-transaction",
            "document_id": "doc_a",
            "experiment_version": 1,
            "source_fingerprint": "fingerprint-doc-a",
            "label": "Reported tensile series",
            "scope_description": "One reported tensile-strength condition.",
            "design_type": "observational",
            "identity_status": "identified",
            "binding_status": "bound",
            "variants": [
                {
                    "variant_key": "reported-condition",
                    "variant_label": "Reported condition",
                    "binding_status": "direct",
                }
            ],
            "test_conditions": [
                {
                    "test_key": "tensile",
                    "test_type": "tensile test",
                    "binding_status": "direct",
                }
            ],
            "measurements": [
                {
                    "measurement_key": "strength-a",
                    "variant_key": "reported-condition",
                    "test_key": "tensile",
                    "outcome": "tensile strength",
                    "value": 900,
                    "unit": "MPa",
                    "binding_status": "direct",
                }
            ],
        }
    )


def _selection(analysis_version: int) -> ObjectiveExperimentSelection:
    return ObjectiveExperimentSelection(
        selection_id="selection-transaction",
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis_version,
        experiment_id="experiment-transaction",
        experiment_version=1,
        outcome="tensile strength",
        measurement_keys=("strength-a",),
    )


def _comparison_group(
    analysis_version: int,
    selection_ids: tuple[str, str],
) -> ComparisonGroup:
    return ComparisonGroup(
        group_id="group-transaction",
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis_version,
        outcome="tensile strength",
        comparison_target="measurement",
        comparison_basis=("reported tensile conditions",),
        members=tuple(
            ComparisonGroupMember(
                selection_id=selection_id,
                role="included",
                comparability="comparable",
                reason="Both selections report the same tensile outcome.",
            )
            for selection_id in selection_ids
        ),
        status="comparable",
    )


def _cross_paper_finding(
    analysis_version: int,
    selection_ids: tuple[str, str],
) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "analysis_version": analysis_version,
            "finding_id": "finding-transaction",
            "statement": "The reported tensile strength was comparable across papers.",
            "factors": ["process condition"],
            "outcome": "tensile strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "association_only",
            "synthesis_status": "agreement",
            "certainty": 0.7,
            "display_rank": 0,
            "mechanisms": [],
            "scientific_context": {},
            "limitations": [],
            "paper_contributions": [],
            "selection_ids": list(selection_ids),
            "comparison_group_ids": ["group-transaction"],
        }
    )


class _FailingAfterWriteFindingRepository(PostgresExperimentFindingRepository):
    """Flush a Finding, then fail so the enclosing transaction must undo it."""

    async def add_finding(self, finding, *, transaction=None):
        await super().add_finding(finding, transaction=transaction)
        raise RuntimeError("forced Finding publication failure")


async def test_shared_transaction_rolls_back_graph_and_objective_publication(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    session_factory = objective_repository.session_factory
    experiments = PostgresPaperExperimentRepository(session_factory)
    selections = PostgresObjectiveExperimentSelectionRepository(session_factory)
    transaction_factory = PostgresExperimentAnalysisTransactionFactory(session_factory)
    revision = _revision()
    selection = _selection(analysis.analysis_version)

    with pytest.raises(RuntimeError, match="forced rollback"):
        async with transaction_factory.begin() as transaction:
            stored = await experiments.add_revision(
                revision,
                created_by="test-agent",
                transaction=transaction,
            )
            await selections.add_selection(
                COLLECTION_ID,
                selection,
                revision_id=stored.revision_id,
                transaction=transaction,
            )
            await objective_repository.publish_experiment_analysis(
                COLLECTION_ID,
                OBJECTIVE_ID,
                analysis.analysis_version,
                contributions=(
                    _contribution(analysis.analysis_version, "doc_a"),
                    _contribution(analysis.analysis_version, "doc_b"),
                ),
                transaction=transaction,
            )
            raise RuntimeError("forced rollback")

    assert await experiments.read_latest_revision(
        "experiment-transaction"
    ) is None
    assert await selections.list_selections(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ()
    restored = await objective_repository.read_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    )
    assert restored is not None
    assert restored.status == "running"


async def test_experiment_graph_publication_does_not_require_paper_contributions(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)

    await objective_repository.publish_experiment_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    )

    published = await objective_repository.read_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    )
    assert published is not None
    assert published.status == "succeeded"
    assert await objective_repository.list_contributions(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ()


async def test_finding_failure_rolls_back_revisions_selections_groups_and_finding(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    session_factory = objective_repository.session_factory
    experiments = PostgresPaperExperimentRepository(session_factory)
    selections = PostgresObjectiveExperimentSelectionRepository(session_factory)
    groups = PostgresComparisonGroupRepository(session_factory)
    findings = _FailingAfterWriteFindingRepository(session_factory)
    publisher = ExperimentFindingPublisher(selections, groups, findings)
    transaction_factory = PostgresExperimentAnalysisTransactionFactory(session_factory)

    revision_a = _revision()
    revision_b = replace(
        revision_a,
        experiment_id="experiment-transaction-b",
        document_id="doc_b",
        source_fingerprint="fingerprint-doc-b",
    )
    selection_a = _selection(analysis.analysis_version)
    selection_b = replace(
        selection_a,
        selection_id="selection-transaction-b",
        experiment_id="experiment-transaction-b",
    )
    selection_ids = (selection_a.selection_id, selection_b.selection_id)
    group = _comparison_group(analysis.analysis_version, selection_ids)
    finding = _cross_paper_finding(analysis.analysis_version, selection_ids)

    with pytest.raises(RuntimeError, match="forced Finding publication failure"):
        async with transaction_factory.begin() as transaction:
            stored_a = await experiments.add_revision(
                revision_a,
                created_by="test-agent",
                transaction=transaction,
            )
            stored_b = await experiments.add_revision(
                revision_b,
                created_by="test-agent",
                transaction=transaction,
            )
            await selections.add_selection(
                COLLECTION_ID,
                selection_a,
                revision_id=stored_a.revision_id,
                transaction=transaction,
            )
            await selections.add_selection(
                COLLECTION_ID,
                selection_b,
                revision_id=stored_b.revision_id,
                transaction=transaction,
            )
            await groups.add_group(
                COLLECTION_ID,
                group,
                transaction=transaction,
            )
            await publisher.publish(finding, transaction=transaction)

    assert await experiments.read_latest_revision(
        revision_a.experiment_id
    ) is None
    assert await experiments.read_latest_revision(
        revision_b.experiment_id
    ) is None
    assert await selections.list_selections(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ()
    assert await groups.list_groups(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ()
    assert await findings.list_findings(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    ) == ()

    restored = await objective_repository.read_analysis(
        COLLECTION_ID,
        OBJECTIVE_ID,
        analysis.analysis_version,
    )
    assert restored is not None
    assert restored.status == "running"
    objective = await objective_repository.read_objective(
        COLLECTION_ID,
        OBJECTIVE_ID,
    )
    assert objective is not None
    assert objective.published_analysis_version is None
