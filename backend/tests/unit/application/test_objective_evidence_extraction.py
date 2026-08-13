from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.evidence_extraction import ExtractedEvidenceDraft
from application.core.objectives.evidence_routing import EvidenceCandidate
from application.core.objectives.research_objective_service import PaperAnalysisFrame
from application.core.objectives.schemas import StructuredEvidenceExtractions
from application.core.paper_facts.schemas import StructuredTableMatrixRepair
from domain.core import PaperSkim
from domain.source import SourceDocumentNode, SourceDocumentTree
from tests.support.collection_service import build_test_collection_service
from tests.support.research_objective_service import (
    build_research_objective_service as _build_research_objective_service,
    research_objective as _research_objective,
)


def test_research_objective_table_source_payload_includes_table_cells(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        document_id="paper-1",
        page=1,
        caption_text="Density results",
        heading_path="Results",
        column_headers=["Specimens", "Density (%)"],
        table_matrix=[
            ["Specimens", "Density (%)"],
            ["as-SLM (140/", "92.19"],
        ],
    )
    cells = [
        SimpleNamespace(
            table_id="other-table",
            row_index=1,
            col_index=0,
            header_path="Specimens",
            cell_text="other",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=1,
            header_path="Density (%)",
            cell_text="92.19",
        ),
        SimpleNamespace(
            table_id="table-1",
            row_index=1,
            col_index=0,
            header_path="Specimens",
            cell_text="as-SLM (140/",
        ),
    ]

    payload = service._build_objective_route_source_payload(
        route=route,
        blocks=[],
        tables=[table],
        table_cells=cells,
    )

    assert payload["table_cells"] == [
        {
            "row_index": 1,
            "col_index": 0,
            "header_path": "Specimens",
            "cell_text": "as-SLM (140/",
        },
        {
            "row_index": 1,
            "col_index": 1,
            "header_path": "Density (%)",
            "cell_text": "92.19",
        },
    ]


def test_research_objective_text_source_payload_uses_document_tree(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods",
            "role": "process_or_treatment",
            "extractable": True,
        }
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section",),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                text="The 316L samples used heat treatment at 650 C for 4 h.",
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="methods",
                page_start=2,
                page_end=2,
            ),
        },
    )

    payload = service._build_objective_route_source_payload(
        route=route,
        blocks=[],
        tables=[],
        document_tree=document_tree,
    )

    assert payload == {
        "source_kind": "text_window",
        "source_ref": "methods",
        "document_id": "paper-1",
        "page": 2,
        "block_type": "paragraph",
        "heading_path": "Methods",
        "text": "The 316L samples used heat treatment at 650 C for 4 h.",
    }


def test_objective_paper_frame_payload_prioritizes_relevant_tree_sections(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength of LPBF 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle", "build orientation angle"],
            "constraints": ["Laser Powder Bed Fusion"],
            "outcomes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    child_ids = [f"section-{index}" for index in range(30)]
    child_ids.extend(("texture-section", "yield-section"))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-p006",
            parent_id=None,
            child_ids=tuple(child_ids),
            node_type="document",
            order=0,
        )
    }
    for index in range(30):
        section_id = f"section-{index}"
        paragraph_id = f"paragraph-{index}"
        nodes[section_id] = SourceDocumentNode(
            node_id=section_id,
            document_id="paper-p006",
            parent_id="root",
            child_ids=(paragraph_id,),
            node_type="section",
            order=100 + index,
            title=f"Background {index}",
            heading_path=(f"Background {index}",),
        )
        nodes[paragraph_id] = SourceDocumentNode(
            node_id=paragraph_id,
            document_id="paper-p006",
            parent_id=section_id,
            child_ids=(),
            node_type="paragraph",
            order=101 + index,
            text=(
                "General additive-manufacturing background and introduction text "
                "without the active variables."
            ),
            heading_path=(f"Background {index}",),
        )
    nodes["texture-section"] = SourceDocumentNode(
        node_id="texture-section",
        document_id="paper-p006",
        parent_id="root",
        child_ids=("texture-paragraph",),
        node_type="section",
        order=1000,
        title="Texture results",
        heading_path=("Results", "Texture results"),
    )
    nodes["texture-paragraph"] = SourceDocumentNode(
        node_id="texture-paragraph",
        document_id="paper-p006",
        parent_id="texture-section",
        child_ids=(),
        node_type="paragraph",
        order=1001,
        text=(
            "Scan strategy rotation angle and build orientation changed "
            "crystallographic texture intensity in LPBF 316L."
        ),
        heading_path=("Results", "Texture results"),
    )
    nodes["yield-section"] = SourceDocumentNode(
        node_id="yield-section",
        document_id="paper-p006",
        parent_id="root",
        child_ids=("yield-paragraph",),
        node_type="section",
        order=1100,
        title="Tensile properties",
        heading_path=("Results", "Tensile properties"),
    )
    nodes["yield-paragraph"] = SourceDocumentNode(
        node_id="yield-paragraph",
        document_id="paper-p006",
        parent_id="yield-section",
        child_ids=(),
        node_type="paragraph",
        order=1101,
        text=(
            "Build orientation angle changed yield strength and tensile response "
            "for 316L stainless steel."
        ),
        heading_path=("Results", "Tensile properties"),
    )
    document_tree = SourceDocumentTree(
        document_id="paper-p006",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )

    payload = service._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=objective,
        paper_skim=None,
        document=SimpleNamespace(
            document_id="paper-p006",
            title="Mapping the roles of scan strategy and build orientation",
        ),
        profile=None,
        blocks=[],
        tables=[],
        document_tree=document_tree,
    )

    labels = [item["section_label"] for item in payload["section_snippets"]]
    assert "Results > Texture results" in labels
    assert "Results > Tensile properties" in labels
    assert len(labels) <= 12
    assert payload["objective"]["variables"] == [
        "scan strategy rotation angle",
        "build orientation angle",
    ]
    assert payload["objective"]["outcomes"] == [
        "crystallographic texture",
        "yield strength",
    ]
    assert payload["objective"]["constraints"] == ["Laser Powder Bed Fusion"]
    assert "objective_context" not in payload


