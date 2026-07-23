from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers.core.finding_review import router
from domain.evaluation import FindingCuration, FindingFeedback


class _Service:
    def record_feedback(self, **kwargs):
        return FindingFeedback.from_mapping(
            {
                "feedback_id": "feedback-1",
                **kwargs,
                "created_at": "2026-07-22T00:00:00+00:00",
            }
        )

    def list_feedback(self, **kwargs):
        return (
            self.record_feedback(
                **kwargs,
                review_status="correct",
                issue_type="none",
            ),
        )

    def record_curation(self, **kwargs):
        return FindingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                **kwargs,
                "updated_at": "2026-07-22T00:00:00+00:00",
            }
        )

    def list_curations(self, **kwargs):
        return (
            self.record_curation(
                **kwargs,
                curated_status="limited",
                curated_statement="Narrower expert statement.",
                curated_evidence_ids=["evidence-1"],
            ),
        )

    def export_dataset(self, **kwargs):
        return _dataset(kwargs["collection_id"], kwargs["objective_id"])

    def export_collection_dataset(self, **kwargs):
        return _dataset(kwargs["collection_id"], None)

    def export_gold_draft(self, **kwargs):
        return {
            "gold_id": "gold-1",
            "collection_id": kwargs["collection_id"],
            "version": "objective_finding_dataset.v1",
            "target_layer": "core",
            "metric_profile": "objective_findings_v1",
            "items": [],
        }


def _dataset(collection_id: str, objective_id: str | None) -> dict:
    return {
        "schema_version": "objective_finding_dataset.v1",
        "collection_id": collection_id,
        "objective_id": objective_id,
        "items": [
            {
                "sample_id": "sample-1",
                "objective_id": objective_id or "obj-1",
                "analysis_version": 1,
                "finding_id": "finding-1",
                "research_objective": "How does temperature affect strength?",
                "finding_level": "paper",
                "document_ids": ["paper-1"],
                "label_status": "gold",
                "dataset_use_status": "training_ready",
                "system_prediction": {"statement": "Temperature affects strength."},
                "expert_target": None,
                "evidence": [
                    {
                        "evidence_id": "evidence-1",
                        "source_excerpt": "At 500 C, strength reached 620 MPa.",
                    }
                ],
                "training_schema_version": "objective_finding_training.v1",
                "training_prompt_version": "objective_finding_training_prompt.v1",
                "training_messages": [
                    {
                        "role": "user",
                        "content": "Evidence: At 500 C, strength reached 620 MPa.",
                    },
                    {"role": "assistant", "content": "{}"},
                ],
                "metadata": {"analysis_version": 1},
            }
        ],
        "warnings": [],
    }


def _client() -> TestClient:
    app = FastAPI()
    app.state.finding_feedback_service = _Service()
    app.include_router(router)
    return TestClient(app)


def test_feedback_api_requires_explicit_analysis_version() -> None:
    response = _client().post(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        json={
            "analysis_version": 1,
            "review_status": "correct",
            "issue_type": "none",
        },
    )

    assert response.status_code == 200
    assert response.json()["analysis_version"] == 1
    assert "claim_id" not in response.json()


def test_curation_api_uses_finding_evidence_ids() -> None:
    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_statement": "Narrower expert statement.",
            "curated_evidence_ids": ["evidence-1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["curated_evidence_ids"] == ["evidence-1"]


def test_training_jsonl_contains_messages_and_versioned_metadata() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "training_jsonl"},
    )

    assert response.status_code == 200
    row = response.json()
    assert "At 500 C" in row["messages"][0]["content"]
    assert row["metadata"]["analysis_version"] == 1
