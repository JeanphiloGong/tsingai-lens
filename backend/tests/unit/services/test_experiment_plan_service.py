from __future__ import annotations

import pytest

from application.goal.experiment_plan_service import ExperimentPlanService
from domain.goal import ExperimentPlanRecord
from infra.persistence.sqlite import (
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
)


def _structured_protocol(source_label: str = "Source 1") -> str:
    return (
        f"Hypothesis: 150 C preheating improves ductility [{source_label}].\n"
        "Variable matrix: compare 25 C and 150 C builds.\n"
        "Measurements: elongation and microstructure.\n"
        "Controls: same LPBF parameters except preheating.\n"
        "Risks or limits: single-alloy validation."
    )


def _ved_protocol(*, operational: bool) -> str:
    variable_matrix = (
        "vary laser power to create VED levels while holding scan speed, hatch "
        "spacing, and layer thickness constant"
        if operational
        else "compare low and moderate VED levels"
    )
    controls = (
        "hold scan speed, hatch spacing, and layer thickness constant"
        if operational
        else "hold laser power, scan speed, hatch spacing, and layer thickness constant"
    )
    return (
        "Hypothesis: VED is associated with fatigue strength [Source 1].\n"
        f"Variable matrix: {variable_matrix}.\n"
        "Measurements: fatigue strength and defect size.\n"
        f"Controls: {controls}.\n"
        "Risks or limits: validate the isolated effect before causal interpretation."
    )


def _protocol_source_item(
    *,
    protocol_source_fingerprint: str = "protocol-source.v1:def",
    dataset_use_status: str = "training_ready",
    protocol_status: str = "protocol_ready",
) -> dict:
    return {
        "finding_id": "finding-1",
        "finding_fingerprint": "finding.v1:abc",
        "protocol_source_fingerprint": protocol_source_fingerprint,
        "dataset_use_status": dataset_use_status,
        "protocol_readiness": {"status": protocol_status},
        "training_evidence_refs": [{"evidence_ref_id": "ev_1"}],
    }


class _ResearchUnderstandingFeedbackService:
    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = list(items if items is not None else [_protocol_source_item()])

    def export_dataset(self, **kwargs):  # noqa: ANN003, ANN201
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": kwargs["scope_type"],
            "scope_id": kwargs["scope_id"],
            "items": self.items,
        }


def _write_goal_message(
    repository: SqliteGoalSessionRepository,
    *,
    user_id: str = "expert-a",
    collection_id: str = "col_1",
    goal_id: str = "goal_1",
    message_id: str = "msg_1",
    source_mode: str = "collection_grounded",
    warnings: list[str] | None = None,
    used_evidence_ids: list[str] | None = None,
    content: str = "Run a traceable validation matrix [Source 1].",
    source_href: str = "/collections/col_1/documents/paper-a?evidence_id=ev_1",
    review_gate: str | None = None,
    source_finding_refs: list[dict] | None = None,
) -> None:
    repository.write_session(
        {
            "session_id": "session_1",
            "user_id": user_id,
            "collection_id": collection_id,
            "focused_material_id": None,
            "focused_paper_id": None,
            "focused_objective_id": None,
            "focused_goal_id": goal_id,
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
                "message_id": message_id,
                "session_id": "session_1",
                "role": "assistant",
                "content": content,
                "answer": content,
                "source_mode": source_mode,
                "used_evidence_ids": used_evidence_ids or ["ev_1"],
                "warnings": warnings or [],
                "links": {},
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": source_href,
                    }
                ],
                "review_gate": review_gate,
                "source_finding_refs": source_finding_refs
                or [
                    {
                        "finding_id": "finding-1",
                        "finding_fingerprint": "finding.v1:abc",
                        "protocol_source_fingerprint": "protocol-source.v1:def",
                        "evidence_ref_ids": used_evidence_ids or ["ev_1"],
                    }
                ],
                "created_at": "2026-07-13T00:01:00+00:00",
            }
        ],
    )


