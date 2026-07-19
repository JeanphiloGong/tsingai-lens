from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from domain.core import CoreFactSet, ObjectiveEvidenceUnit
from tests.support.paper_fact_repository import MemoryPaperFactRepository


class FakeCollectionService:
    def get_collection(self, collection_id: str) -> dict:
        return {"collection_id": collection_id, "name": "Objective collection"}


class FakeCoreFactRepository:
    backend_name = "fake"

    def __init__(self, facts: CoreFactSet) -> None:
        self.facts = facts
        self.comparable_results = ()
        self.collection_comparable_results = ()
        self.comparison_rows = ()

    def read_collection_facts(self, collection_id: str) -> CoreFactSet:  # noqa: ARG002
        return self.facts

    def replace_collection_comparison_artifacts(
        self,
        collection_id: str,  # noqa: ARG002
        comparable_results: tuple,
        collection_comparable_results: tuple,
        comparison_rows: tuple,
        pairwise_comparison_relations: tuple = (),  # noqa: ARG002
    ) -> None:
        self.comparable_results = comparable_results
        self.collection_comparable_results = collection_comparable_results
        self.comparison_rows = comparison_rows


def test_comparison_service_projects_rows_from_objective_measurements():
    repository = FakeCoreFactRepository(
        CoreFactSet(
            objective_evidence_units=(
                ObjectiveEvidenceUnit.from_mapping(
                    {
                        "evidence_unit_id": "oeu-as-built-icorr",
                        "objective_id": "obj-corrosion",
                        "document_id": "paper-1",
                        "unit_kind": "measurement",
                        "material_system": {"name": "316L stainless steel"},
                        "sample_context": {"sample": "as-built"},
                        "process_context": {"process": "LPBF"},
                        "test_condition": {"method": "polarization"},
                        "property_normalized": "corrosion current density",
                        "value_payload": {
                            "value": 1.2,
                            "source_value_text": "1.2 uA/cm2",
                        },
                        "unit": "uA/cm2",
                        "source_refs": [
                            {"source_kind": "table", "source_ref": "table-1"}
                        ],
                        "evidence_anchor_ids": ["anc-1"],
                        "resolution_status": "resolved",
                    }
                ),
            ),
        )
    )
    service = ComparisonService(
        collection_service=FakeCollectionService(),
        document_profile_service=SimpleNamespace(),
        paper_fact_repository=MemoryPaperFactRepository(),
        core_fact_repository=repository,
    )

    rows = service.build_comparison_rows("col-1")

    assert len(rows) == 1
    assert len(repository.comparable_results) == 1
    assert len(repository.collection_comparable_results) == 1
    assert repository.comparison_rows == rows
    assert rows[0].comparable_result_id == "objective:oeu-as-built-icorr"
    assert rows[0].material_system_normalized == "316L stainless steel"
    assert rows[0].property_normalized == "corrosion current density"
    assert rows[0].value == 1.2


def test_comparison_service_does_not_fall_back_to_paper_facts_for_empty_objective_rows():
    repository = FakeCoreFactRepository(
        CoreFactSet(
            objective_evidence_units=(
                ObjectiveEvidenceUnit.from_mapping(
                    {
                        "evidence_unit_id": "oeu-process",
                        "objective_id": "obj-corrosion",
                        "document_id": "paper-1",
                        "unit_kind": "process_context",
                        "material_system": {"name": "316L stainless steel"},
                        "process_context": {"process": "LPBF"},
                        "resolution_status": "resolved",
                    }
                ),
            ),
        )
    )
    service = ComparisonService(
        collection_service=FakeCollectionService(),
        document_profile_service=SimpleNamespace(),
        paper_fact_repository=MemoryPaperFactRepository(),
        core_fact_repository=repository,
    )

    with pytest.raises(ComparisonRowsNotReadyError):
        service.build_comparison_rows("col-1")
