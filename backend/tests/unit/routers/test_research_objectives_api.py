from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers.core import research_objectives
from controllers.core.research_objectives import router
from domain.core import Finding, ObjectiveAnalysis, ObjectiveEvidence, ResearchObjective


def _objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
            "confirmation_status": "confirmed",
            "active_analysis_version": 1,
            "published_analysis_version": 1,
        }
    )


def _analysis(*, queued: bool = False) -> ObjectiveAnalysis:
    analysis = ObjectiveAnalysis(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={},
        total_document_count=1,
    )
    return analysis if queued else analysis.start().succeed()


def _finding() -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": "obj-1",
            "analysis_version": 1,
            "finding_id": "finding-1",
            "statement": "Higher temperature was associated with greater strength.",
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "insufficient_confirmation",
            "certainty": 0.5,
            "display_rank": 0,
            "mechanisms": [],
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
                "value": 620,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Tensile strength increased to 620 MPa.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [],
                "test": [],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


class _Repository:
    def list_objectives(self, collection_id):
        return (_objective(),)


class _Service:
    def __init__(self, *, queued: bool = False) -> None:
        self.queued = queued

    def confirm_objective(self, collection_id, objective_id):
        return self.get_analysis_state(collection_id, objective_id)

    def queue_analysis(self, collection_id, objective_id):
        return self.get_analysis_state(collection_id, objective_id)

    def execute_queued_analysis(self, collection_id, objective_id):
        return self.get_analysis_state(collection_id, objective_id)

    def get_analysis_state(self, collection_id, objective_id):
        return {
            "collection_id": collection_id,
            "objective": _objective(),
            "analysis": _analysis(queued=self.queued),
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


def _client(service: _Service | None = None) -> TestClient:
    app = FastAPI()
    app.state.objective_repository = _Repository()
    app.state.objective_analysis_service = service or _Service()
    app.include_router(router)
    return TestClient(app)


def test_start_analysis_dispatches_the_queued_worker(monkeypatch) -> None:
    service = _Service(queued=True)
    submitted: dict[str, object] = {}

    class _SubmittedFuture:
        def add_done_callback(self, callback) -> None:
            submitted["callback"] = callback

    def submit(function, *args):
        submitted["function"] = function
        submitted["args"] = args
        return _SubmittedFuture()

    monkeypatch.setattr(
        research_objectives._objective_analysis_executor,
        "submit",
        submit,
    )

    response = _client(service).post(
        "/collections/col-1/objectives/obj-1/analysis"
    )

    assert response.status_code == 200
    assert response.json()["active_analysis"]["status"] == "queued"
    assert submitted["function"] == service.execute_queued_analysis
    assert submitted["args"] == ("col-1", "obj-1")
    assert (
        submitted["callback"]
        == research_objectives._log_unexpected_analysis_failure
    )


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
    assert payload["items"][0]["factors"] == ["temperature"]
    assert payload["items"][0]["outcome"] == "strength"
    assert payload["items"][0]["paper_contributions"][0]["supporting_evidence_ids"] == [
        "evidence-1"
    ]
    assert "finding_level" not in str(payload)
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
