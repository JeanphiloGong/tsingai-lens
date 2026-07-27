from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from domain.core import MeasurementResult, SampleVariant, TestCondition as DomainTestCondition
from domain.core.paper_fact import PaperFactSet
from tests.support.comparison_repository import MemoryComparisonRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository


class FakeCollectionService:
    def get_collection(self, collection_id: str) -> dict:
        return {"collection_id": collection_id, "name": "Paper facts collection"}


def _service(paper_facts: PaperFactSet) -> tuple[ComparisonService, MemoryComparisonRepository]:
    paper_repository = MemoryPaperFactRepository()
    paper_repository.replace_paper_facts("col-1", "build_test", paper_facts)
    comparison_repository = MemoryComparisonRepository()
    return (
        ComparisonService(
            collection_service=FakeCollectionService(),
            document_profile_service=SimpleNamespace(),
            paper_fact_repository=paper_repository,
            comparison_repository=comparison_repository,
        ),
        comparison_repository,
    )


def _paper_facts() -> PaperFactSet:
    return PaperFactSet(
        paper_facts_ready=True,
        sample_variants=(
            SampleVariant.from_mapping(
                {
                    "variant_id": "sample-as-built",
                    "document_id": "paper-1",
                    "collection_id": "col-1",
                    "variant_label": "as-built",
                    "host_material_system": {"family": "316L stainless steel"},
                    "process_context": {"process": "LPBF"},
                }
            ),
        ),
        test_conditions=(
            DomainTestCondition.from_mapping(
                {
                    "test_condition_id": "test-polarization",
                    "document_id": "paper-1",
                    "collection_id": "col-1",
                    "property_type": "corrosion",
                    "template_type": "electrochemical",
                    "scope_level": "sample",
                    "condition_payload": {"method": "polarization"},
                    "condition_completeness": "complete",
                }
            ),
        ),
        measurement_results=(
            MeasurementResult.from_mapping(
                {
                    "result_id": "result-as-built-icorr",
                    "document_id": "paper-1",
                    "collection_id": "col-1",
                    "variant_id": "sample-as-built",
                    "property_normalized": "corrosion current density",
                    "result_type": "scalar",
                    "value_payload": {"value": 1.2, "source_value_text": "1.2 uA/cm2"},
                    "unit": "uA/cm2",
                    "test_condition_id": "test-polarization",
                    "result_source_type": "table",
                }
            ),
        ),
    )


def test_comparison_service_projects_rows_from_paper_facts():
    service, repository = _service(_paper_facts())

    rows = service.build_comparison_rows("col-1", "build_test")

    assert len(rows) == 1
    facts = repository.read("col-1")
    assert len(facts.comparable_results) == 1
    assert len(facts.collection_comparable_results) == 1
    assert service.read_comparison_rows("col-1") == rows
    assert facts.comparable_results[0].source_result_id == "result-as-built-icorr"
    assert rows[0].material_system_normalized == "316L stainless steel"
    assert rows[0].property_normalized == "corrosion current density"
    assert rows[0].value == 1.2


def test_comparison_service_requires_measurement_results():
    service, _repository = _service(PaperFactSet(paper_facts_ready=True))

    with pytest.raises(ComparisonRowsNotReadyError):
        service.build_comparison_rows("col-1", "build_test")
