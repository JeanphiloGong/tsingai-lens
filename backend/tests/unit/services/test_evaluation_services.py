from __future__ import annotations

import pytest

from application.evaluation.core_evaluation_service import CoreEvaluationService
from application.evaluation.gold_service import EvaluationGoldService
from application.evaluation.prediction_snapshot_service import (
    CoreArtifactsNotReadyForEvaluationError,
    EvaluationPredictionSnapshotService,
)
from application.evaluation import research_understanding_feedback_service as ruf_service
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

    def __init__(
        self,
        understanding: ResearchUnderstanding | None,
        understandings: tuple[ResearchUnderstanding, ...] | None = None,
    ) -> None:
        self.understanding = understanding
        self.understandings = understandings

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
        understandings = self.understandings
        if understandings is None:
            understandings = (self.understanding,) if self.understanding else ()
        if scope_type is None:
            return tuple(understandings)
        return tuple(
            understanding
            for understanding in understandings
            if understanding.scope.scope_type == scope_type
        )


class FakeResearchUnderstandingProjectionService:
    def __init__(self, projected: dict | None = None) -> None:
        self.projected = projected
        self.inputs = []

    def with_presentation(self, understanding):
        self.inputs.append(understanding)
        return self.projected if self.projected is not None else understanding.to_record()


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
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
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
    assert dataset["quality_summary"] == {
        "total_samples": 4,
        "usable_sample_count": 2,
        "training_ready_sample_count": 1,
        "training_message_sample_count": 1,
        "protocol_ready_sample_count": 1,
        "review_candidate_sample_count": 2,
        "next_review_finding_id": "finding-2",
        "needs_review_count": 2,
        "rejected_count": 1,
        "labeled_sample_count": 3,
        "accepted_system_sample_count": 0,
        "accepted_after_curation_match_count": 1,
        "curated_correction_count": 0,
        "system_error_count": 1,
        "resolved_feedback_count": 0,
        "by_label_status": {
            "candidate": 1,
            "silver": 1,
            "gold": 1,
            "rejected": 1,
        },
        "by_dataset_use_status": {
            "training_ready": 1,
            "review_candidate": 2,
            "rejected": 1,
        },
        "by_review_status": {
            "accepted": 1,
            "partial": 1,
            "incorrect": 1,
            "needs_review": 1,
        },
        "by_issue_type": {
            "none": 2,
            "evidence_not_grounded": 1,
            "unreviewed": 1,
        },
        "by_error_category": {
            "none": 2,
            "evidence_error": 1,
            "unreviewed": 1,
        },
        "by_support_grade": {
            "partial": 2,
            "weak": 2,
        },
        "by_trace_status": {
            "evidence_derived": 4,
        },
        "by_evidence_role": {
            "direct_result": 3,
            "background": 1,
        },
        "by_evidence_traceability_status": {
            "direct": 4,
        },
        "by_quality_decision": {
            "accepted_after_curation_match": 1,
            "partial_review": 1,
            "rejected_system": 1,
            "candidate": 1,
        },
        "by_presentation_bucket": {
            "unbucketed": 4,
        },
        "by_bucket_quality_decision": {
            "unbucketed": {
                "accepted_after_curation_match": 1,
                "partial_review": 1,
                "rejected_system": 1,
                "candidate": 1,
            },
        },
        "by_review_reason": {},
        "by_system_warning": {},
        "by_review_candidate_reason": {},
        "by_review_candidate_warning": {},
        "top_error_categories": [
            {"name": "none", "count": 2},
            {"name": "evidence_error", "count": 1},
            {"name": "unreviewed", "count": 1},
        ],
        "top_issue_types": [
            {"name": "none", "count": 2},
            {"name": "evidence_not_grounded", "count": 1},
            {"name": "unreviewed", "count": 1},
        ],
        "top_review_reasons": [],
        "top_system_warnings": [],
        "warning_counts": {
            "missing_evidence": 0,
            "missing_source_text": 0,
            "missing_context": 0,
            "unavailable_trace": 0,
            "failed_trace": 0,
            "rejected_feedback": 1,
            "resolved_feedback": 0,
        },
    }
    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    assert by_finding["finding-1"]["label_status"] == "gold"
    assert by_finding["finding-1"]["dataset_use_status"] == "training_ready"
    assert by_finding["finding-1"]["presentation_bucket"] == "unbucketed"
    assert by_finding["finding-1"]["system_prediction"]["presentation_bucket"] == (
        "unbucketed"
    )
    assert by_finding["finding-1"]["expert_target"]["source"] == "curation"
    assert by_finding["finding-1"]["expert_target"]["statement"] == (
        "Preheating improves ductility by 14% in LPBF 316L."
    )
    assert by_finding["finding-1"]["evidence_refs"][0]["source_text"] == (
        "Preheating increased ductility by 14% in LPBF 316L."
    )
    assert by_finding["finding-1"]["evidence_refs"][0]["training_source_text"] == (
        by_finding["finding-1"]["evidence_refs"][0]["quote"]
    )
    assert by_finding["finding-1"]["evidence_refs"][0]["heading_path"] == (
        "Results / Mechanical properties"
    )
    assert by_finding["finding-1"]["training_evidence_refs"] == [
        by_finding["finding-1"]["evidence_refs"][0]
    ]
    assert by_finding["finding-1"]["training_messages"][0]["role"] == "user"
    assert "Preheating increased ductility by 14%" in (
        by_finding["finding-1"]["training_messages"][0]["content"]
    )
    assert by_finding["finding-1"]["training_messages"][1] == {
        "role": "assistant",
        "content": (
            '{"direction": "increase", "evidence_ref_ids": ["ev-1"], '
            '"mediators": ["porosity"], "outcomes": ["ductility"], '
            '"scope_summary": "LPBF 316L", '
            '"statement": "Preheating improves ductility by 14% in LPBF 316L.", '
            '"support_grade": "partial", "variables": ["preheating"]}'
        ),
    }
    assert by_finding["finding-1"]["context_refs"][0]["process_summary"] == "LPBF"
    assert by_finding["finding-1"]["trace_status"] == "evidence_derived"
    assert by_finding["finding-1"]["prompt_version"] == (
        "research_understanding_relation.v1"
    )
    assert by_finding["finding-1"]["input_blocks"] == [
        {
            "source_object_id": "ev-1",
            "source_kind": "text",
            "document_id": "doc-1",
            "source_ref": "blk-preheat",
            "page": "3",
            "role": "direct_result",
            "text": "Preheating increased ductility by 14%.",
            "href": "/documents/doc-1#blk-preheat",
        }
    ]
    assert by_finding["finding-1"]["model_output"]["trace_id"] == "rut-1"
    assert by_finding["finding-1"]["model_output"]["parsed_output"] == {
        "relations": []
    }
    assert by_finding["finding-2"]["label_status"] == "silver"
    assert by_finding["finding-2"]["dataset_use_status"] == "review_candidate"
    assert by_finding["finding-2"]["expert_target"]["source"] == "reviewer_feedback"
    assert by_finding["finding-2"]["expert_target"]["review_status"] == "partial"
    assert by_finding["finding-2"]["expert_target"]["feedback_id"] == "ruf-partial"
    assert by_finding["finding-2"]["expert_target"]["statement"] == (
        by_finding["finding-2"]["system_prediction"]["statement"]
    )
    assert by_finding["finding-2"]["evidence_refs"][0]["training_source_text"] == (
        by_finding["finding-2"]["evidence_refs"][0]["quote"]
    )
    assert by_finding["finding-2"]["training_evidence_refs"] == [
        by_finding["finding-2"]["evidence_refs"][0]
    ]
    assert by_finding["finding-2"]["training_messages"] == []
    assert by_finding["finding-3"]["label_status"] == "rejected"
    assert by_finding["finding-3"]["dataset_use_status"] == "rejected"
    assert by_finding["finding-3"]["training_messages"] == []
    assert by_finding["finding-4"]["label_status"] == "candidate"
    assert by_finding["finding-4"]["dataset_use_status"] == "review_candidate"
    assert by_finding["finding-4"]["training_messages"] == []
    assert by_finding["finding-4"]["trace_status"] == "evidence_derived"


