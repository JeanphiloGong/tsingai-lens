from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.paper_experiment_authoring import (
    CreatePaperExperimentRevisionCapability,
    PaperExperimentDraftToolRequest,
    PaperExperimentRevisionToolRequest,
    ProposePaperExperimentDraftCapability,
)
from application.core.objectives.paper_experiment_authoring_service import (
    PaperExperimentAuthoringService,
)
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentDraftValidationError,
)
from domain.chat import ChatMessage, ChatToolRequest, ChatToolResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
        experiment_analysis_writer=object(),
    )
    prepared = await service.prepare(
        collection_id="collection-1",
        user_id="user-1",
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


async def test_prepare_reports_comparison_outcome_validation_as_repairable_error() -> None:
    draft = deepcopy(_draft())
    experiment = draft["experiments"][0]
    experiment["measurements"].append({
        "measurement_key": "m2",
        "variant_key": "control",
        "outcome": "hardness",
        "value": 10,
        "result_text": None,
        "unit": "HV",
        "source_labels": ["S001"],
    })
    experiment["comparisons"] = [{
        "comparison_key": "mixed-outcomes",
        "baseline_variant_key": "control",
        "target_variant_key": "control",
        "outcome": "outcome",
        "baseline_measurement_keys": ["m1"],
        "target_measurement_keys": ["m2"],
        "source_labels": ["S001"],
        "binding_source_labels": ["S001"],
    }]
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceRepository(),
        experiment_analysis_writer=object(),
    )

    with pytest.raises(PaperExperimentDraftValidationError) as error:
        await service.prepare(
            collection_id="collection-1",
            user_id="user-1",
            document_id="paper-1",
            raw_draft=draft,
        )

    assert error.value.error_code == "draft_validation_failed"
    assert error.value.validation_path == "experiments[0]"
    assert "comparison outcome does not match" in str(error.value)


class _CollectionService:
    async def get_collection_for_user(self, collection_id, user_id):
        return {"collection_id": collection_id, "owner_user_id": user_id}

    async def get_document(self, collection_id, document_id):
        return SimpleNamespace(
            document=SimpleNamespace(
                preparation_fingerprint="prep-1",
                source_fingerprint=None,
            )
        )


async def test_review_digest_is_stable_without_objective_context():
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(), source_artifact_repository=_SourceRepository(),
        experiment_analysis_writer=object(),
    )
    first = await service.prepare(
        collection_id="collection-1", user_id="user-1",
        document_id="paper-1", raw_draft=_draft()
    )
    second = await service.prepare(
        collection_id="collection-1", user_id="user-1",
        document_id="paper-1", raw_draft=_draft()
    )
    assert second.draft_digest == first.draft_digest


class _SourceRepository:
    text = "The control treatment was measured."

    async def read_document(self, collection_id, document_id):
        return SimpleNamespace(
            metadata={},
            blocks=(
                SimpleNamespace(
                    block_id="block-1",
                    block_order=1,
                    block_type="paragraph",
                    text=self.text,
                    page=1,
                    heading_path="Methods",
                ),
            ),
            tables=(),
            figures=(),
        )


class _Writer:
    async def write_paper_experiment_revisions(self, **kwargs):
        self.transaction = kwargs.get("transaction")
        self.output_count = len(kwargs["experiment_outputs"])
        return SimpleNamespace(revisions=(), selections=(), groups=(), findings=())


@pytest.mark.parametrize("change", ["source", "payload", "collection"])
async def test_review_digest_invalidated_by_content_or_scope_change(change):
    sources = _SourceRepository()
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(), source_artifact_repository=sources,
        experiment_analysis_writer=object(),
    )
    arguments = dict(collection_id="collection-1", user_id="user-1", document_id="paper-1", raw_draft=_draft())
    first = await service.prepare(**arguments)
    if change == "source":
        sources.text = "The control treatment was measured again."
    elif change == "payload":
        arguments["raw_draft"]["experiments"][0]["measurements"][0]["value"] = 2
    else:
        arguments["collection_id"] = "collection-2"
    second = await service.prepare(**arguments)
    assert first.source_fingerprint == second.source_fingerprint
    assert first.draft_digest != second.draft_digest


async def test_prepare_rejects_foreign_collection_before_reading_sources():
    class DeniedCollection(_CollectionService):
        async def get_collection_for_user(self, collection_id, user_id):
            raise PermissionError("not the collection owner")

    service = PaperExperimentAuthoringService(
        collection_service=DeniedCollection(), source_artifact_repository=object(),
        experiment_analysis_writer=object(),
    )
    with pytest.raises(PermissionError):
        await service.prepare(collection_id="collection-1", user_id="other-user", document_id="paper-1", raw_draft=_draft())


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
async def test_write_saves_paper_experiment_without_objective_analysis():
    writer = _Writer()
    transactions = _TransactionFactory()
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceRepository(),
        experiment_analysis_writer=writer,
        experiment_analysis_transaction_factory=transactions,
    )
    prepared = await service.prepare(
        collection_id="collection-1",
        user_id="user-1",
        document_id="paper-1",
        raw_draft=_draft(),
    )

    result = await service.write(
        prepared=prepared,
        collection_id="collection-1",
        created_by="user-1",
    )

    assert transactions.events == ["begin", "commit"]
    assert writer.transaction is transactions.handle
    assert writer.output_count == 1
    assert result.selections == ()
    assert result.findings == ()


@pytest.mark.anyio
async def test_prepare_reloads_source_context_and_rejects_formal_ids():
    service = PaperExperimentAuthoringService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceRepository(),
        experiment_analysis_writer=object(),
    )
    prepared = await service.prepare(
        collection_id="collection-1",
        user_id="user-1",
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
        return SimpleNamespace(revisions=(revision,), selections=(), findings=())


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
async def test_agent_experiment_draft_can_only_be_saved_from_stored_digest():
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
            document_id="paper-1", **draft
        ),
    )
    assert proposed.data["status"] == "pending_approval"
    assert proposed.data["requires_user_approval"] is True

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
    assert created.data["revision_saved"] is True
    assert created.data["selection_ids"] == []
    assert created.data["finding_ids"] == []
    assert authoring.write_calls


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["digest", "expired", "source_changed"])
async def test_agent_save_rejects_stale_or_unapproved_draft(change):
    prepared = _prepared_for_capability(_draft())
    authoring = _AuthoringStub(prepared)
    context = CapabilityExecutionContext(
        session_id="session-1", user_id="user-1", collection_id="collection-1", tool_call_id="call-1",
    )
    proposed = await ProposePaperExperimentDraftCapability(
        authoring_service=authoring, chat_repository=_ChatRepository(_read_messages()),
    ).execute(context, PaperExperimentDraftToolRequest(document_id="paper-1", **_draft()))
    arguments = PaperExperimentRevisionToolRequest(
        draft_id=proposed.data["draft_id"], draft_digest=proposed.data["draft_digest"],
    )
    if change == "digest":
        arguments.draft_digest = "b" * 64
    elif change == "expired":
        proposed.data["draft_created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    else:
        prepared.draft_digest = "b" * 64
    message = ChatMessage.from_tool_result(
        message_id="draft-result", session_id="session-1", result=proposed,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with pytest.raises(ValueError, match="digest|expired"):
        await CreatePaperExperimentRevisionCapability(
            authoring_service=authoring, chat_repository=_ChatRepository((message,)),
        ).execute(context, arguments)
    assert authoring.write_calls == []


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
