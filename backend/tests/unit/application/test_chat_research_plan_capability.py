from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.chat import (
    AgentContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
)
from application.chat.capabilities import (
    CreateResearchPlanCapability,
    InspectResearchPlansCapability,
    ProposeResearchPlanCapability,
    ReviseResearchPlanCapability,
)
from application.chat.capabilities.contracts import CapabilityExecutionContext


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _CollectionService:
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        if (collection_id, user_id) != ("col-1", "user-1"):
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id, "owner_user_id": user_id}


class _FindingFeedbackService:
    def __init__(self, *, label_status: str = "gold") -> None:
        self.label_status = label_status
        self.calls: list[tuple[str, str]] = []

    async def export_dataset(
        self,
        *,
        collection_id: str,
        objective_id: str,
    ) -> dict:
        self.calls.append((collection_id, objective_id))
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "items": [
                {
                    "finding_id": "finding-1",
                    "analysis_version": 4,
                    "label_status": self.label_status,
                    "dataset_use_status": (
                        "training_ready"
                        if self.label_status == "gold"
                        else "review_required"
                    ),
                    "finding_fingerprint": "finding.v2:abc",
                    "evidence_fingerprint": "evidence.v2:def",
                    "training_target": {
                        "finding_id": "finding-1",
                        "statement": (
                            "Build-plate preheating changes elongation under the "
                            "reported LPBF conditions."
                        ),
                        "limitations": [
                            "Only two preheating conditions were reported."
                        ],
                    },
                    "evidence": [
                        {
                            "evidence_id": "evidence-result",
                            "document_id": "paper-1",
                            "source_kind": "text_window",
                            "source_ref": "results-7",
                            "source_excerpt": (
                                "P150 showed higher elongation than the NP condition."
                            ),
                            "evidence_status": "comparable",
                        },
                        {
                            "evidence_id": "evidence-method",
                            "document_id": "paper-1",
                            "source_kind": "text_window",
                            "source_ref": "methods-4",
                            "source_excerpt": (
                                "NP denotes no preheating and P150 denotes 150 C."
                            ),
                            "evidence_status": "descriptive",
                        },
                    ],
                }
            ],
        }


class _ExperimentPlanService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.plans = {
            "exp-agent-1": SimpleNamespace(
                plan_id="exp-agent-1",
                status="draft",
                metadata={
                    "source": "research_agent",
                    "source_findings": _source_snapshots(),
                },
                to_record=lambda: {
                    "plan_id": "exp-agent-1",
                    "collection_id": "col-1",
                    "objective_id": "objective-1",
                    "title": "Initial plan",
                    "content": "Initial content",
                    "status": "draft",
                    "source_message_id": None,
                    "source_links": [],
                    "metadata": {
                        "source": "research_agent",
                        "source_findings": _source_snapshots(),
                    },
                    "created_by": "user-1",
                    "created_at": "2026-09-06T00:00:00+00:00",
                    "updated_at": "2026-09-06T00:00:00+00:00",
                    "plan_version": 1,
                    "parent_plan_id": None,
                    "structured_plan": None,
                    "updated_by": "user-1",
                },
            )
        }

    async def create_agent_plan(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            plan_id="exp-agent-1",
            status="draft",
            to_record=lambda: {
                "plan_id": "exp-agent-1",
                "collection_id": kwargs["collection_id"],
                "objective_id": kwargs["objective_id"],
                "title": kwargs["title"],
                "content": kwargs["content"],
                "status": "draft",
                "source_message_id": None,
                "source_links": kwargs["source_links"],
                "metadata": {
                    "source": "research_agent",
                    "source_findings": kwargs["source_findings"],
                },
                "created_by": kwargs["created_by"],
                "created_at": "2026-09-06T00:00:00+00:00",
                "updated_at": "2026-09-06T00:00:00+00:00",
            },
        )

    async def list_plans(self, collection_id, objective_id):
        assert (collection_id, objective_id) == ("col-1", "objective-1")
        return tuple(self.plans.values())

    async def read_plan(self, collection_id, objective_id, plan_id):
        assert (collection_id, objective_id) == ("col-1", "objective-1")
        return self.plans[plan_id]

    async def update_plan(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            plan_id="exp-agent-2",
            status="draft",
            to_record=lambda: {
                "plan_id": "exp-agent-2",
                "collection_id": kwargs["collection_id"],
                "objective_id": kwargs["objective_id"],
                "title": kwargs["title"],
                "content": kwargs["content"],
                "status": "draft",
                "source_message_id": None,
                "source_links": kwargs["source_links"],
                "metadata": {
                    "source": "research_agent",
                    "source_findings": kwargs["source_findings"],
                },
                "created_by": "user-1",
                "created_at": "2026-09-06T00:00:00+00:00",
                "updated_at": "2026-09-07T00:00:00+00:00",
                "plan_version": 2,
                "parent_plan_id": kwargs["plan_id"],
                "structured_plan": kwargs["structured_plan"],
                "updated_by": kwargs["updated_by"],
            },
        )