def test_research_understanding_feedback_service_derives_dataset_input_blocks_from_traceable_evidence():
    record = _sample_understanding().to_record()
    record["model_traces"] = []
    record["presentation"]["findings"] = [record["presentation"]["findings"][0]]
    understanding = ResearchUnderstanding.from_mapping(record)
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=FakeEvaluationRepository(),
        core_fact_repository=FakeResearchUnderstandingRepository(understanding),
        research_understanding_service=FakeResearchUnderstandingProjectionService(record),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    sample = dataset["items"][0]
    assert sample["trace_status"] == "evidence_derived"
    assert sample["input_blocks"] == [
        {
            "source_object_id": "ev-1",
            "source_kind": "text",
            "document_id": "doc-1",
            "source_ref": "blk-preheat",
            "page": "3",
            "role": "direct_result",
            "text": "Preheating increased ductility by 14%.",
            "href": "/documents/doc-1#blk-preheat",
        }
    ]
    assert dataset["quality_summary"]["by_trace_status"] == {"evidence_derived": 1}
    assert dataset["quality_summary"]["warning_counts"]["unavailable_trace"] == 0


def test_research_understanding_feedback_service_derives_dataset_input_blocks_when_matched_trace_failed():
    record = _sample_understanding().to_record()
    record["model_traces"] = [
        {
            "trace_id": "rut-failed",
            "task_type": "research_understanding_relation",
            "prompt_version": "research_understanding_relation.v1",
            "model": "fake-model",
            "extraction_mode": "provider_parse",
            "response_model": "StructuredResearchUnderstandingRelations",
            "trace_status": "failed",
            "source_object_ids": ["oeu-preheat"],
            "input_blocks": [
                {
                    "source_object_id": "oeu-preheat",
                    "source_kind": "objective_evidence_unit",
                }
            ],
            "raw_output": "",
            "parsed_output": None,
            "error": "structured extraction failed",
        }
    ]
    record["presentation"]["findings"] = [record["presentation"]["findings"][0]]
    understanding = ResearchUnderstanding.from_mapping(record)
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=FakeEvaluationRepository(),
        core_fact_repository=FakeResearchUnderstandingRepository(understanding),
        research_understanding_service=FakeResearchUnderstandingProjectionService(record),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    sample = dataset["items"][0]
    assert sample["trace_status"] == "evidence_derived"
    assert sample["input_blocks"] == [
        {
            "source_object_id": "ev-1",
            "source_kind": "text",
            "document_id": "doc-1",
            "source_ref": "blk-preheat",
            "page": "3",
            "role": "direct_result",
            "text": "Preheating increased ductility by 14%.",
            "href": "/documents/doc-1#blk-preheat",
        }
    ]
    assert sample["model_output"]["trace_id"] == "rut-failed"
    assert sample["model_output"]["error"] == "structured extraction failed"
    assert sample["metadata"]["trace_note"] == (
        "dataset input reconstructed from resolved evidence source text"
    )
    assert dataset["quality_summary"]["by_trace_status"] == {"evidence_derived": 1}
    assert dataset["quality_summary"]["warning_counts"]["failed_trace"] == 0


