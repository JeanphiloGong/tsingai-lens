from __future__ import annotations

from types import SimpleNamespace

from application.core.objectives import property_matching
from application.core.objectives.analysis import (
    evidence_routing,
    source_extraction,
    source_screening,
)
from application.core.objectives.analysis.evidence_routing import (
    EvidenceCandidate,
    SourceSelectionHint,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import PaperSkim
from domain.source import SourceDocumentNode, SourceDocumentTree
from tests.support.objective_extractor import (
    FakeObjectiveExtractor as _ObjectiveExtractor,
)
from tests.support.research_objective_service import (
    research_objective as _research_objective,
)


def test_objective_evidence_route_prompt_uses_response_schema_field_name():
    system_prompt, user_prompt = (
        evidence_routing.build_objective_evidence_route_prompt(
            {
                "objective": {
                    "question": "How does scan strategy affect residual stress?",
                },
                "current_source": {
                    "source_kind": "text_window",
                    "text": "Residual stress depends on the selected scan strategy.",
                },
            }
        )
    )

    for prompt in (system_prompt, user_prompt):
        assert "`selections`" in prompt
        assert '{"selections": []}' in prompt
        assert "`routes`" not in prompt
        assert '{"routes": []}' not in prompt


def test_research_objective_service_forces_extractable_objective_route_roles():

    assert evidence_routing._normalize_route_extractable(
        {"role": "current_experimental_evidence", "extractable": False}
    )
    assert evidence_routing._normalize_route_extractable(
        {"role": "process_or_treatment", "extractable": False}
    )
    assert not evidence_routing._normalize_route_extractable(
        {"role": "low_value_or_irrelevant", "extractable": True}
    )
    assert not evidence_routing._normalize_route_extractable(
        {"role": "literature_comparison", "extractable": False}
    )


def test_research_objective_service_forces_direct_support_route_role():

    record = evidence_routing._apply_route_evidence_role(
        record={
            "role": "low_value_or_irrelevant",
            "extractable": False,
        },
        evidence_role="direct_support",
    )

    assert record["role"] == "current_experimental_evidence"
    assert record["extractable"] is True
    assert record["join_plan"] == {"evidence_role": "direct_support"}


def test_review_citation_result_is_not_routed_as_primary_evidence() -> None:
    class UnexpectedRouter:
        def route_source(self, payload):  # noqa: ANN001, ARG002
            raise AssertionError("review citations must not reach primary routing")

    objective = _research_objective(
        {
            "objective_id": "obj-ti64-porosity",
            "question": "How does scanning strategy affect porosity?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser exposure condition"],
            "outcomes": ["porosity"],
        }
    )
    source_ref = "block-review-17-4ph"
    source_unit = {
        "source_unit_id": "review-results-unit",
        "source_kind": "section",
        "source_ref": source_ref,
        "section_label": "Effect of scanning strategy",
        "text": (
            "Rashid et al. studied two scanning strategies for 17-4PH "
            "stainless steel."
        ),
    }
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-scanning-review",
            "doc_role": "review",
            "studies": [],
            "evidence_density": "medium",
            "confidence": 0.9,
        }
    )
    frame = source_screening._aggregate_objective_paper_frame_batches(
        objective_id=objective.objective_id,
        document_id=paper_skim.document_id,
        source_units=(source_unit,),
        batch_results=(
            (
                {
                    "relevance": "medium",
                    "paper_role": "primary_experiment",
                    "material_match": ["Ti-6Al-4V"],
                    "changed_variables": ["scanning strategy"],
                    "measured_property_scope": ["porosity"],
                    "relevant_source_unit_ids": [source_unit["source_unit_id"]],
                    "excluded_source_unit_ids": [],
                },
                "model",
                (),
            ),
        ),
        paper_skim=paper_skim,
    )
    assert frame.paper_role == "review"
    review_block = SimpleNamespace(
        block_id=source_ref,
        block_order=116,
        block_type="paragraph",
        heading_path="Effect of scanning strategy",
        text=(
            "Rashid et al. studied two scanning strategies for 17-4PH "
            "stainless steel. The part made by Scan X had smaller porosity "
            "than the part made by Scan O."
        ),
    )

    routes = evidence_routing.route_sources(
        collection_id="collection-review",
        evidence_router=UnexpectedRouter(),
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={frame.document_id: [review_block]},
        tables_by_document_id={frame.document_id: []},
        document_trees_by_document_id={},
    )

    assert routes == ()


