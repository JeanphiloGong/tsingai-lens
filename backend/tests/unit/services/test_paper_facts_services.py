from __future__ import annotations

import numpy as np
import pandas as pd

from domain.core.comparison_assembly import (
    ComparableResultAssembler,
    ComparisonInputRecords,
)
from domain.core.comparison_projection import ComparisonRowProjector
from application.core.comparison_service import ComparisonService
from application.core.semantic_build.llm.prompts import (
    build_table_batch_mentions_prompt,
    build_text_window_extraction_prompt,
)
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.semantic_build.llm.schemas import (
    ExtractedTestConditionPayload,
    MeasurementResultPayload,
    MethodFactPayload,
    SampleVariantPayload,
    StructuredDocumentProfile,
    StructuredExtractionBundle,
    StructuredTableBatchMentions,
    StructuredTableBatchRowMentions,
    TableRowFactMentionPayload,
    TableRowResultClaimPayload,
    TableRowSubjectMentionPayload,
    StructuredTextWindowMentions,
    TextWindowMethodMentionPayload,
    TextWindowResultClaimPayload,
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
    PairwiseComparisonRelation,
    ResultValue,
    build_collection_assessment_input_fingerprint,
    evaluate_comparison_assessment,
)
from domain.core.evidence_backbone import (
    MeasurementResult,
    SampleVariant,
)
from domain.core.research_objective import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ResearchObjective,
)
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
    SqliteSourceArtifactRepository,
)


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


def _store_core_comparison_artifacts(
    comparison_service: ComparisonService,
    collection_id: str,
    comparable_results: list[ComparableResult],
    scoped_results: list[CollectionComparableResult],
) -> None:
    row_records = ComparisonRowProjector().project_rows_from_semantic_artifacts(
        collection_id=collection_id,
        comparable_results=comparable_results,
        scoped_results=scoped_results,
    )
    comparison_service.core_fact_repository.replace_collection_comparison_artifacts(
        collection_id,
        tuple(comparable_results),
        tuple(scoped_results),
        row_records,
    )


class EvidenceOnlyExtractor:
    def extract_document_profile(self, payload):  # noqa: ANN001
        return StructuredDocumentProfile(
            doc_type="experimental",
            parsing_warnings=[],
            confidence=0.9,
        )

    def extract_text_window_mentions(self, payload):  # noqa: ANN001
        text_window = payload.get("text_window") or {}
        quote = str(text_window.get("text") or "").strip() or "Process conditions were reported."
        return StructuredTextWindowMentions(
            method_mentions=[
                TextWindowMethodMentionPayload(
                    method_role="process",
                    method_name="sample preparation",
                    details=quote,
                    evidence_quote=quote,
                    confidence=0.7,
                )
            ]
        )

    def extract_table_batch_mentions(self, payload):  # noqa: ANN001, ARG002
        return StructuredTableBatchMentions()


class CountingEvidenceExtractor(EvidenceOnlyExtractor):
    def __init__(self) -> None:
        self.text_window_payloads: list[dict] = []
        self.table_batch_payloads: list[dict] = []

    def extract_text_window_mentions(self, payload):  # noqa: ANN001
        self.text_window_payloads.append(payload)
        return super().extract_text_window_mentions(payload)

    def extract_table_batch_mentions(self, payload):  # noqa: ANN001
        self.table_batch_payloads.append(payload)
        return StructuredTableBatchMentions()


