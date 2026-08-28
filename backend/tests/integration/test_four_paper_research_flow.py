from __future__ import annotations

import os
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from fastapi.testclient import TestClient

from application.core.document_profiles.schemas import StructuredDocumentProfile
from application.core.objectives.analysis.evidence_routing import (
    StructuredEvidenceSelection,
    StructuredEvidenceSelections,
)
from application.core.objectives.analysis.finding_synthesis import (
    StructuredFindingSynthesis,
    StructuredFindingSynthesisItem,
)
from application.core.objectives.analysis.source_extraction import (
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
)
from application.core.objectives.discovery.study_window import (
    StructuredExperimentalPaperMap,
    StructuredPaperResearchMap,
)
from tests.support.fake_domain_model_extractor import (
    FakeDomainModelExtractor,
    _input_payload,
)


API_PREFIX = "/api/v1"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "four_paper_research_flow"


class _FourPaperResearchModel(FakeDomainModelExtractor):
    """Deterministic scientific decisions at the external model boundary only."""

    model = "deterministic-four-paper-research-model"

    def __init__(self) -> None:
        self.finding_payloads: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[Any],
        parsed_validator: Any = None,
        **options: Any,
    ) -> Any:
        if response_model.__name__ != "_StructuredPaperFrameModelBatch":
            return super().complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                parsed_validator=parsed_validator,
                **options,
            )

        payload = _input_payload(user_prompt)
        paper = payload.get("paper") if isinstance(payload.get("paper"), dict) else {}
        prior = (
            payload.get("paper_prior")
            if isinstance(payload.get("paper_prior"), dict)
            else {}
        )
        source_labels = [
            str(source.get("label") or "")
            for source in payload.get("sources") or ()
            if isinstance(source, dict) and str(source.get("label") or "")
        ]
        prior_context = " ".join(
            str(value)
            for study in prior.get("studies") or ()
            if isinstance(study, dict)
            for value in study.get("process_context") or ()
        ).casefold()
        is_review = (
            str(paper.get("document_type") or "").casefold() == "review"
            or str(prior.get("doc_role") or "").casefold() == "review"
        )
        response = response_model(
            relevance="irrelevant" if is_review else "high",
            paper_role="review" if is_review else "primary_experiment",
            screening_note=(
                "Review used for navigation rather than primary evidence."
                if is_review
                else "Primary experiment reports the requested comparison."
            ),
            material_match=[] if is_review else ["Ti-6Al-4V"],
            changed_variables=[] if is_review else ["laser exposure condition"],
            measured_property_scope=[] if is_review else ["porosity"],
            test_environment_scope=(
                []
                if is_review
                else [
                    (
                        "stress-relieved"
                        if "stress-relief" in prior_context
                        else "as-built"
                    )
                ]
            ),
            relevant_source_labels=[] if is_review else source_labels,
            excluded_source_labels=source_labels if is_review else [],
        )
        if parsed_validator is not None:
            validated = parsed_validator(response)
            if validated is not None:
                response = validated
        return response

    def extract_document_profile(
        self,
        payload: dict[str, Any],
    ) -> StructuredDocumentProfile:
        title = str(payload.get("title") or payload.get("source_filename") or "")
        return StructuredDocumentProfile(
            doc_type="review" if "review" in title.casefold() else "experimental",
            parsing_warnings=[],
            confidence=0.95,
        )

    def extract(
        self,
        payload: dict[str, Any],
    ) -> StructuredExperimentalPaperMap | StructuredPaperResearchMap:
        title = str(payload.get("title") or "").casefold()
        source_text = " ".join(
            str(source.get("content") or "")
            for source in payload.get("sources") or ()
            if isinstance(source, dict)
        )
        source_labels = [
            str(source.get("label") or "")
            for source in payload.get("sources") or ()
            if isinstance(source, dict) and str(source.get("label") or "")
        ]
        document_type = str(payload.get("document_type") or "").casefold()
        if document_type == "review" or "review" in title:
            return StructuredPaperResearchMap(
                doc_role="review",
                studies=[],
                unresolved_signals=[],
                evidence_density="low",
                confidence=0.9,
                warnings=[],
            )

        paper_kind = (
            "stress_relaxed" if "stress-relief" in source_text.casefold() else "as_built"
        )
        studies: list[dict[str, Any]] = []
        if "decreased porosity from" in source_text.casefold() and source_labels:
            studies = [
                {
                    "experiment_label": "LPBF exposure-condition experiment",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["Ti-6Al-4V"],
                    "process_context": [
                        "LPBF",
                        (
                            "stress-relief annealing"
                            if paper_kind == "stress_relaxed"
                            else "as-built"
                        ),
                    ],
                    "relationships": [
                        {
                            "varied_factors": ["laser exposure condition"],
                            "outcome": "porosity",
                            "source_labels": source_labels,
                            "confidence": 0.94,
                        }
                    ],
                    "confidence": 0.94,
                }
            ]
        return StructuredExperimentalPaperMap(
            doc_role="experimental",
            studies=studies,
            unresolved_signals=[],
            evidence_density="high" if studies else "medium",
            confidence=0.94 if studies else 0.75,
            warnings=[],
        )

    def route_source(self, payload: dict[str, Any]) -> StructuredEvidenceSelections:
        source = payload.get("current_source") or {}
        if not isinstance(source, dict) or not source.get("source_ref"):
            return StructuredEvidenceSelections()
        text = str(source.get("text_hint") or "").casefold()
        return StructuredEvidenceSelections(
            selections=[
                StructuredEvidenceSelection(
                    role=(
                        "current_experimental_evidence"
                        if "decreased porosity from" in text
                        else "process_or_treatment"
                    ),
                    extractable=True,
                    confidence=0.92,
                )
            ]
        )

    def extract_source(self, payload: dict[str, Any]) -> StructuredEvidenceExtractions:
        source = payload.get("source") or {}
        text = str(source.get("text") or "").strip()
        lowered = text.casefold()
        if "decreased porosity from" not in lowered:
            return StructuredEvidenceExtractions()

        stress_relaxed = "stress-relieved sample state" in lowered
        values = (1.5, 0.6) if stress_relaxed else (1.9, 0.7)
        if "2.4%" in text:
            values = (2.4, 0.8)
        return StructuredEvidenceExtractions(
            extractions=[
                StructuredEvidenceExtraction(
                    evidence_role="direct_result",
                    changed_variables=[
                        {
                            "name": "laser exposure condition",
                            "baseline_value": "low exposure",
                            "target_value": "high exposure",
                        }
                    ],
                    comparison={
                        "baseline_label": "low exposure",
                        "target_label": "high exposure",
                        "axis_names": ["laser exposure condition"],
                        "comparable": True,
                        "incomparability_reasons": [],
                    },
                    reported_result={
                        "outcome": "porosity",
                        "value": values[1],
                        "baseline_value": values[0],
                        "target_value": values[1],
                        "unit": "%",
                        "direction": "decrease",
                        "result_text": text,
                    },
                    attribution_scope="isolated_effect",
                    scientific_context={
                        "material": [{"name": "alloy", "value": "Ti-6Al-4V"}],
                        "sample": [
                            {
                                "name": "sample state",
                                "value": (
                                    "stress-relieved" if stress_relaxed else "as-built"
                                ),
                            }
                        ],
                        "process": [{"name": "process", "value": "LPBF"}],
                        "test": [
                            {
                                "name": "method",
                                "value": "X-ray computed tomography",
                            }
                        ],
                    },
                    resolution_status="resolved",
                    confidence=0.93,
                )
            ]
        )

    def judge_result_set(
        self,
        payload: dict[str, Any],
    ) -> StructuredFindingSynthesis:
        self.finding_payloads.append(payload)
        document_ids = {
            str(item.get("document_id") or "")
            for item in (payload.get("result_set") or {}).get(
                "document_evidence_summaries", []
            )
            if isinstance(item, dict)
        }
        if len(document_ids) < 2:
            return StructuredFindingSynthesis()
        return StructuredFindingSynthesis(
            findings=[
                StructuredFindingSynthesisItem(
                    assertion_strength="associative",
                    context_evidence_ids=[],
                    mechanisms=[],
                )
            ]
        )


