from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient
import pytest

from application.evaluation import ResearchUnderstandingFeedbackService
from domain.core import ResearchUnderstanding
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback


@dataclass
class RecordingResearchUnderstandingFeedbackService:
    feedback_calls: list[dict[str, Any]] = field(default_factory=list)
    curation_calls: list[dict[str, Any]] = field(default_factory=list)

    def record_feedback(self, **kwargs):  # noqa: ANN003
        self.feedback_calls.append(kwargs)
        return ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": f"ruf-{len(self.feedback_calls)}",
                "collection_id": kwargs["collection_id"],
                "scope_type": kwargs["scope_type"],
                "scope_id": kwargs["scope_id"],
                "finding_id": kwargs["finding_id"],
                "claim_id": kwargs["claim_id"],
                "review_status": kwargs["review_status"],
                "issue_type": kwargs["issue_type"],
                "note": kwargs["note"],
                "reviewer": kwargs["reviewer"],
                "created_at": "2026-07-11T00:00:00+00:00",
            }
        )

    def record_curation(self, **kwargs):  # noqa: ANN003
        self.curation_calls.append(kwargs)
        return ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": f"ruc-{len(self.curation_calls)}",
                "collection_id": kwargs["collection_id"],
                "scope_type": kwargs["scope_type"],
                "scope_id": kwargs["scope_id"],
                "finding_id": kwargs["finding_id"],
                "claim_id": kwargs["claim_id"],
                "curated_claim_type": kwargs["curated_claim_type"],
                "curated_status": kwargs["curated_status"],
                "curated_statement": kwargs["curated_statement"],
                "curated_support_grade": kwargs["curated_support_grade"],
                "curated_review_status": kwargs["curated_review_status"],
                "curated_variables": kwargs["curated_variables"],
                "curated_mediators": kwargs["curated_mediators"],
                "curated_outcomes": kwargs["curated_outcomes"],
                "curated_direction": kwargs["curated_direction"],
                "curated_scope_summary": kwargs["curated_scope_summary"],
                "curated_evidence_ref_ids": kwargs["curated_evidence_ref_ids"],
                "curated_context_ids": kwargs["curated_context_ids"],
                "note": kwargs["note"],
                "reviewer": kwargs["reviewer"],
                "updated_at": "2026-07-11T00:00:00+00:00",
            }
        )


class PersistingEvaluationRepository:
    backend_name = "fake"

    def __init__(self) -> None:
        self.feedback: list[ResearchUnderstandingFeedback] = []
        self.curations: list[ResearchUnderstandingCuration] = []

    def upsert_research_understanding_feedback(self, feedback):
        self.feedback.append(feedback)
        return feedback

    def upsert_research_understanding_curation(self, curation):
        self.curations = [
            existing
            for existing in self.curations
            if existing.curation_id != curation.curation_id
        ]
        self.curations.append(curation)
        return curation

    def list_research_understanding_feedback(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ):
        return tuple(
            item
            for item in self.feedback
            if item.collection_id == collection_id
            and (scope_type is None or item.scope_type == scope_type)
            and (scope_id is None or item.scope_id == scope_id)
            and (finding_id is None or item.finding_id == finding_id)
            and (claim_id is None or item.claim_id == claim_id)
        )

    def list_research_understanding_curations(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ):
        return tuple(
            item
            for item in self.curations
            if item.collection_id == collection_id
            and (scope_type is None or item.scope_type == scope_type)
            and (scope_id is None or item.scope_id == scope_id)
            and (finding_id is None or item.finding_id == finding_id)
            and (claim_id is None or item.claim_id == claim_id)
        )


class StaticResearchUnderstandingRepository:
    backend_name = "fake"

    def __init__(self, understanding: ResearchUnderstanding) -> None:
        self.understanding = understanding

    def read_research_understanding(
        self,
        collection_id: str,  # noqa: ARG002
        scope_type: str,  # noqa: ARG002
        scope_id: str,  # noqa: ARG002
    ):
        return self.understanding

    def list_research_understandings(
        self,
        collection_id: str,  # noqa: ARG002
        scope_type: str | None = None,
    ):
        if scope_type and self.understanding.scope.scope_type != scope_type:
            return ()
        return (self.understanding,)


class PassthroughResearchUnderstandingService:
    def with_presentation(self, understanding: ResearchUnderstanding):
        return understanding.to_record()


@pytest.fixture()
def feedback_client(
    monkeypatch,
    tmp_path,
    auth_session_service,
) -> Iterator[tuple[TestClient, RecordingResearchUnderstandingFeedbackService]]:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("LENS_PERSISTENCE_BACKEND", "file")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.factory.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.artifact_repository.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.task_repository.DATA_DIR", tmp_path)

    from tests.support.collection_service import build_test_collection_service
    from controllers.core import research_understanding_feedback
    from main import create_app

    collection_service = build_test_collection_service(tmp_path / "collections")
    feedback_service = RecordingResearchUnderstandingFeedbackService()
    monkeypatch.setattr(
        research_understanding_feedback,
        "feedback_service",
        feedback_service,
    )
    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
        )
    ) as client:
        yield client, feedback_service


