from __future__ import annotations

from agent.capabilities import research_planning

import pytest
from agent.capabilities.research_planning import (
    CreateResearchPlanCapability,
    InspectResearchPlansCapability,
    ProposeResearchPlanCapability,
    ReviseResearchPlanCapability,
)
from agent.tools.registry import ToolExecutionContext
from agent.capabilities.research_planning import (
    ProposeResearchPlanToolRequest,
)
from domain.goal import ExperimentPlanRecord
from exceptions import ResourceConflictException
from pydantic import ValidationError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _WorkspaceService:
    async def get_workspace_for_user(
        self,
        workspace_id: str,
        user_id: str,
    ) -> dict:
        if (workspace_id, user_id) != ("col-1", "user-1"):
            raise FileNotFoundError("workspace not found")
        return {"workspace_id": workspace_id, "owner_user_id": user_id}


class _FindingFeedbackService:
    def __init__(self, *, label_status: str = "gold") -> None:
        self.label_status = label_status
        self.calls: list[tuple[str, str]] = []

    async def export_dataset(
        self,
        *,
        workspace_id: str,
        objective_id: str,
        user_id: str,
    ) -> dict:
        self.calls.append((workspace_id, objective_id))
        return {
            "workspace_id": workspace_id,
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
            "exp-agent-1": ExperimentPlanRecord(
                plan_id="exp-agent-1",
                workspace_id="col-1",
                objective_id="objective-1",
                title="Initial plan",
                content="Initial content",
                status="draft",
                source_message_id=None,
                source_links=(),
                metadata={
                    "source": "research_agent",
                    "source_findings": _source_snapshots(),
                },
                created_by="user-1",
                created_at="2026-09-06T00:00:00+00:00",
                updated_at="2026-09-06T00:00:00+00:00",
                plan_version=1,
                parent_plan_id=None,
                structured_plan=None,
                updated_by="user-1",
            )
        }

    async def create_agent_plan(self, **kwargs):
        self.calls.append(kwargs)
        return ExperimentPlanRecord(
            plan_id="exp-agent-1",
            workspace_id=kwargs["workspace_id"],
            objective_id=kwargs["objective_id"],
            title=kwargs["title"],
            content=kwargs["content"],
            status="draft",
            source_message_id=None,
            source_links=tuple(kwargs["source_links"]),
            metadata={
                "source": "research_agent",
                "source_findings": kwargs["source_findings"],
            },
            created_by=kwargs["created_by"],
            created_at="2026-09-06T00:00:00+00:00",
            updated_at="2026-09-06T00:00:00+00:00",
        )

    async def list_plans(self, workspace_id, objective_id, *, user_id):
        assert (workspace_id, objective_id) == ("col-1", "objective-1")
        return tuple(self.plans.values())

    async def read_plan(self, workspace_id, objective_id, plan_id, *, user_id):
        assert (workspace_id, objective_id) == ("col-1", "objective-1")
        return self.plans[plan_id]

    async def update_plan(self, **kwargs):
        self.calls.append(kwargs)
        return ExperimentPlanRecord(
            plan_id="exp-agent-2",
            workspace_id=kwargs["workspace_id"],
            objective_id=kwargs["objective_id"],
            title=kwargs["title"],
            content=kwargs["content"],
            status="draft",
            source_message_id=None,
            source_links=tuple(kwargs["source_links"]),
            metadata={
                "source": "research_agent",
                "source_findings": kwargs["source_findings"],
            },
            created_by="user-1",
            created_at="2026-09-06T00:00:00+00:00",
            updated_at="2026-09-07T00:00:00+00:00",
            plan_version=2,
            parent_plan_id=kwargs["plan_id"],
            structured_plan=kwargs["structured_plan"],
            updated_by=kwargs["updated_by"],
        )


class _StaleExperimentPlanService(_ExperimentPlanService):
    async def create_agent_plan(self, **kwargs):
        self.calls.append(kwargs)
        raise ResourceConflictException(
            "research plan sources are stale: concurrent update",
            data={"code": "research_plan_sources_stale"},
        )


