from __future__ import annotations

import pytest

from application.goal.experiment_plan_service import (
    ExperimentPlanNotFoundError,
    ExperimentPlanService,
)
from domain.goal import ExperimentPlanRecord
from tests.support.experiment_plan_repository import (
    InMemoryExperimentPlanRepository,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FindingFeedbackService:
    def __init__(self, validity: str = "current") -> None:
        self.validity = validity
        self.validity_calls: list[dict] = []

    async def source_snapshot_validity(self, **kwargs):
        self.validity_calls.append(kwargs)
        reasons = [] if self.validity == "current" else ["finding_changed"]
        return self.validity, reasons


def _service(
    repository: InMemoryExperimentPlanRepository | None = None,
    *,
    validity: str = "current",
) -> ExperimentPlanService:
    return ExperimentPlanService(
        repository=repository or InMemoryExperimentPlanRepository(),
        finding_feedback_service=_FindingFeedbackService(validity),
    )


def _structured_plan(hypothesis: str) -> dict:
    return {
        "hypothesis": hypothesis,
        "variables": [
            {
                "name": "build-plate preheating temperature",
                "role": "independent",
                "planned_values": ["expert-selected levels"],
                "basis": "expert_selection_required",
                "basis_evidence_ids": [],
            },
            {
                "name": "elongation",
                "role": "response",
                "planned_values": ["measured value"],
                "basis": "proposed_for_validation",
                "basis_evidence_ids": [],
            },
        ],
        "controls": ["Include a reference condition."],
        "fixed_conditions": ["Hold alloy state fixed."],
        "measurements": ["Measure elongation and microstructure."],
        "replication": "Use independent builds.",
        "analysis_method": "Estimate the response with uncertainty.",
        "acceptance_criteria": ["Direction repeats across builds."],
        "feasibility_checks": ["Verify thermal stability."],
        "safety_considerations": ["Review hot-surface controls."],
        "limitations": ["Exact levels require expert selection."],
    }


def _historical_plan() -> ExperimentPlanRecord:
    return ExperimentPlanRecord.from_mapping(
        {
            "plan_id": "exp_historical",
            "collection_id": "col_1",
            "objective_id": "objective_1",
            "title": "Historical preheating plan",
            "content": (
                "Hypothesis: preheating improves ductility [Source 1].\n"
                "Variable matrix: compare baseline and preheated builds.\n"
                "Measurements: elongation and microstructure.\n"
                "Controls: keep the alloy and scan setup fixed.\n"
                "Risks or limits: validate the cited material state."
            ),
            "status": "draft",
            "source_message_id": "msg_legacy",
            "source_links": [
                {
                    "kind": "evidence",
                    "label": "Source 1",
                    "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
                }
            ],
            "metadata": {
                "source": "goal_copilot",
                "review_gate": "reviewed_findings",
                "source_findings": [{"finding_id": "finding-1"}],
            },
            "created_by": "expert-a",
            "created_at": "2026-07-13T00:00:00+00:00",
            "updated_at": "2026-07-13T00:00:00+00:00",
        }
    )


async def test_manual_plan_creation_has_no_chat_provenance() -> None:
    repository = InMemoryExperimentPlanRepository()
    service = _service(repository)

    draft = await service.create_plan(
        collection_id="col_1",
        objective_id="objective_1",
        title="Manual validation plan",
        content="Expert-authored plan.",
        structured_plan={
            "hypothesis": "Laser power changes porosity.",
            "variables": [
                {
                    "name": "laser power",
                    "role": "independent",
                    "planned_values": ["expert-selected levels"],
                    "basis": "expert_selection_required",
                    "basis_evidence_ids": [],
                }
            ],
            "controls": ["Use a reference parameter set."],
            "fixed_conditions": ["Hold alloy state fixed."],
            "measurements": ["Measure porosity."],
            "replication": "Use independent builds.",
            "analysis_method": "Estimate the response with uncertainty.",
            "acceptance_criteria": ["Replicates agree within the declared limit."],
            "feasibility_checks": ["Confirm stable laser delivery."],
            "safety_considerations": ["Apply powder-handling controls."],
            "limitations": ["Exact levels require expert selection."],
        },
        created_by="expert-a",
    )

    assert draft.status == "draft"
    assert draft.source_message_id is None
    assert draft.source_links == ()
    assert draft.metadata == {"source": "manual"}
    assert draft.plan_version == 1
    assert draft.parent_plan_id is None
    assert draft.updated_by == "expert-a"
    assert draft.structured_plan is not None
    assert draft.structured_plan["hypothesis"] == "Laser power changes porosity."
    assert await service.list_plans("col_1", "objective_1") == (draft,)


async def test_manual_plan_revision_preserves_history_and_marks_new_leaf_ready() -> None:
    service = _service()
    draft = await service.create_plan(
        collection_id="col_1",
        objective_id="objective_1",
        title="Initial",
        content="Initial plan.",
        created_by="expert-a",
    )

    updated = await service.update_plan(
        collection_id="col_1",
        objective_id="objective_1",
        plan_id=draft.plan_id,
        title="Reviewed",
        content="Reviewed plan with explicit controls.",
        status="ready_for_review",
        structured_plan=_structured_plan("Reviewed hypothesis."),
        updated_by="expert-b",
    )

    assert updated.plan_id != draft.plan_id
    assert updated.title == "Reviewed"
    assert updated.status == "ready_for_review"
    assert updated.source_message_id is None
    assert updated.plan_version == 2
    assert updated.parent_plan_id == draft.plan_id
    assert updated.updated_by == "expert-b"
    assert updated.structured_plan == _structured_plan("Reviewed hypothesis.")
    assert await service.read_plan(
        "col_1", "objective_1", draft.plan_id
    ) == draft
    assert await service.list_plans("col_1", "objective_1") == (updated,)


async def test_agent_plan_persists_current_finding_sources_after_approval() -> None:
    repository = InMemoryExperimentPlanRepository()
    feedback_service = _FindingFeedbackService()
    service = ExperimentPlanService(
        repository=repository,
        finding_feedback_service=feedback_service,
    )
    source_findings = [
        {
            "finding_id": "finding-1",
            "analysis_version": 4,
            "finding_fingerprint": "finding.v2:abc",
            "evidence_fingerprint": "evidence.v2:def",
            "evidence_ids": ["evidence-result", "evidence-method"],
        }
    ]

    plan = await service.create_agent_plan(
        collection_id="col_1",
        objective_id="objective_1",
        title="Preheating validation plan",
        content=(
            "Hypothesis: preheating changes elongation [Evidence 1].\n"
            "Variable matrix: compare baseline and expert-selected levels.\n"
            "Measurements: elongation and microstructure.\n"
            "Controls: hold alloy state and scan strategy fixed.\n"
            "Risks or limits: temperature stability and powder handling."
        ),
        source_links=[
            {
                "kind": "evidence",
                "label": "Evidence 1",
                "href": (
                    "/collections/col_1/documents/paper-1"
                    "?evidence_id=evidence-result"
                ),
            }
        ],
        source_findings=source_findings,
        structured_plan=_structured_plan("Preheating changes elongation."),
        created_by="expert-a",
        created_by_tool_call_id="call-plan-save",
    )

    assert feedback_service.validity_calls == [
        {
            "collection_id": "col_1",
            "objective_id": "objective_1",
            "source_findings": source_findings,
        }
    ]
    assert plan.status == "draft"
    assert plan.source_message_id is None
    assert plan.source_links[0]["label"] == "Evidence 1"
    assert plan.metadata["source"] == "research_agent"
    assert plan.metadata["review_gate"] == "reviewed_findings"
    assert plan.metadata["source_findings"] == source_findings
    assert plan.metadata["created_by_tool_call_id"] == "call-plan-save"
    assert plan.metadata["source_validity"] == "current"
    assert plan.structured_plan == _structured_plan("Preheating changes elongation.")
    assert plan.updated_by == "expert-a"


async def test_agent_plan_is_not_saved_when_finding_sources_are_stale() -> None:
    repository = InMemoryExperimentPlanRepository()
    service = _service(repository, validity="stale")

    with pytest.raises(ValueError, match="research plan sources are stale"):
        await service.create_agent_plan(
            collection_id="col_1",
            objective_id="objective_1",
            title="Stale plan",
            content=(
                "Hypothesis: preheating changes elongation [Evidence 1].\n"
                "Variable matrix: compare conditions.\n"
                "Measurements: elongation.\n"
                "Controls: hold material state fixed.\n"
                "Risks: source result may have changed."
            ),
            source_links=[
                {
                    "kind": "evidence",
                    "label": "Evidence 1",
                    "href": "/documents/paper-1?evidence_id=evidence-result",
                }
            ],
            source_findings=[
                {
                    "finding_id": "finding-1",
                    "analysis_version": 4,
                    "finding_fingerprint": "finding.v2:old",
                    "evidence_fingerprint": "evidence.v2:old",
                    "evidence_ids": ["evidence-result"],
                }
            ],
            structured_plan=_structured_plan("Stale hypothesis."),
            created_by="expert-a",
            created_by_tool_call_id="call-stale-plan",
        )

    assert repository.plans == {}


async def test_agent_revision_uses_the_shared_version_service_and_replaces_basis() -> None:
    repository = InMemoryExperimentPlanRepository()
    service = _service(repository)
    manual = await service.create_plan(
        collection_id="col_1",
        objective_id="objective_1",
        title="Manual starting point",
        content="Expert-authored starting point.",
        structured_plan=_structured_plan("Initial hypothesis."),
        created_by="expert-a",
    )
    source_findings = [
        {
            "finding_id": "finding-1",
            "analysis_version": 4,
            "finding_fingerprint": "finding.v2:abc",
            "evidence_fingerprint": "evidence.v2:def",
            "evidence_ids": ["evidence-result"],
        }
    ]

    revised = await service.update_plan(
        collection_id="col_1",
        objective_id="objective_1",
        plan_id=manual.plan_id,
        title="Agent-assisted revision",
        content=(
            "Hypothesis: preheating changes elongation [Evidence 1].\n"
            "Variable matrix: compare expert-selected levels.\n"
            "Measurements: measure elongation.\n"
            "Controls: include a reference condition.\n"
            "Risks: exact levels require expert review."
        ),
        status="draft",
        structured_plan=_structured_plan("Preheating changes elongation."),
        updated_by="expert-b",
        source_links=[
            {
                "kind": "evidence",
                "label": "Evidence 1",
                "href": "/collections/col_1/documents/paper-1?evidence_id=evidence-result",
            }
        ],
        source_findings=source_findings,
        updated_by_tool_call_id="call-plan-revision",
    )

    assert revised.parent_plan_id == manual.plan_id
    assert revised.plan_version == 2
    assert revised.updated_by == "expert-b"
    assert revised.source_links[0]["label"] == "Evidence 1"
    assert revised.metadata["source"] == "research_agent"
    assert revised.metadata["source_findings"] == source_findings
    assert revised.metadata["updated_by_tool_call_id"] == "call-plan-revision"
    assert await service.read_plan("col_1", "objective_1", manual.plan_id) == manual


async def test_missing_plan_update_is_explicit() -> None:
    with pytest.raises(ExperimentPlanNotFoundError):
        await _service().update_plan(
            collection_id="col_1",
            objective_id="objective_1",
            plan_id="missing",
            title="Missing",
            content="Missing",
            status="draft",
            structured_plan=None,
            updated_by="expert-a",
        )


async def test_historical_grounded_plan_remains_auditable_after_chat_cutover() -> None:
    repository = InMemoryExperimentPlanRepository()
    historical = _historical_plan()
    await repository.upsert_plan(historical)

    listed = await _service(repository).list_plans("col_1", "objective_1")

    assert listed[0].source_message_id == "msg_legacy"
    assert listed[0].source_links == historical.source_links
    assert listed[0].metadata["source_validity"] == "current"
    assert listed[0].metadata["source_validity_reasons"] == []


async def test_stale_historical_plan_cannot_be_promoted() -> None:
    repository = InMemoryExperimentPlanRepository()
    historical = _historical_plan()
    await repository.upsert_plan(historical)

    with pytest.raises(ValueError, match="historical source Findings are stale"):
        await _service(repository, validity="stale").update_plan(
            collection_id="col_1",
            objective_id="objective_1",
            plan_id=historical.plan_id,
            title=historical.title,
            content=historical.content,
            status="ready_for_review",
            structured_plan=None,
            updated_by="expert-a",
        )