def test_research_objective_service_treats_energy_density_only_table_as_condition():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How do laser power and scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power", "scan speed"],
            "outcomes": ["density"],
        }
    )

    hints = evidence_routing._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-process",
                document_id="paper-1",
                caption_text="SLM process parameters.",
                column_headers=(
                    "Laser power [W]",
                    "Scan speed [mm/s]",
                    "Energy density [J/mm3]",
                ),
                table_matrix=(("375", "2100", "100"),),
            ),
        ),
    )

    assert len(hints) == 1
    assert hints[0].role == "condition_context"
    assert hints[0].matched_outcomes == ()


def test_research_objective_service_normalizes_archimedes_density_column():
    objective_context = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does volumetric energy density affect density?",
            "outcomes": ["density"],
        }
    )

    normalized = property_matching.normalize_objective_unit_property(
        "Density [%] > Archimedes ' method",
        objective_context=objective_context,
    )

    assert normalized == "density"


def test_research_objective_service_ignores_analysis_purpose_as_table_result():
    objective = _research_objective(
        {
            "objective_id": "obj-microstructure",
            "question": "How does heat treatment affect microstructure?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["microstructure"],
        }
    )

    hints = evidence_routing._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-sample-angles",
                document_id="paper-1",
                caption_text=(
                    "Scan strategy and build orientation of cubes for "
                    "microstructure analysis."
                ),
                column_headers=("Sample", "rotation angle", "build orientation"),
                table_matrix=(("1", "0", "0"), ("2", "15", "0")),
            ),
        ),
    )

    assert hints == ()


def test_research_objective_service_recovers_non_seed_condition_and_result_routes():
    objective = _research_objective(
        {
            "objective_id": "obj-mechanical",
            "question": "How do LPBF parameters affect tensile properties?",
            "material_scope": ["316L stainless steel"],
            "variables": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
            ],
            "outcomes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
            "seed_document_ids": ["paper-seed"],
        }
    )
    condition_table = SimpleNamespace(
        table_id="table-conditions",
        document_id="paper-independent",
        caption_text="Fabrication parameters for samples with varying VED.",
        heading_path="Materials and methods",
        column_headers=(
            "ID",
            "Volumetric energy density [J/mm3]",
            "Laser power [W]",
            "Scanning speed [mm/s]",
            "Hatch spacing [um]",
        ),
        row_count=3,
        col_count=5,
        table_matrix=(
            ("L-VED", "50.8", "160", "875", "120"),
            ("H-VED", "84.3", "220", "725", "120"),
        ),
    )
    result_table = SimpleNamespace(
        table_id="table-results",
        document_id="paper-independent",
        caption_text="Tensile properties for samples printed at different VEDs.",
        heading_path="Results",
        column_headers=(
            "Printed 316L",
            "Yield strength [MPa]",
            "Ultimate tensile strength [MPa]",
            "Total elongation [%]",
        ),
        row_count=3,
        col_count=4,
        table_matrix=(
            ("L-VED", "462", "610", "33.2"),
            ("H-VED", "437", "560", "48.3"),
        ),
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-independent",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": list(objective.variables),
            "measured_property_scope": list(objective.outcomes),
            "relevant_tables": [],
            "excluded_tables": ["table-conditions", "table-results"],
        }
    )

    routes = evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=_ObjectiveExtractor(),
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-independent": []},
        tables_by_document_id={
            "paper-independent": [condition_table, result_table]
        },
        document_trees_by_document_id={},
    )

    active_routes = {
        (route.source_ref, route.role)
        for route in routes
        if route.extractable
    }
    assert active_routes == {
        ("table-conditions", "process_or_treatment"),
        ("table-results", "current_experimental_evidence"),
    }


