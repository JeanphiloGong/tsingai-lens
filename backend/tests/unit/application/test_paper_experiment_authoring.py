from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.paper_experiment_authoring import (
    PaperExperimentRevisionToolRequest,
    CreatePaperExperimentRevisionCapability,
    PaperExperimentDraftToolRequest,
    ProposePaperExperimentDraftCapability,
)
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringService,
)
from domain.chat import ChatMessage, ChatToolRequest, ChatToolResult
from domain.core.research_objective import ObjectiveAnalysis, PaperContribution, ResearchObjective


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
                "label": "Control experiment",
                "scope_description": "Control treatment measured for the requested outcome.",
                "design_type": "parallel",
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
                        "result_text": None,
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


def test_agent_request_schema_describes_structured_test_parameters() -> None:
    schema = ProposePaperExperimentDraftCapability.spec.model_schema()
    serialized = str(schema)
    assert "Structured test parameters" in serialized
    assert "strain_rate" in serialized
    assert "test_attributes" in serialized
    parameters_schema = schema["function"]["parameters"]
    test_condition_schema = parameters_schema["$defs"][
        "_PaperExperimentTestConditionToolField"
    ]
    assert "protocol_completeness" not in test_condition_schema["required"]

    request = PaperExperimentDraftToolRequest(
        objective_id="objective-1",
        document_id="paper-1",
        source_labels=["S001"],
        experiments=[
            {
                "series_key": "series-a",
                "label": "Tensile series",
                "scope_description": "One tensile test condition.",
                "test_conditions": [
                    {
                        "test_key": "tensile-1",
                        "test_type": "tensile",
                        "source_labels": ["S001"],
                        "protocol_specificity": "exact",
                        "protocol_completeness": "complete",
                        "parameters": [
                            {"name": "temperature", "value": 25, "unit": "C"},
                            {"name": "strain_rate", "value": 0.001, "unit": "1/s"},
                        ],
                    }
                ],
            }
        ],
    )
    raw = request.raw_draft()
    assert raw["experiments"][0]["test_conditions"][0]["parameters"][1]["name"] == "strain_rate"


def test_agent_request_allows_omitted_protocol_completeness() -> None:
    draft = deepcopy(_draft())
    draft["experiments"][0]["test_conditions"].append(
        {
            "test_key": "tensile-1",
            "test_type": "tensile",
            "source_labels": ["S001"],
            "protocol_specificity": "exact",
            "parameters": [],
        }
    )

    request = PaperExperimentDraftToolRequest(
        objective_id="objective-1",
        document_id="paper-1",
        **draft,
    )

    test_condition = request.experiments[0].test_conditions[0]
    assert test_condition.protocol_completeness == "unknown"
    assert "protocol_completeness" not in request.raw_draft()["experiments"][0][
        "test_conditions"
    ][0]


def test_agent_request_schema_describes_the_complete_scientific_graph() -> None:
    tool_schema = ProposePaperExperimentDraftCapability.spec.model_schema()
    schema = tool_schema["function"]["parameters"]
    description = tool_schema["function"]["description"]
    assert "label and scope_description" in description
    assert all(
        phrase in description
        for phrase in (
            "statement",
            "kind (result_summary, mechanism_hypothesis, or limitation)",
            "source_labels",
        )
    )
    experiment_schema = schema["$defs"]["_PaperExperimentDraftExperimentField"]
    comparison_schema = schema["$defs"]["_PaperExperimentComparisonToolField"]
    interpretation_schema = schema[
        "$defs"
    ]["_PaperExperimentReportedInterpretationToolField"]
    measurement_schema = schema["$defs"]["_PaperExperimentMeasurementToolField"]

    assert {"label", "scope_description"}.issubset(experiment_schema["required"])
    assert "design_type" in experiment_schema["properties"]
    assert experiment_schema["properties"]["comparisons"]["items"]["$ref"].endswith(
        "_PaperExperimentComparisonToolField"
    )
    assert experiment_schema["properties"]["reported_interpretations"]["items"][
        "$ref"
    ].endswith("_PaperExperimentReportedInterpretationToolField")
    assert comparison_schema["additionalProperties"] is False
    assert {
        "comparison_key",
        "baseline_variant_key",
        "target_variant_key",
        "outcome",
        "baseline_measurement_keys",
        "target_measurement_keys",
        "source_labels",
        "binding_source_labels",
    }.issubset(comparison_schema["required"])
    assert interpretation_schema["additionalProperties"] is False
    assert {"statement", "kind", "source_labels"}.issubset(
        interpretation_schema["required"]
    )
    assert {
        "measurement_key",
        "outcome",
        "source_labels",
    }.issubset(measurement_schema["required"])