def test_research_understanding_feedback_service_exports_current_presentation_findings():
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-gold",
                "goal_id": "goal-1",
                "title": "How does VED affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim-legacy",
                    "claim_type": "finding",
                    "statement": "Legacy claim text should not drive the dataset.",
                    "status": "limited",
                    "evidence_ref_ids": ["ev-legacy"],
                    "context_ids": ["ctx-1"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev-off-target",
                    "source_kind": "table",
                    "document_id": "doc-1",
                    "label": "P001 table context",
                    "locator": {"source_ref": "tbl-density"},
                    "traceability_status": "partial",
                    "quote": "Table reports specimen labels and density metadata.",
                },
                {
                    "evidence_ref_id": "ev-current",
                    "source_kind": "text",
                    "document_id": "doc-1",
                    "label": "P001 density result",
                    "locator": {"source_ref": "blk-density"},
                    "traceability_status": "direct",
                    "evidence_role": "direct_support",
                    "quote": "Density increased from 91.9% to 99.6% from L-VED to H-VED.",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx-1",
                    "label": "LPBF 316L",
                    "material_scope": ["316L"],
                    "property_scope": ["density"],
                }
            ],
        }
    )
    projected = stored.to_record()
    projected["presentation"] = {
        "findings": [
            {
                "finding_id": "finding-current",
                "claim_id": "claim-current",
                "title": "VED -> density",
                "statement": "H-VED achieved 99.6% density.",
                "variables": ["VED"],
                "mediators": [],
                "outcomes": ["density"],
                "direction": "increase",
                "scope_summary": "LPBF 316L",
                "support_grade": "partial",
                "review_status": "needs_review",
                "confidence": 0.78,
                "paper_count": 1,
                "evidence_count": 1,
                "evidence_ref_ids": ["ev-off-target"],
                "context_ids": ["ctx-1"],
                "relation_ids": [],
                "evidence_bundle": {
                    "direct_result": ["ev-current"],
                    "uncategorized": ["ev-off-target"],
                },
            }
        ],
        "evidence_items": [
            {
                "evidence_ref_id": "ev-off-target",
                "document_id": "doc-1",
                "title": "P001 table context",
                "source_label": "P001 table",
                "source_kind": "table",
                "source_ref": "tbl-density",
                "quote": "Table reports specimen labels and density metadata.",
                "source_text": "Table reports specimen labels and density metadata.",
                "traceability_status": "partial",
            },
            {
                "evidence_ref_id": "ev-current",
                "document_id": "doc-1",
                "title": "P001 density result",
                "source_label": "P001 p.4",
                "source_kind": "text",
                "source_ref": "blk-density",
                "heading_path": "Results / Density",
                "page": "4",
                "quote": "Density increased from 91.9% to 99.6% from L-VED to H-VED.",
                "source_text": "Density increased from 91.9% to 99.6% from L-VED to H-VED.",
                "value_summary": "density 99.6%",
                "traceability_status": "direct",
                "evidence_role": "direct_support",
            }
        ],
        "context_summaries": [
            {
                "context_id": "ctx-1",
                "label": "LPBF 316L",
                "material_scope": ["316L"],
                "property_scope": ["density"],
            }
        ],
    }
    projection_service = FakeResearchUnderstandingProjectionService(projected)
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=FakeEvaluationRepository(),
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=projection_service,
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    assert projection_service.inputs == [stored]
    assert dataset["item_count"] == 1
    sample = dataset["items"][0]
    assert sample["finding_id"] == "finding-current"
    assert sample["claim_id"] == "claim-current"
    assert sample["system_prediction"]["title"] == "VED -> density"
    assert sample["system_prediction"]["statement"] == "H-VED achieved 99.6% density."
    assert sample["system_prediction"]["variables"] == ["VED"]
    assert sample["system_prediction"]["outcomes"] == ["density"]
    assert sample["system_prediction"]["evidence_bundle"] == {
        "direct_result": ["ev-current"],
        "uncategorized": ["ev-off-target"],
    }
    assert [ref["evidence_ref_id"] for ref in sample["evidence_refs"]] == [
        "ev-current",
        "ev-off-target",
    ]
    assert sample["evidence_refs"][0]["source_text"] == (
        "Density increased from 91.9% to 99.6% from L-VED to H-VED."
    )
    assert sample["evidence_refs"][0]["training_source_text"] == (
        "Density increased from 91.9% to 99.6% from L-VED to H-VED."
    )
    assert [ref["evidence_ref_id"] for ref in sample["training_evidence_refs"]] == [
        "ev-current"
    ]
    assert dataset["quality_summary"]["by_support_grade"] == {"partial": 1}


def test_research_understanding_feedback_service_exports_presentation_buckets():
    stored = _sample_understanding()
    projected = stored.to_record()
    projected["presentation"]["primary_findings"] = [
        projected["presentation"]["findings"][0],
        projected["presentation"]["findings"][2],
    ]
    projected["presentation"]["review_queue_findings"] = [
        projected["presentation"]["findings"][1],
    ]
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=FakeEvaluationRepository(),
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=FakeResearchUnderstandingProjectionService(projected),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    assert by_finding["finding-1"]["presentation_bucket"] == "primary"
    assert by_finding["finding-1"]["dataset_use_status"] == "review_candidate"
    assert by_finding["finding-1"]["metadata"]["presentation_bucket"] == "primary"
    assert by_finding["finding-2"]["presentation_bucket"] == "review_queue"
    assert by_finding["finding-2"]["dataset_use_status"] == "review_candidate"
    assert by_finding["finding-3"]["presentation_bucket"] == "primary"
    assert by_finding["finding-3"]["dataset_use_status"] == "review_candidate"
    assert "finding-4" not in by_finding
    assert by_finding["finding-2"]["system_prediction"]["presentation_bucket"] == (
        "review_queue"
    )
    assert dataset["quality_summary"]["by_presentation_bucket"] == {
        "primary": 2,
        "review_queue": 1,
    }
    assert dataset["quality_summary"]["by_bucket_quality_decision"] == {
        "primary": {"candidate": 2},
        "review_queue": {"candidate": 1},
    }
    assert dataset["quality_summary"]["by_dataset_use_status"] == {
        "training_ready": 0,
        "review_candidate": 3,
        "rejected": 0,
    }
    assert dataset["quality_summary"]["training_ready_sample_count"] == 0
    assert dataset["quality_summary"]["review_candidate_sample_count"] == 3


