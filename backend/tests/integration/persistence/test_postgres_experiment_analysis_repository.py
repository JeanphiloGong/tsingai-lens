from __future__ import annotations

from infra.persistence import database

import pytest
from domain.core import Finding
from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    Finding,
)
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _positive_int as finding_positive_int
from domain.core.finding import _strings as finding_strings
from domain.core.finding import _text as finding_text
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
    _text,
)
from domain.core.scientific_fact import (
    ScientificContext,
)
from infra.persistence.postgres.experiment_analysis_transaction import (
    PostgresExperimentAnalysisTransactionFactory,
)
from repositories.comparison_group_repository import (
    ComparisonGroupRepository,
)
from repositories.experiment_analysis_repository import (
    ExperimentAnalysisRepository,
    ExperimentAnalysisWrite,
)
from repositories.experiment_finding_repository import (
    ExperimentFindingRepository,
)
from repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from repositories.paper_experiment_repository import (
    PaperExperimentRepository,
)
from tests.integration.persistence.test_postgres_objective_lifecycle import (
    COLLECTION_ID,
    OBJECTIVE_ID,
    _queue_and_claim,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_objective_lifecycle",)
pytestmark = pytest.mark.anyio


def _revision(
    *,
    experiment_id: str,
    document_id: str,
    measurement_key: str,
    value: int,
) -> PaperExperimentRevision:
    return PaperExperimentRevision(
        experiment_id=experiment_id,
        document_id=document_id,
        experiment_version=int(1),
        source_fingerprint=f"fingerprint-{document_id}",
        label=f"{document_id} tensile series",
        scope_description="One reported tensile-strength condition.",
        design_type="observational",
        identity_status="identified",
        binding_status="bound",
        variants=(
            ExperimentalVariant(
                variant_key="reported-condition",
                variant_label="Reported condition",
                binding_status="direct",
            ),
        ),
        test_conditions=(
            ExperimentTestCondition(
                test_key="tensile", test_type="tensile test", binding_status="direct"
            ),
        ),
        measurements=(
            ExperimentMeasurementResult(
                measurement_key=_text(measurement_key or None),
                outcome="tensile strength",
                variant_key="reported-condition",
                test_key="tensile",
                value=value,
                unit="MPa",
                binding_status="direct",
            ),
        ),
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
    return Finding(
        collection_id=finding_text(COLLECTION_ID) or "",
        objective_id=finding_text(OBJECTIVE_ID) or "",
        analysis_version=finding_positive_int(analysis_version),
        finding_id="finding-strength-across-papers",
        statement="Both papers report higher tensile strength.",
        factors=("laser power",),
        outcome="tensile strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope=finding_choice(
            "association_only",
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status="agreement",
        certainty=0.7,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=(),
        paper_contributions=(),
        selection_ids=("selection-a", "selection-b"),
        comparison_group_ids=finding_strings(
            ["strength-across-papers"] if with_group else []
        ),
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
    repository = ExperimentAnalysisRepository(
        database.AsyncSessionLocal
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
    session_factory = database.AsyncSessionLocal
    repository = ExperimentAnalysisRepository(session_factory)

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

    experiments = PaperExperimentRepository(session_factory)
    selections = ObjectiveExperimentSelectionRepository(session_factory)
    groups = ComparisonGroupRepository(session_factory)
    findings = ExperimentFindingRepository(session_factory)
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
    session_factory = database.AsyncSessionLocal
    repository = ExperimentAnalysisRepository(session_factory)
    transaction_factory = PostgresExperimentAnalysisTransactionFactory(
        session_factory
    )

    with pytest.raises(RuntimeError, match="objective publication failed"):
        async with transaction_factory.begin() as transaction:
            await repository.write_graph(graph, transaction=transaction)
            raise RuntimeError("objective publication failed")

    experiments = PaperExperimentRepository(session_factory)
    selections = ObjectiveExperimentSelectionRepository(session_factory)
    groups = ComparisonGroupRepository(session_factory)
    findings = ExperimentFindingRepository(session_factory)
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
