from __future__ import annotations

from collections import deque
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from application.chat import ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.capabilities import (
    AssessObjectiveQualityCapability,
    CapabilityRegistry,
    ConfirmObjectiveCapability,
    CreateFindingVersionCapability,
    CreateObjectiveCandidateCapability,
    CreateResearchPlanCapability,
    DeriveObjectiveCapability,
    InspectDocumentSourcesCapability,
    ProposeResearchPlanCapability,
    PublishAgentObjectiveAnalysisCapability,
    RecordFindingFeedbackCapability,
)
from application.chat.session_service import ChatSessionService
from application.core.objectives.agent_analysis_service import (
    AgentObjectiveAnalysisService,
)
from application.core.objectives.analysis_service import ObjectiveAnalysisService
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from application.core.objectives.objective_authoring_service import (
    ObjectiveAuthoringService,
)
from application.core.objectives.objective_analysis_service import (
    ObjectiveEvidenceAnalysisService,
)
from application.evaluation import FindingFeedbackService
from application.goal.experiment_plan_service import ExperimentPlanService
from application.source.collection_service import CollectionService
from domain.chat import ChatMessage, ChatToolCall, ChatToolResult, ToolCallStatus
from domain.source import SourceDocument
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.experiment_plan_repository import (
    PostgresExperimentPlanRepository,
)
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from tests.integration.persistence.test_postgres_source_artifacts import (
    COLLECTION_ID,
    _source,
)
from tests.unit.application.test_research_agent_runner import _Model


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

_USER_ID = "user_source"
_P002_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "agent_p002" / "source_document.json"
)


class _QueuedModel(_Model):
    """Deterministic model turns while the real Agent loop owns tool execution."""

    def __init__(self) -> None:
        super().__init__()

    def queue_tool(self, name: str, arguments: dict[str, Any]) -> None:
        self.turns.extend(
            (
                ModelTurn(tool_calls=(ModelToolCall(name=name, arguments=arguments),)),
                ModelTurn(content=f"{name} completed."),
            )
        )

def _p002_source() -> SourceDocument:
    payload = json.loads(_P002_FIXTURE.read_text(encoding="utf-8"))
    payload["document_id"] = "doc_a"
    for field in ("blocks", "tables", "table_rows", "table_cells", "figures"):
        for item in payload.get(field) or ():
            item["document_id"] = "doc_a"
    for item in payload.get("text_units") or ():
        item["document_ids"] = ["doc_a"]
    return SourceDocument.from_record(payload)


def _no_result_source() -> SourceDocument:
    source = _source("doc_b", title="LPBF process-calibration review")
    text = (
        "This review summarizes build-platform temperature control and powder "
        "handling, but reports no mechanical-property measurements."
    )
    return replace(
        source,
        text=text,
        text_units=(
            replace(source.text_units[0], text=text, document_ids=("doc_b",)),
        ),
        blocks=(
            replace(
                source.blocks[0],
                text=text,
                heading_path="Review scope",
            ),
        ),
        tables=(),
        table_rows=(),
        table_cells=(),
        figures=(),
    )


def _tool_result(turn: dict[str, Any]) -> ChatToolResult:
    results = [
        message.tool_result
        for message in turn["messages"]
        if isinstance(message, ChatMessage) and message.tool_result is not None
    ]
    domain_results = [result for result in results if "catalog_version" not in result.data]
    assert len(domain_results) == 1
    return domain_results[0]


async def _run_tool(
    service: ChatSessionService,
    model: _QueuedModel,
    *,
    session_id: str,
    name: str,
    arguments: dict[str, Any],
    user_message: str,
) -> ChatToolResult:
    model.queue_tool(name, arguments)
    turn = await service.post_message_for_user(
        session_id,
        _USER_ID,
        message=user_message,
    )
    assert turn["status"] == "completed"
    assert turn["pending_approval"] is None
    result = _tool_result(turn)
    assert result.status.value == "succeeded", result.to_record()
    return result


