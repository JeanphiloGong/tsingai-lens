from __future__ import annotations

import asyncio

from controllers.core import research_understanding_feedback as feedback_controller
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingCurationCreateRequest,
    ResearchUnderstandingFeedbackCreateRequest,
)
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback


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
                claim_id="claim-1",
                review_status="incorrect",
                issue_type="evidence_not_grounded",
                note="The cited table does not support the mechanism claim.",
                reviewer="materials-expert",
            ),
        )
    )

    assert response.feedback_id == "ruf-created"
    assert response.collection_id == "col-1"
    assert response.scope_id == "obj-1"
    assert response.claim_id == "claim-1"
    assert response.review_status == "incorrect"
    assert service.created == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
        "claim_id": "claim-1",
        "review_status": "incorrect",
        "issue_type": "evidence_not_grounded",
        "note": "The cited table does not support the mechanism claim.",
        "reviewer": "materials-expert",
    }


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
        )
    )

    assert response.curation_id == "ruc-created"
    assert response.collection_id == "col-1"
    assert response.claim_id == "claim-1"
    assert response.curated_claim_type == "mechanism"
    assert response.curated_status == "limited"
    assert response.curated_evidence_ref_ids == ["ev-1"]
    assert service.curated == {
        "collection_id": "col-1",
        "scope_type": "objective",
        "scope_id": "obj-1",
        "claim_id": "claim-1",
        "curated_claim_type": "mechanism",
        "curated_status": "limited",
        "curated_statement": "Nitrogen improves strength with limited mechanism evidence.",
        "curated_evidence_ref_ids": ["ev-1"],
        "curated_context_ids": ["ctx-1"],
        "note": "Needs microstructure evidence before marking supported.",
        "reviewer": "materials-expert",
    }


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
        "claim_id": "claim-1",
    }
