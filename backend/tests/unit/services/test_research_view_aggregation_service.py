from __future__ import annotations

from types import SimpleNamespace

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
    ResearchViewNotReadyError,
)
from controllers.schemas.core.research_view import MaterialProfileResponse
from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    ComparisonRowRecord,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    ObjectiveEvidenceUnit,
    ResearchObjective,
    SampleVariant,
    StructureFeature,
    TestCondition as CoreTestCondition,
    project_objective_comparison_rows,
)


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


class FakeDocumentProfileService:
    def __init__(self, profiles: list[dict]) -> None:
        self.profiles = profiles

    def read_document_profiles(self, collection_id: str) -> list[dict]:  # noqa: ARG002
        return self.profiles


class FakePaperFactsService:
    def __init__(self, core_fact_repository: "FakeCoreFactRepository") -> None:
        self.core_fact_repository = core_fact_repository


class FakeCoreFactRepository:
    backend_name = "fake"

    def __init__(
        self,
        profiles: list[dict],
        frames: dict[str, list[dict]],
        comparison_rows: list[dict] | None,
        objective_units: list[dict] | None = None,
        research_objectives: list[dict] | None = None,
    ) -> None:
        self.facts = CoreFactSet(
            research_objectives=self._records(
                research_objectives if research_objectives is not None else [],
                ResearchObjective,
            ),
            document_profiles=self._records(profiles, DocumentProfile),
            evidence_anchors=self._records(
                frames.get("evidence_anchors", []),
                EvidenceAnchor,
            ),
            method_facts=self._records(
                frames.get("method_facts", []),
                MethodFact,
            ),
            sample_variants=self._records(
                frames.get("sample_variants", []),
                SampleVariant,
            ),
            test_conditions=self._records(
                frames.get("test_conditions", []),
                CoreTestCondition,
            ),
            baseline_references=self._records(
                frames.get("baseline_references", []),
                BaselineReference,
            ),
            measurement_results=self._records(
                frames.get("measurement_results", []),
                MeasurementResult,
            ),
            characterization_observations=self._records(
                frames.get("characterization_observations", []),
                CharacterizationObservation,
            ),
            structure_features=self._records(
                frames.get("structure_features", []),
                StructureFeature,
            ),
            comparison_rows=self._records(
                comparison_rows if comparison_rows is not None else [],
                ComparisonRowRecord,
            ),
            objective_evidence_units=self._records(
                objective_units if objective_units is not None else [],
                ObjectiveEvidenceUnit,
            ),
        )

    def read_collection_facts(self, collection_id: str) -> CoreFactSet:  # noqa: ARG002
        return self.facts

    def _records(
        self,
        records: list[dict],
        record_cls: type,
    ) -> tuple:
        if not records:
            return ()
        return tuple(record_cls.from_mapping(record) for record in records)


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
    core_fact_repository = FakeCoreFactRepository(profiles, frames, comparison_rows)
    return ResearchViewAggregationService(
        collection_service=FakeCollectionService(has_files=has_files),
        document_profile_service=FakeDocumentProfileService(profiles),
        paper_facts_service=FakePaperFactsService(core_fact_repository),
        workspace_service=SimpleNamespace(),
        core_fact_repository=core_fact_repository,
    )