def test_research_understanding_feedback_service_summarizes_system_review_risks():
    stored = _sample_understanding()
    projected = stored.to_record()
    projected["presentation"]["findings"] = [
        projected["presentation"]["findings"][0],
        projected["presentation"]["findings"][1],
    ]
    projected["presentation"]["findings"][0]["review_reasons"] = [
        "single_paper_evidence",
        "partial_support",
    ]
    projected["presentation"]["findings"][0]["warnings"] = [
        "table_row_alignment_uncertain",
    ]
    projected["presentation"]["findings"][1]["review_reasons"] = [
        "single_paper_evidence",
    ]
    projected["presentation"]["findings"][1]["warnings"] = [
        "weak_evidence",
    ]
    projected["presentation"]["findings"][1]["review_reasons"].append(
        "table_row_needs_expert_review"
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=FakeEvaluationRepository(),
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=FakeResearchUnderstandingProjectionService(projected),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    assert by_finding["finding-1"]["system_prediction"]["review_reasons"] == [
        "single_paper_evidence",
        "partial_support",
    ]
    assert by_finding["finding-1"]["system_prediction"]["warnings"] == [
        "table_row_alignment_uncertain"
    ]
    assert by_finding["finding-1"]["review_action"] == {
        "code": "verify_table_rows",
        "label": "verify parsed table rows before accepting or correcting",
    }
    assert by_finding["finding-2"]["review_action"] == {
        "code": "review_table_rows",
        "label": "review selected table rows before accepting or correcting",
    }
    assert dataset["quality_summary"]["by_review_reason"] == {
        "single_paper_evidence": 2,
        "partial_support": 1,
        "table_row_needs_expert_review": 1,
    }
    assert dataset["quality_summary"]["by_system_warning"] == {
        "table_row_alignment_uncertain": 1,
        "weak_evidence": 1,
    }
    assert dataset["quality_summary"]["by_review_candidate_reason"] == {
        "single_paper_evidence": 2,
        "partial_support": 1,
        "table_row_needs_expert_review": 1,
    }
    assert dataset["quality_summary"]["by_review_candidate_warning"] == {
        "table_row_alignment_uncertain": 1,
        "weak_evidence": 1,
    }


def test_research_understanding_feedback_service_curation_evidence_priority():
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-gold",
                "goal_id": "goal-1",
                "title": "How does porosity affect corrosion?",
            },
            "claims": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev-off-target",
                    "source_kind": "table",
                    "document_id": "doc-1",
                    "label": "Density table",
                    "locator": {"source_ref": "tbl-density"},
                    "traceability_status": "partial",
                    "quote": "Table reports density values.",
                },
                {
                    "evidence_ref_id": "ev-corrosion",
                    "source_kind": "text",
                    "document_id": "doc-1",
                    "label": "Corrosion result",
                    "locator": {"source_ref": "blk-corrosion"},
                    "traceability_status": "direct",
                    "quote": "Higher porosity made the passive film less stable.",
                },
            ],
            "contexts": [],
        }
    )
    projected = stored.to_record()
    projected["presentation"] = {
        "findings": [
            {
                "finding_id": "finding-corrosion",
                "claim_id": "claim-corrosion",
                "title": "porosity -> corrosion",
                "statement": "Porosity is associated with corrosion.",
                "variables": ["porosity"],
                "mediators": [],
                "outcomes": ["corrosion behavior"],
                "direction": "increase",
                "scope_summary": "SLM 316L",
                "support_grade": "partial",
                "review_status": "needs_review",
                "confidence": 0.7,
                "paper_count": 1,
                "evidence_count": 2,
                "evidence_ref_ids": ["ev-off-target", "ev-corrosion"],
                "context_ids": [],
                "relation_ids": [],
                "evidence_bundle": {
                    "direct_result": ["ev-off-target"],
                    "uncategorized": ["ev-corrosion"],
                },
            }
        ],
        "primary_findings": [],
        "review_queue_findings": [],
        "evidence_items": [
            {
                "evidence_ref_id": "ev-off-target",
                "document_id": "doc-1",
                "title": "Density table",
                "source_kind": "table",
                "quote": "Table reports density values.",
                "source_text": "Table reports density values.",
            },
            {
                "evidence_ref_id": "ev-corrosion",
                "document_id": "doc-1",
                "title": "Corrosion result",
                "source_kind": "text",
                "quote": "Higher porosity made the passive film less stable.",
                "source_text": "Higher porosity made the passive film less stable.",
            },
        ],
    }
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-corrosion",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-corrosion",
                "claim_id": "claim-corrosion",
                "curated_claim_type": "finding",
                "curated_status": "supported",
                "curated_statement": (
                    "Higher porosity made SLM 316L more vulnerable to corrosion."
                ),
                "curated_support_grade": "partial",
                "curated_review_status": "accepted",
                "curated_evidence_ref_ids": ["ev-corrosion"],
                "curated_context_ids": [],
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=FakeResearchUnderstandingProjectionService(projected),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    sample = dataset["items"][0]
    assert sample["label_status"] == "gold"
    assert sample["expert_target"]["source"] == "curation"
    assert [ref["evidence_ref_id"] for ref in sample["evidence_refs"]] == [
        "ev-corrosion",
        "ev-off-target",
    ]
    assert [ref["evidence_ref_id"] for ref in sample["training_evidence_refs"]] == [
        "ev-corrosion",
    ]
    assert "Higher porosity made the passive film less stable." in (
        sample["training_messages"][0]["content"]
    )
    assert "Table reports density values." not in sample["training_messages"][0][
        "content"
    ]


