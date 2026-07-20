from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from application.core.comparison_service import ComparisonService
from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
    ResearchViewNotReadyError,
)
from application.core.research_understanding_service import ResearchUnderstandingService
from controllers.schemas.core.research_view import MaterialProfileResponse
from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    ObjectiveEvidenceUnit,
    ObjectiveFactSet,
    ResearchObjective,
    SampleVariant,
    StructureFeature,
    TestCondition as CoreTestCondition,
    project_objective_comparison_rows,
)
from domain.core.paper_fact import PaperFactSet
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.comparison_repository import MemoryComparisonRepository


class FakeCollectionService:
    def __init__(self, *, has_files: bool = True) -> None:
        self.has_files = has_files

    def get_collection(self, collection_id: str) -> dict:
        return {
            "collection_id": collection_id,
            "name": "Research Collection",
            "paper_count": 1 if self.has_files else 0,
        }

    def list_files(self, collection_id: str) -> list[dict]:  # noqa: ARG002
        if not self.has_files:
            return []
        return [{"filename": "paper.pdf"}]


def _frames(collection_id: str = "col-1") -> tuple[list[dict], dict[str, list[dict]]]:
    profiles = [
        {
            "document_id": "paper-1",
            "collection_id": collection_id,
            "title": "PBF Sample Study",
        }
    ]
    frames = {
        "evidence_anchors": [
            {
                "anchor_id": "anc-density",
                "document_id": "paper-1",
                "source_type": "table",
                "locator_type": "table_row",
                "page": 4,
                "quote": "S1 density was 99%.",
            },
            {
                "anchor_id": "anc-yield-25",
                "document_id": "paper-1",
                "source_type": "table",
                "locator_type": "table_row",
                "page": 5,
                "quote": "S1 yield strength was 940 MPa at 25 C.",
            },
            {
                "anchor_id": "anc-yield-200",
                "document_id": "paper-1",
                "source_type": "table",
                "locator_type": "table_row",
                "page": 5,
                "quote": "S1 yield strength was 820 MPa at 200 C.",
            },
        ],
        "method_facts": [],
        "sample_variants": [
            {
                "variant_id": "var-s1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "variant_label": "S1 as built",
                "host_material_system": {
                    "family": "titanium alloy",
                    "composition": "Ti-6Al-4V",
                },
                "composition": "Ti-6Al-4V",
                "variable_axis_type": "post_treatment",
                "variable_value": "as built",
                "process_context": {
                    "laser_power_w": 280,
                    "scan_speed_mm_s": 1200,
                    "energy_density_j_mm3": 78,
                },
                "source_anchor_ids": ["anc-density"],
            },
            {
                "variant_id": "var-generic",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "variant_label": "titanium alloy",
                "host_material_system": {"family": "titanium alloy"},
                "composition": "titanium alloy",
                "variable_axis_type": None,
                "variable_value": None,
                "process_context": {},
                "source_anchor_ids": [],
            },
        ],
        "test_conditions": [
            {
                "test_condition_id": "tc-25",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "condition_payload": {
                    "test_method": "tensile",
                    "test_temperature_c": 25.0,
                },
                "evidence_anchor_ids": ["anc-yield-25"],
            },
            {
                "test_condition_id": "tc-200",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "condition_payload": {
                    "test_method": "tensile",
                    "test_temperature_c": 200.0,
                },
                "evidence_anchor_ids": ["anc-yield-200"],
            },
        ],
        "baseline_references": [],
        "measurement_results": [
            {
                "result_id": "res-density",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "variant_id": "var-s1",
                "property_normalized": "density",
                "value_payload": {"value": 99.0, "source_value_text": "99"},
                "unit": "%",
                "test_condition_id": "tc-25",
                "evidence_anchor_ids": ["anc-density"],
            },
            {
                "result_id": "res-density-duplicate",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "variant_id": "var-s1",
                "property_normalized": "density",
                "value_payload": {"value": 99.0, "source_value_text": "99"},
                "unit": "%",
                "test_condition_id": "tc-25",
                "evidence_anchor_ids": ["anc-density"],
            },
            {
                "result_id": "res-yield-25",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "variant_id": "var-s1",
                "property_normalized": "yield_strength",
                "value_payload": {"value": 940.0, "source_value_text": "940"},
                "unit": "MPa",
                "test_condition_id": "tc-25",
                "evidence_anchor_ids": ["anc-yield-25"],
            },
            {
                "result_id": "res-yield-200",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "variant_id": "var-s1",
                "property_normalized": "yield_strength",
                "value_payload": {"value": 820.0, "source_value_text": "820"},
                "unit": "MPa",
                "test_condition_id": "tc-200",
                "evidence_anchor_ids": ["anc-yield-200"],
            },
        ],
        "characterization_observations": [],
        "structure_features": [],
    }
    return profiles, frames


