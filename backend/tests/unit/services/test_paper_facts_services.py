from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from application.core.comparison_assembly import ComparableResultAssembler
from application.core.comparison_projection import ComparisonRowProjector
from application.core.comparison_service import ComparisonService
from application.core.semantic_build.document_profile_service import DocumentProfileService
from application.core.semantic_build.llm.prompts import (
    build_table_row_extraction_prompt,
    build_text_window_extraction_prompt,
)
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.semantic_build.llm.schemas import (
    EvidenceAnchorPayload,
    MethodFactPayload,
    SampleVariantPayload,
    StructuredDocumentProfile,
    StructuredExtractionBundle,
)
from domain.core.comparison import (
    COMPARABLE_RESULT_NORMALIZATION_VERSION,
    COLLECTION_COMPARISON_POLICY_FAMILY,
    COLLECTION_COMPARISON_POLICY_VERSION,
    COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
    CollectionComparableResult,
    ComparableResult,
    ComparisonAxis,
    ContextBinding,
    EvidenceTrace,
    NormalizedComparisonContext,
    ResultValue,
    build_collection_assessment_input_fingerprint,
    evaluate_comparison_assessment,
)
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

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


def _build_test_comparable_result(
    *,
    comparable_result_id: str,
    source_document_id: str,
    source_result_id: str,
    property_normalized: str = "flexural_strength",
    summary: str = "Flexural strength increased to 97 MPa.",
    numeric_value: float | None = 97.0,
) -> ComparableResult:
    return ComparableResult(
        comparable_result_id=comparable_result_id,
        source_result_id=source_result_id,
        source_document_id=source_document_id,
        binding=ContextBinding(
            variant_id="var-1",
            baseline_id="base-1",
            test_condition_id="tc-1",
        ),
        normalized_context=NormalizedComparisonContext(
            material_system_normalized="epoxy composite",
            process_normalized="80 C, 2 h, under Ar",
            baseline_normalized="untreated baseline",
            test_condition_normalized="SEM",
        ),
        axis=ComparisonAxis(
            axis_name=None,
            axis_value=None,
            axis_unit=None,
        ),
        value=ResultValue(
            property_normalized=property_normalized,
            result_type="scalar",
            numeric_value=numeric_value,
            unit="MPa",
            summary=summary,
        ),
        evidence=EvidenceTrace(
            direct_anchor_ids=("anchor-1",),
            contextual_anchor_ids=("anchor-2",),
            evidence_ids=(f"ev_result_{source_result_id}",),
            structure_feature_ids=(),
            characterization_observation_ids=(),
            traceability_status="direct",
        ),
        variant_label="epoxy composite",
        baseline_reference="untreated baseline",
        result_source_type="text",
        epistemic_status="normalized_from_evidence",
        normalization_version=COMPARABLE_RESULT_NORMALIZATION_VERSION,
    )


def _build_collection_overlay(
    *,
    collection_id: str,
    comparable_result: ComparableResult,
    included: bool = True,
    sort_order: int | None = 0,
) -> CollectionComparableResult:
    assessment = evaluate_comparison_assessment(comparable_result)
    return CollectionComparableResult(
        collection_id=collection_id,
        comparable_result_id=comparable_result.comparable_result_id,
        assessment=assessment,
        epistemic_status=assessment.assessment_epistemic_status,
        included=included,
        sort_order=sort_order,
        policy_family=COLLECTION_COMPARISON_POLICY_FAMILY,
        policy_version=COLLECTION_COMPARISON_POLICY_VERSION,
        comparable_result_normalization_version=comparable_result.normalization_version,
        assessment_input_fingerprint=build_collection_assessment_input_fingerprint(
            comparable_result
        ),
        reassessment_triggers=(
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
            COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
        ),
    )


class EvidenceOnlyExtractor:
    def extract_document_profile(self, payload):  # noqa: ANN001
        return StructuredDocumentProfile(
            doc_type="experimental",
            protocol_extractable="yes",
            protocol_extractability_signals=[],
            parsing_warnings=[],
            confidence=0.9,
        )

    def extract_text_window_bundle(self, payload):  # noqa: ANN001
        return StructuredExtractionBundle(
            method_facts=[
                MethodFactPayload(
                    method_role="process",
                    method_name="sample preparation",
                    method_payload={"details": "Process conditions were reported."},
                    anchors=[
                        EvidenceAnchorPayload(
                            quote="Process conditions were reported.",
                            source_type="text",
                        )
                    ],
                    confidence=0.7,
                )
            ]
        )

    def extract_table_row_bundle(self, payload):  # noqa: ANN001, ARG002
        return StructuredExtractionBundle()


def test_paper_facts_prompt_payloads_exclude_internal_ids():
    service = PaperFactsService()

    text_window_payload = service._build_text_window_extraction_payload(
        title="Prompt Boundary Paper",
        source_filename="prompt-boundary.pdf",
        profile={
            "doc_type": "experimental",
            "protocol_extractable": "yes",
        },
        text_window={
            "window_id": "win-1",
            "heading": "Experimental Section",
            "heading_path": "Methods > Experimental Section",
            "text": "Powders were mixed and annealed under Ar.",
            "text_unit_ids": ["tu-1"],
            "block_ids": ["blk-1"],
            "page": 4,
        },
    )
    _, text_window_prompt = build_text_window_extraction_prompt(text_window_payload)
    for field in (
        "document_id",
        "window_id",
        "text_unit_ids",
        "block_ids",
        "table_id",
        "row_index",
        "method_ref",
        "variant_ref",
        "test_condition_ref",
        "baseline_ref",
        "result_ref",
    ):
        assert f'"{field}"' not in text_window_prompt
    assert '"page"' in text_window_prompt

    table_row_payload = service._build_table_row_extraction_payload(
        title="Prompt Boundary Paper",
        source_filename="prompt-boundary.pdf",
        profile={
            "doc_type": "experimental",
            "protocol_extractable": "yes",
        },
        table_row={
            "table_id": "tbl-1",
            "row_index": 2,
            "row_text": "Sample A | 12 MPa | as-built",
            "heading_path": "Results > Table 1",
        },
        row_cells=[
            {
                "header_path": "Sample",
                "cell_text": "A",
                "unit_hint": None,
                "col_index": 0,
            },
            {
                "header_path": "Strength",
                "cell_text": "12",
                "unit_hint": "MPa",
                "col_index": 1,
            },
        ],
        text_windows=[
            {
                "window_id": "win-2",
                "heading": "Results",
                "heading_path": "Results",
                "text": "Annealed samples showed higher strength.",
                "text_unit_ids": ["tu-2"],
                "block_ids": ["blk-2"],
                "page": 5,
            }
        ],
    )
    _, table_row_prompt = build_table_row_extraction_prompt(table_row_payload)
    for field in (
        "document_id",
        "window_id",
        "text_unit_ids",
        "block_ids",
        "table_id",
        "row_index",
        "method_ref",
        "variant_ref",
        "test_condition_ref",
        "baseline_ref",
        "result_ref",
    ):
        assert f'"{field}"' not in table_row_prompt
    assert '"page"' in table_row_prompt


