from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.paper_experiment_authoring import (
    CreatePaperExperimentRevisionArguments,
    CreatePaperExperimentRevisionCapability,
    ProposePaperExperimentDraftArguments,
    ProposePaperExperimentDraftCapability,
)
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringService,
)
from domain.chat import ChatMessage, ChatToolResult
from domain.core.research_objective import ObjectiveAnalysis, ResearchObjective


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "Does treatment change the outcome?",
            "variables": ["treatment"],
            "outcomes": ["outcome"],
            "confirmation_status": "confirmed",
            "active_analysis_version": 1,
        }
    )


def _analysis() -> ObjectiveAnalysis:
    return ObjectiveAnalysis.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "document_inputs": [
                {"document_id": "paper-1", "preparation_fingerprint": "prep-1"}
            ],
            "pipeline_version": "test",
            "status": "succeeded",
            "processed_document_count": 1,
            "total_document_count": 1,
        }
    )


def _draft() -> dict:
    return {
        "source_labels": ["S001"],
        "experiments": [
            {
                "series_key": "series-a",
                "scope_kind": "parent",
                "experimental_variants": [
                    {
                        "variant_key": "control",
                        "variant_label": "control",
                        "subject_attributes": [],
                        "intervention_attributes": [
                            {"name": "treatment", "value": "none"}
                        ],
                        "source_labels": ["S001"],
                        "binding_source_labels": ["S001"],
                    }
                ],
                "test_conditions": [],
                "measurements": [
                    {
                        "measurement_key": "m1",
                        "variant_key": "control",
                        "outcome": "outcome",
                        "value": 1,
                        "unit": "unit",
                        "source_labels": ["S001"],
                    }
                ],
                "comparisons": [],
                "unresolved_issues": [],
            }
        ],
        "unresolved_issues": [],
    }


class _CollectionService:
    async def get_collection_for_user(self, collection_id, user_id):
        return {"collection_id": collection_id, "owner_user_id": user_id}

    async def get_document(self, collection_id, document_id):
        return SimpleNamespace(preparation_fingerprint="prep-1")


class _SourceRepository:
    async def read_document(self, collection_id, document_id):
        return SimpleNamespace(
            metadata={},
            blocks=(
                SimpleNamespace(
                    block_id="block-1",
                    block_order=1,
                    block_type="paragraph",
                    text="The control treatment was measured.",
                    page=1,
                    heading_path="Methods",
                ),
            ),
            tables=(),
            figures=(),
        )


class _ObjectiveRepository:
    async def read_objective(self, collection_id, objective_id):
        return _objective()

    async def read_analysis(self, collection_id, objective_id, analysis_version=None):
        return _analysis()


@pytest.mark.anyio
async def test_prepare_reloads_source_context_and_rejects_formal_ids():
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceRepository(),
        objective_repository=_ObjectiveRepository(),
        experiment_analysis_writer=object(),
    )
    prepared = await service.prepare(
        collection_id="collection-1",
        user_id="user-1",
        objective_id="objective-1",
        document_id="paper-1",
        raw_draft=_draft(),
    )
    assert prepared.source_fingerprint == "prep-1"
    assert prepared.output.output.document_id == "paper-1"
    assert prepared.output.output.source_labels["S001"]["source_ref"] == "block-1"

    invalid = _draft()
    invalid["experiments"][0]["experiment_id"] = "model-owned-id"
    with pytest.raises(ValueError, match="formal identity"):
        await service.prepare(
            collection_id="collection-1",
            user_id="user-1",
            objective_id="objective-1",
            document_id="paper-1",
            raw_draft=invalid,
        )


class _AuthoringStub:
    def __init__(self, prepared):
        self.prepared = prepared
        self.prepare_calls = []
        self.write_calls = []

    async def prepare(self, **kwargs):
        self.prepare_calls.append(kwargs)
        return self.prepared

    async def write(self, **kwargs):
        self.write_calls.append(kwargs)
        revision = SimpleNamespace(
            revision=SimpleNamespace(
                experiment_id="pexp-1",
                experiment_version=1,
                document_id="paper-1",
                to_record=lambda: {"experiment_id": "pexp-1", "experiment_version": 1},
            )
        )
        selection = SimpleNamespace(selection_id="selection-1")
        return SimpleNamespace(revisions=(revision,), selections=(selection,))


class _ChatRepository:
    def __init__(self, messages=()):
        self.messages = tuple(messages)

    async def read_messages(self, session_id):
        return self.messages


def _prepared_for_capability(draft):
    experiment = SimpleNamespace(payload=draft["experiments"][0])
    return SimpleNamespace(
        draft_digest="a" * 64,
        source_fingerprint="prep-1",
        output=SimpleNamespace(output=SimpleNamespace(experiments=(experiment,))),
    )


@pytest.mark.anyio
async def test_agent_experiment_draft_can_only_be_published_from_stored_digest():
    draft = _draft()
    authoring = _AuthoringStub(_prepared_for_capability(draft))
    context = CapabilityExecutionContext(
        session_id="session-1",
        user_id="user-1",
        collection_id="collection-1",
        tool_call_id="call-propose",
    )
    proposed = await ProposePaperExperimentDraftCapability(
        authoring_service=authoring
    ).execute(
        context,
        ProposePaperExperimentDraftArguments(
            objective_id="objective-1", document_id="paper-1", **draft
        ),
    )
    assert proposed.data["status"] == "pending_approval"
    assert proposed.data["published"] is False

    message = ChatMessage.from_tool_result(
        message_id="message-1",
        session_id="session-1",
        result=proposed,
        created_at="2026-09-28T00:00:00+00:00",
    )
    repository = _ChatRepository((message,))
    created = await CreatePaperExperimentRevisionCapability(
        authoring_service=authoring,
        chat_repository=repository,
    ).execute(
        context.__class__(
            session_id="session-1",
            user_id="user-1",
            collection_id="collection-1",
            tool_call_id="call-create",
        ),
        CreatePaperExperimentRevisionArguments(
            draft_id=proposed.data["draft_id"],
            draft_digest=proposed.data["draft_digest"],
        ),
    )
    assert created.data["published"] is True
    assert created.data["selection_ids"] == ["selection-1"]
    assert created.data["finding_ids"] == []
    assert authoring.write_calls


@pytest.mark.anyio
async def test_agent_experiment_revision_rejects_unknown_or_changed_draft():
    authoring = _AuthoringStub(_prepared_for_capability(_draft()))
    capability = CreatePaperExperimentRevisionCapability(
        authoring_service=authoring,
        chat_repository=_ChatRepository(),
    )
    context = CapabilityExecutionContext(
        session_id="session-1",
        user_id="user-1",
        collection_id="collection-1",
        tool_call_id="call-create",
    )
    with pytest.raises(ValueError, match="not found"):
        await capability.execute(
            context,
            CreatePaperExperimentRevisionArguments(
                draft_id="pexp_draft_missing", draft_digest="a" * 64
            ),
        )
