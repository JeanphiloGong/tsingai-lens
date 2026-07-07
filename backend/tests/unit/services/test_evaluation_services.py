from __future__ import annotations

import pytest

from application.evaluation.core_evaluation_service import CoreEvaluationService
from application.evaluation.gold_service import EvaluationGoldService
from application.evaluation.prediction_snapshot_service import (
    CoreArtifactsNotReadyForEvaluationError,
    EvaluationPredictionSnapshotService,
)
from application.evaluation.research_understanding_feedback_service import (
    ResearchUnderstandingFeedbackService,
)
from domain.core import (
    CoreFactSet,
    MeasurementResult,
    ObjectiveEvidenceUnit,
    ResearchUnderstanding,
)
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback


class FakeCollectionService:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or {"col-gold"}
        self.files_by_collection = {
            "col-gold": [
                {
                    "file_id": "file-1",
                    "source_document_id": "doc-1",
                    "document_id": "doc-1",
                    "original_filename": "paper-1.pdf",
                    "stored_filename": "paper-1.pdf",
                }
            ]
        }

    def get_collection(self, collection_id: str) -> dict:
        if collection_id not in self.existing:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return {"collection_id": collection_id, "name": "Gold collection"}

    def list_files(self, collection_id: str) -> list[dict]:
        self.get_collection(collection_id)
        return list(self.files_by_collection.get(collection_id, []))

    def get_import_manifest(self, collection_id: str) -> dict:
        self.get_collection(collection_id)
        return {
            "schema_version": 1,
            "collection_id": collection_id,
            "handoffs": [],
            "imports": [
                {
                    "documents": [
                        {
                            "source_document_id": "doc-1",
                            "original_filename": "paper-1.pdf",
                            "stored_filename": "paper-1.pdf",
                        }
                    ]
                }
            ],
        }


class FakeEvaluationRepository:
    backend_name = "fake"

    def __init__(self) -> None:
        self.gold_set = None
        self.gold_items = ()
        self.snapshot = None
        self.run = None

    def upsert_gold_set(self, gold_set, gold_items) -> None:
        self.gold_set = gold_set
        self.gold_items = gold_items

    def read_gold_set(self, gold_id: str):
        if self.gold_set and self.gold_set.gold_id == gold_id:
            return self.gold_set
        return None

    def list_gold_items(self, gold_id: str):  # noqa: ARG002
        return self.gold_items

    def upsert_prediction_snapshot(self, snapshot) -> None:
        self.snapshot = snapshot

    def read_prediction_snapshot(self, snapshot_id: str):
        if self.snapshot and self.snapshot.snapshot_id == snapshot_id:
            return self.snapshot
        return None

    def upsert_evaluation_run(self, run) -> None:
        self.run = run

    def list_research_understanding_curations(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ):
        return tuple(
            curation
            for curation in getattr(self, "curations", ())
            if curation.collection_id == collection_id
            and (scope_type is None or curation.scope_type == scope_type)
            and (scope_id is None or curation.scope_id == scope_id)
            and (finding_id is None or curation.finding_id == finding_id)
            and (claim_id is None or curation.claim_id == claim_id)
        )

    def list_research_understanding_feedback(
        self,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ):
        return tuple(
            feedback
            for feedback in getattr(self, "feedback", ())
            if feedback.collection_id == collection_id
            and (scope_type is None or feedback.scope_type == scope_type)
            and (scope_id is None or feedback.scope_id == scope_id)
            and (finding_id is None or feedback.finding_id == finding_id)
            and (claim_id is None or feedback.claim_id == claim_id)
        )


class FakeCoreFactRepository:
    backend_name = "fake"

    def __init__(self, facts: CoreFactSet) -> None:
        self.facts = facts

    def read_collection_facts(self, collection_id: str) -> CoreFactSet:  # noqa: ARG002
        return self.facts

    def read_research_understanding(
        self,
        collection_id: str,
        scope_type: str,
        scope_id: str,
    ):
        return None


class FakeResearchUnderstandingRepository:
    backend_name = "fake"

    def __init__(self, understanding: ResearchUnderstanding | None) -> None:
        self.understanding = understanding

    def read_research_understanding(
        self,
        collection_id: str,  # noqa: ARG002
        scope_type: str,  # noqa: ARG002
        scope_id: str,  # noqa: ARG002
    ):
        return self.understanding


