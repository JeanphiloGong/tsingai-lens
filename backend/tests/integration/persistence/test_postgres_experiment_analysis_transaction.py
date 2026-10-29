from __future__ import annotations

from infra.persistence import database

from dataclasses import replace

import pytest
from application.core.objectives.analysis.experiment_finding_publisher import (
    ExperimentFindingPublisher,
)
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
    _contribution,
    _queue_and_claim,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_objective_lifecycle",)
pytestmark = pytest.mark.anyio


def _revision() -> PaperExperimentRevision:
    return PaperExperimentRevision(
        experiment_id="experiment-transaction",
        document_id="doc_a",
        experiment_version=int(1),
        source_fingerprint="fingerprint-doc-a",
        label="Reported tensile series",
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
                measurement_key="strength-a",
                outcome="tensile strength",
                variant_key="reported-condition",
                test_key="tensile",
                value=900,
                unit="MPa",
                binding_status="direct",
            ),
        ),
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
    return Finding(
        collection_id=COLLECTION_ID or "",
        objective_id=OBJECTIVE_ID or "",
        analysis_version=analysis_version,
        finding_id="finding-transaction",
        statement="The reported tensile strength was comparable across papers.",
        factors=("process condition",),
        outcome="tensile strength",
        direction="increase",
        assertion_strength="associative",
        attribution_scope='association_only',
        synthesis_status="agreement",
        certainty=0.7,
        display_rank=0,
        mechanisms=(),
        scientific_context=ScientificContext(),
        limitations=(),
        paper_contributions=(),
        selection_ids=tuple(list(selection_ids) or ()),
        comparison_group_ids=("group-transaction",),
    )


class _FailingAfterWriteFindingRepository(ExperimentFindingRepository):
    """Flush a Finding, then fail so the enclosing transaction must undo it."""

    async def add_finding(self, db, finding):
        await super().add_finding(db, finding)
        raise RuntimeError("forced Finding publication failure")


async def test_shared_transaction_rolls_back_graph_and_objective_publication(
    objective_repository,
) -> None:
    _, analysis = await _queue_and_claim(objective_repository)
    experiments = PaperExperimentRepository()
    selections = ObjectiveExperimentSelectionRepository()
    revision = _revision()
    selection = _selection(analysis.analysis_version)

    with pytest.raises(RuntimeError, match="forced rollback"):
        async with database.AsyncSessionLocal() as db, db.begin():
            stored = await experiments.add_revision(db, revision, created_by='test-agent')
            await selections.add_selection(db, COLLECTION_ID, selection, revision_id=stored.revision_id)
            await objective_repository.publish_experiment_analysis(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version, contributions=(_contribution(analysis.analysis_version, 'doc_a'), _contribution(analysis.analysis_version, 'doc_b')))
            raise RuntimeError("forced rollback")

    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, 'experiment-transaction') is None
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await selections.list_selections(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version) == ()
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

    async with database.AsyncSessionLocal() as db, db.begin():
        await objective_repository.publish_experiment_analysis(db, COLLECTION_ID, OBJECTIVE_ID, analysis.analysis_version)

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
    experiments = PaperExperimentRepository()
    selections = ObjectiveExperimentSelectionRepository()
    groups = ComparisonGroupRepository()
    findings = _FailingAfterWriteFindingRepository()
    publisher = ExperimentFindingPublisher(selections, groups, findings)

    revision_a = _revision()
    revision_b = replace(
        revision_a,
        experiment_id="experiment-db-b",
        document_id="doc_b",
        source_fingerprint="fingerprint-doc-b",
    )
    selection_a = _selection(analysis.analysis_version)
    selection_b = replace(
        selection_a,
        selection_id="selection-db-b",
        experiment_id="experiment-db-b",
    )
    selection_ids = (selection_a.selection_id, selection_b.selection_id)
    group = _comparison_group(analysis.analysis_version, selection_ids)
    finding = _cross_paper_finding(analysis.analysis_version, selection_ids)

    with pytest.raises(RuntimeError, match="forced Finding publication failure"):
        async with database.AsyncSessionLocal() as db, db.begin():
            stored_a = await experiments.add_revision(db, revision_a, created_by='test-agent')
            stored_b = await experiments.add_revision(db, revision_b, created_by='test-agent')
            await selections.add_selection(db, COLLECTION_ID, selection_a, revision_id=stored_a.revision_id)
            await selections.add_selection(db, COLLECTION_ID, selection_b, revision_id=stored_b.revision_id)
            await groups.add_group(db, COLLECTION_ID, group)
            await publisher.publish(finding, db=db)

    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, revision_a.experiment_id) is None
    async with database.AsyncSessionLocal() as db, db.begin():
        assert await experiments.read_latest_revision(db, revision_b.experiment_id) is None
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