def test_research_understanding_feedback_service_curation_match_evidence_order_keeps_current_direct_evidence_first():
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-gold",
                "goal_id": "goal-1",
                "title": "How does porosity affect corrosion?",
            },
            "claims": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev-broad",
                    "source_kind": "text",
                    "document_id": "doc-1",
                    "label": "Abstract",
                    "locator": {"source_ref": "blk-abstract"},
                    "traceability_status": "partial",
                    "quote": (
                        "The mechanical and corrosion properties were "
                        "investigated by subsequent testing."
                    ),
                },
                {
                    "evidence_ref_id": "ev-corrosion",
                    "source_kind": "text",
                    "document_id": "doc-1",
                    "label": "Corrosion result",
                    "locator": {"source_ref": "blk-corrosion"},
                    "traceability_status": "direct",
                    "quote": (
                        "Porosities were highly sensitive to pitting corrosion."
                    ),
                },
                {
                    "evidence_ref_id": "ev-table",
                    "source_kind": "table",
                    "document_id": "doc-1",
                    "label": "Density table",
                    "locator": {"source_ref": "tbl-density"},
                    "traceability_status": "partial",
                    "quote": "Table reports density values.",
                },
            ],
            "contexts": [],
        }
    )
    projected = stored.to_record()
    projected["presentation"] = {
        "findings": [
            {
                "finding_id": "finding-corrosion",
                "claim_id": "claim-corrosion",
                "title": "porosity -> pitting corrosion behavior",
                "statement": (
                    "Porosities were highly sensitive to pitting corrosion."
                ),
                "variables": ["porosity"],
                "mediators": [],
                "outcomes": ["pitting corrosion"],
                "direction": "increase",
                "scope_summary": "SLM 316L",
                "support_grade": "partial",
                "review_status": "needs_review",
                "confidence": 0.7,
                "paper_count": 1,
                "evidence_count": 3,
                "evidence_ref_ids": [
                    "ev-table",
                    "ev-broad",
                    "ev-corrosion",
                ],
                "context_ids": [],
                "relation_ids": [],
                "evidence_bundle": {
                    "direct_result": ["ev-corrosion"],
                    "uncategorized": ["ev-table", "ev-broad"],
                },
            }
        ],
        "primary_findings": [
            {"finding_id": "finding-corrosion"},
        ],
        "review_queue_findings": [],
        "evidence_items": [
            {
                "evidence_ref_id": "ev-broad",
                "document_id": "doc-1",
                "title": "Abstract",
                "source_kind": "text",
                "quote": (
                    "The mechanical and corrosion properties were "
                    "investigated by subsequent testing."
                ),
                "source_text": (
                    "The mechanical and corrosion properties were "
                    "investigated by subsequent testing."
                ),
            },
            {
                "evidence_ref_id": "ev-corrosion",
                "document_id": "doc-1",
                "title": "Corrosion result",
                "source_kind": "text",
                "quote": (
                    "Porosities were highly sensitive to pitting corrosion."
                ),
                "source_text": (
                    "Porosities were highly sensitive to pitting corrosion."
                ),
            },
            {
                "evidence_ref_id": "ev-table",
                "document_id": "doc-1",
                "title": "Density table",
                "source_kind": "table",
                "quote": "Table reports density values.",
                "source_text": "Table reports density values.",
            },
        ],
    }
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-corrosion",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-corrosion",
                "claim_id": "claim-corrosion",
                "curated_claim_type": "finding",
                "curated_status": "supported",
                "curated_statement": (
                    "Porosities were highly sensitive to pitting corrosion."
                ),
                "curated_support_grade": "partial",
                "curated_review_status": "accepted",
                "curated_variables": ["porosity"],
                "curated_mediators": [],
                "curated_outcomes": ["pitting corrosion"],
                "curated_direction": "increase",
                "curated_scope_summary": "SLM 316L",
                "curated_evidence_ref_ids": ["ev-broad", "ev-corrosion"],
                "curated_context_ids": [],
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=FakeResearchUnderstandingProjectionService(projected),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    sample = dataset["items"][0]
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "accepted_after_curation_match": 1,
    }
    assert sample["expert_target"]["source"] == "curation"
    assert sample["expert_target"]["evidence_ref_ids"] == [
        "ev-broad",
        "ev-corrosion",
    ]
    assert [ref["evidence_ref_id"] for ref in sample["evidence_refs"]] == [
        "ev-corrosion",
        "ev-table",
        "ev-broad",
    ]


def test_research_understanding_feedback_service_current_label_alignment_ignores_stale_claim_level_correct_feedback():
    stored = _sample_understanding()
    projected = stored.to_record()
    projected["presentation"]["findings"][1]["title"] = "energy density -> microstructure"
    projected["presentation"]["findings"][1]["statement"] = (
        "Energy density is associated with microstructure variation."
    )
    projected["presentation"]["findings"][1]["support_grade"] = "insufficient"
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-stale-correct",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "",
                "claim_id": "claim-2",
                "review_status": "correct",
                "issue_type": "none",
                "note": "Reviewed an older claim-level VED density finding.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=FakeResearchUnderstandingProjectionService(projected),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    stale_sample = by_finding["finding-2"]
    assert stale_sample["label_status"] == "candidate"
    assert stale_sample["expert_target"] is None
    assert stale_sample["feedback_refs"] == []
    assert stale_sample["metadata"]["ignored_feedback_refs"][0]["feedback_id"] == (
        "ruf-stale-correct"
    )
    assert dataset["quality_summary"]["by_quality_decision"] == {"candidate": 4}
    assert dataset["quality_summary"]["accepted_system_sample_count"] == 0