def test_research_objective_service_routes_pitting_corrosion_metric_tables_as_results():
    objective = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power and energy density affect pitting corrosion "
                "behavior of SLM 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power", "energy density"],
            "outcomes": ["pitting corrosion behavior"],
        }
    )

    hints = evidence_routing._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-electrochemical",
                document_id="paper-1",
                caption_text=(
                    "Table 3 Electrochemical parameters results obtained from "
                    "the polarization test"
                ),
                column_headers=(
                    "Sample",
                    "E corr (mV)",
                    "E d (mV)",
                    "E p (mV)",
                    "E p - E d (mV)",
                ),
                table_matrix=(
                    ("Sample", "E corr (mV)", "E p (mV)"),
                    ("375 W-2100 mm·s -1", "-312.9", "124.7"),
                ),
            ),
            SimpleNamespace(
                table_id="tbl-eis",
                document_id="paper-1",
                caption_text="Table 4 Fitted parameters obtained from the EIS plots",
                column_headers=("Sample", "R s (Ω cm 2 )", "R film (Ω cm 2 )"),
                table_matrix=(
                    ("Sample", "R s (Ω cm 2 )", "R film (Ω cm 2 )"),
                    ("135 W-750 mm·s -1", "5.21", "1.90×10 5"),
                ),
            ),
        ),
    )

    assert {
        (hint.table_id, hint.role, hint.matched_outcomes)
        for hint in hints
    } == {
        ("tbl-electrochemical", "result_table", ("pitting corrosion behavior",)),
        ("tbl-eis", "result_table", ("pitting corrosion behavior",)),
    }


def test_research_objective_service_keeps_density_out_of_defect_structure_results():
    objective = _research_objective(
        {
            "objective_id": "obj-fatigue",
            "question": (
                "How does volumetric energy density affect defect structure and "
                "fatigue strength of LPBF 316L?"
            ),
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["defect structure", "fatigue strength"],
        }
    )

    hints = evidence_routing._build_objective_table_routing_hints(
        objective,
        tables=(
            SimpleNamespace(
                table_id="tbl-density",
                document_id="paper-1",
                caption_text="Table 1 SLM processing parameters and relative densities.",
                column_headers=("VED", "Relative density"),
                table_matrix=(
                    ("VED", "Relative density"),
                    ("50", "91.9"),
                    ("100", "98.9"),
                ),
            ),
        ),
    )

    assert all(hint.role != "result_table" for hint in hints)
    target_axes = property_matching.objective_outcomes(objective)
    assert property_matching.property_matches_target_axes(
        "maximum defect diameter",
        target_axes=target_axes,
    )
    assert not property_matching.property_matches_target_axes(
        "relative density",
        target_axes=target_axes,
    )


def test_research_objective_service_route_payload_uses_objective_contract():
    context = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion?",
            "outcomes": ["pitting potential"],
            "mechanisms": ["porosity"],
        }
    )

    payload = evidence_routing._route_prompt_objective_record(context)

    assert payload["outcomes"] == ["pitting potential"]
    assert payload["mechanisms"] == ["porosity"]
    assert "objective_evidence_lens" not in payload


def test_process_route_does_not_treat_result_columns_as_process_context():
    objective_context = _research_objective(
        {
            "objective_id": "obj-fatigue",
            "variables": [
                "volumetric energy density",
                "laser power",
                "scanning speed",
                "hatch spacing",
                "layer thickness",
            ],
            "outcomes": ["defect structure", "fatigue strength"],
        }
    )
    misrouted_result_table = EvidenceCandidate.from_mapping(
        {
            "source_ref": "route-misclassified-results",
            "objective_id": "obj-fatigue",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-melt-pool-density",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Grain Size [um] > Eq. diam.": "statistical_measure",
            },
            "confidence": 0.84,
        }
    )

    records = source_extraction._objective_table_matrix_evidence_records(
        route=misrouted_result_table,
        source={
            "page": 5,
            "column_headers": [
                "ID",
                "Melt Pool Size [um] > Width",
                "Grain Size [um] > Eq. diam.",
                "Density [%] > Archimedes method",
            ],
            "table_matrix": [
                [
                    "ID",
                    "Melt Pool Size [um] > Width",
                    "Grain Size [um] > Eq. diam.",
                    "Density [%] > Archimedes method",
                ],
                ["L-VED", "148", "81", "91.90"],
            ],
        },
        objective_context=objective_context,
    )

    assert records == ()