def test_paper_facts_prompt_payloads_exclude_internal_ids():
    service = PaperFactsService()

    text_window_payload = service._build_text_window_extraction_payload(
        title="Prompt Boundary Paper",
        source_filename="prompt-boundary.pdf",
        profile={
            "doc_type": "experimental",
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
        "method_ref",
        "variant_ref",
        "test_condition_ref",
        "baseline_ref",
        "result_ref",
    ):
        assert f'"{field}"' not in text_window_prompt
    assert '"page"' in text_window_prompt
    assert "Use exactly the schema keys and no others." in text_window_prompt
    assert '"keywords"' in text_window_prompt
    assert '"evidence_quote"' in text_window_prompt
    assert '"claim_scope"' in text_window_prompt
    assert '"measurement_results"' not in text_window_prompt
    assert "If none fit exactly, use `other`." in text_window_prompt
    assert "If unsure, use `unclear`." in text_window_prompt

    table_batch_payload = service._build_table_batch_extraction_payload(
        title="Prompt Boundary Paper",
        source_filename="prompt-boundary.pdf",
        profile={
            "doc_type": "experimental",
        },
        table_context={
            "caption_text": "Table 1 Mechanical results.",
            "heading_path": "Results > Table 1",
            "column_headers": ["Sample", "Strength"],
            "table_matrix": [["Sample", "Strength"], ["A", "12 MPa"]],
            "table_markdown": "| Sample | Strength |\n| --- | --- |\n| A | 12 MPa |",
            "table_text": "Sample | Strength\nA | 12 MPa",
            "page": 5,
        },
        table_rows=[{
            "table_id": "tbl-1",
            "row_index": 2,
            "row_text": "Sample A | 12 MPa | as-built",
            "heading_path": "Results > Table 1",
        }],
        row_cells_by_index={
            2: [
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
        },
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
    _, table_batch_prompt = build_table_batch_mentions_prompt(table_batch_payload)
    for field in (
        "document_id",
        "window_id",
        "text_unit_ids",
        "block_ids",
        "table_id",
        "method_ref",
        "variant_ref",
        "test_condition_ref",
        "baseline_ref",
        "result_ref",
    ):
        assert f'"{field}"' not in table_batch_prompt
    assert '"page"' in table_batch_prompt
    assert '"table_context"' in table_batch_prompt
    assert '"table_markdown"' in table_batch_prompt
    assert "Use exactly the schema keys and no others." in table_batch_prompt
    assert '"keywords"' in table_batch_prompt
    assert '"row_subjects": [' in table_batch_prompt
    assert '"unit": "MPa"' in table_batch_prompt
    assert "Non-target rows are context only" in table_batch_prompt
    assert "Use `supporting_text_windows` only when they are required to interpret a row." in table_batch_prompt
    assert "Emit at most 2 `row_subjects`" in table_batch_prompt
    assert "Do not emit `confidence`, `epistemic_status`" in table_batch_prompt
    assert '"target_rows"' in table_batch_prompt
    assert '"row_results": [' in table_batch_prompt
    assert '"row_index": 2' in table_batch_prompt
    assert '"method_facts"' not in table_batch_prompt
    assert '"measurement_results"' in table_batch_prompt
    assert '"process_context": {' not in table_batch_prompt
    assert '"value_payload": {"value": 940}' in table_batch_prompt
    assert '"name": "laser_power_w"' in table_batch_prompt
    assert "strain_rate_s-1" in table_batch_prompt
    assert '"laser_power_w": null' not in table_batch_prompt
    assert '"strain_rate_s-1": null' not in table_batch_prompt
    assert '"result_claims": [' in table_batch_prompt


def test_paper_facts_payloads_include_sanitized_objective_context():
    service = PaperFactsService()
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-internal-1",
            "question": "How does scan speed affect LPBF 316L yield strength?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["scanning speed"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["yield strength"],
            "excluded_property_axes": ["relative density"],
            "routing_hints": [
                {
                    "table_id": "tbl-internal-1",
                    "document_id": "doc-internal-1",
                    "role": "result_table",
                    "strength": "strong",
                    "matched_property_axes": ["yield strength"],
                    "matched_variable_process_axes": ["scanning speed"],
                    "reason": "Table contains target property columns.",
                }
            ],
            "extraction_guidance": {
                "focus": "Extract mechanical current-work evidence.",
            },
            "confidence": 0.9,
        }
    )

    text_window_payload = service._build_text_window_extraction_payload(
        title="Objective Prompt Paper",
        source_filename="objective.pdf",
        profile={"doc_type": "experimental"},
        text_window={
            "heading": "Results",
            "heading_path": "Results",
            "text": "Yield strength increased with scanning speed.",
            "page": 4,
        },
        objective_context=objective_context,
    )

    assert text_window_payload["objective_context"] == {
        "focus": "How does scan speed affect LPBF 316L yield strength?",
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": ["scanning speed"],
        "process_context_axes": ["LPBF"],
        "target_property_axes": ["yield strength"],
        "excluded_property_axes": ["relative density"],
        "routing_hints": [],
        "extraction_guidance": {"focus": "Extract mechanical current-work evidence."},
        "confidence": 0.9,
    }
    _, text_window_prompt = build_text_window_extraction_prompt(text_window_payload)
    assert "Objective-context rules:" in text_window_prompt
    assert "objective_context.target_property_axes" in text_window_prompt
    assert '"objective_id"' not in text_window_prompt
    assert '"table_id"' not in text_window_prompt
    assert '"document_id"' not in text_window_prompt

    table_batch_payload = service._build_table_batch_extraction_payload(
        title="Objective Prompt Paper",
        source_filename="objective.pdf",
        profile={"doc_type": "experimental"},
        table_context={
            "caption_text": "Mechanical properties by scanning speed.",
            "column_headers": ["Sample", "Scanning speed", "Yield strength"],
            "table_matrix": [["Sample", "Scanning speed", "Yield strength"], ["A", "100", "560"]],
        },
        table_rows=[{
            "table_id": "tbl-internal-1",
            "row_index": 1,
            "row_text": "A | 100 | 560",
        }],
        row_cells_by_index={},
        text_windows=[],
        objective_context=objective_context,
        objective_table_route=objective_context.routing_hints[0],
    )

    table_objective_context = table_batch_payload["objective_context"]
    assert table_objective_context["routing_hints"] == [
        {
            "role": "result_table",
            "strength": "strong",
            "matched_property_axes": ["yield strength"],
            "matched_variable_process_axes": ["scanning speed"],
            "reason": "Table contains target property columns.",
        }
    ]
    _, table_batch_prompt = build_table_batch_mentions_prompt(table_batch_payload)
    assert "The active table route is `result_table`" in table_batch_prompt
    assert '"objective_id"' not in table_batch_prompt
    assert '"table_id"' not in table_batch_prompt
    assert '"document_id"' not in table_batch_prompt


def test_paper_facts_selects_objective_context_by_text_and_table_route():
    service = PaperFactsService()
    structural_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-structural",
            "question": "How do SLM parameters affect densification?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["energy density", "scanning speed"],
            "process_context_axes": ["Selective Laser Melting"],
            "target_property_axes": ["relative density"],
            "excluded_property_axes": ["yield strength"],
            "routing_hints": [
                {
                    "table_id": "table-1",
                    "document_id": "paper-1",
                    "role": "result_table",
                    "strength": "strong",
                    "matched_property_axes": ["relative density"],
                    "matched_variable_process_axes": ["energy density"],
                }
            ],
            "extraction_guidance": {},
        }
    )
    mechanical_context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "question": "How do SLM parameters affect mechanical properties?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["energy density", "scanning speed"],
            "process_context_axes": ["Selective Laser Melting"],
            "target_property_axes": ["yield strength", "ultimate tensile strength"],
            "excluded_property_axes": ["relative density"],
            "routing_hints": [
                {
                    "table_id": "table-1",
                    "document_id": "paper-1",
                    "role": "condition_context",
                    "strength": "strong",
                    "matched_variable_process_axes": ["energy density"],
                },
                {
                    "table_id": "table-2",
                    "document_id": "paper-1",
                    "role": "result_table",
                    "strength": "strong",
                    "matched_property_axes": [
                        "yield strength",
                        "ultimate tensile strength",
                    ],
                },
            ],
            "extraction_guidance": {},
        }
    )
    contexts = (structural_context, mechanical_context)

    selected_text_context = service._select_text_window_objective_context(
        contexts,
        text_window={
            "heading": "Mechanical properties",
            "heading_path": "Results > Mechanical properties",
            "text": "Yield strength and ultimate tensile strength increased.",
        },
    )
    assert selected_text_context == mechanical_context

    table_1_context, table_1_route = service._select_table_batch_objective_context(
        contexts,
        document_id="paper-1",
        table_id="table-1",
        table_context={"caption_text": "Processing parameters and relative density."},
        table_rows=[{"row_index": 1, "row_text": "A | 70 | 99.2"}],
        row_cells_by_index={},
    )
    assert table_1_context == structural_context
    assert table_1_route is not None
    assert table_1_route["role"] == "result_table"

    table_2_context, table_2_route = service._select_table_batch_objective_context(
        contexts,
        document_id="paper-1",
        table_id="table-2",
        table_context={"caption_text": "Mechanical properties."},
        table_rows=[{"row_index": 1, "row_text": "A | 560 | 690"}],
        row_cells_by_index={},
    )
    assert table_2_context == mechanical_context
    assert table_2_route is not None
    assert table_2_route["role"] == "result_table"


