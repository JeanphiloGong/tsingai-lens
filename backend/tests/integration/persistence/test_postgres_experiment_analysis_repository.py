from __future__ import annotations

import pytest

from application.repositories.experiment_analysis_repository import (
    ExperimentAnalysisWrite,
)
from domain.core import Finding
from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision
from infra.persistence.postgres.comparison_group_repository import (
    PostgresComparisonGroupRepository,
)
from infra.persistence.postgres.experiment_analysis_repository import (
    PostgresExperimentAnalysisRepository,
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
    _queue_and_claim,
)


pytest_plugins = ("tests.integration.persistence.test_postgres_objectives",)
pytestmark = pytest.mark.anyio


def _revision(
    *,
    experiment_id: str,
    document_id: str,
    measurement_key: str,
    value: int,
) -> PaperExperimentRevision:
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": experiment_id,
            "document_id": document_id,
            "experiment_version": 1,
            "source_fingerprint": f"fingerprint-{document_id}",
            "label": f"{document_id} tensile series",
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
                    "measurement_key": measurement_key,
                    "variant_key": "reported-condition",
                    "test_key": "tensile",
                    "outcome": "tensile strength",
                    "value": value,
                    "unit": "MPa",
                    "binding_status": "direct",
                }
            ],
        }
    )


def _selection(
    *,
    selection_id: str,
    experiment_id: str,
    measurement_key: str,
    analysis_version: int,
) -> ObjectiveExperimentSelection:
    return ObjectiveExperimentSelection(
        selection_id=selection_id,
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis_version,
        experiment_id=experiment_id,
        experiment_version=1,
        outcome="tensile strength",
        measurement_keys=(measurement_key,),
    )


def _group(*, analysis_version: int) -> ComparisonGroup:
    return ComparisonGroup(
        group_id="strength-across-papers",
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis_version,
        outcome="tensile strength",
        comparison_target="measurement",
        comparison_basis=("same reported outcome",),
        members=(
            ComparisonGroupMember(
                selection_id="selection-a",
                role="included",
                comparability="comparable",
                reason="Uses the same reported outcome.",
            ),
            ComparisonGroupMember(
                selection_id="selection-b",
                role="included",
                comparability="comparable",
                reason="Uses the same reported outcome.",
            ),
        ),
        status="comparable",
    )


def _finding(*, analysis_version: int, with_group: bool) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "analysis_version": analysis_version,
            "finding_id": "finding-strength-across-papers",
            "statement": "Both papers report higher tensile strength.",
            "factors": ["laser power"],
            "outcome": "tensile strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "association_only",
            "synthesis_status": "agreement",
            "certainty": 0.7,
            "display_rank": 0,
            "scientific_context": {},
            "limitations": [],
            "selection_ids": ["selection-a", "selection-b"],
            "comparison_group_ids": (
                ["strength-across-papers"] if with_group else []
            ),
        }
    )