def test_research_objective_service_adds_context_hint_route_for_condition_table():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_tables": ["table-2"],
            "excluded_tables": ["table-1"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-mechanical",
            "question": "How do processing parameters affect yield strength?",
            "variables": [
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    routes: list[EvidenceCandidate] = []

    evidence_routing._append_objective_context_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective_context,
        routing_hints=(
            SourceSelectionHint.from_mapping(
                {
                    "document_id": "paper-1",
                    "table_id": "table-1",
                    "role": "condition_context",
                    "reason": "Table contains process variables.",
                }
            ),
        ),
        candidate_by_key={
            ("table", "table-1"): {
                "source_kind": "table",
                "source_ref": "table-1",
                "frame_status": "excluded",
                "table_schema": {
                    "column_headers": [
                        "Condition number",
                        "Sample number",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                        "Energy density (J/mm 3 )",
                        "Relative density",
                    ],
                },
            }
        },
    )

    assert len(routes) == 1
    route = routes[0]
    assert route.role == "process_or_treatment"
    assert route.extractable is True
    assert route.source_ref == "table-1"
    assert route.column_roles == {
        "Condition number": "sample_condition",
        "Sample number": "sample_id",
        "Scan strategy": "process_variable",
        "Scanning speed (mm/s)": "process_variable",
        "Energy density (J/mm 3 )": "process_variable",
    }


def test_research_objective_service_ranks_result_text_candidates():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-structure",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["scanning speed", "energy density"],
            "measured_property_scope": ["microstructure", "densification"],
            "relevant_sections": ["Paper title"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-structure",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning speed", "energy density"],
            "outcomes": ["microstructure", "densification"],
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="intro",
            block_order=1,
            block_type="paragraph",
            heading_path="Paper title",
            text="Prior work studied 316L stainless steel processing.",
        ),
        SimpleNamespace(
            block_id="microstructure-results",
            block_order=100,
            block_type="paragraph",
            heading_path="3.3. Microstructure",
            text=(
                "The higher scanning speed samples showed refined "
                "microstructure and better densification."
            ),
        ),
        SimpleNamespace(
            block_id="page-number",
            block_order=101,
            block_type="paragraph",
            heading_path="3.3. Thermal Simulation and Microstructure",
            text="418",
        ),
        SimpleNamespace(
            block_id="conclusion",
            block_order=120,
            block_type="list_item",
            heading_path="4. Conclusion",
            text=(
                "Samples processed at higher scanning speed exhibited better "
                "densification and refined microstructure."
            ),
        ),
    ]

    candidates = evidence_routing._build_route_source_candidates(
        frame=frame,
        objective_context=objective_context,
        blocks=blocks,
        tables=[],
    )

    candidate_refs = [candidate["source_ref"] for candidate in candidates]
    assert set(candidate_refs[:2]) == {"microstructure-results", "conclusion"}
    assert "intro" not in candidate_refs
    assert "page-number" not in candidate_refs

    routes: list[EvidenceCandidate] = []
    evidence_routing._append_ranked_text_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective_context,
        source_candidates=candidates,
    )

    assert [route.source_ref for route in routes] == [
        "conclusion",
        "microstructure-results",
    ]
    assert {route.role for route in routes} == {"characterization"}
    assert {route.join_plan["evidence_role"] for route in routes} == {
        "direct_support"
    }


def test_research_objective_text_hints_prefer_observed_result_over_scope_summary():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "changed_variables": ["preheating build platform temperature"],
            "measured_property_scope": ["microstructure"],
        }
    )
    objective = _research_objective(
        {
            "objective_id": "obj-preheat",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    candidates = [
        {
            "source_kind": "text_window",
            "source_ref": "scope-summary",
            "section_label": "Conclusions",
            "block_type": "paragraph",
            "text": (
                "The effect of preheating on microstructure was investigated. "
                "The following conclusions can be drawn."
            ),
        },
        {
            "source_kind": "text_window",
            "source_ref": "direct-result",
            "section_label": "Conclusions",
            "block_type": "list_item",
            "text": (
                "The cooling rate of P150 decreased compared with NP and "
                "resulted in formation of equiaxed cellular microstructure."
            ),
        },
        {
            "source_kind": "text_window",
            "source_ref": "detailed-result",
            "section_label": "Results and microstructure",
            "block_type": "paragraph",
            "text": (
                "Comparing P150 with NP, an equiaxed cellular microstructure "
                "was observed in P150."
            ),
        },
        {
            "source_kind": "text_window",
            "source_ref": "background",
            "section_label": "Abstract",
            "block_type": "paragraph",
            "text": "The study aims to analyze preheating and microstructure.",
        },
    ]
    routes: list[EvidenceCandidate] = []

    evidence_routing._append_ranked_text_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective,
        source_candidates=candidates,
    )

    assert [route.source_ref for route in routes[:2]] == [
        "direct-result",
        "detailed-result",
    ]
    assert routes[-1].source_ref == "scope-summary"


def test_research_objective_service_text_hint_keeps_mediator_out_of_direct_support():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["laser power"],
            "measured_property_scope": ["pitting corrosion"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-corrosion",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "constraints": ["SLM"],
            "outcomes": ["pitting potential"],
            "mechanisms": ["porosity", "pore size", "lack of fusion"],
        }
    )
    candidates = [
        {
            "source_kind": "text_window",
            "source_ref": "lof-defects",
            "section_label": "3. Results",
            "block_type": "paragraph",
            "text": (
                "Lack of fusion defects were observed at melt pool boundaries "
                "with irregular pore morphology."
            ),
        },
        {
            "source_kind": "text_window",
            "source_ref": "pitting-result",
            "section_label": "4. Conclusion",
            "block_type": "paragraph",
            "text": (
                "The pitting potential increased when porosity decreased, "
                "indicating improved pitting corrosion resistance."
            ),
        },
    ]
    routes: list[EvidenceCandidate] = []

    evidence_routing._append_ranked_text_hint_routes(
        routes=routes,
        seen=set(),
        frame=frame,
        objective_context=objective_context,
        source_candidates=candidates,
    )

    route_by_ref = {route.source_ref: route for route in routes}
    assert route_by_ref["lof-defects"].join_plan["evidence_role"] == "mediator_context"
    assert route_by_ref["lof-defects"].role == "characterization"
    assert route_by_ref["lof-defects"].extractable is False
    assert route_by_ref["pitting-result"].join_plan["evidence_role"] == "direct_support"
    assert route_by_ref["pitting-result"].extractable is True