def _context(call_id: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        operation_id="operation",
        task_id="chat-1",
        user_id="user-1",
        workspace_id="col-1",
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


def test_plan_input_preserves_exact_evidence_identities() -> None:
    arguments = _plan_arguments()
    arguments["evidence_ids"] = ["Evidence-A", "evidence-a", "Evidence-A"]
    arguments["variables"][0]["basis_evidence_ids"] = ["Evidence-A", "evidence-a"]
    arguments["variables"][1]["basis_evidence_ids"] = ["Evidence-A"]
    request = ProposeResearchPlanToolRequest.model_validate(arguments)
    assert request.evidence_ids == ["Evidence-A", "evidence-a"]
    assert request.variables[0].basis_evidence_ids == ["Evidence-A", "evidence-a"]


@pytest.mark.parametrize("field", ["controls", "evidence_ids", "finding_ids"])
def test_plan_input_rejects_blank_entries(field: str) -> None:
    arguments = _plan_arguments()
    arguments[field].append("  ")
    with pytest.raises(ValueError):
        ProposeResearchPlanToolRequest.model_validate(arguments)


def test_plan_variable_rejects_blank_planned_value() -> None:
    arguments = _plan_arguments()
    arguments["variables"][0]["planned_values"].append("  ")
    with pytest.raises(ValueError):
        ProposeResearchPlanToolRequest.model_validate(arguments)


async def test_research_plan_draft_is_structured_traceable_and_transient() -> None:
    feedback_service = _FindingFeedbackService()
    research_planning.workspace_service = _WorkspaceService()
    research_planning.finding_dataset_service = feedback_service
    capability = ProposeResearchPlanCapability()

    result = await capability.execute(
        _context("call-plan-draft"),
        capability.spec.input_model(**_plan_arguments()),
    )

    assert capability.spec.requires_approval is False
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
    research_planning.workspace_service = _WorkspaceService()
    research_planning.finding_dataset_service = _FindingFeedbackService(label_status="unreviewed")
    capability = ProposeResearchPlanCapability()

    result = await capability.execute(
        _context("call-plan-unreviewed"),
        capability.spec.input_model(**_plan_arguments()),
    )

    assert result.data["draft_status"] == "needs_finding_review"
    assert result.data["unreviewed_finding_ids"] == ["finding-1"]
    assert result.warnings


async def test_research_plan_draft_rejects_evidence_outside_selected_findings() -> None:
    research_planning.workspace_service = _WorkspaceService()
    research_planning.finding_dataset_service = _FindingFeedbackService()
    capability = ProposeResearchPlanCapability()
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
    research_planning.workspace_service = _WorkspaceService()
    research_planning.finding_dataset_service = _FindingFeedbackService()
    capability = ProposeResearchPlanCapability()
    payload = _plan_arguments()
    payload["controls"] = ["   "]

    with pytest.raises(ValidationError):
        capability.spec.input_model(**payload)




async def test_research_plan_write_rejects_changed_source_snapshot_without_persistence() -> (
    None
):
    feedback_service = _FindingFeedbackService()
    plan_service = _ExperimentPlanService()
    research_planning.workspace_service = _WorkspaceService()
    research_planning.finding_dataset_service = feedback_service
    research_planning.experiment_plan_service = plan_service
    capability = CreateResearchPlanCapability()
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


async def test_research_plan_write_preserves_stale_error_from_persistence_boundary() -> (
    None
):
    feedback_service = _FindingFeedbackService()
    plan_service = _StaleExperimentPlanService()
    research_planning.workspace_service = _WorkspaceService()
    research_planning.finding_dataset_service = feedback_service
    research_planning.experiment_plan_service = plan_service
    capability = CreateResearchPlanCapability()

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
    research_planning.workspace_service = _WorkspaceService()
    research_planning.experiment_plan_service = plan_service
    capability = InspectResearchPlansCapability()

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
    assert {ref.resource_type for ref in historical.resource_refs} == {"research_plan"}
