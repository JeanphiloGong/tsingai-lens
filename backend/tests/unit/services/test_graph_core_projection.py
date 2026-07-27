from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.core.comparison_service import ComparisonService
from application.derived.graph_projection_service import load_core_graph_payload
from application.derived.graph_service import GraphNotReadyError, get_collection_graph
from domain.core import (
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    ObjectiveFactSet,
    ResearchObjective,
    SampleVariant,
    TestCondition as DomainTestCondition,
)
from domain.core.paper_fact import PaperFactSet
from tests.support.collection_service import build_test_collection_service
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository


def _objective(collection_id: str) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": collection_id,
            "objective_id": "obj-1",
            "question": "How does scan speed affect LPBF 316L strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan speed"],
            "property_axes": ["yield strength"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0.9,
        }
    )


def _paper_facts(collection_id: str) -> PaperFactSet:
    return PaperFactSet(
        paper_facts_ready=True,
        document_profiles=(
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "title": "Core Graph Paper",
                    "doc_type": "experimental",
                }
            ),
        ),
        evidence_anchors=(
            EvidenceAnchor.from_mapping(
                {
                    "anchor_id": "anchor-1",
                    "document_id": "paper-1",
                    "locator_type": "table",
                    "source_type": "table",
                    "table_id": "table-1",
                    "quote": "The yield strength was 365.6 MPa.",
                }
            ),
        ),
        sample_variants=(
            SampleVariant.from_mapping(
                {
                    "variant_id": "sample-1",
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "variant_label": "as-built",
                    "host_material_system": {"family": "316L stainless steel"},
                    "process_context": {"scan_speed_mm_s": 900},
                }
            ),
        ),
        test_conditions=(
            DomainTestCondition.from_mapping(
                {
                    "test_condition_id": "test-1",
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "property_type": "tensile_mechanics",
                    "template_type": "tensile",
                    "scope_level": "sample",
                    "condition_payload": {"method": "tensile test"},
                    "condition_completeness": "complete",
                }
            ),
        ),
        measurement_results=(
            MeasurementResult.from_mapping(
                {
                    "result_id": "measurement-1",
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "variant_id": "sample-1",
                    "property_normalized": "yield_strength",
                    "result_type": "scalar",
                    "value_payload": {"value": 365.6},
                    "unit": "MPa",
                    "test_condition_id": "test-1",
                    "evidence_anchor_ids": ["anchor-1"],
                    "traceability_status": "direct",
                    "result_source_type": "table",
                }
            ),
        ),
    )


def test_core_projection_keeps_objective_as_definition_only():
    nodes, edges, truncated = load_core_graph_payload(
        profiles=(),
        research_objectives=(_objective("col-1").to_record(),),
        max_nodes=40,
        min_weight=0.0,
    )

    assert truncated is False
    assert [node["id"] for node in nodes] == ["obj:obj-1"]
    assert nodes[0]["type"] == "objective"
    assert edges == []


def test_graph_requires_paper_facts_and_comparison_rows(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection_id = collection_service.create_collection("Empty Graph")["collection_id"]

    with pytest.raises(GraphNotReadyError) as exc_info:
        get_collection_graph(
            collection_id=collection_id,
            max_nodes=40,
            min_weight=0.0,
            collection_service=collection_service,
            paper_fact_repository=MemoryPaperFactRepository(),
            objective_repository=MemoryObjectiveRepository(),
            comparison_service=ComparisonService(
                collection_service=collection_service,
                paper_fact_repository=MemoryPaperFactRepository(),
                comparison_repository=MemoryComparisonRepository(),
                document_profile_service=SimpleNamespace(),
            ),
        )

    assert "core_fact_repository.document_profiles" in exc_info.value.missing_artifacts
    assert "core_fact_repository.comparison_artifacts" in exc_info.value.missing_artifacts


def test_graph_serves_paper_fact_projection_with_objective_definition(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection_id = collection_service.create_collection("Core Graph")["collection_id"]
    paper_repository = MemoryPaperFactRepository()
    facts = _paper_facts(collection_id)
    paper_repository.replace_document_profiles(
        collection_id,
        "build_test",
        facts.document_profiles,
    )
    paper_repository.replace_paper_facts(collection_id, "build_test", facts)
    objective_repository = MemoryObjectiveRepository()
    objective_repository.replace(
        collection_id,
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            research_objectives=(_objective(collection_id),),
        ),
    )
    comparison_repository = MemoryComparisonRepository()
    comparison_service = ComparisonService(
        collection_service=collection_service,
        paper_fact_repository=paper_repository,
        comparison_repository=comparison_repository,
        document_profile_service=SimpleNamespace(),
    )
    comparison_service.build_comparison_rows(collection_id, "build_test")

    payload = get_collection_graph(
        collection_id=collection_id,
        max_nodes=40,
        min_weight=0.0,
        collection_service=collection_service,
        paper_fact_repository=paper_repository,
        objective_repository=objective_repository,
        comparison_service=comparison_service,
    )

    assert payload["collection_id"] == collection_id
    node_types = {node["type"] for node in payload["nodes"]}
    assert "objective" in node_types
    assert "document" in node_types
    assert "comparison" in node_types
    assert "property" in node_types