def test_objective_paper_frame_payload_filters_unscored_tables(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle", "build orientation angle"],
            "outcomes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    payload = service._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=objective,
        paper_skim=None,
        document=SimpleNamespace(
            document_id="paper-p006",
            title="Mapping the roles of scan strategy and build orientation",
        ),
        profile=None,
        blocks=[],
        tables=[
            SimpleNamespace(
                table_id="tbl-density",
                table_order=1,
                caption_text="VED settings and density.",
                heading_path="Methods",
                column_headers=("VED", "Density"),
                row_count=2,
                col_count=2,
                table_matrix=(("VED", "Density"), ("50", "91.9")),
            ),
            SimpleNamespace(
                table_id="tbl-yield-texture",
                table_order=2,
                caption_text="Build orientation angle, scan strategy rotation angle, texture and yield strength.",
                heading_path="Results",
                column_headers=(
                    "build orientation angle",
                    "scan strategy rotation angle",
                    "texture",
                    "yield strength",
                ),
                row_count=2,
                col_count=4,
                table_matrix=(
                    (
                        "build orientation angle",
                        "scan strategy rotation angle",
                        "texture",
                        "yield strength",
                    ),
                    ("0", "67", "strong", "460"),
                ),
            ),
        ],
        document_tree=None,
    )

    table_ids = [item["table_id"] for item in payload["table_summaries"]]
    assert "tbl-yield-texture" in table_ids
    assert "tbl-density" not in table_ids


def test_objective_symbol_axes_distinguish_scan_and_build_angles(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-angle-effects",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": [
                "scan strategy rotation angle",
                "build orientation angles",
            ],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )

    assert property_matching.process_column_axis_keys("θ") == {
        "scan strategy rotation angle"
    }
    assert property_matching.process_column_axis_keys("ɵ") == {
        "scan strategy rotation angle"
    }
    assert property_matching.process_column_axis_keys("α") == {
        "build orientation alpha angle"
    }
    assert property_matching.process_column_axis_keys("β") == {
        "build orientation beta angle"
    }
    assert service._objective_process_attribute_label(
        column="θ",
        role="process variable",
        objective_context=objective,
    ) == "scan strategy rotation angle"
    assert service._objective_process_attribute_label(
        column="α",
        role="process variable",
        objective_context=objective,
    ) == "build orientation alpha angle"


def test_objective_angle_table_comparison_retains_all_changed_axes(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-angle-effects",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect yield strength?"
            ),
            "variables": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
            "outcomes": ["yield strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-angle",
            "source_kind": "table",
            "source_ref": "table-angle",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "α ( ◦ )": "sample condition",
                "β ( ◦ )": "sample condition",
                "θ ( ◦ )": "process_variable",
                "Yield Strength Experiment (MPa)": "result_property",
            },
            "confidence": 0.95,
        }
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in service._objective_table_matrix_evidence_records(
            route=route,
            objective_context=objective,
            source={
                "page": 8,
                "column_headers": [
                    "α ( ◦ )",
                    "β ( ◦ )",
                    "θ ( ◦ )",
                    "Yield Strength Experiment (MPa)",
                ],
                "table_matrix": [
                    [
                        "α ( ◦ )",
                        "β ( ◦ )",
                        "θ ( ◦ )",
                        "Yield Strength Experiment (MPa)",
                    ],
                    ["0", "0", "0", "334.2"],
                    ["45", "22.5", "45", "365.6"],
                ],
            },
        )
    )

    comparison = service._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )[0]

    assert [item.name for item in comparison.changed_variables] == [
        "build orientation alpha angle",
        "build orientation beta angle",
        "scan strategy rotation angle",
    ]
    assert comparison.attribution_scope == "joint_effect"
    assert comparison.comparison is not None
    assert comparison.comparison.axis_names == (
        "build orientation alpha angle",
        "build orientation beta angle",
        "scan strategy rotation angle",
    )