@pytest.fixture()
def real_feedback_client(
    monkeypatch,
    tmp_path,
    auth_session_service,
) -> Iterator[TestClient]:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("LENS_PERSISTENCE_BACKEND", "file")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.factory.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.artifact_repository.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.task_repository.DATA_DIR", tmp_path)

    from tests.support.collection_service import build_test_collection_service
    from controllers.core import research_understanding_feedback
    from main import create_app

    collection_service = build_test_collection_service(tmp_path / "collections")
    feedback_service = ResearchUnderstandingFeedbackService(
        evaluation_repository=PersistingEvaluationRepository(),
        core_fact_repository=StaticResearchUnderstandingRepository(
            _sample_understanding()
        ),
        research_understanding_service=PassthroughResearchUnderstandingService(),
    )
    monkeypatch.setattr(
        research_understanding_feedback,
        "feedback_service",
        feedback_service,
    )
    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
        )
    ) as client:
        yield client


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin-password"},
    )
    assert response.status_code == 200


def _create_collection(client: TestClient) -> str:
    response = client.post("/api/v1/collections", json={"name": "Review papers"})
    assert response.status_code == 200
    return response.json()["collection_id"]


def _sample_understanding() -> ResearchUnderstanding:
    return ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-test",
                "goal_id": "goal-1",
                "title": "How does preheating affect ductility?",
            },
            "claims": [
                {
                    "claim_id": "claim-1",
                    "claim_type": "finding",
                    "statement": "Preheating improves ductility.",
                    "status": "limited",
                    "evidence_ref_ids": ["ev-1"],
                    "context_ids": ["ctx-1"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev-1",
                    "source_kind": "text",
                    "document_id": "doc-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-preheat"},
                    "traceability_status": "direct",
                    "evidence_role": "direct_result",
                    "quote": "Preheating increased ductility by 14%.",
                    "href": "/documents/doc-1#blk-preheat",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx-1",
                    "label": "LPBF 316L",
                    "material_scope": ["316L"],
                    "process_context": {"process": "LPBF"},
                    "test_condition": {"temperature": "room"},
                    "property_scope": ["ductility"],
                }
            ],
            "presentation": {
                "findings": [
                    {
                        "finding_id": "finding-1",
                        "claim_id": "claim-1",
                        "title": "preheating -> ductility",
                        "statement": "Preheating improves ductility.",
                        "variables": ["preheating"],
                        "mediators": ["cellular microstructure"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "scope_summary": "LPBF 316L",
                        "support_grade": "partial",
                        "review_status": "needs_review",
                        "confidence": 0.7,
                        "paper_count": 1,
                        "evidence_count": 1,
                        "source_object_ids": ["oeu-preheat"],
                        "evidence_ref_ids": ["ev-1"],
                        "context_ids": ["ctx-1"],
                    }
                ],
                "primary_findings": [
                    {
                        "finding_id": "finding-1",
                        "claim_id": "claim-1",
                        "statement": "Preheating improves ductility.",
                        "evidence_ref_ids": ["ev-1"],
                        "context_ids": ["ctx-1"],
                    }
                ],
                "evidence_items": [
                    {
                        "evidence_ref_id": "ev-1",
                        "document_id": "doc-1",
                        "title": "P001 Results",
                        "source_label": "P001 p.9",
                        "source_kind": "text",
                        "source_ref": "blk-preheat",
                        "block_type": "paragraph",
                        "heading_path": "Results",
                        "page": "9",
                        "quote": "Preheating increased ductility by 14%.",
                        "source_text": (
                            "Preheating increased ductility by 14% in LPBF 316L."
                        ),
                        "traceability_status": "direct",
                        "evidence_role": "direct_result",
                        "href": "/documents/doc-1#blk-preheat",
                    }
                ],
                "context_summaries": [
                    {
                        "context_id": "ctx-1",
                        "label": "LPBF 316L",
                        "material_scope": ["316L"],
                        "property_scope": ["ductility"],
                        "process_summary": "LPBF",
                        "test_summary": "room temperature",
                    }
                ],
            },
        }
    )