class _StaleExperimentPlanService(_ExperimentPlanService):
    async def create_agent_plan(self, **kwargs):
        self.calls.append(kwargs)
        raise ValueError("research plan sources are stale: concurrent update")


class _Model:
    def __init__(
        self,
        *turns: ModelTurn,
        expected_tools: set[str] | None = None,
    ) -> None:
        self.turns = deque(turns)
        self.expected_tools = expected_tools or {
            "propose_research_plan",
            "create_research_plan",
        }

    async def respond(self, *, context: tuple, tool_specs: tuple, text_delta_callback=None, timeout_seconds=180.0, max_output_tokens=16_384):
        messages = context.messages
        assert messages
        # Once the final approval write has completed, the runner deliberately
        # gives the model an answer-only turn so it cannot repeat that write.
        expected_tools = self.expected_tools
        next_call = self.turns[0].tool_calls[0] if self.turns and self.turns[0].tool_calls else None
        if next_call is not None and next_call.name == "create_research_plan":
            # After a transient proposal, only the exact approved write remains
            # available for the next model decision.
            expected_tools = {"create_research_plan"}
        if len(self.turns) == 1 and not self.turns[0].tool_calls:
            expected_tools = set()
        assert {item.name for item in tool_specs} == expected_tools
        return self.turns.popleft()


def _context(call_id: str) -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        session_id="chat-1",
        user_id="user-1",
        collection_id="col-1",
        tool_call_id=call_id,
    )


def _plan_arguments() -> dict:
    return {
        "objective_id": "objective-1",
        "title": "Resolve the LPBF preheating response curve",
        "hypothesis": (
            "Build-plate preheating changes elongation through a temperature-dependent "
            "microstructure response."
        ),
        "variables": [
            {
                "name": "build-plate preheating temperature",
                "role": "independent",
                "planned_values": ["expert-selected intermediate levels"],
                "basis": "proposed_for_validation",
                "basis_evidence_ids": ["evidence-result", "evidence-method"],
            },
            {
                "name": "elongation",
                "role": "response",
                "planned_values": ["measured value"],
                "basis": "literature_derived",
                "basis_evidence_ids": ["evidence-result"],
            },
        ],
        "controls": ["Include the reported NP condition as the baseline."],
        "fixed_conditions": ["Keep alloy state and LPBF scan strategy fixed."],
        "measurements": ["Measure elongation and characterize microstructure."],
        "replication": "Use independent builds and report within-condition variation.",
        "analysis_method": (
            "Estimate the response across temperature while preserving uncertainty."
        ),
        "acceptance_criteria": [
            "The response direction is reproducible across independent builds."
        ],
        "feasibility_checks": ["Confirm stable build-plate temperature control."],
        "safety_considerations": ["Review hot-surface and powder-handling controls."],
        "limitations": ["Exact temperature levels require expert selection."],
        "finding_ids": ["finding-1"],
        "evidence_ids": ["evidence-result", "evidence-method"],
    }


def _source_snapshots() -> list[dict]:
    return [
        {
            "finding_id": "finding-1",
            "analysis_version": 4,
            "finding_fingerprint": "finding.v2:abc",
            "evidence_fingerprint": "evidence.v2:def",
            "evidence_ids": ["evidence-result", "evidence-method"],
        }
    ]