def test_research_understanding_feedback_service_current_label_alignment_keeps_exact_finding_rejection():
    stored = _sample_understanding()
    projected = stored.to_record()
    projected["presentation"]["findings"][1]["support_grade"] = "insufficient"
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-stale-correct",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "",
                "claim_id": "claim-2",
                "review_status": "correct",
                "issue_type": "none",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-exact-wrong-context",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "review_status": "partial",
                "issue_type": "wrong_context",
                "note": "The current finding uses the wrong process context.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:30:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(stored),
        research_understanding_service=FakeResearchUnderstandingProjectionService(projected),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    rejected_sample = by_finding["finding-2"]
    assert rejected_sample["label_status"] == "rejected"
    assert [item["feedback_id"] for item in rejected_sample["feedback_refs"]] == [
        "ruf-exact-wrong-context"
    ]
    assert rejected_sample["metadata"]["ignored_feedback_refs"][0]["feedback_id"] == (
        "ruf-stale-correct"
    )
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "candidate": 3,
        "rejected_system": 1,
    }
    assert dataset["quality_summary"]["system_error_count"] == 1


def test_research_understanding_feedback_service_current_label_alignment_aligns_claim_curation_by_evidence_overlap():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-claim-evidence-overlap",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "",
                "claim_id": "claim-3",
                "curated_claim_type": "finding",
                "curated_status": "supported",
                "curated_statement": (
                    "Porosity provides defect sites that support pitting corrosion."
                ),
                "curated_support_grade": "partial",
                "curated_review_status": "accepted",
                "curated_variables": ["porosity"],
                "curated_mediators": ["defect sites"],
                "curated_outcomes": ["pitting corrosion"],
                "curated_direction": "increase",
                "curated_scope_summary": "SLM 316L corrosion",
                "curated_evidence_ref_ids": ["ev-3"],
                "curated_context_ids": ["ctx-2"],
                "note": "Same direct corrosion evidence as the current finding.",
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    curated_sample = by_finding["finding-3"]
    assert curated_sample["label_status"] == "gold"
    assert curated_sample["expert_target"]["source"] == "curation"
    assert curated_sample["expert_target"]["curation_id"] == (
        "ruc-claim-evidence-overlap"
    )
    assert curated_sample["metadata"]["ignored_curation_refs"] == []
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "candidate": 3,
        "accepted_after_curation_match": 1,
    }
    assert dataset["quality_summary"]["accepted_after_curation_match_count"] == 1
    assert dataset["quality_summary"]["curated_correction_count"] == 0


def test_research_understanding_feedback_service_resolved_feedback_does_not_count_as_current_system_error():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-resolved",
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
                "note": "Current statement now matches the accepted correction.",
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-old-overclaim",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "review_status": "partial",
                "issue_type": "overclaim",
                "note": "Older review said the system claim was too broad.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    resolved_sample = by_finding["finding-1"]
    assert resolved_sample["label_status"] == "gold"
    assert resolved_sample["expert_target"]["source"] == "curation"
    assert resolved_sample["feedback_refs"][0]["feedback_id"] == "ruf-old-overclaim"
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "accepted_after_curation_match": 1,
        "candidate": 3,
    }
    assert dataset["quality_summary"]["system_error_count"] == 0
    assert dataset["quality_summary"]["resolved_feedback_count"] == 1
    assert dataset["quality_summary"]["warning_counts"]["rejected_feedback"] == 0
    assert dataset["quality_summary"]["warning_counts"]["resolved_feedback"] == 1


def test_research_understanding_feedback_service_curation_match_keeps_unmatched_curation_as_correction():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-unmatched",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "curated_claim_type": "finding",
                "curated_status": "supported",
                "curated_statement": (
                    "Laser scan strategy changes residual stress and crack formation."
                ),
                "curated_support_grade": "partial",
                "curated_review_status": "accepted",
                "curated_variables": ["scan strategy"],
                "curated_mediators": ["residual stress"],
                "curated_outcomes": ["cracking"],
                "curated_direction": "increase",
                "curated_scope_summary": "LPBF alloys",
                "curated_evidence_ref_ids": ["ev-missing"],
                "curated_context_ids": ["ctx-1"],
                "note": "Different target than the current VED density finding.",
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    curated_sample = by_finding["finding-2"]
    assert curated_sample["label_status"] == "gold"
    assert curated_sample["expert_target"]["source"] == "curation"
    assert curated_sample["metadata"]["curation_id"] == "ruc-unmatched"
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "candidate": 3,
        "curated_correction": 1,
    }
    assert dataset["quality_summary"]["accepted_after_curation_match_count"] == 0
    assert dataset["quality_summary"]["curated_correction_count"] == 1


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
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
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
    assert dataset["quality_summary"]["total_samples"] == 1
    assert dataset["quality_summary"]["by_label_status"] == {
        "candidate": 0,
        "silver": 0,
        "gold": 0,
        "rejected": 1,
    }
    assert dataset["quality_summary"]["by_quality_decision"] == {"rejected_system": 1}
    assert dataset["quality_summary"]["system_error_count"] == 1
    assert dataset["quality_summary"]["by_issue_type"] == {"wrong_relation": 1}
    assert dataset["quality_summary"]["by_error_category"] == {"relation_error": 1}
    assert dataset["quality_summary"]["warning_counts"]["rejected_feedback"] == 1


