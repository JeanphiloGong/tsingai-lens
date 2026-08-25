from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any

import pytest
from application.core.objectives import property_matching
from application.core.objectives.analysis import (
    evidence_materialization,
    evidence_routing,
    paper_experiment,
    source_extraction,
    source_screening,
    source_validation,
)
from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
    StructuredEvidenceExtractions,
    extract_and_validate_source_facts,
)
from application.core.objectives.analysis.source_screening import (
    OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT,
    PaperAnalysisFrame,
    StructuredPaperFrameBatch,
)
from application.core.paper_facts.schemas import StructuredTableMatrixRepair
from domain.core import ObjectiveAnalysis, PaperSkim
from domain.source import SourceDocumentNode, SourceDocumentTree, SourceTable
from httpx import Request, Response
from openai import BadRequestError
from tests.support.research_objective_service import (
    research_objective as _research_objective,
)


class _BoundedFrameExtractor:
    def __init__(
        self,
        *,
        max_source_units: int,
        records_by_source_ref: dict[str, dict[str, Any]] | None = None,
        failing_source_refs: set[str] | None = None,
    ) -> None:
        self.max_source_units = max_source_units
        self.records_by_source_ref = records_by_source_ref or {}
        self.failing_source_refs = failing_source_refs or set()
        self.frame_payloads: list[dict[str, Any]] = []

    def estimate_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        return (
            20_000
            if len(payload.get("source_units") or ()) > self.max_source_units
            else 1_000
        )

    def screen_batch(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperFrameBatch:
        assert (
            self.estimate_prompt_tokens(payload)
            <= OBJECTIVE_PAPER_FRAME_PROMPT_TOKEN_LIMIT
        )
        self.frame_payloads.append(payload)
        source_units = payload["source_units"]
        source_refs = {str(unit["source_ref"]) for unit in source_units}
        if source_refs & self.failing_source_refs:
            raise RuntimeError("frame batch unavailable")

        records = [
            self.records_by_source_ref.get(str(unit["source_ref"]), {})
            for unit in source_units
        ]
        relevant_source_unit_ids = [
            str(unit["source_unit_id"])
            for unit, record in zip(source_units, records, strict=True)
            if not record.get("excluded")
        ]
        excluded_source_unit_ids = [
            str(unit["source_unit_id"])
            for unit, record in zip(source_units, records, strict=True)
            if record.get("excluded")
        ]
        relevance_rank = {
            "irrelevant": 0,
            "uncertain": 1,
            "low": 2,
            "medium": 3,
            "high": 4,
        }
        relevance = max(
            (str(record.get("relevance") or "medium") for record in records),
            key=lambda value: relevance_rank[value],
            default="medium",
        )

        def values(field: str) -> list[str]:
            return list(
                dict.fromkeys(
                    str(value)
                    for record in records
                    for value in record.get(field) or ()
                    if str(value).strip()
                )
            )

        return StructuredPaperFrameBatch(
            relevance=relevance,
            paper_role=next(
                (
                    str(record["paper_role"])
                    for record in records
                    if record.get("paper_role")
                ),
                "primary_experiment",
            ),
            screening_note=next(
                (
                    str(record["screening_note"])
                    for record in records
                    if record.get("screening_note")
                ),
                "Bounded model frame.",
            ),
            material_match=values("material_match"),
            changed_variables=values("changed_variables"),
            measured_property_scope=values("measured_property_scope"),
            test_environment_scope=values("test_environment_scope"),
            relevant_source_unit_ids=relevant_source_unit_ids,
            excluded_source_unit_ids=excluded_source_unit_ids,
        )


class _BlockingFrameExtractor(_BoundedFrameExtractor):
    def __init__(self, *, expected_concurrency: int) -> None:
        super().__init__(max_source_units=1)
        self.expected_concurrency = expected_concurrency
        self.release = Event()
        self.expected_workers_started = Event()
        self._lock = Lock()
        self.active_calls = 0
        self.call_count = 0
        self.peak_concurrency = 0

    def screen_batch(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperFrameBatch:
        with self._lock:
            self.active_calls += 1
            self.call_count += 1
            self.peak_concurrency = max(self.peak_concurrency, self.active_calls)
            if self.active_calls == self.expected_concurrency:
                self.expected_workers_started.set()
        try:
            if not self.release.wait(timeout=5):
                raise TimeoutError("framing concurrency test did not release workers")
            return super().screen_batch(payload)
        finally:
            with self._lock:
                self.active_calls -= 1


def _frame_test_tree(*section_specs: tuple[str, str, str]) -> SourceDocumentTree:
    section_ids = tuple(spec[0] for spec in section_specs)
    nodes: dict[str, SourceDocumentNode] = {
        "root": SourceDocumentNode(
            node_id="root",
            document_id="paper-1",
            parent_id=None,
            child_ids=section_ids,
            node_type="document",
            order=0,
        )
    }
    for position, (section_id, label, text) in enumerate(section_specs, start=1):
        paragraph_id = f"{section_id}-paragraph"
        nodes[section_id] = SourceDocumentNode(
            node_id=section_id,
            document_id="paper-1",
            parent_id="root",
            child_ids=(paragraph_id,),
            node_type="section",
            order=position * 100,
            title=label,
            heading_path=(label,),
        )
        nodes[paragraph_id] = SourceDocumentNode(
            node_id=paragraph_id,
            document_id="paper-1",
            parent_id=section_id,
            child_ids=(),
            node_type="paragraph",
            order=position * 100 + 1,
            text=text,
            heading_path=(label,),
            source_ref_kind="block",
            source_ref_id=paragraph_id,
        )
    return SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes=nodes,
    )


def _frame_test_table(table_id: str, caption: str, order: int) -> SimpleNamespace:
    return SimpleNamespace(
        table_id=table_id,
        table_order=order,
        caption_text=caption,
        heading_path="Results",
        column_headers=("condition", "relative density"),
        row_count=2,
        col_count=2,
        table_matrix=(
            ("condition", "relative density"),
            ("A", "99.1"),
        ),
    )


def test_research_objective_table_source_payload_includes_table_cells():
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

    payload = source_extraction._build_objective_route_source_payload(
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


def test_table_source_payload_recovers_adjacent_descriptive_caption():
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-hip",
            "document_id": "paper-hip",
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "process_or_treatment",
            "extractable": True,
        }
    )
    table = SimpleNamespace(
        table_id="table-2",
        document_id="paper-hip",
        page=4,
        caption_text="Table 2",
        caption_block_id="caption-57",
        heading_path="Methods",
        column_headers=["Nomenclature", "Heat Treatment"],
        table_matrix=[["Nomenclature", "Heat Treatment"], ["HT", "up"]],
    )
    blocks = [
        SimpleNamespace(
            block_id="caption-57",
            document_id="paper-hip",
            block_type="caption",
            text="Table 2",
            block_order=57,
            page=4,
            heading_path="Methods",
        ),
        SimpleNamespace(
            block_id="caption-description-58",
            document_id="paper-hip",
            block_type="paragraph",
            text=(
                "Nominal HIP conditions. Heating/cooling rates are in C/min. "
                "Up and down arrows refer to the nominal heating rates and "
                "cooling rates, respectively."
            ),
            block_order=58,
            page=4,
            heading_path="Methods",
        ),
        SimpleNamespace(
            block_id="unrelated-59",
            document_id="paper-hip",
            block_type="paragraph",
            text="Unrelated methods prose must not become part of the caption.",
            block_order=59,
            page=4,
            heading_path="Methods",
        ),
    ]

    payload = source_extraction._build_objective_route_source_payload(
        route=route,
        blocks=blocks,
        tables=[table],
    )

    assert payload["caption_text"] == (
        "Table 2. Nominal HIP conditions. Heating/cooling rates are in C/min. "
        "Up and down arrows refer to the nominal heating rates and cooling "
        "rates, respectively."
    )


def test_research_objective_text_source_payload_uses_document_tree():
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

    payload = source_extraction._build_objective_route_source_payload(
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


def test_objective_paper_frame_payload_keeps_all_tree_sections_with_stable_ids():
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

    payload = source_screening._build_objective_paper_frame_payload(
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

    section_units = [
        item for item in payload["source_units"] if item["source_kind"] == "section"
    ]
    labels = [item["section_label"] for item in section_units]
    assert "Results > Texture results" in labels
    assert "Results > Tensile properties" in labels
    assert len(labels) == 32
    assert len({item["source_unit_id"] for item in section_units}) == 32
    assert all(item["source_ref"] for item in section_units)
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


def test_objective_paper_frame_payload_gives_unsectioned_chunks_unique_ids():
    source_text = "Relative density changed with laser power. " * 200
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("paragraph",),
                node_type="document",
                order=0,
            ),
            "paragraph": SourceDocumentNode(
                node_id="paragraph",
                document_id="paper-1",
                parent_id="root",
                child_ids=(),
                node_type="paragraph",
                order=1,
                text=source_text,
                source_ref_kind="block",
                source_ref_id="block-1",
            ),
        },
    )

    payload = source_screening._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=_research_objective(
            {
                "objective_id": "obj-density",
                "question": "How does laser power affect relative density?",
                "variables": ["laser power"],
                "outcomes": ["relative density"],
            }
        ),
        paper_skim=None,
        document=SimpleNamespace(document_id="paper-1", title="Density"),
        profile=None,
        blocks=[],
        tables=[],
        document_tree=document_tree,
    )

    source_unit_ids = [
        str(item["source_unit_id"])
        for item in payload["source_units"]
    ]
    assert len(source_unit_ids) > 1
    assert len(source_unit_ids) == len(set(source_unit_ids))
    assert " ".join(
        str(item["text"])
        for item in payload["source_units"]
    ).split() == source_text.split()