def _comparison_rows(collection_id: str = "col-1") -> list[dict]:
    return [
        {
            "row_id": "row-1",
            "collection_id": collection_id,
            "comparable_result_id": "cres-1",
            "source_document_id": "paper-1",
            "variant_id": "var-s1",
            "variant_label": "S1 as built",
            "variable_axis": "post_treatment",
            "variable_value": "as built",
            "result_summary": "940 MPa",
            "supporting_anchor_ids": ["anc-yield-25"],
            "material_system_normalized": "Ti-6Al-4V",
            "process_normalized": "LPBF",
            "property_normalized": "yield_strength",
            "baseline_normalized": "none",
            "test_condition_normalized": "25 C tensile",
            "comparability_status": "comparable",
            "comparability_warnings": [],
            "value": 940.0,
            "unit": "MPa",
        },
        {
            "row_id": "row-2",
            "collection_id": collection_id,
            "comparable_result_id": "cres-2",
            "source_document_id": "paper-1",
            "variant_id": "var-s2",
            "variant_label": "S2 HIP",
            "variable_axis": "post_treatment",
            "variable_value": "HIP",
            "result_summary": "960 MPa",
            "supporting_anchor_ids": ["anc-yield-25"],
            "material_system_normalized": "Ti-6Al-4V",
            "process_normalized": "LPBF",
            "property_normalized": "yield_strength",
            "baseline_normalized": "none",
            "test_condition_normalized": "25 C tensile",
            "comparability_status": "comparable",
            "comparability_warnings": [],
            "value": 960.0,
            "unit": "MPa",
        },
    ]


def _objective_units() -> list[dict]:
    return [
        {
            "evidence_unit_id": "oeu-as-built-icorr",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "as-built"},
            "process_context": {"process": "LPBF"},
            "resolved_condition": {"medium": "3.5 wt.% NaCl"},
            "test_condition": {"method": "potentiodynamic polarization"},
            "property_normalized": "corrosion current density",
            "value_payload": {"value": 1.2, "source_value_text": "1.2 uA/cm2"},
            "unit": "uA/cm2",
            "source_refs": [
                {
                    "route_id": "route-table-1",
                    "source_kind": "table",
                    "source_ref": "table-1",
                }
            ],
            "evidence_anchor_ids": ["anc-as-built"],
            "resolution_status": "resolved",
            "confidence": 0.88,
        },
        {
            "evidence_unit_id": "oeu-heat-treated-icorr",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "heat-treated"},
            "process_context": {
                "process": "LPBF",
                "post_treatment_summary": "solution annealed",
            },
            "resolved_condition": {"medium": "3.5 wt.% NaCl"},
            "test_condition": {"method": "potentiodynamic polarization"},
            "property_normalized": "corrosion current density",
            "value_payload": {"value": 0.4, "source_value_text": "0.4 uA/cm2"},
            "unit": "uA/cm2",
            "source_refs": [
                {
                    "route_id": "route-table-1",
                    "source_kind": "table",
                    "source_ref": "table-1",
                }
            ],
            "evidence_anchor_ids": ["anc-heat-treated"],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-heat-treatment",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "heat-treated"},
            "process_context": {"post_treatment_summary": "solution annealed"},
            "source_refs": [
                {
                    "route_id": "route-text-1",
                    "source_kind": "text_window",
                    "source_ref": "b2",
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.74,
        },
    ]