def test_research_objective_routing_uses_document_tree_order():
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
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="results",
            block_order=1,
            block_type="paragraph",
            heading_path="Results",
            text="The yield strength result showed 900 MPa after heat treatment.",
        ),
        SimpleNamespace(
            block_id="methods",
            block_order=100,
            block_type="paragraph",
            heading_path="Methods",
            text="The 316L samples used heat treatment at 650 C for 4 h.",
        ),
    ]
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("methods-section", "results-section"),
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
                source_ref_id="methods",
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "methods",
        "results",
    ]
    assert extractor.route_payloads[0]["tree_position"]["section_path"] == ["Methods"]
    assert extractor.route_payloads[1]["tree_position"]["section_path"] == ["Results"]


def test_research_objective_routing_binds_current_source_to_model_decision():
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
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
            "relevant_tables": ["table-1"],
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        caption_text="Yield strength results after heat treatment.",
        heading_path="Results",
        columns=("condition", "yield strength"),
        rows=(("HT", "900 MPa"),),
    )
    extractor = _ObjectiveExtractor()

    routes = evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    assert len(extractor.route_payloads) == 1
    assert extractor.route_payloads[0]["current_source"]["source_ref"] == "table-1"
    assert {
        (route.source_kind, route.source_ref, route.role)
        for route in routes
    } == {
        ("table", "table-1", "current_experimental_evidence"),
        ("table", "table-1", "process_or_treatment"),
    }
    result_route = next(
        route for route in routes if route.role == "current_experimental_evidence"
    )
    assert result_route.join_plan["evidence_role"] == "direct_support"