def test_objective_paper_frame_payload_keeps_root_text_beside_sections():
    document_tree = SourceDocumentTree(
        document_id="paper-1",
        collection_id="col-test",
        root_node_id="root",
        nodes={
            "root": SourceDocumentNode(
                node_id="root",
                document_id="paper-1",
                parent_id=None,
                child_ids=("abstract", "results"),
                node_type="document",
                order=0,
            ),
            "abstract": SourceDocumentNode(
                node_id="abstract",
                document_id="paper-1",
                parent_id="root",
                child_ids=(),
                node_type="paragraph",
                order=1,
                text="Laser power controlled relative density in the current work.",
                source_ref_kind="block",
                source_ref_id="block-abstract",
            ),
            "results": SourceDocumentNode(
                node_id="results",
                document_id="paper-1",
                parent_id="root",
                child_ids=("results-paragraph",),
                node_type="section",
                order=2,
                title="Results",
                heading_path=("Results",),
            ),
            "results-paragraph": SourceDocumentNode(
                node_id="results-paragraph",
                document_id="paper-1",
                parent_id="results",
                child_ids=(),
                node_type="paragraph",
                order=3,
                text="Relative density reached 99.5 percent.",
                source_ref_kind="block",
                source_ref_id="block-results",
            ),
        },
    )

    payload = source_screening._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=_research_objective(
            {
                "objective_id": "obj-density",
                "question": "How does laser power affect relative density?",
                "variables": ["laser power"],
                "outcomes": ["relative density"],
            }
        ),
        paper_skim=None,
        document=SimpleNamespace(document_id="paper-1", title="Density"),
        profile=None,
        blocks=[],
        tables=[],
        document_tree=document_tree,
    )

    section_units = [
        item for item in payload["source_units"] if item["source_kind"] == "section"
    ]
    assert [item["section_label"] for item in section_units] == [
        "Unsectioned",
        "Results",
    ]
    assert "current work" in section_units[0]["text"]
    assert "99.5 percent" in section_units[1]["text"]
    assert len({item["source_unit_id"] for item in section_units}) == 2


def test_objective_paper_frame_uses_bounded_opaque_ids_for_long_source_refs():
    long_section_id = f"node_{'a' * 280}"
    document_tree = _frame_test_tree(
        (
            long_section_id,
            "Results",
            "Laser power increased relative density.",
        ),
    )

    units = source_screening._build_frame_tree_section_source_units(document_tree)

    assert len(units) == 1
    assert units[0]["source_ref"] == long_section_id
    assert len(units[0]["source_unit_id"]) <= 200
    assert long_section_id not in units[0]["source_unit_id"]


def test_objective_paper_frame_payload_keeps_all_tables_for_model_classification():
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
    payload = source_screening._build_objective_paper_frame_payload(
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

    table_units = [
        item for item in payload["source_units"] if item["source_kind"] == "table"
    ]
    assert [item["source_ref"] for item in table_units] == [
        "tbl-density",
        "tbl-yield-texture",
    ]
    assert len({item["source_unit_id"] for item in table_units}) == 2


def test_objective_paper_frame_payload_keeps_every_table_row_in_stable_chunks():
    matrix = tuple(
        (f"condition-{index}", f"result-{index}")
        for index in range(8)
    )

    units = source_screening._build_frame_table_source_units(
        [
            SimpleNamespace(
                table_id="table-late-result",
                table_order=1,
                caption_text="Process and property measurements.",
                heading_path="Results",
                column_headers=("condition", "result"),
                row_count=len(matrix),
                col_count=2,
                table_matrix=matrix,
            )
        ]
    )

    assert len(units) == 3
    assert len({unit["source_unit_id"] for unit in units}) == 3
    assert [row for unit in units for row in unit["sample_rows"]] == [
        list(row) for row in matrix
    ]
    assert all(
        unit["caption_text"] == "Process and property measurements."
        and unit["heading_path"] == "Results"
        and unit["column_headers"] == ["condition", "result"]
        for unit in units
    )

    frame = source_screening._aggregate_objective_paper_frame_batches(
        objective_id="obj-density",
        document_id="paper-1",
        source_units=units,
        batch_results=(
            (
                {
                    "relevance": "irrelevant",
                    "paper_role": "irrelevant",
                    "relevant_source_unit_ids": [],
                    "excluded_source_unit_ids": [units[0]["source_unit_id"]],
                },
                "model",
                (),
            ),
            (
                {
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "relevant_source_unit_ids": [units[1]["source_unit_id"]],
                    "excluded_source_unit_ids": [],
                },
                "model",
                (),
            ),
            (
                {
                    "relevance": "irrelevant",
                    "paper_role": "irrelevant",
                    "relevant_source_unit_ids": [],
                    "excluded_source_unit_ids": [units[2]["source_unit_id"]],
                },
                "model",
                (),
            ),
        ),
        paper_skim=None,
    )

    assert frame.relevant_tables == ("table-late-result",)
    assert frame.excluded_tables == ()
    assert [item.disposition for item in frame.source_dispositions] == [
        "model_excluded",
        "model_relevant",
        "model_excluded",
    ]


def test_objective_paper_frame_aggregation_rejects_missing_source_disposition():
    units = source_screening._build_frame_tree_section_source_units(
        _frame_test_tree(
            ("methods", "Methods", "Laser power was varied."),
            ("results", "Results", "Relative density increased."),
        )
    )

    with pytest.raises(ValueError, match="missing Source-unit dispositions"):
        source_screening._aggregate_objective_paper_frame_batches(
            objective_id="obj-density",
            document_id="paper-1",
            source_units=units,
            batch_results=(
                (
                    {
                        "relevance": "medium",
                        "paper_role": "primary_experiment",
                        "relevant_source_unit_ids": [units[0]["source_unit_id"]],
                        "excluded_source_unit_ids": [],
                    },
                    "model",
                    (),
                ),
            ),
            paper_skim=None,
        )


def test_objective_paper_frame_payload_uses_compact_lineage_scientific_prior():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["relative density"],
            "source_relationship_ids": ["relationship-density"],
        }
    )
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": "study-private-lineage",
                    "experiment_label": "LPBF density experiment",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["316L stainless steel"],
                    "process_context": ["LPBF"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-density",
                            "varied_factors": ["laser power"],
                            "outcome": "relative density",
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "results-density",
                                }
                            ],
                        },
                        {
                            "relationship_id": "relationship-unrelated",
                            "varied_factors": ["heat treatment"],
                            "outcome": "microhardness",
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "results-hardness",
                                }
                            ],
                        },
                    ],
                }
            ],
            "evidence_density": "high",
            "confidence": 0.91,
            "source_unit_coverage": [
                {
                    "source_unit_id": f"source-unit-{index}",
                    "window_id": "window-1",
                    "source_kind": "block",
                    "source_ref": f"block-{index}",
                    "status": "no_study_signal",
                    "reason": "coverage-marker-that-must-not-enter-framing",
                }
                for index in range(40)
            ],
        }
    )

    payload = source_screening._build_objective_paper_frame_payload(
        collection_id="col-test",
        objective=objective,
        paper_skim=paper_skim,
        document=SimpleNamespace(document_id="paper-1", title="Density study"),
        profile=None,
        blocks=[],
        tables=[],
        document_tree=None,
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["paper_prior"] == {
        "doc_role": "experimental",
        "evidence_density": "high",
        "studies": [
            {
                "experiment_label": "LPBF density experiment",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": ["316L stainless steel"],
                "process_context": ["LPBF"],
                "sample_context": [],
                "test_context": [],
                "comparator": None,
                "fixed_conditions": [],
                "relationships": [
                    {
                        "varied_factors": ["laser power"],
                        "outcome": "relative density",
                    }
                ],
            }
        ],
    }
    assert "source_unit_coverage" not in serialized
    assert "unresolved_signals" not in serialized
    assert "study-private-lineage" not in serialized
    assert "relationship-density" not in serialized
    assert "source_refs" not in serialized
    assert "coverage-marker-that-must-not-enter-framing" not in serialized
    assert "microhardness" not in serialized


def test_objective_paper_framing_batches_every_stable_source_once():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    document_tree = _frame_test_tree(
        ("methods", "Methods", "Laser power was varied for LPBF samples."),
        ("results", "Results", "Relative density increased with laser power."),
        ("discussion", "Discussion", "The density trend is discussed."),
    )
    tables = [
        _frame_test_table("table-density", "Relative density results.", 1),
        _frame_test_table("table-background", "Nominal composition.", 2),
    ]
    extractor = _BoundedFrameExtractor(
        max_source_units=2,
        records_by_source_ref={
            "methods": {"changed_variables": ["laser power"]},
            "results": {
                "relevance": "high",
                "measured_property_scope": ["relative density"],
            },
            "table-density": {
                "relevance": "high",
                "measured_property_scope": ["relative density"],
            },
            "table-background": {"excluded": True, "relevance": "low"},
        },
    )

    frames = source_screening.screen_sources(
        collection_id="col-test",
        source_screener=extractor,
        objectives=(objective,),
        paper_skims=(),
        documents=(SimpleNamespace(document_id="paper-1", title="Density"),),
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": tables},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert sorted(
        len(payload["source_units"]) for payload in extractor.frame_payloads
    ) == [1, 2, 2]
    sent_ids = [
        unit["source_unit_id"]
        for payload in extractor.frame_payloads
        for unit in payload["source_units"]
    ]
    assert len(sent_ids) == len(set(sent_ids)) == 5
    assert all(
        payload["document"]["document_id"] == "paper-1"
        for payload in extractor.frame_payloads
    )
    assert len(frames) == 1
    assert frames[0].relevance == "high"
    assert frames[0].changed_variables == ("laser power",)
    assert frames[0].measured_property_scope == ("relative density",)
    assert frames[0].relevant_sections == ("Methods", "Results", "Discussion")
    assert frames[0].relevant_text_source_refs == (
        "methods",
        "results",
        "discussion",
    )
    assert frames[0].relevant_tables == ("table-density",)
    assert frames[0].excluded_tables == ("table-background",)
    assert len(frames[0].source_dispositions) == len(sent_ids)
    assert all(
        item.disposition in {"model_relevant", "model_excluded"}
        and not item.accounting_errors
        for item in frames[0].source_dispositions
    )


def test_objective_paper_framing_honors_configured_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBJECTIVE_PAPER_FRAMING_MAX_CONCURRENCY", "10")
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    document_tree = _frame_test_tree(
        *tuple(
            (
                f"section-{position}",
                f"Section {position}",
                f"Laser power and relative density observation {position}.",
            )
            for position in range(12)
        )
    )
    extractor = _BlockingFrameExtractor(expected_concurrency=10)

    with ThreadPoolExecutor(max_workers=1) as runner:
        future = runner.submit(
            source_screening.screen_sources,
            collection_id="col-test",
            source_screener=extractor,
            objectives=(objective,),
            paper_skims=(),
            documents=(SimpleNamespace(document_id="paper-1", title="Density"),),
            profiles_by_document_id={},
            blocks_by_document_id={},
            tables_by_document_id={},
            document_trees_by_document_id={"paper-1": document_tree},
        )
        try:
            assert extractor.expected_workers_started.wait(timeout=1)
            with extractor._lock:
                assert extractor.active_calls == 10
                assert extractor.call_count == 10
        finally:
            extractor.release.set()
        frames = future.result(timeout=5)

    assert extractor.call_count == 12
    assert extractor.peak_concurrency == 10
    assert len(frames) == 1
    assert [item.source_ref for item in frames[0].source_dispositions] == [
        f"section-{position}" for position in range(12)
    ]


def test_objective_paper_framing_shares_concurrency_across_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBJECTIVE_PAPER_FRAMING_MAX_CONCURRENCY", "10")
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    documents = tuple(
        SimpleNamespace(document_id=f"paper-{position}", title=f"Paper {position}")
        for position in range(12)
    )
    trees = {
        document.document_id: _frame_test_tree(
            (
                f"results-{position}",
                "Results",
                f"Laser power and relative density observation {position}.",
            )
        )
        for position, document in enumerate(documents)
    }
    extractor = _BlockingFrameExtractor(expected_concurrency=10)

    with ThreadPoolExecutor(max_workers=1) as runner:
        future = runner.submit(
            source_screening.screen_sources,
            collection_id="col-test",
            source_screener=extractor,
            objectives=(objective,),
            paper_skims=(),
            documents=documents,
            profiles_by_document_id={},
            blocks_by_document_id={},
            tables_by_document_id={},
            document_trees_by_document_id=trees,
        )
        try:
            assert extractor.expected_workers_started.wait(timeout=1)
            with extractor._lock:
                assert extractor.active_calls == 10
                assert extractor.call_count == 10
        finally:
            extractor.release.set()
        frames = future.result(timeout=5)

    assert extractor.call_count == 12
    assert extractor.peak_concurrency == 10
    assert [frame.document_id for frame in frames] == [
        document.document_id for document in documents
    ]


def test_objective_paper_framing_progress_counts_completed_papers() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    documents = (
        SimpleNamespace(document_id="paper-1", title="Paper 1"),
        SimpleNamespace(document_id="paper-2", title="Paper 2"),
    )
    progress: list[dict[str, Any]] = []

    source_screening.screen_sources(
        collection_id="col-test",
        source_screener=_BoundedFrameExtractor(max_source_units=1),
        objectives=(objective,),
        paper_skims=(),
        documents=documents,
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={},
        document_trees_by_document_id={
            "paper-1": _frame_test_tree(
                ("results-1", "Results", "Relative density result 1.")
            ),
            "paper-2": _frame_test_tree(
                ("results-2", "Results", "Relative density result 2.")
            ),
        },
        progress_callback=progress.append,
    )

    assert [item["current"] for item in progress] == [0, 1, 2]
    assert [item["phase"] for item in progress] == [
        "objective_paper_framing_started",
        "objective_paper_framing_completed",
        "objective_paper_framing_completed",
    ]
    assert [item.get("active_document_id") for item in progress] == [
        None,
        "paper-1",
        "paper-2",
    ]


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [
        (None, 10),
        ("3", 3),
        ("invalid", 10),
        ("0", 10),
    ],
)
def test_objective_paper_framing_concurrency_configuration(
    monkeypatch: pytest.MonkeyPatch,
    configured_value: str | None,
    expected: int,
) -> None:
    if configured_value is None:
        monkeypatch.delenv("OBJECTIVE_PAPER_FRAMING_MAX_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv(
            "OBJECTIVE_PAPER_FRAMING_MAX_CONCURRENCY",
            configured_value,
        )

    assert source_screening._paper_framing_max_concurrency() == expected