def _service(
    *,
    has_files: bool = True,
    comparison_rows: list[dict] | None = None,
) -> ResearchViewAggregationService:
    profiles, frames = _frames()
    paper_fact_repository = _paper_fact_repository(profiles, frames)
    objective_repository = MemoryObjectiveRepository()
    source_repository = SimpleNamespace()
    collection_service = FakeCollectionService(has_files=has_files)
    return ResearchViewAggregationService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        comparison_service=_comparison_service(
            collection_service,
            paper_fact_repository,
            objective_repository,
            comparison_rows,
        ),
        research_understanding_service=ResearchUnderstandingService(source_repository),
    )

def _service_from_frames(
    profiles: list[dict],
    frames: dict[str, list[dict]],
    *,
    comparison_rows: list[dict] | None = None,
    objective_units: list[dict] | None = None,
    research_objectives: list[dict] | None = None,
) -> ResearchViewAggregationService:
    paper_fact_repository = _paper_fact_repository(profiles, frames)
    objective_repository = MemoryObjectiveRepository()
    objective_repository.replace(
        "col-1",
        "build_test",
        ObjectiveFactSet(
            research_objectives_ready=True,
            research_objectives=tuple(
                ResearchObjective.from_mapping(record)
                for record in research_objectives or []
            ),
            objective_evidence_units=tuple(
                ObjectiveEvidenceUnit.from_mapping(record)
                for record in objective_units or []
            ),
        ),
    )
    source_repository = SimpleNamespace()
    collection_service = FakeCollectionService()
    return ResearchViewAggregationService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        comparison_service=_comparison_service(
            collection_service,
            paper_fact_repository,
            objective_repository,
            comparison_rows,
        ),
        research_understanding_service=ResearchUnderstandingService(source_repository),
    )


def _comparison_service(
    collection_service: FakeCollectionService,
    paper_fact_repository: MemoryPaperFactRepository,
    objective_repository: MemoryObjectiveRepository,
    comparison_rows: list[dict] | None,
) -> ComparisonService:
    comparison_repository = MemoryComparisonRepository()
    comparison_objective_repository = objective_repository
    if (
        comparison_rows
        and not objective_repository.read("col-1").objective_evidence_units
    ):
        comparison_objective_repository = MemoryObjectiveRepository.from_facts(
            "col-1",
            ObjectiveFactSet(
                objective_evidence_units=tuple(
                    ObjectiveEvidenceUnit.from_mapping(
                        {
                            "evidence_unit_id": row["comparable_result_id"],
                            "objective_id": "obj-test",
                            "document_id": row["source_document_id"],
                            "unit_kind": "measurement",
                            "material_system": {
                                "name": row.get("material_system_normalized")
                            },
                            "sample_context": {
                                "sample": row.get("variant_label"),
                                "variant_id": row.get("variant_id"),
                            },
                            "process_context": {
                                "process": row.get("process_normalized"),
                                row.get("variable_axis") or "variable": row.get(
                                    "variable_value"
                                ),
                            },
                            "test_condition": {
                                "condition": row.get("test_condition_normalized")
                            },
                            "property_normalized": row.get("property_normalized"),
                            "value_payload": {
                                "value": row.get("value"),
                                "source_value_text": row.get("result_summary"),
                                "comparison_axis": row.get("variable_axis"),
                                "comparison_axis_value": row.get("variable_value"),
                            },
                            "unit": row.get("unit"),
                            "evidence_anchor_ids": row.get("supporting_anchor_ids", []),
                            "resolution_status": "resolved",
                        }
                    )
                    for row in comparison_rows
                ),
            ),
        )
    service = ComparisonService(
        collection_service=collection_service,
        paper_fact_repository=paper_fact_repository,
        objective_repository=comparison_objective_repository,
        comparison_repository=comparison_repository,
        document_profile_service=SimpleNamespace(),
    )
    if comparison_rows:
        service.build_comparison_rows("col-1", "build_test")
    return service