def test_agent_request_rejects_missing_interpretation_kind_and_experiment_scope() -> None:
    with pytest.raises(ValidationError):
        PaperExperimentDraftToolRequest(
            objective_id="objective-1",
            document_id="paper-1",
            experiments=[
                {
                    "series_key": "series-a",
                    "scope_kind": "parent",
                    "experimental_variants": [],
                    "test_conditions": [],
                    "measurements": [],
                    "comparisons": [],
                    "reported_interpretations": [
                        {"statement": "The treatment improved the outcome.", "source_labels": ["S001"]}
                    ],
                }
            ],
        )


def test_agent_request_rejects_measurement_without_a_reported_result() -> None:
    with pytest.raises(ValidationError, match="measurement requires value or result_text"):
        PaperExperimentDraftToolRequest(
            objective_id="objective-1",
            document_id="paper-1",
            experiments=[
                {
                    "label": "Tensile series",
                    "scope_description": "One tensile test condition.",
                    "measurements": [
                        {
                            "measurement_key": "m1",
                            "outcome": "elongation",
                            "value": None,
                            "result_text": None,
                            "source_labels": ["S001"],
                        }
                    ],
                }
            ],
        )


@pytest.mark.parametrize("reported_result", [{"value": 0}, {"result_text": "Ductile dimples"}])
def test_agent_request_accepts_numeric_or_qualitative_result_without_unused_field(reported_result) -> None:
    request = PaperExperimentDraftToolRequest(
        objective_id="objective-1",
        document_id="paper-1",
        experiments=[{
            "label": "316L tensile series",
            "scope_description": "One source-reported specimen cohort.",
            "measurements": [{
                "measurement_key": "m1", "outcome": "reported result",
                "source_labels": ["S001"], **reported_result,
            }],
        }],
    )
    measurement = request.raw_draft()["experiments"][0]["measurements"][0]
    assert all(measurement[key] == value for key, value in reported_result.items())


def test_agent_request_rejects_omitted_numeric_and_qualitative_result() -> None:
    with pytest.raises(ValidationError, match="measurement requires value or result_text"):
        PaperExperimentDraftToolRequest(
            objective_id="objective-1", document_id="paper-1",
            experiments=[{
                "label": "316L tensile series", "scope_description": "One specimen cohort.",
                "measurements": [{"measurement_key": "m1", "outcome": "elongation", "source_labels": ["S001"]}],
            }],
        )


@pytest.mark.anyio
async def test_agent_request_parameters_survive_authoring_prepare() -> None:
    draft = deepcopy(_draft())
    draft["experiments"][0]["test_conditions"] = [
        {
            "test_key": "tensile-1",
            "test_type": "tensile",
            "source_labels": ["S001"],
            "protocol_specificity": "exact",
            "protocol_completeness": "complete",
            "parameters": [
                {"name": "temperature", "value": 25, "unit": "C"},
                {"name": "strain_rate", "value": 0.001, "unit": "1/s"},
                {"name": "n", "value": 5},
            ],
        }
    ]
    request = PaperExperimentDraftToolRequest(
        objective_id="objective-1", document_id="paper-1", **draft
    )
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceRepository(),
        objective_repository=_ObjectiveRepository(),
        experiment_analysis_writer=object(),
    )
    prepared = await service.prepare(
        collection_id="collection-1",
        user_id="user-1",
        objective_id=request.objective_id,
        document_id=request.document_id,
        raw_draft=request.raw_draft(),
    )
    parameters = prepared.output.output.experiments[0].payload["test_conditions"][0][
        "parameters"
    ]
    assert parameters == [
        {"name": "temperature", "value": 25, "unit": "C"},
        {"name": "strain_rate", "value": 0.001, "unit": "1/s"},
        {"name": "n", "value": 5},
    ]


class _CollectionService:
    async def get_collection_for_user(self, collection_id, user_id):
        return {"collection_id": collection_id, "owner_user_id": user_id}

    async def get_document(self, collection_id, document_id):
        return SimpleNamespace(preparation_fingerprint="prep-1")