def _wait_for_task(client: TestClient, task_id: str) -> dict[str, Any]:
    deadline = monotonic() + 20
    while monotonic() < deadline:
        response = client.get(f"{API_PREFIX}/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["status"] not in {"queued", "running"}:
            return task
        sleep(0.02)
    raise AssertionError(f"task did not finish: {task_id}")


def _wait_for_analysis(
    client: TestClient,
    collection_id: str,
    objective_id: str,
) -> dict[str, Any]:
    deadline = monotonic() + 20
    path = f"{API_PREFIX}/collections/{collection_id}/objectives/{objective_id}/analysis"
    while monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200
        analysis = response.json()
        active = analysis.get("active_analysis")
        if active is not None and active["status"] not in {"queued", "running"}:
            return analysis
        sleep(0.02)
    raise AssertionError(f"analysis did not finish: {objective_id}")


def test_four_paper_research_flow_publishes_only_context_compatible_evidence(
    postgres_sync_engine,
    monkeypatch,
    tmp_path,
) -> None:
    del postgres_sync_engine
    test_database_url = os.environ["LENS_TEST_DATABASE_URL"]
    monkeypatch.setenv("LENS_DATABASE_URL", test_database_url)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "four-paper@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "test-password")
    monkeypatch.setattr("infra.persistence.file.collection_workspace.DATA_DIR", tmp_path)

    from main import create_app

    model = _FourPaperResearchModel()
    with TestClient(create_app(chat_session_service=object())) as client:
        client.app.state.document_profile_service._document_profile_extractor = model
        client.app.state.document_preparation_service._response_client = model
        research_service = client.app.state.research_objective_service
        research_service._response_client = model
        research_service.finding_synthesis_service.assertion_judge = model

        login = client.post(
            f"{API_PREFIX}/auth/login",
            json={
                "email": "four-paper@example.com",
                "password": "test-password",
            },
        )
        assert login.status_code == 200

        created = client.post(
            f"{API_PREFIX}/collections",
            json={
                "name": "Ti-6Al-4V laser exposure comparison",
                "description": "Four-paper deterministic research-chain acceptance.",
            },
        )
        assert created.status_code == 200
        collection_id = created.json()["collection_id"]

        document_ids_by_filename: dict[str, str] = {}
        for fixture_path in sorted(FIXTURE_DIR.glob("*.txt")):
            uploaded = client.post(
                f"{API_PREFIX}/collections/{collection_id}/documents",
                files={
                    "file": (
                        fixture_path.name,
                        fixture_path.read_bytes(),
                        "text/plain",
                    )
                },
            )
            assert uploaded.status_code == 200
            document_id = uploaded.json()["document_id"]
            document_ids_by_filename[fixture_path.name] = document_id
            queued = client.post(
                f"{API_PREFIX}/collections/{collection_id}/documents/"
                f"{document_id}/preparation",
                json={"mode": "standard"},
            )
            assert queued.status_code == 200

        task_history = client.get(
            f"{API_PREFIX}/collections/{collection_id}/tasks",
            params={"limit": 20},
        )
        assert task_history.status_code == 200
        for task in task_history.json()["items"]:
            completed_task = _wait_for_task(client, task["task_id"])
            assert completed_task["status"] == "completed", completed_task

        document_ids = tuple(document_ids_by_filename.values())
        collection = client.get(f"{API_PREFIX}/collections/{collection_id}")
        assert collection.status_code == 200
        assert {item["status"] for item in collection.json()["documents"]} == {
            "ready"
        }

        discovered = client.post(
            f"{API_PREFIX}/collections/{collection_id}/objective-discovery",
            json={"document_ids": list(document_ids)},
        )
        assert discovered.status_code == 200, discovered.text
        objectives = discovered.json()["objectives"]
        objective = next(
            item
            for item in objectives
            if item["variables"] == ["laser exposure condition"]
            and item["outcomes"] == ["porosity"]
        )
        objective_id = objective["objective_id"]

        queued_analysis = client.post(
            f"{API_PREFIX}/collections/{collection_id}/objectives/"
            f"{objective_id}/analysis",
            json={"document_ids": list(document_ids)},
        )
        assert queued_analysis.status_code == 200, queued_analysis.text
        analysis = _wait_for_analysis(client, collection_id, objective_id)
        assert analysis["published_analysis"]["status"] == "succeeded", analysis

        paper_a_id = document_ids_by_filename["paper-a-as-built.txt"]
        paper_b_id = document_ids_by_filename["paper-b-as-built.txt"]
        paper_c_id = document_ids_by_filename["paper-c-stress-relieved.txt"]
        review_id = document_ids_by_filename["paper-d-review.txt"]
        evidence = client.get(
            f"{API_PREFIX}/collections/{collection_id}/objectives/{objective_id}/evidence"
        )
        assert evidence.status_code == 200
        direct_evidence = [
            item
            for item in evidence.json()["items"]
            if item["reported_result"] is not None
        ]
        assert {item["document_id"] for item in direct_evidence} == {
            paper_a_id,
            paper_b_id,
            paper_c_id,
        }
        sample_states_by_document = {
            document_id: {
                str(attribute["value"])
                for item in direct_evidence
                if item["document_id"] == document_id
                for attribute in item["scientific_context"]["sample"]
                if attribute["name"] == "sample state"
            }
            for document_id in (paper_a_id, paper_b_id, paper_c_id)
        }
        assert sample_states_by_document == {
            paper_a_id: {"as-built"},
            paper_b_id: {"as-built"},
            paper_c_id: {"stress-relieved"},
        }

        findings = client.get(
            f"{API_PREFIX}/collections/{collection_id}/objectives/{objective_id}/findings"
        )
        assert findings.status_code == 200
        assert findings.json()["total"] == 1
        finding = findings.json()["items"][0]

        finding_contributions = {
            item["document_id"]: item for item in finding["paper_contributions"]
        }
        assert set(finding_contributions) == {
            paper_a_id,
            paper_b_id,
            paper_c_id,
            review_id,
        }
        assert finding_contributions[paper_a_id]["supporting_evidence_ids"]
        assert finding_contributions[paper_b_id]["supporting_evidence_ids"]
        assert not finding_contributions[paper_c_id]["supporting_evidence_ids"]
        assert finding_contributions[review_id]["analysis_status"] == "excluded"
        assert not finding_contributions[review_id]["supporting_evidence_ids"]

        contributions = {
            item["document_id"]: item for item in analysis["paper_contributions"]
        }
        assert contributions[paper_c_id]["analysis_status"] == "analyzed"
        assert contributions[review_id]["analysis_status"] == "excluded"
        assert contributions[review_id]["paper_role"] == "review"

        for item in direct_evidence:
            document_content = client.get(
                f"{API_PREFIX}/collections/{collection_id}/documents/"
                f"{item['document_id']}/content"
            )
            assert document_content.status_code == 200
            assert item["source_excerpt"] in document_content.json()["content_text"]
            assert item["source_ref"]

        published_again = client.get(
            f"{API_PREFIX}/collections/{collection_id}/objectives/"
            f"{objective_id}/analysis"
        )
        assert published_again.status_code == 200
        assert published_again.json()["published_analysis"] == analysis[
            "published_analysis"
        ]
        assert any(
            {
                str(item.get("document_id") or "")
                for item in payload["result_set"]["document_evidence_summaries"]
            }
            == {paper_c_id}
            for payload in model.finding_payloads
        )