def _paper_fact_repository(
    profiles: list[dict],
    frames: dict[str, list[dict]],
) -> MemoryPaperFactRepository:
    repository = MemoryPaperFactRepository()
    repository.replace_document_profiles(
        "col-1",
        "build_test",
        tuple(DocumentProfile.from_mapping(record) for record in profiles),
    )
    repository.replace_paper_facts(
        "col-1",
        "build_test",
        PaperFactSet(
            evidence_anchors=tuple(
                EvidenceAnchor.from_mapping(record)
                for record in frames.get("evidence_anchors", [])
            ),
            method_facts=tuple(
                MethodFact.from_mapping(record)
                for record in frames.get("method_facts", [])
            ),
            sample_variants=tuple(
                SampleVariant.from_mapping(record)
                for record in frames.get("sample_variants", [])
            ),
            test_conditions=tuple(
                CoreTestCondition.from_mapping(record)
                for record in frames.get("test_conditions", [])
            ),
            baseline_references=tuple(
                BaselineReference.from_mapping(record)
                for record in frames.get("baseline_references", [])
            ),
            measurement_results=tuple(
                MeasurementResult.from_mapping(record)
                for record in frames.get("measurement_results", [])
            ),
            characterization_observations=tuple(
                CharacterizationObservation.from_mapping(record)
                for record in frames.get("characterization_observations", [])
            ),
            structure_features=tuple(
                StructureFeature.from_mapping(record)
                for record in frames.get("structure_features", [])
            ),
        ),
    )
    return repository


def test_document_research_view_builds_sample_matrix_and_condition_series():
    service = _service(comparison_rows=_comparison_rows())

    payload = service.get_document_research_view("col-1", "paper-1")

    assert payload["state"] == "partial"
    assert payload["paper_title"] == "PBF Sample Study"
    rows = payload["sample_matrix"]["rows"]
    assert [row["sample_id"] for row in rows] == ["var-s1"]

    density_key = next(key for key in rows[0]["values"] if key.startswith("density@"))
    density_cell = rows[0]["values"][density_key]
    assert density_cell["display_value"] == "99 %"
    assert density_cell["duplicate_count"] == 1
    assert density_cell["evidence_refs"][0]["anchor_ids"] == ["anc-density"]

    series = payload["condition_series"]
    assert len(series) == 1
    assert series[0]["property"] == "yield_strength"
    assert series[0]["condition_axis"]["axis_name"] == "test_temperature_c"
    assert [point["condition_value"] for point in series[0]["points"]] == [25.0, 200.0]
    assert payload["materials"][0]["material_id"] == "mat-ti-6al-4v"
    assert payload["materials"][0]["canonical_name"] == "Ti-6Al-4V"


def test_research_view_collapses_equivalent_numeric_values_with_missing_units():
    service = _service()

    value = service._build_evidence_backed_value(
        [
            {
                "result_id": "res-density-unitless",
                "property_normalized": "density",
                "value_payload": {"value": 97.7, "source_value_text": "97.7"},
                "unit": "",
                "result_type": "scalar",
                "evidence_anchor_ids": [],
            },
            {
                "result_id": "res-density-percent",
                "property_normalized": "density",
                "value_payload": {"value": 97.7, "source_value_text": "97.7"},
                "unit": "%",
                "result_type": "scalar",
                "evidence_anchor_ids": [],
            },
        ],
        {"evidence_anchors": []},
    )

    assert value["status"] == "observed"
    assert value["display_value"] == "97.7 %"
    assert value["value"] == 97.7
    assert value["unit"] == "%"
    assert value["duplicate_count"] == 1
    assert value["conflict_status"] == "duplicate_only"