def _sample_understanding() -> ResearchUnderstanding:
    return ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-gold",
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
                },
                {
                    "claim_id": "claim-2",
                    "claim_type": "finding",
                    "statement": "VED controls density.",
                    "status": "limited",
                    "evidence_ref_ids": ["ev-2"],
                    "context_ids": ["ctx-1"],
                },
                {
                    "claim_id": "claim-3",
                    "claim_type": "finding",
                    "statement": "Porosity governs pitting.",
                    "status": "limited",
                    "evidence_ref_ids": ["ev-3"],
                    "context_ids": ["ctx-2"],
                },
                {
                    "claim_id": "claim-4",
                    "claim_type": "finding",
                    "statement": "Heat treatment controls fatigue.",
                    "status": "limited",
                    "evidence_ref_ids": ["ev-4"],
                    "context_ids": ["ctx-2"],
                },
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
                },
                {
                    "evidence_ref_id": "ev-2",
                    "source_kind": "table",
                    "document_id": "doc-2",
                    "label": "P002 Table 2",
                    "locator": {"source_ref": "table-density"},
                    "traceability_status": "direct",
                    "evidence_role": "direct_result",
                    "quote": "Density reached 99.6%.",
                },
                {
                    "evidence_ref_id": "ev-3",
                    "source_kind": "text",
                    "document_id": "doc-3",
                    "label": "P003 Corrosion",
                    "locator": {"source_ref": "blk-pitting"},
                    "traceability_status": "direct",
                    "evidence_role": "direct_result",
                    "quote": "Pores acted as pitting sites.",
                },
                {
                    "evidence_ref_id": "ev-4",
                    "source_kind": "text",
                    "document_id": "doc-4",
                    "label": "P004 Fatigue",
                    "locator": {"source_ref": "blk-fatigue"},
                    "traceability_status": "direct",
                    "evidence_role": "background",
                    "quote": "Fatigue was discussed in a review section.",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx-1",
                    "label": "LPBF 316L",
                    "material_scope": ["316L"],
                    "process_context": {"process": "LPBF"},
                    "test_condition": {"temperature": "room"},
                    "property_scope": ["ductility", "density"],
                },
                {
                    "context_id": "ctx-2",
                    "label": "SLM corrosion",
                    "material_scope": ["316L"],
                    "process_context": {"process": "SLM"},
                    "test_condition": {"solution": "NaCl"},
                    "property_scope": ["corrosion"],
                },
            ],
            "presentation": {
                "findings": [
                    {
                        "finding_id": "finding-1",
                        "claim_id": "claim-1",
                        "title": "preheating -> ductility",
                        "statement": "Preheating improves ductility.",
                        "variables": ["preheating"],
                        "mediators": ["porosity"],
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
                        "relation_ids": ["rel-1"],
                    },
                    {
                        "finding_id": "finding-2",
                        "claim_id": "claim-2",
                        "title": "VED -> density",
                        "statement": "VED controls density.",
                        "variables": ["VED"],
                        "outcomes": ["density"],
                        "direction": "increase",
                        "scope_summary": "SLM 316L",
                        "support_grade": "weak",
                        "review_status": "needs_review",
                        "confidence": 0.6,
                        "paper_count": 1,
                        "evidence_count": 1,
                        "evidence_ref_ids": ["ev-2"],
                        "context_ids": ["ctx-1"],
                    },
                    {
                        "finding_id": "finding-3",
                        "claim_id": "claim-3",
                        "title": "porosity -> pitting",
                        "statement": "Porosity governs pitting.",
                        "variables": ["porosity"],
                        "outcomes": ["pitting corrosion"],
                        "direction": "increase",
                        "scope_summary": "SLM 316L",
                        "support_grade": "partial",
                        "review_status": "needs_review",
                        "confidence": 0.6,
                        "paper_count": 1,
                        "evidence_count": 1,
                        "evidence_ref_ids": ["ev-3"],
                        "context_ids": ["ctx-2"],
                    },
                    {
                        "finding_id": "finding-4",
                        "claim_id": "claim-4",
                        "title": "heat treatment -> fatigue",
                        "statement": "Heat treatment controls fatigue.",
                        "variables": ["heat treatment"],
                        "outcomes": ["fatigue"],
                        "direction": "unclear",
                        "scope_summary": "review context",
                        "support_grade": "weak",
                        "review_status": "needs_review",
                        "confidence": 0.4,
                        "paper_count": 1,
                        "evidence_count": 1,
                        "evidence_ref_ids": ["ev-4"],
                        "context_ids": ["ctx-2"],
                    },
                ],
                "evidence_items": [
                    {
                        "evidence_ref_id": "ev-1",
                        "document_id": "doc-1",
                        "title": "P001 Results",
                        "source_label": "P001 p.3",
                        "source_kind": "text",
                        "source_ref": "blk-preheat",
                        "block_type": "paragraph",
                        "heading_path": "Results / Mechanical properties",
                        "page": "3",
                        "quote": "Preheating increased ductility by 14%.",
                        "source_text": "Preheating increased ductility by 14% in LPBF 316L.",
                        "value_summary": "ductility +14%",
                        "traceability_status": "direct",
                        "evidence_role": "direct_result",
                        "confidence": 0.82,
                        "href": "/documents/doc-1#blk-preheat",
                    }
                ],
                "context_summaries": [
                    {
                        "context_id": "ctx-1",
                        "label": "LPBF 316L",
                        "material_scope": ["316L"],
                        "property_scope": ["ductility", "density"],
                        "process_summary": "LPBF",
                        "test_summary": "room temperature",
                        "limitations": [],
                    }
                ],
            },
            "model_traces": [
                {
                    "trace_id": "rut-1",
                    "task_type": "research_understanding_relation",
                    "prompt_version": "research_understanding_relation.v1",
                    "model": "fake-model",
                    "extraction_mode": "provider_parse",
                    "response_model": "StructuredResearchUnderstandingRelations",
                    "trace_status": "available",
                    "source_object_ids": ["oeu-preheat"],
                    "input_blocks": [
                        {
                            "source_object_id": "oeu-preheat",
                            "source_kind": "objective_evidence_unit",
                        }
                    ],
                    "raw_output": "{\"relations\": []}",
                    "parsed_output": {"relations": []},
                }
            ],
        }
    )