def test_research_objective_routing_uses_compact_prompt_payload():
    objective = _research_objective(
        {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment"],
            "outcomes": ["yield strength"],
            "requested_comparator": "compare treated and untreated samples",
            "confidence": 0.9,
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-heat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "screening_note": "x" * 1000,
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
            "relevant_sections": ["Results"],
            "relevant_tables": ["table-1"],
            "excluded_tables": ["table-2"],
        }
    )
    table = SimpleNamespace(
        table_id="table-1",
        caption_text="Yield strength results after heat treatment.",
        heading_path="Results",
        columns=("condition", "yield strength"),
        column_headers=["condition", "yield strength"],
        row_count=200,
        col_count=10,
        table_matrix=[["condition", "yield strength"], *[["HT", "900 MPa"]] * 20],
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    route_payload = extractor.route_payloads[0]
    assert "routing_hints" not in route_payload["objective"]
    assert "extraction_guidance" not in route_payload["objective"]
    assert "objective_context" not in route_payload
    assert "screening_note" not in route_payload["paper_frame"]
    assert "relevant_tables" not in route_payload["paper_frame"]
    assert "excluded_tables" not in route_payload["paper_frame"]
    assert "table_schema" not in route_payload["current_source"]
    assert "sample_rows" not in route_payload["current_source"]
    assert route_payload["current_source"]["column_headers"] == [
        "condition",
        "yield strength",
    ]
    assert route_payload["current_source"]["row_count"] == 200


def test_research_objective_routing_uses_text_hint_not_source_text():
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
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    long_text = "Heat treatment changed yield strength. " + ("x" * 1000)
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("results-node",),
                node_type="document",
                order=0,
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="root",
                child_ids=(),
                node_type="paragraph",
                order=100,
                text=long_text,
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    current_source = extractor.route_payloads[0]["current_source"]
    assert "text" not in current_source
    assert current_source["text_hint"] == long_text[:320]
    assert len(current_source["text_hint"]) == 320


def test_research_objective_routing_builds_text_candidates_from_document_tree():
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
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
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
                child_ids=("methods-section", "results-section", "refs-section"),
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
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                text="The yield strength result showed 900 MPa after heat treatment.",
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
            "refs-section": SourceDocumentNode(
                node_id="refs-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("reference-node",),
                node_type="references_section",
                order=300,
                title="References",
                heading_path=("References",),
            ),
            "reference-node": SourceDocumentNode(
                node_id="reference-node",
                document_id="paper-1",
                parent_id="refs-section",
                child_ids=(),
                node_type="paragraph",
                order=310,
                text="A reference also mentions yield strength after heat treatment.",
                heading_path=("References",),
                source_ref_kind="block",
                source_ref_id="reference",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "methods",
        "results",
    ]
    assert "reference" not in {
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    }


def test_research_objective_low_relevance_tree_routing_uses_frame_sections():
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
            "relevance": "low",
            "paper_role": "supporting_background",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
            "relevant_sections": ["Results"],
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
                child_ids=("methods-section", "results-section"),
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
            ),
            "results-section": SourceDocumentNode(
                node_id="results-section",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-node",),
                node_type="section",
                order=200,
                title="Results",
                heading_path=("Results",),
            ),
            "results-node": SourceDocumentNode(
                node_id="results-node",
                document_id="paper-1",
                parent_id="results-section",
                child_ids=(),
                node_type="paragraph",
                order=210,
                text="The yield strength result showed 900 MPa after heat treatment.",
                heading_path=("Results",),
                source_ref_kind="block",
                source_ref_id="results",
            ),
        },
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [payload["current_source"]["source_ref"] for payload in extractor.route_payloads] == [
        "results",
    ]


def test_research_objective_low_relevance_tree_routing_limits_unsectioned_text():
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
            "relevance": "low",
            "paper_role": "supporting_background",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    child_ids = tuple(f"node-{index}" for index in range(30))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=child_ids,
            node_type="document",
            order=0,
        )
    }
    for index, node_id in enumerate(child_ids):
        nodes[node_id] = SourceDocumentNode(
            node_id=node_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(),
            node_type="paragraph",
            order=100 + index,
            text=(
                f"S{index} 316L samples used heat treatment and reported "
                f"yield strength result {800 + index} MPa."
            ),
            heading_path=("Results",),
            source_ref_kind="block",
            source_ref_id=f"block-{index}",
        )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    routed_refs = [
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    ]
    assert len(routed_refs) == 8
    assert routed_refs == [f"block-{index}" for index in range(8)]


def test_research_objective_tree_routing_keeps_late_document_nodes():
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
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment"],
            "measured_property_scope": ["yield strength"],
        }
    )
    child_ids = tuple(f"node-{index}" for index in range(45))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=child_ids,
            node_type="document",
            order=0,
        )
    }
    for index, node_id in enumerate(child_ids):
        nodes[node_id] = SourceDocumentNode(
            node_id=node_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(),
            node_type="paragraph",
            order=100 + index,
            text=(
                f"S{index} 316L samples used heat treatment and reported "
                f"yield strength result {800 + index} MPa."
            ),
            heading_path=("Results",),
            source_ref_kind="block",
            source_ref_id=f"block-{index}",
        )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    routed_refs = [
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    ]
    assert len(routed_refs) == 8
    assert routed_refs[-1] == "block-44"
    assert routed_refs == sorted(
        routed_refs,
        key=lambda ref: int(ref.replace("block-", "")),
    )