def test_research_understanding_feedback_service_counts_material_error_issue_types():
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-wrong-variable",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "review_status": "incorrect",
                "issue_type": "wrong_variable",
                "note": "The finding uses VED, but the evidence varies preheating.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:30:00+00:00",
            }
        ),
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-wrong-outcome",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "review_status": "incorrect",
                "issue_type": "wrong_outcome",
                "note": "The paper reports density, not tensile strength.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:31:00+00:00",
            }
        ),
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-wrong-direction",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-3",
                "claim_id": "claim-3",
                "review_status": "incorrect",
                "issue_type": "wrong_direction",
                "note": "The system reversed the reported trend.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:32:00+00:00",
            }
        ),
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-insufficient-evidence",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-4",
                "claim_id": "claim-4",
                "review_status": "incorrect",
                "issue_type": "insufficient_evidence",
                "note": "The source sentence is only background, not result evidence.",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:33:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    assert dataset["label_counts"] == {
        "candidate": 0,
        "silver": 0,
        "gold": 0,
        "rejected": 4,
    }
    assert dataset["quality_summary"]["system_error_count"] == 4
    assert dataset["quality_summary"]["by_issue_type"] == {
        "wrong_variable": 1,
        "wrong_outcome": 1,
        "wrong_direction": 1,
        "insufficient_evidence": 1,
    }
    assert dataset["quality_summary"]["by_error_category"] == {
        "variable_error": 1,
        "outcome_error": 1,
        "direction_error": 1,
        "evidence_error": 1,
    }
    assert dataset["quality_summary"]["top_error_categories"] == [
        {"name": "direction_error", "count": 1},
        {"name": "evidence_error", "count": 1},
        {"name": "outcome_error", "count": 1},
        {"name": "variable_error", "count": 1},
    ]
    assert dataset["quality_summary"]["top_issue_types"] == [
        {"name": "insufficient_evidence", "count": 1},
        {"name": "wrong_direction", "count": 1},
        {"name": "wrong_outcome", "count": 1},
        {"name": "wrong_variable", "count": 1},
    ]
    assert dataset["quality_summary"]["warning_counts"]["rejected_feedback"] == 4


def test_research_understanding_feedback_service_filters_dataset_by_use_status():
    repository = FakeEvaluationRepository()
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
                "issue_type": "wrong_relation",
                "created_at": "2026-06-18T10:30:00+00:00",
            }
        ),
    )
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
                "curated_evidence_ref_ids": ["ev-1"],
                "curated_context_ids": ["ctx-1"],
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T09:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    training_ready = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
        dataset_use_status="training_ready",
    )
    review_candidate = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
        dataset_use_status="review_candidate",
    )

    assert training_ready["dataset_use_status_filter"] == "training_ready"
    assert training_ready["item_count"] == 1
    assert {item["finding_id"] for item in training_ready["items"]} == {
        "finding-1",
    }
    assert training_ready["quality_summary"]["by_dataset_use_status"] == {
        "training_ready": 1,
        "review_candidate": 0,
        "rejected": 0,
    }
    assert review_candidate["dataset_use_status_filter"] == "review_candidate"
    assert review_candidate["item_count"] == 2
    by_review_finding = {item["finding_id"]: item for item in review_candidate["items"]}
    assert set(by_review_finding) == {"finding-2", "finding-4"}
    assert by_review_finding["finding-2"]["expert_target"]["source"] == (
        "reviewer_feedback"
    )
    assert by_review_finding["finding-2"]["expert_target"]["review_status"] == "partial"
    with pytest.raises(ValueError, match="unsupported dataset_use_status"):
        service.export_dataset(
            collection_id="col-gold",
            scope_type="goal",
            scope_id="goal-1",
            dataset_use_status="ready",
        )


def test_research_understanding_feedback_service_counts_only_valid_training_messages(
    monkeypatch,
):
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
                "curated_evidence_ref_ids": ["ev-1"],
                "curated_context_ids": ["ctx-1"],
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T09:00:00+00:00",
            }
        ),
    )
    monkeypatch.setattr(
        ruf_service,
        "_training_messages",
        lambda **_: [
            {"role": "user", "content": "Extract one finding."},
            {
                "role": "assistant",
                "content": '{"statement": "This does not match the expert target."}',
            },
        ],
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
        dataset_use_status="training_ready",
    )

    assert dataset["item_count"] == 1
    assert dataset["items"][0]["training_messages"]
    assert dataset["quality_summary"]["training_ready_sample_count"] == 1
    assert dataset["quality_summary"]["training_message_sample_count"] == 0
    assert dataset["quality_summary"]["protocol_ready_sample_count"] == 0


def test_research_understanding_feedback_service_requires_actionable_protocol_inputs():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-1",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "curated_claim_type": "finding",
                "curated_status": "supported",
                "curated_statement": "VED controls density.",
                "curated_evidence_ref_ids": ["ev-2"],
                "curated_context_ids": ["ctx-1"],
                "reviewer": "materials-expert",
                "updated_at": "2026-06-18T09:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
        dataset_use_status="training_ready",
    )

    assert dataset["item_count"] == 1
    assert dataset["items"][0]["training_messages"]
    assert dataset["quality_summary"]["training_ready_sample_count"] == 1
    assert dataset["quality_summary"]["training_message_sample_count"] == 1
    assert dataset["quality_summary"]["protocol_ready_sample_count"] == 0


def test_research_understanding_feedback_service_exports_collection_dataset():
    goal_one = _sample_understanding()
    goal_two_record = _sample_understanding().to_record()
    goal_two_record["scope"]["goal_id"] = "goal-2"
    goal_two_record["scope"]["title"] = "How does VED affect density?"
    goal_two_record["presentation"]["findings"] = [
        goal_two_record["presentation"]["findings"][1]
    ]
    goal_two = ResearchUnderstanding.from_mapping(goal_two_record)
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-goal-1",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "review_status": "correct",
                "issue_type": "none",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-goal-2",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-2",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "review_status": "correct",
                "issue_type": "none",
                "reviewer": "materials-expert",
                "created_at": "2026-06-18T10:01:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(
            None,
            understandings=(goal_one, goal_two),
        ),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_collection_dataset(
        collection_id="col-gold",
        scope_type="goal",
        dataset_use_status="training_ready",
    )

    assert dataset["collection_id"] == "col-gold"
    assert dataset["scope_type"] == "collection"
    assert dataset["scope_id"] == "goal"
    assert dataset["dataset_use_status_filter"] == "training_ready"
    assert dataset["item_count"] == 2
    assert {(item["scope_id"], item["finding_id"]) for item in dataset["items"]} == {
        ("goal-1", "finding-1"),
        ("goal-2", "finding-2"),
    }
    assert dataset["quality_summary"]["training_ready_sample_count"] == 2
    assert dataset["quality_summary"]["by_dataset_use_status"] == {
        "training_ready": 2,
        "review_candidate": 0,
        "rejected": 0,
    }


