from __future__ import annotations

import pytest

from domain.core.research_understanding import ResearchUnderstanding
from domain.evaluation import (
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)
from domain.goal import ExperimentPlanRecord
from infra.persistence.postgres.objective_workspace_repository import (
    PostgresObjectiveWorkspaceRepository,
)
from infra.persistence.postgres.research_understanding_repository import (
    PostgresResearchUnderstandingRepository,
)
from infra.persistence.postgres.research_understanding_review_repository import (
    PostgresResearchUnderstandingReviewRepository,
)

pytest_plugins = (
    "tests.integration.persistence.test_objective_identity_migration",
)


NOW = "2026-07-20T10:00:00+00:00"


def _understanding() -> ResearchUnderstanding:
    return ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "objective",
                "collection_id": "collection-1",
                "objective_id": "objective-linked",
                "title": "Heat treatment and strength",
            },
            "claims": [
                {
                    "claim_id": "claim-1",
                    "claim_type": "finding",
                    "statement": "Heat treatment increased strength.",
                    "status": "supported",
                    "evidence_ref_ids": ["evidence-1"],
                    "context_ids": ["context-1"],
                }
            ],
            "relations": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evidence-1",
                    "source_kind": "text",
                    "document_id": "document-1",
                    "label": "Source 1",
                    "locator": {"page": 1},
                    "fact_ids": ["result-1"],
                    "anchor_ids": ["anchor-1"],
                    "traceability_status": "resolved",
                    "quote": "Strength increased.",
                }
            ],
            "contexts": [
                {
                    "context_id": "context-1",
                    "label": "Heat treatment",
                    "material_scope": ["Alloy A"],
                    "process_context": {"process": "heat treatment"},
                    "test_condition": {},
                    "property_scope": ["strength"],
                    "limitations": [],
                }
            ],
            "presentation": {
                "findings": [
                    {
                        "finding_id": "finding-1",
                        "claim_id": "claim-1",
                        "statement": "Heat treatment increased strength.",
                        "finding_fingerprint": "finding.v1:abc",
                        "review_status": "pending_review",
                        "evidence_ref_ids": ["evidence-1"],
                    }
                ]
            },
        }
    )


def test_objective_understanding_and_review_round_trip(migration_target) -> None:
    understandings = PostgresResearchUnderstandingRepository(migration_target)
    reviews = PostgresResearchUnderstandingReviewRepository(migration_target)

    understandings.upsert_objective_understanding(
        "collection-1", "objective-linked", _understanding()
    )
    stored = understandings.read_objective_understanding(
        "collection-1", "objective-linked"
    )

    assert stored is not None
    assert stored.scope.objective_id == "objective-linked"
    assert stored.claims[0].evidence_ref_ids == ("evidence-1",)
    assert stored.presentation["findings"][0]["finding_id"] == "finding-1"

    feedback = reviews.upsert_feedback(
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "feedback-1",
                "collection_id": "collection-1",
                "objective_id": "objective-linked",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "review_status": "correct",
                "issue_type": "none",
                "reviewer": "expert@example.com",
                "created_at": NOW,
            }
        )
    )
    curation = reviews.upsert_curation(
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                "collection_id": "collection-1",
                "objective_id": "objective-linked",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "curated_claim_type": "finding",
                "curated_status": "supported",
                "curated_statement": "Reviewed finding.",
                "curated_evidence_ref_ids": ["evidence-1"],
                "curated_context_ids": ["context-1"],
                "updated_at": NOW,
            }
        )
    )

    assert feedback.objective_id == "objective-linked"
    assert curation.objective_id == "objective-linked"
    assert reviews.list_feedback("collection-1", "objective-linked") == (feedback,)
    assert reviews.list_curations("collection-1", "objective-linked") == (curation,)

    with pytest.raises(ValueError, match="same Objective"):
        reviews.upsert_feedback(
            ResearchUnderstandingFeedback.from_mapping(
                {
                    **feedback.to_record(),
                    "feedback_id": "feedback-invalid",
                    "claim_id": "claim-other",
                }
            )
        )


def test_objective_workspace_preserves_message_and_plan_provenance(
    migration_target,
) -> None:
    repository = PostgresObjectiveWorkspaceRepository(migration_target)
    repository.write_session(
        {
            "session_id": "session-1",
            "user_id": "user-1",
            "collection_id": "collection-1",
            "focused_material_id": None,
            "focused_paper_id": None,
            "focused_objective_id": "objective-linked",
            "goal_text": "Design a validation experiment",
            "goal_brief_json": {},
            "answer_mode": "grounded",
            "rolling_summary": "",
            "last_evidence_ids": [],
            "last_material_ids": [],
            "last_paper_ids": [],
            "collection_data_version": "build-1",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    repository.write_messages(
        "session-1",
        [
            {
                "message_id": "message-1",
                "session_id": "session-1",
                "role": "assistant",
                "content": "Use the reviewed finding [Source 1].",
                "source_mode": "collection_grounded",
                "used_evidence_ids": ["evidence-1"],
                "warnings": [],
                "links": {},
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/collection-1/documents/document-1?evidence_id=evidence-1",
                    }
                ],
                "review_gate": "protocol_ready_findings",
                "source_finding_refs": [{"finding_id": "finding-1"}],
                "created_at": NOW,
            }
        ],
    )
    plan = repository.upsert_plan(
        ExperimentPlanRecord.from_mapping(
            {
                "plan_id": "plan-1",
                "collection_id": "collection-1",
                "objective_id": "objective-linked",
                "title": "Validation plan",
                "content": "Compare controlled heat treatments.",
                "status": "draft",
                "source_message_id": "message-1",
                "created_by": "user-1",
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
    )

    context = repository.read_message_context("message-1")
    assert context is not None
    assert context["session"]["focused_objective_id"] == "objective-linked"
    assert "focused_goal_id" not in context["session"]
    assert plan.objective_id == "objective-linked"
    assert repository.list_plans("collection-1", "objective-linked") == (plan,)

    with pytest.raises(ValueError, match="Objective workspace"):
        repository.upsert_plan(
            ExperimentPlanRecord.from_mapping(
                {
                    **plan.to_record(),
                    "plan_id": "plan-invalid",
                    "objective_id": "objective-other",
                }
            )
        )