def test_collection_research_view_builds_coverage_and_comparable_groups():
    service = _service(comparison_rows=_comparison_rows())

    payload = service.get_collection_research_view("col-1")

    assert payload["state"] == "ready"
    assert payload["overview"]["sample_variant_count"] == 1
    assert payload["paper_coverage"][0]["state"] == "ready"
    assert payload["paper_coverage"][0]["sample_count"] == 1
    assert payload["paper_coverage"][0]["measurement_count"] == 4

    group = payload["comparable_groups"][0]
    assert group["comparability_status"] == "comparable"
    assert group["variable_axis"] == "post_treatment"
    assert group["properties"] == ["yield_strength"]
    assert len(group["matrix"]["rows"]) == 2

    assert payload["materials"] == []


def test_collection_research_view_reads_each_semantic_family_once():
    service = _service(comparison_rows=_comparison_rows())
    service.paper_fact_repository.read = Mock(wraps=service.paper_fact_repository.read)
    service.objective_repository.read = Mock(wraps=service.objective_repository.read)
    service.comparison_service.read_comparison_projection = Mock(
        wraps=service.comparison_service.read_comparison_projection
    )

    payload = service.get_collection_research_view("col-1")

    assert payload["overview"]["measurement_count"] == 4
    assert payload["overview"]["comparable_group_count"] == 1
    service.paper_fact_repository.read.assert_called_once_with("col-1")
    service.objective_repository.read.assert_called_once_with("col-1")
    service.comparison_service.read_comparison_projection.assert_called_once_with(
        "col-1"
    )


def test_collection_research_view_returns_empty_state_for_empty_collection():
    service = _service(has_files=False)

    payload = service.get_collection_research_view("col-1")

    assert payload["state"] == "empty"
    assert payload["materials"] == []
    assert payload["paper_coverage"] == []
    assert payload["comparable_groups"] == []


def test_collection_material_endpoints_require_objective_evidence_units():
    service = _service(comparison_rows=_comparison_rows())

    try:
        service.list_collection_materials("col-1")
    except ResearchViewNotReadyError as exc:
        assert exc.collection_id == "col-1"
    else:  # pragma: no cover
        raise AssertionError("old facts must not drive collection material list")

    try:
        service.get_collection_material_research_view("col-1", "mat-ti-6al-4v")
    except ResearchViewNotReadyError as exc:
        assert exc.collection_id == "col-1"
    else:  # pragma: no cover
        raise AssertionError("old facts must not drive collection material profile")


def test_collection_materials_can_use_objective_evidence_units_without_old_facts():
    profiles, _ = _frames()
    service = _service_from_frames(
        profiles,
        {
            "evidence_anchors": [],
            "method_facts": [],
            "sample_variants": [],
            "test_conditions": [],
            "baseline_references": [],
            "measurement_results": [],
            "characterization_observations": [],
            "structure_features": [],
        },
        objective_units=_objective_units(),
    )

    materials = service.list_collection_materials("col-1")

    assert materials["state"] == "ready"
    assert [item["material_id"] for item in materials["materials"]] == [
        "mat-316l-stainless-steel"
    ]
    summary = materials["materials"][0]
    assert summary["canonical_name"] == "316L stainless steel"
    assert summary["sample_count"] == 2
    assert summary["measured_properties"] == ["corrosion current density"]
    assert summary["evidence_coverage"] == {
        "observed_count": 3,
        "with_evidence_count": 3,
        "coverage": 1.0,
    }

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    MaterialProfileResponse.model_validate(profile)
    assert profile["state"] == "ready"
    assert profile["overview"]["sample_count"] == 2
    assert profile["overview"]["measured_properties"] == ["corrosion current density"]
    assert [row["sample_label"] for row in profile["sample_matrix"]["rows"]] == [
        "as-built",
        "heat-treated",
    ]
    assert (
        profile["sample_matrix"]["rows"][0]["values"]["corrosion current density"][
            "condition"
        ]
        == "method: potentiodynamic polarization"
    )
    assert profile["measured_properties"][0]["display_range"] == "0.4-1.2 uA/cm2"
    assert profile["evidence_refs"][0]["fact_ids"] == ["oeu-as-built-icorr"]
    understanding = profile["understanding"]
    assert understanding["state"] == "ready"
    assert understanding["scope"]["scope_type"] == "material"
    assert understanding["scope"]["material_id"] == "mat-316l-stainless-steel"
    assert understanding["claims"]
    assert understanding["claims"][0]["evidence_ref_ids"]
    assert understanding["evidence_refs"]


