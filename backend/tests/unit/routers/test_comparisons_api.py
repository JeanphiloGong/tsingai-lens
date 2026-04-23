from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.core.comparison_service import ComparisonService
from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.semantic_build.paper_facts_service import PaperFactsService
from controllers.core import comparisons as comparisons_controller
from domain.core.comparison import build_comparison_row_id
from infra.source.runtime.source_evidence import build_blocks, build_table_cells, build_table_rows


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        payload = {
            "columns": list(frame.columns),
            "records": frame.to_dict(orient="records"),
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload["records"], columns=payload["columns"])

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _write_source_artifacts(
    output_dir: Path,
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> None:
    build_blocks(documents, text_units).to_parquet(output_dir / "blocks.parquet", index=False)
    build_table_rows(documents, text_units).to_parquet(output_dir / "table_rows.parquet", index=False)
    build_table_cells(documents, text_units).to_parquet(output_dir / "table_cells.parquet", index=False)


def _build_semantic_comparison_record(
    *,
    collection_id: str,
    comparable_result_id: str,
    source_document_id: str,
    variant_id: str | None,
    variant_label: str | None,
    variable_axis: str | None,
    variable_value,
    baseline_reference: str | None,
    result_source_type: str | None,
    result_type: str,
    result_summary: str,
    supporting_evidence_ids: list[str],
    supporting_anchor_ids: list[str],
    characterization_observation_ids: list[str],
    structure_feature_ids: list[str],
    material_system_normalized: str,
    process_normalized: str,
    property_normalized: str,
    baseline_normalized: str,
    test_condition_normalized: str,
    comparability_status: str,
    comparability_warnings: list[str],
    comparability_basis: list[str],
    requires_expert_review: bool,
    assessment_epistemic_status: str,
    missing_critical_context: list[str],
    value: float | None,
    unit: str | None,
    sort_order: int,
) -> tuple[dict, dict, str]:
    comparable_result = {
        "comparable_result_id": comparable_result_id,
        "source_result_id": f"res-{comparable_result_id}",
        "source_document_id": source_document_id,
        "binding": {
            "variant_id": variant_id,
            "baseline_id": f"base-{comparable_result_id}" if baseline_reference else None,
            "test_condition_id": (
                f"tc-{comparable_result_id}" if test_condition_normalized else None
            ),
        },
        "normalized_context": {
            "material_system_normalized": material_system_normalized,
            "process_normalized": process_normalized,
            "baseline_normalized": baseline_normalized,
            "test_condition_normalized": test_condition_normalized,
        },
        "axis": {
            "axis_name": variable_axis,
            "axis_value": variable_value,
            "axis_unit": None,
        },
        "value": {
            "property_normalized": property_normalized,
            "result_type": result_type,
            "numeric_value": value,
            "unit": unit,
            "summary": result_summary,
            "statistic_type": None,
            "uncertainty": None,
        },
        "evidence": {
            "direct_anchor_ids": supporting_anchor_ids,
            "contextual_anchor_ids": [],
            "evidence_ids": supporting_evidence_ids,
            "structure_feature_ids": structure_feature_ids,
            "characterization_observation_ids": characterization_observation_ids,
            "traceability_status": "direct",
        },
        "variant_label": variant_label,
        "baseline_reference": baseline_reference,
        "result_source_type": result_source_type,
        "epistemic_status": assessment_epistemic_status,
        "normalization_version": "comparable_result_v1",
    }
    scoped_result = {
        "collection_id": collection_id,
        "comparable_result_id": comparable_result_id,
        "assessment": {
            "missing_critical_context": missing_critical_context,
            "comparability_basis": comparability_basis,
            "comparability_warnings": comparability_warnings,
            "comparability_status": comparability_status,
            "requires_expert_review": requires_expert_review,
            "assessment_epistemic_status": assessment_epistemic_status,
        },
        "epistemic_status": assessment_epistemic_status,
        "included": True,
        "sort_order": sort_order,
    }
    row_id = build_comparison_row_id(
        collection_id=collection_id,
        comparable_result_id=comparable_result_id,
    )
    return comparable_result, scoped_result, row_id


def _write_semantic_comparison_artifacts(
    output_dir: Path,
    comparable_results: list[dict],
    scoped_results: list[dict],
) -> None:
    pd.DataFrame(comparable_results).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(scoped_results).to_parquet(
        output_dir / "collection_comparable_results.parquet",
        index=False,
    )


@pytest.fixture()
def comparison_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        paper_facts_service,
    )

    monkeypatch.setattr(comparisons_controller, "comparison_service", comparison_service)

    return collection_service, artifact_registry, comparison_service


def test_comparisons_route_returns_409_when_rows_are_not_ready(comparison_services):
    collection_service, _artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(comparisons_controller.list_collection_comparisons(record["collection_id"]))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "comparison_rows_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_comparisons_route_returns_404_for_missing_collection(comparison_services):
    _collection_service, _artifact_registry, _comparison_service = comparison_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(comparisons_controller.list_collection_comparisons("col_missing"))

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


