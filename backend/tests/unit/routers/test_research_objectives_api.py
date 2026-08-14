from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers.core import research_objectives
from controllers.core.research_objectives import router
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperStudyDisposition,
    PaperSkim,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage


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
            "source_relationship_ids": ["relationship-1"],
            "rank": 1,
            "confirmation_status": "confirmed",
            "active_analysis_version": 1,
            "published_analysis_version": 1,
        }
    )


def _analysis(*, status: str = "succeeded") -> ObjectiveAnalysis:
    analysis = ObjectiveAnalysis(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={"paper_framing": "paper_framing.v1"},
        stats=ExecutionStats(
            duration_ms=1250,
            model_usage=(
                ModelUsage("model-1", 2, TokenUsage(300, 50, 350)),
            ),
            prompt_versions={"paper_framing": "paper_framing.v1"},
        ),
        total_document_count=1,
    )
    if status == "queued":
        return analysis
    if status == "failed":
        return analysis.fail(
            error_code="analysis_dispatch_failed",
            error_message=(
                "Objective analysis could not be scheduled. Retry the analysis."
            ),
        )
    return analysis.start().succeed()


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
    def __init__(self, facts: ObjectiveFactSet | None = None) -> None:
        self.facts = facts or _default_objective_facts()

    def read(self, collection_id):
        return self.facts

    def list_objectives(self, collection_id):
        return self.facts.research_objectives


class _Service:
    def __init__(self, *, queued: bool = False) -> None:
        self.analysis_status = "queued" if queued else "succeeded"
        self.dispatch_failure_version: int | None = None

    def confirm_objective(self, collection_id, objective_id):
        return self.get_analysis_state(collection_id, objective_id)

    def queue_analysis(self, collection_id, objective_id):
        return self.get_analysis_state(collection_id, objective_id)

    def execute_queued_analysis(self, collection_id, objective_id, analysis_version):
        return self.get_analysis_state(collection_id, objective_id)

    def fail_analysis_dispatch(self, collection_id, objective_id, analysis_version):
        self.analysis_status = "failed"
        self.dispatch_failure_version = analysis_version
        return self.get_analysis_state(collection_id, objective_id)

    def get_analysis_state(self, collection_id, objective_id):
        return {
            "collection_id": collection_id,
            "objective": _objective(),
            "analysis": _analysis(status=self.analysis_status),
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


def _client(
    service: _Service | None = None,
    *,
    repository: _Repository | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.state.objective_repository = repository or _Repository()
    app.state.objective_analysis_service = service or _Service()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _ranked_objective(rank: int) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "objective_id": f"obj-{rank}",
            "question": f"How does variable {rank} affect outcome {rank}?",
            "variables": [f"variable {rank}"],
            "outcomes": [f"outcome {rank}"],
            "seed_document_ids": [f"paper-{rank}"],
            "confidence": 1 - rank / 100,
            "source_relationship_ids": [f"relationship-{rank}"],
            "rank": rank,
        }
    )


def _ranked_facts(count: int) -> ObjectiveFactSet:
    skims = tuple(
        PaperSkim.from_mapping(
            {
                "document_id": f"paper-{rank}",
                "studies": [
                    {
                        "study_id": f"study-{rank}",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "relationships": [
                            {
                                "relationship_id": f"relationship-{rank}",
                                "varied_factors": [f"variable {rank}"],
                                "outcome": f"outcome {rank}",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": f"block-{rank}",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        for rank in range(1, count + 1)
    )
    return ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=skims,
        research_objectives=tuple(
            _ranked_objective(rank) for rank in range(1, count + 1)
        ),
        study_dispositions=tuple(
            PaperStudyDisposition.from_mapping(
                {
                    "document_id": f"paper-{rank}",
                    "study_id": f"study-{rank}",
                    "relationship_id": f"relationship-{rank}",
                    "status": "promoted",
                    "objective_id": f"obj-{rank}",
                }
            )
            for rank in range(1, count + 1)
        ),
    )


def _default_objective_facts() -> ObjectiveFactSet:
    skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "studies": [
                {
                    "study_id": "study-1",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["Alloy A"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-1",
                            "varied_factors": ["temperature"],
                            "outcome": "strength",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "block-7"}
                            ],
                        }
                    ],
                }
            ],
        }
    )
    return ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=(skim,),
        research_objectives=(_objective(),),
        study_dispositions=(
            PaperStudyDisposition.from_mapping(
                {
                    "document_id": "paper-1",
                    "study_id": "study-1",
                    "relationship_id": "relationship-1",
                    "status": "promoted",
                    "objective_id": "obj-1",
                }
            ),
        ),
    )