def _service_from_frames(
    profiles: list[dict],
    frames: dict[str, list[dict]],
    *,
    comparison_rows: list[dict] | None = None,
    objective_units: list[dict] | None = None,
    research_objectives: list[dict] | None = None,
) -> ResearchViewAggregationService:
    core_fact_repository = FakeCoreFactRepository(
        profiles,
        frames,
        comparison_rows,
        objective_units,
        research_objectives,
    )
    return ResearchViewAggregationService(
        collection_service=FakeCollectionService(),
        document_profile_service=FakeDocumentProfileService(profiles),
        paper_facts_service=FakePaperFactsService(core_fact_repository),
        workspace_service=SimpleNamespace(),
        core_fact_repository=core_fact_repository,
    )


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
    assert profile["overview"]["measured_properties"] == [
        "corrosion current density"
    ]
    assert [row["sample_label"] for row in profile["sample_matrix"]["rows"]] == [
        "as-built",
        "heat-treated",
    ]
    assert profile["sample_matrix"]["rows"][0]["values"][
        "corrosion current density"
    ]["condition"] == "method: potentiodynamic polarization"
    assert profile["measured_properties"][0]["display_range"] == "0.4-1.2 uA/cm2"
    assert profile["evidence_refs"][0]["fact_ids"] == ["oeu-as-built-icorr"]
    report_package = profile["report_package"]
    assert report_package["schema_version"] == "material_report_package.v1"
    assert report_package["canonical_name"] == "316L stainless steel"
    assert report_package["material_scope"]["sample_row_count"] == 2
    assert report_package["evidence_appendix"]["sample_matrix_row_count"] == 2
    assert report_package["paper_contributions"][0]["document_id"] == "paper-1"
    chains = report_package["material_state_chains"]
    assert [chain["sample_label"] for chain in chains] == ["as-built", "heat-treated"]
    assert report_package["representative_states"] == chains
    assert report_package["key_findings"]
    assert report_package["thematic_sections"]
    document = report_package["document"]
    assert document["schema_version"] == "material_report_document.v1"
    assert document["title"] == "316L stainless steel Material Report"
    assert "# 316L stainless steel Material Report" in document["markdown"]
    assert "## Representative Material States" in document["markdown"]
    assert "as-built" in document["markdown"]
    assert "heat-treated" in document["markdown"]
    assert "[E001]" in document["markdown"]
    assert document["citations"]["E001"]["fact_ids"] == ["oeu-as-built-icorr"]
    assert document["outline"][0] == {
        "level": 1,
        "title": "316L stainless steel Material Report",
        "anchor": "316l-stainless-steel-material-report",
    }
    assert document["evidence_appendix"] == report_package["evidence_appendix"]
    assert chains[0]["preparation_context"] == {"process": "LPBF"}
    assert chains[0]["test_conditions"] == {
        "method": "potentiodynamic polarization",
        "medium": "3.5 wt.% NaCl",
    }
    assert chains[0]["performance_results"][0]["property"] == (
        "corrosion current density"
    )
    assert chains[0]["performance_results"][0]["display_value"] == "1.2 uA/cm2"
    assert chains[0]["source_evidence"][0]["fact_ids"] == ["oeu-as-built-icorr"]


