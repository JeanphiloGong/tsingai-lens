from __future__ import annotations

import asyncio
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
from application.core.comparison_projection import ComparisonRowProjector
from application.core.semantic_build.document_profile_service import DocumentProfileService
from controllers.core import documents as documents_controller
from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    CoreFactSet,
    DocumentProfile,
    MeasurementResult,
    SampleVariant,
    StructureFeature,
    TestCondition as CoreTestCondition,
)
from domain.source import SourceArtifactSet
from tests.support.pbf_acceptance_fixture import (
    PBF_BASELINE_LABEL,
    PBF_DOCUMENT_ID,
    PBF_ELONGATION_COMPARABLE_ID,
    PBF_S3_VARIANT_ID,
    PBF_YIELD_25_COMPARABLE_ID,
    PBF_YIELD_200_COMPARABLE_ID,
    PBF_YIELD_SERIES_KEY,
    pbf_acceptance_baseline_references,
    pbf_acceptance_characterization_observations,
    pbf_acceptance_comparison_records,
    pbf_acceptance_measurement_results,
    pbf_acceptance_sample_variants,
    pbf_acceptance_structure_features,
    pbf_acceptance_test_conditions,
)


def _store_document_profiles(
    document_profile_service: DocumentProfileService,
    collection_id: str,
    profiles: list[dict],
) -> None:
    document_profile_service.core_fact_repository.replace_collection_document_profiles(
        collection_id,
        tuple(DocumentProfile.from_mapping(row) for row in profiles),
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


def _store_core_document_semantics(
    comparison_service: ComparisonService,
    collection_id: str,
    *,
    comparable_results: list[dict] | None = None,
    scoped_results: list[dict] | None = None,
    sample_variants: list[dict] | None = None,
    test_conditions: list[dict] | None = None,
    baseline_references: list[dict] | None = None,
    measurement_results: list[dict] | None = None,
    characterization_observations: list[dict] | None = None,
    structure_features: list[dict] | None = None,
) -> None:
    comparable_results = comparable_results or []
    scoped_results = scoped_results or []
    comparison_rows: tuple[ComparisonRowRecord, ...] = ()
    if comparable_results and scoped_results:
        comparison_rows = ComparisonRowProjector().project_rows_from_semantic_artifacts(
            collection_id=collection_id,
            comparable_results=(
                ComparableResult.from_mapping(row) for row in comparable_results
            ),
            scoped_results=(
                CollectionComparableResult.from_mapping(row)
                for row in scoped_results
            ),
        )
    comparison_service.core_fact_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            paper_facts_ready=True,
            comparison_artifacts_ready=True,
            sample_variants=tuple(
                SampleVariant.from_mapping(row) for row in (sample_variants or [])
            ),
            test_conditions=tuple(
                CoreTestCondition.from_mapping(row)
                for row in (test_conditions or [])
            ),
            baseline_references=tuple(
                BaselineReference.from_mapping(row)
                for row in (baseline_references or [])
            ),
            measurement_results=tuple(
                MeasurementResult.from_mapping(row)
                for row in (measurement_results or [])
            ),
            characterization_observations=tuple(
                CharacterizationObservation.from_mapping(row)
                for row in (characterization_observations or [])
            ),
            structure_features=tuple(
                StructureFeature.from_mapping(row)
                for row in (structure_features or [])
            ),
            comparable_results=tuple(
                ComparableResult.from_mapping(row) for row in comparable_results
            ),
            collection_comparable_results=tuple(
                CollectionComparableResult.from_mapping(row)
                for row in scoped_results
            ),
            comparison_rows=comparison_rows,
        ),
    )


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


def test_document_profile_route_returns_single_profile(document_services):
    collection_service, artifact_registry, document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Single Profile Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Single Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_profile(collection_id, "paper-1")
    )

    assert payload.document_id == "paper-1"
    assert payload.collection_id == collection_id
    assert payload.title == "Single Paper"


def test_document_profile_route_normalizes_invalid_profile_status_values(
    document_services,
):
    collection_service, artifact_registry, document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Invalid Profile Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Single Paper",
                "source_filename": "paper.txt",
                "doc_type": "research_article",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.get_collection_document_profile(collection_id, "paper-1")
    )

    assert payload.doc_type == "experimental"


