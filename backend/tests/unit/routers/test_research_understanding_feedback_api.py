from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from controllers.core import research_understanding_feedback as feedback_controller
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingCurationCreateRequest,
    ResearchUnderstandingFeedbackCreateRequest,
)
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback


def request_with_user(
    *,
    user_id: str = "user-materials-expert",
    email: str = "materials-expert@example.com",
    display_name: str | None = "Materials Expert",
):
    return SimpleNamespace(
        state=SimpleNamespace(
            current_user={
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
            }
        )
    )


class FakeResearchUnderstandingFeedbackService:
    def __init__(self) -> None:
        self.created = None
        self.items = (
            ResearchUnderstandingFeedback.from_mapping(
                {
                    "feedback_id": "ruf-existing",
                    "collection_id": "col-1",
                    "scope_type": "objective",
                    "scope_id": "obj-1",
                    "finding_id": "finding-1",
                    "claim_id": "claim-1",
                    "review_status": "incorrect",
                    "issue_type": "evidence_not_grounded",
                    "note": "The cited table does not support the mechanism claim.",
                    "reviewer": "materials-expert",
                    "created_at": "2026-06-18T08:00:00+00:00",
                }
            ),
        )
        self.curations = (
            ResearchUnderstandingCuration.from_mapping(
                {
                    "curation_id": "ruc-existing",
                    "collection_id": "col-1",
                    "scope_type": "objective",
                    "scope_id": "obj-1",
                    "finding_id": "finding-1",
                    "claim_id": "claim-1",
                    "curated_claim_type": "mechanism",
                    "curated_status": "limited",
                    "curated_statement": "Nitrogen improves strength with limited mechanism evidence.",
                    "curated_evidence_ref_ids": ["ev-1"],
                    "curated_context_ids": ["ctx-1"],
                    "note": "Needs microstructure evidence before marking supported.",
                    "reviewer": "materials-expert",
                    "updated_at": "2026-06-18T08:00:00+00:00",
                }
            ),
        )

    def record_feedback(self, **kwargs):  # noqa: ANN003
        self.created = kwargs
        return ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-created",
                "collection_id": kwargs["collection_id"],
                "scope_type": kwargs["scope_type"],
                "scope_id": kwargs["scope_id"],
                "finding_id": kwargs["finding_id"],
                "claim_id": kwargs["claim_id"],
                "review_status": kwargs["review_status"],
                "issue_type": kwargs["issue_type"],
                "note": kwargs["note"],
                "reviewer": kwargs["reviewer"],
                "created_at": "2026-06-18T09:00:00+00:00",
            }
        )

    def list_feedback(self, **kwargs):  # noqa: ANN003
        self.listed = kwargs
        return self.items

    def record_curation(self, **kwargs):  # noqa: ANN003
        self.curated = kwargs
        return ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-created",
                "collection_id": kwargs["collection_id"],
                "scope_type": kwargs["scope_type"],
                "scope_id": kwargs["scope_id"],
                "finding_id": kwargs["finding_id"],
                "claim_id": kwargs["claim_id"],
                "curated_claim_type": kwargs["curated_claim_type"],
                "curated_status": kwargs["curated_status"],
                "curated_statement": kwargs["curated_statement"],
                "curated_evidence_ref_ids": kwargs["curated_evidence_ref_ids"],
                "curated_context_ids": kwargs["curated_context_ids"],
                "note": kwargs["note"],
                "reviewer": kwargs["reviewer"],
                "updated_at": "2026-06-18T09:00:00+00:00",
            }
        )

    def list_curations(self, **kwargs):  # noqa: ANN003
        self.curations_listed = kwargs
        return self.curations

    def export_gold_draft(self, **kwargs):  # noqa: ANN003
        self.exported = kwargs
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": kwargs["scope_type"],
            "scope_id": kwargs["scope_id"],
            "gold_id": "gold_col-1_obj-1_research_understanding",
            "target_layer": "core",
            "metric_profile": "research_understanding_v1",
            "item_count": 1,
            "items": [
                {
                    "gold_item_id": "gold_claim-1",
                    "document_id": "",
                    "family": "research_understanding_findings",
                    "item_key": "objective:obj-1:finding-1",
                    "payload": {
                        "finding_id": "finding-1",
                        "claim_id": "claim-1",
                        "claim_type": "mechanism",
                        "status": "limited",
                        "statement": (
                            "Nitrogen improves strength with limited mechanism evidence."
                        ),
                    },
                    "evidence_refs": [{"evidence_ref_id": "ev-1"}],
                    "metadata": {"curation_id": "ruc-existing"},
                }
            ],
        }

    def export_dataset(self, **kwargs):  # noqa: ANN003
        self.dataset_exported = kwargs
        dataset_use_status = kwargs["dataset_use_status"] or "training_ready"
        label_status = "silver" if dataset_use_status == "review_candidate" else "gold"
        return {
            "schema_version": "research_understanding_dataset.v1",
            "dataset_id": "dataset_col-1_goal_goal-1_research_understanding",
            "collection_id": kwargs["collection_id"],
            "scope_type": kwargs["scope_type"],
            "scope_id": kwargs["scope_id"],
            "task_type": "research_understanding_finding",
            "metric_profile": "research_understanding_v1",
            "label_status_filter": kwargs["label_status"],
            "dataset_use_status_filter": kwargs["dataset_use_status"],
            "item_count": 1,
            "label_counts": {
                "candidate": 0,
                "silver": 1 if label_status == "silver" else 0,
                "gold": 1 if label_status == "gold" else 0,
                "rejected": 0,
            },
            "quality_summary": {
                "total_samples": 1,
                "usable_sample_count": 1,
                "training_ready_sample_count": 1,
                "review_candidate_sample_count": 0,
                "needs_review_count": 0,
                "rejected_count": 0,
                "labeled_sample_count": 1,
                "accepted_system_sample_count": 0,
                "accepted_after_curation_match_count": 1,
                "curated_correction_count": 0,
                "system_error_count": 0,
                "resolved_feedback_count": 0,
                "by_label_status": {
                    "candidate": 0,
                    "silver": 1 if label_status == "silver" else 0,
                    "gold": 1 if label_status == "gold" else 0,
                    "rejected": 0,
                },
                "by_dataset_use_status": {
                    "training_ready": 1 if dataset_use_status == "training_ready" else 0,
                    "review_candidate": 1 if dataset_use_status == "review_candidate" else 0,
                    "rejected": 0,
                },
                "by_review_status": {"accepted": 1},
                "by_issue_type": {"none": 1},
                "by_error_category": {"none": 1},
                "by_support_grade": {"partial": 1},
                "by_trace_status": {"unavailable": 1},
                "by_evidence_role": {"direct_result": 1},
                "by_evidence_traceability_status": {"direct": 1},
                "by_quality_decision": {"accepted_after_curation_match": 1},
                "by_presentation_bucket": {"primary": 1},
                "by_bucket_quality_decision": {
                    "primary": {"accepted_after_curation_match": 1}
                },
                "warning_counts": {
                    "missing_evidence": 0,
                    "missing_source_text": 0,
                    "missing_context": 0,
                    "unavailable_trace": 1,
                    "failed_trace": 0,
                    "rejected_feedback": 0,
                    "resolved_feedback": 0,
                },
            },
            "items": [
                {
                    "sample_id": "rus-1",
                    "task_type": "research_understanding_finding",
                    "collection_id": kwargs["collection_id"],
                    "scope_type": kwargs["scope_type"],
                    "scope_id": kwargs["scope_id"],
                    "finding_id": "finding-1",
                    "claim_id": "claim-1",
                    "label_status": label_status,
                    "dataset_use_status": dataset_use_status,
                    "presentation_bucket": "primary",
                    "trace_status": "unavailable",
                    "input_blocks": [],
                    "prompt_version": None,
                    "model_output": None,
                    "system_prediction": {
                        "statement": "Preheating improves ductility.",
                        "variables": ["build platform preheating"],
                        "mediators": ["homogenized microstructure"],
                        "outcomes": ["ductility"],
                        "direction": "increases",
                        "scope_summary": "LPBF 316L",
                        "support_grade": "partial",
                        "review_status": "needs_review",
                        "presentation_bucket": "primary",
                        "review_reasons": ["single_paper_evidence"],
                        "warnings": ["needs_expert_review"],
                    },
                    "expert_target": {
                        "source": "curation",
                        "statement": "Preheating improves ductility by 14%.",
                        "evidence_ref_ids": ["ev-1"],
                    },
                    "review_action": {
                        "code": "accept_as_paper_level",
                        "label": "Accept as paper-level evidence",
                    },
                    "evidence_refs": [
                        {
                            "evidence_ref_id": "ev-1",
                            "label": "P001 Section 3.2",
                            "source_ref": "blk_1",
                            "page": "9",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk_1",
                            "quote": "Preheating increased ductility by 14%.",
                            "source_text": (
                                "Preheating increased ductility by 14% in LPBF 316L."
                            ),
                            "training_source_text": "Preheating increased ductility by 14%.",
                        }
                    ],
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev-1",
                            "label": "P001 Section 3.2",
                            "source_ref": "blk_1",
                            "page": "9",
                            "href": "/collections/col-1/documents/doc-1?source_ref=blk_1",
                            "quote": "Preheating increased ductility by 14%.",
                            "source_text": (
                                "Preheating increased ductility by 14% in LPBF 316L."
                            ),
                            "training_source_text": "Preheating increased ductility by 14%.",
                        }
                    ],
                    "training_messages": [
                        {
                            "role": "user",
                            "content": (
                                "Research goal: improve LPBF 316L ductility.\n\n"
                                "Evidence ev-1: Preheating increased ductility by 14%."
                            ),
                        },
                        {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "finding": (
                                        "Preheating improves ductility by 14%."
                                    ),
                                    "evidence_ref_ids": ["ev-1"],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    "context_refs": [],
                    "feedback_refs": [],
                    "metadata": {"curation_id": "ruc-existing"},
                }
            ],
            "warnings": [],
        }

    def export_collection_dataset(self, **kwargs):  # noqa: ANN003
        self.collection_dataset_exported = kwargs
        dataset = self.export_dataset(
            collection_id=kwargs["collection_id"],
            scope_type="goal",
            scope_id="goal-1",
            label_status=kwargs["label_status"],
            dataset_use_status=kwargs["dataset_use_status"],
        )
        dataset["dataset_id"] = "dataset_col-1_collection_goal_research_understanding"
        dataset["scope_type"] = "collection"
        dataset["scope_id"] = kwargs["scope_type"]
        for item in dataset["items"]:
            item["scope_type"] = "goal"
            item["scope_id"] = "goal-1"
        return dataset