def test_paper_facts_build_uses_objective_routes_to_gate_legacy_extraction(
    tmp_path,
    caplog,
):
    from application.core.semantic_build.document_profile_service import (
        DocumentProfileService,
    )
    from application.source.collection_service import CollectionService
    from domain.source import SourceArtifactSet

    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Route Gated Facts")
    collection_id = collection["collection_id"]
    core_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    extractor = CountingEvidenceExtractor()
    document_profile_service = DocumentProfileService(
        collection_service=collection_service,
        structured_extractor=extractor,
        core_fact_repository=core_repository,
        source_artifact_repository=source_repository,
    )
    service = PaperFactsService(
        collection_service=collection_service,
        document_profile_service=document_profile_service,
        structured_extractor=extractor,
        core_fact_repository=core_repository,
        source_artifact_repository=source_repository,
    )
    source_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "LPBF 316L Route Gated Paper",
                    "text": "Allowed process text. Excluded composition text.",
                }
            ],
            text_units=[
                {
                    "id": "tu-1",
                    "text": "Allowed process text.",
                    "document_ids": ["paper-1"],
                },
                {
                    "id": "tu-2",
                    "text": "Excluded composition text.",
                    "document_ids": ["paper-1"],
                },
            ],
            blocks=[
                {
                    "block_id": "block-allowed",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "Allowed process text reports LPBF scan speed.",
                    "block_order": 1,
                    "heading_path": "Results",
                    "text_unit_ids": ["tu-1"],
                },
                {
                    "block_id": "block-excluded",
                    "document_id": "paper-1",
                    "block_type": "paragraph",
                    "text": "Excluded composition text reports Fe Cr Ni only.",
                    "block_order": 2,
                    "heading_path": "Composition",
                    "text_unit_ids": ["tu-2"],
                },
            ],
            tables=[
                {
                    "table_id": "table-allowed",
                    "document_id": "paper-1",
                    "table_order": 1,
                    "caption_text": "Allowed tensile results",
                    "heading_path": "Results",
                    "column_headers": ["Sample", "Yield strength"],
                    "table_matrix": [
                        ["Sample", "Yield strength"],
                        ["Sample A", "560 MPa"],
                    ],
                },
                {
                    "table_id": "table-excluded",
                    "document_id": "paper-1",
                    "table_order": 2,
                    "caption_text": "Excluded chemical composition",
                    "heading_path": "Composition",
                    "column_headers": ["Fe", "Cr", "Ni"],
                    "table_matrix": [
                        ["Fe", "Cr", "Ni"],
                        ["balance", "17", "12"],
                    ],
                },
            ],
            table_rows=[
                {
                    "row_id": "row-allowed-1",
                    "document_id": "paper-1",
                    "table_id": "table-allowed",
                    "row_index": 1,
                    "row_text": "Sample A | 560 MPa",
                    "heading_path": "Results",
                },
                {
                    "row_id": "row-excluded-1",
                    "document_id": "paper-1",
                    "table_id": "table-excluded",
                    "row_index": 1,
                    "row_text": "balance | 17 | 12",
                    "heading_path": "Composition",
                },
            ],
            table_cells=[
                {
                    "cell_id": "cell-allowed-1",
                    "document_id": "paper-1",
                    "table_id": "table-allowed",
                    "row_index": 1,
                    "col_index": 1,
                    "header_path": "Sample",
                    "cell_text": "Sample A",
                },
                {
                    "cell_id": "cell-allowed-2",
                    "document_id": "paper-1",
                    "table_id": "table-allowed",
                    "row_index": 1,
                    "col_index": 2,
                    "header_path": "Yield strength",
                    "cell_text": "560",
                    "unit_hint": "MPa",
                },
                {
                    "cell_id": "cell-excluded-1",
                    "document_id": "paper-1",
                    "table_id": "table-excluded",
                    "row_index": 1,
                    "col_index": 1,
                    "header_path": "Fe",
                    "cell_text": "balance",
                },
                {
                    "cell_id": "cell-excluded-2",
                    "document_id": "paper-1",
                    "table_id": "table-excluded",
                    "row_index": 1,
                    "col_index": 2,
                    "header_path": "Cr",
                    "cell_text": "17",
                    "unit_hint": "wt%",
                },
            ],
        ),
    )

    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "question": "How does scan speed affect LPBF 316L yield strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan speed"],
            "property_axes": ["yield strength"],
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["scan speed"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["yield strength"],
        }
    )
    existing_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-existing",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield_strength",
            "value_payload": {"value": 560},
            "resolution_status": "resolved",
        }
    )
    existing_chain = ObjectiveLogicChain.from_mapping(
        {
            "logic_chain_id": "olc-existing",
            "objective_id": objective.objective_id,
            "chain_scope": "objective",
            "evidence_unit_ids": [existing_unit.evidence_unit_id],
            "chain_payload": {"schema_version": "objective_logic_chain.v1"},
        }
    )
    core_repository.replace_collection_research_objectives(
        collection_id,
        (),
        (objective,),
        (objective_context,),
        (),
        (
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "block-allowed",
                    "role": "current_experimental_evidence",
                    "extractable": True,
                }
            ),
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "block-excluded",
                    "role": "low_value_or_irrelevant",
                    "extractable": False,
                }
            ),
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "table-allowed",
                    "role": "current_experimental_evidence",
                    "extractable": True,
                }
            ),
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "table-excluded",
                    "role": "low_value_or_irrelevant",
                    "extractable": False,
                }
            ),
        ),
        (existing_unit,),
        (existing_chain,),
    )

    with caplog.at_level("INFO"):
        service.build_paper_facts(collection_id)

    assert len(extractor.text_window_payloads) == 1
    assert extractor.text_window_payloads[0]["text_window"]["text"].startswith(
        "Allowed process text"
    )
    assert len(extractor.table_batch_payloads) == 1
    target_rows = extractor.table_batch_payloads[0]["target_rows"]
    assert len(target_rows) == 1
    assert target_rows[0]["row_summary"] == "Sample A | 560 MPa"
    assert all("balance" not in row["row_summary"] for row in target_rows)

    facts = core_repository.read_collection_facts(collection_id)
    assert facts.objective_evidence_units == (existing_unit,)
    assert facts.objective_logic_chains == (existing_chain,)
    assert any(
        "Paper facts objective route gate loaded" in record.message
        and "text_window_routes=1" in record.message
        and "table_routes=1" in record.message
        for record in caplog.records
    )
    assert any(
        "Paper facts extraction started" in record.message
        and "total_extraction_units=2" in record.message
        for record in caplog.records
    )

    extractor.text_window_payloads.clear()
    extractor.table_batch_payloads.clear()
    caplog.clear()
    core_repository.replace_collection_research_objectives(
        collection_id,
        (),
        (objective,),
        (objective_context,),
        (),
        (
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "table-allowed",
                    "role": "current_experimental_evidence",
                    "extractable": True,
                }
            ),
        ),
        (existing_unit,),
        (existing_chain,),
    )

    with caplog.at_level("INFO"):
        service.build_paper_facts(collection_id)

    assert extractor.text_window_payloads == []
    assert len(extractor.table_batch_payloads) == 1
    assert any(
        "Paper facts objective route gate loaded" in record.message
        and "text_window_routes=0" in record.message
        and "table_routes=1" in record.message
        for record in caplog.records
    )
    assert any(
        "Paper facts extraction started" in record.message
        and "total_extraction_units=1" in record.message
        for record in caplog.records
    )


def test_evidence_cards_use_objective_units_without_paper_facts(tmp_path):
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Evidence Cards")
    collection_id = collection["collection_id"]
    core_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    service = PaperFactsService(
        collection_service=collection_service,
        core_fact_repository=core_repository,
    )
    unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-as-built-icorr",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "as-built"},
            "process_context": {"process": "LPBF"},
            "test_condition": {"method": "potentiodynamic polarization"},
            "property_normalized": "corrosion current density",
            "value_payload": {"value": 1.2, "source_value_text": "1.2 uA/cm2"},
            "unit": "uA/cm2",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 4,
                }
            ],
            "evidence_anchor_ids": ["anc-as-built"],
            "resolution_status": "resolved",
            "confidence": 0.88,
        }
    )
    core_repository.replace_collection_research_objectives(
        collection_id,
        (),
        (),
        (),
        (),
        (),
        (unit,),
        (),
    )

    def fail_build_paper_facts(collection_id: str):  # noqa: ARG001
        raise AssertionError("objective evidence cards should not build paper facts")

    service.build_paper_facts = fail_build_paper_facts

    cards = service.build_evidence_cards(collection_id)
    payload = service.list_evidence_cards(collection_id)

    assert len(cards) == 1
    assert payload["total"] == 1
    card = payload["items"][0]
    assert card["evidence_id"] == "ev_objective_oeu-as-built-icorr"
    assert card["claim_type"] == "property"
    assert card["claim_text"] == (
        "as-built reported corrosion current density of 1.2 uA/cm2."
    )
    assert card["evidence_source_type"] == "table"
    assert card["traceability_status"] == "direct"
    assert card["material_system"]["family"] == "316L stainless steel"
    assert card["evidence_anchors"][0]["anchor_id"] == "anc-as-built"
    assert card["evidence_anchors"][0]["figure_or_table"] == "table-1"


