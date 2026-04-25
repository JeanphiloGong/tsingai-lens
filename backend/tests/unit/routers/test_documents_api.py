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
from controllers.core import documents as documents_controller
from infra.source.runtime.source_evidence import build_blocks
from tests.support.pbf_acceptance_fixture import (
    PBF_BASELINE_LABEL,
    PBF_DOCUMENT_ID,
    PBF_ELONGATION_COMPARABLE_ID,
    PBF_S3_VARIANT_ID,
    PBF_YIELD_25_COMPARABLE_ID,
    PBF_YIELD_200_COMPARABLE_ID,
    PBF_YIELD_SERIES_KEY,
    write_pbf_acceptance_artifacts,
)


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


def _write_blocks(output_dir: Path, documents: pd.DataFrame) -> None:
    build_blocks(documents, None).to_parquet(output_dir / "blocks.parquet", index=False)


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


def _build_semantic_comparison_record(
    *,
    collection_id: str,
    comparable_result_id: str,
    source_document_id: str,
    sort_order: int = 0,
) -> tuple[dict, dict]:
    comparable_result = {
        "comparable_result_id": comparable_result_id,
        "source_result_id": f"res-{comparable_result_id}",
        "source_document_id": source_document_id,
        "binding": {
            "variant_id": "var-1",
            "baseline_id": "base-1",
            "test_condition_id": "tc-1",
        },
        "normalized_context": {
            "material_system_normalized": "epoxy composite",
            "process_normalized": "80 C, 2 h, under Ar",
            "baseline_normalized": "untreated baseline",
            "test_condition_normalized": "SEM",
        },
        "axis": {
            "axis_name": None,
            "axis_value": None,
            "axis_unit": None,
        },
        "value": {
            "property_normalized": "flexural_strength",
            "result_type": "scalar",
            "numeric_value": 97.0,
            "unit": "MPa",
            "summary": "Flexural strength increased to 97 MPa.",
            "statistic_type": None,
            "uncertainty": None,
        },
        "evidence": {
            "direct_anchor_ids": ["anchor-1"],
            "contextual_anchor_ids": ["anchor-2"],
            "evidence_ids": ["ev-result-1"],
            "structure_feature_ids": [],
            "characterization_observation_ids": [],
            "traceability_status": "direct",
        },
        "variant_label": "epoxy composite",
        "baseline_reference": "untreated baseline",
        "result_source_type": "text",
        "epistemic_status": "normalized_from_evidence",
        "normalization_version": "comparable_result_v1",
    }
    scoped_result = {
        "collection_id": collection_id,
        "comparable_result_id": comparable_result_id,
        "assessment": {
            "missing_critical_context": [],
            "comparability_basis": [
                "variant_linked",
                "baseline_resolved",
                "test_condition_resolved",
                "direct_traceability",
                "numeric_value_available",
                "result_type:scalar",
            ],
            "comparability_warnings": [],
            "comparability_status": "comparable",
            "requires_expert_review": False,
            "assessment_epistemic_status": "normalized_from_evidence",
        },
        "epistemic_status": "normalized_from_evidence",
        "included": True,
        "sort_order": sort_order,
        "policy_family": "default_collection_comparison_policy",
        "policy_version": "comparison_policy_v1",
        "comparable_result_normalization_version": "comparable_result_v1",
        "assessment_input_fingerprint": f"cafp-{comparable_result_id}",
        "reassessment_triggers": [
            "policy_family_changed",
            "policy_version_changed",
            "comparable_result_normalization_version_changed",
            "assessment_input_fingerprint_changed",
        ],
    }
    return comparable_result, scoped_result


@pytest.fixture()
def document_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    comparison_service = ComparisonService(collection_service, artifact_registry)

    monkeypatch.setattr(documents_controller, "document_profile_service", document_profile_service)
    monkeypatch.setattr(documents_controller, "comparison_service", comparison_service)

    return collection_service, artifact_registry, document_profile_service, comparison_service


def test_documents_route_returns_409_when_profiles_are_not_ready(document_services):
    collection_service, _artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.list_collection_document_profiles(record["collection_id"])
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_profiles_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_documents_route_returns_404_for_missing_collection(document_services):
    _collection_service, _artifact_registry, _document_profile_service, _comparison_service = document_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.list_collection_document_profiles("col_missing")
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


def test_documents_route_returns_200_with_empty_profiles_after_stage_generated(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Empty Profiles Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(columns=["id", "title", "text"]).to_parquet(
        output_dir / "documents.parquet",
        index=False,
    )
    _write_blocks(output_dir, pd.DataFrame(columns=["id", "title", "text"]))
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.list_collection_document_profiles(collection_id)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 0
    assert payload.count == 0


def test_document_profile_route_returns_single_profile(document_services, monkeypatch):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Single Profile Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Single Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": ["methods_section_detected"],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_profile(collection_id, "paper-1")
    )

    assert payload.document_id == "paper-1"
    assert payload.collection_id == collection_id
    assert payload.title == "Single Paper"


