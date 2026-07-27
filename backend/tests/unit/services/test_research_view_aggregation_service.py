from __future__ import annotations

from unittest.mock import Mock

import pytest

from application.core.comparison_service import ComparisonRowsNotReadyError
from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
    ResearchViewMaterialNotFoundError,
    ResearchViewNotReadyError,
)
from domain.core import (
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    SampleVariant,
    TestCondition as DomainTestCondition,
)
from domain.core.paper_fact import PaperFactSet
from tests.support.paper_fact_repository import MemoryPaperFactRepository


COLLECTION_ID = "col-1"


def _paper_facts() -> PaperFactSet:
    return PaperFactSet(
        paper_facts_ready=True,
        document_profiles=(
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-1",
                    "collection_id": COLLECTION_ID,
                    "title": "LPBF 316L paper",
                    "doc_type": "experimental",
                    "candidate_materials": ["316L stainless steel"],
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
                    "quote": "The yield strength was 520 MPa.",
                }
            ),
        ),
        sample_variants=(
            SampleVariant.from_mapping(
                {
                    "variant_id": "sample-annealed",
                    "document_id": "paper-1",
                    "collection_id": COLLECTION_ID,
                    "variant_label": "annealed",
                    "host_material_system": {"family": "316L stainless steel"},
                    "process_context": {"post_treatment_summary": "annealed"},
                    "source_anchor_ids": ["anchor-1"],
                }
            ),
        ),
        test_conditions=(
            DomainTestCondition.from_mapping(
                {
                    "test_condition_id": "test-tensile",
                    "document_id": "paper-1",
                    "collection_id": COLLECTION_ID,
                    "property_type": "tensile_mechanics",
                    "template_type": "tensile",
                    "scope_level": "sample",
                    "condition_payload": {"method": "tensile"},
                    "condition_completeness": "complete",
                }
            ),
        ),
        measurement_results=(
            MeasurementResult.from_mapping(
                {
                    "result_id": "result-yield",
                    "document_id": "paper-1",
                    "collection_id": COLLECTION_ID,
                    "variant_id": "sample-annealed",
                    "property_normalized": "yield_strength",
                    "result_type": "scalar",
                    "value_payload": {"value": 520.0},
                    "unit": "MPa",
                    "test_condition_id": "test-tensile",
                    "evidence_anchor_ids": ["anchor-1"],
                    "traceability_status": "direct",
                    "result_source_type": "table",
                }
            ),
        ),
    )


def _service(*, has_files: bool = True, facts: PaperFactSet | None = None):
    collection_service = Mock()
    collection_service.get_collection.return_value = {
        "collection_id": COLLECTION_ID,
        "paper_count": 1 if has_files else 0,
    }
    collection_service.list_files.return_value = (
        [{"filename": "paper.pdf"}] if has_files else []
    )
    repository = MemoryPaperFactRepository()
    if facts is not None:
        repository.replace_document_profiles(
            COLLECTION_ID,
            "build_test",
            facts.document_profiles,
        )
        repository.replace_paper_facts(COLLECTION_ID, "build_test", facts)
    comparison_service = Mock()
    comparison_service.read_comparison_projection.side_effect = (
        ComparisonRowsNotReadyError(COLLECTION_ID)
    )
    return ResearchViewAggregationService(
        collection_service=collection_service,
        paper_fact_repository=repository,
        comparison_service=comparison_service,
    )


def test_collection_research_view_returns_empty_state_without_files():
    payload = _service(has_files=False).get_collection_research_view(COLLECTION_ID)

    assert payload["state"] == "empty"
    assert payload["materials"] == []


def test_collection_research_view_requires_reusable_paper_facts():
    with pytest.raises(ResearchViewNotReadyError):
        _service().get_collection_research_view(COLLECTION_ID)


def test_collection_materials_and_profile_come_from_paper_facts():
    service = _service(facts=_paper_facts())

    materials = service.list_collection_materials(COLLECTION_ID)

    assert len(materials["materials"]) == 1
    material = materials["materials"][0]
    assert material["canonical_name"] == "316L stainless steel"
    profile = service.get_collection_material_research_view(
        COLLECTION_ID,
        material["material_id"],
    )
    assert profile["canonical_name"] == "316L stainless steel"
    assert profile["sample_matrix"]["rows"][0]["sample_label"] == "annealed"
    assert profile["measured_properties"][0]["property"] == "yield_strength"
    assert profile["measured_properties"][0]["display_range"] == "520 MPa"
    assert "understanding" not in profile


def test_document_research_view_preserves_source_backed_measurement():
    service = _service(facts=_paper_facts())

    payload = service.get_document_research_view(COLLECTION_ID, "paper-1")

    assert payload["paper_title"] == "LPBF 316L paper"
    assert payload["sample_matrix"]["rows"][0]["sample_label"] == "annealed"
    value = payload["sample_matrix"]["rows"][0]["values"]["yield_strength"]
    assert value["value"] == 520.0
    assert value["display_value"] == "520.0 MPa"
    assert value["unit"] == "MPa"
    assert value["evidence_refs"][0]["fact_ids"] == ["result-yield"]
    assert value["evidence_refs"][0]["locator"]["quote"] == (
        "The yield strength was 520 MPa."
    )


def test_missing_material_is_explicit():
    with pytest.raises(ResearchViewMaterialNotFoundError):
        _service(facts=_paper_facts()).get_collection_material_research_view(
            COLLECTION_ID,
            "mat-missing",
        )