def test_evaluation_gold_service_registers_gold_set_for_collection():
    repository = FakeEvaluationRepository()
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )

    gold_set = service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        items=[
            {
                "gold_item_id": "gold-1",
                "document_id": "doc-1",
                "family": "measurement_results",
                "item_key": "doc-1:sample-a:yield_strength",
                "payload": {"metric": "yield_strength", "value": 520, "unit": "MPa"},
            }
        ],
    )

    assert repository.gold_set == gold_set
    assert repository.gold_items[0].gold_id == "gold-v1"
    assert repository.gold_items[0].payload["value"] == 520


def test_evaluation_gold_service_rejects_missing_collection():
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(existing=set()),
        evaluation_repository=FakeEvaluationRepository(),
    )

    with pytest.raises(FileNotFoundError):
        service.register_gold_set(
            collection_id="missing",
            gold_id="gold-v1",
            items=[],
        )


def test_evaluation_gold_service_rejects_gold_item_outside_collection():
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=FakeEvaluationRepository(),
    )

    with pytest.raises(ValueError, match="gold item document is not in collection"):
        service.register_gold_set(
            collection_id="col-gold",
            gold_id="gold-v1",
            items=[
                {
                    "gold_item_id": "gold-1",
                    "document_id": "doc-outside",
                    "family": "measurement_results",
                    "item_key": "doc-outside:sample-a:yield_strength",
                    "payload": {
                        "metric": "yield_strength",
                        "value": 520,
                        "unit": "MPa",
                    },
                }
            ],
        )