def test_document_profile_route_normalizes_invalid_profile_status_values(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Invalid Profile Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Single Paper",
                "source_filename": "paper.txt",
                "doc_type": "research_article",
                "protocol_extractable": "Laser-TIG hybrid additive manufacturing produced finer grains.",
                "protocol_extractability_signals": [
                    "methods_section_detected",
                    "procedural_actions_detected",
                    "condition_markers_detected",
                ],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_profile(collection_id, "paper-1")
    )

    assert payload.doc_type == "experimental"
    assert payload.protocol_extractable == "uncertain"


def test_document_content_route_includes_source_locators(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Document Locator Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Locator Paper",
                "source_filename": "paper-1.pdf",
                "text": "The optimized sample reached 940 MPa. Missing locator paragraph.",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet", index=False)
    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Locator Paper",
                "source_filename": "paper-1.pdf",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "block_id": "blk-result",
                "block_type": "paragraph",
                "heading_path": "Results",
                "heading_level": 1,
                "block_order": 1,
                "text": "The optimized sample reached 940 MPa.",
                "text_unit_ids": [],
                "page": 6,
                "bbox": json.dumps(
                    {"l": 72.4, "t": 182.1, "r": 512.8, "b": 228.6, "coord_origin": "top_left"}
                ),
                "char_range": json.dumps({"start": 0, "end": 37}),
            },
            {
                "document_id": "paper-1",
                "block_id": "blk-invalid",
                "block_type": "paragraph",
                "heading_path": "Results",
                "heading_level": 1,
                "block_order": 2,
                "text": "Missing locator paragraph.",
                "text_unit_ids": [],
                "page": 0,
                "bbox": "not-json",
                "char_range": json.dumps({"start": 20, "end": 10}),
            },
        ]
    ).to_parquet(output_dir / "blocks.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_content(collection_id, "paper-1")
    )

    first = payload.blocks[0]
    assert first.page == 6
    assert first.bbox is not None
    assert first.bbox.x0 == 72.4
    assert first.bbox.y0 == 182.1
    assert first.bbox.x1 == 512.8
    assert first.bbox.y1 == 228.6
    assert first.bbox.coord_origin == "top_left"
    assert first.char_range is not None
    assert first.char_range.start == 0
    assert first.char_range.end == 37

    second = payload.blocks[1]
    assert second.page is None
    assert second.bbox is None
    assert second.char_range is None


def test_document_source_route_streams_manifest_source_file(document_services):
    collection_service, _artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Source File Collection")
    collection_id = record["collection_id"]
    paths = collection_service.get_paths(collection_id)
    source_path = paths.input_dir / "paper-1.pdf"
    source_path.write_bytes(b"%PDF-1.4\nfixture\n")
    collection_service.repository.write_import_manifest(
        collection_id,
        {
            "collection_id": collection_id,
            "imports": [
                {
                    "documents": [
                        {
                            "source_document_id": "paper-1",
                            "original_filename": "paper-1.pdf",
                            "stored_filename": "paper-1.pdf",
                            "storage_relpath": "input/paper-1.pdf",
                            "media_type": "application/pdf",
                        }
                    ]
                }
            ],
        },
    )

    response = asyncio.run(
        documents_controller.get_collection_document_source(collection_id, "paper-1")
    )

    assert Path(response.path).read_bytes() == b"%PDF-1.4\nfixture\n"
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


