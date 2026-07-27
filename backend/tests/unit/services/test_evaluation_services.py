from __future__ import annotations

import pytest

from application.evaluation.core_evaluation_service import CoreEvaluationService
from application.evaluation.gold_service import EvaluationGoldService
from application.evaluation.prediction_snapshot_service import (
    CoreArtifactsNotReadyForEvaluationError,
    EvaluationPredictionSnapshotService,
)
from application.evaluation.finding_feedback_service import (
    FindingFeedbackService,
)
from domain.core import (
    Finding,
    MeasurementResult,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    ResearchObjective,
)
from domain.core.paper_fact import PaperFactSet
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.objective_review_repository import InMemoryObjectiveReviewRepository


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
                    "storage_key": "col-gold/input/paper-1.pdf",
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
                            "storage_key": "col-gold/input/paper-1.pdf",
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

    def upsert_feedback(self, feedback):
        self.feedback = (
            feedback,
            *(
                item
                for item in getattr(self, "feedback", ())
                if item.feedback_id != feedback.feedback_id
            ),
        )
        return feedback

    def upsert_curation(self, curation):
        self.curations = (
            curation,
            *(
                item
                for item in getattr(self, "curations", ())
                if item.curation_id != curation.curation_id
            ),
        )
        return curation

    def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ):
        return tuple(
            curation
            for curation in getattr(self, "curations", ())
            if curation.collection_id == collection_id
            and (objective_id is None or curation.objective_id == objective_id)
            and (
                analysis_version is None
                or curation.analysis_version == analysis_version
            )
            and (finding_id is None or curation.finding_id == finding_id)
        )

    def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ):
        return tuple(
            feedback
            for feedback in getattr(self, "feedback", ())
            if feedback.collection_id == collection_id
            and (objective_id is None or feedback.objective_id == objective_id)
            and (
                analysis_version is None
                or feedback.analysis_version == analysis_version
            )
            and (finding_id is None or feedback.finding_id == finding_id)
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


def test_evaluation_gold_service_accepts_collection_file_storage_key():
    repository = FakeEvaluationRepository()
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )

    service.register_gold_set(
        collection_id="col-gold",
        gold_id="gold-by-storage-key",
        items=[
            {
                "gold_item_id": "gold-storage-key-1",
                "document_id": "col-gold/input/paper-1.pdf",
                "family": "measurement_results",
                "item_key": "paper-1:sample-a:yield_strength",
                "payload": {"metric": "yield_strength", "value": 520, "unit": "MPa"},
            }
        ],
    )

    assert repository.gold_items[0].document_id == "col-gold/input/paper-1.pdf"


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


def _published_objective_repository() -> MemoryObjectiveRepository:
    repository = MemoryObjectiveRepository()
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-gold",
            "objective_id": "obj-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "process_axes": ["temperature"],
            "property_axes": ["strength"],
            "seed_document_ids": ["doc-1"],
            "confidence": 0.9,
        }
    )
    repository.replace(
        "col-gold",
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            research_objectives=(objective,),
        ),
    )
    repository.confirm_objective("col-gold", "obj-1")
    _, analysis = repository.queue_analysis(
        "col-gold",
        "obj-1",
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={},
    )
    running = repository.claim_analysis("col-gold", "obj-1", analysis.analysis_version)
    assert running is not None
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col-gold",
            "objective_id": "obj-1",
            "analysis_version": 1,
            "evidence_id": "evidence-1",
            "document_id": "doc-1",
            "source_kind": "text_window",
            "source_ref": "block-7",
            "source_excerpt": "At 500 C, tensile strength increased to 620 MPa.",
            "page_numbers": [7],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "evidence_kind": "measurement",
            "property_normalized": "strength",
            "value_payload": {"value": 620, "unit": "MPa"},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    finding = Finding.from_mapping(
        {
            "collection_id": "col-gold",
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
                "contributing_document_ids": ["doc-1"],
                "supporting_evidence_ids": ["evidence-1"],
                "rationale": "One direct paper result.",
            },
        }
    )
    repository.publish_analysis(
        "col-gold",
        "obj-1",
        1,
        contributions=(
            PaperContribution.from_mapping(
                {
                    "collection_id": "col-gold",
                    "objective_id": "obj-1",
                    "analysis_version": 1,
                    "document_id": "doc-1",
                    "analysis_status": "analyzed",
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "confidence": 0.9,
                }
            ),
        ),
        evidence_records=(evidence,),
        findings=(finding,),
    )
    return repository