def test_research_understanding_feedback_route_records_contract_payload(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.create_research_understanding_feedback(
            "col-1",
            ResearchUnderstandingFeedbackCreateRequest(
                scope_type="objective",
                scope_id="obj-1",
                finding_id="finding-1",
                claim_id="claim-1",
                review_status="incorrect",
                issue_type="evidence_not_grounded",
                note="The cited table does not support the mechanism claim.",
                reviewer="materials-expert",
            ),
            request_with_user(),
        )
    )

    assert response.feedback_id == "ruf-created"
    assert response.collection_id == "col-1"
    assert response.scope_id == "obj-1"
    assert response.finding_id == "finding-1"
    assert response.claim_id == "claim-1"
    assert response.review_status == "incorrect"
    assert service.created == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "review_status": "incorrect",
        "issue_type": "evidence_not_grounded",
        "note": "The cited table does not support the mechanism claim.",
        "reviewer": "materials-expert@example.com",
    }


def test_research_understanding_feedback_route_preserves_agent_reviewer(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.create_research_understanding_feedback(
            "col-1",
            ResearchUnderstandingFeedbackCreateRequest(
                scope_type="objective",
                scope_id="obj-1",
                finding_id="finding-1",
                claim_id="claim-1",
                review_status="correct",
                issue_type="none",
                note="AI source audit accepted the evidence.",
                reviewer="ai-reviewer-codex-evidence-audit",
            ),
            request_with_user(),
        )
    )

    assert response.reviewer == "ai-reviewer-codex-evidence-audit"
    assert service.created["reviewer"] == "ai-reviewer-codex-evidence-audit"