def test_research_objective_tree_routing_uses_confirmed_objective_axes():
    objective = _research_objective(
        {
            "objective_id": "obj-preheat-cracking",
            "question": (
                "How does base plate preheating temperature affect crack formation?"
            ),
            "variables": ["base plate preheating temperature"],
            "outcomes": ["crack formation"],
            "confirmation_status": "confirmed",
        }
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-preheat-cracking",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "changed_variables": ["laser power"],
            "measured_property_scope": ["porosity"],
        }
    )
    child_ids = tuple(f"node-{index}" for index in range(30))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=child_ids,
            node_type="document",
            order=0,
        )
    }
    for index, node_id in enumerate(child_ids):
        source_ref = f"noise-{index}"
        text = (
            "Laser power affected porosity and showed a measured result for "
            f"condition {index}."
        )
        if index == 7:
            source_ref = "preheating-crack-result"
            text = (
                "Although the application of preheating largely reduces this "
                "cracking behavior, it fails to completely prevent microcrack "
                "formation after preheating at 400 C."
            )
        nodes[node_id] = SourceDocumentNode(
            node_id=node_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(),
            node_type="paragraph",
            order=100 + index,
            text=text,
            heading_path=("Results",),
            source_ref_kind="block",
            source_ref_id=source_ref,
        )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )
    extractor = _ObjectiveExtractor()

    evidence_routing.route_sources(
        collection_id="col-test",
        evidence_router=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": []},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert "preheating-crack-result" in {
        payload["current_source"]["source_ref"]
        for payload in extractor.route_payloads
    }


def test_research_objective_tree_routing_keeps_direct_result_among_scope_text():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["preheating build platform temperature"],
            "measured_property_scope": ["microstructure"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-preheat",
            "material_scope": ["316L stainless steel"],
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    child_ids = tuple(f"node-{index}" for index in range(17))
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=child_ids,
            node_type="document",
            order=0,
        )
    }
    for index, node_id in enumerate(child_ids):
        text = (
            "The 316L stainless steel study investigated preheating build "
            "platform temperature and microstructure in fabricated and "
            "processed specimens."
        )
        if index == 7:
            text = (
                "Comparing the microstructure obtained for P150 with NP, the "
                "cellular structure was observed after preheating the build "
                "platform because of the lower temperature gradient."
            )
        nodes[node_id] = SourceDocumentNode(
            node_id=node_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(),
            node_type="paragraph",
            order=100 + index,
            text=text,
            heading_path=(f"Section {index}",),
            source_ref_kind="block",
            source_ref_id=("direct-result" if index == 7 else f"scope-{index}"),
        )
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )

    candidates = evidence_routing._build_tree_route_text_candidates(
        frame=frame,
        objective_context=objective_context,
        blocks=[],
        document_tree=document_tree,
    )

    assert len(candidates) == 8
    assert "direct-result" in {
        candidate["source_ref"] for candidate in candidates
    }


def test_research_objective_tree_routing_recognizes_preheating_crack_results():
    objective_context = _research_objective(
        {
            "objective_id": "obj-preheat-cracking",
            "variables": ["base plate preheating temperature"],
            "outcomes": ["crack formation"],
        }
    )

    direct_results = (
        (
            "Although the application of preheating largely reduces this cracking "
            "behavior, it fails to completely prevent microcrack formation after "
            "preheating at 400 C."
        ),
        (
            "Preheating up to 400 C does not have a significant effect on "
            "Hastelloy X crack formation."
        ),
    )

    assert all(
        evidence_routing._route_text_candidate_is_direct_result(
            objective_context=objective_context,
            candidate={"text": text},
        )
        for text in direct_results
    )
    assert not evidence_routing._route_text_candidate_is_direct_result(
        objective_context=objective_context,
        candidate={
            "text": (
                "Crack formation was characterized for all four materials in "
                "the experimental program."
            )
        },
    )


def test_research_objective_tree_routing_recognizes_energy_input_ductility_result():
    objective_context = _research_objective(
        {
            "objective_id": "obj-energy-ductility",
            "variables": ["energy input"],
            "outcomes": ["ductility"],
        }
    )

    direct_results = (
        (
            "The increases in input energy including laser power and input "
            "current lead to the reduction in tensile strength while enhancing "
            "the elongation from 14.2% to 20.1%."
        ),
        (
            "Increasing laser power enhanced elongation from 15.4% to 20.1% in "
            "the Ti-6Al-4V samples."
        ),
    )

    assert all(
        evidence_routing._route_text_candidate_is_direct_result(
            objective_context=objective_context,
            candidate={"text": text},
        )
        for text in direct_results
    )