async def _request_write(
    service: ChatSessionService,
    model: _QueuedModel,
    *,
    session_id: str,
    name: str,
    arguments: dict[str, Any],
    user_message: str,
) -> ChatToolCall:
    model.queue_tool(name, arguments)
    turn = await service.post_message_for_user(
        session_id,
        _USER_ID,
        message=user_message,
    )
    assert turn["status"] == "approval_required"
    pending = turn["pending_approval"]
    assert isinstance(pending, ChatToolCall)
    assert pending.name == name
    assert pending.status is ToolCallStatus.APPROVAL_REQUIRED
    return pending


async def _approve_write(
    service: ChatSessionService,
    *,
    session_id: str,
    pending: ChatToolCall,
) -> ChatToolResult:
    turn = await service.decide_tool_call_for_user(
        session_id,
        pending.tool_call_id,
        _USER_ID,
        arguments_digest=pending.arguments_digest,
        decision="approved",
    )
    assert turn["status"] == "completed"
    result = _tool_result(turn)
    assert result.status.value == "succeeded", result.to_record()
    return result


async def _approve_write_failure(
    service: ChatSessionService,
    *,
    session_id: str,
    pending: ChatToolCall,
) -> ChatToolResult:
    turn = await service.decide_tool_call_for_user(
        session_id,
        pending.tool_call_id,
        _USER_ID,
        arguments_digest=pending.arguments_digest,
        decision="approved",
    )
    assert turn["status"] == "completed"
    result = _tool_result(turn)
    assert result.status.value == "failed", result.to_record()
    return result


def _p002_plan_arguments(
    *,
    objective_id: str,
    finding_id: str,
    result_evidence_id: str,
    context_evidence_id: str,
) -> dict[str, Any]:
    return {
        "objective_id": objective_id,
        "title": "Test intermediate preheating temperatures for elongation",
        "hypothesis": (
            "Build-platform preheating increases elongation across the untested "
            "temperature range under otherwise fixed LPBF conditions."
        ),
        "variables": [
            {
                "name": "build-platform preheating temperature",
                "role": "independent",
                "planned_values": ["room temperature", "75 C", "150 C"],
                "basis": "literature_derived",
                "basis_evidence_ids": [result_evidence_id],
            },
            {
                "name": "elongation",
                "role": "response",
                "planned_values": ["measured percentage"],
                "basis": "literature_derived",
                "basis_evidence_ids": [result_evidence_id],
            },
        ],
        "controls": ["Use the non-preheated condition as the control."],
        "fixed_conditions": [
            "Hold alloy feedstock, specimen geometry, and LPBF parameters fixed."
        ],
        "measurements": ["Measure tensile elongation to failure."],
        "replication": "Use at least three independently built specimens per condition.",
        "analysis_method": (
            "Estimate the temperature-response trend with uncertainty intervals and "
            "compare every condition with the non-preheated control."
        ),
        "acceptance_criteria": [
            "The estimated direction is reproducible and uncertainty is reported."
        ],
        "feasibility_checks": [
            "Confirm stable and calibrated build-platform temperature control."
        ],
        "safety_considerations": [
            "Follow metal-powder handling and heated-platform safety procedures."
        ],
        "limitations": [
            "The literature basis contains one directly comparable experiment."
        ],
        "finding_ids": [finding_id],
        "evidence_ids": [result_evidence_id, context_evidence_id],
    }