def test_research_understanding_feedback_service_exports_curation_gold_draft():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-abc123",
                "collection_id": "col-gold",
                "scope_type": "objective",
                "scope_id": "obj-1",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "curated_claim_type": "mechanism",
                "curated_status": "limited",
                "curated_statement": "Annealing mechanism evidence remains limited.",
                "curated_support_grade": "weak",
                "curated_review_status": "needs_review",
                "curated_variables": ["annealing"],
                "curated_mediators": ["cellular substructure"],
                "curated_outcomes": ["yield strength"],
                "curated_direction": "explains",
                "curated_scope_summary": "LPBF 316L",
                "curated_evidence_ref_ids": ["ev-1", "ev-2"],
                "curated_context_ids": ["ctx-1"],
                "note": "Needs microstructure evidence.",
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T09:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(evaluation_repository=repository)

    draft = service.export_gold_draft(
        collection_id="col-gold",
        scope_type="objective",
        scope_id="obj-1",
    )

    assert draft["gold_id"] == "gold_col-gold_objective_obj-1_research_understanding"
    assert draft["metric_profile"] == "research_understanding_v1"
    assert draft["item_count"] == 1
    item = draft["items"][0]
    assert item["family"] == "research_understanding_findings"
    assert item["item_key"] == "objective:obj-1:finding-1"
    assert item["payload"] == {
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "claim_type": "mechanism",
        "status": "limited",
        "statement": "Annealing mechanism evidence remains limited.",
        "support_grade": "weak",
        "review_status": "needs_review",
        "variables": ["annealing"],
        "mediators": ["cellular substructure"],
        "outcomes": ["yield strength"],
        "direction": "explains",
        "scope_summary": "LPBF 316L",
        "evidence_ref_ids": ["ev-1", "ev-2"],
        "context_ids": ["ctx-1"],
    }
    assert item["evidence_refs"] == [
        {"evidence_ref_id": "ev-1"},
        {"evidence_ref_id": "ev-2"},
    ]
    assert item["metadata"]["curation_id"] == "ruc-abc123"


def test_research_understanding_feedback_service_exports_dataset_samples():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-1",
                "collection_id": "col-gold",
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
                "curated_mediators": ["porosity"],
                "curated_outcomes": ["ductility"],
                "curated_direction": "increase",
                "curated_scope_summary": "LPBF 316L",
                "curated_evidence_ref_ids": ["ev-1"],
                "curated_context_ids": ["ctx-1"],
                "note": "Quote supports the result.",
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T09:00:00+00:00",
            }
        ),
    )
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-partial",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "review_status": "partial",
                "issue_type": "none",
                "note": "Density trend needs one more source.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-wrong",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-3",
                "claim_id": "claim-3",
                "review_status": "incorrect",
                "issue_type": "evidence_not_grounded",
                "note": "The quote does not support a causal corrosion claim.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:30:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    assert dataset["schema_version"] == "research_understanding_dataset.v1"
    assert dataset["task_type"] == "research_understanding_finding"
    assert dataset["item_count"] == 4
    assert dataset["label_counts"] == {
        "candidate": 1,
        "silver": 1,
        "gold": 1,
        "rejected": 1,
    }
    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    assert by_finding["finding-1"]["label_status"] == "gold"
    assert by_finding["finding-1"]["expert_target"]["source"] == "curation"
    assert by_finding["finding-1"]["expert_target"]["statement"] == (
        "Preheating improves ductility by 14% in LPBF 316L."
    )
    assert by_finding["finding-1"]["evidence_refs"][0]["source_text"] == (
        "Preheating increased ductility by 14% in LPBF 316L."
    )
    assert by_finding["finding-1"]["evidence_refs"][0]["heading_path"] == (
        "Results / Mechanical properties"
    )
    assert by_finding["finding-1"]["context_refs"][0]["process_summary"] == "LPBF"
    assert by_finding["finding-1"]["trace_status"] == "available"
    assert by_finding["finding-1"]["prompt_version"] == (
        "research_understanding_relation.v1"
    )
    assert by_finding["finding-1"]["input_blocks"] == [
        {
            "source_object_id": "oeu-preheat",
            "source_kind": "objective_evidence_unit",
        }
    ]
    assert by_finding["finding-1"]["model_output"]["trace_id"] == "rut-1"
    assert by_finding["finding-1"]["model_output"]["parsed_output"] == {
        "relations": []
    }
    assert by_finding["finding-2"]["label_status"] == "silver"
    assert by_finding["finding-3"]["label_status"] == "rejected"
    assert by_finding["finding-4"]["label_status"] == "candidate"
    assert by_finding["finding-4"]["trace_status"] == "unavailable"


def test_research_understanding_feedback_service_filters_dataset_by_label():
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-wrong",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-3",
                "claim_id": "claim-3",
                "review_status": "incorrect",
                "issue_type": "wrong_relation",
                "created_at": "2026-06-18T10:30:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
        label_status="rejected",
    )

    assert dataset["label_status_filter"] == "rejected"
    assert dataset["item_count"] == 1
    assert dataset["items"][0]["finding_id"] == "finding-3"
    assert dataset["label_counts"] == {
        "candidate": 0,
        "silver": 0,
        "gold": 0,
        "rejected": 1,
    }