def test_document_method_family_conditions_bind_table_results():
    service = PaperFactsService()
    text_windows = [
        {
            "window_id": "win-tensile",
            "heading": "Mechanical testing",
            "heading_path": "Experimental > Mechanical testing",
            "text": (
                "Tensile tests followed ASTM E8M on an INSTRON mechanical "
                "testing machine at a strain rate of 0.02 mm/min with all "
                "blocks built horizontally on substrate."
            ),
            "block_ids": ["blk-tensile"],
            "page": 2,
        },
        {
            "window_id": "win-hardness",
            "heading": "Microhardness",
            "heading_path": "Experimental > Microhardness",
            "text": (
                "Vickers microhardness was measured using a Wilson tester "
                "under a 10 N load and 15 s holding time with 20 readings "
                "per sample."
            ),
            "block_ids": ["blk-hardness"],
            "page": 3,
        },
        {
            "window_id": "win-sem",
            "heading": "SEM characterization",
            "heading_path": "Experimental > SEM characterization",
            "text": (
                "Horizontal and vertical sections were polished with 400-1200 "
                "grit papers and colloidal silica for SEM and ImageJ relative "
                "density and porosity analysis at 100x-10000x magnification."
            ),
            "block_ids": ["blk-sem"],
            "page": 4,
        },
    ]
    evidence_anchor_rows: list[dict[str, object]] = []
    test_condition_rows: list[dict[str, object]] = []
    document_state = service._build_document_state()

    service._materialize_document_method_family_test_conditions(
        collection_id="col-1",
        document_id="doc-1",
        text_windows=text_windows,
        evidence_anchor_rows=evidence_anchor_rows,
        test_condition_rows=test_condition_rows,
        document_state=document_state,
    )

    test_conditions = service._normalize_test_condition_records(
        test_condition_rows,
        "col-1",
    )
    assert {row["property_type"] for row in test_conditions} == {
        "tensile_mechanics",
        "microhardness",
        "density_porosity_microstructure",
    }
    test_condition_by_type = {
        row["property_type"]: row
        for row in test_conditions
    }
    tensile_payload = test_condition_by_type["tensile_mechanics"]["condition_payload"]
    assert tensile_payload["standard"] == "ASTM E8M"
    assert tensile_payload["strain_rate_s-1"] == "0.02 mm/min"

    measurement_results = service._attach_document_test_condition_ids_to_measurements(
        measurement_results=(
            {
                "result_id": "res-yield",
                "document_id": "doc-1",
                "collection_id": "col-1",
                "variant_id": "var-1",
                "property_normalized": "yield_strength",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {"value": 560},
                "unit": "MPa",
                "result_source_type": "table",
            },
            {
                "result_id": "res-hardness",
                "document_id": "doc-1",
                "collection_id": "col-1",
                "variant_id": "var-1",
                "property_normalized": "hardness",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {"value": 215},
                "unit": "HV",
                "result_source_type": "table",
            },
            {
                "result_id": "res-density",
                "document_id": "doc-1",
                "collection_id": "col-1",
                "variant_id": "var-1",
                "property_normalized": "density",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {"value": 99.4},
                "unit": "%",
                "result_source_type": "table",
            },
        ),
        test_conditions=test_conditions,
    )

    condition_ids_by_property = {
        row["property_normalized"]: row["test_condition_id"]
        for row in measurement_results
    }
    assert condition_ids_by_property["yield_strength"] == test_condition_by_type[
        "tensile_mechanics"
    ][
        "test_condition_id"
    ]
    assert condition_ids_by_property["hardness"] == test_condition_by_type[
        "microhardness"
    ][
        "test_condition_id"
    ]
    assert condition_ids_by_property["density"] == test_condition_by_type[
        "density_porosity_microstructure"
    ][
        "test_condition_id"
    ]


def test_characterization_observations_include_table_derived_pbf_context():
    service = PaperFactsService()
    sample_variants = (
        {
            "variant_id": "var-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "variant_label": "1",
            "process_context": {"scan_strategy": "A"},
        },
        {
            "variant_id": "var-2",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "variant_label": "2",
            "process_context": {"scan_strategy": "B"},
        },
    )
    measurement_results = (
        {
            "result_id": "res-1",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "variant_id": "var-1",
            "property_normalized": "density",
            "result_type": "scalar",
            "value_payload": {"value": 95.4},
            "unit": "%",
            "result_source_type": "table",
            "evidence_anchor_ids": ["anc-1"],
        },
        {
            "result_id": "res-2",
            "document_id": "doc-1",
            "collection_id": "col-1",
            "variant_id": "var-2",
            "property_normalized": "density",
            "result_type": "scalar",
            "value_payload": {"value": 97.7},
            "unit": "%",
            "result_source_type": "table",
            "evidence_anchor_ids": ["anc-2"],
        },
    )

    observations = service._build_characterization_observations(
        collection_id="col-1",
        method_facts=(),
        evidence_anchors=(
            {"anchor_id": "anc-1", "document_id": "doc-1"},
            {"anchor_id": "anc-2", "document_id": "doc-1"},
        ),
        text_windows_by_doc={
            "doc-1": [
                {
                    "window_id": "win-1",
                    "block_ids": ["blk-1"],
                    "text": (
                        "Horizontal and vertical SEM sections were examined. "
                        "The dendrite width increased as scan speed decreased. "
                        "Low energy input caused pores, while overheating led to balling."
                    ),
                }
            ]
        },
        sample_variants=sample_variants,
        measurement_results=measurement_results,
    )

    observation_types = {row["characterization_type"] for row in observations}
    assert "density_porosity_sem_imagej" in observation_types
    assert "highest_density_sample" in observation_types
    assert "scan_strategy_a" in observation_types
    assert "scan_strategy_b" in observation_types
    highest_density = next(
        row
        for row in observations
        if row["characterization_type"] == "highest_density_sample"
    )
    assert highest_density["variant_id"] == "var-2"


def test_table_row_process_context_uses_cell_header_bindings():
    service = PaperFactsService()

    context = service._build_table_row_process_context(
        [],
        row_cells=[
            {"col_index": 1, "header_path": "Sample number", "cell_text": "5"},
            {"col_index": 2, "header_path": "Hatch space (mm)", "cell_text": "0.111"},
            {"col_index": 3, "header_path": "Scan strategy", "cell_text": "A"},
            {"col_index": 4, "header_path": "Scanning speed (mm/s)", "cell_text": "0.12"},
            {"col_index": 5, "header_path": "Energy density (J/mm 3 )", "cell_text": "150"},
        ],
    )

    assert context.hatch_spacing_um == 111.0
    assert context.scan_strategy == "A"
    assert context.scan_speed_mm_s == 0.12
    assert context.energy_density_j_mm3 == 150.0


def test_table_row_process_context_keeps_p001_process_columns_separate():
    service = PaperFactsService()

    context = service._build_table_row_process_context(
        [],
        row_cells=[
            {"col_index": 1, "header_path": "Sample number", "cell_text": "9"},
            {"col_index": 2, "header_path": "Hatch space (mm)", "cell_text": "0.12"},
            {"col_index": 3, "header_path": "Scan strategy", "cell_text": "B"},
            {"col_index": 4, "header_path": "Scanning speed (mm/s)", "cell_text": "0.239"},
            {"col_index": 5, "header_path": "Energy density (J/mm 3 )", "cell_text": "70"},
        ],
    )

    assert context.hatch_spacing_um == 120.0
    assert context.scan_strategy == "B"
    assert context.scan_speed_mm_s == 0.239
    assert context.energy_density_j_mm3 == 70.0