def test_research_understanding_feedback_route_accepts_material_error_issue_type(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.create_research_understanding_feedback(
            "col-1",
            ResearchUnderstandingFeedbackCreateRequest(
                scope_type="goal",
                scope_id="goal-1",
                finding_id="finding-1",
                claim_id="claim-1",
                review_status="incorrect",
                issue_type="wrong_variable",
                note="The finding attributes the effect to VED, but the paper varied preheating.",
                reviewer="materials-expert",
            ),
            request_with_user(),
        )
    )

    assert response.issue_type == "wrong_variable"
    assert service.created["issue_type"] == "wrong_variable"


def test_research_understanding_feedback_route_lists_claim_feedback(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.list_research_understanding_feedback(
            "col-1",
            scope_type="objective",
            scope_id="obj-1",
            finding_id="finding-1",
            claim_id="claim-1",
        )
    )

    assert response.collection_id == "col-1"
    assert response.items[0].feedback_id == "ruf-existing"
    assert response.items[0].issue_type == "evidence_not_grounded"
    assert service.listed == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
    }


def test_research_understanding_curation_route_records_expert_claim_curation(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.create_research_understanding_curation(
            "col-1",
            ResearchUnderstandingCurationCreateRequest(
                scope_type="objective",
                scope_id="obj-1",
                finding_id="finding-1",
                claim_id="claim-1",
                curated_claim_type="mechanism",
                curated_status="limited",
                curated_statement=(
                    "Nitrogen improves strength with limited mechanism evidence."
                ),
                curated_evidence_ref_ids=["ev-1"],
                curated_context_ids=["ctx-1"],
                note="Needs microstructure evidence before marking supported.",
                reviewer="materials-expert",
            ),
            request_with_user(),
        )
    )

    assert response.curation_id == "ruc-created"
    assert response.collection_id == "col-1"
    assert response.finding_id == "finding-1"
    assert response.claim_id == "claim-1"
    assert response.curated_claim_type == "mechanism"
    assert response.curated_status == "limited"
    assert response.curated_evidence_ref_ids == ["ev-1"]
    assert service.curated == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "curated_claim_type": "mechanism",
        "curated_status": "limited",
        "curated_statement": "Nitrogen improves strength with limited mechanism evidence.",
        "curated_support_grade": None,
        "curated_review_status": None,
        "curated_variables": [],
        "curated_mediators": [],
        "curated_outcomes": [],
        "curated_direction": None,
        "curated_scope_summary": None,
        "curated_evidence_ref_ids": ["ev-1"],
        "curated_context_ids": ["ctx-1"],
        "note": "Needs microstructure evidence before marking supported.",
        "reviewer": "materials-expert@example.com",
    }