def test_research_understanding_feedback_service_keeps_anonymous_correct_feedback_silver():
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-anonymous-correct",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "review_status": "correct",
                "issue_type": "none",
                "note": "Correct, but reviewer identity is missing.",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    reviewed = by_finding["finding-1"]
    assert reviewed["label_status"] == "silver"
    assert reviewed["dataset_use_status"] == "review_candidate"
    assert reviewed["expert_target"]["source"] == "reviewer_feedback"
    assert reviewed["expert_target"]["review_status"] == "correct"
    assert reviewed["expert_target"]["reviewer"] is None
    assert dataset["quality_summary"]["training_ready_sample_count"] == 0
    assert dataset["quality_summary"]["review_candidate_sample_count"] == 4
    assert dataset["quality_summary"]["next_review_finding_id"] == "finding-1"
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "partial_review": 1,
        "candidate": 3,
    }


def test_research_understanding_feedback_service_keeps_ai_partial_feedback_reviewable():
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-ai-partial",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-2",
                "claim_id": "claim-2",
                "review_status": "partial",
                "issue_type": "none",
                "note": "Keep as a single-paper silver finding pending expert review.",
                "reviewer": "ai-reviewer-codex-primary-findings",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    reviewed = by_finding["finding-2"]
    assert reviewed["label_status"] == "silver"
    assert reviewed["dataset_use_status"] == "review_candidate"
    assert reviewed["expert_target"]["source"] == "reviewer_feedback"
    assert reviewed["expert_target"]["reviewer"] == "ai-reviewer-codex-primary-findings"
    assert dataset["quality_summary"]["training_ready_sample_count"] == 0
    assert dataset["quality_summary"]["review_candidate_sample_count"] == 4
    assert dataset["quality_summary"]["next_review_finding_id"] == "finding-1"


def test_research_understanding_feedback_service_keeps_ai_correct_feedback_silver():
    repository = FakeEvaluationRepository()
    repository.feedback = (
        ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": "ruf-ai-correct",
                "collection_id": "col-gold",
                "scope_type": "goal",
                "scope_id": "goal-1",
                "finding_id": "finding-1",
                "claim_id": "claim-1",
                "review_status": "correct",
                "issue_type": "none",
                "note": "AI reviewer confirms source support; keep pending human expert confirmation.",
                "reviewer": "ai-reviewer-codex-primary-findings",
                "created_at": "2026-06-18T10:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    reviewed = by_finding["finding-1"]
    assert reviewed["label_status"] == "silver"
    assert reviewed["dataset_use_status"] == "review_candidate"
    assert reviewed["expert_target"]["source"] == "ai_review_feedback"
    assert reviewed["expert_target"]["review_status"] == "correct"
    assert reviewed["expert_target"]["reviewer"] == "ai-reviewer-codex-primary-findings"
    assert dataset["quality_summary"]["training_ready_sample_count"] == 0
    assert dataset["quality_summary"]["review_candidate_sample_count"] == 4
    assert dataset["quality_summary"]["next_review_finding_id"] == "finding-1"
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "partial_review": 1,
        "candidate": 3,
    }


def test_research_understanding_feedback_service_keeps_ai_curation_silver():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-ai-1",
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
                "note": "AI reviewer-authored curation should remain silver until human expert confirmation.",
                "reviewer": "ai-reviewer-codex-primary-findings",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    reviewed = by_finding["finding-1"]
    assert reviewed["label_status"] == "silver"
    assert reviewed["dataset_use_status"] == "review_candidate"
    assert reviewed["expert_target"]["source"] == "ai_curation"
    assert reviewed["expert_target"]["reviewer"] == "ai-reviewer-codex-primary-findings"
    assert dataset["quality_summary"]["training_ready_sample_count"] == 0
    assert dataset["quality_summary"]["review_candidate_sample_count"] == 4
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "ai_curated_suggestion": 1,
        "candidate": 3,
    }


def test_research_understanding_feedback_service_keeps_anonymous_curation_silver():
    repository = FakeEvaluationRepository()
    repository.curations = (
        ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": "ruc-anonymous-1",
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
                "note": "Curated statement is usable for review, but reviewer identity is missing.",
                "updated_at": "2026-06-18T11:00:00+00:00",
            }
        ),
    )
    service = ResearchUnderstandingFeedbackService(
        evaluation_repository=repository,
        core_fact_repository=FakeResearchUnderstandingRepository(_sample_understanding()),
        research_understanding_service=FakeResearchUnderstandingProjectionService(),
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        scope_type="goal",
        scope_id="goal-1",
    )

    by_finding = {item["finding_id"]: item for item in dataset["items"]}
    reviewed = by_finding["finding-1"]
    assert reviewed["label_status"] == "silver"
    assert reviewed["dataset_use_status"] == "review_candidate"
    assert reviewed["expert_target"]["source"] == "unverified_curation"
    assert reviewed["expert_target"]["reviewer"] is None
    assert dataset["quality_summary"]["training_ready_sample_count"] == 0
    assert dataset["quality_summary"]["review_candidate_sample_count"] == 4
    assert dataset["quality_summary"]["by_quality_decision"] == {
        "unverified_curation": 1,
        "candidate": 3,
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
    assert dataset["quality_summary"]["total_samples"] == 0
    assert dataset["quality_summary"]["by_label_status"] == {
        "candidate": 0,
        "silver": 0,
        "gold": 0,
        "rejected": 0,
    }


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