def test_experiment_plan_service_saves_and_lists_goal_scoped_drafts(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="protocol_ready_findings",
        content=_structured_protocol(),
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )

    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Preheating validation matrix",
        content=_structured_protocol(),
        source_message_id="msg_1",
        created_by="expert-a",
        source_links=[
            {
                "kind": "evidence",
                "label": "Stale client label",
                "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
            }
        ],
        metadata={"source": "client-supplied", "model": "fake-model"},
    )
    plans = service.list_plans("col_1", "goal_1")

    assert draft.plan_id.startswith("exp_")
    assert draft.status == "draft"
    assert draft.collection_id == "col_1"
    assert draft.goal_id == "goal_1"
    assert draft.title == "Preheating validation matrix"
    assert draft.source_message_id == "msg_1"
    assert draft.created_by == "expert-a"
    assert draft.source_links[0]["label"] == "Source 1"
    assert draft.metadata["model"] == "fake-model"
    assert draft.metadata["source"] == "goal_copilot"
    assert draft.metadata["source_session_id"] == "session_1"
    assert draft.metadata["source_mode"] == "collection_grounded"
    assert draft.metadata["used_evidence_ids"] == ["ev_1"]
    assert draft.metadata["review_gate"] == "protocol_ready_findings"
    assert draft.metadata["source_findings"] == [
        {
            "finding_id": "finding-1",
            "finding_fingerprint": "finding.v1:abc",
            "protocol_source_fingerprint": "protocol-source.v1:def",
            "evidence_ref_ids": ["ev_1"],
        }
    ]
    assert draft.metadata["source_validity"] == "current"
    assert draft.metadata["source_validity_reasons"] == []
    assert [plan.plan_id for plan in plans] == [draft.plan_id]


def test_experiment_plan_service_marks_changed_sources_stale_and_blocks_review(
    tmp_path,
):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="protocol_ready_findings",
        content=_structured_protocol(),
    )
    feedback_service = _ResearchUnderstandingFeedbackService()
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=feedback_service,
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Preheating validation matrix",
        content=_structured_protocol(),
        source_message_id="msg_1",
        created_by="expert-a",
    )

    feedback_service.items = [
        _protocol_source_item(
            protocol_source_fingerprint="protocol-source.v1:changed"
        )
    ]
    stale = service.list_plans("col_1", "goal_1")[0]

    assert stale.plan_id == draft.plan_id
    assert stale.metadata["source_validity"] == "stale"
    assert stale.metadata["source_validity_reasons"] == ["source_finding_changed"]
    feedback_service.items = [
        _protocol_source_item(
            dataset_use_status="review_candidate",
            protocol_status="ready_after_review",
        )
    ]
    no_longer_ready = service.list_plans("col_1", "goal_1")[0]
    assert no_longer_ready.metadata["source_validity"] == "stale"
    assert no_longer_ready.metadata["source_validity_reasons"] == [
        "source_finding_no_longer_protocol_ready"
    ]
    with pytest.raises(ValueError, match="source Findings are stale or unverified"):
        service.update_plan(
            collection_id="col_1",
            goal_id="goal_1",
            plan_id=draft.plan_id,
            title=draft.title,
            content=draft.content,
            status="ready_for_review",
        )


def test_experiment_plan_service_marks_existing_inconsistent_ved_plan_stale(
    tmp_path,
):
    repository = SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    existing = repository.upsert_plan(
        ExperimentPlanRecord.from_mapping(
            {
                "plan_id": "exp_inconsistent_ved",
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "title": "Existing VED protocol",
                "content": _ved_protocol(operational=False),
                "status": "draft",
                "source_message_id": "msg_existing",
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": (
                            "/collections/col_1/documents/"
                            "paper-a?evidence_id=ev_1"
                        ),
                    }
                ],
                "metadata": {
                    "source": "goal_copilot",
                    "review_gate": "protocol_ready_findings",
                    "used_evidence_ids": ["ev_1"],
                    "source_findings": [
                        {
                            "finding_id": "finding-1",
                            "finding_fingerprint": "finding.v1:abc",
                            "protocol_source_fingerprint": "protocol-source.v1:def",
                            "evidence_ref_ids": ["ev_1"],
                        }
                    ],
                },
                "created_by": "expert-a",
                "created_at": "2026-07-01T00:00:00+00:00",
                "updated_at": "2026-07-01T00:00:00+00:00",
            }
        )
    )
    service = ExperimentPlanService(
        repository=repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )

    listed = service.list_plans("col_1", "goal_1")[0]

    assert listed.plan_id == existing.plan_id
    assert listed.metadata["source_validity"] == "stale"
    assert listed.metadata["source_validity_reasons"] == [
        "protocol_design_inconsistent"
    ]