def test_objective_paper_frame_routes_duplicate_headings_by_selected_source_ref(
):
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    document_tree = _frame_test_tree(
        (
            "current-results",
            "Results",
            "Laser power increased relative density in the current experiment.",
        ),
        (
            "literature-results",
            "Results",
            "Laser power increased relative density in a cited study.",
        ),
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "medium",
            "paper_role": "primary_experiment",
            "relevant_sections": ["Results"],
            "relevant_text_source_refs": ["current-results"],
        }
    )

    candidates = evidence_routing._build_tree_route_text_candidates(
        frame=frame,
        objective_context=objective,
        blocks=[],
        document_tree=document_tree,
    )

    assert [candidate["source_ref"] for candidate in candidates] == [
        "current-results-paragraph"
    ]


def test_objective_paper_framing_preserves_siblings_when_one_batch_fails():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    document_tree = _frame_test_tree(
        ("methods", "Methods", "Laser power was varied."),
        ("middle", "Experimental setup", "Samples were prepared consistently."),
        ("results", "Results", "Relative density increased."),
    )
    extractor = _BoundedFrameExtractor(
        max_source_units=1,
        records_by_source_ref={
            "methods": {
                "relevance": "medium",
                "screening_note": "Variable definition.",
                "changed_variables": ["laser power"],
            },
            "results": {
                "relevance": "high",
                "screening_note": "Direct density result.",
                "measured_property_scope": ["relative density"],
            },
        },
        failing_source_refs={"middle"},
    )

    frames = source_screening.screen_sources(
        collection_id="col-test",
        source_screener=extractor,
        objectives=(objective,),
        paper_skims=(),
        documents=(SimpleNamespace(document_id="paper-1", title="Density"),),
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert len(extractor.frame_payloads) == 3
    assert len(frames) == 1
    frame = frames[0]
    assert frame.relevance == "high"
    assert frame.changed_variables == ("laser power",)
    assert frame.measured_property_scope == ("relative density",)
    assert frame.relevant_sections == ("Methods", "Experimental setup", "Results")
    assert frame.screening_note == "Direct density result."
    assert frame.screening_note != (
        "Deterministic frame built after model framing failed."
    )


def test_objective_paper_framing_keeps_failed_batch_routable_when_sibling_is_irrelevant():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    extractor = _BoundedFrameExtractor(
        max_source_units=1,
        records_by_source_ref={
            "background": {
                "excluded": True,
                "relevance": "irrelevant",
                "paper_role": "irrelevant",
                "screening_note": "This source is unrelated.",
            },
        },
        failing_source_refs={"results"},
    )

    frames = source_screening.screen_sources(
        collection_id="col-test",
        source_screener=extractor,
        objectives=(objective,),
        paper_skims=(),
        documents=(SimpleNamespace(document_id="paper-1", title="Density"),),
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={},
        document_trees_by_document_id={
            "paper-1": _frame_test_tree(
                ("background", "Background", "General background."),
                ("results", "Results", "Relative density increased."),
            )
        },
    )

    assert len(frames) == 1
    assert frames[0].relevance == "uncertain"
    assert frames[0].paper_role == "uncertain"
    assert frames[0].screening_note is None
    assert frames[0].relevant_sections == ("Results",)
    assert [
        (item.source_ref, item.disposition)
        for item in frames[0].source_dispositions
    ] == [
        ("background", "model_excluded"),
        ("results", "fallback_relevant"),
    ]
    assert "frame batch unavailable" in frames[0].source_dispositions[1].accounting_errors[0]


def test_objective_paper_framing_skips_explicitly_excluded_document():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
            "excluded_document_ids": ["paper-1"],
        }
    )
    extractor = _BoundedFrameExtractor(max_source_units=8)

    frames = source_screening.screen_sources(
        collection_id="col-test",
        source_screener=extractor,
        objectives=(objective,),
        paper_skims=(),
        documents=(SimpleNamespace(document_id="paper-1", title="Density"),),
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={},
        document_trees_by_document_id={
            "paper-1": _frame_test_tree(
                ("results", "Results", "Relative density increased."),
            )
        },
    )

    assert extractor.frame_payloads == []
    assert len(frames) == 1
    assert frames[0].relevance == "irrelevant"
    assert frames[0].paper_role == "irrelevant"
    assert frames[0].relevant_sections == ()


def test_objective_paper_framing_does_not_send_over_budget_singleton():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    extractor = _BoundedFrameExtractor(max_source_units=0)

    frames = source_screening.screen_sources(
        collection_id="col-test",
        source_screener=extractor,
        objectives=(objective,),
        paper_skims=(),
        documents=(SimpleNamespace(document_id="paper-1", title="Density"),),
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={},
        document_trees_by_document_id={
            "paper-1": _frame_test_tree(
                ("results", "Results", "Relative density increased."),
            )
        },
    )

    assert extractor.frame_payloads == []
    assert frames[0].relevance == "uncertain"
    assert frames[0].relevant_sections == ("Results",)
    assert frames[0].source_dispositions[0].disposition == "fallback_relevant"
    assert "prompt token preflight failed" in (
        frames[0].source_dispositions[0].accounting_errors[0]
    )