def test_material_report_package_selects_representative_states_from_full_matrix():
    profiles, _ = _frames()
    objective_units = [
        {
            "evidence_unit_id": f"oeu-sample-{index}",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": f"sample-{index}"},
            "process_context": {"process": "LPBF", "laser_power_w": 200 + index},
            "test_condition": {"method": "tensile"},
            "property_normalized": "yield strength",
            "value_payload": {
                "value": 400 + index,
                "source_value_text": str(400 + index),
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "route_id": f"route-table-{index}",
                    "source_kind": "table",
                    "source_ref": f"table-{index}",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
        for index in range(12)
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
        objective_units=objective_units,
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    assert len(profile["sample_matrix"]["rows"]) == 12
    report_package = profile["report_package"]
    assert report_package["evidence_appendix"]["sample_matrix_row_count"] == 12
    assert len(report_package["material_state_chains"]) == 8
    assert len(report_package["representative_states"]) == 8
    assert len(report_package["key_findings"]) == 6
    assert {chain["sample_label"] for chain in report_package["material_state_chains"]} < {
        f"sample-{index}" for index in range(12)
    }


def test_material_report_package_selects_scientific_representative_states():
    profiles, _ = _frames()
    objective_units = [
        {
            "evidence_unit_id": "oeu-filler-density",
            "objective_id": "obj-mechanical",
            "document_id": "paper-filler",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "Filler high density"},
            "process_context": {"energy_density": "150 J/mm3"},
            "test_condition": {"method": "density"},
            "property_normalized": "relative density",
            "value_payload": {"value": 99.9, "source_value_text": "99.9"},
            "unit": "%",
            "source_refs": [{"route_id": "route-filler", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.8,
        },
        {
            "evidence_unit_id": "oeu-s014-density",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p001",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "14"},
            "process_context": {"energy_density": "150 J/mm3"},
            "test_condition": {"method": "SEM / ImageJ"},
            "property_normalized": "relative density",
            "value_payload": {"value": 99.45, "source_value_text": "99.45"},
            "unit": "%",
            "source_refs": [{"route_id": "route-s014-density", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-s014-yield",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p001",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "14"},
            "process_context": {"scan_strategy": "A"},
            "test_condition": {"method": "tensile testing"},
            "property_normalized": "yield strength",
            "value_payload": {"value": 462.02, "source_value_text": "462.02"},
            "unit": "MPa",
            "source_refs": [{"route_id": "route-s014-yield", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-s014-uts",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p001",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "14"},
            "process_context": {"scan_strategy": "A"},
            "test_condition": {"method": "tensile testing"},
            "property_normalized": "ultimate tensile strength",
            "value_payload": {"value": 584.44, "source_value_text": "584.44"},
            "unit": "MPa",
            "source_refs": [{"route_id": "route-s014-uts", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-s014-elongation",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p001",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "14"},
            "process_context": {"scan_strategy": "A"},
            "test_condition": {"method": "tensile testing"},
            "property_normalized": "elongation",
            "value_payload": {"value": 41.9, "source_value_text": "41.9"},
            "unit": "%",
            "source_refs": [
                {"route_id": "route-s014-elongation", "source_kind": "table"}
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-heat-hardness",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p004",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "as-SLM(140/ 100)"},
            "process_context": {"laser_power": "140 W", "scan_speed": "100 mm/s"},
            "test_condition": {"method": "Vickers hardness"},
            "property_normalized": "hardness",
            "value_payload": {"value": 198.4, "source_value_text": "198.4"},
            "unit": "HV",
            "source_refs": [{"route_id": "route-heat-hardness", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-p005-density",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p005",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "255 W-1400 mm/s"},
            "process_context": {"laser_power": "255 W", "scanning_speed": "1400 mm/s"},
            "test_condition": {"method": "density"},
            "property_normalized": "relative density",
            "value_payload": {"value": 99.5, "source_value_text": "99.5"},
            "unit": "%",
            "source_refs": [{"route_id": "route-p005-density", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-case7-odf",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p006",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "7"},
            "process_context": {
                "scan strategy rotation angle": "45",
                "build orientation alpha": "45",
            },
            "test_condition": {"Case": "7"},
            "property_normalized": "odf correlation coefficient",
            "value_payload": {"value": 0.6584, "source_value_text": "0.6584"},
            "unit": "Experiment vs. Prediction",
            "source_refs": [{"route_id": "route-case7-odf", "source_kind": "table"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
        {
            "evidence_unit_id": "oeu-case7-predicted",
            "objective_id": "obj-mechanical",
            "document_id": "paper-p006",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "7"},
            "process_context": {
                "scan strategy rotation angle": "45",
                "build orientation alpha": "45",
            },
            "test_condition": {"Case": "7"},
            "property_normalized": "predicted yield strength",
            "value_payload": {"value": 347.14, "source_value_text": "347.14"},
            "unit": "MPa",
            "source_refs": [
                {"route_id": "route-case7-predicted", "source_kind": "table"}
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    ]
    for index in range(8):
        objective_units.append(
            {
                "evidence_unit_id": f"oeu-filler-density-{index}",
                "objective_id": "obj-mechanical",
                "document_id": f"paper-filler-{index}",
                "unit_kind": "measurement",
                "material_system": {"name": "316L stainless steel"},
                "sample_context": {"sample": f"Filler density {index}"},
                "process_context": {"energy_density": f"{100 + index} J/mm3"},
                "test_condition": {"method": "density"},
                "property_normalized": "relative density",
                "value_payload": {"value": 95 + index, "source_value_text": str(95 + index)},
                "unit": "%",
                "source_refs": [
                    {"route_id": f"route-filler-{index}", "source_kind": "table"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        )
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
        objective_units=objective_units,
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    report_package = profile["report_package"]
    labels = [chain["sample_label"] for chain in report_package["representative_states"]]
    assert labels[:4] == [
        "14",
        "as-SLM(140/ 100)",
        "255 W-1400 mm/s",
        "7",
    ]
    markdown = report_package["document"]["markdown"]
    assert "Sample 14" in markdown
    assert "99.45 %" in markdown
    assert "462.02 MPa" in markdown
    assert "584.44 MPa" in markdown
    assert "41.9 %" in markdown
    assert "as-SLM(140/ 100)" in markdown
    assert "255 W-1400 mm/s" in markdown
    assert "Case 7" in markdown
    assert "0.6584" in markdown
    assert "347.14 MPa" in markdown


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
    assert {item["property"] for item in profile["measured_properties"]} == {"elongation"}
    chain = profile["report_package"]["material_state_chains"][0]
    assert profile["report_package"]["status"] == "partial"
    assert chain["unresolved_fields"] == [
        "preparation_context",
        "test_conditions",
    ]
    assert "summary is missing preparation_context." in profile["report_package"][
        "limitations"
    ]
    assert "summary is missing test_conditions." in profile["report_package"][
        "limitations"
    ]


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
    assert payload["overview"]["measured_properties"] == [
        "corrosion current density"
    ]
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

    def fail_matrix_build(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("material list should not build cross-paper matrices")

    monkeypatch.setattr(service, "_build_cross_paper_matrix", fail_matrix_build)

    materials = service.list_collection_materials("col-1")

    assert materials["state"] == "ready"
    assert materials["materials"][0]["material_id"] == "mat-316l-stainless-steel"
    assert materials["materials"][0]["comparison_count"] == 0


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
    assert [row["document_id"] for row in profile["sample_matrix"]["rows"]] == ["paper-1"]
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
