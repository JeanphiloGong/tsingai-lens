from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
)
from application.core.workspace_overview_service import WorkspaceService
from application.derived.graph_service import load_graph_payload
from application.evaluation.prediction_snapshot_service import (
    EvaluationPredictionSnapshotService,
)
from domain.core import (
    ComparisonFactSet,
    DocumentProfile,
    ObjectiveEvidenceUnit,
    ObjectiveFactSet,
    ResearchObjective,
)
from domain.core.paper_fact import PaperFactSet
from domain.source import SourceArtifactSet
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository


COLLECTION_ID = "col-focused"
PROFILE = DocumentProfile.from_mapping(
    {
        "document_id": "doc-1",
        "collection_id": COLLECTION_ID,
        "title": "Focused read paper",
        "source_filename": "paper.pdf",
        "doc_type": "experimental",
        "confidence": 0.95,
    }
)
PAPER_FACTS = PaperFactSet(paper_facts_ready=True)
OBJECTIVE_FACTS = ObjectiveFactSet(
    research_objectives_ready=True,
    research_objectives=(
        ResearchObjective.from_mapping(
            {
                "objective_id": "obj-1",
                "question": "How does heat treatment affect yield strength?",
                "material_scope": ["316L stainless steel"],
                "process_axes": ["heat treatment"],
                "property_axes": ["yield strength"],
                "seed_document_ids": ["doc-1"],
                "confidence": 0.9,
            }
        ),
    ),
    objective_evidence_units=(
        ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": "unit-1",
                "objective_id": "obj-1",
                "document_id": "doc-1",
                "unit_kind": "measurement",
                "material_system": {"name": "316L stainless steel"},
                "sample_context": {"sample": "annealed"},
                "process_context": {"post_treatment": "annealed"},
                "test_condition": {"method": "tensile"},
                "property_normalized": "yield strength",
                "value_payload": {"value": 520.0, "source_value_text": "520"},
                "unit": "MPa",
                "source_refs": [{"source_kind": "table", "source_ref": "table-1"}],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        ),
    ),
)


def test_workspace_reads_each_semantic_family_once_and_preserves_ready_empty():
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_document_profiles(COLLECTION_ID, "build_test", (PROFILE,))
    paper_repository.replace_paper_facts(COLLECTION_ID, "build_test", PAPER_FACTS)
    objective_repository = MemoryObjectiveRepository.from_facts(
        COLLECTION_ID, OBJECTIVE_FACTS
    )
    comparison_repository = MemoryComparisonRepository()
    comparison_repository.replace(
        COLLECTION_ID,
        "build_test",
        ComparisonFactSet(comparison_artifacts_ready=True),
    )
    paper_repository.read = Mock(wraps=paper_repository.read)
    objective_repository.read = Mock(wraps=objective_repository.read)
    comparison_repository.read = Mock(wraps=comparison_repository.read)
    collection_service = Mock()
    collection_service.get_collection.return_value = {
        "collection_id": COLLECTION_ID,
        "updated_at": "2026-07-20T00:00:00Z",
    }
    collection_service.list_files.return_value = [{"filename": "paper.pdf"}]
    task_service = Mock()
    task_service.list_tasks.return_value = []
    source_repository = Mock()
    source_repository.read_collection_artifacts.return_value = SourceArtifactSet()
    document_profile_service = Mock()
    document_profile_service.get_document_summary.return_value = {
        "total_documents": 1,
        "by_doc_type": {"experimental": 1},
        "warnings": [],
    }
    service = WorkspaceService(
        collection_service,
        task_service,
        source_repository,
        paper_repository,
        objective_repository,
        comparison_repository,
        document_profile_service,
    )

    payload = service.get_workspace_overview(COLLECTION_ID)

    assert payload["artifacts"]["comparison_rows_generated"] is True
    assert payload["artifacts"]["comparison_rows_ready"] is False
    paper_repository.read.assert_called_once_with(COLLECTION_ID)
    objective_repository.read.assert_called_once_with(COLLECTION_ID)
    comparison_repository.read.assert_called_once_with(COLLECTION_ID)