def test_research_understanding_curation_route_preserves_agent_reviewer(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.create_research_understanding_curation(
            "col-1",
            ResearchUnderstandingCurationCreateRequest(
                scope_type="objective",
                scope_id="obj-1",
                finding_id="finding-1",
                claim_id="claim-1",
                curated_claim_type="mechanism",
                curated_status="limited",
                curated_statement=(
                    "Nitrogen improves strength with limited mechanism evidence."
                ),
                curated_evidence_ref_ids=["ev-1"],
                curated_context_ids=["ctx-1"],
                note="AI curation candidate, keep silver.",
                reviewer="agent-lens-claim-review",
            ),
            request_with_user(),
        )
    )

    assert response.reviewer == "agent-lens-claim-review"
    assert service.curated["reviewer"] == "agent-lens-claim-review"


def test_research_understanding_curation_route_lists_expert_claim_curations(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.list_research_understanding_curations(
            "col-1",
            scope_type="objective",
            scope_id="obj-1",
            finding_id="finding-1",
            claim_id="claim-1",
        )
    )

    assert response.collection_id == "col-1"
    assert response.items[0].curation_id == "ruc-existing"
    assert response.items[0].curated_status == "limited"
    assert service.curations_listed == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
    }


def test_research_understanding_gold_draft_route_exports_curations(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_research_understanding_gold_draft(
            "col-1",
            scope_type="objective",
            scope_id="obj-1",
        )
    )

    assert response.collection_id == "col-1"
    assert response.scope_type == "objective"
    assert response.scope_id == "obj-1"
    assert response.item_count == 1
    assert response.items[0].family == "research_understanding_findings"
    assert response.items[0].payload["claim_type"] == "mechanism"
    assert service.exported == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
    }