async def test_research_plan_draft_is_structured_traceable_and_transient() -> None:
    feedback_service = _FindingFeedbackService()
    capability = ProposeResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
    )

    result = await capability.execute(
        _context("call-plan-draft"),
        capability.spec.input_model(**_plan_arguments()),
    )

    assert capability.spec.risk.value == "draft"
    assert feedback_service.calls == [("col-1", "objective-1")]
    assert result.data["draft_status"] == "ready_for_researcher_review"
    assert result.data["persistence"] == "transient_chat_result"
    assert result.data["support_is_evidence"] is False
    assert result.data["source_analysis_version"] == 4
    assert result.data["source_finding_ids"] == ["finding-1"]
    assert result.data["source_evidence_ids"] == [
        "evidence-result",
        "evidence-method",
    ]
    assert "## Variable matrix" in result.data["content"]
    assert "## Controls" in result.data["content"]
    assert "## Acceptance criteria" in result.data["content"]
    assert "[Evidence 1]" in result.data["content"]
    assert result.data["source_snapshots"] == [
        {
            "finding_id": "finding-1",
            "analysis_version": 4,
            "finding_fingerprint": "finding.v2:abc",
            "evidence_fingerprint": "evidence.v2:def",
            "evidence_ids": ["evidence-result", "evidence-method"],
        }
    ]
    assert {ref.resource_type for ref in result.resource_refs} == {
        "research_plan_draft",
        "finding",
        "evidence",
        "source",
    }


async def test_research_plan_draft_marks_unreviewed_findings_for_review() -> None:
    capability = ProposeResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=_FindingFeedbackService(label_status="unreviewed"),
    )

    result = await capability.execute(
        _context("call-plan-unreviewed"),
        capability.spec.input_model(**_plan_arguments()),
    )

    assert result.data["draft_status"] == "needs_finding_review"
    assert result.data["unreviewed_finding_ids"] == ["finding-1"]
    assert result.warnings


async def test_research_plan_draft_rejects_evidence_outside_selected_findings() -> None:
    capability = ProposeResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=_FindingFeedbackService(),
    )
    payload = _plan_arguments()
    payload["evidence_ids"] = [
        "evidence-result",
        "evidence-method",
        "invented-evidence",
    ]

    result = await capability.execute(
        _context("call-plan-invalid-source"),
        capability.spec.input_model(**payload),
    )

    assert result.data["draft_status"] == "abstained"
    assert result.data["abstention_reason"] == "source_basis_not_current"
    assert result.data["missing_evidence_ids"] == ["invented-evidence"]
    assert "content" not in result.data


def test_research_plan_contract_requires_a_complete_real_experiment() -> None:
    capability = ProposeResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=_FindingFeedbackService(),
    )
    payload = _plan_arguments()
    payload["controls"] = ["   "]

    with pytest.raises(ValidationError):
        capability.spec.input_model(**payload)


async def test_research_plan_write_waits_for_exact_approval_after_draft() -> None:
    feedback_service = _FindingFeedbackService()
    plan_service = _ExperimentPlanService()
    proposal = ProposeResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
    )
    writer = CreateResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
        experiment_plan_service=plan_service,
    )
    plan_arguments = _plan_arguments()
    write_arguments = {
        **plan_arguments,
        "source_snapshots": _source_snapshots(),
    }
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="propose_research_plan",
                    arguments=plan_arguments,
                ),)
            ),
            ModelTurn(
                content="The research plan draft is ready for approval.",
                tool_calls=(ModelToolCall(
                    name="create_research_plan",
                    arguments=write_arguments,
                ),),
            ),
            ModelTurn(content="The approved research plan draft has been saved."),
        ),
        capabilities=CapabilityRegistry((proposal, writer)),
    )
    context = AgentContext("chat-1", "user-1", "col-1")

    proposed = await runner.run_turn(
        context=context,
        previous_messages=(),
        user_message="Draft and save a plan to test this conclusion.",
    )

    assert proposed.status.value == "approval_required"
    assert proposed.tool_results[0].data["persistence"] == "transient_chat_result"
    assert proposed.pending_approval.name == "create_research_plan"
    assert plan_service.calls == []

    approved = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-09-06T08:00:00+00:00",
    )
    completed = await runner.resume_claimed_call(
        context=context,
        previous_messages=proposed.messages,
        claimed_call=approved.start("2026-08-19T00:01:01+00:00"),
    )

    assert completed.status.value == "completed"
    assert completed.tool_results[0].data["plan"]["plan_id"] == "exp-agent-1"
    assert len(plan_service.calls) == 1
    assert plan_service.calls[0]["created_by"] == "user-1"
    assert plan_service.calls[0]["created_by_tool_call_id"] == (
        proposed.pending_approval.tool_call_id
    )
    assert plan_service.calls[0]["structured_plan"] == proposed.tool_results[0].data[
        "structured_plan"
    ]


