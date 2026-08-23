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
    PaperSkim,
    PaperStudyDisposition,
    ResearchObjective,
)
from domain.core.paper_fact import PaperFactSet
from domain.evaluation import FindingCuration, FindingFeedback
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.objective_review_repository import InMemoryObjectiveReviewRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_TEMPERATURE_STRENGTH_RELATIONSHIP_ID = (
    "relationship-doc-1-temperature-strength"
)
_TEMPERATURE_STRENGTH_STUDY_ID = "study-doc-1-temperature-strength"


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

    async def get_collection(self, collection_id: str) -> dict:
        if collection_id not in self.existing:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        return {"collection_id": collection_id, "name": "Gold collection"}

    async def list_files(self, collection_id: str) -> list[dict]:
        await self.get_collection(collection_id)
        return list(self.files_by_collection.get(collection_id, []))

    async def get_import_manifest(self, collection_id: str) -> dict:
        await self.get_collection(collection_id)
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

    async def upsert_gold_set(self, gold_set, gold_items) -> None:
        self.gold_set = gold_set
        self.gold_items = gold_items

    async def read_gold_set(self, gold_id: str):
        if self.gold_set and self.gold_set.gold_id == gold_id:
            return self.gold_set
        return None

    async def list_gold_items(self, gold_id: str):  # noqa: ARG002
        return self.gold_items

    async def upsert_prediction_snapshot(self, snapshot) -> None:
        self.snapshot = snapshot

    async def read_prediction_snapshot(self, snapshot_id: str):
        if self.snapshot and self.snapshot.snapshot_id == snapshot_id:
            return self.snapshot
        return None

    async def upsert_evaluation_run(self, run) -> None:
        self.run = run

    async def upsert_feedback(self, feedback):
        self.feedback = (
            feedback,
            *(
                item
                for item in getattr(self, "feedback", ())
                if item.feedback_id != feedback.feedback_id
            ),
        )
        return feedback

    async def upsert_curation(self, curation):
        self.curations = (
            curation,
            *(
                item
                for item in getattr(self, "curations", ())
                if item.curation_id != curation.curation_id
            ),
        )
        return curation

    async def list_curations(
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

    async def list_feedback(
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


async def test_evaluation_gold_service_registers_gold_set_for_collection():
    repository = FakeEvaluationRepository()
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )

    gold_set = await service.register_gold_set(
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


async def test_evaluation_gold_service_accepts_collection_file_storage_key():
    repository = FakeEvaluationRepository()
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=repository,
    )

    await service.register_gold_set(
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


async def test_evaluation_gold_service_rejects_missing_collection():
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(existing=set()),
        evaluation_repository=FakeEvaluationRepository(),
    )

    with pytest.raises(FileNotFoundError):
        await service.register_gold_set(
            collection_id="missing",
            gold_id="gold-v1",
            items=[],
        )


async def test_evaluation_gold_service_rejects_gold_item_outside_collection():
    service = EvaluationGoldService(
        collection_service=FakeCollectionService(),
        evaluation_repository=FakeEvaluationRepository(),
    )

    with pytest.raises(ValueError, match="gold item document is not in collection"):
        await service.register_gold_set(
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


async def _published_objective_repository() -> MemoryObjectiveRepository:
    repository = MemoryObjectiveRepository()
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-gold",
            "objective_id": "obj-1",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "seed_document_ids": ["doc-1"],
            "confidence": 0.9,
            "source_relationship_ids": [_TEMPERATURE_STRENGTH_RELATIONSHIP_ID],
            "rank": 1,
        }
    )
    skim = PaperSkim.from_mapping(
        {
            "document_id": "doc-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": _TEMPERATURE_STRENGTH_STUDY_ID,
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": list(objective.material_scope),
                    "relationships": [
                        {
                            "relationship_id": (
                                _TEMPERATURE_STRENGTH_RELATIONSHIP_ID
                            ),
                            "varied_factors": list(objective.variables),
                            "outcome": objective.outcomes[0],
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "block-7",
                                }
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )
    await repository.replace(
        "col-gold",
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(skim,),
            research_objectives=(objective,),
            study_dispositions=(
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": "doc-1",
                        "study_id": _TEMPERATURE_STRENGTH_STUDY_ID,
                        "relationship_id": _TEMPERATURE_STRENGTH_RELATIONSHIP_ID,
                        "status": "promoted",
                        "objective_id": objective.objective_id,
                    }
                ),
            ),
        ),
    )
    await repository.confirm_objective("col-gold", "obj-1")
    _, analysis = await repository.queue_analysis(
        "col-gold",
        "obj-1",
        pipeline_version="test.v1",
        model_name="model-1",
        prompt_versions={},
    )
    running = await repository.claim_analysis(
        "col-gold",
        "obj-1",
        analysis.analysis_version,
    )
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
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "strength",
                "value": 620,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "At 500 C, tensile strength increased to 620 MPa.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [{"name": "test", "value": "tensile"}],
            },
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
            "statement": "Higher temperature was associated with greater strength.",
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "insufficient_confirmation",
            "certainty": 0.5,
            "display_rank": 0,
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Alloy A"}],
                "sample": [],
                "process": [],
                "test": [{"name": "test", "value": "tensile"}],
            },
            "limitations": ["Only one paper directly supports this Finding."],
            "paper_contributions": [
                {
                    "document_id": "doc-1",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-1"],
                }
            ],
        }
    )
    await repository.publish_analysis(
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


async def _finding_feedback_service() -> FindingFeedbackService:
    return FindingFeedbackService(
        review_repository=InMemoryObjectiveReviewRepository(),
        objective_repository=await _published_objective_repository(),
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


async def test_prediction_snapshot_exports_published_findings_with_exact_evidence() -> None:
    service, evaluation_repository = _prediction_snapshot_service(
        await _published_objective_repository()
    )

    snapshot = await service.create_core_snapshot(
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


async def test_prediction_snapshot_rejects_unconfirmed_objective() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": "col-gold",
            "objective_id": "obj-candidate",
            "question": "How does temperature affect strength?",
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "seed_document_ids": ["doc-1"],
            "confidence": 0.9,
            "source_relationship_ids": [_TEMPERATURE_STRENGTH_RELATIONSHIP_ID],
            "rank": 1,
        }
    )
    skim = PaperSkim.from_mapping(
        {
            "document_id": "doc-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": _TEMPERATURE_STRENGTH_STUDY_ID,
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": list(objective.material_scope),
                    "relationships": [
                        {
                            "relationship_id": (
                                _TEMPERATURE_STRENGTH_RELATIONSHIP_ID
                            ),
                            "varied_factors": list(objective.variables),
                            "outcome": objective.outcomes[0],
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "block-7",
                                }
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )
    repository = MemoryObjectiveRepository.from_facts(
        "col-gold",
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(skim,),
            research_objectives=(objective,),
            study_dispositions=(
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": "doc-1",
                        "study_id": _TEMPERATURE_STRENGTH_STUDY_ID,
                        "relationship_id": _TEMPERATURE_STRENGTH_RELATIONSHIP_ID,
                        "status": "promoted",
                        "objective_id": objective.objective_id,
                    }
                ),
            ),
        ),
    )
    service, _evaluation_repository = _prediction_snapshot_service(repository)

    with pytest.raises(CoreArtifactsNotReadyForEvaluationError):
        await service.create_core_snapshot(
            collection_id="col-gold",
            fact_source="objective_first",
        )