def test_research_objective_tree_routing_excludes_non_block_caption_refs():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "changed_variables": ["energy density"],
            "measured_property_scope": ["relative density"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["energy density"],
            "outcomes": ["relative density"],
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
                child_ids=("figure-caption",),
                node_type="document",
                order=0,
            ),
            "figure-caption": SourceDocumentNode(
                node_id="figure-caption",
                document_id="paper-1",
                parent_id="root",
                child_ids=(),
                node_type="caption",
                order=100,
                text=(
                    "Relative density increased when energy density changed from "
                    "70 to 150 J/mm3."
                ),
                source_ref_kind="figure",
                source_ref_id="figure-1",
            ),
        },
    )

    candidates = evidence_routing._build_tree_route_text_candidates(
        frame=frame,
        objective_context=objective_context,
        blocks=[],
        document_tree=document_tree,
    )

    assert candidates == []


def test_research_objective_tree_routing_keeps_multiple_comparative_results():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "changed_variables": ["preheating build platform temperature"],
            "measured_property_scope": ["microstructure"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-preheat",
            "variables": ["preheating build platform temperature"],
            "outcomes": ["microstructure"],
        }
    )
    generic_candidates = [
        (
            -20,
            index,
            {
                "source_kind": "text_window",
                "source_ref": f"scope-{index}",
                "section_label": "Conclusions and future study",
                "text": (
                    "The study investigated preheating build platform temperature "
                    "and microstructure in 316L stainless steel."
                ),
            },
        )
        for index in range(20)
    ]
    comparative_candidates = [
        (
            -8,
            10,
            {
                "source_kind": "text_window",
                "source_ref": "detailed-result",
                "section_label": "Thermal Simulation and Microstructure",
                "text": (
                    "Comparing the microstructure obtained for P150 with NP, "
                    "cellular structure was observed in P150."
                ),
            },
        ),
        (
            -7,
            11,
            {
                "source_kind": "text_window",
                "source_ref": "conclusion-result",
                "section_label": "Conclusions and future study",
                "text": (
                    "The cooling rate of P150 decreased compared to NP and "
                    "resulted in formation of equiaxed cellular structure."
                ),
            },
        ),
    ]

    selected = evidence_routing._bounded_tree_route_text_candidates(
        frame=frame,
        objective_context=objective_context,
        scored_candidates=[*generic_candidates, *comparative_candidates],
    )

    selected_refs = {item[2]["source_ref"] for item in selected}
    assert {"detailed-result", "conclusion-result"} <= selected_refs


def test_research_objective_service_keeps_numeric_mechanism_text_candidates():
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "obj-preheating",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["build platform temperature"],
            "measured_property_scope": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "porosity",
            ],
            "test_environment_scope": ["preheating"],
            "relevant_sections": ["Abstract"],
        }
    )
    objective_context = _research_objective(
        {
            "objective_id": "obj-preheating",
            "material_scope": ["316L stainless steel"],
            "variables": ["build platform temperature"],
            "outcomes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "porosity",
            ],
        }
    )
    blocks = [
        SimpleNamespace(
            block_id="cooling-rate",
            block_order=86,
            block_type="paragraph",
            heading_path="Thermal Simulation and Microstructure",
            text=(
                "The cooling rate values were obtained from the simulation "
                "to be 1.43x10 6 C/s for P150, and 1.65x10 6 C/s for "
                "the NP condition."
            ),
        ),
        SimpleNamespace(
            block_id="melt-pool-ratio",
            block_order=87,
            block_type="paragraph",
            heading_path="Thermal Simulation and Microstructure",
            text=(
                "The average width to depth ratios of the melt pool are "
                "calculated for NP and P150 conditions to be 1.38 and 1.7, "
                "respectively."
            ),
        ),
        SimpleNamespace(
            block_id="residual-stress",
            block_order=88,
            block_type="paragraph",
            heading_path="3.1. X-ray diffraction and residual stress",
            text=(
                "The HT-SLM (i.e., 17.8 MPa) and HIP-SLM (i.e., 27.5 MPa) "
                "showed comparable residual stress values, whereas the "
                "as-SLM residual stress was found to be 99.5 MPa."
            ),
        ),
    ]

    candidates = evidence_routing._build_route_source_candidates(
        frame=frame,
        objective_context=objective_context,
        blocks=blocks,
        tables=[],
    )

    assert {candidate["source_ref"] for candidate in candidates} == {
        "cooling-rate",
        "melt-pool-ratio",
        "residual-stress",
    }