def test_research_understanding_feedback_service_reports_missing_dataset_scope():
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=FakeEvaluationRepository(),
        core_fact_repository=FakeResearchUnderstandingRepository(None),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="missing-goal",
    )

    assert dataset["item_count"] == 0
    assert dataset["warnings"] == ["research understanding artifact is not available"]


def test_prediction_snapshot_service_exports_objective_first_measurements():
    repository = FakeEvaluationRepository()
    service = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        core_fact_repository=FakeCoreFactRepository(
            CoreFactSet(
                objective_evidence_units=(
                    ObjectiveEvidenceUnit.from_mapping(
                        {
                            "evidence_unit_id": "oeu-1",
                            "objective_id": "obj-1",
                            "document_id": "doc-1",
                            "unit_kind": "measurement",
                            "sample_context": {"sample": "sample-a"},
                            "property_normalized": "yield_strength",
                            "value_payload": {"value": 520},
                            "unit": "MPa",
                            "source_refs": [{"source_kind": "table", "source_ref": "t1"}],
                            "confidence": 0.9,
                            "resolution_status": "resolved",
                        }
                    ),
                )
            )
        ),
        evaluation_repository=repository,
    )

    snapshot = service.create_core_snapshot(
        collection_id="col-gold",
        fact_source="objective_first",
        snapshot_id="snapshot-1",
        system_context={"model": "qwen"},
    )

    assert repository.snapshot == snapshot
    assert snapshot.artifact_counts["objective_evidence_units"] == 1
    assert snapshot.items[0].family == "measurement_results"
    assert snapshot.items[0].item_key == "doc-1:sample-a:yield_strength"
    assert snapshot.items[0].payload["value"] == 520.0


def test_prediction_snapshot_service_exports_paper_fact_measurements():
    repository = FakeEvaluationRepository()
    service = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        core_fact_repository=FakeCoreFactRepository(
            CoreFactSet(
                measurement_results=(
                    MeasurementResult.from_mapping(
                        {
                            "result_id": "res-1",
                            "document_id": "doc-1",
                            "collection_id": "col-gold",
                            "variant_id": "sample-a",
                            "property_normalized": "yield_strength",
                            "value_payload": {"numeric_value": 520},
                            "unit": "MPa",
                            "evidence_anchor_ids": ["anc-1"],
                            "traceability_status": "direct",
                            "result_source_type": "table",
                        }
                    ),
                )
            )
        ),
        evaluation_repository=repository,
    )

    snapshot = service.create_core_snapshot(
        collection_id="col-gold",
        fact_source="paper_facts",
        snapshot_id="snapshot-1",
    )

    assert snapshot.items[0].item_id == "res-1"
    assert snapshot.items[0].payload["sample"] == "sample-a"
    assert snapshot.items[0].source_refs == ({"anchor_id": "anc-1"},)


def test_prediction_snapshot_service_reports_not_ready_when_no_items():
    service = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        core_fact_repository=FakeCoreFactRepository(CoreFactSet()),
        evaluation_repository=FakeEvaluationRepository(),
    )

    with pytest.raises(CoreArtifactsNotReadyForEvaluationError):
        service.create_core_snapshot(collection_id="col-gold")


def test_prediction_snapshot_service_allows_empty_ready_core_outputs():
    repository = FakeEvaluationRepository()
    service = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        core_fact_repository=FakeCoreFactRepository(
            CoreFactSet(research_objectives_ready=True)
        ),
        evaluation_repository=repository,
    )

    snapshot = service.create_core_snapshot(
        collection_id="col-gold",
        fact_source="objective_first",
        snapshot_id="snapshot-empty",
    )

    assert repository.snapshot == snapshot
    assert snapshot.items == ()
    assert snapshot.artifact_counts["objective_evidence_units"] == 0