def test_text_window_test_conditions_skip_empty_payload():
    service = PaperFactsService()
    text_window = {
        "text": "Yield strength reached 560 MPa.",
        "window_id": "window-1",
    }
    claim = TextWindowResultClaimPayload(
        claim_text="Yield strength reached 560 MPa.",
        property_normalized="yield_strength",
        result_type="scalar",
        value_text="560",
        unit="MPa",
        claim_scope="current_work",
        eligible_for_measurement_result=True,
        evidence_quote="Yield strength reached 560 MPa.",
    )

    conditions = service._build_text_window_test_conditions(
        StructuredTextWindowMentions(result_claims=[claim]),
        text_window,
        [claim],
    )

    assert conditions == []


def test_generic_text_samples_are_removed_when_table_samples_exist():
    service = PaperFactsService()
    samples = service._normalize_sample_variant_records(
        [
            {
                "variant_id": "var-generic",
                "document_id": "paper-1",
                "collection_id": "collection-1",
                "variant_label": "316L stainless steel samples",
                "host_material_system": {},
                "composition": None,
                "variable_axis_type": None,
                "variable_value": None,
                "process_context": {},
                "profile_payload": {"source_kind": "text_window"},
                "structure_feature_ids": [],
                "source_anchor_ids": [],
                "confidence": 0.8,
                "epistemic_status": "inferred_with_low_confidence",
            },
            {
                "variant_id": "var-1",
                "document_id": "paper-1",
                "collection_id": "collection-1",
                "variant_label": "1",
                "host_material_system": {},
                "composition": None,
                "variable_axis_type": None,
                "variable_value": None,
                "process_context": {},
                "profile_payload": {"source_kind": "table_row"},
                "structure_feature_ids": [],
                "source_anchor_ids": [],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            },
        ],
        None,
    )
    filtered, removed_ids = service._filter_generic_text_sample_variants(samples)

    assert {row["variant_label"] for row in filtered} == {"1"}
    assert removed_ids == {"var-generic"}

    measurements = service._normalize_measurement_result_records(
        [
            {
                "result_id": "res-1",
                "document_id": "paper-1",
                "collection_id": "collection-1",
                "variant_id": "var-generic",
                "property_normalized": "density",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {"value": 95.0, "statement": "Relative density was 95%."},
                "unit": "%",
                "evidence_anchor_ids": ["anchor-1"],
                "traceability_status": "direct",
                "result_source_type": "text",
            }
        ],
        None,
    )
    cleared = service._clear_removed_variant_ids_from_measurements(
        measurements,
        removed_ids,
    )

    assert cleared[0]["variant_id"] is None


def test_measurement_results_dedupe_merges_duplicate_scalars_and_drops_statistics():
    service = PaperFactsService()
    measurements = service._normalize_measurement_result_records(
        [
            {
                "result_id": "res-1",
                "document_id": "paper-1",
                "collection_id": "collection-1",
                "variant_id": "var-1",
                "property_normalized": "hardness",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {"value": 187.7, "statement": "Microhardness is 187.7 HV."},
                "unit": None,
                "evidence_anchor_ids": ["anchor-1"],
                "traceability_status": "direct",
                "result_source_type": "table",
            },
            {
                "result_id": "res-2",
                "document_id": "paper-1",
                "collection_id": "collection-1",
                "variant_id": "var-1",
                "property_normalized": "hardness",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {"value": 187.7, "statement": "Microhardness measured at 187.7."},
                "unit": "HV",
                "evidence_anchor_ids": ["anchor-2"],
                "traceability_status": "direct",
                "result_source_type": "table",
            },
            {
                "result_id": "res-std",
                "document_id": "paper-1",
                "collection_id": "collection-1",
                "variant_id": "var-1",
                "property_normalized": "hardness",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {
                    "value": 11.4,
                    "statement": "Standard deviation of microhardness is 11.4 HV.",
                },
                "unit": "HV",
                "evidence_anchor_ids": ["anchor-std"],
                "traceability_status": "direct",
                "result_source_type": "table",
            },
        ],
        None,
    )

    deduped = service._deduplicate_measurement_result_records(measurements)

    assert len(deduped) == 1
    assert deduped[0]["unit"] == "HV"
    assert set(deduped[0]["evidence_anchor_ids"]) == {"anchor-1", "anchor-2"}


def test_pbf_fact_schema_accepts_process_test_and_value_provenance_fields():
    bundle = StructuredExtractionBundle(
        method_facts=[
            MethodFactPayload(
                method_role="process",
                method_name="LPBF",
                method_payload={
                    "laser_power_w": 280,
                    "scan_speed_mm_s": 1200,
                    "layer_thickness_um": 30,
                    "hatch_spacing_um": 100,
                    "energy_density_j_mm3": 78,
                    "energy_density_origin": "reported",
                    "build_orientation": "vertical",
                    "post_treatment_summary": "HIP",
                },
            )
        ],
        sample_variants=[
            SampleVariantPayload(
                variant_label="S3",
                host_material_system={
                    "family": "titanium alloy",
                    "composition": "Ti-6Al-4V",
                },
                composition="Ti-6Al-4V",
                variable_axis_type="post_treatment",
                variable_value="optimized VED + HIP",
                process_context={
                    "laser_power_w": 280,
                    "scan_speed_mm_s": 1200,
                    "layer_thickness_um": 30,
                    "hatch_spacing_um": 100,
                    "energy_density_j_mm3": 78,
                    "energy_density_origin": "reported",
                    "build_orientation": "vertical",
                    "post_treatment_summary": "HIP",
                },
            )
        ],
        test_conditions=[
            ExtractedTestConditionPayload(
                property_type="yield_strength",
                condition_payload={
                    "test_method": "tensile",
                    "test_temperature_c": 25,
                    "strain_rate_s-1": 0.001,
                    "loading_direction": "vertical",
                    "sample_orientation": "vertical",
                },
            )
        ],
        measurement_results=[
            MeasurementResultPayload(
                claim_text="S3 showed a yield strength of 940 MPa.",
                property_normalized="yield_strength",
                result_type="scalar",
                value_payload={
                    "value": 940,
                    "value_origin": "reported",
                    "source_value_text": "940",
                    "source_unit_text": "MPa",
                },
                unit="MPa",
                variant_label="S3",
                baseline_label="S2",
            )
        ],
    )

    assert bundle.method_facts[0].method_payload.laser_power_w == 280
    assert bundle.sample_variants[0].process_context.energy_density_origin == "reported"
    assert bundle.test_conditions[0].condition_payload.strain_rate_s_1 == 0.001
    assert bundle.measurement_results[0].value_payload.source_value_text == "940"


def test_paper_facts_service_reads_extraction_concurrency_from_env(monkeypatch):
    monkeypatch.setenv("CORE_EXTRACTION_MAX_CONCURRENCY", "8")

    service = PaperFactsService()

    assert service._get_max_extraction_concurrency() == 8


