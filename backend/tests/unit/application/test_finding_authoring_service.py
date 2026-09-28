from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from application.core.objectives.finding_authoring_service import FindingAuthoringService
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.research_objective import ObjectiveAnalysis, PaperContribution, ResearchObjective


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