async def test_finding_feedback_rejects_stale_analysis_version() -> None:
    service = await _finding_feedback_service()

    with pytest.raises(ValueError, match="published analysis version"):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=2,
            finding_id="finding-1",
            review_status="correct",
            issue_type="none",
        )


async def test_finding_feedback_rejects_inconsistent_review_decisions() -> None:
    service = await _finding_feedback_service()

    with pytest.raises(ValueError, match="correct finding feedback cannot report"):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            review_status="correct",
            issue_type="evidence_not_grounded",
        )
    with pytest.raises(ValueError, match="partial finding feedback requires an issue"):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            review_status="partial",
            issue_type="none",
        )


async def test_finding_review_rejects_unknown_status_values() -> None:
    service = await _finding_feedback_service()
    published = await service.objective_repository.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    assert published is not None

    with pytest.raises(ValueError, match="unsupported finding review status"):
        await service.record_feedback(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            review_status="bogus",
            issue_type="none",
        )
    with pytest.raises(ValueError, match="unsupported finding curation status"):
        await service.record_curation(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            curated_status="bogus",
            curated_finding=published.to_record(),
        )


async def test_finding_curation_rejects_evidence_outside_published_finding() -> None:
    service = await _finding_feedback_service()
    published = await service.objective_repository.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    assert published is not None
    curated = published.to_record()
    curated["paper_contributions"][0]["supporting_evidence_ids"] = ["evidence-outside"]

    with pytest.raises(ValueError, match="references missing evidence"):
        await service.record_curation(
            collection_id="col-gold",
            objective_id="obj-1",
            analysis_version=1,
            finding_id="finding-1",
            curated_status="limited",
            curated_finding=curated,
        )