def test_feedback_route_uses_authenticated_user_not_spoofed_reviewer(
    feedback_client,
):
    client, feedback_service = feedback_client
    _login(client)
    collection_id = _create_collection(client)

    response = client.post(
        f"/api/v1/collections/{collection_id}/research-understanding/feedback",
        json={
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-1",
            "claim_id": "claim-1",
            "review_status": "correct",
            "issue_type": "none",
            "note": "Human expert accepted this source-grounded finding.",
            "reviewer": "spoofed-human-reviewer",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "admin@example.com"
    assert feedback_service.feedback_calls[-1]["reviewer"] == "admin@example.com"


def test_curation_route_uses_authenticated_user_not_spoofed_reviewer(
    feedback_client,
):
    client, feedback_service = feedback_client
    _login(client)
    collection_id = _create_collection(client)

    response = client.post(
        f"/api/v1/collections/{collection_id}/research-understanding/curations",
        json={
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-1",
            "claim_id": "claim-1",
            "curated_claim_type": "finding",
            "curated_status": "supported",
            "curated_statement": "Preheating improves LPBF 316L ductility by 14%.",
            "curated_support_grade": "strong",
            "curated_review_status": "accepted",
            "curated_variables": ["preheating"],
            "curated_outcomes": ["ductility"],
            "curated_evidence_ref_ids": ["ev-1"],
            "note": "Human expert curation.",
            "reviewer": "spoofed-human-curator",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "admin@example.com"
    assert feedback_service.curation_calls[-1]["reviewer"] == "admin@example.com"


def test_feedback_route_preserves_agent_reviewer(
    feedback_client,
):
    client, feedback_service = feedback_client
    _login(client)
    collection_id = _create_collection(client)

    response = client.post(
        f"/api/v1/collections/{collection_id}/research-understanding/feedback",
        json={
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-1",
            "claim_id": "claim-1",
            "review_status": "partial",
            "issue_type": "none",
            "note": "Agent audit keeps this as silver.",
            "reviewer": "ai-reviewer-codex-evidence-audit",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "ai-reviewer-codex-evidence-audit"
    assert (
        feedback_service.feedback_calls[-1]["reviewer"]
        == "ai-reviewer-codex-evidence-audit"
    )


def test_feedback_route_requires_login_before_writing(
    feedback_client,
):
    client, feedback_service = feedback_client

    response = client.post(
        "/api/v1/collections/col-missing/research-understanding/feedback",
        json={
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-1",
            "review_status": "correct",
            "issue_type": "none",
            "reviewer": "spoofed-human-reviewer",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
    assert feedback_service.feedback_calls == []


def test_human_curation_route_makes_dataset_sample_training_ready(
    real_feedback_client,
):
    client = real_feedback_client
    _login(client)
    collection_id = _create_collection(client)

    curation = client.post(
        f"/api/v1/collections/{collection_id}/research-understanding/curations",
        json={
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-1",
            "claim_id": "claim-1",
            "curated_claim_type": "finding",
            "curated_status": "supported",
            "curated_statement": "Preheating improves ductility by 14% in LPBF 316L.",
            "curated_support_grade": "partial",
            "curated_review_status": "accepted",
            "curated_variables": ["preheating"],
            "curated_mediators": ["cellular microstructure"],
            "curated_outcomes": ["ductility"],
            "curated_direction": "increase",
            "curated_scope_summary": "LPBF 316L",
            "curated_evidence_ref_ids": ["ev-1"],
            "curated_context_ids": ["ctx-1"],
            "note": "Human expert verified the quote.",
            "reviewer": "spoofed-human-curator",
        },
    )
    assert curation.status_code == 200
    assert curation.json()["reviewer"] == "admin@example.com"

    dataset = client.get(
        (
            f"/api/v1/collections/{collection_id}/research-understanding/dataset"
            "?scope_type=goal&scope_id=goal-1"
        )
    )

    assert dataset.status_code == 200
    payload = dataset.json()
    assert payload["quality_summary"]["training_ready_sample_count"] == 1
    assert payload["quality_summary"]["by_dataset_use_status"]["training_ready"] == 1
    assert payload["items"][0]["label_status"] == "gold"
    assert payload["items"][0]["dataset_use_status"] == "training_ready"
    assert payload["items"][0]["expert_target"]["source"] == "curation"
    assert payload["items"][0]["expert_target"]["reviewer"] == "admin@example.com"
    assert payload["items"][0]["input_blocks"][0]["text"] == (
        "Preheating increased ductility by 14%."
    )
    assert payload["items"][0]["training_evidence_refs"][0]["source_ref"] == (
        "blk-preheat"
    )

    collection_dataset = client.get(
        (
            f"/api/v1/collections/{collection_id}"
            "/research-understanding/dataset/collection?scope_type=goal"
        )
    )

    assert collection_dataset.status_code == 200
    collection_payload = collection_dataset.json()
    assert collection_payload["scope_type"] == "collection"
    assert collection_payload["scope_id"] == "goal"
    assert collection_payload["quality_summary"]["training_ready_sample_count"] == 1
    assert (
        collection_payload["quality_summary"]["by_dataset_use_status"][
            "training_ready"
        ]
        == 1
    )
    assert collection_payload["items"][0]["dataset_use_status"] == "training_ready"
