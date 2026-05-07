from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
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
    def __init__(self, profiles: pd.DataFrame) -> None:
        self.profiles = profiles

    def read_document_profiles(self, collection_id: str) -> pd.DataFrame:  # noqa: ARG002
        return self.profiles


class FakePaperFactsService:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def read_paper_fact_frames(self, collection_id: str) -> dict[str, pd.DataFrame]:  # noqa: ARG002
        return self.frames


class FakeComparisonService:
    def __init__(self, rows: pd.DataFrame | None) -> None:
        self.rows = rows

    def read_comparison_projection(self, collection_id: str):  # noqa: ANN001, ARG002
        if self.rows is None:
            return None
        return SimpleNamespace(comparison_rows=self.rows)


def _frames(collection_id: str = "col-1") -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    profiles = pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "PBF Sample Study",
            }
        ]
    )
    frames = {
        "evidence_anchors": pd.DataFrame(
            [
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
            ]
        ),
        "method_facts": pd.DataFrame(),
        "sample_variants": pd.DataFrame(
            [
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
            ]
        ),
        "test_conditions": pd.DataFrame(
            [
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
            ]
        ),
        "baseline_references": pd.DataFrame(),
        "measurement_results": pd.DataFrame(
            [
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
            ]
        ),
        "characterization_observations": pd.DataFrame(),
        "structure_features": pd.DataFrame(),
    }
    return profiles, frames


def _comparison_rows(collection_id: str = "col-1") -> pd.DataFrame:
    return pd.DataFrame(
        [
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
    )


def _service(
    *,
    has_files: bool = True,
    comparison_rows: pd.DataFrame | None = None,
) -> ResearchViewAggregationService:
    profiles, frames = _frames()
    return ResearchViewAggregationService(
        collection_service=FakeCollectionService(has_files=has_files),
        document_profile_service=FakeDocumentProfileService(profiles),
        paper_facts_service=FakePaperFactsService(frames),
        comparison_service=FakeComparisonService(comparison_rows),
        workspace_service=SimpleNamespace(),
    )


def _service_from_frames(
    profiles: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    *,
    comparison_rows: pd.DataFrame | None = None,
) -> ResearchViewAggregationService:
    return ResearchViewAggregationService(
        collection_service=FakeCollectionService(),
        document_profile_service=FakeDocumentProfileService(profiles),
        paper_facts_service=FakePaperFactsService(frames),
        comparison_service=FakeComparisonService(comparison_rows),
        workspace_service=SimpleNamespace(),
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
        {"evidence_anchors": pd.DataFrame()},
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

    assert payload["materials"][0]["material_id"] == "mat-ti-6al-4v"
    assert payload["materials"][0]["paper_count"] == 1
    assert payload["materials"][0]["sample_count"] == 2
    assert payload["materials"][0]["comparison_count"] == 1


def test_collection_research_view_returns_empty_state_for_empty_collection():
    service = _service(has_files=False)

    payload = service.get_collection_research_view("col-1")

    assert payload["state"] == "empty"
    assert payload["materials"] == []
    assert payload["paper_coverage"] == []
    assert payload["comparable_groups"] == []


def test_collection_materials_and_profile_are_material_scoped():
    service = _service(comparison_rows=_comparison_rows())

    materials = service.list_collection_materials("col-1")

    assert materials["state"] == "ready"
    assert [item["material_id"] for item in materials["materials"]] == [
        "mat-ti-6al-4v"
    ]
    summary = materials["materials"][0]
    assert summary["canonical_name"] == "Ti-6Al-4V"
    assert summary["measured_properties"] == ["density", "yield_strength"]
    assert summary["links"]["research_view"].endswith(
        "/materials/mat-ti-6al-4v/research-view"
    )

    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-ti-6al-4v",
    )

    assert profile["canonical_name"] == "Ti-6Al-4V"
    assert profile["overview"]["sample_count"] == 1
    assert [row["sample_id"] for row in profile["sample_matrix"]["rows"]] == ["var-s1"]
    assert [paper["document_id"] for paper in profile["papers"]] == ["paper-1"]
    assert {item["parameter"] for item in profile["process_parameter_ranges"]} >= {
        "laser_power_w",
        "scan_speed_mm_s",
    }
    assert {item["property"] for item in profile["measured_properties"]} == {
        "density",
        "yield_strength",
    }
    assert profile["comparison_groups"][0]["material_system"] == "Ti-6Al-4V"


def test_collection_materials_does_not_build_comparison_matrices(monkeypatch):
    service = _service(comparison_rows=_comparison_rows())

    def fail_matrix_build(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("material list should not build cross-paper matrices")

    monkeypatch.setattr(service, "_build_cross_paper_matrix", fail_matrix_build)

    materials = service.list_collection_materials("col-1")

    assert materials["state"] == "ready"
    assert materials["materials"][0]["material_id"] == "mat-ti-6al-4v"
    assert materials["materials"][0]["comparison_count"] == 1


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


def test_material_profile_inherits_single_document_material_and_keeps_filename():
    profiles, frames = _frames()
    profiles.loc[0, "title"] = None
    profiles.loc[
        0,
        "source_filename",
    ] = "Effect of energy density on 316L stainless steel.pdf"
    variants = frames["sample_variants"].copy()
    variants.at[0, "host_material_system"] = {
        "name": "unspecified material system",
    }
    variants.at[0, "composition"] = "unspecified material system"
    frames["sample_variants"] = variants

    service = _service_from_frames(profiles, frames)

    materials = service.list_collection_materials("col-1")
    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    assert [item["material_id"] for item in materials["materials"]] == [
        "mat-316l-stainless-steel"
    ]
    assert materials["materials"][0]["sample_count"] == 1
    assert profile["canonical_name"] == "316L stainless steel"
    assert profile["papers"][0].get("title") is None
    assert profile["papers"][0]["source_filename"] == (
        "Effect of energy density on 316L stainless steel.pdf"
    )
    assert profile["sample_matrix"]["rows"][0]["material"] == "316L stainless steel"


def test_material_profile_inherits_single_document_comparison_material():
    profiles, frames = _frames()
    profiles.loc[0, "title"] = "PBF Sample Study"
    variants = frames["sample_variants"].copy()
    variants.at[0, "host_material_system"] = {
        "name": "unspecified material system",
    }
    variants.at[0, "composition"] = "unspecified material system"
    frames["sample_variants"] = variants
    comparison_rows = _comparison_rows()
    comparison_rows["material_system_normalized"] = "316L stainless steel"

    service = _service_from_frames(
        profiles,
        frames,
        comparison_rows=comparison_rows,
    )

    materials = service.list_collection_materials("col-1")
    profile = service.get_collection_material_research_view(
        "col-1",
        "mat-316l-stainless-steel",
    )

    assert [item["material_id"] for item in materials["materials"]] == [
        "mat-316l-stainless-steel"
    ]
    assert profile["canonical_name"] == "316L stainless steel"
    assert profile["overview"]["sample_count"] == 1
    assert profile["sample_matrix"]["rows"][0]["material"] == "316L stainless steel"
