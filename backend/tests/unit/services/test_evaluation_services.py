from __future__ import annotations

import pytest

from application.evaluation.core_evaluation_service import CoreEvaluationService
from application.evaluation.gold_service import EvaluationGoldService
from application.evaluation.prediction_snapshot_service import (
    CoreArtifactsNotReadyForEvaluationError,
    EvaluationPredictionSnapshotService,
)
from domain.core import CoreFactSet, MeasurementResult, ObjectiveEvidenceUnit


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


class FakeCoreFactRepository:
    backend_name = "fake"

    def __init__(self, facts: CoreFactSet) -> None:
        self.facts = facts

    def read_collection_facts(self, collection_id: str) -> CoreFactSet:  # noqa: ARG002
        return self.facts


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