def test_experiment_plan_service_marks_legacy_source_without_snapshot_unverified(
    tmp_path,
):
    repository = SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    legacy = repository.upsert_plan(
        ExperimentPlanRecord.from_mapping(
            {
                "plan_id": "exp_legacy",
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "title": "Legacy protocol",
                "content": _structured_protocol(),
                "status": "draft",
                "source_message_id": "msg_legacy",
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": (
                            "/collections/col_1/documents/"
                            "paper-a?evidence_id=ev_1"
                        ),
                    }
                ],
                "metadata": {
                    "source": "goal_copilot",
                    "review_gate": "protocol_ready_findings",
                    "used_evidence_ids": ["ev_1"],
                },
                "created_by": "expert-a",
                "created_at": "2026-07-01T00:00:00+00:00",
                "updated_at": "2026-07-01T00:00:00+00:00",
            }
        )
    )
    service = ExperimentPlanService(
        repository=repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )

    listed = service.list_plans("col_1", "goal_1")[0]

    assert listed.plan_id == legacy.plan_id
    assert listed.metadata["source_validity"] == "unverified"
    assert listed.metadata["source_validity_reasons"] == [
        "source_finding_snapshot_missing"
    ]


def test_experiment_plan_service_rejects_unstructured_goal_copilot_plan(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        content="Run 25 C and 150 C LPBF 316L builds [Source 1].",
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )

    with pytest.raises(ValueError, match="structured protocol draft"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds [Source 1].",
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_goal_copilot_source_without_review_gate(
    tmp_path,
):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(goal_session_repository)
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="protocol-ready findings"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_training_ready_only_review_gate(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="training_ready_findings",
        content=_structured_protocol(),
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="protocol-ready findings"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_unreviewed_goal_copilot_source(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        warnings=["curated_research_findings_empty"],
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="not eligible"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_invalid_protocol_contract_warning(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        warnings=["goal_copilot_protocol_contract_invalid"],
        review_gate="protocol_ready_findings",
        content=_structured_protocol(),
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="not eligible"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_ved_plan_without_operational_constituent(
    tmp_path,
):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        content=_ved_protocol(operational=False),
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )

    with pytest.raises(ValueError, match="VED design"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="VED validation matrix",
            content=_ved_protocol(operational=False),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_ved_only_isolation_claim(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    content = _ved_protocol(operational=True).replace(
        "validate the isolated effect before causal interpretation",
        "this design isolates the effect of VED from its constituent parameters",
    )
    _write_goal_message(
        goal_session_repository,
        content=content,
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )

    with pytest.raises(ValueError, match="VED design"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="VED isolation matrix",
            content=content,
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_answer_without_source_label(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        content="Run a traceable validation matrix based on the accepted evidence.",
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="does not cite a visible source label"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_plan_content_without_source_label(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        content=_structured_protocol(),
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="does not cite a visible source label"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=(
                "Hypothesis: 150 C preheating improves ductility.\n"
                "Variable matrix: compare 25 C and 150 C builds.\n"
                "Measurements: elongation and microstructure.\n"
                "Controls: same LPBF parameters except preheating.\n"
                "Risks or limits: single-alloy validation."
            ),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_source_link_without_used_evidence(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        used_evidence_ids=["ev_1"],
        source_href="/collections/col_1/documents/paper-a?evidence_id=ev_other",
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="source links do not match evidence citations"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_used_evidence_without_source_link(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        used_evidence_ids=["ev_1", "ev_2"],
        source_href="/collections/col_1/documents/paper-a?evidence_id=ev_1",
        content="Run a traceable validation matrix [Source 1].",
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="missing source links for evidence citations"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content=_structured_protocol(),
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_cross_goal_source_message(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        goal_id="goal_other",
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="not focused on this goal"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds.",
            source_message_id="msg_1",
            created_by="expert-a",
        )


def test_experiment_plan_service_rejects_source_message_without_user(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="authenticated user"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds.",
            source_message_id="msg_1",
        )


def test_experiment_plan_service_allows_manual_draft_without_source_message(tmp_path):
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    )

    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Manual validation plan",
        content="Expert-authored plan without a copilot source.",
        created_by="expert-a",
    )

    assert draft.source_message_id is None
    assert draft.source_links == ()


def test_experiment_plan_service_updates_existing_draft(tmp_path):
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Initial draft",
        content="Initial plan.",
        created_by="expert-a",
    )

    updated = service.update_plan(
        collection_id="col_1",
        goal_id="goal_1",
        plan_id=draft.plan_id,
        title="Edited draft",
        content="Edited plan with controls.",
        status="ready_for_review",
    )

    assert updated.plan_id == draft.plan_id
    assert updated.title == "Edited draft"
    assert updated.content == "Edited plan with controls."
    assert updated.status == "ready_for_review"
    assert updated.updated_at >= draft.updated_at


def test_experiment_plan_service_preserves_copilot_traceability_on_update(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="protocol_ready_findings",
        content=_structured_protocol(),
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Preheating validation matrix",
        content=_structured_protocol(),
        source_message_id="msg_1",
        created_by="expert-a",
        metadata={"source": "goal_copilot"},
    )

    updated = service.update_plan(
        collection_id="col_1",
        goal_id="goal_1",
        plan_id=draft.plan_id,
        title="Edited traceable protocol",
        content=(
            "Hypothesis: 150 C preheating improves ductility [Source 1].\n"
            "Variable matrix: compare 25 C, 100 C, and 150 C builds.\n"
            "Measurements: elongation and microstructure.\n"
            "Controls: same LPBF parameters except preheating.\n"
            "Risks or limits: single-alloy validation."
        ),
        status="ready_for_review",
    )

    assert updated.status == "ready_for_review"
    assert updated.metadata["review_gate"] == "protocol_ready_findings"
    assert updated.source_links[0]["label"] == "Source 1"


def test_experiment_plan_service_rejects_copilot_update_without_source_label(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="protocol_ready_findings",
        content=_structured_protocol(),
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Preheating validation matrix",
        content=_structured_protocol(),
        source_message_id="msg_1",
        created_by="expert-a",
        metadata={"source": "goal_copilot"},
    )

    with pytest.raises(ValueError, match="visible source label"):
        service.update_plan(
            collection_id="col_1",
            goal_id="goal_1",
            plan_id=draft.plan_id,
            title="Edited untraceable protocol",
            content=(
                "Hypothesis: 150 C preheating improves ductility.\n"
                "Variable matrix: compare 25 C and 150 C builds.\n"
                "Measurements: elongation and microstructure.\n"
                "Controls: same LPBF parameters except preheating.\n"
                "Risks or limits: single-alloy validation."
            ),
            status="ready_for_review",
        )


def test_experiment_plan_service_rejects_copilot_update_without_protocol_structure(
    tmp_path,
):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        review_gate="protocol_ready_findings",
        content=_structured_protocol(),
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Preheating validation matrix",
        content=_structured_protocol(),
        source_message_id="msg_1",
        created_by="expert-a",
        metadata={"source": "goal_copilot"},
    )

    with pytest.raises(ValueError, match="structured protocol draft"):
        service.update_plan(
            collection_id="col_1",
            goal_id="goal_1",
            plan_id=draft.plan_id,
            title="Edited unstructured protocol",
            content="Run 25 C and 150 C LPBF builds [Source 1].",
            status="ready_for_review",
        )


def test_experiment_plan_service_rejects_ved_conflict_added_by_plan_edit(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        content=_ved_protocol(operational=True),
        review_gate="protocol_ready_findings",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
        research_understanding_feedback_service=(
            _ResearchUnderstandingFeedbackService()
        ),
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="VED validation matrix",
        content=_ved_protocol(operational=True),
        source_message_id="msg_1",
        created_by="expert-a",
        metadata={"source": "goal_copilot"},
    )

    with pytest.raises(ValueError, match="VED design"):
        service.update_plan(
            collection_id="col_1",
            goal_id="goal_1",
            plan_id=draft.plan_id,
            title="Edited VED validation matrix",
            content=_ved_protocol(operational=False),
            status="ready_for_review",
        )