def test_objective_symbol_axes_distinguish_scan_and_build_angles():
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
    assert source_extraction._objective_process_attribute_label(
        column="θ",
        role="process variable",
        objective_context=objective,
    ) == "scan strategy rotation angle"
    assert source_extraction._objective_process_attribute_label(
        column="α",
        role="process variable",
        objective_context=objective,
    ) == "build orientation alpha angle"


def test_objective_angle_table_comparison_retains_all_changed_axes():
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
        for record in source_extraction._objective_table_matrix_evidence_records(
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

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
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


def test_llm_objective_evidence_rejects_values_and_axis_absent_from_source():
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

    records = source_validation.validate_source_fact(
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


class _StudySourceEvidenceExtractor:
    def __init__(
        self,
        records_by_source_ref: dict[str, dict[str, Any] | None],
        *,
        failing_source_ref: str | None = None,
    ) -> None:
        self.records_by_source_ref = records_by_source_ref
        self.failing_source_ref = failing_source_ref
        self.calls: list[str] = []

    def extract_source(self, payload):
        source_ref = str(payload["source"]["source_ref"])
        self.calls.append(source_ref)
        if source_ref == self.failing_source_ref:
            raise RuntimeError("objective evidence provider unavailable")
        record = self.records_by_source_ref[source_ref]
        return StructuredEvidenceExtractions.model_validate(
            {"extractions": [record] if record is not None else []}
        )


def _study_source_route(objective_id: str, source_ref: str) -> EvidenceCandidate:
    return EvidenceCandidate.from_mapping(
        {
            "objective_id": objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": source_ref,
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )


def _study_source_block(source_ref: str, heading: str, text: str, page: int):
    return SimpleNamespace(
        block_id=source_ref,
        document_id="paper-1",
        page=page,
        block_type="paragraph",
        heading_path=heading,
        text=text,
    )


def _cross_source_microstructure_records() -> dict[str, dict[str, Any]]:
    def condition(sample: str, power: int, speed: int) -> dict[str, Any]:
        return {
            "evidence_role": "condition_context",
            "changed_variables": [],
            "comparison": None,
            "reported_result": None,
            "attribution_scope": "not_attributable",
            "scientific_context": {
                "sample": [{"name": "sample", "value": sample}],
                "process": [
                    {"name": "laser power", "value": power, "unit": "W"},
                    {
                        "name": "scanning speed",
                        "value": speed,
                        "unit": "mm/s",
                    },
                ],
            },
            "resolution_status": "resolved",
            "confidence": 0.93,
        }

    return {
        "01-methods-s1": condition("S1", 180, 600),
        "02-methods-s2": condition("S2", 240, 900),
        "03-results": {
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 180,
                    "target_value": 240,
                    "unit": "W",
                },
                {
                    "name": "scanning speed",
                    "baseline_value": 600,
                    "target_value": 900,
                    "unit": "mm/s",
                },
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["laser power", "scanning speed"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "cellular-dendritic microstructure",
                "value": None,
                "unit": None,
                "direction": "mixed",
                "result_text": "S2 displayed a cellular-dendritic microstructure",
            },
            "attribution_scope": "joint_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.91,
        },
    }


def test_research_objective_binds_same_study_methods_and_results_sources():
    objective = _research_objective(
        {
            "objective_id": "obj-microstructure",
            "question": (
                "How do laser power and scanning speed affect microstructure?"
            ),
            "variables": ["laser power", "scanning speed"],
            "outcomes": ["microstructure"],
        }
    )
    blocks = [
        _study_source_block(
            "01-methods-s1",
            "Methods",
            "Sample S1 used laser power 180 W and scanning speed 600 mm/s.",
            2,
        ),
        _study_source_block(
            "02-methods-s2",
            "Methods",
            "Sample S2 used laser power 240 W and scanning speed 900 mm/s.",
            2,
        ),
        _study_source_block(
            "03-results",
            "Results",
            (
                "Sample S1 showed equiaxed grains, whereas S2 displayed a "
                "cellular-dendritic microstructure."
            ),
            6,
        ),
    ]
    extractor = _StudySourceEvidenceExtractor(
        _cross_source_microstructure_records()
    )

    routes = tuple(
        _study_source_route(objective.objective_id, block.block_id)
        for block in blocks
    )
    source_drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )
    drafts = paper_experiment._bind_objective_result_process_context(source_drafts)

    assert extractor.calls == ["01-methods-s1", "02-methods-s2", "03-results"]
    assert not any(draft.selection_status == "failed" for draft in drafts)
    result_draft = next(draft for draft in drafts if draft.reported_result is not None)
    assert result_draft.attribution_scope == "joint_effect"
    assert [variable.to_record() for variable in result_draft.changed_variables] == [
        {
            "name": "laser power",
            "baseline_value": 180,
            "target_value": 240,
            "unit": "W",
        },
        {
            "name": "scanning speed",
            "baseline_value": 600,
            "target_value": 900,
            "unit": "mm/s",
        },
    ]
    assert {
        (ref["source_ref"], tuple(ref.get("supports", ())))
        for ref in result_draft.source_refs
    } == {
        (
            "01-methods-s1",
            (
                "changed_variables",
                "comparison.axis_names",
                "scientific_context.sample",
                "scientific_context.process",
            ),
        ),
        (
            "02-methods-s2",
            (
                "changed_variables",
                "comparison.axis_names",
                "scientific_context.sample",
                "scientific_context.process",
            ),
        ),
        ("03-results", ("comparison.labels", "reported_result")),
    }

    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-test",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    evidence_records = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=drafts,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={"paper-1": []},
        figures_by_document_id={"paper-1": []},
    )
    result_evidence = next(
        evidence for evidence in evidence_records if evidence.reported_result is not None
    )
    assert result_evidence.reported_result.outcome == "microstructure"
    assert len(result_evidence.related_source_refs) == 3
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    contributions = evidence_materialization._analysis_contributions(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        paper_skims=(),
        frames=(frame,),
        routes=routes,
        evidence_records=evidence_records,
    )

    assert len(contributions) == 1
    assert contributions[0].evidence_disposition == "comparable_evidence"
    assert contributions[0].routed_source_count == 3
    assert contributions[0].extracted_source_count == 3
    assert contributions[0].comparable_evidence_count == 1
    assert contributions[0].failed_source_count == 0


def test_research_objective_keeps_unbound_result_as_descriptive_evidence():
    objective = _research_objective(
        {
            "objective_id": "obj-microstructure",
            "variables": ["laser power", "scanning speed"],
            "outcomes": ["microstructure"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        (
            "Sample S1 showed equiaxed grains, whereas S2 displayed a "
            "cellular-dendritic microstructure."
        ),
        6,
    )
    extractor = _StudySourceEvidenceExtractor(
        {"03-results": _cross_source_microstructure_records()["03-results"]}
    )

    source_drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={"paper-1": [result_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )
    drafts = paper_experiment._bind_objective_result_process_context(source_drafts)

    assert extractor.calls == ["03-results"]
    assert len(drafts) == 1
    assert drafts[0].selection_status == "extracted"
    assert drafts[0].reported_result is not None
    assert drafts[0].changed_variables == ()
    assert drafts[0].comparison is None
    assert drafts[0].attribution_scope == "descriptive_only"
    assert drafts[0].resolution_status == "partial"


def test_research_objective_binds_directional_result_series_to_process_table() -> None:
    def condition(
        sample: str,
        laser_power: str,
        input_current: str = "200 A",
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"condition-{sample}",
                "objective_id": "obj-energy-ductility",
                "document_id": "paper-sild",
                "source_kind": "table",
                "source_ref": "table-2",
                "evidence_role": "condition_context",
                "selection_status": "extracted",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "Sample", "value": sample}],
                    "process": [
                        {
                            "name": "Input current (induction heater), I",
                            "value": input_current,
                        },
                        {"name": "Laser power, P", "value": laser_power},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-2",
                        "source_excerpt": (
                            f"Sample: {sample} | Input current: 200 A | "
                            f"Laser power: {laser_power}"
                        ),
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    result_text = (
        "the elongation decreases from 20.1% ± 0.5% (20 0-10 0 0) to "
        "17.0% ± 0.7% (20 0-850)"
    )
    source_text = (
        "With decreasing laser power, the UTS increases from 867 ± 5 MPa "
        "(20 0-10 0 0) to 876 ± 8 MPa (20 0-850), and then to 892 ± 3 MPa "
        "(20 0-70 0), "
        f"{result_text} and then to 15.4% ± 1.3% (20 0-70 0)."
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-ductility",
            "objective_id": "obj-energy-ductility",
            "document_id": "paper-sild",
            "source_kind": "text_window",
            "source_ref": "results-ductility",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "value": 17.0,
                "unit": "%",
                "direction": "decrease",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-ductility",
                    "source_excerpt": source_text,
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )

    drafts = paper_experiment._bind_objective_result_process_context(
        (
            condition("0-1000", "1000 W", "0 A"),
            condition("100-1000", "1000 W", "100 A"),
            condition("200-1000", "1000 W"),
            condition("200-850", "850 W"),
            condition("200-700", "700 W"),
            result,
        )
    )
    bound = [
        item
        for item in drafts
        if item.source_ref == result.source_ref and item.comparison is not None
    ]

    assert [
        (
            item.comparison.baseline_label,
            item.comparison.target_label,
            item.reported_result.baseline_value,
            item.reported_result.target_value,
        )
        for item in bound
    ] == [
        ("200-1000", "200-850", 20.1, 17.0),
        ("200-850", "200-700", 17.0, 15.4),
    ]
    assert [
        [variable.to_record() for variable in item.changed_variables]
        for item in bound
    ] == [
        [
            {
                "name": "Laser power, P",
                "baseline_value": "1000 W",
                "target_value": "850 W",
                "unit": None,
            }
        ],
        [
            {
                "name": "Laser power, P",
                "baseline_value": "850 W",
                "target_value": "700 W",
                "unit": None,
            }
        ],
    ]
    assert all(item.reported_result.unit == "%" for item in bound)
    assert all(item.reported_result.direction == "decrease" for item in bound)
    assert all(item.comparison.comparable for item in bound)
    assert all(item.attribution_scope == "isolated_effect" for item in bound)


def test_objective_extraction_contract_keeps_result_comparison_values() -> None:
    response = StructuredEvidenceExtractions.model_validate(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [],
                    "comparison": {
                        "baseline_label": "200-1000",
                        "target_label": "200-850",
                        "axis_names": ["laser power"],
                        "comparable": True,
                        "incomparability_reasons": [],
                    },
                    "reported_result": {
                        "outcome": "elongation",
                        "value": 17.0,
                        "baseline_value": 20.1,
                        "target_value": 17.0,
                        "unit": "%",
                        "direction": "decrease",
                        "result_text": "elongation decreases from 20.1% to 17.0%",
                    },
                    "attribution_scope": "association_only",
                    "scientific_context": {},
                    "resolution_status": "partial",
                    "confidence": 0.9,
                }
            ]
        }
    )

    result = response.extractions[0].reported_result
    assert result is not None
    assert result.baseline_value == 20.1
    assert result.target_value == 17.0