def test_collection_material_profile_uses_objective_profile_when_available():
    profiles, frames = _frames()
    service = _service_from_frames(
        profiles,
        frames,
        comparison_rows=_comparison_rows(),
        objective_units=[
            {
                "evidence_unit_id": "oeu-objective-only-note",
                "objective_id": "obj-mechanical",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {"name": "Ti-6Al-4V"},
                "sample_context": {"sample": "summary"},
                "property_normalized": "elongation",
                "value_payload": {"value": 33, "source_value_text": "33"},
                "unit": "%",
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        ],
    )

    profile = service.get_collection_material_research_view("col-1", "mat-ti-6al-4v")

    rows = profile["sample_matrix"]["rows"]
    assert [row["sample_label"] for row in rows] == ["summary"]
    assert rows[0]["values"]["elongation"]["value"] == 33
    assert {item["property"] for item in profile["measured_properties"]} == {
        "elongation"
    }
    assert profile["overview"]["measured_properties"] == ["elongation"]
    assert profile["evidence_refs"][0]["fact_ids"] == ["oeu-objective-only-note"]
    assert profile["understanding"]["scope"]["scope_type"] == "material"
    assert profile["understanding"]["state"] == "ready"


def test_collection_research_view_uses_objective_units_without_old_facts():
    profiles, _ = _frames()
    objective_units = _objective_units()
    comparison_rows = [
        row.to_record()
        for row in project_objective_comparison_rows(
            collection_id="col-1",
            evidence_units=(
                ObjectiveEvidenceUnit.from_mapping(objective_units[0]),
                ObjectiveEvidenceUnit.from_mapping(objective_units[1]),
            ),
        )
    ]
    service = _service_from_frames(
        profiles,
        {
            "evidence_anchors": [],
            "method_facts": [],
            "sample_variants": [],
            "test_conditions": [],
            "baseline_references": [],
            "measurement_results": [],
            "characterization_observations": [],
            "structure_features": [],
        },
        comparison_rows=comparison_rows,
        objective_units=objective_units,
    )

    payload = service.get_collection_research_view("col-1")

    assert payload["state"] == "ready"
    assert payload["overview"]["sample_variant_count"] == 2
    assert payload["overview"]["measurement_count"] == 2
    assert payload["overview"]["material_systems"] == ["316L stainless steel"]
    assert payload["overview"]["measured_properties"] == ["corrosion current density"]
    assert payload["paper_coverage"][0]["state"] == "ready"
    assert payload["paper_coverage"][0]["measurement_count"] == 2
    assert payload["materials"][0]["material_id"] == "mat-316l-stainless-steel"
    assert payload["comparable_groups"][0]["material_system"] == (
        "316L stainless steel"
    )


def test_collection_materials_does_not_build_comparison_matrices(monkeypatch):
    profiles, _ = _frames()
    service = _service_from_frames(
        profiles,
        {
            "evidence_anchors": [],
            "method_facts": [],
            "sample_variants": [],
            "test_conditions": [],
            "baseline_references": [],
            "measurement_results": [],
            "characterization_observations": [],
            "structure_features": [],
        },
        objective_units=_objective_units(),
    )
    service.paper_fact_repository.read = Mock(wraps=service.paper_fact_repository.read)
    service.objective_repository.read = Mock(wraps=service.objective_repository.read)
    service.comparison_service.read_comparison_projection = Mock(
        wraps=service.comparison_service.read_comparison_projection
    )

    def fail_matrix_build(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("material list should not build cross-paper matrices")

    monkeypatch.setattr(service, "_build_cross_paper_matrix", fail_matrix_build)

    materials = service.list_collection_materials("col-1")

    assert materials["state"] == "ready"
    assert materials["materials"][0]["material_id"] == "mat-316l-stainless-steel"
    assert materials["materials"][0]["comparison_count"] == 0
    service.paper_fact_repository.read.assert_called_once_with("col-1")
    service.objective_repository.read.assert_called_once_with("col-1")
    service.comparison_service.read_comparison_projection.assert_not_called()


def test_document_material_profile_stays_inside_one_paper():
    service = _service(comparison_rows=_comparison_rows())

    materials = service.list_document_materials("col-1", "paper-1")
    profile = service.get_document_material_research_view(
        "col-1",
        "paper-1",
        materials["materials"][0]["material_id"],
    )

    assert materials["document_id"] == "paper-1"
    assert materials["materials"][0]["sample_count"] == 1
    assert profile["document_id"] == "paper-1"
    assert profile["sample_matrix"]["document_id"] == "paper-1"
    assert [row["document_id"] for row in profile["sample_matrix"]["rows"]] == [
        "paper-1"
    ]
    assert len(profile["process_conditions"]) == 1
    assert {row["test_condition_id"] for row in profile["test_conditions"]} == {
        "tc-25",
        "tc-200",
    }


def test_objective_material_profile_inherits_material_scope_for_sample_measurements():
    profiles, frames = _frames()
    frames["sample_variants"] = []
    frames["measurement_results"] = []
    service = _service_from_frames(
        profiles,
        frames,
        objective_units=[
            {
                "evidence_unit_id": "oeu-preheated-yield",
                "objective_id": "obj-preheat",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {},
                "sample_context": {
                    "Build platform conditions": "Preheated",
                    "sample_number": "2",
                },
                "process_context": {"process": "LPBF"},
                "property_normalized": "yield_strength",
                "value_payload": {
                    "source_value_numeric": 508,
                    "source_value_text": "508",
                },
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.85,
            },
            {
                "evidence_unit_id": "oeu-preheated-elongation",
                "objective_id": "obj-preheat",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {},
                "sample_context": {
                    "Build platform conditions": "Preheated",
                    "sample_number": "2",
                },
                "property_normalized": "elongation",
                "value_payload": {
                    "source_value_numeric": 82,
                    "source_value_text": "82",
                    "unit": "%",
                },
                "resolution_status": "resolved",
                "confidence": 0.85,
            },
        ],
        research_objectives=[
            {
                "objective_id": "obj-preheat",
                "question": "How does build-platform preheating affect LPBF 316L?",
                "material_scope": ["316L stainless steel"],
                "process_axes": ["preheating"],
                "property_axes": ["yield strength", "elongation"],
                "confidence": 0.9,
            }
        ],
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    row = profile["sample_matrix"]["rows"][0]
    assert row["sample_label"] == "Preheated"
    assert row["material"] == "316L stainless steel"
    assert row["values"]["yield_strength"]["value"] == 508
    assert row["values"]["yield_strength"]["display_value"] == "508 MPa"
    assert row["values"]["elongation"]["value"] == 82
    assert row["values"]["elongation"]["unit"] == "%"


def test_objective_material_profile_projects_sample_context_and_test_conditions():
    profiles, frames = _frames()
    frames["sample_variants"] = []
    frames["measurement_results"] = []
    service = _service_from_frames(
        profiles,
        frames,
        objective_units=[
            {
                "evidence_unit_id": "oeu-preheated-yield",
                "objective_id": "obj-preheat",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {},
                "sample_context": {
                    "Build platform conditions": "Preheated",
                    "sample_number": "2",
                },
                "test_condition": {
                    "Build platform conditions": "Preheated",
                    "standard": "ASTM E8",
                },
                "property_normalized": "yield_strength",
                "value_payload": {
                    "source_value_numeric": 465,
                    "source_value_text": "465",
                },
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.85,
            },
            {
                "evidence_unit_id": "oeu-preheated-process",
                "objective_id": "obj-preheat",
                "document_id": "paper-1",
                "unit_kind": "process_context",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {
                    "Build platform conditions": "Preheated",
                    "sample_number": "2",
                },
                "process_context": {"platform_temperature": "150 C"},
                "resolution_status": "resolved",
                "confidence": 0.8,
            },
            {
                "evidence_unit_id": "oeu-other-process",
                "objective_id": "obj-preheat",
                "document_id": "paper-1",
                "unit_kind": "process_context",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {"Build platform conditions": "Non-preheated"},
                "process_context": {"platform_temperature": "room temperature"},
                "resolution_status": "resolved",
                "confidence": 0.8,
            },
        ],
        research_objectives=[
            {
                "objective_id": "obj-preheat",
                "question": "How does build-platform preheating affect LPBF 316L?",
                "material_scope": ["316L stainless steel"],
                "process_axes": ["preheating"],
                "property_axes": ["yield strength"],
                "confidence": 0.9,
            }
        ],
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    rows = profile["sample_matrix"]["rows"]
    assert [row["sample_label"] for row in rows] == ["Preheated"]
    row = rows[0]
    assert row["process_context"] == {
        "Build platform conditions": "Preheated",
        "platform_temperature": "150 C",
    }
    assert row["test_condition"] == {
        "Build platform conditions": "Preheated",
        "standard": "ASTM E8",
    }
    assert row["values"]["yield_strength"]["value"] == 465


def test_objective_material_profile_uses_informative_sample_context_keys():
    profiles, frames = _frames()
    frames["sample_variants"] = []
    frames["measurement_results"] = []
    service = _service_from_frames(
        profiles,
        frames,
        objective_units=[
            {
                "evidence_unit_id": "oeu-lved-uts",
                "objective_id": "obj-ved",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {
                    "Printed > 316L": "L-VED",
                    "material": "316L stainless steel",
                },
                "property_normalized": "ultimate_tensile_strength",
                "value_payload": {
                    "source_value_numeric": 610,
                    "source_value_text": "610 ± 6",
                    "source_unit_text": "MPa",
                },
                "resolution_status": "resolved",
                "confidence": 0.88,
            }
        ],
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    row = profile["sample_matrix"]["rows"][0]
    assert row["sample_label"] == "L-VED"
    assert row["values"]["ultimate_tensile_strength"]["value"] == 610
    assert row["values"]["ultimate_tensile_strength"]["display_value"] == (
        "610 ± 6 MPa"
    )


def test_objective_material_profile_collapses_duplicate_property_columns():
    profiles, frames = _frames()
    frames["sample_variants"] = []
    frames["measurement_results"] = []
    service = _service_from_frames(
        profiles,
        frames,
        objective_units=[
            {
                "evidence_unit_id": "oeu-lved-yield-1",
                "objective_id": "obj-ved",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {"Printed": "L-VED"},
                "property_normalized": "yield strength",
                "value_payload": {
                    "source_value_numeric": 560,
                    "source_value_text": "560",
                },
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.88,
            },
            {
                "evidence_unit_id": "oeu-lved-yield-2",
                "objective_id": "obj-ved",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {"Printed": "L-VED"},
                "property_normalized": "yield strength",
                "value_payload": {
                    "source_value_numeric": 560,
                    "source_value_text": "560",
                },
                "unit": "MPa",
                "resolution_status": "resolved",
                "confidence": 0.88,
            },
            {
                "evidence_unit_id": "oeu-lved-process",
                "objective_id": "obj-ved",
                "document_id": "paper-1",
                "unit_kind": "process_context",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {"Printed": "heat input"},
                "process_context": {"process": "LPBF"},
                "resolution_status": "resolved",
                "confidence": 0.7,
            },
        ],
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    rows = profile["sample_matrix"]["rows"]
    property_columns = [
        column
        for column in profile["sample_matrix"]["columns"]
        if column["role"] == "property"
    ]
    assert [row["sample_label"] for row in rows] == ["L-VED"]
    assert [column["column_id"] for column in property_columns] == ["yield strength"]
    assert rows[0]["values"]["yield strength"]["value"] == 560
    assert rows[0]["values"]["yield strength"]["duplicate_count"] == 1