def test_document_content_route_includes_source_locators(
    document_services,
):
    collection_service, artifact_registry, document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Document Locator Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    document_profile_service.source_artifact_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Locator Paper",
                    "source_filename": "paper-1.pdf",
                    "text": "The optimized sample reached 940 MPa. Missing locator paragraph.",
                }
            ],
            blocks=[
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
                    "bbox": {
                        "l": 72.4,
                        "t": 182.1,
                        "r": 512.8,
                        "b": 228.6,
                        "coord_origin": "top_left",
                    },
                    "char_range": {"start": 0, "end": 37},
                },
            ],
        ),
    )
    _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Locator Paper",
                "source_filename": "paper-1.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
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


def test_document_source_route_resolves_profile_document_id_by_source_filename(
    document_services,
):
    collection_service, artifact_registry, document_profile_service, _comparison_service = document_services
    record = collection_service.create_collection(name="Profile Source File Collection")
    collection_id = record["collection_id"]
    paths = collection_service.get_paths(collection_id)
    output_dir = paths.output_dir
    source_path = paths.input_dir / "stored-paper.pdf"
    source_path.write_bytes(b"%PDF-1.4\nprofile fixture\n")
    _store_document_profiles(
        document_profile_service,
        collection_id,
        [
            {
                "document_id": "profile-hash-doc",
                "collection_id": collection_id,
                "title": "Profile Paper",
                "source_filename": "paper.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ],
    )
    artifact_registry.upsert(collection_id, output_dir)
    collection_service.repository.write_import_manifest(
        collection_id,
        {
            "collection_id": collection_id,
            "imports": [
                {
                    "documents": [
                        {
                            "source_document_id": "srcdoc-from-upload",
                            "original_filename": "paper.pdf",
                            "stored_filename": "stored-paper.pdf",
                            "storage_relpath": "input/stored-paper.pdf",
                            "media_type": "application/pdf",
                        }
                    ]
                }
            ],
        },
    )

    response = asyncio.run(
        documents_controller.get_collection_document_source(
            collection_id,
            "profile-hash-doc",
        )
    )

    assert Path(response.path).read_bytes() == b"%PDF-1.4\nprofile fixture\n"
    assert response.media_type == "application/pdf"


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
):
    collection_service, artifact_registry, _document_profile_service, comparison_service = document_services
    record = collection_service.create_collection(name="Missing Document Semantics")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    comparison_service.core_fact_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            comparison_artifacts_ready=True,
            document_profiles=(
                DocumentProfile.from_mapping(
                    {
                        "document_id": "paper-2",
                        "collection_id": collection_id,
                        "title": "Other Paper",
                        "source_filename": "other.txt",
                        "doc_type": "experimental",
                        "confidence": 0.9,
                    }
                ),
            ),
        ),
    )
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
):
    collection_service, _artifact_registry, _document_profile_service, comparison_service = document_services
    record = collection_service.create_collection(name="Document Semantic Drilldown")
    collection_id = record["collection_id"]

    comparable_result, scoped_result = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
    )
    _store_core_document_semantics(
        comparison_service,
        collection_id,
        comparable_results=[comparable_result],
        scoped_results=[scoped_result],
    )

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
):
    collection_service, _artifact_registry, _document_profile_service, comparison_service = document_services
    record = collection_service.create_collection(name="Document Semantic Projection")
    collection_id = record["collection_id"]

    comparable_result, scoped_result = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
    )
    _store_core_document_semantics(
        comparison_service,
        collection_id,
        comparable_results=[comparable_result],
        scoped_results=[scoped_result],
    )

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
):
    collection_service, _artifact_registry, _document_profile_service, comparison_service = document_services
    record = collection_service.create_collection(name="Document Evidence Chain")
    collection_id = record["collection_id"]
    sample_variants = pbf_acceptance_sample_variants(collection_id)
    test_conditions = pbf_acceptance_test_conditions(collection_id)
    baseline_references = pbf_acceptance_baseline_references(collection_id)
    measurement_results = pbf_acceptance_measurement_results(collection_id)
    characterization_observations = pbf_acceptance_characterization_observations(
        collection_id
    )
    structure_features = pbf_acceptance_structure_features(collection_id)
    comparable_results, scoped_results = pbf_acceptance_comparison_records(
        collection_id,
        sample_variants=sample_variants,
        test_conditions=test_conditions,
        baseline_references=baseline_references,
        measurement_results=measurement_results,
    )
    _store_core_document_semantics(
        comparison_service,
        collection_id,
        sample_variants=sample_variants,
        test_conditions=test_conditions,
        baseline_references=baseline_references,
        measurement_results=measurement_results,
        characterization_observations=characterization_observations,
        structure_features=structure_features,
        comparable_results=comparable_results,
        scoped_results=scoped_results,
    )

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