def test_research_objective_abstains_without_target_result():
    objective = _research_objective({"objective_id": "obj-microstructure"})
    block = _study_source_block(
        "03-background",
        "Introduction",
        "Additive manufacturing is widely used for metal components.",
        1,
    )
    extractor = _StudySourceEvidenceExtractor({"03-background": None})

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, block.block_id),
        ),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert drafts == ()


def test_research_objective_records_provider_failure_as_failed_evidence():
    objective = _research_objective({"objective_id": "obj-microstructure"})
    block = _study_source_block(
        "03-results",
        "Results",
        "S2 displayed a cellular-dendritic microstructure.",
        6,
    )
    extractor = _StudySourceEvidenceExtractor(
        {"03-results": None},
        failing_source_ref="03-results",
    )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, block.block_id),
        ),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert len(drafts) == 1
    assert drafts[0].selection_status == "failed"
    assert drafts[0].failure_reason == (
        "RuntimeError: objective evidence provider unavailable"
    )


def test_llm_objective_evidence_preserves_zero_extraction_confidence():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.95,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "block-1",
            "text": (
                "At a laser power of 100 W the relative density was 97.83%, "
                "while at a laser power of 140 W the relative density was "
                "98.05%."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 100,
                    "target_value": 140,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "100 W",
                "target_label": "140 W",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 98.05,
                "unit": "%",
                "direction": "increase",
                "result_text": "relative density was 98.05%",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.0,
        },
    )

    assert records[0]["confidence"] == 0.0


def test_source_validation_preserves_unchanged_result_for_paper_level_binding():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "results-800-cooling",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.95,
        }
    )
    result_text = (
        "the elongation of the 800 C HIP treatments remained relatively unchanged"
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": (
                "The 800 SC condition had the highest strength compared to the "
                "800 FC and 800 RQ conditions, which had progressively lower "
                "strengths as a result of the increased cooling rate. While the "
                "decrease in strength was observed for the faster cooling rates, "
                f"{result_text}."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "value": None,
                "unit": None,
                "direction": "unknown",
                "result_text": result_text,
            },
            "attribution_scope": "not_attributable",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.0,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is None
    assert records[0]["reported_result"]["direction"] == "no_change"
    assert records[0]["attribution_scope"] == "not_attributable"
    assert "800 SC condition" in records[0]["source_refs"][0]["source_excerpt"]
    assert records[0]["confidence"] == 0.0


def test_source_validation_does_not_invent_series_from_generic_sample_labels():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "ambiguous-groups",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": (
                "Samples S1 and S2 used different cooling rates. Their "
                "elongation remained unchanged."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "direction": "unknown",
                "result_text": "elongation remained unchanged",
            },
            "attribution_scope": "not_attributable",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.8,
        },
    )

    assert records[0]["reported_result"]["direction"] == "no_change"
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "not_attributable"


def test_source_validation_recovers_explicit_direction_from_result_text() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-energy-ductility",
            "question": "How does laser power affect elongation?",
            "variables": ["laser power"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-sild",
            "source_kind": "text_window",
            "source_ref": "results-ductility",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = (
        "elongation decreases from 20.1% (200-1000) to 17.0% (200-850)"
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": result_text,
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "value": 17.0,
                "unit": "%",
                "direction": "unknown",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert records[0]["reported_result"]["direction"] == "decrease"


def test_source_validation_recovers_material_bound_by_source_heading() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-energy-ductility",
            "question": "How does laser power affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-sild",
            "source_kind": "text_window",
            "source_ref": "results-ductility",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = "elongation decreases from 20.1% to 17.0%"
    extracted_record = {
        "evidence_role": "direct_result",
        "changed_variables": [],
        "comparison": None,
        "reported_result": {
            "outcome": "elongation",
            "value": 17.0,
            "unit": "%",
            "direction": "decrease",
            "result_text": result_text,
        },
        "attribution_scope": "descriptive_only",
        "scientific_context": {},
        "resolution_status": "partial",
        "confidence": 0.9,
    }

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "heading_path": (
                "Mechanical properties in SILD-fabricated Ti-6Al-4V"
            ),
            "text": result_text,
        },
        objective_context=objective,
        extracted_record=extracted_record,
    )

    assert records[0]["scientific_context"]["material"] == [
        {"name": "material", "value": "Ti-6Al-4V", "unit": None}
    ]

    other_material_records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "heading_path": "Mechanical properties in SLM-fabricated 316L",
            "text": result_text,
        },
        objective_context=objective,
        extracted_record=extracted_record,
    )
    assert other_material_records[0]["scientific_context"]["material"] == []