def test_graph_reads_each_semantic_family_once_and_records_payload_volume():
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_document_profiles(COLLECTION_ID, "build_test", (PROFILE,))
    paper_repository.replace_paper_facts(COLLECTION_ID, "build_test", PAPER_FACTS)
    objective_repository = MemoryObjectiveRepository.from_facts(
        COLLECTION_ID, OBJECTIVE_FACTS
    )
    paper_repository.read = Mock(wraps=paper_repository.read)
    objective_repository.read = Mock(wraps=objective_repository.read)
    comparison_service = Mock()
    comparison_service.read_comparison_projection.return_value = SimpleNamespace(
        comparison_rows=()
    )
    collection_service = Mock()
    collection_service.get_collection.return_value = {"collection_id": COLLECTION_ID}

    nodes, edges, truncated = load_graph_payload(
        collection_id=COLLECTION_ID,
        max_nodes=40,
        min_weight=0.0,
        collection_service=collection_service,
        paper_fact_repository=paper_repository,
        objective_repository=objective_repository,
        comparison_service=comparison_service,
    )

    assert truncated is False
    assert len([node for node in nodes if node["type"] == "objective"]) == 1
    assert len(edges) > 0
    paper_repository.read.assert_called_once_with(COLLECTION_ID)
    objective_repository.read.assert_called_once_with(COLLECTION_ID)
    comparison_service.read_comparison_projection.assert_called_once_with(COLLECTION_ID)


def test_research_view_reads_each_consumed_family_once_and_records_payload_volume():
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_document_profiles(COLLECTION_ID, "build_test", (PROFILE,))
    paper_repository.replace_paper_facts(COLLECTION_ID, "build_test", PAPER_FACTS)
    objective_repository = MemoryObjectiveRepository.from_facts(
        COLLECTION_ID, OBJECTIVE_FACTS
    )
    paper_repository.read = Mock(wraps=paper_repository.read)
    objective_repository.read = Mock(wraps=objective_repository.read)
    comparison_service = Mock()
    comparison_service.read_comparison_projection.return_value = SimpleNamespace(
        comparison_rows=()
    )
    collection_service = Mock()
    collection_service.get_collection.return_value = {
        "collection_id": COLLECTION_ID,
        "paper_count": 1,
    }
    collection_service.list_files.return_value = [{"filename": "paper.pdf"}]
    service = ResearchViewAggregationService(
        collection_service=collection_service,
        source_artifact_repository=Mock(),
        paper_fact_repository=paper_repository,
        objective_repository=objective_repository,
        comparison_service=comparison_service,
        research_understanding_service=Mock(),
    )

    payload = service.get_collection_research_view(COLLECTION_ID)

    assert payload["overview"]["document_count"] == 1
    assert payload["overview"]["measurement_count"] == 1
    assert len(payload["materials"]) == 1
    assert len(payload["paper_coverage"]) == 1
    paper_repository.read.assert_called_once_with(COLLECTION_ID)
    objective_repository.read.assert_called_once_with(COLLECTION_ID)
    comparison_service.read_comparison_projection.assert_called_once_with(COLLECTION_ID)


def test_prediction_snapshot_reads_each_semantic_family_once_and_records_items():
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_document_profiles(COLLECTION_ID, "build_test", (PROFILE,))
    paper_repository.replace_paper_facts(COLLECTION_ID, "build_test", PAPER_FACTS)
    objective_repository = MemoryObjectiveRepository.from_facts(
        COLLECTION_ID, OBJECTIVE_FACTS
    )
    comparison_repository = MemoryComparisonRepository()
    comparison_repository.replace(
        COLLECTION_ID,
        "build_test",
        ComparisonFactSet(comparison_artifacts_ready=True),
    )
    paper_repository.read = Mock(wraps=paper_repository.read)
    objective_repository.read = Mock(wraps=objective_repository.read)
    comparison_repository.read = Mock(wraps=comparison_repository.read)
    evaluation_repository = Mock()
    collection_service = Mock()
    collection_service.get_collection.return_value = {"collection_id": COLLECTION_ID}
    service = EvaluationPredictionSnapshotService(
        collection_service=collection_service,
        paper_fact_repository=paper_repository,
        objective_repository=objective_repository,
        comparison_repository=comparison_repository,
        evaluation_repository=evaluation_repository,
    )

    snapshot = service.create_core_snapshot(
        collection_id=COLLECTION_ID,
        fact_source="objective_first",
        snapshot_id="snapshot-focused",
    )

    assert snapshot.artifact_counts["objective_evidence_units"] == 1
    assert len(snapshot.items) == 1
    assert snapshot.items[0].payload["value"] == 520.0
    paper_repository.read.assert_called_once_with(COLLECTION_ID)
    objective_repository.read.assert_called_once_with(COLLECTION_ID)
    comparison_repository.read.assert_called_once_with(COLLECTION_ID)
    evaluation_repository.upsert_prediction_snapshot.assert_called_once_with(snapshot)