def test_research_understanding_dataset_route_exports_json(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            scope_id="goal-1",
            label_status="gold",
            dataset_use_status="training_ready",
            format="json",
        )
    )

    assert response.collection_id == "col-1"
    assert response.scope_type == "goal"
    assert response.scope_id == "goal-1"
    assert response.label_status_filter == "gold"
    assert response.dataset_use_status_filter == "training_ready"
    assert response.item_count == 1
    assert response.quality_summary.total_samples == 1
    assert response.quality_summary.by_label_status["gold"] == 1
    assert response.quality_summary.by_issue_type == {"none": 1}
    assert response.quality_summary.by_error_category == {"none": 1}
    assert response.quality_summary.accepted_after_curation_match_count == 1
    assert response.quality_summary.curated_correction_count == 0
    assert response.quality_summary.resolved_feedback_count == 0
    assert response.quality_summary.by_quality_decision == {
        "accepted_after_curation_match": 1
    }
    assert response.quality_summary.by_presentation_bucket == {"primary": 1}
    assert response.quality_summary.by_bucket_quality_decision == {
        "primary": {"accepted_after_curation_match": 1}
    }
    assert response.items[0].label_status == "gold"
    assert response.items[0].presentation_bucket == "primary"
    assert response.items[0].evidence_refs[0]["source_text"] == (
        "Preheating increased ductility by 14% in LPBF 316L."
    )
    assert response.items[0].training_evidence_refs[0]["training_source_text"] == (
        "Preheating increased ductility by 14%."
    )
    assert response.items[0].training_messages[0]["role"] == "user"
    assert response.items[0].training_messages[1]["role"] == "assistant"
    assert service.dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "scope_id": "goal-1",
        "label_status": "gold",
        "dataset_use_status": "training_ready",
    }


def test_research_understanding_dataset_route_exports_jsonl(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            scope_id="goal-1",
            label_status=None,
            dataset_use_status=None,
            format="jsonl",
        )
    )

    assert response.media_type == "application/x-ndjson"
    body = response.body.decode("utf-8")
    line = json.loads(body.strip())
    assert line["sample_id"] == "rus-1"
    assert line["presentation_bucket"] == "primary"
    assert body.endswith("\n")
    assert service.dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "scope_id": "goal-1",
        "label_status": None,
        "dataset_use_status": None,
    }


def test_research_understanding_dataset_route_exports_messages_jsonl(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            scope_id="goal-1",
            label_status="gold",
            dataset_use_status="training_ready",
            format="messages_jsonl",
        )
    )

    assert response.media_type == "application/x-ndjson"
    body = response.body.decode("utf-8")
    line = json.loads(body.strip())
    assert list(line) == ["messages"]
    assert line["messages"][0]["role"] == "user"
    assert line["messages"][1]["role"] == "assistant"
    assert "Preheating increased ductility by 14%." in line["messages"][0]["content"]
    assert '"evidence_ref_ids": ["ev-1"]' in line["messages"][1]["content"]
    assert body.endswith("\n")
    assert service.dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "scope_id": "goal-1",
        "label_status": "gold",
        "dataset_use_status": "training_ready",
    }