def test_objective_list_returns_every_ranked_candidate_when_limit_is_omitted() -> None:
    repository = _Repository(_ranked_facts(8))

    response = _client(repository=repository).get("/collections/col-1/objectives")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert payload["offset"] == 0
    assert payload["limit"] is None
    assert [objective["objective_id"] for objective in payload["objectives"]] == [
        f"obj-{rank}" for rank in range(1, 9)
    ]
    assert [objective["rank"] for objective in payload["objectives"]] == list(
        range(1, 9)
    )


def test_objective_list_exposes_candidates_after_rank_six() -> None:
    repository = _Repository(_ranked_facts(8))

    response = _client(repository=repository).get(
        "/collections/col-1/objectives",
        params={"offset": 6, "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert [objective["objective_id"] for objective in payload["objectives"]] == [
        "obj-7",
        "obj-8",
    ]
    assert [objective["rank"] for objective in payload["objectives"]] == [7, 8]


def test_objective_list_hides_stale_objectives_from_an_unready_build() -> None:
    class UnreadyRepository(_Repository):
        def read(self, collection_id):
            return ObjectiveFactSet(
                research_objectives_ready=False,
                research_objectives=(_objective(),),
            )

        def list_objectives(self, collection_id):
            return ()

    response = _client(repository=UnreadyRepository()).get(
        "/collections/col-1/objectives"
    )

    assert response.status_code == 200
    assert response.json()["objectives"] == []
    assert response.json()["total"] == 0


def test_paper_study_inventory_preserves_relationships_dispositions_and_signals(
) -> None:
    skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": "study-1",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": "temperature series",
                    "material_scope": ["Alloy A"],
                    "process_context": ["heat treatment"],
                    "sample_context": ["dog-bone specimen"],
                    "test_context": ["room-temperature tensile test"],
                    "comparator": "400 C versus 500 C",
                    "fixed_conditions": ["30 minute hold"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-1",
                            "varied_factors": ["temperature"],
                            "outcome": "strength",
                            "confidence": 0.9,
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "block-7"}
                            ],
                        },
                        {
                            "relationship_id": "relationship-2",
                            "varied_factors": ["scan speed"],
                            "outcome": "porosity",
                            "confidence": 0.8,
                            "source_refs": [
                                {
                                    "source_kind": "table_row",
                                    "source_ref": "row-2",
                                }
                            ],
                        },
                    ],
                    "confidence": 0.9,
                },
            ],
            "unresolved_signals": [
                {
                    "signal_id": "signal-1",
                    "signal_type": "variable",
                    "label": "grain size",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": "microstructure series",
                    "material_scope": ["Alloy A"],
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "block-11"}
                    ],
                    "confidence": 0.7,
                    "reason": "no outcome signal was found in this paper",
                }
            ],
            "source_unit_coverage": [
                {
                    "source_unit_id": "results-1-source-1",
                    "window_id": "results-1",
                    "source_kind": "block",
                    "source_ref": "block-7",
                    "status": "relationship_emitted",
                },
                {
                    "source_unit_id": "results-1-source-2",
                    "window_id": "results-1",
                    "source_kind": "block",
                    "source_ref": "block-11",
                    "status": "unresolved_signal_emitted",
                },
                {
                    "source_unit_id": "results-1-source-3",
                    "window_id": "results-1",
                    "source_kind": "block",
                    "source_ref": "block-12",
                    "status": "no_study_signal",
                    "reason": "The unit contains only background context.",
                },
                {
                    "source_unit_id": "results-1-source-4",
                    "window_id": "results-1",
                    "source_kind": "table_row",
                    "source_ref": "row-3",
                    "status": "extraction_failed",
                    "reason": "The window response failed validation.",
                },
            ],
        }
    )
    repository = _Repository(
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(skim,),
            research_objectives=(_objective(),),
            study_dispositions=(
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": "paper-1",
                        "study_id": "study-1",
                        "relationship_id": "relationship-1",
                        "status": "promoted",
                        "objective_id": "obj-1",
                    }
                ),
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": "paper-1",
                        "study_id": "study-1",
                        "relationship_id": "relationship-2",
                        "status": "rejected",
                        "reason": "The relationship lacks a defensible comparison.",
                    }
                ),
            ),
        )
    )

    response = _client(repository=repository).get(
        "/collections/col-1/paper-study-inventory",
        params={"offset": 0, "limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 6
    assert payload["research_objectives_ready"] is True
    assert payload["coverage_complete"] is False
    assert payload["source_unit_coverage_counts"] == {
        "relationship_emitted": 1,
        "unresolved_signal_emitted": 1,
        "no_study_signal": 1,
        "extraction_failed": 1,
    }
    study, unresolved, *coverage = payload["items"]
    assert study["item_type"] == "paper_study"
    assert study["study_id"] == "study-1"
    assert study["experiment_label"] == "temperature series"
    promoted, rejected = study["relationships"]
    assert promoted["relationship_id"] == "relationship-1"
    assert promoted["disposition"] == {
        "status": "promoted",
        "objective_id": "obj-1",
        "reason": None,
    }
    assert promoted["source_refs"] == [
        {"source_kind": "block", "source_ref": "block-7"}
    ]
    assert rejected["relationship_id"] == "relationship-2"
    assert rejected["disposition"] == {
        "status": "rejected",
        "objective_id": None,
        "reason": "The relationship lacks a defensible comparison.",
    }
    assert rejected["source_refs"] == [
        {"source_kind": "table_row", "source_ref": "row-2"}
    ]
    assert unresolved["item_type"] == "unresolved_signal"
    assert unresolved["reason"] == (
        "no outcome signal was found in this paper"
    )
    assert unresolved["source_refs"] == [
        {"source_kind": "block", "source_ref": "block-11"}
    ]
    assert [item["item_type"] for item in coverage] == [
        "source_unit_coverage"
    ] * 4
    assert coverage[-1] == {
        "item_type": "source_unit_coverage",
        "document_id": "paper-1",
        "doc_role": "experimental",
        "source_unit_id": "results-1-source-4",
        "window_id": "results-1",
        "source_kind": "table_row",
        "source_ref": "row-3",
        "status": "extraction_failed",
        "reason": "The window response failed validation.",
    }

    second_page = _client(repository=repository).get(
        "/collections/col-1/paper-study-inventory",
        params={"offset": 1, "limit": 1},
    )

    assert second_page.status_code == 200
    second_page_payload = second_page.json()
    assert second_page_payload["total"] == 6
    assert second_page_payload["offset"] == 1
    assert second_page_payload["limit"] == 1
    assert second_page_payload["items"][0]["signal_id"] == "signal-1"


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
    assert submitted["args"] == ("col-1", "obj-1", 1)
    assert (
        submitted["callback"]
        == research_objectives._log_unexpected_analysis_failure
    )


def test_start_analysis_fails_queued_version_when_worker_submission_fails(
    monkeypatch,
) -> None:
    service = _Service(queued=True)

    def submit(*_args):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(
        research_objectives._objective_analysis_executor,
        "submit",
        submit,
    )

    response = _client(service, raise_server_exceptions=False).post(
        "/collections/col-1/objectives/obj-1/analysis"
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "objective_analysis_dispatch_failed"
    assert service.analysis_status == "failed"
    assert service.dispatch_failure_version == 1


def test_objective_api_exposes_definition_and_separate_analysis_state() -> None:
    response = _client().get("/collections/col-1/objectives/obj-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["objective"]["confirmation_status"] == "confirmed"
    assert payload["active_analysis"]["status"] == "succeeded"
    assert payload["published_analysis"]["analysis_version"] == 1
    assert payload["active_analysis"]["stats"] == {
        "duration_ms": 1250,
        "token_usage": {
            "input_tokens": 300,
            "output_tokens": 50,
            "total_tokens": 350,
        },
        "model_usage": [
            {
                "model_name": "model-1",
                "request_count": 2,
                "token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 50,
                    "total_tokens": 350,
                },
                "unreported_request_count": 0,
            }
        ],
        "unreported_request_count": 0,
        "prompt_versions": {"paper_framing": "paper_framing.v1"},
    }
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
