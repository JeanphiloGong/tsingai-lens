from __future__ import annotations

from infra.persistence import database

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from domain.core.finding import (
    PAPER_CONTRIBUTION_STATUSES,
)
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _text as finding_text
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.research_objective import (
    ObjectiveFactSet,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.core.research_objective import (
    _positive_int_or_none as objective_positive_int_or_none,
)
from domain.core.research_objective import (
    _text,
    normalize_objective_terms,
)
from repositories.objective_repository import (
    ExecutionStats,
    ObjectiveAnalysis,
)
from repositories.objective_repository import ObjectiveRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _objective() -> ResearchObjective:
    return ResearchObjective(
        collection_id="collection-1",
        objective_id="objective-1",
        question="Does treatment change outcome?",
        material_scope=(),
        variables=("treatment",),
        outcomes=("outcome",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        confirmation_status="confirmed",
        active_analysis_version=1,
    )


def _analysis(version: int, status: str) -> ObjectiveAnalysis:
    return ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=int(version or 0),
        document_inputs=(
            PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="p1"),
        ),
        pipeline_version="test",
        model_name=None,
        prompt_versions={str(key): str(value) for key, value in dict({}).items()},
        stats=ExecutionStats(duration_ms=None, model_usage=(), prompt_versions={}),
        status=_text(status) or "queued",
        processed_document_count=int(1),
        total_document_count=int(1),
    )


def _selection() -> ObjectiveExperimentSelection:
    return ObjectiveExperimentSelection(
        selection_id="selection-1",
        objective_id="objective-1",
        analysis_version=1,
        experiment_id="experiment-1",
        experiment_version=1,
        outcome="outcome",
        comparison_keys=("comparison-1",),
    )


class _Collection:
    async def get_collection_for_user(self, collection_id, user_id):
        return {"collection_id": collection_id}


class _Transactions:
    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __init__(self):
        self.events = []
        self.handle = self

    @asynccontextmanager
    async def begin(self):
        self.events.append("begin")
        try:
            yield self.handle
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


class _Repository:
    def __init__(self, *, fail_publish=False):
        self.fail_publish = fail_publish
        self.failed = None
        self.published = None

    async def read_objective(self, *args):
        return _objective()

    async def read_analysis(self, *args):
        return _analysis(args[-1], "succeeded")

    async def queue_analysis(self, *args, **kwargs):
        return _objective(), _analysis(2, "queued")

    async def claim_analysis(self, *args, **kwargs):
        return _analysis(2, "running")

    async def list_contributions(self, *args, **kwargs):
        return (
            PaperContribution(
                collection_id="collection-1",
                objective_id="objective-1",
                analysis_version=objective_positive_int_or_none(args[-1]) or 0,
                document_id="paper-1",
                analysis_status="analyzed",
                relevance="uncertain",
                paper_role="uncertain",
                contribution_summary=None,
                material_match=(),
                changed_variables=(),
                measured_property_scope=(),
                test_environment_scope=(),
                exclusion_reason=None,
                warnings=(),
                confidence=0.0,
            ),
        )

    async def publish_experiment_analysis(self, db, *args, **kwargs):
        self.published = {"db": db, **kwargs}
        if self.fail_publish:
            raise RuntimeError("publish failed")
        return _objective(), _analysis(2, "succeeded")

    async def fail_analysis(self, *args, **kwargs):
        self.failed = kwargs
        return None


class _Query:
    async def read_analysis_bundle(self, *args):
        return SimpleNamespace(
            selections=(_selection(),),
            groups=(),
            revisions=(SimpleNamespace(revision=SimpleNamespace()),),
            findings=(SimpleNamespace(finding_id="finding-parent"),),
        )


class _Writer:
    def __init__(self):
        self.call = None

    async def write_selection_finding_revision(self, **kwargs):
        self.call = kwargs
        if not kwargs["selections"]:
            return SimpleNamespace(findings=(), revisions=(), selections=(), groups=())
        selection = kwargs["selections"][0]
        finding = SimpleNamespace(selection_ids=(selection.selection_id,))
        return SimpleNamespace(findings=(finding,), revisions=(), selections=(), groups=())