async def test_research_plan_write_rejects_changed_source_snapshot_without_persistence() -> None:
    feedback_service = _FindingFeedbackService()
    plan_service = _ExperimentPlanService()
    capability = CreateResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
        experiment_plan_service=plan_service,
    )
    stale_snapshots = _source_snapshots()
    stale_snapshots[0]["finding_fingerprint"] = "finding.v2:old"

    result = await capability.execute(
        _context("call-plan-stale"),
        capability.spec.input_model(
            **_plan_arguments(),
            source_snapshots=stale_snapshots,
        ),
    )

    assert result.status.value == "failed"
    assert result.error_code == "research_plan_source_stale"
    assert plan_service.calls == []


async def test_research_plan_write_preserves_stale_error_from_persistence_boundary() -> None:
    feedback_service = _FindingFeedbackService()
    plan_service = _StaleExperimentPlanService()
    capability = CreateResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
        experiment_plan_service=plan_service,
    )

    result = await capability.execute(
        _context("call-plan-race"),
        capability.spec.input_model(
            **_plan_arguments(),
            source_snapshots=_source_snapshots(),
        ),
    )

    assert result.status.value == "failed"
    assert result.error_code == "research_plan_source_stale"
    assert "concurrent update" in result.error_message
    assert result.data["source_snapshots_current"] is False
    assert len(plan_service.calls) == 1


async def test_agent_can_inspect_current_or_named_research_plan_revision() -> None:
    plan_service = _ExperimentPlanService()
    capability = InspectResearchPlansCapability(
        collection_service=_CollectionService(),
        experiment_plan_service=plan_service,
    )

    listed = await capability.execute(
        _context("call-plan-list"),
        capability.spec.input_model(objective_id="objective-1"),
    )
    historical = await capability.execute(
        _context("call-plan-read"),
        capability.spec.input_model(
            objective_id="objective-1",
            plan_id="exp-agent-1",
        ),
    )

    assert listed.data["plans"][0]["plan_id"] == "exp-agent-1"
    assert listed.data["history_scope"] == "current_revisions"
    assert historical.data["plan"]["plan_version"] == 1
    assert historical.data["history_scope"] == "named_revision"
    assert {ref.resource_type for ref in historical.resource_refs} == {
        "research_plan"
    }


async def test_agent_plan_revision_waits_for_approval_then_uses_shared_service() -> None:
    feedback_service = _FindingFeedbackService()
    plan_service = _ExperimentPlanService()
    capability = ReviseResearchPlanCapability(
        collection_service=_CollectionService(),
        finding_feedback_service=feedback_service,
        experiment_plan_service=plan_service,
    )
    arguments = {
        **_plan_arguments(),
        "parent_plan_id": "exp-agent-1",
        "source_snapshots": _source_snapshots(),
    }
    runner = ResearchAgentRunner(
        model=_Model(
            ModelTurn(
                content="The revision is ready for approval.",
                tool_calls=(ModelToolCall(
                    name="revise_research_plan",
                    arguments=arguments,
                ),),
            ),
            ModelTurn(content="The approved revision has been saved."),
            expected_tools={"revise_research_plan"},
        ),
        capabilities=CapabilityRegistry((capability,)),
    )
    context = AgentContext("chat-1", "user-1", "col-1")

    proposed = await runner.run_turn(
        context=context,
        previous_messages=(),
        user_message="Revise the saved plan using the current evidence.",
    )

    assert proposed.status.value == "approval_required"
    assert plan_service.calls == []
    approved = proposed.pending_approval.approve(
        user_id="user-1",
        arguments_digest=proposed.pending_approval.arguments_digest,
        decided_at="2026-09-07T00:00:00+00:00",
    )
    completed = await runner.resume_claimed_call(
        context=context,
        previous_messages=proposed.messages,
        claimed_call=approved.start("2026-09-07T00:00:01+00:00"),
    )

    assert completed.status.value == "completed"
    assert completed.tool_results[0].data["plan"]["plan_version"] == 2
    assert plan_service.calls[0]["plan_id"] == "exp-agent-1"
    assert plan_service.calls[0]["updated_by"] == "user-1"
    assert plan_service.calls[0]["updated_by_tool_call_id"] == (
        proposed.pending_approval.tool_call_id
    )