def test_evidence_and_comparison_services_build_backbone_artifacts(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

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

    collection = collection_service.create_collection("Evidence Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Epoxy Composite Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                        "SEM showed columnar beta phase with grain size of 12 um.",
                        "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-3",
                "text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    profiles = document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = paper_facts_service.build_evidence_cards(collection_id, output_dir)
    comparisons = comparison_service.build_comparison_rows(collection_id, output_dir)

    assert not profiles.empty
    assert len(evidence) >= 2
    assert set(evidence["claim_type"]) >= {"process", "characterization", "property"}
    assert not comparisons.empty
    assert "comparable_result_id" in comparisons.columns
    assert "comparability_status" in comparisons.columns
    assert "limited" in set(comparisons["comparability_status"]) or "comparable" in set(
        comparisons["comparability_status"]
    )
    characterization = pd.read_parquet(output_dir / "characterization_observations.parquet")
    structure_features = pd.read_parquet(output_dir / "structure_features.parquet")
    method_facts = pd.read_parquet(output_dir / "method_facts.parquet")
    evidence_anchors = pd.read_parquet(output_dir / "evidence_anchors.parquet")
    test_conditions = pd.read_parquet(output_dir / "test_conditions.parquet")
    baseline_references = pd.read_parquet(output_dir / "baseline_references.parquet")
    sample_variants = pd.read_parquet(output_dir / "sample_variants.parquet")
    measurement_results = pd.read_parquet(output_dir / "measurement_results.parquet")
    comparable_results = pd.read_parquet(output_dir / "comparable_results.parquet")
    collection_comparable_results = pd.read_parquet(
        output_dir / "collection_comparable_results.parquet"
    )
    assert not characterization.empty
    assert not method_facts.empty
    assert not evidence_anchors.empty
    assert not baseline_references.empty
    assert not sample_variants.empty
    assert not measurement_results.empty
    assert not comparable_results.empty
    assert not collection_comparable_results.empty
    assert "directly_observed" in set(characterization["epistemic_status"])
    if not structure_features.empty:
        assert "inferred_from_characterization" in set(structure_features["epistemic_status"])
    if not test_conditions.empty:
        assert "normalized_from_evidence" in set(test_conditions["epistemic_status"])
    assert set(baseline_references["baseline_type"]) == {"implicit_within_document_control"}
    assert "inferred_with_low_confidence" in set(sample_variants["epistemic_status"])
    assert set(measurement_results["result_type"]) == {"scalar"}
    artifacts = artifact_registry.get(collection_id)
    assert artifacts["document_profiles_ready"] is True
    assert artifacts["evidence_anchors_ready"] is True
    assert artifacts["method_facts_ready"] is True
    assert artifacts["evidence_cards_ready"] is True
    assert artifacts["characterization_observations_ready"] is True
    assert artifacts["structure_features_ready"] is (not structure_features.empty)
    assert artifacts["test_conditions_ready"] is (not test_conditions.empty)
    assert artifacts["baseline_references_ready"] is True
    assert artifacts["sample_variants_ready"] is True
    assert artifacts["measurement_results_ready"] is True
    assert artifacts["comparable_results_ready"] is True
    assert artifacts["collection_comparable_results_ready"] is True
    assert artifacts["comparison_rows_ready"] is True


def test_evidence_service_builds_table_backed_property_cards(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Table Evidence Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Conductivity Table Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed and annealed.",
                        "Table 1 Conductivity Results",
                        "Sample | Conductivity (mS/cm) | Baseline",
                        "A | 12 | as-prepared",
                        "B | 18 | annealed",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed and annealed.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = paper_facts_service.build_evidence_cards(collection_id, output_dir)

    table_cards = evidence[evidence["evidence_source_type"] == "table"]
    assert len(table_cards) == 2
    assert any("12 mS/cm" in claim for claim in table_cards["claim_text"])
    assert any("18 mS/cm" in claim for claim in table_cards["claim_text"])
    assert set(table_cards["traceability_status"]) == {"direct"}


def test_evidence_service_builds_sample_variants_and_measurement_results(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Wave D Backbone Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Induction Assisted AM Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Ti alloy samples were fabricated under different induction currents.",
                        "The powders were annealed at 600 C under Ar for 2 h.",
                        "Characterization",
                        "SEM showed columnar beta phase with grain size of 12 um.",
                        "Table 1 Tensile Results",
                        "Sample | Induction Current (A) | Tensile Strength (MPa) | Retention (%) | Baseline",
                        "A0 | 0 | 950 | 88 | as-built",
                        "A1 | 10 | 1010 | 92 | as-built",
                        "A3 | 30 | 1085 | 95 | as-built",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Ti alloy samples were fabricated under different induction currents.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The powders were annealed at 600 C under Ar for 2 h.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    paper_facts_service.build_evidence_cards(collection_id, output_dir)

    sample_variants = pd.read_parquet(output_dir / "sample_variants.parquet")
    measurement_results = pd.read_parquet(output_dir / "measurement_results.parquet")
    baseline_references = pd.read_parquet(output_dir / "baseline_references.parquet")

    assert set(sample_variants["variant_label"]) == {"A0", "A1", "A3"}
    assert set(sample_variants["variable_axis_type"]) == {"induction_current"}
    assert set(sample_variants["variable_value"]) == {0, 10, 30}
    assert all(sample_variants["source_anchor_ids"].astype(str) != "[]")

    assert len(measurement_results) == 6
    assert set(measurement_results["property_normalized"]) == {
        "tensile_strength",
        "retention",
    }
    assert set(measurement_results["result_type"]) == {"scalar", "retention"}
    assert measurement_results["variant_id"].notna().all()
    assert measurement_results["baseline_id"].notna().all()
    assert all(measurement_results["evidence_anchor_ids"].astype(str) != "[]")
    assert set(baseline_references["baseline_label"]) == {"as-built"}


def test_evidence_service_logs_warning_when_measurements_are_empty(monkeypatch, tmp_path, caplog):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    extractor = EvidenceOnlyExtractor()
    document_profile_service = DocumentProfileService(
        collection_service,
        artifact_registry,
        structured_extractor=extractor,
    )
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
        structured_extractor=extractor,
    )

    collection = collection_service.create_collection("Evidence Only Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Process Note",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed and dried under Ar.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed and dried under Ar.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    with caplog.at_level("WARNING"):
        paper_facts_service.build_evidence_cards(collection_id, output_dir)

    assert any(
        "Paper facts extraction produced zero measurement_results" in record.message
        for record in caplog.records
    )


def test_measurement_results_link_entities_without_model_refs(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    class SemanticLinkExtractor:
        def extract_document_profile(self, payload):  # noqa: ANN001, ARG002
            return StructuredDocumentProfile(
                doc_type="experimental",
                protocol_extractable="yes",
                protocol_extractability_signals=[],
                parsing_warnings=[],
                confidence=0.9,
            )

        def extract_text_window_bundle(self, payload):  # noqa: ANN001
            text_window = payload.get("text_window") or {}
            quote = "A0 reached 950 MPa while A1 reached 1010 MPa relative to A0."
            if quote not in str(text_window.get("text") or ""):
                return StructuredExtractionBundle()
            return StructuredExtractionBundle(
                sample_variants=[
                    SampleVariantPayload(
                        variant_label="A0",
                        host_material_system={"family": "Ti alloy", "composition": None},
                        confidence=0.8,
                    ),
                    SampleVariantPayload(
                        variant_label="A1",
                        host_material_system={"family": "Ti alloy", "composition": None},
                        confidence=0.8,
                    ),
                ],
                test_conditions=[
                    {
                        "property_type": "tensile_strength",
                        "condition_payload": {"method": "tensile test", "methods": ["tensile test"]},
                        "confidence": 0.8,
                    }
                ],
                baseline_references=[
                    {
                        "baseline_label": "A0",
                        "confidence": 0.8,
                    }
                ],
                measurement_results=[
                    {
                        "claim_text": "A0 reached 950 MPa relative to A0.",
                        "property_normalized": "tensile_strength",
                        "result_type": "scalar",
                        "value_payload": {"value": 950, "statement": "A0 reached 950 MPa."},
                        "unit": "MPa",
                        "variant_label": "A0",
                        "baseline_label": "A0",
                        "anchors": [{"quote": quote, "source_type": "text"}],
                        "confidence": 0.84,
                    },
                    {
                        "claim_text": "A1 reached 1010 MPa relative to A0.",
                        "property_normalized": "tensile_strength",
                        "result_type": "scalar",
                        "value_payload": {"value": 1010, "statement": "A1 reached 1010 MPa."},
                        "unit": "MPa",
                        "variant_label": "A1",
                        "baseline_label": "A0",
                        "anchors": [{"quote": quote, "source_type": "text"}],
                        "confidence": 0.84,
                    },
                ],
            )

        def extract_table_row_bundle(self, payload):  # noqa: ANN001, ARG002
            return StructuredExtractionBundle()

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    extractor = SemanticLinkExtractor()
    document_profile_service = DocumentProfileService(
        collection_service,
        artifact_registry,
        structured_extractor=extractor,
    )
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
        structured_extractor=extractor,
    )

    collection = collection_service.create_collection("Semantic Link Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Semantic Link Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "A0 reached 950 MPa while A1 reached 1010 MPa relative to A0.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "A0 reached 950 MPa while A1 reached 1010 MPa relative to A0.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    paper_facts_service.build_evidence_cards(collection_id, output_dir)

    sample_variants = pd.read_parquet(output_dir / "sample_variants.parquet")
    test_conditions = pd.read_parquet(output_dir / "test_conditions.parquet")
    baseline_references = pd.read_parquet(output_dir / "baseline_references.parquet")
    measurement_results = pd.read_parquet(output_dir / "measurement_results.parquet")

    variant_lookup = {
        row["variant_label"]: row["variant_id"]
        for _, row in sample_variants.iterrows()
    }
    assert set(variant_lookup) == {"A0", "A1"}
    assert len(test_conditions) == 1
    assert len(baseline_references) == 1
    assert len(measurement_results) == 2
    assert set(measurement_results["variant_id"]) == {
        variant_lookup["A0"],
        variant_lookup["A1"],
    }
    assert measurement_results["test_condition_id"].nunique() == 1
    assert measurement_results["baseline_id"].nunique() == 1


def test_quote_only_anchor_outputs_resolve_traceback_from_local_scope(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    class QuoteOnlyScopeExtractor:
        def extract_document_profile(self, payload):  # noqa: ANN001, ARG002
            return StructuredDocumentProfile(
                doc_type="experimental",
                protocol_extractable="yes",
                protocol_extractability_signals=[],
                parsing_warnings=[],
                confidence=0.9,
            )

        def extract_text_window_bundle(self, payload):  # noqa: ANN001
            text_window = payload.get("text_window") or {}
            quote = "Process conditions were reported."
            if quote not in str(text_window.get("text") or ""):
                return StructuredExtractionBundle()
            return StructuredExtractionBundle(
                method_facts=[
                    MethodFactPayload(
                        method_role="process",
                        method_name="sample preparation",
                        method_payload={"details": quote},
                        anchors=[
                            EvidenceAnchorPayload(
                                quote=quote,
                                source_type="text",
                            )
                        ],
                        confidence=0.7,
                    )
                ]
            )

        def extract_table_row_bundle(self, payload):  # noqa: ANN001, ARG002
            return StructuredExtractionBundle()

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    extractor = QuoteOnlyScopeExtractor()
    document_profile_service = DocumentProfileService(
        collection_service,
        artifact_registry,
        structured_extractor=extractor,
    )
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
        structured_extractor=extractor,
    )

    collection = collection_service.create_collection("Quote Only Anchor Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Quote Only Anchor Paper",
                "text": "Process conditions were reported.",
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Process conditions were reported.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = paper_facts_service.build_evidence_cards(collection_id, output_dir)
    evidence_anchors = pd.read_parquet(output_dir / "evidence_anchors.parquet")
    blocks = build_blocks(documents, text_units)
    methods_block = blocks[
        blocks["text_unit_ids"].apply(lambda value: "tu-1" in (value or []))
    ].iloc[0]

    assert not evidence.empty
    assert not evidence_anchors.empty
    assert evidence_anchors.iloc[0]["section_id"] == methods_block["block_id"]
    assert evidence_anchors.iloc[0]["block_id"] == methods_block["block_id"]
    assert evidence_anchors.iloc[0]["char_range"] is not None

    traceback = paper_facts_service.get_evidence_traceback(
        collection_id,
        str(evidence.iloc[0]["evidence_id"]),
    )
    assert traceback["traceback_status"] == "ready"
    assert traceback["anchors"][0]["locator_type"] == "char_range"
    assert traceback["anchors"][0]["block_id"] == methods_block["block_id"]


def test_comparison_service_logs_warning_when_upstream_measurements_are_empty(
    monkeypatch,
    tmp_path,
    caplog,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    extractor = EvidenceOnlyExtractor()
    document_profile_service = DocumentProfileService(
        collection_service,
        artifact_registry,
        structured_extractor=extractor,
    )
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
        structured_extractor=extractor,
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        paper_facts_service,
    )

    collection = collection_service.create_collection("No Measurement Comparison Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Process Note",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed and dried under Ar.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed and dried under Ar.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    paper_facts_service.build_evidence_cards(collection_id, output_dir)
    with caplog.at_level("WARNING"):
        comparison_service.build_comparison_rows(collection_id, output_dir)

    assert any(
        "Comparison assembly produced zero rows because upstream measurement_results were empty"
        in record.message
        for record in caplog.records
    )


def test_evidence_cards_parquet_write_handles_empty_nested_contexts(tmp_path):
    pytest.importorskip("pyarrow")

    from application.source.collection_service import CollectionService
    from application.core.semantic_build.document_profile_service import DocumentProfileService
    from application.core.semantic_build.paper_facts_service import PaperFactsService
    from application.source.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Process Only Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Process Only Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The slurry was stirred for 2 h and dried at 80 C under Ar.",
                        "Characterization",
                        "SEM was used to inspect the coating.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The slurry was stirred for 2 h and dried at 80 C under Ar.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = paper_facts_service.build_evidence_cards(collection_id, output_dir)

    assert not evidence.empty
    assert output_dir.joinpath("evidence_cards.parquet").exists()
    reloaded = pd.read_parquet(output_dir / "evidence_cards.parquet")
    assert not reloaded.empty
    assert isinstance(reloaded.iloc[0]["condition_context"], str)


def test_evidence_service_normalizes_array_backed_condition_contexts(tmp_path):
    from application.source.collection_service import CollectionService
    from application.core.semantic_build.document_profile_service import DocumentProfileService
    from application.core.semantic_build.paper_facts_service import PaperFactsService
    from application.source.artifact_registry_service import ArtifactRegistryService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    normalized = paper_facts_service._normalize_condition_context_payload(
        {
            "process": {
                "temperatures_c": np.array([80.0, 600.0]),
                "durations": np.array(["2 h", "4 h"], dtype=object),
                "atmosphere": "Ar",
            },
            "baseline": {
                "control": None,
            },
            "test": {
                "methods": np.array(["XRD", "SEM"], dtype=object),
                "method": None,
            },
        }
    )

    assert normalized == {
        "process": {
            "temperatures_c": [80.0, 600.0],
            "durations": ["2 h", "4 h"],
            "atmosphere": "Ar",
        },
        "baseline": {
            "control": None,
        },
        "test": {
            "methods": ["XRD", "SEM"],
            "method": None,
        },
    }


def test_comparison_service_builds_rows_from_array_backed_nested_contexts(tmp_path):
    assembler = ComparableResultAssembler()
    projector = ComparisonRowProjector()

    comparable_result = assembler.assemble_comparable_result(
        result_row=pd.Series(
            {
                "result_id": "res-1",
                "document_id": "paper-1",
                "variant_id": "var-1",
                "property_normalized": "flexural_strength",
                "result_type": "scalar",
                "value_payload": {
                    "value": 97.0,
                    "statement": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                },
                "unit": "MPa",
                "test_condition_id": "tc-1",
                "baseline_id": "base-1",
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "evidence_anchor_ids": ["anchor-1"],
                "traceability_status": "direct",
                "result_source_type": "text",
            }
        ),
        sample_lookup={
            "var-1": {
                "variant_id": "var-1",
                "variant_label": "epoxy composite",
                "variable_axis_type": None,
                "variable_value": None,
                "host_material_system": {
                    "family": "epoxy composite",
                    "composition": None,
                },
                "process_context": {
                    "temperatures_c": np.array([80.0]),
                    "durations": np.array(["2 h"], dtype=object),
                    "atmosphere": "Ar",
                },
            }
        },
        test_condition_lookup={
            "tc-1": {
                "test_condition_id": "tc-1",
                "condition_payload": {
                    "methods": np.array(["SEM"], dtype=object),
                    "method": None,
                },
            }
        },
        baseline_lookup={
            "base-1": {
                "baseline_id": "base-1",
                "baseline_label": "untreated baseline",
            }
        },
    )
    assert comparable_result is not None
    scoped_result = assembler.build_collection_comparable_result(
        collection_id="col-1",
        comparable_result=comparable_result,
        sort_order=0,
    )
    row = projector.project_row(
        comparable_result=comparable_result,
        scoped_result=scoped_result,
    )

    assert row.row_id.startswith("cmp_")
    assert row.comparable_result_id.startswith("cres_")
    assert row.process_normalized == "80 C, 2 h, under Ar"
    assert row.baseline_normalized == "untreated baseline"
    assert row.test_condition_normalized == "SEM"
    assert row.comparability_status == "comparable"
    assert row.supporting_evidence_ids == ("ev_result_res-1",)
    assert list(row.comparability_basis) == [
        "variant_linked",
        "baseline_resolved",
        "test_condition_resolved",
        "direct_traceability",
        "numeric_value_available",
        "result_type:scalar",
    ]
    assert row.assessment_epistemic_status == "normalized_from_evidence"


def test_comparison_service_collapses_duplicate_comparable_results(tmp_path):
    assembler = ComparableResultAssembler()
    projector = ComparisonRowProjector()

    sample_lookup = {
        "var-1": {
            "variant_id": "var-1",
            "variant_label": "epoxy composite",
            "variable_axis_type": None,
            "variable_value": None,
            "host_material_system": {
                "family": "epoxy composite",
                "composition": None,
            },
            "process_context": {
                "temperatures_c": np.array([80.0]),
                "durations": np.array(["2 h"], dtype=object),
                "atmosphere": "Ar",
            },
        }
    }
    test_condition_lookup = {
        "tc-1": {
            "test_condition_id": "tc-1",
            "condition_payload": {
                "methods": np.array(["SEM"], dtype=object),
                "method": None,
            },
        }
    }
    baseline_lookup = {
        "base-1": {
            "baseline_id": "base-1",
            "baseline_label": "untreated baseline",
        }
    }

    first = assembler.assemble_comparable_result(
        result_row=pd.Series(
            {
                "result_id": "res-1",
                "document_id": "paper-1",
                "variant_id": "var-1",
                "property_normalized": "flexural_strength",
                "result_type": "scalar",
                "value_payload": {
                    "value": 97.0,
                    "statement": "Flexural strength increased to 97 MPa.",
                },
                "unit": "MPa",
                "test_condition_id": "tc-1",
                "baseline_id": "base-1",
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "evidence_anchor_ids": ["anchor-1"],
                "traceability_status": "direct",
                "result_source_type": "text",
            }
        ),
        sample_lookup=sample_lookup,
        test_condition_lookup=test_condition_lookup,
        baseline_lookup=baseline_lookup,
    )
    second = assembler.assemble_comparable_result(
        result_row=pd.Series(
            {
                "result_id": "res-2",
                "document_id": "paper-1",
                "variant_id": "var-1",
                "property_normalized": "flexural_strength",
                "result_type": "scalar",
                "value_payload": {
                    "statement": "Flexural strength increased to 97 MPa.",
                    "value": 97.0,
                },
                "unit": "MPa",
                "test_condition_id": "tc-1",
                "baseline_id": "base-1",
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "evidence_anchor_ids": ["anchor-2"],
                "traceability_status": "direct",
                "result_source_type": "text",
            }
        ),
        sample_lookup=sample_lookup,
        test_condition_lookup=test_condition_lookup,
        baseline_lookup=baseline_lookup,
    )

    assert first is not None
    assert second is not None
    assert first.comparable_result_id == second.comparable_result_id

    first_row = projector.project_row(
        comparable_result=first,
        scoped_result=assembler.build_collection_comparable_result(
            collection_id="col-1",
            comparable_result=first,
            sort_order=0,
        ),
    )
    second_row = projector.project_row(
        comparable_result=second,
        scoped_result=assembler.build_collection_comparable_result(
            collection_id="col-1",
            comparable_result=second,
            sort_order=1,
        ),
    )

    merged = projector.merge_row_records(first_row, second_row)

    assert first_row.row_id == second_row.row_id
    assert merged.supporting_evidence_ids == ("ev_result_res-1", "ev_result_res-2")
    assert merged.supporting_anchor_ids == ("anchor-1", "anchor-2")


def test_comparison_service_persists_semantic_and_scope_artifacts_for_duplicate_results(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )
    collection = collection_service.create_collection("Duplicate Comparable Result Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    measurement_results = pd.DataFrame(
        [
            {
                "result_id": "res-1",
                "document_id": "paper-1",
                "variant_id": "var-1",
                "property_normalized": "flexural_strength",
                "result_type": "scalar",
                "value_payload": {
                    "value": 97.0,
                    "statement": "Flexural strength increased to 97 MPa.",
                },
                "unit": "MPa",
                "test_condition_id": "tc-1",
                "baseline_id": "base-1",
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "evidence_anchor_ids": ["anchor-1"],
                "traceability_status": "direct",
                "result_source_type": "text",
            },
            {
                "result_id": "res-2",
                "document_id": "paper-1",
                "variant_id": "var-1",
                "property_normalized": "flexural_strength",
                "result_type": "scalar",
                "value_payload": {
                    "statement": "Flexural strength increased to 97 MPa.",
                    "value": 97.0,
                },
                "unit": "MPa",
                "test_condition_id": "tc-1",
                "baseline_id": "base-1",
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "evidence_anchor_ids": ["anchor-2"],
                "traceability_status": "direct",
                "result_source_type": "text",
            },
        ]
    )
    sample_variants = pd.DataFrame(
        [
            {
                "variant_id": "var-1",
                "variant_label": "epoxy composite",
                "variable_axis_type": None,
                "variable_value": None,
                "host_material_system": {
                    "family": "epoxy composite",
                    "composition": None,
                },
                "process_context": {
                    "temperatures_c": [80.0],
                    "durations": ["2 h"],
                    "atmosphere": "Ar",
                },
                "source_anchor_ids": [],
            }
        ]
    )
    test_conditions = pd.DataFrame(
        [
            {
                "test_condition_id": "tc-1",
                "condition_payload": {
                    "methods": ["SEM"],
                    "method": None,
                },
                "missing_fields": [],
                "evidence_anchor_ids": [],
            }
        ]
    )
    baseline_references = pd.DataFrame(
        [
            {
                "baseline_id": "base-1",
                "baseline_label": "untreated baseline",
                "baseline_type": "implicit_within_document_control",
                "baseline_scope": None,
                "evidence_anchor_ids": [],
            }
        ]
    )

    monkeypatch.setattr(
        comparison_service,
        "_load_comparison_inputs",
        lambda collection_id, base_dir: SimpleNamespace(
            sample_variants=sample_variants,
            measurement_results=measurement_results,
            test_conditions=test_conditions,
            baseline_references=baseline_references,
        ),
    )

    comparison_rows = comparison_service.build_comparison_rows(collection_id, output_dir)
    stored_comparable_results = comparison_service.read_comparable_results(collection_id)
    stored_scoped_results = comparison_service.read_collection_comparable_results(
        collection_id
    )

    assert len(comparison_rows) == 1
    assert len(stored_comparable_results) == 1
    assert len(stored_scoped_results) == 1
    assert stored_comparable_results.iloc[0]["comparable_result_id"].startswith("cres_")
    assert stored_scoped_results.iloc[0]["comparable_result_id"] == stored_comparable_results.iloc[0][
        "comparable_result_id"
    ]
    assert stored_comparable_results.iloc[0]["evidence"]["evidence_ids"] == [
        "ev_result_res-1",
        "ev_result_res-2",
    ]
    assert stored_comparable_results.iloc[0]["evidence"]["direct_anchor_ids"] == [
        "anchor-1",
        "anchor-2",
    ]
    assert (output_dir / "comparable_results.parquet").exists()
    assert (output_dir / "collection_comparable_results.parquet").exists()


def test_evidence_and_comparison_services_round_trip_real_parquet_storage(tmp_path):
    pytest.importorskip("pyarrow")

    from application.source.collection_service import CollectionService
    from application.core.semantic_build.document_profile_service import DocumentProfileService
    from application.core.semantic_build.paper_facts_service import PaperFactsService
    from application.source.artifact_registry_service import ArtifactRegistryService

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

    collection = collection_service.create_collection("Round Trip Evidence Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Epoxy Composite Study",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "SEM was used to characterize the powders.",
                        "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The epoxy and SiO2 powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    evidence = paper_facts_service.build_evidence_cards(collection_id, output_dir)
    comparisons = comparison_service.build_comparison_rows(collection_id, output_dir)

    assert not evidence.empty
    assert not comparisons.empty

    stored_evidence = pd.read_parquet(output_dir / "evidence_cards.parquet")
    stored_comparable_results = pd.read_parquet(output_dir / "comparable_results.parquet")
    stored_scoped_results = pd.read_parquet(output_dir / "collection_comparable_results.parquet")
    stored_comparisons = pd.read_parquet(output_dir / "comparison_rows.parquet")
    assert isinstance(stored_evidence.iloc[0]["evidence_anchors"], str)
    assert isinstance(stored_evidence.iloc[0]["material_system"], str)
    assert isinstance(stored_evidence.iloc[0]["condition_context"], str)
    assert isinstance(stored_comparable_results.iloc[0]["binding"], str)
    assert isinstance(stored_comparable_results.iloc[0]["normalized_context"], str)
    assert isinstance(stored_comparable_results.iloc[0]["axis"], str)
    assert isinstance(stored_comparable_results.iloc[0]["value"], str)
    assert isinstance(stored_comparable_results.iloc[0]["evidence"], str)
    assert isinstance(stored_scoped_results.iloc[0]["assessment"], str)
    assert isinstance(stored_comparisons.iloc[0]["comparable_result_id"], str)
    assert isinstance(stored_comparisons.iloc[0]["supporting_evidence_ids"], str)
    assert isinstance(stored_comparisons.iloc[0]["supporting_anchor_ids"], str)
    assert isinstance(stored_comparisons.iloc[0]["comparability_warnings"], str)
    assert isinstance(stored_comparisons.iloc[0]["comparability_basis"], str)
    assert isinstance(stored_comparisons.iloc[0]["missing_critical_context"], str)

    restored_evidence = paper_facts_service.read_evidence_cards(collection_id)
    restored_comparable_results = comparison_service.read_comparable_results(collection_id)
    restored_scoped_results = comparison_service.read_collection_comparable_results(
        collection_id
    )
    restored_comparisons = comparison_service.read_comparison_rows(collection_id)
    assert isinstance(restored_evidence.iloc[0]["evidence_anchors"], list)
    assert isinstance(restored_evidence.iloc[0]["material_system"], dict)
    assert isinstance(restored_evidence.iloc[0]["condition_context"], dict)
    assert isinstance(restored_comparable_results.iloc[0]["binding"], dict)
    assert isinstance(restored_comparable_results.iloc[0]["normalized_context"], dict)
    assert isinstance(restored_comparable_results.iloc[0]["axis"], dict)
    assert isinstance(restored_comparable_results.iloc[0]["value"], dict)
    assert isinstance(restored_comparable_results.iloc[0]["evidence"], dict)
    assert isinstance(restored_scoped_results.iloc[0]["assessment"], dict)
    assert restored_comparisons.iloc[0]["comparable_result_id"].startswith("cres_")
    assert isinstance(restored_comparisons.iloc[0]["supporting_evidence_ids"], list)
    assert isinstance(restored_comparisons.iloc[0]["supporting_anchor_ids"], list)
    assert isinstance(restored_comparisons.iloc[0]["comparability_warnings"], list)
    assert isinstance(restored_comparisons.iloc[0]["comparability_basis"], list)
    assert isinstance(restored_comparisons.iloc[0]["missing_critical_context"], list)

    comparison_rows_path = output_dir / "comparison_rows.parquet"
    comparison_rows_path.unlink()

    projection_tables = comparison_service.read_comparison_projection(
        collection_id,
        materialize_row_cache=False,
    )
    assert not comparison_rows_path.exists()
    assert not projection_tables.comparable_results.empty
    assert not projection_tables.collection_comparable_results.empty
    assert not projection_tables.comparison_rows.empty
    assert (
        projection_tables.comparison_rows.iloc[0]["comparable_result_id"]
        == restored_comparable_results.iloc[0]["comparable_result_id"]
    )

    reprojected_comparisons = comparison_service.read_comparison_rows(collection_id)
    assert comparison_rows_path.exists()
    assert not reprojected_comparisons.empty
    assert (
        reprojected_comparisons.iloc[0]["comparable_result_id"]
        == restored_comparable_results.iloc[0]["comparable_result_id"]
    )


def test_comparison_service_inspects_document_semantics_from_semantic_artifacts(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(collection_service, artifact_registry)

    collection = collection_service.create_collection("Document Semantic Inspection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    first = _build_test_comparable_result(
        comparable_result_id="cres-doc-1-a",
        source_document_id="paper-1",
        source_result_id="res-1",
    )
    second = _build_test_comparable_result(
        comparable_result_id="cres-doc-1-b",
        source_document_id="paper-1",
        source_result_id="res-2",
        property_normalized="impact_strength",
        summary="Impact strength increased to 61 MPa.",
        numeric_value=61.0,
    )
    other_document = _build_test_comparable_result(
        comparable_result_id="cres-doc-2-a",
        source_document_id="paper-2",
        source_result_id="res-3",
    )
    pd.DataFrame(
        [
            first.to_record(),
            second.to_record(),
            other_document.to_record(),
        ]
    ).to_parquet(output_dir / "comparable_results.parquet", index=False)
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=first,
                sort_order=2,
            ).to_record(),
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=other_document,
                sort_order=0,
            ).to_record(),
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = comparison_service.inspect_document_comparison_semantics(
        collection_id,
        "paper-1",
    )

    assert payload["collection_id"] == collection_id
    assert payload["source_document_id"] == "paper-1"
    assert payload["total"] == 2
    assert payload["count"] == 2
    assert [item["comparable_result_id"] for item in payload["items"]] == [
        "cres-doc-1-a",
        "cres-doc-1-b",
    ]
    assert payload["items"][0]["collection_overlays"] == [
        _build_collection_overlay(
            collection_id=collection_id,
            comparable_result=first,
            sort_order=2,
        ).to_record()
    ]
    assert payload["items"][0]["collection_overlays"][0]["policy_family"] == (
        COLLECTION_COMPARISON_POLICY_FAMILY
    )
    assert payload["items"][0]["collection_overlays"][0]["policy_version"] == (
        COLLECTION_COMPARISON_POLICY_VERSION
    )
    assert payload["items"][1]["collection_overlays"] == [
        _build_collection_overlay(
            collection_id=collection_id,
            comparable_result=second,
            sort_order=3,
        ).to_record()
    ]
    assert "projected_rows" not in payload["items"][0]
    assert (output_dir / "comparison_rows.parquet").exists()


def test_comparison_service_document_semantic_inspection_can_project_rows_without_row_cache(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(collection_service, artifact_registry)

    collection = collection_service.create_collection("Document Semantic Projection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparable_result = _build_test_comparable_result(
        comparable_result_id="cres-doc-1-a",
        source_document_id="paper-1",
        source_result_id="res-1",
    )
    pd.DataFrame([comparable_result.to_record()]).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=comparable_result,
                sort_order=0,
            ).to_record()
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = comparison_service.inspect_document_comparison_semantics(
        collection_id,
        "paper-1",
        include_row_projections=True,
    )

    assert payload["total"] == 1
    projected_rows = payload["items"][0]["projected_rows"]
    assert len(projected_rows) == 1
    assert projected_rows[0]["row_id"].startswith("cmp_")
    assert projected_rows[0]["collection_id"] == collection_id
    assert projected_rows[0]["source_document_id"] == "paper-1"
    assert projected_rows[0]["display"]["property_normalized"] == "flexural_strength"
    assert projected_rows[0]["assessment"]["comparability_status"] == "comparable"
    assert not (output_dir / "comparison_rows.parquet").exists()


def test_comparison_service_persists_policy_metadata_on_collection_overlays(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )
    collection = collection_service.create_collection("Policy Metadata Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparable_result = _build_test_comparable_result(
        comparable_result_id="cres-policy-1",
        source_document_id="paper-1",
        source_result_id="res-policy-1",
    )
    pd.DataFrame([comparable_result.to_record()]).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=comparable_result,
                sort_order=0,
            ).to_record()
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    overlays = comparison_service.read_collection_comparable_results(collection_id)

    assert overlays.iloc[0]["policy_family"] == COLLECTION_COMPARISON_POLICY_FAMILY
    assert overlays.iloc[0]["policy_version"] == COLLECTION_COMPARISON_POLICY_VERSION
    assert overlays.iloc[0]["comparable_result_normalization_version"] == (
        COMPARABLE_RESULT_NORMALIZATION_VERSION
    )
    assert overlays.iloc[0]["assessment_input_fingerprint"].startswith("cafp_")
    assert overlays.iloc[0]["reassessment_triggers"] == [
        COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
        COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
        COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
        COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
    ]


def test_comparison_service_reassesses_stale_scope_artifacts_and_refreshes_row_cache(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )
    collection = collection_service.create_collection("Stale Scope Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparable_result = _build_test_comparable_result(
        comparable_result_id="cres-stale-1",
        source_document_id="paper-1",
        source_result_id="res-stale-1",
    )
    pd.DataFrame([comparable_result.to_record()]).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    stale_overlay = _build_collection_overlay(
        collection_id=collection_id,
        comparable_result=comparable_result,
        sort_order=7,
    ).to_record()
    stale_overlay["policy_version"] = "comparison_policy_v0"
    stale_overlay["assessment_input_fingerprint"] = "cafp_outdated"
    pd.DataFrame([stale_overlay]).to_parquet(
        output_dir / "collection_comparable_results.parquet",
        index=False,
    )
    artifact_registry.upsert(collection_id, output_dir)

    overlays = comparison_service.read_collection_comparable_results(collection_id)

    assert overlays.iloc[0]["policy_version"] == COLLECTION_COMPARISON_POLICY_VERSION
    assert overlays.iloc[0]["assessment_input_fingerprint"].startswith("cafp_")
    assert overlays.iloc[0]["assessment_input_fingerprint"] != "cafp_outdated"
    assert overlays.iloc[0]["sort_order"] == 7
    assert (output_dir / "comparison_rows.parquet").exists()

    artifacts = artifact_registry.get(collection_id)
    assert artifacts["collection_comparable_results_ready"] is True
    assert artifacts["collection_comparable_results_stale"] is False
    assert artifacts["comparison_rows_generated"] is True
    assert artifacts["comparison_rows_ready"] is True
    assert artifacts["comparison_rows_stale"] is False
    assert artifacts["graph_generated"] is False
    assert artifacts["graph_ready"] is False
    assert artifacts["graph_stale"] is False


def test_comparison_service_lists_corpus_comparable_results_across_collections_without_row_cache(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )

    first_collection = collection_service.create_collection("Corpus Collection A")
    second_collection = collection_service.create_collection("Corpus Collection B")
    first_collection_id = first_collection["collection_id"]
    second_collection_id = second_collection["collection_id"]

    first_output_dir = collection_service.get_paths(first_collection_id).output_dir
    second_output_dir = collection_service.get_paths(second_collection_id).output_dir
    first_output_dir.mkdir(parents=True, exist_ok=True)
    second_output_dir.mkdir(parents=True, exist_ok=True)

    shared_result = _build_test_comparable_result(
        comparable_result_id="cres-shared-1",
        source_document_id="paper-shared",
        source_result_id="res-shared-1",
    )
    unique_result = _build_test_comparable_result(
        comparable_result_id="cres-unique-1",
        source_document_id="paper-unique",
        source_result_id="res-unique-1",
        property_normalized="impact_strength",
        summary="Impact strength increased to 61 MPa.",
        numeric_value=61.0,
    )

    pd.DataFrame(
        [
            shared_result.to_record(),
            unique_result.to_record(),
        ]
    ).to_parquet(first_output_dir / "comparable_results.parquet", index=False)
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=first_collection_id,
                comparable_result=shared_result,
                sort_order=0,
            ).to_record(),
            _build_collection_overlay(
                collection_id=first_collection_id,
                comparable_result=unique_result,
                sort_order=1,
            ).to_record(),
        ]
    ).to_parquet(first_output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(first_collection_id, first_output_dir)

    pd.DataFrame([shared_result.to_record()]).to_parquet(
        second_output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=second_collection_id,
                comparable_result=shared_result,
                sort_order=4,
            ).to_record()
        ]
    ).to_parquet(second_output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(second_collection_id, second_output_dir)

    payload = comparison_service.list_corpus_comparable_results()

    assert payload["total"] == 2
    assert payload["count"] == 2
    items_by_id = {
        item["comparable_result_id"]: item
        for item in payload["items"]
    }
    assert set(items_by_id) == {"cres-shared-1", "cres-unique-1"}
    assert items_by_id["cres-shared-1"]["observed_collection_ids"] == sorted(
        [first_collection_id, second_collection_id]
    )
    assert len(items_by_id["cres-shared-1"]["collection_overlays"]) == 2
    assert {
        overlay["collection_id"]
        for overlay in items_by_id["cres-shared-1"]["collection_overlays"]
    } == {first_collection_id, second_collection_id}
    assert items_by_id["cres-unique-1"]["observed_collection_ids"] == [first_collection_id]
    assert len(items_by_id["cres-unique-1"]["collection_overlays"]) == 1
    assert not (first_output_dir / "comparison_rows.parquet").exists()
    assert not (second_output_dir / "comparison_rows.parquet").exists()


def test_comparison_service_filters_corpus_results_to_one_collection_and_refreshes_stale_overlay(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )

    first_collection = collection_service.create_collection("Policy Current A")
    second_collection = collection_service.create_collection("Policy Current B")
    first_collection_id = first_collection["collection_id"]
    second_collection_id = second_collection["collection_id"]

    first_output_dir = collection_service.get_paths(first_collection_id).output_dir
    second_output_dir = collection_service.get_paths(second_collection_id).output_dir
    first_output_dir.mkdir(parents=True, exist_ok=True)
    second_output_dir.mkdir(parents=True, exist_ok=True)

    shared_result = _build_test_comparable_result(
        comparable_result_id="cres-policy-shared-1",
        source_document_id="paper-shared",
        source_result_id="res-policy-shared-1",
    )

    pd.DataFrame([shared_result.to_record()]).to_parquet(
        first_output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=first_collection_id,
                comparable_result=shared_result,
                sort_order=0,
            ).to_record()
        ]
    ).to_parquet(first_output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(first_collection_id, first_output_dir)

    pd.DataFrame([shared_result.to_record()]).to_parquet(
        second_output_dir / "comparable_results.parquet",
        index=False,
    )
    stale_overlay = _build_collection_overlay(
        collection_id=second_collection_id,
        comparable_result=shared_result,
        sort_order=7,
    ).to_record()
    stale_overlay["policy_version"] = "comparison_policy_v0"
    stale_overlay["assessment_input_fingerprint"] = "cafp_stale"
    pd.DataFrame([stale_overlay]).to_parquet(
        second_output_dir / "collection_comparable_results.parquet",
        index=False,
    )
    artifact_registry.upsert(second_collection_id, second_output_dir)

    payload = comparison_service.list_corpus_comparable_results(
        collection_id=second_collection_id,
    )

    assert payload["collection_id"] == second_collection_id
    assert payload["total"] == 1
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["comparable_result_id"] == "cres-policy-shared-1"
    assert item["observed_collection_ids"] == [second_collection_id]
    assert len(item["collection_overlays"]) == 1
    assert item["collection_overlays"][0]["collection_id"] == second_collection_id
    assert item["collection_overlays"][0]["policy_version"] == (
        COLLECTION_COMPARISON_POLICY_VERSION
    )
    assert item["collection_overlays"][0]["assessment_input_fingerprint"] != "cafp_stale"
    assert (second_output_dir / "comparison_rows.parquet").exists()


def test_comparison_service_reuses_corpus_manifest_cache_without_rescanning(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )

    collection = collection_service.create_collection("Corpus Cache Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparable_result = _build_test_comparable_result(
        comparable_result_id="cres-cache-1",
        source_document_id="paper-cache-1",
        source_result_id="res-cache-1",
    )
    pd.DataFrame([comparable_result.to_record()]).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=comparable_result,
                sort_order=0,
            ).to_record()
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    first_payload = comparison_service.list_corpus_comparable_results()

    cache_table_path, cache_meta_path = comparison_service._resolve_corpus_comparable_results_cache_paths()
    assert cache_table_path.exists()
    assert cache_meta_path.exists()

    def fail_scan(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("corpus cache should avoid rescanning collection outputs")

    monkeypatch.setattr(
        comparison_service,
        "_scan_corpus_comparable_result_items",
        fail_scan,
    )

    second_payload = comparison_service.list_corpus_comparable_results()

    assert second_payload == first_payload


def test_comparison_service_refreshes_corpus_manifest_cache_when_semantic_artifacts_change(
    monkeypatch,
    tmp_path,
):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry,
    )

    collection = collection_service.create_collection("Corpus Refresh Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    first_result = _build_test_comparable_result(
        comparable_result_id="cres-refresh-1",
        source_document_id="paper-refresh-1",
        source_result_id="res-refresh-1",
    )
    pd.DataFrame([first_result.to_record()]).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=first_result,
                sort_order=0,
            ).to_record()
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    first_payload = comparison_service.list_corpus_comparable_results()
    assert first_payload["total"] == 1

    second_result = _build_test_comparable_result(
        comparable_result_id="cres-refresh-2",
        source_document_id="paper-refresh-2",
        source_result_id="res-refresh-2",
        property_normalized="impact_strength",
        summary="Impact strength increased to 73 MPa.",
        numeric_value=73.0,
    )
    pd.DataFrame(
        [
            first_result.to_record(),
            second_result.to_record(),
        ]
    ).to_parquet(output_dir / "comparable_results.parquet", index=False)
    pd.DataFrame(
        [
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=first_result,
                sort_order=0,
            ).to_record(),
            _build_collection_overlay(
                collection_id=collection_id,
                comparable_result=second_result,
                sort_order=1,
            ).to_record(),
        ]
    ).to_parquet(output_dir / "collection_comparable_results.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    original_scan = comparison_service._scan_corpus_comparable_result_items
    scan_calls = 0

    def track_scan(*, collection_id=None):  # noqa: ANN001
        nonlocal scan_calls
        scan_calls += 1
        return original_scan(collection_id=collection_id)

    monkeypatch.setattr(
        comparison_service,
        "_scan_corpus_comparable_result_items",
        track_scan,
    )

    refreshed_payload = comparison_service.list_corpus_comparable_results()

    assert scan_calls == 1
    assert refreshed_payload["total"] == 2
    assert {
        item["comparable_result_id"]
        for item in refreshed_payload["items"]
    } == {"cres-refresh-1", "cres-refresh-2"}


def test_evidence_service_list_recovers_quote_span_as_string(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService
    from controllers.schemas.core.evidence import EvidenceCardListResponse

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Evidence Quote Span Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    cards = pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "The document reports process evidence.",
                "claim_type": "process",
                "evidence_source_type": "method",
                "evidence_anchors": json.dumps(
                    [
                        {
                            "anchor_id": "anchor-1",
                            "source_type": "method",
                            "section_id": "sec-1",
                            "block_id": None,
                            "snippet_id": "tu-1",
                            "figure_or_table": None,
                            "quote_span": "[31]",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "material_system": json.dumps(
                    {"family": "composite", "composition": None},
                    ensure_ascii=False,
                ),
                "condition_context": json.dumps(
                    {"process": {}, "baseline": {}, "test": {}},
                    ensure_ascii=False,
                ),
                "confidence": 0.8,
                "traceability_status": "direct",
            }
        ]
    )
    cards.to_parquet(output_dir / "evidence_cards.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = paper_facts_service.list_evidence_cards(collection_id)
    assert payload["items"][0]["evidence_anchors"][0]["quote_span"] == "[31]"

    response = EvidenceCardListResponse(**payload)
    assert response.items[0].evidence_anchors[0].quote_span == "[31]"


def test_document_content_and_traceback_ready_resolve_stable_section_ids(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Traceback Ready Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Traceback Ready Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    blocks = build_blocks(documents, text_units)
    methods_block = blocks[
        blocks["text_unit_ids"].apply(lambda value: "tu-1" in (value or []))
    ].iloc[0]

    pd.DataFrame(
        [
            {
                "evidence_id": "ev-ready",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "claim_type": "process",
                "evidence_source_type": "method",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor-ready",
                        "source_type": "method",
                        "section_id": methods_block["block_id"],
                        "block_id": methods_block["block_id"],
                        "snippet_id": "tu-1",
                        "quote_span": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                    }
                ],
                "material_system": {"family": "composite", "composition": None},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.8,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    content = document_profile_service.get_document_content(collection_id, "paper-1")
    matched_block = next(
        item for item in content["blocks"] if item["block_id"] == methods_block["block_id"]
    )
    assert matched_block["start_offset"] is not None

    traceback = paper_facts_service.get_evidence_traceback(collection_id, "ev-ready")
    assert traceback["traceback_status"] == "ready"
    assert traceback["anchors"][0]["locator_type"] == "char_range"
    assert traceback["anchors"][0]["char_range"] is not None
    assert traceback["anchors"][0]["block_id"] == methods_block["block_id"]
    assert "evidence_id=ev-ready" in traceback["anchors"][0]["deep_link"]


def test_evidence_traceback_partial_falls_back_to_section(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Traceback Partial Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Traceback Partial Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    _write_source_artifacts(output_dir, documents, text_units)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)
    blocks = build_blocks(documents, text_units)
    methods_block = blocks[
        blocks["text_unit_ids"].apply(lambda value: "tu-1" in (value or []))
    ].iloc[0]

    pd.DataFrame(
        [
            {
                "evidence_id": "ev-partial",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "The document reports a process route.",
                "claim_type": "process",
                "evidence_source_type": "method",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor-partial",
                        "source_type": "method",
                        "section_id": methods_block["block_id"],
                        "block_id": methods_block["block_id"],
                        "quote_span": "This quote is not present in the document.",
                    }
                ],
                "material_system": {"family": "composite", "composition": None},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.72,
                "traceability_status": "partial",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    traceback = paper_facts_service.get_evidence_traceback(collection_id, "ev-partial")
    assert traceback["traceback_status"] == "partial"
    assert traceback["anchors"][0]["locator_type"] == "section"
    assert traceback["anchors"][0]["block_id"] == methods_block["block_id"]
    assert traceback["anchors"][0]["char_range"] is None


def test_evidence_traceback_unavailable_when_no_locator_can_be_resolved(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    collection = collection_service.create_collection("Traceback Unavailable Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Traceback Unavailable Paper",
                "text": "A short note without section structure.",
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    _write_source_artifacts(output_dir, documents, None)
    artifact_registry.upsert(collection_id, output_dir)

    document_profile_service.build_document_profiles(collection_id, output_dir)

    pd.DataFrame(
        [
            {
                "evidence_id": "ev-unavailable",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "No usable anchor is available.",
                "claim_type": "property",
                "evidence_source_type": "figure",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor-unavailable",
                        "source_type": "figure",
                        "figure_or_table": "Figure 2",
                    }
                ],
                "material_system": {"family": "composite", "composition": None},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.51,
                "traceability_status": "missing",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    traceback = paper_facts_service.get_evidence_traceback(collection_id, "ev-unavailable")
    assert traceback["traceback_status"] == "unavailable"
    assert traceback["anchors"] == []