def test_document_source_route_returns_409_when_source_is_unavailable(document_services):
    collection_service, _artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Missing Source Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.get_collection_document_source(
                record["collection_id"],
                "paper-1",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_source_unavailable"
    assert exc.detail["document_id"] == "paper-1"


def test_document_source_route_rejects_manifest_path_outside_collection(
    document_services,
    tmp_path,
):
    collection_service, _artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Unsafe Source Collection")
    collection_id = record["collection_id"]
    outside_path = tmp_path / "outside.pdf"
    outside_path.write_bytes(b"%PDF-1.4\noutside\n")
    collection_service.repository.write_import_manifest(
        collection_id,
        {
            "collection_id": collection_id,
            "imports": [
                {
                    "documents": [
                        {
                            "source_document_id": "paper-1",
                            "original_filename": "paper-1.pdf",
                            "stored_path": str(outside_path),
                            "media_type": "application/pdf",
                        }
                    ]
                }
            ],
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.get_collection_document_source(collection_id, "paper-1")
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_source_path_invalid"
    assert "outside.pdf" not in str(exc.detail)


def test_document_comparison_semantics_route_returns_409_when_semantics_are_not_ready(
    document_services,
):
    collection_service, _artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Pending Semantic Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.get_collection_document_comparison_semantics(
                record["collection_id"],
                "paper-1",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_comparison_semantics_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_document_comparison_semantics_route_returns_404_for_missing_document(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Missing Document Semantics")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    _write_semantic_comparison_artifacts(output_dir, [], [])
    pd.DataFrame(
        [
            {
                "document_id": "paper-2",
                "collection_id": collection_id,
                "title": "Other Paper",
                "source_filename": "other.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.9,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.get_collection_document_comparison_semantics(
                collection_id,
                "paper-1",
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "document_not_found"
    assert exc.detail["document_id"] == "paper-1"


def test_document_comparison_semantics_route_returns_semantic_items_for_document(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Document Semantic Drilldown")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    comparable_result, scoped_result = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_comparison_semantics(
            collection_id,
            "paper-1",
        )
    )

    assert payload.collection_id == collection_id
    assert payload.document_id == "paper-1"
    assert payload.total == 1
    assert payload.count == 1
    assert payload.items[0].comparable_result_id == "cres-1"
    assert payload.items[0].source_document_id == "paper-1"
    assert payload.items[0].collection_overlays[0].collection_id == collection_id
    assert payload.items[0].collection_overlays[0].policy_version == "comparison_policy_v1"
    assert payload.items[0].collection_overlays[0].reassessment_triggers == [
        "policy_family_changed",
        "policy_version_changed",
        "comparable_result_normalization_version_changed",
        "assessment_input_fingerprint_changed",
    ]
    assert payload.items[0].projected_rows is None


def test_document_comparison_semantics_route_can_include_projected_rows(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Document Semantic Projection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    comparable_result, scoped_result = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_comparison_semantics(
            collection_id,
            "paper-1",
            include_row_projections=True,
        )
    )

    assert payload.total == 1
    assert payload.items[0].projected_rows is not None
    assert len(payload.items[0].projected_rows) == 1
    assert payload.items[0].projected_rows[0].row_id.startswith("cmp_")
    assert payload.items[0].projected_rows[0].source_document_id == "paper-1"


def test_document_comparison_semantics_route_returns_pbf_acceptance_chain(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Document Evidence Chain")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    write_pbf_acceptance_artifacts(output_dir, collection_id=collection_id)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_comparison_semantics(
            collection_id,
            PBF_DOCUMENT_ID,
            include_grouped_projections=True,
        )
    )

    assert payload.total == 3
    assert payload.variant_dossiers is not None
    assert len(payload.variant_dossiers) == 1
    dossier = payload.variant_dossiers[0]
    assert dossier.variant_id == PBF_S3_VARIANT_ID
    assert dossier.variant_label == "S3 optimized VED + HIP"
    assert dossier.material.label == "Ti-6Al-4V"
    assert dossier.material.composition == "Ti-6Al-4V"
    assert dossier.shared_process_state["laser_power_w"] == 280
    assert dossier.shared_process_state["scan_speed_mm_s"] == 1200
    assert dossier.shared_process_state["hatch_spacing_um"] == 100
    assert dossier.shared_process_state["layer_thickness_um"] == 30
    assert dossier.shared_process_state["energy_density_j_mm3"] == 78
    assert dossier.shared_process_state["energy_density_origin"] == "reported"
    assert dossier.shared_process_state["build_orientation"] == "vertical"
    assert dossier.shared_process_state["post_treatment_summary"] == "HIP"
    series_by_key = {series.series_key: series for series in dossier.series}
    assert PBF_YIELD_SERIES_KEY in series_by_key
    yield_series = series_by_key[PBF_YIELD_SERIES_KEY]
    assert yield_series.varying_axis.axis_name == "test_temperature_c"
    assert [chain.result_id for chain in yield_series.chains] == [
        PBF_YIELD_25_COMPARABLE_ID,
        PBF_YIELD_200_COMPARABLE_ID,
    ]
    assert [chain.test_condition.test_temperature_c for chain in yield_series.chains] == [
        25.0,
        200.0,
    ]
    assert [chain.test_condition.strain_rate_s_1 for chain in yield_series.chains] == [
        0.001,
        0.001,
    ]
    assert [chain.measurement.value for chain in yield_series.chains] == [940.0, 820.0]
    assert yield_series.chains[0].baseline.reference == PBF_BASELINE_LABEL
    assert yield_series.chains[0].value_provenance.value_origin == "reported"
    assert yield_series.chains[0].value_provenance.source_value_text == "940"
    elongation_chain = next(
        chain
        for series in dossier.series
        for chain in series.chains
        if chain.result_id == PBF_ELONGATION_COMPARABLE_ID
    )
    assert elongation_chain.measurement.property == "elongation"
    assert elongation_chain.measurement.value == 15.0
