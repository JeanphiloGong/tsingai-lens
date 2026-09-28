from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.core.objectives.finding_authoring_service import FindingAuthoringService
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.research_objective import (
    ObjectiveAnalysis, ObjectiveFactSet, PaperContribution, PreparedDocumentInput,
    ResearchObjective,
)
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringService,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping({
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "question": "Does treatment change outcome?",
        "variables": ["treatment"],
        "outcomes": ["outcome"],
        "confirmation_status": "confirmed",
        "active_analysis_version": 1,
    })


def _analysis(version: int, status: str) -> ObjectiveAnalysis:
    return ObjectiveAnalysis.from_mapping({
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": version,
        "document_inputs": [{"document_id": "paper-1", "preparation_fingerprint": "p1"}],
        "pipeline_version": "test",
        "status": status,
        "processed_document_count": 1,
        "total_document_count": 1,
    })


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
    def __init__(self):
        self.events = []
        self.handle = object()

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
        return (PaperContribution.from_mapping({
            "collection_id": "collection-1", "objective_id": "objective-1",
            "analysis_version": args[-1], "document_id": "paper-1",
            "analysis_status": "analyzed", "relevance": "relevant",
        }),)

    async def publish_experiment_analysis(self, *args, **kwargs):
        self.published = kwargs
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
        )


class _Writer:
    def __init__(self):
        self.call = None

    async def write_selection_finding_revision(self, **kwargs):
        self.call = kwargs
        selection = kwargs["selections"][0]
        finding = SimpleNamespace(selection_ids=(selection.selection_id,))
        return SimpleNamespace(findings=(finding,), revisions=(), selections=(), groups=())


@pytest.mark.anyio
async def test_selection_version_copies_contributions_and_uses_one_transaction():
    repository = _Repository()
    transactions = _Transactions()
    writer = _Writer()
    service = FindingAuthoringService(
        collection_service=_Collection(), objective_repository=repository,
        experiment_query_service=_Query(), experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=transactions,
    )

    result = await service.create_selection_version(
        collection_id="collection-1", objective_id="objective-1",
        source_analysis_version=1, selection_ids=("selection-1",),
        created_by_user_id="user-1",
    )

    assert transactions.events == ["begin", "commit"]
    assert writer.call["transaction"] is transactions.handle
    assert writer.call["selections"][0].selection_id == "selection-1"
    assert repository.published["transaction"] is transactions.handle
    assert repository.published["contributions"][0].analysis_version == 2
    assert "contributions" not in writer.call
    assert result.finding is not None


@pytest.mark.anyio
async def test_selection_version_rolls_back_and_marks_running_snapshot_failed():
    repository = _Repository(fail_publish=True)
    transactions = _Transactions()
    service = FindingAuthoringService(
        collection_service=_Collection(), objective_repository=repository,
        experiment_query_service=_Query(), experiment_analysis_writer=_Writer(),
        experiment_analysis_transaction_factory=transactions,
    )

    with pytest.raises(RuntimeError, match="publish failed"):
        await service.create_selection_version(
            collection_id="collection-1", objective_id="objective-1",
            source_analysis_version=1, selection_ids=("selection-1",),
            created_by_user_id="user-1",
        )

    assert transactions.events == ["begin", "rollback"]
    assert repository.failed["expected_status"] == "running"


@pytest.mark.parametrize("origin", ["human_authored", "agent_authored"])
async def test_authored_publication_preserves_coverage_with_real_repository(origin):
    repository = MemoryObjectiveRepository()
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
        PaperContribution.from_mapping({
            "collection_id": "collection-1", "objective_id": "objective-1",
            "analysis_version": 1, "document_id": paper,
            "analysis_status": status,
            "warnings": [] if status == "analyzed" else [reason],
        })
        for paper, status, reason in (
            ("paper-1", "analyzed", ""),
            ("paper-2", "excluded", "Outside the material scope"),
            ("paper-3", "failed", "Source extraction failed"),
        )
    )
    objective, source = await repository.publish_experiment_analysis(
        "collection-1", "objective-1", 1, contributions=coverage,
    )
    transactions = _Transactions()
    writer = _Writer()
    if origin == "human_authored":
        service = FindingAuthoringService(
            collection_service=_Collection(), objective_repository=repository,
            experiment_query_service=_Query(), experiment_analysis_writer=writer,
            experiment_analysis_transaction_factory=transactions,
        )
        await service.create_selection_version(
            collection_id="collection-1", objective_id="objective-1",
            source_analysis_version=1, selection_ids=("selection-1",),
            created_by_user_id="user-1",
        )
    else:
        async def write_experiment(**kwargs):
            writer.call = kwargs
            return SimpleNamespace(revisions=(), selections=(), groups=(), findings=())

        writer.write_single_experiment_revision = write_experiment
        service = PaperExperimentAuthoringService(
            collection_service=_Collection(), source_artifact_repository=None,
            objective_repository=repository, experiment_analysis_writer=writer,
            experiment_analysis_transaction_factory=transactions,
        )
        await service.write(
            prepared=SimpleNamespace(objective=objective, analysis=source, output=None),
            collection_id="collection-1", created_by="user-1",
            created_by_tool_call_id="call-1",
        )

    published = await repository.read_analysis("collection-1", "objective-1", 2)
    assert published.status == "succeeded"
    assert published.origin == origin
    assert published.scientific_record_source == "experiment_graph"
    assert published.source_analysis_version == 1
    assert published.created_by_user_id == "user-1"
    assert published.created_by_tool_call_id == (
        "call-1" if origin == "agent_authored" else None
    )
    with pytest.raises(ValueError, match="source analysis version is stale"):
        await repository.queue_analysis(
            "collection-1", "objective-1", document_inputs=inputs,
            pipeline_version="test", model_name=None, prompt_versions={},
            origin=origin, source_analysis_version=1, created_by_user_id="user-1",
            created_by_tool_call_id="call-2" if origin == "agent_authored" else None,
        )
    assert await repository.list_contributions("collection-1", "objective-1", 2) == tuple(
        replace(item, analysis_version=2) for item in coverage
    )
    assert await repository.list_contributions("collection-1", "objective-1", 1) == coverage
    assert "contributions" not in writer.call
    assert transactions.events == ["begin", "commit"]
