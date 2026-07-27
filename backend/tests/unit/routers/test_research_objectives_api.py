from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers.core.research_objectives import router
from domain.core import Finding, ObjectiveAnalysis, ObjectiveEvidence, ResearchObjective


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "process_axes": ["temperature"],
            "property_axes": ["strength"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
            "confirmation_status": "confirmed",
            "active_analysis_version": 1,
            "published_analysis_version": 1,
        }
    )


def _analysis() -> ObjectiveAnalysis:
    return ObjectiveAnalysis(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={},
        total_document_count=1,
    ).start().succeed()


def _finding() -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "analysis_version": 1,
            "finding_id": "finding-1",
            "finding_level": "paper",
            "statement": "Higher temperature was associated with greater strength.",
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "scope_summary": "Alloy A",
            "evidence_strength": "weak",
            "generalization_status": "paper_level_only",
            "paper_count": 1,
            "confidence": 0.8,
            "display_rank": 0,
            "relations": [
                {
                    "source_term": "temperature",
                    "relation_type": "associated_with",
                    "target_term": "strength",
                    "assertion_strength": "associative",
                    "supporting_evidence_ids": ["evidence-1"],
                }
            ],
            "context": {"supporting_evidence_ids": ["evidence-1"]},
            "derivation": {
                "synthesis_mode": "paper",
                "comparison_status": "insufficient_confirmation",
                "contributing_document_ids": ["paper-1"],
                "supporting_evidence_ids": ["evidence-1"],
                "rationale": "One paper reported the direct result.",
            },
        }
    )


def _evidence() -> ObjectiveEvidence:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "analysis_version": 1,
            "evidence_id": "evidence-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-7",
            "source_excerpt": "At 500 C, tensile strength increased to 620 MPa.",
            "page_numbers": [7],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "evidence_kind": "measurement",
            "property_normalized": "strength",
            "value_payload": {"value": 620},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


class _Repository:
    def list_objectives(self, collection_id):
        return (_objective(),)


class _Service:
    def confirm_objective(self, collection_id, objective_id):
        return self.get_analysis(collection_id, objective_id)

    def queue_analysis(self, collection_id, objective_id):
        return self.get_analysis(collection_id, objective_id)

    def run_analysis(self, collection_id, objective_id):
        return self.get_analysis(collection_id, objective_id)

    def get_analysis(self, collection_id, objective_id):
        return {
            "collection_id": collection_id,
            "objective": _objective(),
            "analysis": _analysis(),
            "published_analysis": _analysis(),
            "warnings": [],
        }

    def list_findings(self, collection_id, objective_id, **kwargs):
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "items": [_finding().to_record()],
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "total": 1,
        }

    def get_finding(self, collection_id, objective_id, finding_id, **kwargs):
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "finding": _finding().to_record(),
        }

    def list_evidence(self, collection_id, objective_id, **kwargs):
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "analysis_version": 1,
            "finding_id": kwargs["finding_id"],
            "items": [_evidence().to_record()],
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "total": 1,
        }


def _client() -> TestClient:
    app = FastAPI()
    app.state.objective_repository = _Repository()
    app.state.objective_analysis_service = _Service()
    app.include_router(router)
    return TestClient(app)


def test_objective_api_exposes_definition_and_separate_analysis_state() -> None:
    response = _client().get("/collections/col-1/objectives/obj-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["objective"]["confirmation_status"] == "confirmed"
    assert payload["active_analysis"]["status"] == "succeeded"
    assert payload["published_analysis"]["analysis_version"] == 1
    assert "status" not in payload["objective"]
    assert "understanding" not in payload


def test_finding_api_returns_canonical_finding_without_claim_identity() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/findings",
        params={"analysis_version": 1, "offset": 0, "limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["finding_id"] == "finding-1"
    assert payload["items"][0]["relations"][0]["relation_order"] == 0
    assert "claim_id" not in str(payload)
    assert "logic_chain_id" not in str(payload)


def test_evidence_api_returns_exact_source_excerpt_and_locator() -> None:
    response = _client().get(
        "/collections/col-1/objectives/obj-1/evidence",
        params={"analysis_version": 1, "finding_id": "finding-1"},
    )

    assert response.status_code == 200
    evidence = response.json()["items"][0]
    assert evidence["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert evidence["source_ref"] == "block-7"
    assert evidence["page_numbers"] == [7]
    assert "evidence_unit_id" not in evidence