def test_paper_facts_service_falls_back_to_default_concurrency_for_invalid_env(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("CORE_EXTRACTION_MAX_CONCURRENCY", "invalid")

    service = PaperFactsService()

    with caplog.at_level("WARNING"):
        assert service._get_max_extraction_concurrency() == 4

    assert any(
        "Invalid CORE_EXTRACTION_MAX_CONCURRENCY=" in record.message
        for record in caplog.records
    )


def test_table_batch_payload_truncates_supporting_window_text():
    service = PaperFactsService()

    payload = service._build_table_batch_extraction_payload(
        title="Prompt Boundary Paper",
        source_filename="prompt-boundary.pdf",
        profile={
            "doc_type": "experimental",
        },
        table_context=None,
        table_rows=[{
            "table_id": "tbl-1",
            "row_index": 2,
            "row_text": "Sample A | 12 MPa | as-built",
            "heading_path": "Results > Table 1",
        }],
        row_cells_by_index={
            2: [
                {
                    "header_path": "Sample",
                    "cell_text": "A",
                    "unit_hint": None,
                    "col_index": 0,
                }
            ],
        },
        text_windows=[
            {
                "window_id": "win-2",
                "heading": "Results",
                "heading_path": "Results > Table 1",
                "text": "x" * 2000,
                "text_unit_ids": ["tu-2"],
                "block_ids": ["blk-2"],
                "page": 5,
            }
        ],
    )

    assert len(payload["supporting_text_windows"]) == 1
    assert len(payload["supporting_text_windows"][0]["text"]) == 1200


def test_table_batch_payload_includes_source_table_context():
    service = PaperFactsService()

    payload = service._build_table_batch_extraction_payload(
        title="Prompt Boundary Paper",
        source_filename="prompt-boundary.pdf",
        profile={
            "doc_type": "experimental",
        },
        table_context={
            "caption_text": "Table 1 Mechanical properties.",
            "heading_path": "Results > Mechanical Properties",
            "column_headers": ["Sample", "Yield strength (MPa)", "Baseline"],
            "table_matrix": [
                ["Sample", "Yield strength (MPa)", "Baseline"],
                ["A", "560", "as-built"],
            ],
            "table_markdown": "| Sample | Yield strength (MPa) | Baseline |\n| --- | --- | --- |\n| A | 560 | as-built |",
            "table_text": "Sample | Yield strength (MPa) | Baseline\nA | 560 | as-built",
            "page": 5,
        },
        table_rows=[{
            "table_id": "tbl-1",
            "row_index": 1,
            "row_text": "A | 560 | as-built",
            "heading_path": "Results > Mechanical Properties",
            "page": 5,
        }],
        row_cells_by_index={
            1: [
                {
                    "header_path": "Sample",
                    "cell_text": "A",
                    "unit_hint": None,
                    "col_index": 0,
                },
                {
                    "header_path": "Yield strength (MPa)",
                    "cell_text": "560",
                    "unit_hint": "MPa",
                    "col_index": 1,
                },
            ],
        },
        text_windows=[],
    )

    assert payload["table_context"] == {
        "caption_text": "Table 1 Mechanical properties.",
        "heading_path": "Results > Mechanical Properties",
        "column_headers": ["Sample", "Yield strength (MPa)", "Baseline"],
        "table_matrix": [
            ["Sample", "Yield strength (MPa)", "Baseline"],
            ["A", "560", "as-built"],
        ],
        "table_markdown": "| Sample | Yield strength (MPa) | Baseline |\n| --- | --- | --- |\n| A | 560 | as-built |",
        "table_text": "Sample | Yield strength (MPa) | Baseline\nA | 560 | as-built",
        "page": 5,
    }
    assert payload["target_rows"][0]["row_summary"] == "A | 560 | as-built"
    assert payload["target_rows"][0]["row_index"] == 1


def test_table_batching_keeps_small_tables_whole_and_chunks_large_tables():
    service = PaperFactsService()

    small_rows = [
        {"table_id": "tbl-small", "row_index": index, "row_text": f"A{index} | {index}"}
        for index in range(1, 7)
    ]
    large_rows = [
        {"table_id": "tbl-large", "row_index": index, "row_text": f"B{index} | {index}"}
        for index in range(1, 42)
    ]

    batches = service._batch_table_rows_for_extraction([*small_rows, *large_rows])

    assert [len(batch) for batch in batches] == [
        6,
        5,
        5,
        5,
        5,
        5,
        5,
        5,
        5,
        1,
    ]


def test_table_batch_payload_bounds_large_table_matrix_to_target_rows():
    service = PaperFactsService()
    matrix = [["Sample", "Strength"]]
    matrix.extend([[f"A{index}", str(index)] for index in range(1, 50)])

    payload = service._build_table_batch_extraction_payload(
        title="Large Table Paper",
        source_filename="large-table.pdf",
        profile={
            "doc_type": "experimental",
        },
        table_context={
            "caption_text": "Table 1 Large result table.",
            "heading_path": "Results",
            "column_headers": ["Sample", "Strength"],
            "table_matrix": matrix,
            "table_markdown": "| Sample | Strength |",
            "table_text": "Sample | Strength",
            "page": 3,
        },
        table_rows=[
            {
                "table_id": "tbl-large",
                "row_index": 24,
                "row_text": "A24 | 24",
                "heading_path": "Results",
                "page": 3,
            }
        ],
        row_cells_by_index={},
        text_windows=[],
    )

    bounded_matrix = payload["table_context"]["table_matrix"]
    assert ["A24", "24"] in bounded_matrix
    assert ["A23", "23"] in bounded_matrix
    assert ["A25", "25"] in bounded_matrix
    assert ["A49", "49"] in bounded_matrix
    assert ["A10", "10"] not in bounded_matrix


def test_table_row_binding_repairs_split_lpbf_variant_labels():
    service = PaperFactsService()
    row_cells = [
        {
            "header_path": None,
            "cell_text": "100) HT-SLM (100/",
            "unit_hint": None,
            "col_index": 0,
        },
        {
            "header_path": "Type of heat treatment",
            "cell_text": "Furnace HT",
            "unit_hint": None,
            "col_index": 1,
        },
        {
            "header_path": "Laser power (W)",
            "cell_text": "100",
            "unit_hint": None,
            "col_index": 2,
        },
        {
            "header_path": "Scan speed (mm/s)",
            "cell_text": "100",
            "unit_hint": None,
            "col_index": 3,
        },
        {
            "header_path": "Density (%)",
            "cell_text": "98.70",
            "unit_hint": "%",
            "col_index": 4,
        },
    ]

    bundle = service._bind_table_row_mentions_to_bundle(
        mentions=StructuredTableBatchRowMentions(
            row_index=2,
            row_subjects=[
                TableRowSubjectMentionPayload(
                    variant_label="100) HT-SLM (100/",
                    family="316L stainless steel",
                )
            ],
            process_mentions=[
                TableRowFactMentionPayload(
                    name="post_treatment_summary",
                    value_text="Furnace HT",
                )
            ],
            result_claims=[
                TableRowResultClaimPayload(
                    property_normalized="density",
                    value_text="98.70",
                    unit="%",
                    variant_label="100) HT-SLM (100/",
                    quote="100) HT-SLM (100/ | Furnace HT | 100 | 100 | 98.70",
                )
            ],
        ),
        table_row={
            "table_id": "tbl-1",
            "row_index": 2,
            "row_text": "100) HT-SLM (100/ | Furnace HT | 100 | 100 | 98.70",
            "page": 3,
        },
        row_cells=row_cells,
        table_context=None,
    )

    assert bundle.sample_variants[0].variant_label == "HT-SLM (100/100)"
    assert bundle.measurement_results[0].variant_label == "HT-SLM (100/100)"
    assert "HT-SLM (100/100)" in bundle.measurement_results[0].claim_text


def test_evidence_service_normalizes_array_backed_condition_contexts(tmp_path):
    from application.source.collection_service import CollectionService
    from application.core.semantic_build.document_profile_service import DocumentProfileService
    from application.core.semantic_build.paper_facts_service import PaperFactsService

    collection_service = CollectionService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service)
    paper_facts_service = PaperFactsService(
        collection_service=collection_service,
        document_profile_service=document_profile_service,
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


def test_pbf_comparison_assembly_uses_process_test_and_value_context():
    assembler = ComparableResultAssembler()
    result_row = pd.Series(
        {
            "result_id": "res-s3-25",
            "document_id": "paper-1",
            "variant_id": "var-s3",
            "property_normalized": "yield_strength",
            "result_type": "scalar",
            "value_payload": {
                "value": 940.0,
                "statement": "S3 showed a yield strength of 940 MPa at 25 C.",
                "value_origin": "reported",
                "source_value_text": "940",
                "source_unit_text": "MPa",
            },
            "unit": "MPa",
            "test_condition_id": "tc-25",
            "baseline_id": "base-s2",
            "structure_feature_ids": ["sf-porosity"],
            "characterization_observation_ids": [],
            "evidence_anchor_ids": ["anchor-s3-25"],
            "traceability_status": "direct",
            "result_source_type": "table",
            "claim_scope": "current_work",
        }
    )
    sample_lookup = {
        "var-s3": {
            "variant_id": "var-s3",
            "domain_profile": "pbf_metal",
            "variant_label": "S3",
            "variable_axis_type": "post_treatment",
            "variable_value": "optimized VED + HIP",
            "host_material_system": {
                "family": "titanium alloy",
                "composition": "Ti-6Al-4V",
            },
            "process_context": {
                "laser_power_w": 280,
                "scan_speed_mm_s": 1200,
                "hatch_spacing_um": 100,
                "layer_thickness_um": 30,
                "energy_density_j_mm3": 78,
                "energy_density_origin": "reported",
                "build_orientation": "vertical",
                "post_treatment_summary": "HIP",
            },
            "source_anchor_ids": ["anchor-process"],
        }
    }
    test_condition_lookup = {
        "tc-25": {
            "test_condition_id": "tc-25",
            "condition_payload": {
                "test_method": "tensile",
                "test_temperature_c": 25,
                "strain_rate_s-1": 0.001,
                "loading_direction": "vertical",
                "sample_orientation": "vertical",
            },
            "evidence_anchor_ids": ["anchor-test"],
        }
    }
    baseline_lookup = {
        "base-s2": {
            "baseline_id": "base-s2",
            "baseline_label": "S2 optimized VED without HIP",
            "baseline_type": "same_paper_control",
            "baseline_scope": "current_paper",
            "evidence_anchor_ids": ["anchor-baseline"],
        }
    }

    comparable_result = assembler.assemble_comparable_result(
        result_row=result_row,
        sample_lookup=sample_lookup,
        test_condition_lookup=test_condition_lookup,
        baseline_lookup=baseline_lookup,
    )
    assert comparable_result is not None
    assessment_context = assembler.build_assessment_context(
        result_row=result_row,
        sample_lookup=sample_lookup,
        test_condition_lookup=test_condition_lookup,
        baseline_lookup=baseline_lookup,
    )
    scoped_result = assembler.build_collection_comparable_result(
        collection_id="col-1",
        comparable_result=comparable_result,
        sort_order=0,
        assessment_context=assessment_context,
    )

    assert comparable_result.normalized_context.process_normalized == (
        "P=280 W, v=1200 mm/s, h=100 um, t=30 um, VED=78 J/mm3, "
        "VED_origin=reported, build=vertical, HIP"
    )
    assert comparable_result.normalized_context.test_condition_normalized == (
        "tensile, 25 C, strain_rate=0.001 s^-1, loading=vertical, sample=vertical"
    )
    assert scoped_result.assessment.comparability_status == "comparable"
    assert "pbf_context_detected" in scoped_result.assessment.comparability_basis
    assert "build_orientation_reported" in scoped_result.assessment.comparability_basis
    assert "strain_rate_reported" in scoped_result.assessment.comparability_basis

    missing_strain_lookup = {
        "tc-25": {
            **test_condition_lookup["tc-25"],
            "condition_payload": {
                "test_method": "tensile",
                "test_temperature_c": 25,
                "loading_direction": "vertical",
                "sample_orientation": "vertical",
            },
        }
    }
    limited_result = assembler.assemble_comparable_result(
        result_row=result_row,
        sample_lookup=sample_lookup,
        test_condition_lookup=missing_strain_lookup,
        baseline_lookup=baseline_lookup,
    )
    assert limited_result is not None
    limited_scope = assembler.build_collection_comparable_result(
        collection_id="col-1",
        comparable_result=limited_result,
        sort_order=0,
        assessment_context=assembler.build_assessment_context(
            result_row=result_row,
            sample_lookup=sample_lookup,
            test_condition_lookup=missing_strain_lookup,
            baseline_lookup=baseline_lookup,
        ),
    )

    assert limited_scope.assessment.comparability_status == "limited"
    assert "strain_rate_s-1" in limited_scope.assessment.missing_critical_context


def test_comparison_assembly_builds_pairwise_sample_relations():
    assembler = ComparableResultAssembler()
    records = ComparisonInputRecords(
        sample_variants=(
            SampleVariant(
                variant_id="var-a",
                document_id="doc-1",
                collection_id="col-1",
                domain_profile="core_neutral",
                variant_label="A",
                host_material_system={"family": "316L stainless steel"},
                composition=None,
                variable_axis_type=None,
                variable_value=None,
                process_context={
                    "energy_density_j_mm3": 70,
                    "scan_speed_mm_s": 0.25,
                    "scan_strategy": "A",
                },
                profile_payload={"source_kind": "table_row"},
                structure_feature_ids=(),
                source_anchor_ids=(),
                confidence=0.9,
                epistemic_status="normalized_from_evidence",
            ),
            SampleVariant(
                variant_id="var-b",
                document_id="doc-1",
                collection_id="col-1",
                domain_profile="core_neutral",
                variant_label="B",
                host_material_system={"family": "316L stainless steel"},
                composition=None,
                variable_axis_type=None,
                variable_value=None,
                process_context={
                    "energy_density_j_mm3": 70,
                    "scan_speed_mm_s": 0.25,
                    "scan_strategy": "B",
                },
                profile_payload={"source_kind": "table_row"},
                structure_feature_ids=(),
                source_anchor_ids=(),
                confidence=0.9,
                epistemic_status="normalized_from_evidence",
            ),
        ),
        measurement_results=(
            MeasurementResult(
                result_id="res-a",
                document_id="doc-1",
                collection_id="col-1",
                domain_profile="core_neutral",
                variant_id="var-a",
                property_normalized="yield_strength",
                result_type="scalar",
                claim_scope="current_work",
                value_payload={"value": 560},
                unit="MPa",
                test_condition_id=None,
                baseline_id=None,
                structure_feature_ids=(),
                characterization_observation_ids=(),
                evidence_anchor_ids=("anc-a",),
                traceability_status="direct",
                result_source_type="table",
                epistemic_status="directly_observed",
            ),
            MeasurementResult(
                result_id="res-b",
                document_id="doc-1",
                collection_id="col-1",
                domain_profile="core_neutral",
                variant_id="var-b",
                property_normalized="yield_strength",
                result_type="scalar",
                claim_scope="current_work",
                value_payload={"value": 480},
                unit="MPa",
                test_condition_id=None,
                baseline_id=None,
                structure_feature_ids=(),
                characterization_observation_ids=(),
                evidence_anchor_ids=("anc-b",),
                traceability_status="direct",
                result_source_type="table",
                epistemic_status="directly_observed",
            ),
        ),
        test_conditions=(),
        baseline_references=(),
    )

    semantic_records = assembler.assemble_semantic_records(
        collection_id="col-1",
        records=records,
    )

    assert len(semantic_records.pairwise_comparison_relations) == 1
    relation = semantic_records.pairwise_comparison_relations[0]
    assert isinstance(relation, PairwiseComparisonRelation)
    assert relation.comparison_axis == "scan_strategy"
    assert relation.current_variant_id == "var-a"
    assert relation.reference_variant_id == "var-b"
    assert relation.current_value == 560
    assert relation.reference_value == 480
    assert relation.evidence_anchor_ids == ("anc-a", "anc-b")


def test_comparison_assembly_selects_p001_style_salient_pairwise_relations():
    assembler = ComparableResultAssembler()
    sample_rows = [
        ("1", 70, 0.25, "A"),
        ("2", 70, 0.25, "B"),
        ("3", 70, 0.25, "C"),
        ("4", 100, 0.175, "A"),
        ("5", 150, 0.12, "A"),
        ("6", 150, 0.12, "B"),
        ("7", 150, 0.12, "C"),
        ("8", 70, 0.239, "A"),
        ("9", 70, 0.239, "B"),
        ("10", 70, 0.239, "C"),
        ("11", 100, 0.167, "A"),
        ("12", 100, 0.167, "B"),
        ("13", 100, 0.167, "C"),
        ("14", 150, 0.111, "A"),
        ("15", 150, 0.111, "B"),
        ("16", 150, 0.111, "C"),
    ]
    values = {
        "1": (95.4, 236.65, 375.13, 7.21),
        "2": (97.7, 159.97, 196.78, 1.79),
        "3": (93.8, 169.40, 199.47, 2.27),
        "4": (93.9, 341.38, 459.58, 6.62),
        "5": (97.14, 302.24, 384.50, 6.40),
        "6": (95.7, 200.31, 278.13, 1.62),
        "7": (94.3, 263.55, 356.84, 2.93),
        "8": (96.8, 187.82, 269.95, 3.66),
        "9": (92.4, 148.36, 178.37, 2.08),
        "10": (93.8, 161.61, 198.47, 2.12),
        "11": (96.2, 177.68, 203.48, 3.31),
        "12": (96.1, 201.08, 239.34, 2.42),
        "13": (98.0, 186.46, 256.68, 2.194),
        "14": (99.45, 462.02, 584.44, 41.9),
        "15": (96.7, 278.76, 342.23, 4.29),
        "16": (98.6, 414.07, 530.37, 1.17),
    }
    properties = (
        ("density", "%", 0),
        ("yield_strength", "MPa", 1),
        ("tensile_strength", "MPa", 2),
        ("elongation", "%", 3),
    )
    samples = tuple(
        SampleVariant(
            variant_id=f"var-{label}",
            document_id="doc-1",
            collection_id="col-1",
            domain_profile="core_neutral",
            variant_label=label,
            host_material_system={"family": "316L stainless steel"},
            composition=None,
            variable_axis_type=None,
            variable_value=None,
            process_context={
                "energy_density_j_mm3": energy_density,
                "scan_speed_mm_s": scan_speed,
                "scan_strategy": strategy,
            },
            profile_payload={"source_kind": "table_row"},
            structure_feature_ids=(),
            source_anchor_ids=(),
            confidence=0.9,
            epistemic_status="normalized_from_evidence",
        )
        for label, energy_density, scan_speed, strategy in sample_rows
    )
    measurements = tuple(
        MeasurementResult(
            result_id=f"res-{label}-{property_name}",
            document_id="doc-1",
            collection_id="col-1",
            domain_profile="core_neutral",
            variant_id=f"var-{label}",
            property_normalized=property_name,
            result_type="scalar",
            claim_scope="current_work",
            value_payload={"value": values[label][value_index]},
            unit=unit,
            test_condition_id=None,
            baseline_id=None,
            structure_feature_ids=(),
            characterization_observation_ids=(),
            evidence_anchor_ids=(f"anc-{label}-{property_name}",),
            traceability_status="direct",
            result_source_type="table",
            epistemic_status="directly_observed",
        )
        for label, *_ in sample_rows
        for property_name, unit, value_index in properties
    )
    records = ComparisonInputRecords(
        sample_variants=samples,
        measurement_results=measurements,
        test_conditions=(),
        baseline_references=(),
    )

    semantic_records = assembler.assemble_semantic_records(
        collection_id="col-1",
        records=records,
    )

    relation_keys = {
        (
            relation.current_variant_id.removeprefix("var-"),
            relation.reference_variant_id.removeprefix("var-"),
            relation.property_normalized,
        )
        for relation in semantic_records.pairwise_comparison_relations
    }

    assert len(relation_keys) == 19
    assert relation_keys == {
        ("1", "3", "density"),
        ("2", "1", "density"),
        ("1", "2", "yield_strength"),
        ("1", "2", "tensile_strength"),
        ("1", "2", "elongation"),
        ("1", "8", "yield_strength"),
        ("1", "8", "tensile_strength"),
        ("1", "8", "elongation"),
        ("11", "4", "density"),
        ("4", "11", "yield_strength"),
        ("4", "11", "tensile_strength"),
        ("14", "5", "density"),
        ("14", "5", "yield_strength"),
        ("14", "5", "tensile_strength"),
        ("14", "5", "elongation"),
        ("14", "15", "yield_strength"),
        ("14", "16", "yield_strength"),
        ("14", "15", "elongation"),
        ("14", "16", "elongation"),
    }


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


def test_comparison_service_lists_corpus_results_without_manifest_cache_artifacts(
    tmp_path,
):
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
    )

    collection = collection_service.create_collection("Corpus Cache Collection")
    collection_id = collection["collection_id"]

    comparable_result = _build_test_comparable_result(
        comparable_result_id="cres-cache-1",
        source_document_id="paper-cache-1",
        source_result_id="res-cache-1",
    )
    scoped_results = [
        _build_collection_overlay(
            collection_id=collection_id,
            comparable_result=comparable_result,
            sort_order=0,
        )
    ]
    _store_core_comparison_artifacts(
        comparison_service,
        collection_id,
        [comparable_result],
        scoped_results,
    )

    payload = comparison_service.list_corpus_comparable_results()

    assert payload["total"] == 1
    assert payload["items"][0]["comparable_result_id"] == "cres-cache-1"
    assert not (collection_service.root_dir / "_core_cache").exists()