def test_comparisons_route_returns_200_with_empty_rows_after_stage_generated(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Empty Comparisons Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Review of Composite Fillers",
                "text": "This review summarizes recent advances in composite filler systems.",
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    _write_source_artifacts(output_dir, documents, None)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        comparisons_controller.list_collection_comparisons(collection_id)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 0
    assert payload.count == 0


def test_comparisons_route_exposes_v2_contract_fields_for_existing_rows(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Existing Comparisons Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    comparable_result, scoped_result, row_id = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
        variant_id="var-1",
        variant_label="A1",
        variable_axis="induction_current",
        variable_value=10,
        baseline_reference="as-prepared",
        result_source_type="table",
        result_type="scalar",
        result_summary="12 mS/cm",
        supporting_evidence_ids=["ev-1"],
        supporting_anchor_ids=["anchor-1"],
        characterization_observation_ids=["obs-1"],
        structure_feature_ids=["feat-1"],
        material_system_normalized="oxide cathode",
        process_normalized="700 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["variant_linked", "baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=12.0,
        unit="mS/cm",
        sort_order=0,
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        comparisons_controller.list_collection_comparisons(collection_id)
    )

    assert payload.count == 1
    item = payload.items[0]
    assert item.row_id == row_id
    assert item.result_id == "cres-1"
    assert item.display.variant_id == "var-1"
    assert item.display.variant_label == "A1"
    assert item.display.variable_axis == "induction_current"
    assert item.display.variable_value == 10
    assert item.display.baseline_reference == "as-prepared"
    assert item.display.result_summary == "12 mS/cm"
    assert item.evidence_bundle.result_source_type == "table"
    assert item.evidence_bundle.supporting_evidence_ids == ["ev-1"]
    assert item.evidence_bundle.supporting_anchor_ids == ["anchor-1"]
    assert item.assessment.comparability_status == "comparable"
    assert item.assessment.requires_expert_review is False
    assert item.uncertainty.missing_critical_context == []


def test_comparisons_route_applies_canonical_graph_filters(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Filtered Comparisons Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    comparable_result_1, scoped_result_1, row_id_1 = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
        variant_id="var-1",
        variant_label="A1",
        variable_axis="induction_current",
        variable_value=10,
        baseline_reference="as-prepared",
        result_source_type="table",
        result_type="scalar",
        result_summary="12 mS/cm",
        supporting_evidence_ids=["ev-1"],
        supporting_anchor_ids=["anchor-1"],
        characterization_observation_ids=["obs-1"],
        structure_feature_ids=["feat-1"],
        material_system_normalized="oxide cathode",
        process_normalized="700 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["variant_linked", "baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=12.0,
        unit="mS/cm",
        sort_order=0,
    )
    comparable_result_2, scoped_result_2, _row_id_2 = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-2",
        source_document_id="paper-2",
        variant_id="var-2",
        variant_label="B1",
        variable_axis="anneal_atmosphere",
        variable_value="air",
        baseline_reference="air annealed",
        result_source_type="text",
        result_type="trend",
        result_summary="Trend reported",
        supporting_evidence_ids=["ev-2"],
        supporting_anchor_ids=["anchor-2"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="layered oxide",
        process_normalized="air anneal",
        property_normalized="cycle retention",
        baseline_normalized="air annealed",
        test_condition_normalized="cycling",
        comparability_status="limited",
        comparability_warnings=[],
        comparability_basis=["baseline_partial"],
        requires_expert_review=True,
        assessment_epistemic_status="provisional",
        missing_critical_context=[],
        value=None,
        unit=None,
        sort_order=1,
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result_1, comparable_result_2],
        [scoped_result_1, scoped_result_2],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        comparisons_controller.list_collection_comparisons(
            collection_id,
            material_system_normalized="oxide cathode",
            property_normalized="conductivity",
            test_condition_normalized="EIS",
            baseline_normalized="as-prepared",
        )
    )

    assert payload.count == 1
    assert payload.total == 1
    assert payload.items[0].row_id == row_id_1


def test_comparison_route_returns_single_row(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Single Comparison Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    comparable_result, scoped_result, row_id = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
        variant_id="var-1",
        variant_label="A1",
        variable_axis="anneal_temp",
        variable_value=700,
        baseline_reference="as-prepared",
        result_source_type="table",
        result_type="scalar",
        result_summary="12 mS/cm",
        supporting_evidence_ids=["ev-1"],
        supporting_anchor_ids=["anchor-1"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="oxide cathode",
        process_normalized="700 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=12.0,
        unit="mS/cm",
        sort_order=0,
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        comparisons_controller.get_collection_comparison(collection_id, row_id)
    )

    assert payload.row_id == row_id
    assert payload.result_id == "cres-1"
    assert payload.collection_id == collection_id
    assert payload.display.property_normalized == "conductivity"


def test_comparisons_route_returns_409_when_only_row_cache_exists(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Row Cache Only Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "row_id": "cmp-legacy-1",
                "collection_id": collection_id,
                "source_document_id": "paper-1",
                "property_normalized": "conductivity",
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(comparisons_controller.list_collection_comparisons(collection_id))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "comparison_rows_not_ready"