@pytest.mark.anyio
async def test_selection_version_copies_contributions_and_uses_one_transaction(monkeypatch, ):
    repository = _Repository()
    transactions = _Transactions()
    writer = _Writer()
    monkeypatch.setattr("application.core.objectives.finding_authoring_service.AsyncSessionLocal", transactions)
    service = FindingAuthoringService(collection_service=_Collection(), objective_repository=repository, experiment_query_service=_Query(), experiment_analysis_writer=writer)

    result = await service.create_selection_version(
        collection_id="collection-1", objective_id="objective-1",
        source_analysis_version=1, selection_ids=("selection-1",),
        created_by_user_id="user-1",
    )

    assert transactions.events == ["begin", "commit"]
    assert writer.call["db"] is transactions.handle
    assert writer.call["selections"][0].selection_id == "selection-1"
    assert repository.published["db"] is transactions.handle
    assert repository.published["contributions"][0].analysis_version == 2
    assert "contributions" not in writer.call
    assert result.finding is not None


async def test_selection_revision_preserves_parent_and_expert_limitations(monkeypatch, ):
    writer = _Writer()
    repository = _Repository()
    monkeypatch.setattr("application.core.objectives.finding_authoring_service.AsyncSessionLocal", _Transactions())
    service = FindingAuthoringService(collection_service=_Collection(), objective_repository=repository, experiment_query_service=_Query(), experiment_analysis_writer=writer)
    await service.create_selection_version(
        collection_id="collection-1",
        objective_id="objective-1",
        source_analysis_version=1,
        selection_ids=("selection-1",),
        created_by_user_id="user-1",
        parent_finding_id="finding-parent",
        limitations=(" Only tested conditions. ",),
    )
    assert writer.call["parent_finding_id"] == "finding-parent"
    assert writer.call["limitations"] == ("Only tested conditions.",)


async def test_abstention_publishes_explanation_and_coverage_without_finding(monkeypatch, ):
    repository = _Repository()
    transactions = _Transactions()
    monkeypatch.setattr("application.core.objectives.finding_authoring_service.AsyncSessionLocal", transactions)
    service = FindingAuthoringService(collection_service=_Collection(), objective_repository=repository, experiment_query_service=_Query(), experiment_analysis_writer=_Writer())
    result = await service.create_selection_version(
        collection_id="collection-1",
        objective_id="objective-1",
        source_analysis_version=1,
        selection_ids=(),
        created_by_user_id="user-1",
        abstention_reason="insufficient_evidence",
        limitations=("No comparable measurement in the second paper.",),
    )
    assert result.finding is None
    assert transactions.events == ["begin", "commit"]
    assert repository.published["abstention_reason"] == "insufficient_evidence"
    assert (
        repository.published["abstention_note"]
        == "No comparable measurement in the second paper."
    )
    assert repository.published["contributions"][0].analysis_version == 2


async def test_unknown_parent_is_rejected_before_creating_a_revision(monkeypatch, ):
    repository = _Repository()
    writer = _Writer()
    transactions = _Transactions()
    monkeypatch.setattr("application.core.objectives.finding_authoring_service.AsyncSessionLocal", transactions)
    service = FindingAuthoringService(collection_service=_Collection(), objective_repository=repository, experiment_query_service=_Query(), experiment_analysis_writer=writer)
    with pytest.raises(ValueError, match="parent Finding"):
        await service.create_selection_version(
            collection_id="collection-1",
            objective_id="objective-1",
            source_analysis_version=1,
            selection_ids=("selection-1",),
            created_by_user_id="user-1",
            parent_finding_id="foreign-parent",
        )
    assert transactions.events == []
    assert writer.call is None