def test_core_evaluation_service_scores_matching_measurements():
    repository = FakeEvaluationRepository()
    gold_service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )
    gold_service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        items=[
            {
                "gold_item_id": "gold-1",
                "document_id": "doc-1",
                "family": "measurement_results",
                "item_key": "doc-1:sample-a:yield_strength",
                "payload": {
                    "sample": "sample-a",
                    "metric": "yield_strength",
                    "value": 520,
                    "unit": "MPa",
                },
                "evidence_refs": [{"quote": "520 MPa"}],
            }
        ],
    )
    snapshot_service = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        core_fact_repository=FakeCoreFactRepository(
            CoreFactSet(
                objective_evidence_units=(
                    ObjectiveEvidenceUnit.from_mapping(
                        {
                            "evidence_unit_id": "oeu-1",
                            "objective_id": "obj-1",
                            "document_id": "doc-1",
                            "unit_kind": "measurement",
                            "sample_context": {"sample": "sample-a"},
                            "property_normalized": "yield_strength",
                            "value_payload": {"value": 520.0000001},
                            "unit": "MPa",
                            "source_refs": [{"source_kind": "table", "source_ref": "t1"}],
                            "confidence": 0.9,
                            "resolution_status": "resolved",
                        }
                    ),
                )
            )
        ),
        evaluation_repository=repository,
    )
    snapshot_service.create_core_snapshot(
        collection_id="col-gold",
        fact_source="objective_first",
        snapshot_id="snapshot-1",
    )
    service = CoreEvaluationService(evaluation_repository=repository)

    run = service.evaluate_snapshot(
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-1",
        evaluation_run_id="eval-1",
    )

    assert repository.run == run
    assert run.status == "ready"
    assert run.summary["measurement_recall"] == 1.0
    assert run.summary["measurement_precision"] == 1.0
    assert run.failures == ()


def test_core_evaluation_service_reports_missing_extra_and_unit_failures():
    repository = FakeEvaluationRepository()
    gold_service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )
    gold_service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        items=[
            {
                "gold_item_id": "gold-1",
                "document_id": "doc-1",
                "family": "measurement_results",
                "item_key": "doc-1:sample-a:yield_strength",
                "payload": {"value": 520, "unit": "MPa"},
            },
            {
                "gold_item_id": "gold-2",
                "document_id": "doc-1",
                "family": "measurement_results",
                "item_key": "doc-1:sample-b:elongation",
                "payload": {"value": 22, "unit": "%"},
            },
        ],
    )
    repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshotService(
            collection_service=FakeCollectionService(),
            core_fact_repository=FakeCoreFactRepository(
                CoreFactSet(
                    objective_evidence_units=(
                        ObjectiveEvidenceUnit.from_mapping(
                            {
                                "evidence_unit_id": "oeu-1",
                                "objective_id": "obj-1",
                                "document_id": "doc-1",
                                "unit_kind": "measurement",
                                "sample_context": {"sample": "sample-a"},
                                "property_normalized": "yield_strength",
                                "value_payload": {"value": 520},
                                "unit": "GPa",
                                "source_refs": [{"source_kind": "table", "source_ref": "t1"}],
                            }
                        ),
                        ObjectiveEvidenceUnit.from_mapping(
                            {
                                "evidence_unit_id": "oeu-extra",
                                "objective_id": "obj-1",
                                "document_id": "doc-1",
                                "unit_kind": "measurement",
                                "sample_context": {"sample": "sample-c"},
                                "property_normalized": "hardness",
                                "value_payload": {"value": 210},
                                "unit": "HV",
                            }
                        ),
                    )
                )
            ),
            evaluation_repository=FakeEvaluationRepository(),
        ).create_core_snapshot(
            collection_id="col-gold",
            fact_source="objective_first",
            snapshot_id="snapshot-1",
        )
    )
    service = CoreEvaluationService(evaluation_repository=repository)

    run = service.evaluate_snapshot(
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-1",
        evaluation_run_id="eval-1",
    )

    assert run.status == "ready_with_failures"
    assert run.summary["measurement_recall"] == 0.0
    assert run.summary["measurement_precision"] == 0.0
    assert sorted(failure.failure_type for failure in run.failures) == [
        "extra_prediction",
        "missing_gold_item",
        "unit_mismatch",
    ]