def test_llm_objective_evidence_accepts_source_grounded_axis_and_values():
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

    records = source_validation.validate_source_fact(
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
                "baseline_value": 334.2,
                "target_value": 351.9,
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


def test_llm_objective_evidence_rejects_ungrounded_result_endpoint() -> None:
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
            "source_kind": "text_window",
            "source_ref": "result-angle",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": "Yield strength increased from 334.2 to 351.9 MPa.",
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "yield strength",
                "value": 351.9,
                "baseline_value": 999.0,
                "target_value": 351.9,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Yield strength increased from 334.2 to 351.9 MPa.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert records == ()


def test_llm_objective_evidence_completes_grounded_categorical_endpoints():
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

    records = source_validation.validate_source_fact(
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
):
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

    records = source_validation.validate_source_fact(
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


def test_llm_objective_evidence_drops_unsupported_qualitative_direction():
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

    records = source_validation.validate_source_fact(
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


def test_llm_objective_evidence_keeps_grounded_qualitative_direction():
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

    records = source_validation.validate_source_fact(
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


def test_llm_objective_evidence_repairs_endpoints_to_grounded_group_labels():
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

    records = source_validation.validate_source_fact(
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


def test_llm_objective_evidence_keeps_result_without_labels_absent_from_source(
):
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

    records = source_validation.validate_source_fact(
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

    assert len(records) == 1
    assert records[0]["reported_result"]["outcome"] == "microstructure"
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "descriptive_only"
    assert records[0]["resolution_status"] == "partial"


def test_llm_table_result_rejects_outcome_and_unit_from_another_column():
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

    assert not source_validation._objective_extracted_result_is_source_grounded(
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


def test_llm_table_result_rejects_value_from_a_different_experiment_row():
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

    assert not source_validation._objective_extracted_result_is_source_grounded(
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


def test_llm_context_drops_values_absent_from_source():

    record = source_validation._objective_retain_source_grounded_context(
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


def test_llm_result_rejects_ungrounded_categorical_variable_endpoint():

    assert not source_validation._objective_extracted_result_is_source_grounded(
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
):

    record = source_validation._objective_retain_source_grounded_context(
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


def test_objective_paper_framing_marks_all_explicitly_excluded_sources_irrelevant():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    table = _frame_test_table("table-composition", "Nominal composition.", 1)
    extractor = _BoundedFrameExtractor(
        max_source_units=8,
        records_by_source_ref={
            "background": {"excluded": True, "relevance": "irrelevant"},
            "table-composition": {"excluded": True, "relevance": "irrelevant"},
        },
    )

    frames = source_screening.screen_sources(
        collection_id="col-test",
        source_screener=extractor,
        objectives=(objective,),
        paper_skims=(),
        documents=(SimpleNamespace(document_id="paper-1", title="Background"),),
        profiles_by_document_id={},
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={
            "paper-1": _frame_test_tree(
                ("background", "Background", "General alloy context."),
            )
        },
    )

    assert frames[0].relevance == "irrelevant"
    assert frames[0].relevant_sections == ()
    assert frames[0].relevant_tables == ()
    assert frames[0].excluded_tables == ("table-composition",)


def test_research_objective_text_source_payload_resolves_tree_node_to_block():
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

    payload = source_extraction._build_objective_route_source_payload(
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


def test_research_objective_prompt_source_uses_complete_markdown_without_raw_cells():
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

    projected = source_extraction._objective_evidence_prompt_source(source)

    assert "table_matrix" not in projected
    assert "table_cells" not in projected
    assert projected["table_markdown"] == (
        "| sample | density |\n"
        "| --- | --- |\n"
        "| A | 99.6 |"
    )
    _, prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {"question": "How does processing affect density?"},
            "evidence_route": {"source_kind": "table"},
            "source": projected,
        }
    )
    assert "CAPTION: Measured density" in prompt
    assert "| A | 99.6 |" in prompt


def test_objective_evidence_prompt_does_not_copy_objective_material() -> None:
    system_prompt, _user_prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does scanning strategy affect porosity?",
                "material_scope": ["Ti-6Al-4V"],
                "variables": ["scanning strategy"],
                "outcomes": ["porosity"],
            },
            "source": {
                "text": "Scan X reduced porosity in 17-4PH stainless steel."
            },
        }
    )

    assert "Never copy the OBJECTIVE material" in system_prompt


def test_research_objective_evidence_prompt_compacts_long_text_source(
):
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
            "screening_note": "x" * 1000,
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

        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.unit_payloads.append(payload)
            return StructuredEvidenceExtractions()

    extractor = PayloadCaptureExtractor()

    extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    payload = extractor.unit_payloads[0]
    assert len(payload["source"]["text"]) <= 1800
    assert "screening_note" not in payload["paper_frame"]
    assert "relevant_tables" not in payload["paper_frame"]
    assert "excluded_tables" not in payload["paper_frame"]


def test_research_objective_fragmented_table_matrix_triggers_structural_repair(
):
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

    assert source_extraction._objective_table_source_needs_llm_structural_repair(
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

    repaired_source, repair_error = (
        source_extraction._repair_objective_table_source_if_needed(
            collection_id="col-test",
            route=route,
            source=source,
            paper_facts_extractor=extractor,
        )
    )

    assert repair_error is None
    assert len(extractor.payloads) == 1
    assert repaired_source["raw_table_matrix"] == source["table_matrix"]
    assert repaired_source["table_matrix"] == [
        ["Specimens", "Density (%)"],
        ["HIP-SLM (100/100)", "98.15"],
    ]
    assert repaired_source["table_matrix_structural_repair_applied"] is True


def test_research_objective_repairs_long_table_as_complete_markdown_row_slices():
    class BoundedRepairExtractor:
        def __init__(self) -> None:
            self.payloads: list[dict[str, Any]] = []

        def estimate_table_matrix_repair_prompt_tokens(
            self,
            payload: dict[str, Any],
        ) -> int:
            markdown = str(payload["source"]["table_markdown"])
            data_row_count = sum(
                1
                for line in markdown.splitlines()
                if line.startswith("| sample-") or line.startswith("| HIP-SLM")
            )
            return 20_000 if data_row_count > 4 else 1_000

        def repair_table_matrix(
            self,
            payload: dict[str, Any],
        ) -> StructuredTableMatrixRepair:
            self.payloads.append(payload)
            markdown = str(payload["source"]["table_markdown"])
            rows = [
                [cell.strip().replace(r"\|", "|") for cell in line.strip("|").split("|")]
                for line in markdown.splitlines()
                if line.startswith("|") and "---" not in line
            ]
            rows = [
                ["HIP-SLM (100/100)" if cell == "HIP-SLM (100/" else cell for cell in row]
                for row in rows
            ]
            return StructuredTableMatrixRepair(
                repaired_table_matrix=rows,
                confidence=0.9,
            )

    extractor = BoundedRepairExtractor()
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
        "caption_text": "Density for every processing condition.",
        "column_headers": ["Specimen", "Density (%)"],
        "header_row_count": 1,
        "table_matrix": [
            ["Specimen", "Density (%)"],
            *[
                [
                    "HIP-SLM (100/" if row_index == 5 else f"sample-{row_index}",
                    f"{98 + row_index / 100:.2f}",
                ]
                for row_index in range(10)
            ],
        ],
    }

    repaired_source, repair_error = (
        source_extraction._repair_objective_table_source_if_needed(
            collection_id="col-test",
            route=route,
            source=source,
            paper_facts_extractor=extractor,
        )
    )

    assert repair_error is None
    assert len(extractor.payloads) == 4
    assert all(
        payload["source"]["caption_text"]
        == "Density for every processing condition."
        for payload in extractor.payloads
    )
    assert all(
        payload["source"]["table_markdown"].startswith(
            "| Specimen | Density (%) |\n| --- | --- |"
        )
        for payload in extractor.payloads
    )
    assert all("table_cells" not in payload["source"] for payload in extractor.payloads)
    assert repaired_source["table_matrix"] == [
        ["Specimen", "Density (%)"],
        *[
            [
                "HIP-SLM (100/100)" if row_index == 5 else f"sample-{row_index}",
                f"{98 + row_index / 100:.2f}",
            ]
            for row_index in range(10)
        ],
    ]


def test_research_objective_table_repair_rejects_changed_numeric_source_cell():
    class NumericChangingRepairExtractor:
        def repair_table_matrix(self, _payload):
            return StructuredTableMatrixRepair(
                repaired_table_matrix=[
                    ["Specimens", "Density (%)"],
                    ["HIP-SLM (100/100)", "98.25"],
                ],
                confidence=0.9,
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
            ["HIP-SLM (100/", "98.15"],
        ],
    }

    with capture_analysis_diagnostics() as diagnostics:
        repaired_source, repair_error = (
            source_extraction._repair_objective_table_source_if_needed(
                collection_id="col-test",
                route=route,
                source=source,
                paper_facts_extractor=NumericChangingRepairExtractor(),
            )
        )

    assert repaired_source is source
    assert str(repair_error) == (
        "table matrix repair changed or reordered source result numbers"
    )
    assert diagnostics.records == (
        {
            "trace_type": "table_matrix_repair",
            "collection_id": "col-test",
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "table_id": "table-1",
            "page": None,
            "status": "rejected",
            "original_row_count": 2,
            "model_row_count": 2,
            "final_row_count": 2,
            "model_request_count": 1,
            "model_repair_count": 0,
            "fragment_row_reduction_count": 0,
            "deterministic_rebind_count": 0,
            "number_sequence_verified": False,
            "warnings": [],
            "failure_reason": (
                "table matrix repair changed or reordered source result numbers"
            ),
        },
    )


def test_research_objective_table_repair_accepts_cross_row_uncertainty_rebinding():
    original_matrix = [
        ["Specimens", "Hardness (HV)"],
        ["HIP-SLM (100/280)", "147.6"],
        ["as-SLM (120/100)", "( +/- 9.2) 196.9 (+/- 4.5)"],
    ]
    repaired_matrix = [
        ["Specimens", "Hardness (HV)"],
        ["HIP-SLM (100/280)", "147.6 (+/- 9.2)"],
        ["as-SLM (120/100)", "196.9 (+/- 4.5)"],
    ]

    assert (
        source_extraction._objective_table_repair_preserves_result_number_sequences(
            original_matrix=original_matrix,
            repaired_matrix=repaired_matrix,
        )
    )


def test_research_objective_table_repair_accepts_p004_trailing_fragment_row():
    repaired_matrix = [
        [
            "Specimens",
            "Hardness (HV)",
            "Yield Strength (MPa)",
            "Tensile Strength (MPa)",
            "Elongation (%)",
        ],
        [
            "as-SLM (140/280)",
            "191.8 (+/- 7.2)",
            "301.4 (+/- 22.0)",
            "347.8 (+/- 31.8)",
            "5.6 (+/- 1.2)",
        ],
        [
            "HT-SLM (140/280)",
            "160.1 (+/- 5.5)",
            "217.0 (+/- 19.9)",
            "323.2 (+/- 40.5)",
            "9.1 (+/- 1.3)",
        ],
        [
            "HIP-SLM (140/280)",
            "162.4 ( ± 6.9)",
            "221.3 (+/- 9.3)",
            "332.6 (+/- 39.6)",
            "9.6 (+/- 4.1)",
        ],
    ]

    class RepairingPaperFactsExtractor:
        def repair_table_matrix(self, _payload):
            model_matrix = [list(row) for row in repaired_matrix]
            model_matrix[-1][1] = "162.4 (+/- 5.5)"
            return StructuredTableMatrixRepair(
                repaired_table_matrix=model_matrix,
                confidence=0.95,
            )

    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-strength",
            "document_id": "paper-p004",
            "source_kind": "table",
            "source_ref": "table-3",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    source = {
        "source_kind": "table",
        "source_ref": "table-3",
        "document_id": "paper-p004",
        "column_headers": repaired_matrix[0],
        "header_row_count": 1,
        "table_matrix": [
            repaired_matrix[0],
            [
                "as-SLM(140/",
                "191.8 (+/- 7.2)",
                "301.4 (+/- 22.0)",
                "347.8 (+/- 31.8)",
                "5.6 (+/- 1.2)",
            ],
            [
                "280) HT-SLM",
                "160.1 (+/- 5.5)",
                "217.0 (+/- 19.9)",
                "323.2 (+/- 40.5)",
                "9.1 (+/- 1.3)",
            ],
            [
                "(140/280) HIP-SLM",
                "162.4",
                "221.3 (+/- 9.3)",
                "332.6 (+/- 39.6)",
                "9.6 (+/- 4.1)",
            ],
            ["(140/280)", "(+/- 6.9)", "", "", ""],
        ],
    }

    with capture_analysis_diagnostics() as diagnostics:
        repaired_source, repair_error = (
            source_extraction._repair_objective_table_source_if_needed(
                collection_id="col-test",
                route=route,
                source=source,
                paper_facts_extractor=RepairingPaperFactsExtractor(),
            )
        )

    assert repair_error is None
    assert repaired_source["table_matrix"] == repaired_matrix
    assert repaired_source["table_matrix_structural_repair_applied"] is True
    assert diagnostics.records == (
        {
            "trace_type": "table_matrix_repair",
            "collection_id": "col-test",
            "objective_id": "obj-strength",
            "document_id": "paper-p004",
            "table_id": "table-3",
            "page": None,
            "status": "verified",
            "original_row_count": 5,
            "model_row_count": 4,
            "final_row_count": 4,
            "model_request_count": 1,
            "model_repair_count": 0,
            "fragment_row_reduction_count": 1,
            "deterministic_rebind_count": 1,
            "number_sequence_verified": True,
            "warnings": [],
            "failure_reason": None,
        },
    )


def test_research_objective_table_repair_rejects_lost_p004_uncertainty():
    original_matrix = [
        ["Specimens", "Hardness (HV)"],
        ["HT-SLM (140/280)", "160.1 (+/- 5.5)"],
        ["HIP-SLM (140/280)", "162.4"],
        ["(140/280)", "(+/- 6.9)"],
    ]
    repaired_matrix = [
        ["Specimens", "Hardness (HV)"],
        ["HT-SLM (140/280)", "160.1 (+/- 5.5)"],
        ["HIP-SLM (140/280)", "162.4 (+/- 5.5)"],
    ]

    assert not (
        source_extraction._objective_table_repair_preserves_result_number_sequences(
            original_matrix=original_matrix,
            repaired_matrix=repaired_matrix,
        )
    )


def test_research_objective_table_repair_bad_request_is_route_scoped():
    class RouteScopedRepairExtractor:
        def __init__(self) -> None:
            self.source_refs: list[str] = []

        def repair_table_matrix(
            self,
            payload: dict[str, Any],
        ) -> StructuredTableMatrixRepair:
            source_ref = str(payload["source"]["source_ref"])
            self.source_refs.append(source_ref)
            if source_ref == "table-a":
                request = Request("POST", "http://llm.test/v1/chat/completions")
                raise BadRequestError(
                    "invalid table repair payload",
                    response=Response(400, request=request),
                    body=None,
                )
            return StructuredTableMatrixRepair(
                repaired_table_matrix=[
                    ["Specimens", "Density (%)"],
                    ["HIP-SLM (100/100)", "98.15"],
                ],
                confidence=0.9,
            )

    class UnexpectedEvidenceExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract_source(self, _payload):
            self.calls += 1
            return StructuredEvidenceExtractions()

    repair_extractor = RouteScopedRepairExtractor()
    evidence_extractor = UnexpectedEvidenceExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["density"],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "column_roles": {
                    "Specimens": "process_variable",
                    "Density (%)": "result_property",
                },
                "confidence": 0.9,
            }
        )
        for source_ref in ("table-a", "table-b")
    )
    tables = [
        SourceTable(
            table_id=source_ref,
            document_id="paper-1",
            table_order=table_order,
            caption_text="Laser-power conditions and density.",
            caption_block_id=None,
            page=4,
            heading_path="Results",
            column_headers=("Specimens", "Density (%)"),
            table_matrix=(
                ("Specimens", "Density (%)"),
                (f"{table_order}) HIP-SLM (100/", "98.15"),
            ),
        )
        for table_order, source_ref in enumerate(("table-a", "table-b"), start=1)
    ]

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=evidence_extractor,
        paper_facts_extractor=repair_extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": tables},
        document_trees_by_document_id={},
    )

    assert repair_extractor.source_refs == ["table-a", "table-b"]
    assert evidence_extractor.calls == 0
    assert any(
        unit.source_ref == "table-a"
        and unit.selection_status == "failed"
        and unit.failure_reason is not None
        and unit.failure_reason.startswith("BadRequestError:")
        for unit in units
    )
    assert any(
        unit.source_ref == "table-b"
        and unit.selection_status == "extracted"
        and unit.reported_result is not None
        and unit.reported_result.value == 98.15
        for unit in units
    )


@pytest.mark.parametrize(
    ("repaired_table_matrix", "expected_failure_reason"),
    [
        ([], "table matrix repair returned no usable matrix"),
        (
            [
                ["Specimens", "Density (%)"],
                ["100) HIP-SLM (100/", "98.15"],
            ],
            "table matrix repair left the fragmented matrix unchanged",
        ),
        (
            [
                ["Specimens", "Density (%)"],
                ["HIP-SLM (100/", "98.15"],
            ],
            "table matrix repair returned a structurally fragmented matrix",
        ),
    ],
    ids=("empty", "unchanged-fragment", "remaining-fragment"),
)
def test_research_objective_rejects_unusable_table_matrix_repair(
    repaired_table_matrix,
    expected_failure_reason,
):
    class UnusableRepairExtractor:
        def repair_table_matrix(self, _payload):
            return StructuredTableMatrixRepair(
                repaired_table_matrix=repaired_table_matrix,
                confidence=0.9,
            )

    class UnexpectedEvidenceExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract_source(self, _payload):
            self.calls += 1
            return StructuredEvidenceExtractions()

    evidence_extractor = UnexpectedEvidenceExtractor()
    repair_extractor = UnusableRepairExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["density"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Specimens": "process_variable",
                "Density (%)": "result_property",
            },
            "confidence": 0.9,
        }
    )
    table = SourceTable(
        table_id="table-1",
        document_id="paper-1",
        table_order=1,
        caption_text="Laser-power conditions and density.",
        caption_block_id=None,
        page=4,
        heading_path="Results",
        column_headers=("Specimens", "Density (%)"),
        table_matrix=(
            ("Specimens", "Density (%)"),
            ("100) HIP-SLM (100/", "98.15"),
        ),
    )

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=evidence_extractor,
        paper_facts_extractor=repair_extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
    )

    assert evidence_extractor.calls == 0
    assert len(units) == 1
    assert units[0].selection_status == "failed"
    assert units[0].source_ref == "table-1"
    assert units[0].failure_reason == f"ValueError: {expected_failure_reason}"