async def test_review_digest_changes_when_source_analysis_advances():
    repository = _ObjectiveRepository()
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(), source_artifact_repository=_SourceRepository(),
        objective_repository=repository, experiment_analysis_writer=object(),
    )
    kwargs = dict(collection_id="collection-1", user_id="user-1",
                  objective_id="objective-1", document_id="paper-1", raw_draft=_draft())
    first = await service.prepare(**kwargs)
    assert (await service.prepare(**kwargs)).draft_digest == first.draft_digest
    async def advanced_objective(*args):
        return replace(_objective(), active_analysis_version=2)
    async def advanced_analysis(*args):
        return replace(_analysis(), analysis_version=2)
    repository.read_objective = advanced_objective
    repository.read_analysis = advanced_analysis
    second = await service.prepare(**kwargs)
    assert second.draft_digest != first.draft_digest
    stored = ChatMessage.from_tool_result(
        message_id="review-1", session_id="session-1", created_at="2026-09-30T00:00:00Z",
        result=ChatToolResult(tool_call_id="proposal-1", status="succeeded", data={
                "draft_id": "reviewed-draft", "draft_digest": first.draft_digest,
                "status": "pending_approval", "draft_created_at": datetime.now(timezone.utc).isoformat(),
            "objective_id": "objective-1", "document_id": "paper-1", "draft": _draft(),
        }),
    )
    from unittest.mock import AsyncMock
    service.write = AsyncMock()
    capability = CreatePaperExperimentRevisionCapability(
        authoring_service=service, chat_repository=_ChatRepository((stored,)),
    )
    with pytest.raises(ValueError, match="digest changed"):
        await capability.execute(
            CapabilityExecutionContext(session_id="session-1", user_id="user-1",
                                       collection_id="collection-1", tool_call_id="save-1"),
            PaperExperimentRevisionToolRequest(draft_id="reviewed-draft", draft_digest=first.draft_digest),
        )
    service.write.assert_not_awaited()


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

    async def queue_analysis(self, *args, **kwargs):
        return _objective(), _analysis()

    async def claim_analysis(self, *args, **kwargs):
        return _analysis()

    async def publish_experiment_analysis(self, *args, **kwargs):
        return _objective(), _analysis()


class _WriteRepository(_ObjectiveRepository):
    def __init__(self, *, fail_publish: bool = False):
        self.fail_publish = fail_publish
        self.published = None
        self.failed = None

    async def queue_analysis(self, *args, **kwargs):
        return _objective(), ObjectiveAnalysis.from_mapping(
            {
                "collection_id": "collection-1",
                "objective_id": "objective-1",
                "analysis_version": 2,
                "document_inputs": [
                    {"document_id": "paper-1", "preparation_fingerprint": "prep-1"}
                ],
                "pipeline_version": "test",
                "status": "queued",
                "processed_document_count": 0,
                "total_document_count": 1,
            }
        )

    async def claim_analysis(self, *args, **kwargs):
        return ObjectiveAnalysis.from_mapping(
            {
                "collection_id": "collection-1",
                "objective_id": "objective-1",
                "analysis_version": 2,
                "document_inputs": [
                    {"document_id": "paper-1", "preparation_fingerprint": "prep-1"}
                ],
                "pipeline_version": "test",
                "status": "running",
                "processed_document_count": 0,
                "total_document_count": 1,
            }
        )

    async def list_contributions(self, *args, **kwargs):
        return (
            PaperContribution.from_mapping(
                {
                    "collection_id": "collection-1",
                    "objective_id": "objective-1",
                    "analysis_version": 1,
                    "document_id": "paper-1",
                    "analysis_status": "analyzed",
                    "relevance": "relevant",
                    "paper_role": "primary",
                    "confidence": 0.9,
                }
            ),
        )

    async def publish_experiment_analysis(self, *args, **kwargs):
        self.published = kwargs
        if self.fail_publish:
            raise RuntimeError("publish failed")
        return _objective(), _analysis()

    async def fail_analysis(self, *args, **kwargs):
        self.failed = kwargs
        return _analysis()


class _Writer:
    async def write_single_experiment_revision(self, **kwargs):
        self.transaction = kwargs.get("transaction")
        return SimpleNamespace(revisions=(), selections=(), groups=(), findings=())


class _TransactionFactory:
    def __init__(self):
        self.handle = object()
        self.events = []

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