async def test_deep_path_round_trips_one_source_grounded_research_cycle(
    source_repository: PostgresSourceArtifactRepository,
    tmp_path: Path,
) -> None:
    """Model one real review from question formation to a follow-up plan.

    P002 supplies a controlled build-platform comparison and exact elongation
    values. A second paper is inspected but cannot answer the target outcome.
    The researcher approves every durable Agent write, then a fresh repository
    process reloads the immutable scientific lineage.
    """

    collection_repository = PostgresCollectionRepository(
        source_repository.session_factory
    )
    collection_service = CollectionService(
        collection_repository,
        FileCollectionWorkspace(tmp_path / "collections"),
    )
    objective_repository = PostgresObjectiveRepository(
        source_repository.session_factory
    )
    chat_repository = PostgresChatRepository(source_repository.session_factory)
    finding_review_repository = PostgresFindingReviewRepository(
        source_repository.session_factory
    )
    experiment_plan_repository = PostgresExperimentPlanRepository(
        source_repository.session_factory
    )

    p002 = _p002_source()
    no_result = _no_result_source()
    await source_repository.replace_document(COLLECTION_ID, p002)
    await source_repository.replace_document(COLLECTION_ID, no_result)
    for position, document_id in enumerate(("doc_a", "doc_b"), start=1):
        await collection_service.update_document_preparation(
            COLLECTION_ID,
            document_id,
            status="ready",
            preparation_fingerprint=f"prepared-deep-path-{position}",
            source_fingerprint=f"source-deep-path-{position}",
            profile_fingerprint=f"profile-deep-path-{position}",
            parser_version="source-runtime.test",
            document_analysis_version="document-profile.test",
        )

    evidence_analysis_service = ObjectiveEvidenceAnalysisService(
        collection_service=collection_service,
        paper_map_repository=SimpleNamespace(),
        objective_repository=objective_repository,
        finding_synthesis_service=SimpleNamespace(),
        objective_input_service=SimpleNamespace(),
    )
    objective_authoring_service = ObjectiveAuthoringService(
        collection_service=collection_service,
        objective_repository=objective_repository,
    )
    objective_analysis_service = ObjectiveAnalysisService(
        objective_repository=objective_repository,
        evidence_analysis_service=evidence_analysis_service,
        objective_input_service=SimpleNamespace(),
        document_profile_service=SimpleNamespace(),
    )
    finding_feedback_service = FindingFeedbackService(
        review_repository=finding_review_repository,
        objective_repository=objective_repository,
    )
    experiment_plan_service = ExperimentPlanService(
        experiment_plan_repository,
        finding_feedback_service,
    )
    model = _QueuedModel()
    capabilities = CapabilityRegistry(
        (
            CreateObjectiveCandidateCapability(
                objective_authoring_service=objective_authoring_service
            ),
            ConfirmObjectiveCapability(
                objective_authoring_service=objective_authoring_service
            ),
            InspectDocumentSourcesCapability(
                collection_service=collection_service,
                source_artifact_repository=source_repository,
            ),
            PublishAgentObjectiveAnalysisCapability(
                agent_analysis_service=AgentObjectiveAnalysisService(
                    collection_service=collection_service,
                    objective_repository=objective_repository,
                    source_artifact_repository=source_repository,
                ),
                model_name="deterministic-deep-path-test",
                prompt_version="research-agent.deep-path-e2e.v1",
            ),
            CreateFindingVersionCapability(
                finding_authoring_service=FindingAuthoringService(
                    collection_service=collection_service,
                    objective_repository=objective_repository,
                )
            ),
            AssessObjectiveQualityCapability(
                collection_service=collection_service,
                objective_analysis_service=objective_analysis_service,
            ),
            RecordFindingFeedbackCapability(
                collection_service=collection_service,
                finding_feedback_service=finding_feedback_service,
            ),
            DeriveObjectiveCapability(
                collection_service=collection_service,
                objective_analysis_service=objective_analysis_service,
            ),
            ProposeResearchPlanCapability(
                collection_service=collection_service,
                finding_feedback_service=finding_feedback_service,
            ),
            CreateResearchPlanCapability(
                collection_service=collection_service,
                finding_feedback_service=finding_feedback_service,
                experiment_plan_service=experiment_plan_service,
            ),
        )
    )
    chat_service = ChatSessionService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        repository=chat_repository,
        runner=ResearchAgentRunner(model=model, capabilities=capabilities),
    )
    session = await chat_service.create_session(
        collection_id=COLLECTION_ID,
        user_id=_USER_ID,
    )

    candidate_arguments = {
        "question": (
            "How does build-platform preheating affect elongation in 316L "
            "stainless steel?"
        ),
        "material_scope": ["316L stainless steel"],
        "variables": ["build-platform preheating"],
        "outcomes": ["elongation"],
        "mechanisms": [],
        "constraints": ["LPBF"],
        "requested_comparator": "non-preheated versus 150 C preheated",
        "seed_document_ids": ["doc_a"],
        "excluded_document_ids": [],
    }
    pending_candidate = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="create_objective_candidate",
        arguments=candidate_arguments,
        user_message="Save this focused research question as a candidate.",
    )
    assert await objective_repository.list_objectives(COLLECTION_ID) == ()
    candidate_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_candidate,
    )
    objective_id = str(candidate_result.data["objective_id"])
    candidate = await objective_repository.read_objective(COLLECTION_ID, objective_id)
    assert candidate is not None
    assert candidate.confirmation_status == "candidate"
    assert candidate.active_analysis_version is None
    assert candidate.created_by_tool_call_id == pending_candidate.tool_call_id

    pending_confirmation = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="confirm_objective",
        arguments={"objective_id": objective_id},
        user_message="Confirm the reviewed question without starting analysis.",
    )
    assert (
        await objective_repository.read_objective(COLLECTION_ID, objective_id)
    ).confirmation_status == "candidate"
    confirmation_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_confirmation,
    )
    assert confirmation_result.data == {
        "objective_id": objective_id,
        "confirmation_status": "confirmed",
        "analysis_started": False,
    }

    methods_result = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="inspect_document_sources",
        arguments={
            "document_id": "doc_a",
            "source_ref": p002.blocks[0].block_id,
        },
        user_message="Inspect the P002 group definitions.",
    )
    result_table = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="inspect_document_sources",
        arguments={
            "document_id": "doc_a",
            "source_ref": p002.tables[0].table_id,
        },
        user_message="Inspect the complete P002 tensile table.",
    )
    no_result_inspection = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="inspect_document_sources",
        arguments={
            "document_id": "doc_b",
            "source_ref": no_result.blocks[0].block_id,
        },
        user_message="Check whether the review paper reports the target outcome.",
    )
    methods_source = methods_result.data["sources"][0]
    table_source = result_table.data["sources"][0]
    no_result_source = no_result_inspection.data["sources"][0]
    assert methods_source["content_truncated"] is False
    assert table_source["content_truncated"] is False
    assert "Non-preheated" in table_source["content"]
    assert "Preheated" in table_source["content"]
    assert "no mechanical-property measurements" in no_result_source["content"]
    assert all(
        result.data["support_is_evidence"] is False
        for result in (methods_result, result_table, no_result_inspection)
    )

    analysis_arguments = {
        "objective_id": objective_id,
        "document_ids": ["doc_a", "doc_b"],
        "paper_summaries": [
            {
                "document_id": "doc_a",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "contribution_summary": (
                    "P002 defines the preheating groups and reports their elongation."
                ),
                "confidence": 0.98,
                "inspection_outcome": "evidence_recorded",
            },
            {
                "document_id": "doc_b",
                "relevance": "medium",
                "paper_role": "review",
                "contribution_summary": (
                    "The review provides process context but no elongation result."
                ),
                "confidence": 0.92,
                "inspection_outcome": "no_grounded_evidence",
                "inspection_outcome_reason": (
                    "The inspected Source contains no mechanical-property measurement."
                ),
                "inspected_source_refs": [
                    {
                        "source_kind": no_result_source["source_kind"],
                        "source_ref": no_result_source["source_ref"],
                        "source_digest": no_result_source["source_digest"],
                    }
                ],
            },
        ],
        "evidence_drafts": [
            {
                "draft_id": "draft-p002-group-definitions",
                "document_id": "doc_a",
                "source_kind": methods_source["source_kind"],
                "source_ref": methods_source["source_ref"],
                "source_excerpt": methods_source["content"],
                "source_digest": methods_source["source_digest"],
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "material": [],
                    "sample": [],
                    "process": [
                        {"name": "group", "value": "NP"},
                        {"name": "group", "value": "P150"},
                        {"name": "preheating", "value": 150, "unit": "°C"},
                    ],
                    "test": [],
                },
                "confidence": 0.98,
                "authoring_note": "Defines NP and P150 in the same paper.",
            },
            {
                "draft_id": "draft-p002-elongation-result",
                "document_id": "doc_a",
                "source_kind": table_source["source_kind"],
                "source_ref": table_source["source_ref"],
                "source_excerpt": table_source["content"],
                "source_digest": table_source["source_digest"],
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "Build platform conditions",
                        "baseline_value": "Non-preheated",
                        "target_value": "Preheated",
                    }
                ],
                "comparison": {
                    "baseline_label": "Non-preheated",
                    "target_label": "Preheated",
                    "axis_names": ["Build platform conditions"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "elongation",
                    "value": 82,
                    "baseline_value": 72,
                    "target_value": 82,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Non-preheated: 72%; Preheated: 82%.",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {
                    "material": [],
                    "sample": [],
                    "process": [],
                    "test": [],
                },
                "confidence": 0.96,
                "authoring_note": "Transcribed from the complete P002 tensile table.",
            },
        ],
    }
    pending_analysis = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="publish_agent_objective_analysis",
        arguments=analysis_arguments,
        user_message="Publish this reviewed source-grounded analysis.",
    )
    assert await objective_repository.read_analysis(
        COLLECTION_ID, objective_id, 1
    ) is None
    analysis_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_analysis,
    )
    assert analysis_result.data["analysis"]["analysis_version"] == 1
    assert analysis_result.data["analysis"]["origin"] == "agent_authored"
    assert analysis_result.data["finding_count"] == 0
    evidence = analysis_result.data["evidence"]
    result_evidence = next(
        item for item in evidence if item["evidence_role"] == "direct_result"
    )
    context_evidence = next(
        item for item in evidence if item["evidence_role"] == "condition_context"
    )
    assert result_evidence["reported_result"]["baseline_value"] == 72
    assert result_evidence["reported_result"]["target_value"] == 82

    version_one_evidence, version_one_total = await objective_repository.list_evidence(
        COLLECTION_ID,
        objective_id,
        1,
    )
    assert version_one_total == 2
    version_one_contributions = await objective_repository.list_contributions(
        COLLECTION_ID,
        objective_id,
        1,
    )
    no_evidence_contribution = next(
        item for item in version_one_contributions if item.document_id == "doc_b"
    )
    assert no_evidence_contribution.evidence_disposition == "no_grounded_evidence"
    assert no_evidence_contribution.inspected_source_refs[0].source_ref == (
        no_result_source["source_ref"]
    )
    assert no_evidence_contribution.inspected_source_refs[0].source_digest == (
        no_result_source["source_digest"]
    )

    finding_arguments = {
        "objective_id": objective_id,
        "source_analysis_version": 1,
        "statement": (
            "In P002, build-platform preheating to 150 C increased elongation "
            "from 72% to 82% relative to the non-preheated condition."
        ),
        "assertion_strength": "descriptive",
        "supporting_evidence_ids": [result_evidence["evidence_id"]],
        "contradicting_evidence_ids": [],
        "context_evidence_ids": [context_evidence["evidence_id"]],
        "condition_boundary_evidence_ids": [context_evidence["evidence_id"]],
        "limitations": [
            "The quantitative comparison comes from one paper and two conditions."
        ],
        "parent_finding_id": None,
        "abstention_reason": None,
    }
    pending_finding = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="create_finding_version",
        arguments=finding_arguments,
        user_message="Publish this conservative conclusion from the reviewed evidence.",
    )
    assert await objective_repository.list_findings(
        COLLECTION_ID,
        objective_id,
        1,
    ) == ((), 0)
    finding_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_finding,
    )
    assert finding_result.data["analysis"]["analysis_version"] == 2
    assert finding_result.data["analysis"]["source_analysis_version"] == 1
    finding = finding_result.data["finding"]
    finding_id = str(finding["finding_id"])
    assert finding["origin"] == "agent_authored"
    assert finding["source_analysis_version"] == 1
    assert finding["created_by_tool_call_id"] == pending_finding.tool_call_id
    plan_arguments = _p002_plan_arguments(
        objective_id=objective_id,
        finding_id=finding_id,
        result_evidence_id=result_evidence["evidence_id"],
        context_evidence_id=context_evidence["evidence_id"],
    )

    quality = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="assess_objective_quality",
        arguments={"objective_id": objective_id},
        user_message="Assess the published conclusion and remaining gaps.",
    )
    assert quality.data["published_analysis_version"] == 2
    assert quality.data["quality_status"] == "finding_available_with_gaps"
    assert quality.data["finding_count"] == 1
    assert quality.data["total_evidence_count"] == 2
    assert quality.data["comparable_evidence_count"] == 1
    assert quality.data["technical_failure_count"] == 0
    assert quality.data["scientific_gap_count"] == 1
    assert {
        item["document_id"]: item["evidence_disposition"]
        for item in quality.data["paper_contributions"]
    } == {"doc_a": "coverage_incomplete", "doc_b": "no_grounded_evidence"}

    unreviewed_plan_draft = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="propose_research_plan",
        arguments=plan_arguments,
        user_message="Draft the follow-up experiment before I review the Finding.",
    )
    assert unreviewed_plan_draft.data["draft_status"] == "needs_finding_review"
    assert unreviewed_plan_draft.data["unreviewed_finding_ids"] == [finding_id]
    pending_unreviewed_plan = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="create_research_plan",
        arguments={
            **plan_arguments,
            "source_snapshots": unreviewed_plan_draft.data["source_snapshots"],
        },
        user_message="Save this plan before reviewing its Finding.",
    )
    unreviewed_plan_result = await _approve_write_failure(
        chat_service,
        session_id=session.session_id,
        pending=pending_unreviewed_plan,
    )
    assert unreviewed_plan_result.error_code == "research_plan_source_stale"
    assert unreviewed_plan_result.data["source_snapshots_current"] is False
    assert await experiment_plan_repository.list_plans(
        COLLECTION_ID, objective_id
    ) == ()

    pending_review = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="record_finding_feedback",
        arguments={
            "objective_id": objective_id,
            "analysis_version": 2,
            "finding_id": finding_id,
            "review_status": "correct",
            "issue_type": "none",
            "note": (
                "The statement preserves the P002 conditions, values, unit, and "
                "single-paper limitation."
            ),
        },
        user_message="Record my review that this Finding is source-faithful.",
    )
    assert await finding_feedback_service.list_feedback(
        collection_id=COLLECTION_ID,
        objective_id=objective_id,
        analysis_version=2,
        finding_id=finding_id,
    ) == ()
    review_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_review,
    )
    assert review_result.data["review_status"] == "correct"
    assert review_result.data["reviewer"] == _USER_ID

    derived = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="derive_objective",
        arguments={
            "objective_id": objective_id,
            "drafts": [
                {
                    "question": (
                        "How does intermediate build-platform preheating "
                        "temperature affect elongation in LPBF 316L?"
                    ),
                    "material_scope": ["316L stainless steel"],
                    "variables": ["build-platform preheating temperature"],
                    "outcomes": ["elongation"],
                    "mechanisms": [],
                    "constraints": ["LPBF", "between room temperature and 150 C"],
                    "requested_comparator": "multiple intermediate temperatures",
                    "derivation_basis": [
                        {
                            "kind": "finding",
                            "reference_id": finding_id,
                            "rationale": (
                                "The two-condition result leaves the response between "
                                "room temperature and 150 C unresolved."
                            ),
                        }
                    ],
                }
            ],
        },
        user_message="Derive the next narrow research question from this gap.",
    )
    assert derived.data["derivation_status"] == "proposed"
    assert derived.data["published_analysis_version"] == 2
    derived_draft = derived.data["drafts"][0]

    derived_candidate_arguments = {
        key: derived_draft[key]
        for key in (
            "question",
            "material_scope",
            "variables",
            "outcomes",
            "mechanisms",
            "constraints",
            "requested_comparator",
            "parent_objective_id",
            "parent_analysis_version",
            "derivation_basis",
        )
    }
    derived_candidate_arguments.update(
        {"seed_document_ids": ["doc_a"], "excluded_document_ids": []}
    )
    pending_derived_candidate = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="create_objective_candidate",
        arguments=derived_candidate_arguments,
        user_message="Save this reviewed follow-up question as a candidate.",
    )
    derived_candidate_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_derived_candidate,
    )
    derived_objective_id = str(derived_candidate_result.data["objective_id"])

    plan_draft = await _run_tool(
        chat_service,
        model,
        session_id=session.session_id,
        name="propose_research_plan",
        arguments=plan_arguments,
        user_message="Draft a follow-up experiment that tests the unresolved range.",
    )
    assert plan_draft.data["persistence"] == "transient_chat_result"
    assert plan_draft.data["draft_status"] == "ready_for_researcher_review"
    assert plan_draft.data["unreviewed_finding_ids"] == []
    assert await experiment_plan_repository.list_plans(
        COLLECTION_ID, objective_id
    ) == ()

    pending_plan = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="create_research_plan",
        arguments={
            **plan_arguments,
            "source_snapshots": plan_draft.data["source_snapshots"],
        },
        user_message="Save the reviewed plan draft with its current source snapshots.",
    )
    plan_result = await _approve_write(
        chat_service,
        session_id=session.session_id,
        pending=pending_plan,
    )
    plan_id = str(plan_result.data["plan"]["plan_id"])
    assert plan_result.data["source_snapshots_current"] is True

    fresh_objectives = PostgresObjectiveRepository(source_repository.session_factory)
    fresh_plans = PostgresExperimentPlanRepository(source_repository.session_factory)
    fresh_chat = PostgresChatRepository(source_repository.session_factory)
    restored_parent = await fresh_objectives.read_objective(
        COLLECTION_ID, objective_id
    )
    restored_derived = await fresh_objectives.read_objective(
        COLLECTION_ID, derived_objective_id
    )
    restored_plan = await fresh_plans.read_plan(
        COLLECTION_ID, objective_id, plan_id
    )
    assert restored_parent is not None
    assert restored_parent.published_analysis_version == 2
    assert restored_derived is not None
    assert restored_derived.confirmation_status == "candidate"
    assert restored_derived.parent_objective_id == objective_id
    assert restored_derived.parent_analysis_version == 2
    assert restored_derived.derivation_basis[0]["reference_id"] == finding_id
    assert restored_derived.derivation_basis[0]["snapshot"] == {
        "statement": finding["statement"]
    }
    assert restored_plan is not None
    assert restored_plan.status == "draft"
    assert restored_plan.created_by == _USER_ID
    assert restored_plan.metadata["created_by_tool_call_id"] == (
        pending_plan.tool_call_id
    )
    assert restored_plan.metadata["source_findings"] == (
        plan_draft.data["source_snapshots"]
    )
    assert len(restored_plan.source_links) == 2

    restored_version_one = await fresh_objectives.read_analysis(
        COLLECTION_ID, objective_id, 1
    )
    restored_version_two = await fresh_objectives.read_analysis(
        COLLECTION_ID, objective_id, 2
    )
    restored_version_one_evidence, restored_total = (
        await fresh_objectives.list_evidence(COLLECTION_ID, objective_id, 1)
    )
    restored_version_one_findings, finding_total = (
        await fresh_objectives.list_findings(COLLECTION_ID, objective_id, 1)
    )
    restored_finding = await fresh_objectives.read_finding(
        COLLECTION_ID,
        objective_id,
        2,
        finding_id,
    )
    assert restored_version_one is not None
    assert restored_version_one.origin == "agent_authored"
    assert restored_version_one.created_by_tool_call_id == pending_analysis.tool_call_id
    assert restored_version_two is not None
    assert restored_version_two.source_analysis_version == 1
    assert restored_version_two.created_by_tool_call_id == pending_finding.tool_call_id
    assert restored_total == version_one_total
    assert restored_version_one_evidence == version_one_evidence
    assert restored_version_one_findings == ()
    assert finding_total == 0
    assert restored_finding is not None
    assert restored_finding.source_analysis_version == 1
    assert restored_finding.created_by_tool_call_id == pending_finding.tool_call_id

    pending_stale_plan = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="create_research_plan",
        arguments={
            **plan_arguments,
            "title": "Stale copy of the intermediate-temperature plan",
            "source_snapshots": plan_draft.data["source_snapshots"],
        },
        user_message="Save another copy of the reviewed plan.",
    )
    fresh_feedback = FindingFeedbackService(
        review_repository=PostgresFindingReviewRepository(
            source_repository.session_factory
        ),
        objective_repository=fresh_objectives,
    )
    curated_finding = restored_finding.to_record()
    curated_finding["statement"] = (
        f"{restored_finding.statement} This interpretation is limited to the "
        "reported LPBF specimen and tensile-test context."
    )
    await fresh_feedback.record_curation(
        collection_id=COLLECTION_ID,
        objective_id=objective_id,
        analysis_version=2,
        finding_id=finding_id,
        curated_status="limited",
        curated_finding=curated_finding,
        note="Clarify the experimental boundary before planning.",
        reviewer=_USER_ID,
    )
    stale_plan_result = await _approve_write_failure(
        chat_service,
        session_id=session.session_id,
        pending=pending_stale_plan,
    )
    assert stale_plan_result.error_code == "research_plan_source_stale"
    assert stale_plan_result.data["approved_source_snapshots"] == (
        plan_draft.data["source_snapshots"]
    )
    assert stale_plan_result.data["current_source_snapshots"] != (
        plan_draft.data["source_snapshots"]
    )
    assert (
        stale_plan_result.data["current_source_snapshots"][0]["finding_fingerprint"]
        != plan_draft.data["source_snapshots"][0]["finding_fingerprint"]
    )
    assert await fresh_plans.list_plans(COLLECTION_ID, objective_id) == (
        restored_plan,
    )

    pending_stale_analysis = await _request_write(
        chat_service,
        model,
        session_id=session.session_id,
        name="publish_agent_objective_analysis",
        arguments=analysis_arguments,
        user_message="Publish a new analysis from the previously inspected Sources.",
    )
    changed_table = replace(
        p002.tables[0],
        table_matrix=(
            p002.tables[0].table_matrix[0],
            ("Preheated", "465", "618", "83"),
        ),
    )
    await source_repository.replace_document(
        COLLECTION_ID,
        replace(p002, tables=(changed_table,)),
    )
    await collection_service.update_document_preparation(
        COLLECTION_ID,
        "doc_a",
        status="ready",
        preparation_fingerprint="prepared-deep-path-reparsed",
        source_fingerprint="source-deep-path-reparsed",
        profile_fingerprint="profile-deep-path-reparsed",
        parser_version="source-runtime.test.v2",
        document_analysis_version="document-profile.test.v2",
    )
    stale_analysis_result = await _approve_write_failure(
        chat_service,
        session_id=session.session_id,
        pending=pending_stale_analysis,
    )
    assert stale_analysis_result.error_code == "capability_execution_failed"
    assert await fresh_objectives.read_analysis(
        COLLECTION_ID,
        objective_id,
        3,
    ) is None
    assert (
        await fresh_objectives.read_objective(COLLECTION_ID, objective_id)
    ).published_analysis_version == 2

    messages = await fresh_chat.read_messages(session.session_id)
    tool_calls = []
    for message in messages:
        for request in message.tool_calls:
            tool_calls.append(await fresh_chat.read_tool_call(request.tool_call_id))
    write_calls = tuple(
        call for call in tool_calls if call is not None and call.risk.value == "write"
    )
    assert [
        call.name for call in write_calls if call.status is ToolCallStatus.SUCCEEDED
    ] == [
        "create_objective_candidate",
        "confirm_objective",
        "publish_agent_objective_analysis",
        "create_finding_version",
        "record_finding_feedback",
        "create_objective_candidate",
        "create_research_plan",
    ]
    assert [
        call.name for call in write_calls if call.status is ToolCallStatus.FAILED
    ] == [
        "create_research_plan",
        "create_research_plan",
        "publish_agent_objective_analysis",
    ]
    assert all(call.decision_user_id == _USER_ID for call in write_calls)
    assert all(
        call.decision_arguments_digest == call.arguments_digest for call in write_calls
    )
    assert model.turns == deque()