def test_core_evaluation_service_scores_empty_prediction_as_zero_recall():
    repository = FakeEvaluationRepository()
    gold_service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )
    gold_service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        items=[
            {
                "gold_item_id": "gold-1",
                "document_id": "doc-1",
                "family": "measurement_results",
                "item_key": "doc-1:sample-a:yield_strength",
                "payload": {"value": 520, "unit": "MPa"},
            }
        ],
    )
    repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshotService(
            collection_service=FakeCollectionService(),
            core_fact_repository=FakeCoreFactRepository(
                CoreFactSet(research_objectives_ready=True)
            ),
            evaluation_repository=FakeEvaluationRepository(),
        ).create_core_snapshot(
            collection_id="col-gold",
            fact_source="objective_first",
            snapshot_id="snapshot-empty",
        )
    )
    service = CoreEvaluationService(evaluation_repository=repository)

    run = service.evaluate_snapshot(
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-empty",
        evaluation_run_id="eval-empty",
    )

    assert run.summary["measurement_recall"] == 0.0
    assert [failure.failure_type for failure in run.failures] == ["missing_gold_item"]


def test_core_evaluation_service_matches_objective_first_comparison_values():
    repository = FakeEvaluationRepository()
    gold_service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )
    gold_service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        items=[
            {
                "gold_item_id": "gold-comparison-1",
                "document_id": "doc-1",
                "family": "comparisons",
                "item_key": "doc-1:sample-a:sample-b:yield_strength",
                "payload": {
                    "current_value": 520,
                    "baseline_value": 470,
                    "unit": "MPa",
                    "direction": "higher",
                },
            }
        ],
    )
    snapshot = EvaluationPredictionSnapshotService(
        collection_service=FakeCollectionService(),
        core_fact_repository=FakeCoreFactRepository(
            CoreFactSet(
                objective_evidence_units=(
                    ObjectiveEvidenceUnit.from_mapping(
                        {
                            "evidence_unit_id": "oeu-comparison-1",
                            "objective_id": "obj-1",
                            "document_id": "doc-1",
                            "unit_kind": "comparison",
                            "sample_context": {"sample": "sample-a"},
                            "baseline_context": {"sample": "sample-b"},
                            "property_normalized": "yield_strength",
                            "value_payload": {
                                "current_value": 520,
                                "baseline_value": 470,
                                "direction": "higher",
                            },
                            "unit": "MPa",
                            "source_refs": [{"source_kind": "table", "source_ref": "t1"}],
                            "confidence": 0.9,
                        }
                    ),
                )
            )
        ),
        evaluation_repository=FakeEvaluationRepository(),
    ).create_core_snapshot(
        collection_id="col-gold",
        fact_source="objective_first",
        snapshot_id="snapshot-comparison",
    )
    repository.upsert_prediction_snapshot(snapshot)
    service = CoreEvaluationService(evaluation_repository=repository)

    run = service.evaluate_snapshot(
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-comparison",
        evaluation_run_id="eval-comparison",
    )

    assert snapshot.items[0].payload["current_value"] == 520.0
    assert snapshot.items[0].payload["baseline_value"] == 470.0
    assert snapshot.items[0].payload["direction"] == "higher"
    assert run.summary["comparison_recall"] == 1.0
    assert run.failures == ()


def test_core_evaluation_service_reports_numeric_and_evidence_failures():
    repository = FakeEvaluationRepository()
    gold_service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )
    gold_service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-v1",
        items=[
            {
                "gold_item_id": "gold-1",
                "document_id": "doc-1",
                "family": "measurement_results",
                "item_key": "doc-1:sample-a:yield_strength",
                "payload": {"value": 520, "unit": "MPa"},
                "evidence_refs": [{"quote": "520 MPa"}],
            }
        ],
    )
    repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshotService(
            collection_service=FakeCollectionService(),
            core_fact_repository=FakeCoreFactRepository(
                CoreFactSet(
                    objective_evidence_units=(
                        ObjectiveEvidenceUnit.from_mapping(
                            {
                                "evidence_unit_id": "oeu-1",
                                "objective_id": "obj-1",
                                "document_id": "doc-1",
                                "unit_kind": "measurement",
                                "sample_context": {"sample": "sample-a"},
                                "property_normalized": "yield_strength",
                                "value_payload": {"value": 510},
                                "unit": "MPa",
                            }
                        ),
                    )
                )
            ),
            evaluation_repository=FakeEvaluationRepository(),
        ).create_core_snapshot(
            collection_id="col-gold",
            fact_source="objective_first",
            snapshot_id="snapshot-1",
        )
    )
    service = CoreEvaluationService(evaluation_repository=repository)

    run = service.evaluate_snapshot(
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-1",
        evaluation_run_id="eval-1",
    )

    assert sorted(failure.failure_type for failure in run.failures) == [
        "evidence_trace_missing",
        "numeric_value_mismatch",
    ]