def test_comparison_service_reflects_repository_updates_without_manifest_cache(
    tmp_path,
):
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    comparison_service = ComparisonService(
        collection_service=collection_service,
    )

    collection = collection_service.create_collection("Corpus Refresh Collection")
    collection_id = collection["collection_id"]

    first_result = _build_test_comparable_result(
        comparable_result_id="cres-refresh-1",
        source_document_id="paper-refresh-1",
        source_result_id="res-refresh-1",
    )
    first_scoped_results = [
        _build_collection_overlay(
            collection_id=collection_id,
            comparable_result=first_result,
            sort_order=0,
        )
    ]
    _store_core_comparison_artifacts(
        comparison_service,
        collection_id,
        [first_result],
        first_scoped_results,
    )

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
    refreshed_scoped_results = [
        _build_collection_overlay(
            collection_id=collection_id,
            comparable_result=first_result,
            sort_order=0,
        ),
        _build_collection_overlay(
            collection_id=collection_id,
            comparable_result=second_result,
            sort_order=1,
        ),
    ]
    _store_core_comparison_artifacts(
        comparison_service,
        collection_id,
        [first_result, second_result],
        refreshed_scoped_results,
    )

    refreshed_payload = comparison_service.list_corpus_comparable_results()

    assert refreshed_payload["total"] == 2
    assert {
        item["comparable_result_id"]
        for item in refreshed_payload["items"]
    } == {"cres-refresh-1", "cres-refresh-2"}
    assert not (collection_service.root_dir / "_core_cache").exists()