def _finding_feedback_service() -> FindingFeedbackService:
    return FindingFeedbackService(
        review_repository=InMemoryObjectiveReviewRepository(),
        objective_repository=_published_objective_repository(),
    )


def _prediction_snapshot_service(
    objective_repository: MemoryObjectiveRepository,
) -> tuple[EvaluationPredictionSnapshotService, FakeEvaluationRepository]:
    evaluation_repository = FakeEvaluationRepository()
    return (
        EvaluationPredictionSnapshotService(
            collection_service=FakeCollectionService(),
            paper_fact_repository=MemoryPaperFactRepository(),
            objective_repository=objective_repository,
            comparison_repository=MemoryComparisonRepository(),
            evaluation_repository=evaluation_repository,
        ),
        evaluation_repository,
    )


def test_prediction_snapshot_exports_published_findings_with_exact_evidence() -> None:
    service, evaluation_repository = _prediction_snapshot_service(
        _published_objective_repository()
    )

    snapshot = service.create_core_snapshot(
        collection_id="col-gold",
        fact_source="objective_first",
        snapshot_id="snapshot-1",
    )

    assert evaluation_repository.snapshot == snapshot
    assert snapshot.artifact_counts["published_objective_analyses"] == 1
    assert snapshot.artifact_counts["objective_findings"] == 1
    assert snapshot.artifact_counts["objective_evidence"] == 1
    assert "objective_evidence_units" not in snapshot.artifact_counts
    assert "objective_logic_chains" not in snapshot.artifact_counts
    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.family == "objective_findings"
    assert item.item_key == "obj-1:v1:finding-1"
    assert item.payload["analysis_version"] == 1
    assert item.payload["finding_id"] == "finding-1"
    assert item.payload["evidence"][0]["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert item.source_refs == (
        {
            "evidence_id": "evidence-1",
            "document_id": "doc-1",
            "source_kind": "text_window",
            "source_ref": "block-7",
            "source_excerpt": "At 500 C, tensile strength increased to 620 MPa.",
            "page_numbers": [7],
            "related_source_refs": [],
        },
    )


def test_prediction_snapshot_rejects_unpublished_objective_candidates() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-gold",
            "objective_id": "obj-candidate",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "process_axes": ["temperature"],
            "property_axes": ["strength"],
            "seed_document_ids": ["doc-1"],
            "confidence": 0.9,
        }
    )
    repository = MemoryObjectiveRepository.from_facts(
        "col-gold",
        ObjectiveFactSet(
            research_objectives_ready=True,
            research_objectives=(objective,),
        ),
    )
    service, _evaluation_repository = _prediction_snapshot_service(repository)

    with pytest.raises(CoreArtifactsNotReadyForEvaluationError):
        service.create_core_snapshot(
            collection_id="col-gold",
            fact_source="objective_first",
        )


def test_finding_feedback_rejects_stale_analysis_version() -> None:
    service = _finding_feedback_service()

    with pytest.raises(ValueError, match="published analysis version"):
        service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=2,
            finding_id="finding-1",
            review_status="correct",
            issue_type="none",
        )


def test_finding_feedback_export_contains_exact_source_text() -> None:
    service = _finding_feedback_service()
    service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="correct",
        issue_type="none",
        reviewer="expert-1",
    )

    dataset = service.export_dataset(
        collection_id="col-gold",
        objective_id="obj-1",
    )

    assert len(dataset["items"]) == 1
    sample = dataset["items"][0]
    assert sample["label_status"] == "gold"
    assert sample["dataset_use_status"] == "training_ready"
    assert sample["evidence"][0]["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert "At 500 C" in sample["training_messages"][0]["content"]
    assert sample["metadata"]["analysis_version"] == 1
    assert "claim_id" not in str(sample)