@pytest.mark.anyio
async def test_selection_version_rolls_back_and_marks_running_snapshot_failed(monkeypatch, ):
    repository = _Repository(fail_publish=True)
    transactions = _Transactions()
    monkeypatch.setattr("application.core.objectives.finding_authoring_service.AsyncSessionLocal", transactions)
    service = FindingAuthoringService(collection_service=_Collection(), objective_repository=repository, experiment_query_service=_Query(), experiment_analysis_writer=_Writer())

    with pytest.raises(RuntimeError, match="publish failed"):
        await service.create_selection_version(
            collection_id="collection-1", objective_id="objective-1",
            source_analysis_version=1, selection_ids=("selection-1",),
            created_by_user_id="user-1",
        )

    assert transactions.events == ["begin", "rollback"]
    assert repository.failed["expected_status"] == "running"


async def test_authored_publication_preserves_coverage_with_real_repository(monkeypatch, *, postgres_session_factory):
    from tests.support.postgres import seed_collection
    await seed_collection(postgres_session_factory, "collection-1", document_ids=("paper-1", "paper-2", "paper-3"))
    repository = ObjectiveRepository()
    objective = replace(_objective(), active_analysis_version=None)
    await repository.replace(
        "collection-1", ObjectiveFactSet(research_objectives=(objective,))
    )
    inputs = tuple(
        PreparedDocumentInput(document_id=paper, preparation_fingerprint=paper)
        for paper in ("paper-1", "paper-2", "paper-3")
    )
    await repository.queue_analysis(
        "collection-1", "objective-1", document_inputs=inputs,
        pipeline_version="test", model_name=None, prompt_versions={},
    )
    await repository.claim_analysis("collection-1", "objective-1", 1)
    coverage = tuple(
        PaperContribution(
            collection_id="collection-1",
            objective_id="objective-1",
            analysis_version=1,
            document_id=finding_text(paper) or "",
            analysis_status=finding_choice(
                status, PAPER_CONTRIBUTION_STATUSES, "pending"
            ),
            relevance="uncertain",
            paper_role="uncertain",
            contribution_summary=None,
            material_match=(),
            changed_variables=(),
            measured_property_scope=(),
            test_environment_scope=(),
            exclusion_reason=None,
            warnings=normalize_objective_terms(
                [] if status == "analyzed" else [reason]
            ),
            confidence=0.0,
        )
        for paper, status, reason in (
            ("paper-1", "analyzed", ""),
            ("paper-2", "excluded", "Outside the material scope"),
            ("paper-3", "failed", "Source extraction failed"),
        )
    )
    async with database.AsyncSessionLocal() as db, db.begin():
        objective, source = await repository.publish_experiment_analysis(db, 'collection-1', 'objective-1', 1, contributions=coverage)

    writer = _Writer()
    monkeypatch.setattr("application.core.objectives.finding_authoring_service.AsyncSessionLocal", database.AsyncSessionLocal)
    service = FindingAuthoringService(collection_service=_Collection(), objective_repository=repository, experiment_query_service=_Query(), experiment_analysis_writer=writer)
    await service.create_selection_version(
        collection_id="collection-1", objective_id="objective-1",
        source_analysis_version=1, selection_ids=("selection-1",),
        created_by_user_id="user-1",
    )

    published = await repository.read_analysis("collection-1", "objective-1", 2)
    assert published.status == "succeeded"
    assert published.origin == "human_authored"
    assert published.scientific_record_source == "experiment_graph"
    assert published.source_analysis_version == 1
    assert published.created_by_user_id == "user-1"
    assert published.created_by_tool_call_id is None
    with pytest.raises(ValueError, match="source analysis version is stale"):
        await repository.queue_analysis(
            "collection-1", "objective-1", document_inputs=inputs,
            pipeline_version="test", model_name=None, prompt_versions={},
            origin="human_authored", source_analysis_version=1, created_by_user_id="user-1",
        )
    assert await repository.list_contributions("collection-1", "objective-1", 2) == tuple(
        replace(item, analysis_version=2) for item in coverage
    )
    assert await repository.list_contributions("collection-1", "objective-1", 1) == coverage
    assert "contributions" not in writer.call
