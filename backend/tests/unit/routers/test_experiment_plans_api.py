from __future__ import annotations

import asyncio
from types import SimpleNamespace

from application.goal.experiment_plan_service import ExperimentPlanService
from controllers.goal import experiment_plans as experiment_plans_controller
from controllers.schemas.goal.experiment_plan import (
    ExperimentPlanCreateRequest,
    ExperimentPlanUpdateRequest,
)
from tests.support.objective_workspace_repository import (
    InMemoryObjectiveWorkspaceRepository,
)


PROTOCOL_DRAFT = """Hypothesis: 150 C build-platform preheating improves LPBF 316L ductility compared with room-temperature builds [Source 1].

Variable matrix: compare room-temperature and 150 C build-platform settings under the same LPBF material and scan setup.

Measurements: tensile ductility, yield strength, and microstructure indicators after printing.

Controls: include a no-preheat control build and repeat specimens for both temperatures.

Risks and limits: one reviewed finding is not enough to generalize beyond the cited 316L condition."""


def _request(service, user_id: str = "expert-a"):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(experiment_plan_service=service),
        ),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


class _FindingFeedbackService:
    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        return {
            "collection_id": kwargs["collection_id"],
            "objective_id": kwargs["objective_id"],
            "items": [
                {
                    "finding_id": "finding-1",
                    "finding_fingerprint": "finding.v1:abc",
                    "protocol_source_fingerprint": "protocol-source.v1:def",
                    "dataset_use_status": "training_ready",
                    "protocol_readiness": {"status": "protocol_ready"},
                    "training_evidence_refs": [{"evidence_ref_id": "ev_1"}],
                }
            ],
        }


def _write_goal_message(repository: InMemoryObjectiveWorkspaceRepository) -> None:
    repository.write_session(
        {
            "session_id": "session_1",
            "user_id": "expert-a",
            "collection_id": "col_1",
            "focused_material_id": None,
            "focused_paper_id": None,
            "focused_objective_id": "objective_1",
            "goal_text": None,
            "goal_brief_json": {},
            "answer_mode": "hybrid",
            "rolling_summary": "",
            "last_evidence_ids": [],
            "last_material_ids": [],
            "last_paper_ids": [],
            "collection_data_version": None,
            "created_at": "2026-07-13T00:00:00+00:00",
            "updated_at": "2026-07-13T00:00:00+00:00",
        }
    )
    repository.write_messages(
        "session_1",
        [
            {
                "message_id": "msg_1",
                "session_id": "session_1",
                "role": "assistant",
                "content": PROTOCOL_DRAFT,
                "answer": PROTOCOL_DRAFT,
                "source_mode": "collection_grounded",
                "used_evidence_ids": ["ev_1"],
                "warnings": [],
                "links": {},
                "review_gate": "protocol_ready_findings",
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
                    }
                ],
                "source_finding_refs": [
                    {
                        "finding_id": "finding-1",
                        "finding_fingerprint": "finding.v1:abc",
                        "protocol_source_fingerprint": "protocol-source.v1:def",
                        "evidence_ref_ids": ["ev_1"],
                    }
                ],
                "created_at": "2026-07-13T00:01:00+00:00",
            }
        ],
    )


def test_experiment_plan_routes_create_list_and_update():
    goal_session_repository = InMemoryObjectiveWorkspaceRepository()
    _write_goal_message(goal_session_repository)
    service = ExperimentPlanService(
        repository=InMemoryObjectiveWorkspaceRepository(),
        goal_session_repository=goal_session_repository,
        finding_feedback_service=(
            _FindingFeedbackService()
        ),
    )
    request = _request(service)

    created = asyncio.run(
        experiment_plans_controller.create_experiment_plan(
            "col_1",
            "objective_1",
            ExperimentPlanCreateRequest(
                title="Preheating validation matrix",
                content=PROTOCOL_DRAFT,
                source_message_id="msg_1",
                source_links=[
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
                    }
                ],
            ),
            request,
        )
    )
    listed = asyncio.run(
        experiment_plans_controller.list_experiment_plans(
            "col_1", "objective_1", request
        )
    )
    updated = asyncio.run(
        experiment_plans_controller.update_experiment_plan(
            "col_1",
            "objective_1",
            created.plan_id,
            ExperimentPlanUpdateRequest(
                title="Edited validation matrix",
                content=(
                    PROTOCOL_DRAFT
                    + "\n\nMeasurements: add repeat tensile testing and EBSD checks."
                ),
                status="ready_for_review",
            ),
            request,
        )
    )

    assert created.status == "draft"
    assert created.created_by == "expert-a"
    assert created.source_links[0].label == "Source 1"
    assert created.metadata["source_validity"] == "current"
    assert listed.items[0].plan_id == created.plan_id
    assert listed.items[0].metadata["source_validity_reasons"] == []
    assert updated.title == "Edited validation matrix"
    assert updated.status == "ready_for_review"
