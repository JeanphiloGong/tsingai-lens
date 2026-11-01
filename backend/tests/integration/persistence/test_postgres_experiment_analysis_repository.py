from __future__ import annotations

from dataclasses import replace

from infra.persistence import database

import pytest
from domain.core import Finding
from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    Finding,
)
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
)
from domain.core.scientific_fact import (
    ScientificContext,
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
                measurement_key=measurement_key,
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
        collection_id=COLLECTION_ID or "",
        objective_id=OBJECTIVE_ID or "",
        analysis_version=analysis_version,
        finding_id="finding-strength-across-papers",
        statement="Both papers report higher tensile strength.",
        factors=("laser power",),
        outcome="tensile strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope='association_only',
        synthesis_status="agreement",
        certainty=0.735123,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=(),
        paper_contributions=(),
        selection_ids=("selection-a", "selection-b"),
        comparison_group_ids=tuple((['strength-across-papers'] if with_group else []) or ()),
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
    revision_a = replace(
        revision_a,
        measurements=tuple(
            replace(revision_a.measurements[0], measurement_key=key)
            for key in ("strength-A", "strength-a", "001")
        ),
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
    selection_a = replace(
        selection_a, measurement_keys=("strength-A", "strength-a", "001")
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
    repository = ExperimentAnalysisRepository()

    async with database.AsyncSessionLocal() as db, db.begin():
        first = await repository.write_graph(db, graph)
    async with database.AsyncSessionLocal() as db, db.begin():
        second = await repository.write_graph(db, graph)

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
    repository = ExperimentAnalysisRepository()

    with pytest.raises(ValueError, match="requires a comparison group"):
        async with database.AsyncSessionLocal() as db, db.begin():
            await repository.write_graph(db, ExperimentAnalysisWrite(collection_id=COLLECTION_ID, objective_id=OBJECTIVE_ID, analysis_version=analysis.analysis_version, revisions=(revision_a, revision_b), selections=(selection_a, selection_b), groups=(), findings=(invalid_finding,), created_by='test-agent'))

    experiments = PaperExperimentRepository()
    selections = ObjectiveExperimentSelectionRepository()
    groups = ComparisonGroupRepository()
    findings = ExperimentFindingRepository()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, 'experiment-a') is None
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, 'experiment-b') is None
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await selections.list_selections(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version) == ()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await groups.list_groups(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version) == ()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await findings.list_findings(db,
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
    repository = ExperimentAnalysisRepository()

    with pytest.raises(RuntimeError, match="objective publication failed"):
        async with database.AsyncSessionLocal() as db, db.begin():
            await repository.write_graph(db, graph)
            raise RuntimeError("objective publication failed")

    experiments = PaperExperimentRepository()
    selections = ObjectiveExperimentSelectionRepository()
    groups = ComparisonGroupRepository()
    findings = ExperimentFindingRepository()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, 'experiment-a') is None
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, 'experiment-b') is None
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await selections.list_selections(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version) == ()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await groups.list_groups(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version) == ()
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await findings.list_findings(db,
            COLLECTION_ID,
            OBJECTIVE_ID,
            analysis.analysis_version,
        ) == ()


@pytest.mark.parametrize("with_group, message", [
    (False, "independent experiment"),
    (True, "included selections from multiple experiments"),
])
async def test_same_experiment_selections_cannot_publish_independent_support(
    objective_repository, with_group, message,
):
    _, analysis = await _queue_and_claim(objective_repository)
    revision = _revision(
        experiment_id="experiment-a", document_id="doc_a",
        measurement_key="strength-a", value=900,
    )
    first = _selection(
        selection_id="selection-a", experiment_id="experiment-a",
        measurement_key="strength-a", analysis_version=analysis.analysis_version,
    )
    graph = ExperimentAnalysisWrite(
        collection_id=COLLECTION_ID, objective_id=OBJECTIVE_ID,
        analysis_version=analysis.analysis_version, revisions=(revision,),
        selections=(first, replace(first, selection_id="selection-b")),
        groups=(_group(analysis_version=analysis.analysis_version),) if with_group else (),
        findings=(_finding(analysis_version=analysis.analysis_version, with_group=with_group),),
    )
    with pytest.raises(ValueError, match=message):
        async with database.AsyncSessionLocal() as db, db.begin():
            await ExperimentAnalysisRepository().write_graph(db, graph)
    async with database.AsyncSessionLocal() as db:
        assert await PaperExperimentRepository().read_latest_revision(db, "experiment-a") is None
        assert await ObjectiveExperimentSelectionRepository().list_selections(
            db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version,
        ) == ()
        assert await ComparisonGroupRepository().list_groups(
            db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version,
        ) == ()
        assert await ExperimentFindingRepository().list_findings(
            db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version,
        ) == ()