def test_research_objective_records_failed_evidence_when_table_repair_fails():
    class FailingPaperFactsExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def repair_table_matrix(self, _payload):
            self.calls += 1
            raise RuntimeError("table repair unavailable")

    class UnexpectedEvidenceExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract_source(self, _payload):
            self.calls += 1
            return StructuredEvidenceExtractions()

    repair_extractor = FailingPaperFactsExtractor()
    evidence_extractor = UnexpectedEvidenceExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["density"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Specimens": "process_variable",
                "Density (%)": "result_property",
            },
            "confidence": 0.9,
        }
    )
    table = SourceTable(
        table_id="table-1",
        document_id="paper-1",
        table_order=1,
        caption_block_id=None,
        page=4,
        caption_text="Laser-power conditions and density.",
        heading_path="Results",
        column_headers=("Specimens", "Density (%)"),
        table_matrix=(
            ("Specimens", "Density (%)"),
            ("100) HIP-SLM (100/", "98.15"),
        ),
    )

    with capture_analysis_diagnostics() as diagnostics:
        units = extract_and_validate_source_facts(
            collection_id="col-test",
            source_extractor=evidence_extractor,
            paper_facts_extractor=repair_extractor,
            objectives=(objective,),
            objective_paper_frames=(),
            objective_evidence_routes=(route,),
            blocks_by_document_id={},
            tables_by_document_id={"paper-1": [table]},
            document_trees_by_document_id={},
        )

    assert repair_extractor.calls == 1
    assert evidence_extractor.calls == 0
    assert len(units) == 1
    assert units[0].selection_status == "failed"
    assert units[0].source_ref == "table-1"
    assert units[0].failure_reason == "RuntimeError: table repair unavailable"
    assert diagnostics.records == (
        {
            "trace_type": "table_matrix_repair",
            "collection_id": "col-test",
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "table_id": "table-1",
            "page": 4,
            "status": "provider_failed",
            "original_row_count": 2,
            "model_row_count": None,
            "final_row_count": None,
            "model_request_count": 1,
            "model_repair_count": 0,
            "fragment_row_reduction_count": 0,
            "deterministic_rebind_count": 0,
            "number_sequence_verified": None,
            "warnings": [],
            "failure_reason": "RuntimeError: table repair unavailable",
        },
    )

    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    evidence = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=units,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        figures_by_document_id={},
    )[0]

    assert evidence.selection_status == "failed"
    assert evidence.failure_reason == "RuntimeError: table repair unavailable"
    assert evidence.source_kind == "table"
    assert evidence.source_ref == "table-1"
    assert evidence.source_excerpt


def test_research_objective_service_skips_matrix_test_condition_table_fallback(
):
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

    assert source_extraction._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_skips_untyped_table_test_condition_fallback(
):
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

    assert source_extraction._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_skips_off_target_result_table_fallback(
):
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

    assert source_extraction._objective_table_route_should_skip_llm_fallback(route)
    assert source_extraction._objective_table_route_should_skip_llm_fallback(corrosion_route)

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

    assert source_extraction._objective_table_route_should_skip_llm_fallback(eis_route)


def test_research_objective_service_skips_non_target_result_property_columns(
):
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

    records = source_extraction._objective_table_matrix_evidence_records(
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


def test_energy_input_process_table_preserves_induction_current() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-energy-ductility",
            "variables": ["energy input"],
            "outcomes": ["ductility"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-sild",
            "source_kind": "table",
            "source_ref": "table-2",
            "role": "process_or_treatment",
            "extractable": True,
            "confidence": 0.95,
        }
    )

    records = source_extraction._objective_table_matrix_evidence_records(
        route=route,
        objective_context=objective,
        source={
            "source_kind": "table",
            "source_ref": "table-2",
            "caption_text": (
                "DED processing parameters used for synchronous induction "
                "assisted laser deposition experiments."
            ),
            "column_headers": [
                "Sample",
                "Input current (induction heater), I",
                "Laser power, P",
            ],
            "table_matrix": [
                [
                    "Sample",
                    "Input current (induction heater), I",
                    "Laser power, P",
                ],
                ["0-1000", "0 A", "1000 W"],
                ["200-850", "200 A", "850 W"],
            ],
        },
    )

    process_by_sample = {
        next(
            item["value"]
            for item in record["scientific_context"]["sample"]
            if item["name"] == "Sample"
        ): {
            item["name"]: item["value"]
            for item in record["scientific_context"]["process"]
        }
        for record in records
    }
    assert process_by_sample == {
        "0-1000": {
            "Input current (induction heater), I": "0 A",
            "Laser power, P": "1000 W",
        },
        "200-850": {
            "Input current (induction heater), I": "200 A",
            "Laser power, P": "850 W",
        },
    }