async def test_complete_analysis_graph_commits_once_and_is_idempotent(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    revision_a = _revision(
        experiment_id="experiment-a",
        document_id="doc_a",
        measurement_key="strength-a",
        value=900,
    )
    revision_b = _revision(
        experiment_id="experiment-b",
        document_id="doc_b",
        measurement_key="strength-b",
        value=950,
    )
    selection_a = _selection(
        selection_id="selection-a",
        experiment_id="experiment-a",
        measurement_key="strength-a",
        analysis_version=analysis.analysis_version,
    )
    selection_b = _selection(
        selection_id="selection-b",
        experiment_id="experiment-b",
        measurement_key="strength-b",
        analysis_version=analysis.analysis_version,
    )
    graph = ExperimentAnalysisWrite(
        collection_id=COLLECTION_ID,
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis.analysis_version,
        revisions=(revision_a, revision_b),
        selections=(selection_a, selection_b),
        groups=(_group(analysis_version=analysis.analysis_version),),
        findings=(
            _finding(analysis_version=analysis.analysis_version, with_group=True),
        ),
        created_by="test-agent",
    )
    repository = PostgresExperimentAnalysisRepository(
        objective_repository.session_factory
    )

    first = await repository.write_graph(graph)
    second = await repository.write_graph(graph)

    assert second == first
    assert len(first.revisions) == 2
    assert first.selections == (selection_a, selection_b)
    assert first.groups == graph.groups
    assert first.findings == graph.findings


async def test_failed_cross_paper_finding_rolls_back_the_entire_analysis_graph(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    revision_a = _revision(
        experiment_id="experiment-a",
        document_id="doc_a",
        measurement_key="strength-a",
        value=900,
    )
    revision_b = _revision(
        experiment_id="experiment-b",
        document_id="doc_b",
        measurement_key="strength-b",
        value=950,
    )
    selection_a = _selection(
        selection_id="selection-a",
        experiment_id="experiment-a",
        measurement_key="strength-a",
        analysis_version=analysis.analysis_version,
    )
    selection_b = _selection(
        selection_id="selection-b",
        experiment_id="experiment-b",
        measurement_key="strength-b",
        analysis_version=analysis.analysis_version,
    )
    invalid_finding = _finding(
        analysis_version=analysis.analysis_version,
        with_group=False,
    )
    session_factory = objective_repository.session_factory
    repository = PostgresExperimentAnalysisRepository(session_factory)

    with pytest.raises(ValueError, match="requires a comparison group"):
        await repository.write_graph(
            ExperimentAnalysisWrite(
                collection_id=COLLECTION_ID,
                objective_id=OBJECTIVE_ID,
                analysis_version=analysis.analysis_version,
                revisions=(revision_a, revision_b),
                selections=(selection_a, selection_b),
                groups=(),
                findings=(invalid_finding,),
                created_by="test-agent",
            )
        )

    experiments = PostgresPaperExperimentRepository(session_factory)
    selections = PostgresObjectiveExperimentSelectionRepository(session_factory)
    groups = PostgresComparisonGroupRepository(session_factory)
    findings = PostgresExperimentFindingRepository(session_factory)
    assert await experiments.read_latest_revision("experiment-a") is None
    assert await experiments.read_latest_revision("experiment-b") is None
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


async def test_caller_transaction_rolls_back_the_complete_analysis_graph(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    revision_a = _revision(
        experiment_id="experiment-a",
        document_id="doc_a",
        measurement_key="strength-a",
        value=900,
    )
    revision_b = _revision(
        experiment_id="experiment-b",
        document_id="doc_b",
        measurement_key="strength-b",
        value=950,
    )
    selection_a = _selection(
        selection_id="selection-a",
        experiment_id="experiment-a",
        measurement_key="strength-a",
        analysis_version=analysis.analysis_version,
    )
    selection_b = _selection(
        selection_id="selection-b",
        experiment_id="experiment-b",
        measurement_key="strength-b",
        analysis_version=analysis.analysis_version,
    )
    graph = ExperimentAnalysisWrite(
        collection_id=COLLECTION_ID,
        objective_id=OBJECTIVE_ID,
        analysis_version=analysis.analysis_version,
        revisions=(revision_a, revision_b),
        selections=(selection_a, selection_b),
        groups=(_group(analysis_version=analysis.analysis_version),),
        findings=(
            _finding(analysis_version=analysis.analysis_version, with_group=True),
        ),
        created_by="test-agent",
    )
    session_factory = objective_repository.session_factory
    repository = PostgresExperimentAnalysisRepository(session_factory)
    transaction_factory = PostgresExperimentAnalysisTransactionFactory(
        session_factory
    )

    with pytest.raises(RuntimeError, match="objective publication failed"):
        async with transaction_factory.begin() as transaction:
            await repository.write_graph(graph, transaction=transaction)
            raise RuntimeError("objective publication failed")

    experiments = PostgresPaperExperimentRepository(session_factory)
    selections = PostgresObjectiveExperimentSelectionRepository(session_factory)
    groups = PostgresComparisonGroupRepository(session_factory)
    findings = PostgresExperimentFindingRepository(session_factory)
    assert await experiments.read_latest_revision("experiment-a") is None
    assert await experiments.read_latest_revision("experiment-b") is None
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