def test_llm_objective_evidence_rejects_values_and_axis_absent_from_source(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-angle-effects",
            "question": "How do scan and build angles affect yield strength?",
            "variables": [
                "scan strategy rotation angle",
                "build orientation angle",
            ],
            "outcomes": ["yield strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-angle",
            "source_kind": "text_window",
            "source_ref": "block-strategies",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-strategies",
            "text": (
                "Scanning strategies A, B, and C were evaluated at an energy "
                "density of 100 J/mm3 and a scanning speed of 700 mm/s."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "scan strategy rotation angle",
                    "baseline_value": 0,
                    "target_value": 67,
                    "unit": "degree",
                },
                {
                    "name": "build orientation angle",
                    "baseline_value": 0,
                    "target_value": 67,
                    "unit": "degree",
                },
            ],
            "comparison": {
                "baseline_label": "0 degree",
                "target_label": "67 degree",
                "axis_names": [
                    "scan strategy rotation angle",
                    "build orientation angle",
                ],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "yield strength",
                "value": 480,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Yield strength increased from 450 to 480 MPa.",
            },
            "attribution_scope": "joint_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert records == ()


def test_llm_objective_evidence_accepts_source_grounded_axis_and_values(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-angle-effects",
            "question": "How does scan rotation affect yield strength?",
            "variables": ["scan strategy rotation angle"],
            "outcomes": ["yield strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-angle",
            "source_kind": "table",
            "source_ref": "table-angle",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "table",
            "source_ref": "table-angle",
            "column_headers": ["theta (degree)", "Yield strength (MPa)"],
            "table_matrix": [
                ["theta (degree)", "Yield strength (MPa)"],
                ["0", "334.2"],
                ["45", "351.9"],
            ],
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "scan strategy rotation angle",
                    "baseline_value": 0,
                    "target_value": 45,
                    "unit": "degree",
                }
            ],
            "comparison": {
                "baseline_label": "theta 0",
                "target_label": "theta 45",
                "axis_names": ["scan strategy rotation angle"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "yield strength",
                "value": 351.9,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Yield strength increased from 334.2 to 351.9 MPa.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "material", "value": "316L"}],
                "process": [
                    {"name": "process", "value": "laser powder bed fusion"}
                ],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1


def test_llm_objective_evidence_completes_grounded_categorical_endpoints(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "text": (
                "The build platform preheating temperature conditions were "
                "non-preheated NP and 150 C preheated P150. P150 had a coarser "
                "cellular microstructure than NP."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "preheating build platform temperature",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["preheating build platform temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "value": None,
                "unit": None,
                "direction": "mixed",
                "result_text": "P150 had a coarser cellular microstructure than NP.",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == [
        {
            "name": "preheating build platform temperature",
            "baseline_value": "NP",
            "target_value": "P150",
            "unit": None,
        }
    ]
    assert records[0]["scientific_context"] == {
        "material": [],
        "sample": [],
        "process": [],
        "test": [],
    }


def test_llm_objective_evidence_accepts_verbatim_preheating_crack_comparison(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-cracks",
            "question": (
                "How does base plate preheating temperature affect crack formation?"
            ),
            "variables": ["base plate preheating temperature"],
            "outcomes": ["crack formation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "block-crack-result",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-crack-result",
            "text": (
                "Al7075 microcracks can abundantly form after SLM processing "
                "without preheating. Although the application of preheating "
                "largely reduces this cracking behavior, it fails to completely "
                "prevent microcrack formation after preheating at 400 C."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "base plate preheating temperature",
                    "baseline_value": "without preheating",
                    "target_value": "preheating at 400 C",
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "without preheating",
                "target_label": "preheating at 400 C",
                "axis_names": ["base plate preheating temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "crack formation",
                "value": None,
                "unit": None,
                "direction": "decrease",
                "result_text": (
                    "application of preheating largely reduces this cracking behavior"
                ),
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "material", "value": "Al7075"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == [
        {
            "name": "base plate preheating temperature",
            "baseline_value": "without preheating",
            "target_value": "preheating at 400 C",
            "unit": None,
        }
    ]
    assert records[0]["reported_result"]["direction"] == "decrease"


def test_llm_objective_evidence_drops_unsupported_qualitative_direction(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "text": (
                "The build platform preheating temperature conditions were NP "
                "and P150. A cellular structure was observed in the P150 "
                "microstructure."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "preheating build platform temperature",
                    "baseline_value": "NP",
                    "target_value": "P150",
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["preheating build platform temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "value": "cellular structure",
                "unit": None,
                "direction": "increase",
                "result_text": "cellular structure",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["reported_result"]["direction"] == "unknown"


def test_llm_objective_evidence_keeps_grounded_qualitative_direction(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "question": "How does build platform preheating affect grain size?",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["grain size"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "text": (
                "The build platform preheating temperature changed from NP to "
                "P150, and grain size increased."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "preheating build platform temperature",
                    "baseline_value": "NP",
                    "target_value": "P150",
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["preheating build platform temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "grain size",
                "value": None,
                "unit": None,
                "direction": "increase",
                "result_text": "grain size increased",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["reported_result"]["direction"] == "increase"


def test_llm_objective_evidence_repairs_endpoints_to_grounded_group_labels(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "text": (
                "Comparing the microstructure obtained for P150 with NP condition, "
                "the cellular structure is seen in the former condition. The "
                "decrease in the cooling rate by preheating the build platform is "
                "due to the lower temperature gradient."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "preheating build platform temperature",
                    "baseline_value": "150 C",
                    "target_value": "room temperature",
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "P150",
                "target_label": "NP",
                "axis_names": ["preheating build platform temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "value": "cellular structure",
                "unit": None,
                "direction": "mixed",
                "result_text": (
                    "Comparing the microstructure obtained for P150 with NP "
                    "condition, the cellular structure is seen in the former "
                    "condition."
                ),
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == [
        {
            "name": "preheating build platform temperature",
            "baseline_value": "P150",
            "target_value": "NP",
            "unit": None,
        }
    ]


def test_llm_objective_evidence_does_not_complete_labels_absent_from_source(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = service._objective_evidence_records_from_extracted(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-preheating",
            "text": "Preheating changed the cellular microstructure.",
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "preheating build platform temperature",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["preheating build platform temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "value": None,
                "unit": None,
                "direction": "mixed",
                "result_text": "Preheating changed the cellular microstructure.",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert records == ()


def test_llm_table_result_rejects_outcome_and_unit_from_another_column(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    record = {
        "changed_variables": [
            {
                "name": "scan strategy rotation angle",
                "baseline_value": 0,
                "target_value": 45,
                "unit": "degree",
            }
        ],
        "comparison": {
            "baseline_label": "theta 0",
            "target_label": "theta 45",
        },
        "reported_result": {
            "outcome": "yield strength",
            "value": 351.9,
            "unit": "MPa",
            "result_text": "Yield strength increased from 334.2 to 351.9 MPa.",
        },
    }

    assert not service._objective_extracted_result_is_source_grounded(
        record,
        source={
            "source_kind": "table",
            "column_headers": ["theta (degree)", "Hardness (HV)"],
            "table_matrix": [
                ["theta (degree)", "Hardness (HV)"],
                ["0", "334.2"],
                ["45", "351.9"],
            ],
        },
    )


def test_llm_table_result_rejects_value_from_a_different_experiment_row(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    record = {
        "changed_variables": [
            {
                "name": "scan strategy rotation angle",
                "baseline_value": 0,
                "target_value": 45,
                "unit": "degree",
            }
        ],
        "comparison": {
            "baseline_label": "theta 0",
            "target_label": "theta 45",
        },
        "reported_result": {
            "outcome": "yield strength",
            "value": 365.6,
            "unit": "MPa",
            "result_text": "Yield strength increased from 334.2 to 365.6 MPa.",
        },
    }

    assert not service._objective_extracted_result_is_source_grounded(
        record,
        source={
            "source_kind": "table",
            "column_headers": ["theta (degree)", "Yield strength (MPa)"],
            "table_matrix": [
                ["theta (degree)", "Yield strength (MPa)"],
                ["0", "334.2"],
                ["45", "351.9"],
                ["67", "365.6"],
            ],
        },
    )


def test_llm_context_drops_values_absent_from_source(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    record = service._objective_retain_source_grounded_context(
        {
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [
                    {
                        "name": "heat treatment temperature",
                        "value": "500",
                        "unit": "C",
                    }
                ],
                "test": [],
            }
        },
        source={
            "source_kind": "text_window",
            "text": "The samples were heat treated at 650 C for four hours.",
        },
    )

    assert record["scientific_context"]["process"] == []


def test_llm_result_rejects_ungrounded_categorical_variable_endpoint(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    assert not service._objective_extracted_result_is_source_grounded(
        {
            "changed_variables": [
                {
                    "name": "sample state",
                    "baseline_value": "as-SLM",
                    "target_value": "solution-treated",
                    "unit": None,
                }
            ],
            "reported_result": {
                "outcome": "yield strength",
                "value": 265.1,
                "unit": "MPa",
                "result_text": "Yield strength changed from 426.7 to 265.1 MPa.",
            },
        },
        source={
            "source_kind": "text_window",
            "text": (
                "Sample state changed from as-SLM to HIP-SLM; the samples had "
                "yield strengths of 426.7 and 265.1 MPa, respectively."
            ),
        },
    )


def test_llm_context_drops_attribute_not_bound_to_name_value_and_unit(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )

    record = service._objective_retain_source_grounded_context(
        {
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [
                    {"name": "laser power", "value": 650, "unit": "W"}
                ],
                "test": [],
            }
        },
        source={
            "source_kind": "text_window",
            "text": "The samples were heat treated at 650 C for four hours.",
        },
    )

    assert record["scientific_context"]["process"] == []


def test_deterministic_frame_requires_variable_and_property_axis(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-texture-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation angle "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["scan strategy rotation angle", "build orientation angle"],
            "outcomes": ["crystallographic texture", "yield strength"],
            "confidence": 0.9,
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-ved",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": "study-paper-ved",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "process_context": ["LPBF", "VED"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-paper-ved-density",
                            "varied_factors": ["laser power", "scan speed"],
                            "outcome": "density",
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "block-ved",
                                }
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
            "evidence_density": "low",
        }
    )

    record = service._build_deterministic_objective_paper_frame_record(
        objective=objective,
        paper_skim=paper_skim,
        payload={
            "document": {
                "document_id": "paper-ved",
                "title": "VED density study",
            },
            "section_snippets": [
                {
                    "section_label": "Results",
                    "text": "Laser power and scan speed changed density.",
                }
            ],
            "table_summaries": [
                {
                    "table_id": "tbl-density",
                    "caption_text": "VED and density.",
                    "column_headers": ["VED", "density"],
                }
            ],
        },
    )

    assert record["relevance"] == "irrelevant"
    assert record["relevant_tables"] == []


def test_research_objective_text_source_payload_resolves_tree_node_to_block(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-node",
            "role": "process_or_treatment",
            "extractable": True,
        }
    )
    block = SimpleNamespace(
        block_id="block-methods",
        page=2,
        block_type="paragraph",
        heading_path="Methods",
        text="The 316L samples used heat treatment at 650 C for 4 h.",
    )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section",),
                node_type="document",
                order=0,
            ),
            "methods-section": SourceDocumentNode(
                node_id="methods-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("methods-node",),
                node_type="section",
                order=100,
                title="Methods",
                heading_path=("Methods",),
            ),
            "methods-node": SourceDocumentNode(
                node_id="methods-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=110,
                heading_path=("Methods",),
                source_ref_kind="block",
                source_ref_id="block-methods",
                page_start=2,
                page_end=2,
            ),
        },
    )

    payload = service._build_objective_route_source_payload(
        route=route,
        blocks=[block],
        tables=[],
        document_tree=document_tree,
    )

    assert payload == {
        "source_kind": "text_window",
        "source_ref": "methods-node",
        "document_id": "paper-1",
        "page": 2,
        "block_type": "paragraph",
        "heading_path": "Methods",
        "text": "The 316L samples used heat treatment at 650 C for 4 h.",
    }


def test_research_objective_prompt_source_uses_cells_without_duplicate_matrix(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    source = {
        "source_kind": "table",
        "source_ref": "table-1",
        "document_id": "paper-1",
        "page": 4,
        "caption_text": "Measured density",
        "heading_path": "Results",
        "column_headers": ["sample", "density"],
        "table_matrix": [["sample", "density"], ["A", "99.6"]],
        "table_cells": [
            {
                "row_index": 1,
                "col_index": 0,
                "header_path": "sample",
                "cell_text": "A",
            }
        ],
    }

    projected = service._objective_evidence_prompt_source(source)

    assert "table_matrix" not in projected
    assert projected["table_cells"] == source["table_cells"]

    fallback = service._objective_evidence_prompt_source(
        {key: value for key, value in source.items() if key != "table_cells"}
    )
    assert fallback["table_matrix"] == [["sample", "density"], ["A", "99.6"]]


def test_research_objective_evidence_prompt_compacts_long_text_source(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "background": "x" * 1000,
            "relevant_tables": ["table-1"],
            "excluded_tables": ["table-2"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "long-results",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.86,
        }
    )
    block = SimpleNamespace(
        block_id="long-results",
        document_id="paper-1",
        page=4,
        block_type="paragraph",
        heading_path="Results",
        text="Yield strength improved after heat treatment. " * 200,
    )

    class PayloadCaptureExtractor:
        def __init__(self) -> None:
            self.unit_payloads: list[dict[str, Any]] = []

        def extract_objective_evidence(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.unit_payloads.append(payload)
            return StructuredEvidenceExtractions()

    extractor = PayloadCaptureExtractor()

    service._build_objective_evidence(
        collection_id="col-test",
        extractor=extractor,
        objectives=(objective,),
        paper_skims=(),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    payload = extractor.unit_payloads[0]
    assert len(payload["source"]["text"]) <= 1800
    assert "background" not in payload["paper_frame"]
    assert "relevant_tables" not in payload["paper_frame"]
    assert "excluded_tables" not in payload["paper_frame"]


def test_research_objective_fragmented_table_matrix_triggers_structural_repair(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    assert service._objective_table_source_needs_llm_structural_repair(
        route=route,
        source={
            "table_matrix": [
                ["Specimens", "Density (%)"],
                ["100) HIP-SLM (100/", "98.15"],
            ],
            "table_cells": [],
        },
    )


def test_research_objective_repairs_fragmented_table_with_paper_facts_extractor(
    tmp_path,
):
    class RepairingPaperFactsExtractor:
        def __init__(self) -> None:
            self.payloads: list[dict[str, Any]] = []

        def repair_table_matrix(
            self,
            payload: dict[str, Any],
        ) -> StructuredTableMatrixRepair:
            self.payloads.append(payload)
            return StructuredTableMatrixRepair(
                repaired_table_matrix=[
                    ["Specimens", "Density (%)"],
                    ["100) HIP-SLM (100/100)", "98.15"],
                ],
                confidence=0.9,
            )

    extractor = RepairingPaperFactsExtractor()
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
        paper_facts_extractor=extractor,
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    source = {
        "source_kind": "table",
        "source_ref": "table-1",
        "document_id": "paper-1",
        "column_headers": ["Specimens", "Density (%)"],
        "table_matrix": [
            ["Specimens", "Density (%)"],
            ["100) HIP-SLM (100/", "98.15"],
        ],
    }

    repaired_source, repair_failed = (
        service._repair_objective_table_source_if_needed(
            collection_id="col-test",
            route=route,
            source=source,
        )
    )

    assert repair_failed is False
    assert len(extractor.payloads) == 1
    assert repaired_source["raw_table_matrix"] == source["table_matrix"]
    assert repaired_source["table_matrix"] == [
        ["Specimens", "Density (%)"],
        ["HIP-SLM (100/100)", "98.15"],
    ]
    assert repaired_source["table_matrix_structural_repair_applied"] is True


def test_research_objective_service_skips_matrix_test_condition_table_fallback(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "test_condition",
            "extractable": True,
            "column_roles": {
                "Condition number": "condition",
                "Sample number": "sample",
                "Scan strategy": "process_variable",
                "Relative density": "result",
            },
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_skips_untyped_table_test_condition_fallback(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "test_condition",
            "extractable": True,
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_skips_off_target_result_table_fallback(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-corrosion",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Sample": "sample_index",
                "E corr (mV)": "electrochemical_parameter",
                "E d (mV)": "electrochemical_parameter",
                "E p (mV)": "electrochemical_parameter",
                "E p - E d (mV)": "electrochemical_parameter",
            },
        }
    )
    corrosion_route = EvidenceCandidate.from_mapping(
        {
            **route.to_record(),
            "objective_id": "obj-corrosion",
            "column_roles": {
                "Sample": "sample_condition",
                "E corr (mV)": "corrosion_potential",
                "E d (mV)": "passivation_potential",
                "E p (mV)": "pitting_potential",
                "E p - E d (mV)": "passivation_interval",
            },
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(route)
    assert service._objective_table_route_should_skip_llm_fallback(corrosion_route)

    eis_route = EvidenceCandidate.from_mapping(
        {
            **route.to_record(),
            "source_ref": "table-eis",
            "column_roles": {
                "Sample": "sample_index",
                "R s (ohm cm2)": "current_experimental_evidence",
                "Q film > n film": "current_experimental_evidence",
                "R film (ohm cm2)": "current_experimental_evidence",
            },
        }
    )

    assert service._objective_table_route_should_skip_llm_fallback(eis_route)


def test_research_objective_service_skips_non_target_result_property_columns(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-chemistry",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Si": "result_property",
                "O": "result_property",
                "N": "result_property",
                "S": "result_property",
            },
            "confidence": 0.76,
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-preheat",
            "outcomes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        }
    )

    records = service._objective_table_matrix_evidence_records(
        route=route,
        objective_context=objective_context,
        source={
            "page": 3,
            "column_headers": ["Si", "O", "N", "S"],
            "table_matrix": [
                ["Si", "O", "N", "S"],
                ["0.10", "<0.10", "<0.10", "<0.03"],
            ],
        },
    )

    assert records == ()


def test_research_objective_service_uses_objective_scientific_intent_directly(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power, porosity, and pore size affect pitting "
                "corrosion behavior of SLM 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["pitting potential"],
            "mechanisms": ["porosity", "pore size"],
            "constraints": ["SLM"],
            "requested_comparator": "lower laser power",
        }
    )

    assert service._route_prompt_objective_record(objective) == {
        "objective_id": "obj-corrosion",
        "question": objective.question,
        "material_scope": ["316L stainless steel"],
        "variables": ["laser power"],
        "outcomes": ["pitting potential"],
        "mechanisms": ["porosity", "pore size"],
        "constraints": ["SLM"],
        "requested_comparator": "lower laser power",
    }


def test_research_objective_service_enriches_missing_source_backed_scope_context(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does energy density affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["energy density"],
            "outcomes": ["relative density"],
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": "study-paper-1-density",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["316L stainless steel"],
                    "process_context": ["selective laser melting"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-paper-1-density",
                            "varied_factors": ["energy density"],
                            "outcome": "relative density",
                            "source_refs": [
                                {
                                    "source_kind": "table",
                                    "source_ref": "table-1",
                                }
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.9,
        }
    )
    evidence = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "density-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "energy density",
                    "baseline_value": 70,
                    "target_value": 150,
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "condition 1",
                "target_label": "condition 2",
                "axis_names": ["energy density"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 99.2,
                "unit": "%",
                "direction": "increase",
                "result_text": "Relative density increased to 99.2%.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [
                    {"name": "hatch space", "value": 0.1, "unit": "mm"}
                ],
                "test": [],
            },
            "source_refs": [
                {"source_kind": "table", "source_ref": "table-1"}
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    enriched = service._enrich_objective_scope_context(
        (evidence,),
        paper_skims=(paper_skim,),
    )[0]

    assert enriched.scientific_context.to_record() == {
        "material": [
            {"name": "material", "value": "316L stainless steel", "unit": None}
        ],
        "sample": [],
        "process": [
            {"name": "hatch space", "value": 0.1, "unit": "mm"},
            {
                "name": "process",
                "value": "selective laser melting",
                "unit": None,
            }
        ],
        "test": [],
    }


def test_research_objective_service_does_not_invent_material_without_document_skim(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    evidence = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "density-result",
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "direct_result",
            "changed_variables": [
                {"name": "energy density", "target_value": 150}
            ],
            "reported_result": {
                "outcome": "relative density",
                "direction": "increase",
                "result_text": "Relative density increased.",
            },
            "attribution_scope": "association_only",
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    enriched = service._enrich_objective_scope_context(
        (evidence,),
        paper_skims=(),
    )[0]

    assert enriched.scientific_context.material == ()


def test_research_objective_service_routes_matching_tables_beyond_seed_documents(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does volumetric energy density affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["density"],
            "seed_document_ids": ["paper-seed"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-seed-density",
                document_id="paper-seed",
                caption_text="Density results for the seed paper.",
                column_headers=("VED [J/mm3]", "Density [%]"),
                table_matrix=(("L-VED", "91.9"),),
            ),
            SimpleNamespace(
                table_id="tbl-independent-density",
                document_id="paper-independent",
                caption_text="Independent density results at different VEDs.",
                column_headers=("VED [J/mm3]", "Density [%]"),
                table_matrix=(("L-VED", "91.90"), ("H-VED", "99.60")),
            ),
        ),
    )

    assert {
        (hint.document_id, hint.table_id, hint.role)
        for hint in hints
    } == {
        ("paper-seed", "tbl-seed-density", "result_table"),
        (
            "paper-independent",
            "tbl-independent-density",
            "result_table",
        ),
    }


def test_real_ved_process_and_defect_tables_form_joint_comparison(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-defect",
            "question": "How does volumetric energy density affect defect structure?",
            "variables": ["volumetric energy density"],
            "outcomes": ["defect structure"],
        }
    )
    process_table = SimpleNamespace(
        table_id="table-2",
        document_id="paper-ved",
        caption_text="Table 2 Fabrication parameters for 316L samples with varying VED.",
        heading_path="Materials and methods",
        page=4,
        column_headers=(
            "ID",
            "VED [J/mm 3 ]",
            "Laser power [W]",
            "Scanning speed [mm/s]",
            "Hatch spacing [ μ m]",
            "Layer thickness [ μ m]",
        ),
        table_matrix=(
            (
                "ID",
                "VED [J/mm 3 ]",
                "Laser power [W]",
                "Scanning speed [mm/s]",
                "Hatch spacing [ μ m]",
                "Layer thickness [ μ m]",
            ),
            ("L-VED", "50.8", "160", "875", "120", "30"),
            ("M-VED", "79.4", "190", "800", "100", "30"),
            ("H-VED", "84.3", "220", "725", "120", "30"),
        ),
        row_count=4,
        col_count=6,
    )
    result_table = SimpleNamespace(
        table_id="table-5",
        document_id="paper-ved",
        caption_text=(
            "Table 5 Fatigue and maximum defect measurements for 316L "
            "structures printed at different VEDs."
        ),
        heading_path="Results",
        page=10,
        column_headers=(
            "Printed 316L",
            "UTS [MPa]",
            "FAT50 % [MPa]",
            "FAT/ UTS -",
            "FAT at 10 4 cycles [MPa]",
            "Max. Defect length (LCSM) [ μ m]",
        ),
        table_matrix=(
            (
                "Printed 316L",
                "UTS [MPa]",
                "FAT50 % [MPa]",
                "FAT/ UTS -",
                "FAT at 10 4 cycles [MPa]",
                "Max. Defect length (LCSM) [ μ m]",
            ),
            ("L-VED", "610 ± 6", "93", "0.15", "340", "394"),
            ("M-VED", "595 ± 13", "82", "0.14", "450", "179"),
            ("H-VED", "560 ± 4", "97", "0.17", "470", "86"),
        ),
        row_count=4,
        col_count=6,
    )
    tables = (process_table, result_table)

    hints = service._build_objective_table_routing_hints(objective, tables=tables)

    assert {(hint.table_id, hint.role) for hint in hints} == {
        ("table-2", "condition_context"),
        ("table-5", "result_table"),
    }

    routes: list[EvidenceCandidate] = []
    service._append_objective_context_hint_routes(
        routes=routes,
        seen=set(),
        frame=PaperAnalysisFrame.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-ved",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "relevant_tables": ["table-2", "table-5"],
            }
        ),
        objective_context=objective,
        routing_hints=hints,
        candidate_by_key={
            ("table", table.table_id): {
                "source_kind": "table",
                "source_ref": table.table_id,
                "frame_status": "relevant",
                "table_schema": service._build_route_table_schema(table),
            }
            for table in tables
        },
    )
    units = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for route in routes
        for record in service._objective_table_matrix_evidence_records(
            route=route,
            source=service._build_objective_route_source_payload(
                route=route,
                blocks=[],
                tables=list(tables),
            ),
            objective_context=objective,
        )
    )
    comparisons = service._build_objective_pairwise_comparison_units(
        service._bind_objective_result_process_context(units),
        objectives=(objective,),
    )
    low_to_high = next(
        comparison
        for comparison in comparisons
        if comparison.comparison is not None
        and comparison.comparison.baseline_label == "l-ved"
        and comparison.comparison.target_label == "h-ved"
    )

    assert low_to_high.attribution_scope == "joint_effect"
    assert {
        property_matching.normalize_property_label(item.name)
        for item in low_to_high.changed_variables
    } == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }
    assert {ref["source_ref"] for ref in low_to_high.source_refs} == {
        "table-2",
        "table-5",
    }


def test_objective_densification_outcome_includes_relative_density_evidence(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does energy density affect densification?",
            "variables": ["energy density"],
            "outcomes": ["densification"],
        }
    )

    target_axes = property_matching.objective_outcomes(objective)

    assert target_axes == ("densification", "relative density")
    assert property_matching.property_matches_target_axes(
        "relative density",
        target_axes=target_axes,
    )


def test_real_p001_density_table_retains_complete_changed_factor_tuple(tmp_path):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-p001-density",
            "question": "How does energy density affect densification?",
            "variables": ["energy density"],
            "outcomes": ["densification"],
        }
    )
    table = SimpleNamespace(
        table_id="table-p001-1",
        document_id="paper-p001",
        caption_text="SLM processing parameters along with relative densities.",
        heading_path="Materials and methods",
        page=2,
        column_headers=(
            "Condition number",
            "Sample number",
            "Hatch space (mm)",
            "Scan strategy",
            "Scanning speed (mm/s)",
            "Energy density (J/mm 3 )",
            "Relative density",
        ),
        table_matrix=(
            (
                "Condition number",
                "Sample number",
                "Hatch space (mm)",
                "Scan strategy",
                "Scanning speed (mm/s)",
                "Energy density (J/mm 3 )",
                "Relative density",
            ),
            ("1", "1", "0.114", "A", "0.25", "70", "95.4"),
            ("3", "6", "0.111", "B", "0.12", "150", "95.7"),
        ),
        row_count=3,
        col_count=7,
    )
    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(table,),
    )
    routes: list[EvidenceCandidate] = []
    service._append_objective_context_hint_routes(
        routes=routes,
        seen=set(),
        frame=PaperAnalysisFrame.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-p001",
                "relevance": "high",
                "paper_role": "primary_experiment",
                "relevant_tables": [table.table_id],
            }
        ),
        objective_context=objective,
        routing_hints=hints,
        candidate_by_key={
            ("table", table.table_id): {
                "source_kind": "table",
                "source_ref": table.table_id,
                "frame_status": "relevant",
                "table_schema": service._build_route_table_schema(table),
            }
        },
    )
    units = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for route in routes
        for record in service._objective_table_matrix_evidence_records(
            route=route,
            source=service._build_objective_route_source_payload(
                route=route,
                blocks=[],
                tables=[table],
            ),
            objective_context=objective,
        )
    )
    comparisons = service._build_objective_pairwise_comparison_units(
        service._bind_objective_result_process_context(units),
        objectives=(objective,),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.attribution_scope == "joint_effect"
    assert {
        property_matching.normalize_property_label(item.name)
        for item in comparison.changed_variables
    } == {
        "hatch space",
        "scan strategy",
        "scanning speed",
        "energy density",
    }


def test_research_objective_service_does_not_route_single_letter_acronym_tables(
    tmp_path,
):
    service = _build_research_objective_service(
        collection_service=build_test_collection_service(tmp_path / "collections"),
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scan speed"],
            "outcomes": ["density"],
        }
    )

    hints = service._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-composition",
                document_id="paper-1",
                caption_text="Chemical composition of SS316L powder.",
                column_headers=("C", "Cr", "Ni", "P", "S", "Fe"),
                table_matrix=(("0.02", "16.7", "11.9", "0.01", "0.02", "Bal."),),
            ),
            SimpleNamespace(
                table_id="tbl-polarization",
                document_id="paper-1",
                caption_text="Electrochemical polarization parameters.",
                column_headers=("Sample", "E corr", "E d", "E p"),
                table_matrix=(("sample-1", "-312.9", "-208.0", "124.7"),),
            ),
        ),
    )

    assert hints == ()
