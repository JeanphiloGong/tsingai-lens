from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers.core.finding_review import router
from domain.core import Finding, ObjectiveEvidence
from domain.evaluation import FindingCuration, FindingFeedback


class _Service:
    async def record_feedback(self, **kwargs):
        return FindingFeedback.from_mapping(
            {
                "feedback_id": "feedback-1",
                **kwargs,
                "created_at": "2026-07-22T00:00:00+00:00",
            }
        )

    async def list_feedback(self, **kwargs):
        if kwargs["analysis_version"] != 1:
            raise ValueError("review must reference the published analysis version")
        return (
            await self.record_feedback(
                **kwargs,
                review_status="correct",
                issue_type="none",
            ),
        )

    async def record_curation(self, **kwargs):
        return FindingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                **kwargs,
                "updated_at": "2026-07-22T00:00:00+00:00",
            }
        )

    async def list_curations(self, **kwargs):
        if kwargs["analysis_version"] != 1:
            raise ValueError("review must reference the published analysis version")
        return (
            await self.record_curation(
                **kwargs,
                curated_status="limited",
                curated_finding=_finding_record("Narrower expert statement."),
            ),
        )

    async def export_dataset(self, **kwargs):
        return _dataset(kwargs["collection_id"], kwargs["objective_id"])

    async def export_collection_dataset(self, **kwargs):
        return _dataset(kwargs["collection_id"], None)

    async def export_gold_draft(self, **kwargs):
        return {
            "gold_id": "gold-1",
            "collection_id": kwargs["collection_id"],
            "version": "objective_finding_dataset.v2",
            "target_layer": "core",
            "metric_profile": "objective_findings_v1",
            "items": [],
        }


def _dataset(collection_id: str, objective_id: str | None) -> dict:
    finding = _finding_record()
    evidence = _evidence_record()
    return {
        "schema_version": "objective_finding_dataset.v2",
        "collection_id": collection_id,
        "objective_id": objective_id,
        "items": [
            {
                "sample_id": "sample-1",
                "objective_id": objective_id or "obj-1",
                "analysis_version": 1,
                "finding_id": "finding-1",
                "research_objective": "How does temperature affect strength?",
                "document_ids": ["paper-1"],
                "label_status": "gold",
                "dataset_use_status": "training_ready",
                "finding_fingerprint": "finding.v2:abc",
                "evidence_fingerprint": "evidence.v2:def",
                "system_prediction": finding,
                "expert_target": None,
                "training_target": finding,
                "evidence": [evidence],
                "training_schema_version": "objective_finding_training.v2",
                "training_prompt_version": "objective_finding_training_prompt.v2",
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


def _finding_record(statement: str = "Temperature affects strength.") -> dict:
    return Finding.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "analysis_version": 1,
            "finding_id": "finding-1",
            "statement": statement,
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "insufficient_confirmation",
            "certainty": 0.5,
            "display_rank": 0,
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [],
                "test": [],
            },
            "limitations": ["Supported by one paper."],
            "paper_contributions": [
                {
                    "document_id": "paper-1",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-1"],
                }
            ],
        }
    ).to_record()


def _evidence_record() -> dict:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "analysis_version": 1,
            "evidence_id": "evidence-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-7",
            "source_excerpt": "At 500 C, strength reached 620 MPa.",
            "page_numbers": [7],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 400,
                    "target_value": 500,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "400 C",
                "target_label": "500 C",
                "axis_names": ["temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "strength",
                "direction": "increase",
                "result_text": "Strength reached 620 MPa.",
            },
            "attribution_scope": "isolated_effect",
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    ).to_record()


def _client(service: _Service | None = None) -> TestClient:
    app = FastAPI()
    app.state.finding_feedback_service = service or _Service()
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


def test_feedback_api_rejects_inconsistent_status_and_issue() -> None:
    client = _client()

    correct_with_issue = client.post(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        json={
            "analysis_version": 1,
            "review_status": "correct",
            "issue_type": "evidence_not_grounded",
        },
    )
    partial_without_issue = client.post(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        json={
            "analysis_version": 1,
            "review_status": "partial",
            "issue_type": "none",
        },
    )

    assert correct_with_issue.status_code == 422
    assert partial_without_issue.status_code == 422


def test_curation_api_uses_finding_evidence_ids() -> None:
    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_finding": _finding_record("Narrower expert statement."),
        },
    )

    assert response.status_code == 200
    assert response.json()["curated_finding"]["paper_contributions"][0][
        "supporting_evidence_ids"
    ] == ["evidence-1"]


def test_curation_api_rejects_retired_finding_fields() -> None:
    curated_finding = _finding_record("Narrower expert statement.")
    curated_finding["finding_level"] = "paper"

    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_finding": curated_finding,
        },
    )

    assert response.status_code == 422


def test_curation_api_rejects_missing_canonical_finding_fields() -> None:
    curated_finding = _finding_record("Narrower expert statement.")
    curated_finding.pop("scientific_context")
    curated_finding["paper_contributions"][0].pop("context_evidence_ids")

    response = _client().put(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        json={
            "analysis_version": 1,
            "curated_status": "limited",
            "curated_finding": curated_finding,
        },
    )

    assert response.status_code == 422


def test_review_gets_reject_stale_analysis_version() -> None:
    client = _client()

    feedback = client.get(
        "/collections/col-1/objectives/obj-1/findings/finding-1/feedback",
        params={"analysis_version": 2},
    )
    curations = client.get(
        "/collections/col-1/objectives/obj-1/findings/finding-1/curation",
        params={"analysis_version": 2},
    )

    assert feedback.status_code == 409
    assert curations.status_code == 409


def test_training_jsonl_contains_messages_and_versioned_metadata() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "training_jsonl"},
    )

    assert response.status_code == 200
    row = response.json()
    assert "At 500 C" in row["messages"][0]["content"]
    assert row["metadata"]["analysis_version"] == 1


def test_training_jsonl_excludes_non_training_ready_samples() -> None:
    class _RejectedDatasetService(_Service):
        async def export_dataset(self, **kwargs):
            payload = await super().export_dataset(**kwargs)
            payload["items"][0]["label_status"] = "rejected"
            payload["items"][0]["dataset_use_status"] = "rejected"
            return payload

    response = _client(_RejectedDatasetService()).get(
        "/collections/col-1/objectives/obj-1/finding-dataset",
        params={"format": "training_jsonl"},
    )

    assert response.status_code == 200
    assert response.text == ""