def test_research_understanding_dataset_route_exports_review_jsonl(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            scope_id="goal-1",
            label_status=None,
            dataset_use_status="review_candidate",
            format="review_jsonl",
        )
    )

    assert response.media_type == "application/x-ndjson"
    body = response.body.decode("utf-8")
    line = json.loads(body.strip())
    assert line["collection_id"] == "col-1"
    assert line["goal_id"] == "goal-1"
    assert line["finding_id"] == "finding-1"
    assert line["claim_id"] == "claim-1"
    assert line["statement"] == "Preheating improves ductility."
    assert line["variables"] == ["build platform preheating"]
    assert line["outcomes"] == ["ductility"]
    assert line["direction"] == "increases"
    assert line["recommended_action"] == "Accept as paper-level evidence"
    assert line["review_instructions"].startswith("Set action=accept")
    assert line["review_risk_flags"] == [
        "Paper-level evidence; do not treat as cross-paper conclusion without confirmation."
    ]
    assert line["action"] == "skip"
    assert "accept" in line["allowed_actions"]
    assert "wrong_direction" in line["reject_issue_options"]
    assert line["issue_type"] == ""
    assert line["expert_note"] == ""
    assert line["evidence"][0]["evidence_ref_id"] == "ev-1"
    assert line["evidence"][0]["href"].endswith("source_ref=blk_1")
    assert line["suggested_target"]["statement"] == (
        "Preheating improves ductility by 14%."
    )
    assert body.endswith("\n")
    assert service.dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "scope_id": "goal-1",
        "label_status": None,
        "dataset_use_status": "review_candidate",
    }


def test_research_understanding_collection_dataset_route_exports_json(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_collection_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            label_status="gold",
            dataset_use_status="training_ready",
            format="json",
        )
    )

    assert response.collection_id == "col-1"
    assert response.scope_type == "collection"
    assert response.scope_id == "goal"
    assert response.label_status_filter == "gold"
    assert response.dataset_use_status_filter == "training_ready"
    assert response.item_count == 1
    assert response.items[0].scope_type == "goal"
    assert response.items[0].scope_id == "goal-1"
    assert service.collection_dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "label_status": "gold",
        "dataset_use_status": "training_ready",
    }


def test_research_understanding_collection_dataset_route_exports_jsonl(monkeypatch):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_collection_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            label_status=None,
            dataset_use_status=None,
            format="jsonl",
        )
    )

    assert response.media_type == "application/x-ndjson"
    body = response.body.decode("utf-8")
    line = json.loads(body.strip())
    assert line["scope_type"] == "goal"
    assert line["scope_id"] == "goal-1"
    assert line["sample_id"] == "rus-1"
    assert body.endswith("\n")
    assert service.collection_dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "label_status": None,
        "dataset_use_status": None,
    }


def test_research_understanding_collection_dataset_route_exports_messages_jsonl(
    monkeypatch,
):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_collection_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            label_status="gold",
            dataset_use_status="training_ready",
            format="messages_jsonl",
        )
    )

    assert response.media_type == "application/x-ndjson"
    body = response.body.decode("utf-8")
    line = json.loads(body.strip())
    assert list(line) == ["messages"]
    assert line["messages"][0]["role"] == "user"
    assert line["messages"][1]["role"] == "assistant"
    assert body.endswith("\n")
    assert service.collection_dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "label_status": "gold",
        "dataset_use_status": "training_ready",
    }


def test_research_understanding_collection_dataset_route_exports_review_jsonl(
    monkeypatch,
):
    service = FakeResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        feedback_controller,
        "feedback_service",
        service,
    )

    response = asyncio.run(
        feedback_controller.export_collection_research_understanding_dataset(
            "col-1",
            scope_type="goal",
            label_status=None,
            dataset_use_status="review_candidate",
            format="review_jsonl",
        )
    )

    assert response.media_type == "application/x-ndjson"
    body = response.body.decode("utf-8")
    line = json.loads(body.strip())
    assert line["collection_id"] == "col-1"
    assert line["goal_id"] == "goal-1"
    assert line["scope_type"] == "goal"
    assert line["action"] == "skip"
    assert line["evidence"][0]["quote"] == "Preheating increased ductility by 14%."
    assert body.endswith("\n")
    assert service.collection_dataset_exported == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "label_status": None,
        "dataset_use_status": "review_candidate",
    }