def test_objective_evidence_prompt_teaches_cross_source_energy_group_binding() -> None:
    system_prompt, _user_prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does energy input affect ductility?",
                "variables": ["energy input"],
                "outcomes": ["ductility"],
            },
            "source": {"text": "A source-local result."},
        }
    )

    assert '"baseline_label":"200-1000"' in system_prompt
    assert '"target_label":"200-850"' in system_prompt
    assert '"axis_names":["laser power"]' in system_prompt
    assert '"attribution_scope":"association_only"' in system_prompt


def test_research_objective_service_uses_objective_scientific_intent_directly(
):
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

    assert evidence_routing._route_prompt_objective_record(objective) == {
        "objective_id": "obj-corrosion",
        "question": objective.question,
        "material_scope": ["316L stainless steel"],
        "variables": ["laser power"],
        "outcomes": ["pitting potential"],
        "mechanisms": ["porosity", "pore size"],
        "constraints": ["SLM"],
        "requested_comparator": "lower laser power",
    }


def test_research_objective_service_enriches_only_source_linked_material_context(
):
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

    enriched = paper_experiment._enrich_objective_scope_context(
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
        ],
        "test": [],
    }


def test_research_objective_service_does_not_copy_another_study_context():
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": "study-other-source",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": ["unrelated reference material"],
                    "process_context": ["unrelated treatment"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-other-source",
                            "varied_factors": ["heat treatment"],
                            "outcome": "hardness",
                            "source_refs": [
                                {
                                    "source_kind": "table",
                                    "source_ref": "table-other",
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
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-density",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "relative density",
                "value": 99.2,
                "unit": "%",
                "direction": "unknown",
                "result_text": "Relative density was 99.2%.",
            },
            "attribution_scope": "descriptive_only",
            "source_refs": [
                {"source_kind": "table", "source_ref": "table-density"}
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    enriched = paper_experiment._enrich_objective_scope_context(
        (evidence,),
        paper_skims=(paper_skim,),
    )[0]

    assert enriched.scientific_context.material == ()
    assert enriched.scientific_context.process == ()


def test_research_objective_service_does_not_invent_material_without_document_skim(
):
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

    enriched = paper_experiment._enrich_objective_scope_context(
        (evidence,),
        paper_skims=(),
    )[0]

    assert enriched.scientific_context.material == ()


def test_research_objective_service_routes_matching_tables_beyond_seed_documents(
):
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

    hints = evidence_routing._build_objective_table_routing_hints(
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


def test_real_ved_process_and_defect_tables_form_joint_comparison():
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

    hints = evidence_routing._build_objective_table_routing_hints(objective, tables=tables)

    assert {(hint.table_id, hint.role) for hint in hints} == {
        ("table-2", "condition_context"),
        ("table-5", "result_table"),
    }

    routes: list[EvidenceCandidate] = []
    evidence_routing._append_objective_context_hint_routes(
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
                    "table_schema": evidence_routing._build_route_table_schema(table),
            }
            for table in tables
        },
    )
    units = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for route in routes
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            source=source_extraction._build_objective_route_source_payload(
                route=route,
                blocks=[],
                tables=list(tables),
            ),
            objective_context=objective,
        )
    )
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        paper_experiment._bind_objective_result_process_context(units),
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
):
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


def test_real_p001_density_table_retains_complete_changed_factor_tuple():
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
    hints = evidence_routing._build_objective_table_routing_hints(
        objective,
        tables=(table,),
    )
    routes: list[EvidenceCandidate] = []
    evidence_routing._append_objective_context_hint_routes(
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
                    "table_schema": evidence_routing._build_route_table_schema(table),
            }
        },
    )
    units = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for route in routes
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            source=source_extraction._build_objective_route_source_payload(
                route=route,
                blocks=[],
                tables=[table],
            ),
            objective_context=objective,
        )
    )
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        paper_experiment._bind_objective_result_process_context(units),
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


def test_real_ti64_hip_condition_table_builds_comparable_uts_contrast():
    objective = _research_objective(
        {
            "objective_id": "obj-ti64-hip-uts",
            "question": (
                "How do HIP cooling rate, HIP temperature, HIP treatment, "
                "cooling rate, and post-processing condition affect ultimate "
                "tensile strength?"
            ),
            "material_scope": ["Ti-6Al-4V"],
            "variables": [
                "HIP cooling rate",
                "HIP temperature",
                "HIP treatment",
                "cooling rate",
                "post-processing condition",
            ],
            "outcomes": ["ultimate tensile strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-ti64-hip",
            "source_kind": "table",
            "source_ref": "table-8",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Condition": "sample condition",
                "UTS (MPa)": "result_property",
            },
            "confidence": 0.95,
        }
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            objective_context=objective,
            source={
                "source_kind": "table",
                "source_ref": "table-8",
                "caption_text": (
                    "Table 8 Summary of tensile properties for the vertical "
                    "tensile specimen direction. UTS = ultimate tensile strength."
                ),
                "heading_path": (
                    "Microstructure and mechanical properties of laser powder bed "
                    "fusion Ti-6Al-4V after HIP treatments"
                ),
                "column_headers": ["Condition", "UTS (MPa)"],
                "table_matrix": [
                    ["Condition", "UTS (MPa)"],
                    ["AB", "1294.20 +/- 6.69"],
                    ["800 SC", "1082.43 +/- 1.19"],
                ],
            },
        )
    )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert [item.name for item in comparison.changed_variables] == [
        "post-processing condition"
    ]
    assert comparison.changed_variables[0].baseline_value == "AB"
    assert comparison.changed_variables[0].target_value == "800 SC"
    assert comparison.comparison is not None
    assert comparison.comparison.comparable
    assert comparison.reported_result is not None
    assert comparison.reported_result.baseline_value == 1294.2
    assert comparison.reported_result.target_value == 1082.43
    assert comparison.reported_result.direction == "decrease"
    assert comparison.attribution_scope == "association_only"
    assert comparison.scientific_context.to_record() == {
        "material": [
            {"name": "material", "value": "Ti-6Al-4V", "unit": None}
        ],
        "sample": [
            {"name": "build orientation", "value": "vertical", "unit": None}
        ],
        "process": [
            {
                "name": "manufacturing process",
                "value": "laser powder bed fusion",
                "unit": None,
            }
        ],
        "test": [],
    }


def test_real_ti64_compound_sample_labels_preserve_orientation_for_hip_contrasts():
    objective = _research_objective(
        {
            "objective_id": "obj-ti64-post-processing-uts",
            "question": (
                "How does post-processing condition affect ultimate tensile "
                "strength in Ti-6Al-4V?"
            ),
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["post-processing condition"],
            "outcomes": ["ultimate tensile strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-ti64-post-processing",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Alloy": "material or sample label",
                "UTS (MPa)": "result_property",
            },
            "confidence": 0.95,
        }
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            objective_context=objective,
            source={
                "source_kind": "table",
                "source_ref": "table-1",
                "page": 9,
                "caption_text": (
                    "Table 1. Comparison of the tensile properties of SLM "
                    "Ti-6Al-4V produced in this study built in the as-fabricated "
                    "(AF) and post-processed with HIP and polishing (PL) in two "
                    "orientations of vertical (V) and horizontal (H) with wrought "
                    "Ti-6Al-4V, wrought and annealed Ti-6Al-4V, and the ISO standard "
                    "available in the literature."
                ),
                "column_headers": ["Alloy", "UTS (MPa)"],
                "table_matrix": [
                    ["Alloy", "UTS (MPa)"],
                    ["AF-V", "1006.7 6.3"],
                    ["AF-H", "961.3 50.2"],
                    ["HIP-PL-V", "936 3.6"],
                    ["HIP-PL-H", "937.9 43.3"],
                    ["Wrought Ti-6Al-4V [24]", "1008"],
                    ["Wrought and annealed Ti-6Al-4V [25]", "870 10"],
                    ["Standard ISO 5832-3 for implants for surgery [25]", "> 860"],
                ],
            },
        )
    )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )
    comparable = tuple(
        item
        for item in comparisons
        if item.comparison is not None and item.comparison.comparable
    )

    assert len(measurements) == 4
    assert len(comparable) == 2
    assert {
        (
            item.changed_variables[0].baseline_value,
            item.changed_variables[0].target_value,
            item.comparison.baseline_label,
            item.comparison.target_label,
        )
        for item in comparable
    } == {
        ("as-fabricated", "HIP + polishing", "vertical", "vertical"),
        ("as-fabricated", "HIP + polishing", "horizontal", "horizontal"),
    }
    assert all(
        [item.name for item in comparison.changed_variables]
        == ["post-processing condition"]
        for comparison in comparable
    )
    assert all(
        comparison.reported_result is not None
        and comparison.reported_result.direction == "decrease"
        for comparison in comparable
    )
    assert all(
        comparison.attribution_scope == "association_only"
        for comparison in comparable
    )
    assert {
        (
            item.scientific_context.material[0].value,
            item.scientific_context.sample[0].value,
            item.scientific_context.process[0].value,
        )
        for item in comparable
    } == {
        ("Ti-6Al-4V", "vertical", "laser powder bed fusion"),
        ("Ti-6Al-4V", "horizontal", "laser powder bed fusion"),
    }


def test_research_objective_service_does_not_route_single_letter_acronym_tables(
):
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does scan speed affect density?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scan speed"],
            "outcomes": ["density"],
        }
    )

    hints = evidence_routing._build_objective_table_routing_hints(
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