@pytest.mark.anyio
async def test_write_rebinds_contributions_and_fails_running_snapshot_on_publish_error():
    repository = _WriteRepository(fail_publish=True)
    writer = _Writer()
    transactions = _TransactionFactory()
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceRepository(),
        objective_repository=repository,
        experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=transactions,
    )
    prepared = await service.prepare(
        collection_id="collection-1",
        user_id="user-1",
        objective_id="objective-1",
        document_id="paper-1",
        raw_draft=_draft(),
    )

    with pytest.raises(RuntimeError, match="publish failed"):
        await service.write(
            prepared=prepared,
            collection_id="collection-1",
            created_by="user-1",
            created_by_tool_call_id="call-1",
        )

    assert transactions.events == ["begin", "rollback"]
    assert writer.transaction is transactions.handle
    assert repository.published["contributions"][0].analysis_version == 2
    assert repository.published["transaction"] is transactions.handle
    assert repository.failed["expected_status"] == "running"


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
        source_digests={"block-1": sha256(b"Methods").hexdigest()},
        output=SimpleNamespace(output=SimpleNamespace(experiments=(experiment,), source_labels={
            "S001": {"source_ref": "block-1", "source_kind": "text_window"},
        })),
    )


def _read_messages(content="Methods", complete=True):
    return (
        ChatMessage.assistant_tool_calls(message_id="read-request", session_id="session-1", content="", created_at="2026-09-30T00:00:00Z",
            tool_calls=(ChatToolRequest(tool_call_id="read-1", name="read_source", arguments={}, position=0),)),
        ChatMessage.from_tool_result(message_id="read-result", session_id="session-1", created_at="2026-09-30T00:00:01Z",
            result=ChatToolResult(tool_call_id="read-1", status="succeeded", data={
                "document_id": "paper-1", "source_kind": "text_window", "source_ref": "block-1",
                "source_digest": sha256(content.encode()).hexdigest(), "content": content, "content_truncated": not complete,
            })),
    )


@pytest.mark.parametrize(("content", "complete", "expected_status"), [
    ("Methods", True, "succeeded"),
    ("Old Methods", True, "failed"),
    ("Methods", False, "failed"),
])
async def test_experiment_draft_requires_current_complete_read_for_every_cited_source(content, complete, expected_status):
    draft = _draft()
    authoring = _AuthoringStub(_prepared_for_capability(draft))
    capability = ProposePaperExperimentDraftCapability(authoring_service=authoring, chat_repository=_ChatRepository(_read_messages(content, complete)))
    result = await capability.execute(
        CapabilityExecutionContext(session_id="session-1", user_id="user-1", collection_id="collection-1", tool_call_id="draft-1"),
        PaperExperimentDraftToolRequest(objective_id="objective-1", document_id="paper-1", **draft),
    )
    assert result.status.value == expected_status
    assert not authoring.write_calls
    if expected_status == "failed":
        assert result.error_code == "source_read_incomplete"
        assert result.data["sources_to_read"] == [{"source_label": "S001", "source_kind": "text_window", "source_ref": "block-1"}]
        assert "Keep the experiment facts" in result.error_message


async def test_experiment_draft_does_not_treat_one_read_as_coverage_for_another_source():
    draft = _draft()
    prepared = _prepared_for_capability(draft)
    prepared.output.output.source_labels["S002"] = {"source_ref": "results-1", "source_kind": "text_window"}
    prepared.source_digests["results-1"] = sha256(b"Results").hexdigest()
    draft["experiments"][0]["measurements"][0]["source_labels"] = ["S002"]
    result = await ProposePaperExperimentDraftCapability(
        authoring_service=_AuthoringStub(prepared), chat_repository=_ChatRepository(_read_messages()),
    ).execute(
        CapabilityExecutionContext(session_id="session-1", user_id="user-1", collection_id="collection-1", tool_call_id="draft-1"),
        PaperExperimentDraftToolRequest(objective_id="objective-1", document_id="paper-1", **draft),
    )
    assert result.status.value == "failed"
    assert result.data["sources_to_read"] == [{"source_label": "S002", "source_kind": "text_window", "source_ref": "results-1"}]


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
        authoring_service=authoring, chat_repository=_ChatRepository(_read_messages())
    ).execute(
        context,
        PaperExperimentDraftToolRequest(
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
        PaperExperimentRevisionToolRequest(
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
            PaperExperimentRevisionToolRequest(
                draft_id="pexp_draft_missing", draft_digest="a" * 64
            ),
        )
