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

    async def source_snapshot_validity(self, **_kwargs):
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
        created_by="expert-a",
    )

    assert draft.status == "draft"
    assert draft.source_message_id is None
    assert draft.source_links == ()
    assert draft.metadata == {"source": "manual"}
    assert await service.list_plans("col_1", "objective_1") == (draft,)


async def test_manual_plan_can_be_edited_and_marked_ready() -> None:
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
    )

    assert updated.title == "Reviewed"
    assert updated.status == "ready_for_review"
    assert updated.source_message_id is None


async def test_missing_plan_update_is_explicit() -> None:
    with pytest.raises(ExperimentPlanNotFoundError):
        await _service().update_plan(
            collection_id="col_1",
            objective_id="objective_1",
            plan_id="missing",
            title="Missing",
            content="Missing",
            status="draft",
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
        )