async def test_latest_feedback_or_curation_controls_dataset_status() -> None:
    service = await _finding_feedback_service()
    candidate = (
        await service.export_dataset(collection_id="col-gold", objective_id="obj-1")
    )["items"][0]
    assert candidate["dataset_use_status"] == "review_candidate"
    assert candidate["training_messages"] == []

    published = await service.objective_repository.read_finding(
        "col-gold", "obj-1", 1, "finding-1"
    )
    assert published is not None
    identity = {
        "collection_id": "col-gold",
        "objective_id": "obj-1",
        "analysis_version": 1,
        "finding_id": "finding-1",
    }
    await service.review_repository.upsert_curation(
        FindingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                **identity,
                "curated_status": "limited",
                "curated_finding": published.to_record(),
                "updated_at": "2026-08-02T10:00:00+00:00",
            }
        )
    )
    await service.review_repository.upsert_feedback(
        FindingFeedback.from_mapping(
            {
                "feedback_id": "feedback-1",
                **identity,
                "review_status": "incorrect",
                "issue_type": "overclaim",
                "created_at": "2026-08-02T11:00:00+00:00",
            }
        )
    )

    rejected = (
        await service.export_dataset(collection_id="col-gold", objective_id="obj-1")
    )["items"][0]
    assert rejected["label_status"] == "rejected"
    assert rejected["dataset_use_status"] == "rejected"
    assert rejected["expert_target"] is None
    assert rejected["training_messages"] == []

    await service.review_repository.upsert_curation(
        FindingCuration.from_mapping(
            {
                "curation_id": "curation-1",
                **identity,
                "curated_status": "limited",
                "curated_finding": published.to_record(),
                "updated_at": "2026-08-02T12:00:00+00:00",
            }
        )
    )

    curated = (
        await service.export_dataset(collection_id="col-gold", objective_id="obj-1")
    )["items"][0]
    assert curated["label_status"] == "gold"
    assert curated["dataset_use_status"] == "training_ready"
    assert curated["expert_target"] == published.to_record()


async def test_finding_feedback_export_contains_exact_source_text() -> None:
    service = await _finding_feedback_service()
    await service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="correct",
        issue_type="none",
        reviewer="expert-1",
    )

    dataset = await service.export_dataset(
        collection_id="col-gold",
        objective_id="obj-1",
    )

    assert len(dataset["items"]) == 1
    sample = dataset["items"][0]
    assert sample["label_status"] == "gold"
    assert sample["dataset_use_status"] == "training_ready"
    assert sample["system_prediction"]["factors"] == ["temperature"]
    assert sample["training_target"]["outcome"] == "strength"
    assert sample["finding_fingerprint"].startswith("finding.v2:")
    assert sample["evidence_fingerprint"].startswith("evidence.v2:")
    assert sample["evidence"][0]["source_excerpt"] == (
        "At 500 C, tensile strength increased to 620 MPa."
    )
    assert "At 500 C" in sample["training_messages"][0]["content"]
    assert sample["metadata"]["analysis_version"] == 1
    assert sample["metadata"]["finding_fingerprint"] == sample["finding_fingerprint"]
    assert "claim_id" not in str(sample)


@pytest.mark.parametrize(
    ("snapshot_change", "expected_reason"),
    [
        ({"analysis_version": 2}, "source_analysis_version_changed"),
        ({"finding_fingerprint": "finding.v2:changed"}, "source_finding_changed"),
        ({"evidence_fingerprint": "evidence.v2:changed"}, "source_evidence_changed"),
        ({"evidence_ids": ["evidence-replaced"]}, "source_evidence_ids_changed"),
    ],
)
async def test_finding_source_snapshot_detects_each_stale_dimension(
    snapshot_change: dict,
    expected_reason: str,
) -> None:
    service = await _finding_feedback_service()
    await service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="correct",
        issue_type="none",
    )
    item = (await service.export_dataset(
        collection_id="col-gold",
        objective_id="obj-1",
    ))["items"][0]
    source_finding = {
        "finding_id": item["finding_id"],
        "analysis_version": item["analysis_version"],
        "finding_fingerprint": item["finding_fingerprint"],
        "evidence_fingerprint": item["evidence_fingerprint"],
        "evidence_ids": [entry["evidence_id"] for entry in item["evidence"]],
        **snapshot_change,
    }

    validity, reasons = await service.source_snapshot_validity(
        collection_id="col-gold",
        objective_id="obj-1",
        source_findings=[source_finding],
    )

    assert validity == "stale"
    assert reasons == [expected_reason]


async def test_finding_source_snapshot_is_stale_when_dataset_is_unavailable() -> None:
    service = await _finding_feedback_service()

    validity, reasons = await service.source_snapshot_validity(
        collection_id="missing-collection",
        objective_id="missing-objective",
        source_findings=[{"finding_id": "finding-1"}],
    )

    assert validity == "stale"
    assert reasons == ["source_dataset_unavailable"]


async def test_only_training_ready_samples_include_training_messages() -> None:
    candidate_service = await _finding_feedback_service()
    candidate = (await candidate_service.export_dataset(
        collection_id="col-gold",
        objective_id="obj-1",
    ))["items"][0]
    assert candidate["dataset_use_status"] == "review_candidate"
    assert candidate["training_messages"] == []

    rejected_service = await _finding_feedback_service()
    await rejected_service.record_feedback(
        collection_id="col-gold",
        objective_id="obj-1",
        analysis_version=1,
        finding_id="finding-1",
        review_status="incorrect",
        issue_type="overclaim",
    )
    rejected = (await rejected_service.export_dataset(
        collection_id="col-gold",
        objective_id="obj-1",
    ))["items"][0]
    assert rejected["dataset_use_status"] == "rejected"
    assert rejected["training_messages"] == []
