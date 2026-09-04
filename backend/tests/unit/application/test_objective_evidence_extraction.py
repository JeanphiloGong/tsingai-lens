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
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveEvidenceResult,
    PaperResearchMap,
    PreparedDocumentInput,
)
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


def test_result_extraction_receives_same_paper_context_bundle() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "question": "How does laser power affect tensile strength?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["tensile strength"],
        }
    )
    result_block = _study_source_block(
        "results-strength",
        "Results",
        "Tensile strength increased from 900 to 980 MPa for samples S1 and S2.",
        6,
    )
    methods_block = _study_source_block(
        "methods-conditions",
        "Methods",
        (
            "Ti-6Al-4V samples S1 and S2 were fabricated by LPBF. "
            "S1 used laser power 180 W and S2 used 240 W. Tensile tests "
            "followed ASTM E8."
        ),
        3,
    )
    table = SimpleNamespace(
        table_id="table-strength",
        document_id="paper-1",
        page=6,
        caption_text="Tensile strength of the two samples.",
        heading_path="Results",
        column_headers=("Sample", "Tensile strength (MPa)"),
        table_matrix=(
            ("Sample", "Tensile strength (MPa)"),
            ("S1", "900"),
            ("S2", "980"),
        ),
    )
    routes = (
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "results-strength",
                "role": "current_experimental_evidence",
                "extractable": True,
            }
        ),
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "methods-conditions",
                "role": "process_or_treatment",
                "extractable": True,
                "context_fields": ["material", "variable", "comparison", "test"],
            }
        ),
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-strength",
                "role": "current_experimental_evidence",
                "extractable": True,
            }
        ),
    )

    class CapturingExtractor:
        def __init__(self) -> None:
            self.payloads: list[dict[str, Any]] = []

        def extract_source(self, payload: dict[str, Any]):
            self.payloads.append(payload)
            source_ref = payload["source"]["source_ref"]
            if source_ref == "results-strength":
                return StructuredEvidenceExtractions.model_validate(
                    {
                        "extractions": [
                            {
                                "evidence_role": "direct_result",
                                "changed_variables": [
                                    {
                                        "name": "laser power",
                                        "baseline_value": 180,
                                        "target_value": 240,
                                        "unit": "W",
                                    }
                                ],
                                "comparison": {
                                    "baseline_label": "S1",
                                    "target_label": "S2",
                                    "axis_names": ["laser power"],
                                    "comparable": True,
                                    "incomparability_reasons": [],
                                },
                                "reported_result": {
                                    "outcome": "tensile strength",
                                    "value": 980,
                                    "unit": "MPa",
                                    "direction": "increase",
                                    "result_text": "Tensile strength increased from 900 to 980 MPa",
                                },
                                "attribution_scope": "descriptive_only",
                                "scientific_context": {
                                    "material": [
                                        {"name": "material", "value": "Ti-6Al-4V"}
                                    ],
                                    "sample": [
                                        {"name": "sample", "value": "S1"},
                                        {"name": "sample", "value": "S2"},
                                    ],
                                    "process": [
                                        {"name": "laser power", "value": 180, "unit": "W"},
                                        {"name": "laser power", "value": 240, "unit": "W"},
                                    ],
                                    "test": [{"name": "test", "value": "ASTM E8"}],
                                },
                                "resolution_status": "resolved",
                                "confidence": 0.8,
                            }
                        ]
                    }
                )
            return StructuredEvidenceExtractions()

    extractor = CapturingExtractor()
    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": [result_block, methods_block]},
        tables_by_document_id={"paper-1": [table]},
        document_trees_by_document_id={},
        _allow_adaptive_context_expansion=False,
    )

    result_payload = next(
        payload
        for payload in extractor.payloads
        if payload["source"]["source_ref"] == "results-strength"
    )
    bundle = result_payload["same_paper_context_bundle"]
    assert [item["source_ref"] for item in bundle] == [
        "methods-conditions",
        "table-strength",
    ]
    assert bundle[0]["role"] == "process_or_treatment"
    assert "Ti-6Al-4V" in bundle[0]["text"]
    assert "Tensile strength (MPa)" in bundle[1]["table_markdown"]
    context_payload = next(
        payload
        for payload in extractor.payloads
        if payload["source"]["source_ref"] == "methods-conditions"
    )
    assert context_payload["same_paper_context_bundle"] == []

    result_draft = next(
        draft for draft in drafts if draft.source_ref == "results-strength"
    )
    assert [variable.to_record() for variable in result_draft.changed_variables] == [
        {
            "name": "laser power",
            "baseline_value": 180,
            "target_value": 240,
            "unit": "W",
        }
    ]
    assert result_draft.scientific_context.material[0].value == "Ti-6Al-4V"
    assert result_draft.scientific_context.test[0].value == "ASTM E8"
    assert any(
        ref["source_ref"] == "table-strength"
        and "bundle_context" in ref.get("supports", ())
        for ref in result_draft.source_refs
    )


def test_same_paper_context_bundle_prioritizes_late_context_routes() -> None:
    """A bounded bundle must keep a late, field-bearing context Source.

    Route order contains the initial result/context pass followed by adaptive
    same-paper routes.  Truncating that order would omit a Methods Source even
    though it is the only item that can close the result's missing conditions.
    """

    current = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-strength",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    routes = [current]
    blocks = [
        _study_source_block(
            "result",
            "Results",
            "Tensile strength increased for the treated samples.",
            6,
        )
    ]
    for index in range(16):
        source_ref = f"background-{index}"
        routes.append(
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": "obj-strength",
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                    "role": "background_context",
                    "extractable": True,
                }
            )
        )
        blocks.append(
            _study_source_block(
                source_ref,
                "Introduction",
                f"Background discussion {index}.",
                index + 1,
            )
        )

    routes.append(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": "obj-strength",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "methods-late",
                "role": "process_or_treatment",
                "extractable": True,
                "context_fields": ["material", "variable", "comparison", "test"],
            }
        )
    )
    blocks.append(
        _study_source_block(
            "methods-late",
            "Methods",
            "Ti-6Al-4V samples S1 and S2 used laser power 180 W and 240 W; tensile tests followed ASTM E8.",
            20,
        )
    )

    bundle = source_extraction._build_objective_same_paper_context_bundle(
        route=current,
        routes=tuple(routes),
        blocks=blocks,
        tables=[],
        figures=[],
        document_tree=None,
        table_cells=[],
    )

    refs = [item["source_ref"] for item in bundle]
    assert "methods-late" in refs
    assert refs == ["methods-late"]


def test_same_paper_context_bundle_excludes_other_direct_result_sources() -> None:
    """A result anchor receives experiment context, not a second result claim.

    A researcher reading one reported result would use nearby Methods, sample,
    and test material to resolve its conditions.  Sending another independent
    Results block in the same context bundle lets the extractor silently mix
    experiments and can attribute the wrong variable or outcome to the anchor.
    """

    current = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-strength",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result-a",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    other_result = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-strength",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result-b",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    methods = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-strength",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-a",
            "role": "process_or_treatment",
            "context_fields": ["material", "variable", "test"],
            "extractable": True,
        }
    )

    bundle = source_extraction._build_objective_same_paper_context_bundle(
        route=current,
        routes=(current, other_result, methods),
        blocks=[
            _study_source_block(
                "result-a",
                "Results",
                "Yield strength increased for condition A.",
                6,
            ),
            _study_source_block(
                "result-b",
                "Results",
                "Elongation decreased for a separate heat-treatment series.",
                12,
            ),
            _study_source_block(
                "methods-a",
                "Methods",
                "Condition A used Ti-6Al-4V and ASTM E8 tensile testing.",
                4,
            ),
        ],
        tables=[],
        figures=[],
        document_tree=None,
        table_cells=[],
    )

    refs = [item["source_ref"] for item in bundle]
    assert "methods-a" in refs
    assert "result-b" not in refs


def test_validated_context_role_overrides_original_result_route_label() -> None:
    """A validated Methods fact remains context even after route misclassification."""

    current = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-property",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result-a",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    validated_methods = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "validated-methods",
            "objective_id": current.objective_id,
            "document_id": current.document_id,
            "source_kind": "text_window",
            "source_ref": "methods-a",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": None,
            "reported_result": None,
            "attribution_scope": "not_attributable",
            "scientific_context": {
                "sample": [{"name": "sample", "value": "Group B"}],
                "process": [
                    {"name": "treatment temperature", "value": 700, "unit": "C"}
                ],
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-a",
                    "role": "current_experimental_evidence",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    seed_routes = source_extraction._objective_seed_context_routes(
        units=(validated_methods,),
        route=current,
    )
    bundle = source_extraction._build_objective_same_paper_context_bundle(
        route=current,
        routes=(current, *seed_routes),
        blocks=[
            _study_source_block(
                "result-a",
                "Results",
                "The measured property changed for Group B.",
                6,
            ),
            _study_source_block(
                "methods-a",
                "Methods",
                "Group B was treated at 700 C before measurement.",
                3,
            ),
        ],
        tables=[],
        figures=[],
        document_tree=None,
        table_cells=[],
    )

    assert [(route.source_ref, route.role) for route in seed_routes] == [
        ("methods-a", "condition_context")
    ]
    assert [(item["source_ref"], item["role"]) for item in bundle] == [
        ("methods-a", "condition_context")
    ]


def test_empty_context_inspection_preserves_route_scope_for_later_result_read() -> None:
    """An empty first read remains a scoped Methods source, not generic background."""

    methods_route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-preheat",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-manufacturing",
            "role": "process_or_treatment",
            "extractable": True,
            "reason": "Selected to close fixed process context.",
            "context_fields": [],
        }
    )
    result_route = EvidenceCandidate.from_mapping(
        {
            "objective_id": methods_route.objective_id,
            "document_id": methods_route.document_id,
            "source_kind": "text_window",
            "source_ref": "results-microstructure",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    inspected = source_extraction._inspected_objective_source_draft(
        route=methods_route
    )
    seed_routes = source_extraction._objective_seed_context_routes(
        units=(inspected,),
        route=result_route,
    )

    assert inspected.source_refs == (
        {
            "source_kind": "text_window",
            "source_ref": "methods-manufacturing",
            "role": "process_or_treatment",
            "context_fields": [],
        },
    )
    assert [(route.source_ref, route.role, route.context_fields) for route in seed_routes] == [
        ("methods-manufacturing", "process_or_treatment", ("process",))
    ]


def test_result_recovery_route_names_the_context_still_missing_from_result() -> None:
    """A result reread tells extraction which experiment fields remain open."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheat",
            "material_scope": ["alloy A"],
            "variables": ["platform preheating"],
            "outcomes": ["grain morphology"],
        }
    )
    result_route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-microstructure",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-1",
            "objective_id": objective.objective_id,
            "document_id": result_route.document_id,
            "source_kind": result_route.source_kind,
            "source_ref": result_route.source_ref,
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "platform preheating",
                    "baseline_value": "without preheating",
                    "target_value": "with preheating",
                }
            ],
            "comparison": {
                "baseline_label": "without preheating",
                "target_label": "with preheating",
                "axis_names": ["platform preheating"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "grain morphology",
                "direction": "mixed",
                "result_text": "Grain morphology differed between the conditions.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "material", "value": "alloy A"}],
                "test": [{"name": "method", "value": "optical microscopy"}],
            },
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )
    shared_process = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "methods-1",
            "objective_id": objective.objective_id,
            "document_id": result_route.document_id,
            "source_kind": "text_window",
            "source_ref": "methods-manufacturing",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": None,
            "reported_result": None,
            "attribution_scope": "not_attributable",
            "scientific_context": {
                "process": [
                    {
                        "name": "manufacturing process",
                        "value": "laser powder bed fusion",
                        "context_scope": "experimental",
                    }
                ]
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    recovery_routes = source_extraction._objective_result_recovery_routes(
        source_facts=(result, shared_process),
        routes=(result_route,),
        attempted_keys=set(),
        objectives=(objective,),
    )

    assert len(recovery_routes) == 1
    assert recovery_routes[0].context_fields == ("process",)


def test_bundle_provenance_keeps_only_sources_matching_result_conditions() -> None:
    """Bundle provenance is field-supported rather than whole-bundle provenance."""

    item = source_extraction.StructuredEvidenceExtraction.model_validate(
        {
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 180,
                    "target_value": 240,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "yield strength",
                "direction": "increase",
                "result_text": "Yield strength increased from S1 to S2.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
        }
    )
    bundle_pairs = (
        (
            {
                "source_kind": "text_window",
                "source_ref": "methods-relevant",
                "text": "Sample S1 used laser power 180 W; S2 used 240 W.",
            },
            {
                "source_kind": "text_window",
                "source_ref": "methods-relevant",
                "supports": ["bundle_context"],
            },
        ),
        (
            {
                "source_kind": "text_window",
                "source_ref": "methods-unrelated",
                "text": "A separate heat-treatment series used 600 C.",
            },
            {
                "source_kind": "text_window",
                "source_ref": "methods-unrelated",
                "supports": ["bundle_context"],
            },
        ),
    )

    refs = source_extraction._objective_bundle_source_refs_for_record(
        item,
        bundle_pairs,
        existing_grounding_keys=set(),
    )

    assert [ref["source_ref"] for ref in refs] == ["methods-relevant"]


def test_same_paper_context_bundle_keeps_complete_table_before_background() -> None:
    """A complete result table is more useful context than incidental prose."""

    current = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-strength",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    routes = [current]
    blocks = [
        _study_source_block(
            "result",
            "Results",
            "Yield strength was compared across conditions.",
            6,
        )
    ]
    for index in range(16):
        source_ref = f"background-{index}"
        routes.append(
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": "obj-strength",
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                    "role": "background_context",
                    "extractable": True,
                }
            )
        )
        blocks.append(
            _study_source_block(
                source_ref,
                "Introduction",
                f"Background discussion {index}.",
                index + 1,
            )
        )

    routes.append(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": "obj-strength",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "result-table",
                "role": "current_experimental_evidence",
                "extractable": True,
            }
        )
    )
    table = SimpleNamespace(
        table_id="result-table",
        document_id="paper-1",
        page=7,
        caption_text="Yield strength by processing condition.",
        heading_path="Results",
        column_headers=("Condition", "Yield strength (MPa)"),
        table_matrix=(
            ("Condition", "Yield strength (MPa)"),
            ("A", "450"),
            ("B", "490"),
        ),
    )

    bundle = source_extraction._build_objective_same_paper_context_bundle(
        route=current,
        routes=tuple(routes),
        blocks=blocks,
        tables=[table],
        figures=[],
        document_tree=None,
        table_cells=[],
    )

    refs = [item["source_ref"] for item in bundle]
    assert "result-table" in refs
    assert refs == ["result-table"]


def test_source_validation_recovers_specific_variable_and_direction_from_result_clause():
    objective = _research_objective(
        {
            "objective_id": "obj-heat-treatment-elongation",
            "question": "How does heat treatment condition affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["heat treatment condition"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "abstract-result",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    source = {
        "source_kind": "text_window",
        "source_ref": "abstract-result",
        "page": 1,
        "text": (
            "The study investigates heat treatment process parameters, including "
            "temperature, time, and cooling rate. Increasing the cooling rate from "
            "furnace cooling to air cooling and finally to water quenching results "
            "in decreasing the elongation."
        ),
    }
    extracted_record = {
        "evidence_role": "direct_result",
        "changed_variables": [],
        "comparison": None,
        "reported_result": {
            "outcome": "elongation",
            "direction": "unknown",
            "result_text": (
                "Increasing the cooling rate from furnace cooling to air cooling and "
                "finally to water quenching results in decreasing the elongation."
            ),
        },
        "attribution_scope": "not_attributable",
        "scientific_context": {
            "material": [{"name": "material", "value": "Ti-6Al-4V"}]
        },
        "resolution_status": "partial",
        "confidence": 0.9,
    }

    records = source_validation.validate_source_fact(
        route=route,
        source=source,
        objective_context=objective,
        extracted_record=extracted_record,
        candidate_variables=(
            "heat treatment temperature",
            "heat treatment time",
            "cooling rate",
        ),
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == [
        {
            "name": "cooling rate",
            "baseline_value": None,
            "target_value": None,
            "unit": None,
        }
    ]
    assert records[0]["reported_result"]["direction"] == "decrease"
    assert records[0]["attribution_scope"] == "association_only"


def test_source_validation_retains_ungrounded_model_result_as_failed_evidence():
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
            "source_ref": "results-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "results-1",
            "text": "Relative density was reported for the tested conditions.",
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "relative density",
                "value": 99.7,
                "unit": "%",
                "direction": "increase",
                "result_text": "relative density increased to 99.7%",
            },
            "attribution_scope": "not_attributable",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.7,
        },
    )

    assert len(records) == 1
    assert records[0]["selection_status"] == "failed"
    assert records[0]["evidence_role"] == "irrelevant"
    assert "not grounded in SOURCE" in records[0]["failure_reason"]
    assert records[0]["source_refs"] == [
        {"source_kind": "text_window", "source_ref": "results-1"}
    ]


def test_source_validation_keeps_grounded_result_outside_objective_scope():
    """A neighboring measured outcome stays auditable but cannot answer the Objective."""

    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": "results-1",
            "text": (
                "Temperature increased from 500 C to 600 C. Elongation increased "
                "to 12%."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": "500 C",
                    "target_value": "600 C",
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "500 C",
                "target_label": "600 C",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": 12,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation increased to 12%.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["reported_result"]["outcome"] == "elongation"
    assert records[0]["changed_variables"][0]["name"] == "temperature"
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "descriptive_only"
    assert "outside" in records[0]["selection_reason"].casefold()


def test_source_validation_recovers_unique_objective_outcome_from_result_text():
    """A composite model label can be assigned when the Source names one target outcome."""

    objective = _research_objective(
        {
            "objective_id": "obj-fatigue-strength",
            "variables": ["volumetric energy density"],
            "outcomes": ["fatigue strength", "elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-fatigue",
            "source_kind": "text_window",
            "source_ref": "results-fatigue",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": "Fatigue strength increased from low VED to high VED.",
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": "low VED",
                    "target_value": "high VED",
                }
            ],
            "comparison": {
                "baseline_label": "low VED",
                "target_label": "high VED",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "fatigue life and elongation",
                "value": None,
                "unit": None,
                "direction": "increase",
                "result_text": "Fatigue strength increased from low VED to high VED.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["reported_result"]["outcome"] == "fatigue strength"
    assert records[0]["comparison"] is not None
    assert records[0]["attribution_scope"] == "isolated_effect"


def test_source_validation_keeps_ambiguous_composite_outcome_outside_scope():
    """A result sentence naming multiple targets must not be assigned by guesswork."""

    objective = _research_objective(
        {
            "objective_id": "obj-strength-ductility",
            "variables": ["volumetric energy density"],
            "outcomes": ["fatigue strength", "elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-fatigue",
            "source_kind": "text_window",
            "source_ref": "results-fatigue-ambiguous",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": "Fatigue strength and elongation increased with higher VED.",
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": "low VED",
                    "target_value": "high VED",
                }
            ],
            "comparison": {
                "baseline_label": "low VED",
                "target_label": "high VED",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "fatigue life and elongation",
                "value": None,
                "unit": None,
                "direction": "increase",
                "result_text": (
                    "Fatigue strength and elongation increased with higher VED."
                ),
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["reported_result"]["outcome"] == "fatigue life and elongation"
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "descriptive_only"
    assert "outside" in records[0]["selection_reason"].casefold()


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
        paper_map=None,
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
        paper_map=None,
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
        paper_map=None,
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
        paper_map=None,
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
        paper_map=None,
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
            paper_map=None,
        )


def test_objective_paper_frame_payload_uses_compact_lineage_scientific_prior():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect DIDX?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["DIDX"],
            "source_relationship_ids": ["relationship-density"],
        }
    )
    paper_map = PaperResearchMap.from_mapping(
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
            "outcome": "DIDX",
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
        paper_map=paper_map,
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
                    "relationships": [
                    {
                        "varied_factors": ["laser power"],
                        "outcome": "DIDX",
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
        paper_maps=(),
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
            paper_maps=(),
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
            paper_maps=(),
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
        paper_maps=(),
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
        paper_maps=(),
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
        paper_maps=(),
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
        paper_maps=(),
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
        paper_maps=(),
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


def test_objective_result_table_maps_symbol_conditions_to_broad_objective_axes():
    """A researcher can compare theta/alpha/beta rows under broad axes."""

    objective = _research_objective(
        {
            "objective_id": "obj-broad-angle-effects",
            "question": "How do scanning strategy and build orientation affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning strategy", "build orientation"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-symbol-table",
            "source_kind": "table",
            "source_ref": "table-yield-strength",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
            "column_roles": {
                "α (°)": "process_variable",
                "β (°)": "process_variable",
                "θ (°)": "process_variable",
                "Yield Strength Experiment (MPa)": "target_property",
            },
        }
    )
    source = {
        "source_kind": "table",
        "source_ref": route.source_ref,
        "document_id": route.document_id,
        "page": 8,
        "caption_text": (
            "The prediction and average experimental yield strength results "
            "for 316L stainless steel built with different scanning strategies "
            "and build orientations."
        ),
        "column_headers": [
            "α (°)",
            "β (°)",
            "θ (°)",
            "Yield Strength Experiment (MPa)",
        ],
        "table_matrix": [
            [
                "α (°)",
                "β (°)",
                "θ (°)",
                "Yield Strength Experiment (MPa)",
            ],
            ["0", "0", "0", "334.2"],
            ["45", "22.5", "45", "365.6"],
        ],
    }

    records = source_extraction._objective_table_matrix_evidence_records(
        route=route,
        source=source,
        objective_context=objective,
    )

    assert len(records) == 4
    result_records = [
        record for record in records if record["reported_result"] is not None
    ]
    assert len(result_records) == 2
    assert all(
        record["reported_result"]["outcome"] == "yield strength"
        for record in result_records
    )
    process_names = {
        attribute["name"]
        for record in result_records
        for attribute in record["scientific_context"]["process"]
    }
    assert process_names >= {
        "build orientation alpha angle",
        "build orientation beta angle",
        "scan strategy rotation angle",
    }
    assert {
        attribute["unit"]
        for record in result_records
        for attribute in record["scientific_context"]["process"]
        if attribute["name"] != "manufacturing process"
    } == {"°"}
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in records
    )
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )
    assert len(comparisons) == 1
    assert [item.name for item in comparisons[0].changed_variables] == [
        "build orientation alpha angle",
        "build orientation beta angle",
        "scan strategy rotation angle",
    ]


def test_current_result_route_retains_unrequested_symbol_conditions_and_context_rows():
    """A result table must preserve co-varied conditions for later comparison."""

    objective = _research_objective(
        {
            "objective_id": "obj-broad-angle-yield",
            "question": "How does scanning strategy affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning strategy"],
            "outcomes": ["yield strength"],
            "confidence": 0.9,
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-symbol-table",
            "source_kind": "table",
            "source_ref": "table-yield-strength",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
            # Routing may only identify the target column. Symbol columns must
            # still be retained as source-local process context.
            "column_roles": {
                "Yield Strength Experiment (MPa)": "target_property",
            },
        }
    )
    source = {
        "source_kind": "table",
        "source_ref": route.source_ref,
        "document_id": route.document_id,
        "page": 8,
        "caption_text": (
            "Average experimental yield strength for samples built with "
            "different scanning strategies and build orientations."
        ),
        "column_headers": [
            "alpha (deg)",
            "beta (deg)",
            "theta (deg)",
            "Yield Strength Experiment (MPa)",
        ],
        "table_matrix": [
            [
                "alpha (deg)",
                "beta (deg)",
                "theta (deg)",
                "Yield Strength Experiment (MPa)",
            ],
            ["0", "0", "0", "334.2"],
            ["45", "22.5", "45", "365.6"],
        ],
    }

    records = source_extraction._objective_table_matrix_evidence_records(
        route=route,
        source=source,
        objective_context=objective,
    )

    result_records = [
        record for record in records if record["reported_result"] is not None
    ]
    context_records = [
        record for record in records if record["reported_result"] is None
    ]
    assert len(result_records) == 2
    assert len(context_records) == 2
    assert all(
        {
            attribute["name"] for attribute in record["scientific_context"]["process"]
        }
        >= {
            "build orientation alpha angle",
            "build orientation beta angle",
            "scan strategy rotation angle",
        }
        for record in result_records
    )
    assert all(
        {
            attribute["name"] for attribute in record["scientific_context"]["process"]
        }
        >= {
            "build orientation alpha angle",
            "build orientation beta angle",
            "scan strategy rotation angle",
        }
        for record in context_records
    )


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
    assert comparison.attribution_scope == "association_only"
    assert comparison.comparison is not None
    assert comparison.comparison.axis_names == (
        "build orientation alpha angle",
        "build orientation beta angle",
        "scan strategy rotation angle",
    )


def test_objective_table_keeps_condition_values_units_and_comparison_labels():
    """A researcher should be able to read the same table-level comparison."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheat-elongation",
            "question": "How does build platform temperature condition affect elongation?",
            "material_scope": ["316L stainless steel"],
            "variables": ["build platform temperature condition"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheat",
            "source_kind": "table",
            "source_ref": "table-tensile",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
            "column_roles": {},
        }
    )
    source = {
        "source_kind": "table",
        "source_ref": route.source_ref,
        "caption_text": (
            "Monotonic tensile properties of 316L SS fabricated under argon "
            "shielding gas in non-preheated and preheated build platform conditions."
        ),
        "column_headers": [
            "Build platform conditions",
            "Yield strength (MPa)",
            "Ultimate tensile strength (MPa)",
            "El%",
        ],
        "table_matrix": [
            [
                "Build platform conditions",
                "Yield strength (MPa)",
                "Ultimate tensile strength (MPa)",
                "El%",
            ],
            ["Non-preheated", "448", "617", "72"],
            ["Preheated", "465", "618", "82"],
        ],
    }

    records = source_extraction._objective_table_matrix_evidence_records(
        route=route,
        source=source,
        objective_context=objective,
    )

    elongation = [
        record
        for record in records
        if record["reported_result"] is not None
        and record["reported_result"]["outcome"] == "elongation"
    ]
    assert [item["reported_result"]["unit"] for item in elongation] == ["%", "%"]
    assert [
        item["scientific_context"]["process"][0]["value"]
        for item in elongation
    ] == ["Non-preheated", "Preheated"]
    assert [
        item["source_refs"][0]["row_index"] for item in elongation
    ] == [1, 2]

    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record) for record in elongation
    )
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.comparison is not None
    assert comparison.comparison.baseline_label == "Non-preheated"
    assert comparison.comparison.target_label == "Preheated"
    assert comparison.reported_result is not None
    assert comparison.reported_result.baseline_value == 72.0
    assert comparison.reported_result.target_value == 82.0
    assert comparison.reported_result.unit == "%"


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

    assert len(records) == 1
    assert records[0]["selection_status"] == "failed"
    assert records[0]["evidence_role"] == "irrelevant"
    assert records[0]["attribution_scope"] == "not_attributable"
    assert "Source grounding failed" in records[0]["failure_reason"]
    assert records[0]["source_refs"] == [
        {"source_kind": "text_window", "source_ref": "block-strategies"}
    ]


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


def test_empty_context_inspection_is_trace_only_not_scientific_evidence() -> None:
    """Reading a context Source without facts must not create fake Evidence."""

    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["laser power"],
            "outcomes": ["tensile strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-empty",
            "role": "process_or_treatment",
            "extractable": True,
            "reason": "Inspect same-paper process context.",
            "confidence": 0.9,
        }
    )
    block = _study_source_block(
        "methods-empty",
        "Methods",
        "The paper describes the experimental setup without reporting a condition.",
        2,
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": "frame:text_window:methods-empty",
                    "source_kind": "text_window",
                    "source_ref": "methods-empty",
                    "disposition": "model_relevant",
                }
            ],
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        drafts = extract_and_validate_source_facts(
            collection_id="col-test",
            source_extractor=_StudySourceEvidenceExtractor(
                {"methods-empty": None}
            ),
            objectives=(objective,),
            objective_paper_frames=(frame,),
            objective_evidence_routes=(route,),
            blocks_by_document_id={"paper-1": [block]},
            tables_by_document_id={"paper-1": []},
            document_trees_by_document_id={},
            _allow_adaptive_context_expansion=False,
        )
        evidence_records, contributions = evidence_materialization.materialize_evidence(
            collection_id="col-test",
            analysis=analysis,
            objective=objective,
            drafts=drafts,
            paper_maps=(),
            frames=(frame,),
            routes=(route,),
            blocks_by_document_id={"paper-1": [block]},
            tables_by_document_id={},
            figures_by_document_id={},
        )

    assert evidence_records == ()
    assert contributions[0].uninspected_source_count == 0
    inspection_trace = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_source_inspection"
    )
    assert inspection_trace["disposition"] == "no_source_grounded_fact"
    ledger = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_source_coverage_ledger"
    )
    assert ledger["inspected_source_count"] == 1
    assert ledger["uninspected_source_count"] == 0


def test_omitted_extraction_confidence_uses_route_fallback() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    route = _study_source_route(objective.objective_id, "results-1")
    block = _study_source_block(
        "results-1",
        "Results",
        "Relative density increased from 95% at 100 W to 98% at 140 W.",
        4,
    )

    class OmittedConfidenceExtractor:
        def extract_source(self, payload):  # noqa: ANN001
            return StructuredEvidenceExtractions.model_validate(
                {
                    "extractions": [
                        {
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
                                "value": 98,
                                "baseline_value": 95,
                                "target_value": 98,
                                "unit": "%",
                                "direction": "increase",
                                "result_text": (
                                    "Relative density increased from 95% at 100 W "
                                    "to 98% at 140 W."
                                ),
                            },
                            "attribution_scope": "isolated_effect",
                            "resolution_status": "resolved",
                        }
                    ]
                }
            )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=OmittedConfidenceExtractor(),
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={},
        document_trees_by_document_id={},
        _allow_adaptive_context_expansion=False,
    )

    result = next(item for item in drafts if item.reported_result is not None)
    assert result.confidence == 0.9


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


def test_method_context_is_not_created_for_paper_outside_objective_route_scope() -> None:
    """A screened paper is not Objective Evidence until it enters deep reading."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheating-microstructure",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    frames = tuple(
        PaperAnalysisFrame.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": document_id,
                "relevance": "high",
                "paper_role": "primary_experiment",
            }
        )
        for document_id in ("paper-in-scope", "paper-out-of-scope")
    )
    result_block = SimpleNamespace(
        block_id="result-in-scope",
        document_id="paper-in-scope",
        page=5,
        block_type="paragraph",
        heading_path="Results",
        text="Build platform preheating changed the observed microstructure.",
    )
    unrelated_method_block = SimpleNamespace(
        block_id="method-out-of-scope",
        document_id="paper-out-of-scope",
        page=3,
        block_type="paragraph",
        heading_path="Methods",
        text="The microstructure was examined using SEM.",
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-in-scope",
            "source_kind": "text_window",
            "source_ref": result_block.block_id,
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    class EmptyExtractor:
        def extract_source(self, payload: dict[str, Any]):
            return StructuredEvidenceExtractions()

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=EmptyExtractor(),
        objectives=(objective,),
        objective_paper_frames=frames,
        objective_evidence_routes=(route,),
        blocks_by_document_id={
            "paper-in-scope": [result_block],
            "paper-out-of-scope": [unrelated_method_block],
        },
        tables_by_document_id={},
        document_trees_by_document_id={},
        _allow_adaptive_context_expansion=False,
    )

    assert {draft.document_id for draft in drafts} == {"paper-in-scope"}


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
                    {"name": "hatch spacing", "value": 0.1, "unit": "mm"},
                ],
                "test": [
                    {"name": "optical microscopy", "value": "optical microscopy"}
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
            (
                "Sample S1 used laser power 180 W, scanning speed 600 mm/s, "
                "and hatch spacing 0.1 mm before optical microscopy."
            ),
            2,
        ),
        _study_source_block(
            "02-methods-s2",
            "Methods",
            (
                "Sample S2 used laser power 240 W, scanning speed 900 mm/s, "
                "and hatch spacing 0.1 mm before optical microscopy."
            ),
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
    with capture_analysis_diagnostics() as diagnostics:
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
    assert not any(
        record["trace_type"] == "objective_context_scope_gap"
        for record in diagnostics.records
    )
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
                    "scientific_context.test",
            ),
        ),
        (
            "02-methods-s2",
            (
                "changed_variables",
                "comparison.axis_names",
                    "scientific_context.sample",
                    "scientific_context.process",
                    "scientific_context.test",
            ),
        ),
        ("03-results", ("comparison.labels", "reported_result")),
    }

    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
        paper_maps=(),
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


def test_empty_model_result_keeps_source_as_needs_context_candidate() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Porosity decreased as laser power increased, but the comparison condition is described in Table 3.",
        6,
    )
    extractor = _StudySourceEvidenceExtractor(
        {"03-results": None}
    )

    drafts = extract_and_validate_source_facts(
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

    assert len(drafts) == 1
    assert drafts[0].selection_status == "candidate"
    assert drafts[0].reported_result is None
    assert drafts[0].resolution_status == "unresolved"
    assert drafts[0].selection_reason is not None
    assert drafts[0].selection_reason.startswith(
        "Target outcome mentioned but needs same-paper context."
    )


def test_empty_selected_result_keeps_direct_result_role_when_reason_mentions_context() -> None:
    """A selected result needing context must not be demoted to context-only evidence."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "The porosity result is reported for the two process conditions.",
        6,
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": result_block.block_id,
            "role": "current_experimental_evidence",
            "extractable": True,
            "reason": "Selected result Source needs same-paper context.",
            "confidence": 0.9,
        }
    )
    extractor = _StudySourceEvidenceExtractor({result_block.block_id: None})

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [result_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
        _allow_adaptive_context_expansion=False,
    )

    assert len(drafts) == 1
    assert drafts[0].evidence_role == "direct_result"
    assert drafts[0].selection_status == "candidate"
    assert drafts[0].reported_result is None
    assert drafts[0].resolution_status == "unresolved"
    assert drafts[0].selection_reason == (
        "Selected result Source needs same-paper context."
    )


def test_empty_context_route_is_kept_only_in_inspection_ledger() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    methods_block = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "The specimens were prepared before the porosity measurement.",
        2,
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": methods_block.block_id,
            "role": "process_or_treatment",
            "extractable": True,
            "reason": "Same-paper context expansion for missing fields: process.",
            "confidence": 0.8,
        }
    )
    extractor = _StudySourceEvidenceExtractor({methods_block.block_id: None})

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [methods_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert len(drafts) == 1
    assert drafts[0].evidence_role == "irrelevant"
    assert drafts[0].selection_status == "rejected"
    assert drafts[0].resolution_status == "skipped"
    assert drafts[0].reported_result is None
    assert drafts[0].source_refs == (
        {
            "source_kind": "text_window",
            "source_ref": "01-methods",
            "role": "process_or_treatment",
            "context_fields": [],
        },
    )
    assert "inspected" in (drafts[0].selection_reason or "").casefold()


def test_empty_selected_source_is_retained_when_target_is_not_explicitly_mentioned() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    methods_block = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "The specimens were fabricated with a controlled laser process.",
        2,
    )
    extractor = _StudySourceEvidenceExtractor({methods_block.block_id: None})

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": methods_block.block_id,
                    "role": "current_experimental_evidence",
                    "extractable": True,
                    "reason": "Read the same-paper process context.",
                    "confidence": 0.8,
                }
            ),
        ),
        blocks_by_document_id={"paper-1": [methods_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert len(drafts) == 1
    assert drafts[0].source_ref == methods_block.block_id
    assert drafts[0].selection_status == "rejected"
    assert drafts[0].evidence_role == "irrelevant"
    assert drafts[0].reported_result is None
    assert drafts[0].resolution_status == "skipped"
    assert drafts[0].selection_reason is not None
    assert "inspected" in drafts[0].selection_reason.casefold()


def test_empty_direct_result_route_is_retained_without_keyword_match() -> None:
    """A selected result Source must survive synonym/OCR misses in the detector."""
    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["thermal dose"],
            "outcomes": ["tensile strength"],
        }
    )
    result_block = _study_source_block(
        "results-strength",
        "Results",
        "The measured response increased between the two treatment groups.",
        6,
    )
    extractor = _StudySourceEvidenceExtractor({result_block.block_id: None})
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": result_block.block_id,
            "role": "current_experimental_evidence",
            "extractable": True,
            "reason": "The routing model selected this result Source.",
            "confidence": 0.8,
        }
    )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [result_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert len(drafts) == 1
    assert drafts[0].source_ref == result_block.block_id
    assert drafts[0].evidence_role == "direct_result"
    assert drafts[0].selection_status == "candidate"
    assert drafts[0].resolution_status == "unresolved"
    assert drafts[0].reported_result is None
    assert "context" in (drafts[0].selection_reason or "").casefold()


def test_selected_result_source_is_retained_when_validated_model_record_is_empty() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-yield-strength",
            "variables": ["scan strategy rotation angle", "build orientation"],
            "outcomes": ["yield strength"],
        }
    )
    abstract_block = _study_source_block(
        "abstract-result-scope",
        "Abstract",
        (
            "The study evaluates scan strategy rotation and build orientation "
            "against the mechanical response of 316L stainless steel."
        ),
        1,
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": abstract_block.block_id,
            "role": "current_experimental_evidence",
            "extractable": True,
            "reason": "Deterministic recall override: direct Objective result Source.",
            "confidence": 0.72,
        }
    )
    # The provider returned valid JSON, but deterministic validation removes all
    # scientific payload because the record contains no source-grounded fact.
    extractor = _StudySourceEvidenceExtractor({abstract_block.block_id: {}})

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [abstract_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
        _allow_adaptive_context_expansion=False,
    )

    assert len(drafts) == 1
    assert drafts[0].source_ref == abstract_block.block_id
    assert drafts[0].evidence_role == "direct_result"
    assert drafts[0].selection_status == "candidate"
    assert drafts[0].reported_result is None
    assert drafts[0].resolution_status == "unresolved"
    assert drafts[0].selection_reason == (
        "Selected result Source needs same-paper context."
    )


def test_successfully_inspected_extractable_source_leaves_trace_only_marker() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-yield-strength",
            "variables": ["scan strategy rotation angle", "build orientation"],
            "outcomes": ["yield strength"],
        }
    )
    abstract_block = _study_source_block(
        "abstract-study-scope",
        "Abstract",
        (
            "The study evaluates scan strategy rotation and build orientation "
            "for 316L stainless steel."
        ),
        1,
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": abstract_block.block_id,
            "role": "composition_or_background",
            "extractable": True,
            "reason": "Selected to establish paper scope.",
            "confidence": 0.7,
        }
    )
    extractor = _StudySourceEvidenceExtractor({abstract_block.block_id: None})

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [abstract_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
        _allow_adaptive_context_expansion=False,
    )

    assert len(drafts) == 1
    assert drafts[0].source_ref == abstract_block.block_id
    assert drafts[0].evidence_role == "irrelevant"
    assert drafts[0].selection_status == "rejected"
    assert drafts[0].resolution_status == "skipped"
    assert drafts[0].reported_result is None


def test_adaptive_context_uses_nearby_source_when_no_lexical_marker_matches() -> None:
    """Structural proximity is a recall fallback, not scientific closure."""
    objective = _research_objective(
        {
            "objective_id": "obj-response",
            "variables": ["treatment dose"],
            "outcomes": ["response rate"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "result-3")
    result_candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    nearby_context = _study_source_block(
        "context-2",
        "Unsectioned",
        "Groups A and B followed the same protocol before assessment.",
        5,
    )
    distant_noise = _study_source_block(
        "noise-1",
        "Unsectioned",
        "The authors acknowledge limitations of the discussion.",
        1,
    )
    result_block = _study_source_block(
        "result-3",
        "Unsectioned",
        "The measured response increased between Groups A and B.",
        6,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(result_candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={
            "paper-1": [distant_noise, nearby_context, result_block]
        },
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["context-2"]
    assert routes[0].context_fields == ()
    assert "structural" in routes[0].reason.casefold()


def test_needs_context_candidate_selects_same_paper_context_routes() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    methods = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "Samples were fabricated at two laser power levels.",
        2,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={"paper-1": [methods]},
        tables_by_document_id={"paper-1": []},
    )

    assert [(route.document_id, route.source_ref, route.role) for route in routes] == [
        ("paper-1", "01-methods", "process_or_treatment")
    ]


def test_adaptive_context_reads_frame_relevant_source_omitted_by_initial_router() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["alloy X"],
            "variables": ["thermal dose"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "results-block")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    methods_block = SimpleNamespace(
        block_id="methods-block",
        document_id="paper-1",
        page=2,
        block_type="paragraph",
        heading_path="",
        text="The study was conducted as described.",
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
                child_ids=("methods-block-node",),
                node_type="section",
                order=100,
                title="Additional information",
                heading_path=("Additional information",),
            ),
            "methods-block-node": SourceDocumentNode(
                node_id="methods-block-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=101,
                text=methods_block.text,
                heading_path=(),
                source_ref_kind="block",
                source_ref_id=methods_block.block_id,
            ),
        },
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": "frame:section:methods",
                    "source_kind": "section",
                    "source_ref": "methods-section",
                    "disposition": "model_relevant",
                }
            ],
        }
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={"paper-1": [methods_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [(route.source_kind, route.source_ref) for route in routes] == [
        ("text_window", "methods-block")
    ]
    source = source_extraction._build_objective_route_source_payload(
        route=routes[0],
        blocks=[methods_block],
        tables=[],
        document_tree=document_tree,
    )
    assert source["text"] == methods_block.text


def test_adaptive_context_does_not_deep_read_every_frame_positive_source() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["alloy X"],
            "variables": ["thermal dose"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "results-block")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    generic_blocks = [
        _study_source_block(
            f"methods-{position}",
            "Materials and Methods",
            "The experimental procedure was documented for the study.",
            position,
        )
        for position in range(1, 21)
    ]
    experiment_context = _study_source_block(
        "experiment-context",
        "Materials and Methods",
        (
            "Alloy X specimens A and B received thermal doses of 10 and 20 "
            "minutes, respectively, before porosity measurement."
        ),
        21,
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": f"frame:block:{block.block_id}",
                    "source_kind": "block",
                    "source_ref": block.block_id,
                    "disposition": "model_relevant",
                }
                for block in [*generic_blocks, experiment_context]
            ],
        }
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        objective_paper_frames=(frame,),
        blocks_by_document_id={
            "paper-1": [*generic_blocks, experiment_context]
        },
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["experiment-context"]


def test_adaptive_context_selects_context_for_each_incomplete_result_anchor() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["alloy X"],
            "variables": ["thermal dose"],
            "outcomes": ["porosity"],
        }
    )

    def result(source_ref: str, baseline_label: str, target_label: str):
        return source_extraction.ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"evidence-{source_ref}",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": source_ref,
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [],
                "comparison": {
                    "baseline_label": baseline_label,
                    "target_label": target_label,
                    "axis_names": ["thermal dose"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "porosity",
                    "value": 0.5,
                    "unit": "%",
                    "direction": "decrease",
                    "result_text": (
                        f"Porosity decreased from {baseline_label} to {target_label}."
                    ),
                },
                "attribution_scope": "association_only",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.9,
            }
        )

    result_a = result("results-a", "Group Alpha", "Group Beta")
    result_b = result("results-b", "Group Gamma", "Group Delta")
    context_a = _study_source_block(
        "methods-a",
        "Materials and Methods",
        (
            "Alloy X specimens in Group Alpha and Group Beta received thermal "
            "doses of 10 and 20 minutes before porosity measurement."
        ),
        1,
    )
    context_b = _study_source_block(
        "methods-b",
        "Materials and Methods",
        (
            "Alloy X specimens in Group Gamma and Group Delta received thermal "
            "doses of 30 and 40 minutes before porosity measurement."
        ),
        2,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(result_a, result_b),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, "results-a"),
            _study_source_route(objective.objective_id, "results-b"),
        ),
        blocks_by_document_id={"paper-1": [context_a, context_b]},
        tables_by_document_id={"paper-1": []},
    )

    assert {route.source_ref for route in routes} == {"methods-a", "methods-b"}


def test_adaptive_context_uses_tree_parent_when_source_block_has_no_heading() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-tree-context",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    methods_block = SimpleNamespace(
        block_id="methods-block",
        document_id="paper-1",
        text="Samples were prepared at two laser power levels before porosity testing.",
        heading_path="",
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
                child_ids=("methods-block-node",),
                node_type="section",
                order=100,
                title="Materials and Methods",
                heading_path=("Materials and Methods",),
            ),
            "methods-block-node": SourceDocumentNode(
                node_id="methods-block-node",
                document_id="paper-1",
                parent_id="methods-section",
                child_ids=(),
                node_type="paragraph",
                order=101,
                text=methods_block.text,
                heading_path=(),
                source_ref_kind="block",
                source_ref_id="methods-block",
            ),
        },
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={"paper-1": [methods_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={"paper-1": document_tree},
    )

    assert [(route.source_ref, route.role) for route in routes] == [
        ("methods-block", "process_or_treatment")
    ]


def test_adaptive_context_reads_generic_experimental_design_without_domain_terms() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-roughness",
            "variables": ["thermal dose"],
            "outcomes": ["surface roughness"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "results-roughness")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    experimental_design = _study_source_block(
        "design-1",
        "Study design",
        "Groups A and B followed the same procedure before assessment.",
        2,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={"paper-1": [experimental_design]},
        tables_by_document_id={"paper-1": []},
    )

    assert "design-1" in {route.source_ref for route in routes}


def test_adaptive_context_selects_one_bundle_for_rows_in_the_same_result_series() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-response",
            "material_scope": ["material system"],
            "variables": ["treatment level"],
            "outcomes": ["response magnitude"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "table-results")

    def result_row(evidence_id: str, sample_label: str, value: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-results",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "reported_result": {
                    "outcome": "response magnitude",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"response magnitude = {value} %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample", "value": sample_label}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-results",
                    }
                ],
                "resolution_status": "partial",
                "confidence": 0.8,
            }
        )

    alpha_context = _study_source_block(
        "methods-alpha",
        "Methods",
        (
            "Sample Alpha used the material system at treatment level 1 before "
            "the response magnitude test comparison."
        ),
        1,
    )
    beta_context = _study_source_block(
        "methods-beta",
        "Methods",
        (
            "Sample Beta used the material system at treatment level 2 before "
            "the response magnitude test comparison."
        ),
        2,
    )
    series_context = _study_source_block(
        "methods-series",
        "Methods",
        (
            "Samples Alpha and Beta used the material system at treatment levels "
            "1 and 2 before the response magnitude test comparison."
        ),
        3,
    )

    with capture_analysis_diagnostics() as diagnostics:
        routes = source_extraction._build_adaptive_context_routes(
            objectives=(objective,),
            source_facts=(
                result_row("result-alpha", "Alpha", 72.0),
                result_row("result-beta", "Beta", 82.0),
            ),
            objective_evidence_routes=(result_route,),
            blocks_by_document_id={
                "paper-1": [alpha_context, beta_context, series_context]
            },
            tables_by_document_id={"paper-1": []},
        )

    assert [route.source_ref for route in routes] == ["methods-series"]
    audit = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_context_scope_audit"
    )
    assert audit["result_anchor_count"] == 2
    assert audit["result_group_count"] == 1
    assert len(audit["anchor_decisions"]) == 1


def test_adaptive_context_trace_does_not_claim_scientific_closure_for_candidates():
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    context_block = _study_source_block(
        "01-methods",
        "Materials and Methods",
        (
            "Samples were prepared at two laser power conditions for a porosity "
            "test comparison."
        ),
        2,
    )

    with capture_analysis_diagnostics() as diagnostics:
        routes = source_extraction._build_adaptive_context_routes(
            objectives=(objective,),
            source_facts=(candidate,),
            objective_evidence_routes=(result_route,),
            blocks_by_document_id={"paper-1": [context_block]},
            tables_by_document_id={"paper-1": []},
        )

    assert routes
    audit = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_context_scope_audit"
    )
    assert audit["candidate_coverage_complete"] is True
    assert audit["evidence_grounding_complete"] is False
    assert audit["closure_basis"] == "candidate_source_match_only"
    assert "closure_complete" not in audit


def test_adaptive_context_keeps_late_source_that_contains_missing_objective_context() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    filler_blocks = [
        _study_source_block(
            f"methods-{position}",
            "Materials and Methods",
            "The specimen preparation procedure was documented.",
            position,
        )
        for position in range(1, 13)
    ]
    late_comparison_block = _study_source_block(
        "methods-13",
        "Materials and Methods",
        "S1 was fabricated from Ti-6Al-4V at 150 W laser power, while S2 used 200 W.",
        13,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={
            "paper-1": [*filler_blocks, late_comparison_block]
        },
        tables_by_document_id={"paper-1": []},
    )

    assert "methods-13" in {route.source_ref for route in routes}


def test_adaptive_context_prefers_reordered_variable_with_explicit_endpoints() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-elongation",
            "variables": ["build platform preheating"],
            "outcomes": ["elongation"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "table-results")
    candidate = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "elongation-row",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-results",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "reported_result": {
                "outcome": "elongation",
                "value": 82,
                "unit": "%",
                "direction": "unknown",
                "result_text": "elongation = 82 %",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-results",
                    "row_index": 2,
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )
    topic_overview = _study_source_block(
        "abstract-overview",
        "Abstract",
        "This study examines build platform preheating and elongation.",
        1,
    )
    explicit_design = _study_source_block(
        "methods-design",
        "Experimental Procedures",
        (
            "Two experiments were performed, one with preheating the build "
            "platform to 150 C and one without preheating."
        ),
        2,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={
            "paper-1": [topic_overview, explicit_design]
        },
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["methods-design"]


def test_complete_result_still_selects_same_paper_fixed_process_controls() -> None:
    """A result pair is not a complete experiment without its fixed settings."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheating-microstructure",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "results-microstructure")
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "microstructure-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": result_route.source_ref,
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": "without preheating",
                    "target_value": "preheating to 150 C",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["build platform preheating"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "The preheated group developed an equiaxed cellular structure.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "test": [
                    {
                        "name": "characterization method",
                        "value": "optical microscopy",
                    }
                ]
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": result_route.source_ref,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    fixed_controls = _study_source_block(
        "methods-fixed-controls",
        "Experimental Procedures",
        (
            "Both groups used a layer thickness of 50 um, hatch spacing of "
            "0.11 mm, laser power of 200 W, and scan speed of 1833 mm/s. "
            "Microstructure was characterized by optical microscopy."
        ),
        3,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(result,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={"paper-1": [fixed_controls]},
        tables_by_document_id={"paper-1": []},
    )

    assert source_extraction._objective_missing_context_fields(result, objective) == {
        "process"
    }
    assert [route.source_ref for route in routes] == ["methods-fixed-controls"]
    assert routes[0].context_fields == ("process",)


def test_fixed_process_controls_join_result_with_methods_source_lineage() -> None:
    """Shared Methods settings remain fixed context, never changed variables."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheating-microstructure",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    result_block = _study_source_block(
        "results-microstructure",
        "Results",
        (
            "Optical microscopy showed that, compared with NP fabricated "
            "without preheating, P150 fabricated "
            "with build platform preheating to 150 C developed an equiaxed "
            "cellular structure."
        ),
        7,
    )
    controls_block = _study_source_block(
        "methods-fixed-controls",
        "Experimental Procedures",
        (
            "Both groups used a layer thickness of 50 um, hatch spacing of "
            "0.11 mm, laser power of 200 W, and scan speed of 1833 mm/s. "
            "Microstructure was characterized by optical microscopy."
        ),
        3,
    )
    unrelated_process_block = _study_source_block(
        "methods-calibration",
        "Experimental Procedures",
        "A separate calibration specimen used a scan speed of 900 mm/s.",
        4,
    )
    extractor = _StudySourceEvidenceExtractor(
        {
            "results-microstructure": {
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "build platform preheating",
                        "baseline_value": "without preheating",
                        "target_value": "preheating to 150 C",
                    }
                ],
                "comparison": {
                    "baseline_label": "NP",
                    "target_label": "P150",
                    "axis_names": ["build platform preheating"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "microstructure",
                    "direction": "mixed",
                    "result_text": result_block.text,
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {
                    "test": [
                        {
                            "name": "optical microscopy",
                            "value": "optical microscopy",
                        }
                    ]
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            },
            "methods-fixed-controls": {
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "process": [
                        {"name": "layer thickness", "value": 50, "unit": "um"},
                        {"name": "hatch spacing", "value": 0.11, "unit": "mm"},
                        {"name": "laser power", "value": 200, "unit": "W"},
                        {"name": "scan speed", "value": 1833, "unit": "mm/s"},
                    ],
                    "test": [
                        {
                            "name": "characterization method",
                            "value": "optical microscopy",
                        }
                    ],
                },
                "resolution_status": "resolved",
                "confidence": 0.95,
            },
            "methods-calibration": None,
        }
    )

    source_facts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={
            "paper-1": [
                controls_block,
                unrelated_process_block,
                result_block,
            ]
        },
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )
    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="col-test",
        source_facts=source_facts,
        objectives=(objective,),
    )

    assert extractor.calls == ["results-microstructure", "methods-fixed-controls"]
    result = next(item for item in reconstructed if item.reported_result is not None)
    assert [item.name for item in result.changed_variables] == [
        "build platform preheating"
    ]
    assert {item.name for item in result.scientific_context.process} == {
        "layer thickness",
        "hatch spacing",
        "laser power",
        "scan speed",
    }
    controls_ref = next(
        ref
        for ref in result.source_refs
        if ref["source_ref"] == "methods-fixed-controls"
    )
    assert "scientific_context.process" in controls_ref["supports"]


def test_context_binding_changed_axis_alone_does_not_close_fixed_process() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-temperature-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "strength",
                "direction": "increase",
                "result_text": "Strength increased from S1 to S2.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    changed_axis_context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "context-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "process": [{"name": "temperature", "value": 500, "unit": "C"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert not source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(changed_axis_context,),
        objective=objective,
    )


@pytest.mark.parametrize(
    ("baseline_spacing", "target_spacing", "expected"),
    ((0.1, 0.1, True), (0.1, 0.12, False)),
)
def test_context_binding_requires_group_shared_fixed_process_controls(
    baseline_spacing: float,
    target_spacing: float,
    expected: bool,
) -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-temperature-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "strength",
                "direction": "increase",
                "result_text": "Strength increased from S1 to S2.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    def group_context(label: str, temperature: int, spacing: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"context-{label}",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "conditions-1",
                "evidence_role": "condition_context",
                "selection_status": "extracted",
                "scientific_context": {
                    "sample": [{"name": "group", "value": label}],
                    "process": [
                        {"name": "temperature", "value": temperature, "unit": "C"},
                        {"name": "hatch spacing", "value": spacing, "unit": "mm"},
                    ],
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    can_bind = source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(
            group_context("S1", 500, baseline_spacing),
            group_context("S2", 600, target_spacing),
        ),
        objective=objective,
    )

    assert can_bind is expected


def test_context_binding_does_not_borrow_fixed_process_from_another_paper() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-temperature-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "strength",
                "direction": "increase",
                "result_text": "Strength increased from S1 to S2.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    other_paper_controls = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "context-paper-2",
            "objective_id": objective.objective_id,
            "document_id": "paper-2",
            "source_kind": "text_window",
            "source_ref": "methods-2",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "process": [
                    {"name": "hatch spacing", "value": 0.1, "unit": "mm"}
                ],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert not source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(other_paper_controls,),
        objective=objective,
    )


def test_adaptive_context_does_not_revisit_result_source_when_context_is_unresolved():
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Porosity decreased, but the comparison condition is not stated here.",
        6,
    )
    methods_block = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "Specimens were prepared before porosity measurement.",
        2,
    )
    extractor = _StudySourceEvidenceExtractor(
        {
            "03-results": {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": None,
                "reported_result": {
                    "outcome": "porosity",
                    "direction": "decrease",
                    "result_text": "Porosity decreased.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.8,
            },
            "01-methods": None,
        }
    )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={"paper-1": [methods_block, result_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls == ["03-results", "01-methods"]
    result_drafts = [draft for draft in drafts if draft.source_ref == "03-results"]
    assert len(result_drafts) == 1
    assert result_drafts[0].reported_result is not None
    assert result_drafts[0].resolution_status == "partial"


def test_source_extraction_reads_duplicate_source_locator_once():
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Porosity decreased from the baseline condition.",
        6,
    )
    extractor = _StudySourceEvidenceExtractor(
        {
            "03-results": {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": None,
                "reported_result": {
                    "outcome": "porosity",
                    "direction": "decrease",
                    "result_text": "Porosity decreased from the baseline condition.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.8,
            }
        }
    )
    first_route = _study_source_route(objective.objective_id, result_block.block_id)
    duplicate_route = EvidenceCandidate.from_mapping(
        {
            **first_route.to_record(),
            "role": "process_or_treatment",
            "reason": "Same Source selected for context.",
        }
    )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(first_route, duplicate_route),
        blocks_by_document_id={"paper-1": [result_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls == ["03-results"]
    assert len([draft for draft in drafts if draft.source_ref == "03-results"]) == 1


def test_adaptive_context_bounds_broad_same_paper_expansion_without_losing_exact_match() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    generic_blocks = [
        _study_source_block(
            f"methods-{position}",
            "Materials and Methods",
            "The specimen preparation procedure and measurement workflow were documented.",
            position,
        )
        for position in range(1, 31)
    ]
    exact_match = _study_source_block(
        "methods-exact",
        "Materials and Methods",
        "S1 was fabricated from Ti-6Al-4V at 150 W laser power and measured for porosity.",
        31,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={"paper-1": [*generic_blocks, exact_match]},
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["methods-exact"]
    assert "methods-exact" in {route.source_ref for route in routes}


def test_adaptive_context_does_not_drop_explicit_late_source_after_fixed_quota() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    distractor_blocks = [
        _study_source_block(
            f"methods-{position}",
            "Materials and Methods",
            (
                "The Ti-6Al-4V specimen used laser power and porosity was "
                "measured for this condition."
            ),
            position,
        )
        for position in range(1, 14)
    ]
    late_explicit_source = _study_source_block(
        "methods-explicit-late",
        "Materials and Methods",
        (
            "S1 was fabricated from Ti-6Al-4V at 150 W laser power, while S2 "
            "used 200 W; the specimens were measured for porosity."
        ),
        len(distractor_blocks) + 1,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={
            "paper-1": [*distractor_blocks, late_explicit_source]
        },
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["methods-explicit-late"]


def test_adaptive_context_prefers_minimum_source_set_over_generic_methods_filler() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "03-results")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    generic_blocks = [
        _study_source_block(
            f"methods-{position}",
            "Materials and Methods",
            "The specimen preparation procedure and measurement workflow were documented.",
            position,
        )
        for position in range(1, 31)
    ]
    complete_context = _study_source_block(
        "methods-complete",
        "Materials and Methods",
        (
            "S1 was fabricated from Ti-6Al-4V at 150 W laser power, while S2 "
            "used 200 W; the specimens were measured for porosity."
        ),
        len(generic_blocks) + 1,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={
            "paper-1": [*generic_blocks, complete_context]
        },
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["methods-complete"]


def test_adaptive_context_stops_when_new_sources_repeat_same_context_without_closing_result() -> None:
    """Repeated context becomes a scope gap without rereading the result Source."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "results-porosity",
        "Results",
        (
            "Porosity decreased from 1.2% in S1 to 0.4% in S2 as laser power "
            "changed, but the study does not state the comparison conditions here."
        ),
        10,
    )
    repeated_methods = [
        _study_source_block(
            f"methods-{position}",
            "Materials and Methods",
            (
                "The specimens were labeled S1 and S2. Laser power was used during "
                "fabrication and porosity was measured."
            ),
            position,
        )
        for position in range(1, 8)
    ]
    result_record = {
        "evidence_role": "direct_result",
        # The result source names only sample labels (S1/S2), not the laser
        # power levels assigned to them.  Keep the variable unresolved so the
        # test exercises the scope-gap path instead of treating sample labels
        # as experimental endpoints.
        "changed_variables": [],
        "comparison": {
            "baseline_label": "S1",
            "target_label": "S2",
            "axis_names": ["laser power"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "porosity",
            "value": 0.4,
            "baseline_value": 1.2,
            "target_value": 0.4,
            "unit": "%",
            "direction": "decrease",
            "result_text": "Porosity decreased from 1.2% in S1 to 0.4% in S2.",
        },
        "attribution_scope": "association_only",
        "scientific_context": {},
        "resolution_status": "partial",
        "confidence": 0.9,
    }
    repeated_context_record = {
        "evidence_role": "condition_context",
        "changed_variables": [],
        "comparison": None,
        "reported_result": None,
        "attribution_scope": "not_attributable",
        "scientific_context": {
            "process": [{"name": "laser power", "value": "laser power"}]
        },
        "resolution_status": "resolved",
        "confidence": 0.8,
    }
    extractor = _StudySourceEvidenceExtractor(
        {
            result_block.block_id: result_record,
            **{block.block_id: repeated_context_record for block in repeated_methods},
        }
    )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={"paper-1": [result_block, *repeated_methods]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls[0] == result_block.block_id
    assert len(extractor.calls) <= 4
    assert extractor.calls.count(result_block.block_id) == 1
    assert all(
        extractor.calls.count(block.block_id) == 1
        for block in repeated_methods
        if block.block_id in extractor.calls
    )
    result_drafts = [draft for draft in drafts if draft.reported_result is not None]
    assert len(result_drafts) == 1
    result_draft = result_drafts[0]
    assert result_draft.attribution_scope == "association_only"
    assert result_draft.comparison is not None
    assert "Scope gap:" in (result_draft.selection_reason or "")
    assert any(
        draft.evidence_role == "condition_context"
        for draft in drafts
    )


def test_adaptive_context_stops_after_bounded_progress_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Small context gains cannot turn one confirmed question into a full-paper read."""

    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result_block = _study_source_block(
        "result-strength",
        "Results",
        "Strength increased from 100 MPa for Group A to 120 MPa for Group B.",
        10,
    )
    context_blocks = [
        _study_source_block(
            f"context-{position}",
            "Methods",
            f"A supplementary specimen was identified as Context-{position}.",
            position,
        )
        for position in range(1, 5)
    ]
    extractor = _StudySourceEvidenceExtractor(
        {
            "result-strength": {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": {
                    "baseline_label": "Group A",
                    "target_label": "Group B",
                    "axis_names": ["temperature"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "strength",
                    "baseline_value": 100,
                    "target_value": 120,
                    "unit": "MPa",
                    "direction": "increase",
                    "result_text": (
                        "Strength increased from 100 MPa for Group A to 120 MPa "
                        "for Group B."
                    ),
                },
                "attribution_scope": "association_only",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.9,
            },
            **{
                block.block_id: {
                    "evidence_role": "condition_context",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "scientific_context": {
                        "sample": [
                            {
                                "name": "specimen",
                                "value": f"Context-{position}",
                            }
                        ]
                    },
                    "resolution_status": "resolved",
                    "confidence": 0.8,
                }
                for position, block in enumerate(context_blocks, start=1)
            },
        }
    )
    context_route_calls = 0

    def next_context_route(**_kwargs: Any) -> tuple[EvidenceCandidate, ...]:
        nonlocal context_route_calls
        source_ref = context_blocks[context_route_calls].block_id
        context_route_calls += 1
        return (
            EvidenceCandidate.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                    "role": "process_or_treatment",
                    "extractable": True,
                    "reason": "Same-paper context inspection.",
                }
            ),
        )

    monkeypatch.setattr(
        source_extraction,
        "_build_adaptive_context_routes",
        next_context_route,
    )

    with capture_analysis_diagnostics() as diagnostics:
        drafts = extract_and_validate_source_facts(
            collection_id="col-test",
            source_extractor=extractor,
            objectives=(objective,),
            objective_paper_frames=(),
            objective_evidence_routes=(
                _study_source_route(objective.objective_id, result_block.block_id),
            ),
            blocks_by_document_id={
                "paper-1": [result_block, *context_blocks]
            },
            tables_by_document_id={"paper-1": []},
            document_trees_by_document_id={},
        )

    assert context_route_calls == 2
    assert extractor.calls == ["result-strength", "context-1", "context-2"]
    result = next(draft for draft in drafts if draft.reported_result is not None)
    assert "Scope gap:" in (result.selection_reason or "")
    assert any(
        record["trace_type"] == "objective_context_scope_gap"
        and record["context_round"] == 2
        and "bounded" in str(record["reason"]).casefold()
        for record in diagnostics.records
    )


def test_context_binding_ignores_matching_context_from_another_document() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "Group A",
                "target_label": "Group B",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "strength",
                "value": 120,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Strength increased for Group B.",
            },
            "attribution_scope": "association_only",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    other_document_context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "context-paper-2",
            "objective_id": objective.objective_id,
            "document_id": "paper-2",
            "source_kind": "text_window",
            "source_ref": "methods-2",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "sample": [
                    {"name": "sample", "value": "Group A"},
                    {"name": "sample", "value": "Group B"},
                ],
                "process": [{"name": "temperature", "value": "20 C"}],
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert not source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(other_document_context,),
    )


def test_context_binding_accepts_explicit_comparison_labels_in_process_context() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": {
                "baseline_label": "without heat treatment",
                "target_label": "650 C for 4 h",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "strength",
                "value": 120,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Strength increased after 650 C for 4 h.",
            },
            "attribution_scope": "association_only",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    methods_context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "context-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "process": [
                    {"name": "temperature", "value": "without heat treatment"},
                    {"name": "temperature", "value": "650 C for 4 h"},
                ]
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(methods_context,),
    )


@pytest.mark.parametrize(
    "source_changed_variables",
    (
        [],
        [
            {
                "name": "treatment temperature",
                "baseline_value": "R0",
                "target_value": "R1",
            }
        ],
    ),
)
def test_grouped_context_records_bind_result_to_their_explicit_conditions(
    source_changed_variables: list[dict[str, object]],
) -> None:
    """A Methods Source with two groups keeps each condition attached to its label."""

    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["treatment temperature"],
            "outcomes": ["strength"],
        }
    )

    methods_route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "role": "process_or_treatment",
            "extractable": True,
        }
    )
    methods_source = {
        "source_kind": "text_window",
        "source_ref": "methods-1",
        "document_id": "paper-1",
        "text": (
            "Group R0 used treatment temperature: without treatment. "
            "Group R1 used treatment temperature: 150 C. Both groups used "
            "a hatch spacing of 0.1 mm and tensile testing."
        ),
    }

    def context(group: str, condition: str) -> ExtractedEvidenceDraft:
        validated = source_validation.validate_source_fact(
            route=methods_route,
            source=methods_source,
            objective_context=objective,
            extracted_record={
                "evidence_role": "condition_context",
                "scientific_context": {
                    "sample": [{"name": "group", "value": group}],
                    "process": [
                        {"name": "treatment temperature", "value": condition},
                        {"name": "hatch spacing", "value": 0.1, "unit": "mm"},
                    ],
                    "test": [{"name": "method", "value": "tensile testing"}],
                },
                "attribution_scope": "not_attributable",
                "resolution_status": "resolved",
                "confidence": 0.9,
            },
        )
        assert len(validated) == 1
        return ExtractedEvidenceDraft.from_mapping(validated[0])

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": source_changed_variables,
            "comparison": {
                "baseline_label": "R0",
                "target_label": "R1",
                "axis_names": ["sample"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "strength",
                "value": 120,
                "baseline_value": 100,
                "target_value": 120,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Strength increased from R0 to R1.",
            },
            "attribution_scope": "association_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "source_excerpt": "Strength increased from R0 to R1.",
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    context_records = (context("R0", "without treatment"), context("R1", "150 C"))
    assert context_records[0].evidence_id != context_records[1].evidence_id
    assert source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=context_records,
        objective=objective,
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (*context_records, result)
    )[-1]
    assert [variable.to_record() for variable in bound.changed_variables] == [
        {
            "name": "treatment temperature",
            "baseline_value": "without treatment",
            "target_value": "150 C",
            "unit": None,
        }
    ]
    assert bound.comparison is not None and bound.comparison.comparable
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "results-1",
        "methods-1",
    }

def test_explicit_respectively_aliases_bind_results_to_method_conditions() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-microstructure",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": "R0",
                    "target_value": "R1",
                }
            ],
            "comparison": {
                "baseline_label": "R0",
                "target_label": "R1",
                "axis_names": ["build platform preheating"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "R1 had a more equiaxed microstructure than R0.",
            },
            "attribution_scope": "association_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "source_excerpt": "R1 had a more equiaxed microstructure than R0.",
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-1",
        source_facts=(result,),
        objectives=(objective,),
        document_contexts={
            "paper-1": (
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "text": (
                        "For tracking, specimens prepared without build platform "
                        "preheating, and the ones prepared with build platform "
                        "preheating to 150 C are designated by R0 and R1, respectively."
                    ),
                },
            )
        },
    )

    bound = next(item for item in reconstructed if item.evidence_id == result.evidence_id)
    assert [variable.to_record() for variable in bound.changed_variables] == [
        {
            "name": "build platform preheating",
            "baseline_value": "without build platform preheating",
            "target_value": "with build platform preheating to 150 C",
            "unit": None,
        }
    ]
    assert bound.comparison is not None and bound.comparison.comparable
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "results-1",
        "methods-1",
    }



@pytest.mark.parametrize(
    "method_contexts",
    (
        (
            "Specimens prepared without build platform preheating and with "
            "build platform preheating to 150 C are designated by R0 and R1.",
        ),
        (
            "Specimens prepared without build platform preheating, with build "
            "platform preheating to 150 C, and with build platform preheating "
            "to 300 C are designated by R0 and R1, respectively.",
        ),
        (
            "Specimens prepared without build platform preheating and with "
            "build platform preheating to 150 C are designated by R0 and R1, "
            "respectively.",
            "Specimens prepared with build platform preheating to 300 C and "
            "with build platform preheating to 450 C are designated by R0 and "
            "R2, respectively.",
        ),
    ),
    ids=(
        "missing-respectively",
        "condition-label-count-mismatch",
        "conflicting-group-definition",
    ),
)
def test_ambiguous_group_aliases_do_not_bind_result_conditions(
    method_contexts: tuple[str, ...],
) -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-microstructure",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": "R0",
                    "target_value": "R1",
                }
            ],
            "comparison": {
                "baseline_label": "R0",
                "target_label": "R1",
                "axis_names": ["build platform preheating"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "R1 had a more equiaxed microstructure than R0.",
            },
            "attribution_scope": "association_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "source_excerpt": (
                        "R1 had a more equiaxed microstructure than R0."
                    ),
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-1",
        source_facts=(result,),
        objectives=(objective,),
        document_contexts={
            "paper-1": tuple(
                {
                    "source_kind": "text_window",
                    "source_ref": f"methods-{index}",
                    "text": text,
                }
                for index, text in enumerate(method_contexts, start=1)
            )
        },
    )

    unresolved = next(
        item for item in reconstructed if item.evidence_id == result.evidence_id
    )
    assert unresolved.changed_variables == ()
    assert unresolved.comparison is None
    assert unresolved.attribution_scope == "descriptive_only"
    assert unresolved.resolution_status == "partial"
    assert {ref["source_ref"] for ref in unresolved.source_refs} == {"results-1"}


def test_partial_result_keeps_source_fact_and_binds_context_without_revisit() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Porosity decreased from 0.8% for S1 to 0.4% for S2.",
        6,
    )
    methods_block = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "S1 used 150 W laser power and S2 used 200 W laser power for Ti-6Al-4V.",
        2,
    )
    direct_record = {
        "evidence_role": "direct_result",
        "changed_variables": [
            {
                "name": "laser power",
                "baseline_value": 150,
                "target_value": 200,
                "unit": "W",
            }
        ],
        "comparison": {
            "baseline_label": "S1",
            "target_label": "S2",
            "axis_names": ["laser power"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "porosity",
            "value": 0.4,
            "baseline_value": 0.8,
            "target_value": 0.4,
            "unit": "%",
            "direction": "decrease",
            "result_text": "Porosity decreased from 0.8% for S1 to 0.4% for S2.",
        },
        "attribution_scope": "isolated_effect",
        "scientific_context": {
            "material": [{"name": "alloy", "value": "Ti-6Al-4V"}]
        },
        "resolution_status": "resolved",
        "confidence": 0.9,
    }

    class RevisitExtractor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def extract_source(self, payload):
            source_ref = str(payload["source"]["source_ref"])
            prior_evidence = payload["document_state"].get("prior_evidence") or []
            self.calls.append((source_ref, bool(prior_evidence)))
            if source_ref == "01-methods":
                return StructuredEvidenceExtractions.model_validate(
                    {
                        "extractions": [
                            {
                                "evidence_role": "condition_context",
                                "changed_variables": [],
                                "comparison": None,
                                "reported_result": None,
                                "attribution_scope": "not_attributable",
                                "scientific_context": {
                                    "material": [
                                        {"name": "alloy", "value": "Ti-6Al-4V"}
                                    ],
                                    "process": [
                                        {
                                            "name": "laser power",
                                            "value": "150 W for S1 and 200 W for S2",
                                        }
                                    ],
                                },
                                "resolution_status": "resolved",
                                "confidence": 0.9,
                            }
                        ]
                    }
                )
            if source_ref == "03-results":
                return StructuredEvidenceExtractions.model_validate(
                    {"extractions": [direct_record]}
                )
            return StructuredEvidenceExtractions()

    extractor = RevisitExtractor()
    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={"paper-1": [result_block, methods_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls == [("03-results", False), ("01-methods", True)]
    result_drafts = [
        unit
        for unit in drafts
        if unit.source_ref == "03-results" and unit.reported_result is not None
    ]
    assert len(result_drafts) == 1
    assert result_drafts[0].changed_variables == ()
    assert {ref["source_ref"] for ref in result_drafts[0].source_refs} == {
        "03-results"
    }
    context_drafts = [
        unit
        for unit in drafts
        if unit.source_ref == "01-methods" and unit.reported_result is None
    ]
    assert len(context_drafts) == 1
    assert context_drafts[0].scientific_context.process
    assert not any(
        unit.source_ref == "03-results" and unit.reported_result is None
        for unit in drafts
    )


def test_context_closure_uses_new_same_paper_label_in_a_later_round() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Strength increased from 100 MPa for Group A to 120 MPa for Group B.",
        6,
    )
    first_context_block = _study_source_block(
        "01-methods",
        "Methods",
        "Specimen code C-A followed the procedure at 20 C.",
        2,
    )
    second_context_block = _study_source_block(
        "02-notes",
        "Additional notes",
        "C-A was paired with endpoint labels P and Q.",
        3,
    )
    direct_record = {
        "evidence_role": "direct_result",
        "changed_variables": [
            {
                "name": "temperature",
                "baseline_value": 20,
                "target_value": 40,
                "unit": "C",
            }
        ],
        "comparison": {
            "baseline_label": "Group A",
            "target_label": "Group B",
            "axis_names": ["temperature"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "strength",
            "value": 120,
            "baseline_value": 100,
            "target_value": 120,
            "unit": "MPa",
            "direction": "increase",
            "result_text": (
                "Strength increased from 100 MPa for Group A to 120 MPa for Group B."
            ),
        },
        "attribution_scope": "isolated_effect",
        "scientific_context": {},
        "resolution_status": "resolved",
        "confidence": 0.9,
    }

    class ChainedContextExtractor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def extract_source(self, payload):
            source_ref = str(payload["source"]["source_ref"])
            self.calls.append(source_ref)
            records = {
                "03-results": direct_record,
                "01-methods": {
                    "evidence_role": "condition_context",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "scientific_context": {
                        "sample": [{"name": "specimen", "value": "C-A"}],
                        "process": [{"name": "temperature", "value": "20 C"}],
                    },
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                },
                "02-notes": {
                    "evidence_role": "condition_context",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "scientific_context": {
                        "sample": [
                            {"name": "specimen", "value": "P"},
                            {"name": "specimen", "value": "Q"},
                        ],
                        "process": [{"name": "temperature", "value": "20 C"}],
                    },
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                },
            }
            return StructuredEvidenceExtractions.model_validate(
                {"extractions": [records[source_ref]]}
            )

    extractor = ChainedContextExtractor()
    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, "03-results"),
        ),
        blocks_by_document_id={
            "paper-1": [result_block, first_context_block, second_context_block]
        },
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls == ["03-results", "01-methods", "02-notes"]
    assert any(unit.source_ref == "02-notes" for unit in drafts)


def test_partial_result_expands_same_paper_context_bundle_once() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Porosity decreased from 0.8% for S1 to 0.4% for S2; see the Methods section for conditions.",
        6,
    )
    methods_s1 = _study_source_block(
        "01-methods-s1",
        "Materials and Methods",
        "S1 was fabricated from Ti-6Al-4V at 150 W laser power.",
        2,
    )
    methods_s2 = _study_source_block(
        "02-methods-s2",
        "Materials and Methods",
        "S2 was fabricated from Ti-6Al-4V at 200 W laser power.",
        3,
    )
    extractor = _StudySourceEvidenceExtractor(
        {
            "03-results": {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": {
                    "baseline_label": "S1",
                    "target_label": "S2",
                    "axis_names": ["sample"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "porosity",
                    "value": 0.4,
                    "unit": "%",
                    "direction": "decrease",
                    "result_text": "Porosity decreased from 0.8% for S1 to 0.4% for S2.",
                },
                "attribution_scope": "association_only",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.8,
            },
            "01-methods-s1": {
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                    "sample": [{"name": "sample", "value": "S1"}],
                    "process": [{"name": "laser power", "value": 150, "unit": "W"}],
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            },
            "02-methods-s2": {
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                    "sample": [{"name": "sample", "value": "S2"}],
                    "process": [{"name": "laser power", "value": 200, "unit": "W"}],
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            },
        }
    )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={"paper-1": [result_block, methods_s1, methods_s2]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls == ["03-results", "01-methods-s1", "02-methods-s2"]
    assert {draft.source_ref for draft in drafts} == {
        "03-results",
        "01-methods-s1",
        "02-methods-s2",
    }


def test_empty_result_is_reextracted_after_same_paper_context_closure() -> None:
    """A result missed on the first pass is retried after its paper context is read."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result_block = _study_source_block(
        "03-results",
        "Results",
        "Porosity decreased from 0.8% for S1 to 0.4% for S2; conditions are in Methods.",
        6,
    )
    methods_block = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "S1 used 150 W laser power and S2 used 200 W laser power on Ti-6Al-4V.",
        2,
    )
    direct_record = {
        "evidence_role": "direct_result",
        "changed_variables": [
            {
                "name": "laser power",
                "baseline_value": 150,
                "target_value": 200,
                "unit": "W",
            }
        ],
        "comparison": {
            "baseline_label": "S1",
            "target_label": "S2",
            "axis_names": ["laser power"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "porosity",
            "value": 0.4,
            "baseline_value": 0.8,
            "target_value": 0.4,
            "unit": "%",
            "direction": "decrease",
            "result_text": "Porosity decreased from 0.8% for S1 to 0.4% for S2.",
        },
        "attribution_scope": "isolated_effect",
        "scientific_context": {
            "material": [{"name": "material", "value": "Ti-6Al-4V"}],
            "sample": [
                {"name": "sample", "value": "S1"},
                {"name": "sample", "value": "S2"},
            ],
        },
        "resolution_status": "resolved",
        "confidence": 0.9,
    }

    class ContextAwareExtractor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def extract_source(self, payload):  # noqa: ANN001
            source_ref = str(payload["source"]["source_ref"])
            self.calls.append(source_ref)
            if source_ref == "03-results":
                # The first pass has insufficient context; after Methods is
                # inspected, the same Source can be transcribed completely.
                if self.calls.count(source_ref) == 1:
                    return StructuredEvidenceExtractions()
                assert "01-methods" in {
                    item["source_ref"]
                    for item in payload["same_paper_context_bundle"]
                }
                return StructuredEvidenceExtractions.model_validate(
                    {"extractions": [direct_record]}
                )
            return StructuredEvidenceExtractions.model_validate(
                {
                    "extractions": [
                        {
                            "evidence_role": "condition_context",
                            "changed_variables": [],
                            "comparison": None,
                            "reported_result": None,
                            "attribution_scope": "not_attributable",
                            "scientific_context": {
                                "material": [
                                    {"name": "material", "value": "Ti-6Al-4V"}
                                ],
                                "sample": [
                                    {"name": "sample", "value": "S1"},
                                    {"name": "sample", "value": "S2"},
                                ],
                                "process": [
                                    {"name": "laser power", "value": 150, "unit": "W"},
                                    {"name": "laser power", "value": 200, "unit": "W"},
                                ],
                            },
                            "resolution_status": "resolved",
                            "confidence": 0.9,
                        }
                    ]
                }
            )

    extractor = ContextAwareExtractor()
    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, result_block.block_id),
        ),
        blocks_by_document_id={"paper-1": [result_block, methods_block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    assert extractor.calls == ["03-results", "01-methods", "03-results"]
    result_drafts = [draft for draft in drafts if draft.source_ref == "03-results"]
    assert len(result_drafts) == 1
    assert result_drafts[0].reported_result is not None
    assert result_drafts[0].selection_status == "extracted"
    assert result_drafts[0].changed_variables[0].baseline_value == 150


def test_complete_result_endpoints_still_expand_missing_study_context() -> None:
    """A result with endpoints still needs context a researcher would inspect."""
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "03-results",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 150,
                    "target_value": 200,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "value": 0.4,
                "baseline_value": 0.8,
                "target_value": 0.4,
                "unit": "%",
                "direction": "decrease",
                "result_text": "Porosity decreased from 0.8% for S1 to 0.4% for S2.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    methods = _study_source_block(
        "01-methods",
        "Materials and Methods",
        "S1 and S2 were fabricated and tested under the reported process conditions.",
        2,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(result,),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, "03-results"),
        ),
        blocks_by_document_id={"paper-1": [methods]},
        tables_by_document_id={"paper-1": []},
    )

    assert [route.source_ref for route in routes] == ["01-methods"]


def test_context_bundle_is_not_complete_without_required_study_context():
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-paper-1",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "03-results",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 150,
                    "target_value": 200,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "value": 0.4,
                "baseline_value": 0.8,
                "target_value": 0.4,
                "unit": "%",
                "direction": "decrease",
                "result_text": "Porosity decreased from 0.8% for S1 to 0.4% for S2.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert not source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(),
        objective=objective,
    )


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


def test_objective_extraction_contract_preserves_multiple_atomic_results() -> None:
    response = StructuredEvidenceExtractions.model_validate(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": {
                        "outcome": "yield strength",
                        "value": 480,
                        "unit": "MPa",
                        "direction": "increase",
                        "result_text": "Yield strength was 480 MPa.",
                    },
                    "attribution_scope": "descriptive_only",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                },
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": {
                        "outcome": "elongation",
                        "value": 9.1,
                        "unit": "%",
                        "direction": "increase",
                        "result_text": "Elongation was 9.1%.",
                    },
                    "attribution_scope": "descriptive_only",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                },
            ]
        }
    )

    assert [
        item.reported_result.outcome
        for item in response.extractions
        if item.reported_result is not None
    ] == ["yield strength", "elongation"]


def test_source_extraction_persists_each_atomic_result_from_one_source() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-heat-treatment",
            "question": "How does heat treatment affect strength and elongation?",
            "variables": ["heat treatment"],
            "outcomes": ["yield strength", "elongation"],
        }
    )
    block = _study_source_block(
        "results-1",
        "Results",
        (
            "Heat treatment increased yield strength from 420 to 480 MPa. "
            "Elongation increased from 6.2% to 9.1%."
        ),
        7,
    )

    class MultiResultExtractor:
        def extract_source(self, _payload):
            return StructuredEvidenceExtractions.model_validate(
                {
                    "extractions": [
                        {
                            "evidence_role": "direct_result",
                            "changed_variables": [
                                {
                                    "name": "heat treatment",
                                    "baseline_value": "without heat treatment",
                                    "target_value": "heat treatment",
                                }
                            ],
                            "comparison": {
                                "baseline_label": "without heat treatment",
                                "target_label": "heat treatment",
                                "axis_names": ["heat treatment"],
                                "comparable": True,
                                "incomparability_reasons": [],
                            },
                            "reported_result": {
                                "outcome": "yield strength",
                                "baseline_value": 420,
                                "target_value": 480,
                                "value": 480,
                                "unit": "MPa",
                                "direction": "increase",
                                "result_text": (
                                    "Heat treatment increased yield strength from 420 "
                                    "to 480 MPa."
                                ),
                            },
                            "attribution_scope": "isolated_effect",
                            "scientific_context": {},
                            "resolution_status": "resolved",
                            "confidence": 0.9,
                        },
                        {
                            "evidence_role": "direct_result",
                            "changed_variables": [
                                {
                                    "name": "heat treatment",
                                    "baseline_value": "without heat treatment",
                                    "target_value": "heat treatment",
                                }
                            ],
                            "comparison": {
                                "baseline_label": "without heat treatment",
                                "target_label": "heat treatment",
                                "axis_names": ["heat treatment"],
                                "comparable": True,
                                "incomparability_reasons": [],
                            },
                            "reported_result": {
                                "outcome": "elongation",
                                "baseline_value": 6.2,
                                "target_value": 9.1,
                                "value": 9.1,
                                "unit": "%",
                                "direction": "increase",
                                "result_text": "Elongation increased from 6.2% to 9.1%.",
                            },
                            "attribution_scope": "isolated_effect",
                            "scientific_context": {},
                            "resolution_status": "resolved",
                            "confidence": 0.9,
                        },
                    ]
                }
            )

    drafts = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=MultiResultExtractor(),
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(
            _study_source_route(objective.objective_id, block.block_id),
        ),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={"paper-1": []},
        document_trees_by_document_id={},
    )

    result_drafts = [
        item for item in drafts if item.reported_result is not None
    ]
    assert [item.reported_result.outcome for item in result_drafts] == [
        "yield strength",
        "elongation",
    ]
    assert len({item.evidence_id for item in result_drafts}) == 2
    assert {item.source_ref for item in result_drafts} == {block.block_id}
    assert [item.reported_result.result_text for item in result_drafts] == [
        "Heat treatment increased yield strength from 420 to 480 MPa.",
        "Elongation increased from 6.2% to 9.1%.",
    ]


def test_research_objective_records_inspection_without_target_result():
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

    assert len(drafts) == 1
    assert drafts[0].source_ref == block.block_id
    assert drafts[0].selection_status == "candidate"
    assert drafts[0].evidence_role == "direct_result"
    assert drafts[0].reported_result is None
    assert drafts[0].resolution_status == "unresolved"


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


def test_source_validation_keeps_incomplete_endpoint_comparison_non_attributable():
    objective = _research_objective(
        {
            "objective_id": "obj-power-porosity",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-porosity",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = "Porosity differed between Sample A and Sample B."

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
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 100,
                    "target_value": 200,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "Sample A",
                "target_label": "Sample B",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "value": None,
                "unit": None,
                "direction": "unknown",
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.8,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"]["comparable"] is False
    assert records[0]["attribution_scope"] == "not_attributable"
    # The incomplete record remains valid Evidence and cannot erase other
    # source-grounded results from the paper during materialization.
    ExtractedEvidenceDraft.from_mapping(records[0])


def test_source_validation_recovers_objective_factor_from_named_qualitative_groups():
    """Named result groups still expose the source-grounded Objective factor."""

    objective = _research_objective(
        {
            "objective_id": "obj-ved-fatigue",
            "question": (
                "How does volumetric energy density affect low cycle fatigue strength?"
            ),
            "variables": ["volumetric energy density"],
            "outcomes": ["low cycle fatigue strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-lcf",
            "source_kind": "text_window",
            "source_ref": "results-lcf",
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
                "Low cycle fatigue strength was enhanced for medium VED "
                "structures and high VED structures."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": {
                "baseline_label": "medium VED",
                "target_label": "high VED",
                "axis_names": ["sample"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "low cycle fatigue strength",
                "value": None,
                "unit": None,
                "direction": "improve",
                "result_text": "Low cycle fatigue strength was enhanced for medium VED structures and high VED structures.",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert [item["name"] for item in records[0]["changed_variables"]] == [
        "volumetric energy density"
    ]
    assert records[0]["changed_variables"][0]["baseline_value"] is None
    assert records[0]["changed_variables"][0]["target_value"] is None
    assert records[0]["attribution_scope"] == "association_only"
    assert records[0]["reported_result"]["result_text"].startswith(
        "Low cycle fatigue strength was enhanced"
    )


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


def test_source_validation_does_not_promote_sample_ids_to_variable_endpoints():
    """Sample identifiers are not experimental levels just because they match Source text."""

    objective = _research_objective(
        {
            "objective_id": "obj-sample-id-endpoints",
            "question": "How does laser power affect porosity?",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-sample-ids",
            "source_kind": "text_window",
            "source_ref": "results-sample-ids",
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
                "Porosity decreased from 1.2% in S1 to 0.4% in S2 as laser power "
                "changed. The specimens were labeled S1 and S2; the paper does not "
                "state the laser power assigned to either specimen in this Source."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "value": 0.4,
                "baseline_value": 1.2,
                "target_value": 0.4,
                "unit": "%",
                "direction": "decrease",
                "result_text": "Porosity decreased from 1.2% in S1 to 0.4% in S2.",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is not None
    assert records[0]["comparison"]["comparable"] is False
    assert any(
        "complete levels of the Objective variable" in reason
        for reason in records[0]["comparison"]["incomparability_reasons"]
    )
    assert records[0]["attribution_scope"] == "not_attributable"
    assert records[0]["reported_result"]["outcome"] == "porosity"


def test_source_validation_retains_explicit_variable_association_when_groups_are_unresolved():
    """A result can support an association before its group levels are bound."""

    objective = _research_objective(
        {
            "objective_id": "obj-scanning-strategy-association",
            "question": "How does scanning strategy affect yield strength?",
            "variables": ["scanning strategy"],
            "outcomes": ["yield strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-strategy",
            "source_kind": "text_window",
            "source_ref": "results-strategy",
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
                "The better yield strength was observed in samples with scanning "
                "strategy A than in samples processed with scanning strategy B."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": {
                "baseline_label": "scanning strategy B",
                "target_label": "scanning strategy A",
                "axis_names": ["sample"],
                "comparable": False,
                "incomparability_reasons": [
                    "factor levels are unresolved in SOURCE"
                ],
            },
            "reported_result": {
                "outcome": "yield strength",
                "value": None,
                "unit": None,
                "direction": "improve",
                "result_text": (
                    "better yield strength was observed in samples with "
                    "scanning strategy A than in samples processed with "
                    "scanning strategy B"
                ),
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert [item["name"] for item in records[0]["changed_variables"]] == [
        "scanning strategy"
    ]
    assert records[0]["changed_variables"][0]["baseline_value"] is None
    assert records[0]["changed_variables"][0]["target_value"] is None
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "association_only"


def test_source_validation_does_not_guess_arbitrary_group_labels_are_levels():
    """Unseen paper-local labels must not become Objective variable endpoints."""

    objective = _research_objective(
        {
            "objective_id": "obj-arbitrary-group-labels",
            "question": "How does laser power affect porosity?",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-arbitrary-groups",
            "source_kind": "text_window",
            "source_ref": "results-arbitrary-groups",
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
                "Porosity decreased from 1.2% in alpha-variant to 0.4% in "
                "beta-variant. The laser power assigned to these paper-local "
                "groups is reported elsewhere in the paper."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "alpha-variant",
                "target_label": "beta-variant",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "value": 0.4,
                "baseline_value": 1.2,
                "target_value": 0.4,
                "unit": "%",
                "direction": "decrease",
                "result_text": (
                    "Porosity decreased from 1.2% in alpha-variant to 0.4% in "
                    "beta-variant."
                ),
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is not None
    assert records[0]["comparison"]["comparable"] is False
    assert records[0]["attribution_scope"] == "not_attributable"
    assert records[0]["resolution_status"] == "partial"
    assert records[0]["reported_result"]["outcome"] == "porosity"


def test_same_paper_conditions_can_upgrade_opaque_labels_to_real_variable_levels():
    objective = _research_objective(
        {
            "objective_id": "obj-sample-id-context-binding",
            "question": "How does laser power affect porosity?",
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-sample-context",
            "source_kind": "text_window",
            "source_ref": "results-sample-context",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        source_validation.validate_source_fact(
            route=route,
            source={
                "source_kind": "text_window",
                "source_ref": route.source_ref,
                "text": "Porosity decreased from 1.2% in S1 to 0.4% in S2.",
            },
            objective_context=objective,
            extracted_record={
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": None,
                        "target_value": None,
                        "unit": "W",
                    }
                ],
                "comparison": {
                    "baseline_label": "S1",
                    "target_label": "S2",
                    "axis_names": ["laser power"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "porosity",
                    "value": 0.4,
                    "baseline_value": 1.2,
                    "target_value": 0.4,
                    "unit": "%",
                    "direction": "decrease",
                    "result_text": "Porosity decreased from 1.2% in S1 to 0.4% in S2.",
                },
                "attribution_scope": "association_only",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.9,
            },
        )[0]
    )
    assert result.changed_variables == ()
    assert result.comparison is not None and not result.comparison.comparable

    context_units = tuple(
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"context-{sample}",
                "objective_id": objective.objective_id,
                "document_id": "paper-sample-context",
                "source_kind": "text_window",
                "source_ref": f"methods-{sample}",
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [],
                    "sample": [{"name": "sample", "value": sample}],
                    "process": [{"name": "laser power", "value": power, "unit": "W"}],
                    "test": [],
                },
                "source_refs": [
                    {"source_kind": "text_window", "source_ref": f"methods-{sample}"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )
        for sample, power in (("S1", 150), ("S2", 200))
    )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="col-test",
        source_facts=(result, *context_units),
        objectives=(objective,),
    )
    bound_result = next(item for item in reconstructed if item.reported_result is not None)
    assert bound_result.attribution_scope == "isolated_effect"
    assert bound_result.changed_variables[0].to_record() == {
        "name": "laser power",
        "baseline_value": 150,
        "target_value": 200,
        "unit": "W",
    }


def test_same_paper_encoded_sample_labels_bind_explicit_method_condition_schema():
    """A researcher can use a sample label only when Methods defines its order."""

    objective = _research_objective(
        {
            "objective_id": "obj-encoded-condition-schema",
            "question": "How does scan speed affect yield strength?",
            "variables": ["scan speed"],
            "outcomes": ["yield strength"],
        }
    )
    methods_details = (
        "Samples were fabricated at different laser powers (100, 120, and 140 W) "
        "and scan speeds (100, 200, and 280 mm/s)."
    )

    def result(evidence_id: str, label: str, value: float) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-encoded-condition-schema",
                "source_kind": "table",
                "source_ref": "table-results",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": value,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"{label}: yield strength = {value} MPa",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "material": [],
                    "sample": [{"name": "specimen", "value": label}],
                    "process": [
                        {"name": "manufacturing process", "value": "LPBF"}
                    ],
                    "test": [{"name": "details", "value": methods_details}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-results",
                        "source_excerpt": f"Specimen | Yield strength (MPa)\\n{label} | {value}",
                    },
                    {
                        "source_kind": "text_window",
                        "source_ref": "methods-conditions",
                        "source_excerpt": methods_details,
                        "supports": ["scientific_context.test"],
                    },
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    with capture_analysis_diagnostics() as diagnostics:
        reconstructed = paper_experiment.reconstruct_paper_experiments(
            collection_id="col-test",
            source_facts=(
                result("result-100-100", "as-built (100/100)", 200),
                result("result-100-200", "as-built (100/200)", 220),
            ),
            objectives=(objective,),
        )

    comparisons = tuple(
        item
        for item in reconstructed
        if item.evidence_id.startswith("oeu_cmp_")
    )
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.changed_variables[0].to_record() == {
        "name": "scan speed",
        "baseline_value": 100,
        "target_value": 200,
        "unit": "mm/s",
    }
    assert comparison.comparison is not None and comparison.comparison.comparable
    assert {ref["source_ref"] for ref in comparison.source_refs} >= {
        "table-results",
        "methods-conditions",
    }
    audit = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_validated_context_closure"
    )
    assert audit["closure_complete"] is True


def test_encoded_sample_label_stays_descriptive_when_method_order_is_ambiguous():
    """A slash label is not decoded when the paper does not define its order."""

    objective = _research_objective(
        {
            "objective_id": "obj-ambiguous-condition-schema",
            "question": "How does scan speed affect yield strength?",
            "variables": ["scan speed"],
            "outcomes": ["yield strength"],
        }
    )
    ambiguous_details = (
        "Samples were produced under several parameter combinations, including "
        "100/100 and 100/200."
    )

    def result(evidence_id: str, label: str, value: float) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-ambiguous-condition-schema",
                "source_kind": "table",
                "source_ref": "table-results",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": value,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"{label}: yield strength = {value} MPa",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "specimen", "value": label}],
                    "process": [
                        {"name": "manufacturing process", "value": "LPBF"}
                    ],
                    "test": [{"name": "details", "value": ambiguous_details}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-results",
                        "source_excerpt": f"Specimen | Yield strength (MPa)\\n{label} | {value}",
                    },
                    {
                        "source_kind": "text_window",
                        "source_ref": "methods-conditions",
                        "source_excerpt": ambiguous_details,
                        "supports": ["scientific_context.test"],
                    },
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="col-test",
        source_facts=(
            result("result-100-100", "sample A (100/100)", 200),
            result("result-100-200", "sample B (100/200)", 220),
        ),
        objectives=(objective,),
    )

    assert not any(item.evidence_id.startswith("oeu_cmp_") for item in reconstructed)
    assert all(
        item.attribution_scope == "descriptive_only"
        for item in reconstructed
        if item.reported_result is not None
    )


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


def test_source_validation_preserves_explicit_objective_association_without_inventing_endpoints() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-residual-stress",
            "question": "How does laser exposure condition affect residual stress?",
            "variables": ["laser exposure condition"],
            "outcomes": ["residual stress"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-rescanning",
            "source_kind": "text_window",
            "source_ref": "abstract-result",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = (
        "The effects of different scanning strategies on residual stress were "
        "analyzed. Partition rescanning reduced residual stress."
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
                "outcome": "residual stress",
                "value": None,
                "unit": None,
                "direction": "decrease",
                "result_text": "Partition rescanning reduced residual stress.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert records[0]["changed_variables"] == [
        {
            "name": "laser exposure condition",
            "baseline_value": None,
            "target_value": None,
            "unit": None,
        }
    ]
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "association_only"
    assert records[0]["resolution_status"] == "partial"


def test_source_validation_does_not_promote_observed_mediator_to_objective_variable() -> None:
    """A process -> porosity -> elongation passage is not porosity intervention evidence."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity-elongation-mediator",
            "question": "How does porosity affect elongation?",
            "variables": ["porosity"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "results-preheating",
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
                "Porosity size and distribution decreased by preheating the build "
                "platform. Preheating increased elongation from 72% to 82%."
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "value": 82,
                "unit": "%",
                "direction": "increase",
                "result_text": "Preheating increased elongation from 72% to 82%.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "descriptive_only"


def test_source_validation_does_not_promote_mediator_with_causal_as_clause() -> None:
    """A causal ``as`` clause still keeps a process-mediated result descriptive."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity-elongation-as-clause",
            "question": "How does porosity affect elongation?",
            "variables": ["porosity"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating-as-clause",
            "source_kind": "text_window",
            "source_ref": "results-preheating-as-clause",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = (
        "Porosity decreased as preheating increased, while elongation increased."
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
                "value": None,
                "unit": None,
                "direction": "increase",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert records[0]["changed_variables"] == []
    assert records[0]["attribution_scope"] == "descriptive_only"


def test_source_validation_downgrades_model_supplied_mediator_endpoints() -> None:
    """Grounded endpoint values do not make a measured mediator an intervention."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity-elongation-model-mediator",
            "question": "How does porosity affect elongation?",
            "variables": ["porosity"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating-model-mediator",
            "source_kind": "text_window",
            "source_ref": "results-preheating-model-mediator",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = (
        "Porosity decreased from 1.2% to 0.4% after preheating, while elongation "
        "increased."
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
            "changed_variables": [
                {
                    "name": "porosity",
                    "baseline_value": 1.2,
                    "target_value": 0.4,
                    "unit": "%",
                }
            ],
            "comparison": {
                "baseline_label": "1.2%",
                "target_label": "0.4%",
                "axis_names": ["porosity"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": None,
                "unit": None,
                "direction": "increase",
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is None
    assert records[0]["attribution_scope"] == "descriptive_only"
    assert "observed mediator" in records[0]["selection_reason"]


def test_source_validation_keeps_explicit_intervention_before_measurement_method() -> None:
    """A trailing measurement method does not make the intervention a mediator."""

    objective = _research_objective(
        {
            "objective_id": "obj-laser-porosity-measurement-clause",
            "question": "How does laser exposure condition affect porosity?",
            "variables": ["laser exposure condition"],
            "outcomes": ["porosity"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-laser-measurement-clause",
            "source_kind": "text_window",
            "source_ref": "results-laser-measurement-clause",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = (
        "Changing laser exposure condition from low exposure to high exposure "
        "decreased porosity from 2.4% to 0.8% measured by X-ray computed tomography."
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
            "changed_variables": [
                {
                    "name": "laser exposure condition",
                    "baseline_value": "low exposure",
                    "target_value": "high exposure",
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "low exposure",
                "target_label": "high exposure",
                "axis_names": ["laser exposure condition"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "value": 0.8,
                "baseline_value": 2.4,
                "target_value": 0.8,
                "unit": "%",
                "direction": "decrease",
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert records[0]["changed_variables"][0]["name"] == "laser exposure condition"
    assert records[0]["comparison"]["comparable"] is True
    assert records[0]["attribution_scope"] == "isolated_effect"


def test_source_validation_keeps_explicit_mediator_outcome_association() -> None:
    """An explicit porosity-elongation clause remains reviewable as an association."""

    objective = _research_objective(
        {
            "objective_id": "obj-porosity-elongation-association",
            "question": "How does porosity affect elongation?",
            "variables": ["porosity"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-porosity",
            "source_kind": "text_window",
            "source_ref": "results-porosity",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = "Elongation increased as porosity decreased from 1.2% to 0.4%."
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
                "value": None,
                "unit": "%",
                "direction": "increase",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    assert [item["name"] for item in records[0]["changed_variables"]] == [
        "porosity"
    ]
    assert records[0]["attribution_scope"] == "association_only"
    assert records[0]["comparison"] is None


def test_source_validation_preserves_table_association_without_row_endpoints() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-residual-stress-table",
            "question": "How does laser exposure condition affect residual stress?",
            "variables": ["laser exposure condition"],
            "outcomes": ["residual stress"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-rescanning",
            "source_kind": "table",
            "source_ref": "table-residual-stress",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "table",
            "source_ref": route.source_ref,
            "column_headers": ["Scanning strategy", "Residual stress (MPa)"],
            "table_matrix": [
                ["Scanning strategy", "Residual stress (MPa)"],
                ["Partition rescanning", "254"],
            ],
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "residual stress",
                "value": 254,
                "unit": "MPa",
                "direction": "decrease",
                "result_text": "Residual stress = 254 MPa",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )

    assert records[0]["changed_variables"] == [
        {
            "name": "laser exposure condition",
            "baseline_value": None,
            "target_value": None,
            "unit": None,
        }
    ]
    assert records[0]["attribution_scope"] == "association_only"
    assert records[0]["comparison"] is None


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


def test_source_validation_recovers_material_bound_by_the_result_source() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-heat-treatment-elongation",
            "question": "How does heat treatment affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["heat treatment condition"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-heat-treatment",
            "source_kind": "text_window",
            "source_ref": "results-elongation",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    result_text = "After annealing at 750 C, the elongation increases."

    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "heading_path": "Mechanical properties",
            "text": (
                "Ti6Al4V samples were evaluated in the as-built and annealed "
                f"states. {result_text}"
            ),
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "annealing temperature",
                    "baseline_value": "as-built",
                    "target_value": 750,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "as-built",
                "target_label": "750 C",
                "axis_names": ["annealing temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "elongation",
                "value": None,
                "unit": None,
                "direction": "increase",
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert records[0]["scientific_context"]["material"] == [
        {"name": "material", "value": "Ti-6Al-4V", "unit": None}
    ]
    assert "scientific_context.material" in records[0]["source_refs"][0]["supports"]


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

    assert len(records) == 1
    assert records[0]["selection_status"] == "failed"
    assert records[0]["evidence_role"] == "irrelevant"
    assert records[0]["attribution_scope"] == "not_attributable"
    assert "Source grounding failed" in records[0]["failure_reason"]
    assert records[0]["source_refs"] == [
        {"source_kind": "text_window", "source_ref": "result-angle"}
    ]


def test_llm_objective_evidence_retains_categorical_result_without_explicit_endpoints():
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
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is not None
    assert records[0]["comparison"]["comparable"] is False
    assert records[0]["attribution_scope"] == "not_attributable"
    assert records[0]["resolution_status"] == "partial"
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


def test_llm_objective_evidence_does_not_repair_endpoints_to_group_labels():
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
    assert records[0]["changed_variables"] == []
    assert records[0]["comparison"] is not None
    assert records[0]["comparison"]["comparable"] is False
    assert records[0]["attribution_scope"] == "not_attributable"
    assert records[0]["resolution_status"] == "partial"


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


def test_llm_context_keeps_generic_process_when_value_is_source_grounded():
    record = source_validation._objective_retain_source_grounded_context(
        {
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [],
            }
        },
        source={
            "source_kind": "text_window",
            "text": "Ti-6Al-4V coupons were fabricated by LPBF.",
        },
    )

    assert record["scientific_context"]["process"] == [
        {"name": "process", "value": "LPBF"}
    ]


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
        paper_maps=(),
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
        "table_visual_text": "sample density\nA 99.6",
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
    assert projected["table_visual_text"] == "sample density\nA 99.6"
    _, prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {"question": "How does processing affect density?"},
            "evidence_route": {"source_kind": "table"},
            "source": projected,
        }
    )
    assert "CAPTION: Measured density" in prompt
    assert "| A | 99.6 |" in prompt
    assert "PDF LAYOUT TEXT (same table region; use only to resolve wrapped rows)" in prompt
    assert "A 99.6" in prompt


def test_research_objective_prompt_exposes_context_fields_without_values() -> None:
    _, prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does thermal dose affect surface roughness?",
                "variables": ["thermal dose"],
                "outcomes": ["surface roughness"],
            },
            "evidence_route": {
                "role": "process_or_treatment",
                "context_fields": ["comparison", "variable", "not_a_field"],
            },
            "source": {
                "source_kind": "text_window",
                "text": "Groups A and B followed the same procedure before assessment.",
            },
        }
    )

    assert "CONTEXT FIELDS TO CLOSE (SOURCE MUST SUPPORT THEM): [\"comparison\",\"variable\"]" in prompt
    assert "not_a_field" not in prompt


def test_research_objective_prompt_derives_context_field_from_route_role() -> None:
    _, prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does build platform preheating affect microstructure?",
                "variables": ["build platform preheating"],
                "outcomes": ["microstructure"],
            },
            "evidence_route": {
                "role": "process_or_treatment",
                "context_fields": [],
            },
            "source": {
                "source_kind": "text_window",
                "heading_path": "Experimental Procedures",
                "text": (
                    "The specimens were fabricated by laser powder bed fusion "
                    "in the vertical direction under argon shielding gas."
                ),
            },
        }
    )

    assert "CONTEXT FAMILY: process" in prompt
    assert "manufacturing or process family" in prompt


def test_research_objective_prompt_treats_fixed_manufacturing_facts_as_context() -> None:
    system_prompt, user_prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does platform preheating affect grain morphology?",
                "variables": ["platform preheating"],
                "outcomes": ["grain morphology"],
            },
            "evidence_route": {
                "role": "process_or_treatment",
                "context_fields": ["process"],
            },
            "source": {
                "source_kind": "text_window",
                "heading_path": "Experimental procedure",
                "text": (
                    "All specimens were manufactured by laser powder bed fusion "
                    "on System M in the vertical orientation under argon."
                ),
            },
        }
    )

    normalized_prompt = " ".join(system_prompt.split())
    assert "one requested experimental-context family" in normalized_prompt
    assert "ignore adjacent material" in normalized_prompt
    assert "shared by every compared group" in normalized_prompt
    assert "fixed conditions" in normalized_prompt
    assert "not varied" in normalized_prompt
    assert '"facts":[{"name":"descriptive field name"' in normalized_prompt
    assert "CONTEXT FAMILY: process" in user_prompt
    assert "machine or equipment" in user_prompt
    assert "processing atmosphere" in user_prompt
    assert "specimen or build orientation" in user_prompt


def test_context_repair_keeps_manufacturing_facts_out_of_test_context() -> None:
    instruction = source_extraction._objective_context_repair_instruction(
        repair_detail="facts.0.context_scope is missing",
        context_field="process",
    )

    assert "only `process` facts" in instruction
    assert "context_scope" in instruction
    assert '{"facts":[]}' in instruction
    assert "do not duplicate a fact" in instruction


def test_process_context_output_contract_materializes_only_requested_family() -> None:
    parsed = source_extraction.StructuredRequestedContextFacts.model_validate(
        {
            "facts": [
                {
                    "name": "manufacturing process",
                    "value": "laser powder bed fusion",
                    "unit": None,
                    "context_scope": "experimental",
                    "group_label": None,
                }
            ]
        }
    )
    extracted = source_extraction._objective_context_facts_as_extractions(
        parsed,
        context_field="process",
    )

    assert len(extracted.extractions) == 1
    assert extracted.extractions[0].scientific_context.process[0].value == (
        "laser powder bed fusion"
    )
    assert extracted.extractions[0].scientific_context.material == []
    assert extracted.extractions[0].scientific_context.sample == []
    assert extracted.extractions[0].scientific_context.test == []

    with pytest.raises(ValueError, match="context_scope"):
        source_extraction.StructuredRequestedContextFacts.model_validate(
            {"facts": [{"name": "machine", "value": "System M"}]}
        )


def test_result_role_with_only_groundable_context_is_preserved_as_context() -> None:
    payload = {
        "extractions": [
            {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [],
                    "sample": [
                        {
                            "name": "fracture surface",
                            "value": "fibrous region",
                            "context_scope": "experimental",
                        }
                    ],
                    "process": [],
                    "test": [],
                },
                "resolution_status": "partial",
                "confidence": 0.8,
            }
        ]
    }

    normalized = source_extraction._normalize_objective_evidence_payload(payload)
    parsed = source_extraction.StructuredEvidenceExtractions.model_validate(normalized)

    assert len(parsed.extractions) == 1
    extraction = parsed.extractions[0]
    assert extraction.evidence_role == "condition_context"
    assert extraction.reported_result is None
    assert extraction.attribution_scope == "not_attributable"
    assert extraction.scientific_context.sample[0].value == "fibrous region"


def test_result_role_without_result_or_context_remains_invalid() -> None:
    payload = {
        "extractions": [
            {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {},
                "resolution_status": "partial",
                "confidence": 0.8,
            }
        ]
    }

    normalized = source_extraction._normalize_objective_evidence_payload(payload)

    with pytest.raises(ValueError, match="result evidence requires one reported result"):
        source_extraction.StructuredEvidenceExtractions.model_validate(normalized)


def test_research_objective_prompt_separates_result_and_context_authority() -> None:
    system_prompt, prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does laser power affect tensile strength?",
                "variables": ["laser power"],
                "outcomes": ["tensile strength"],
            },
            "evidence_route": {
                "role": "current_experimental_evidence",
                "context_fields": ["material", "comparison", "test"],
            },
            "source": {
                "source_kind": "text_window",
                "text": "Tensile strength increased from 900 to 980 MPa.",
            },
            "same_paper_context_bundle": [
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "text": "Ti-6Al-4V samples used 180 W and 240 W; ASTM E8 tensile testing.",
                }
            ],
        }
    )

    assert "reported result" in system_prompt
    assert "SAME-PAPER CONTEXT BUNDLE" in prompt
    assert "context fields" in system_prompt
    assert "result values" in system_prompt
    assert "intermediate-to-outcome intervention" in system_prompt


def test_research_objective_prompt_requires_context_scope_for_explicit_parameters() -> None:
    system_prompt, _prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does build platform preheating affect microstructure?",
                "variables": ["build platform preheating"],
                "outcomes": ["microstructure"],
            },
            "evidence_route": {
                "role": "process_or_treatment",
                "context_fields": ["process"],
            },
            "source": {
                "source_kind": "text_window",
                "text": (
                    "Software input parameters included laser power and scan speed; "
                    "specimens were fabricated with a preheated platform."
                ),
            },
        }
    )

    assert "Every value must be explicit in SOURCE" in system_prompt
    assert "context_scope" in system_prompt
    assert "simulation" in system_prompt
    assert "experimental" in system_prompt


def test_context_scope_survives_model_validation_and_source_grounding() -> None:
    parsed = source_extraction.StructuredEvidenceExtractions.model_validate(
        {
            "extractions": [
                {
                    "evidence_role": "condition_context",
                    "scientific_context": {
                        "process": [
                            {
                                "name": "laser power",
                                "value": 200,
                                "unit": "W",
                                "context_scope": "simulation",
                            }
                        ]
                    },
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                }
            ]
        }
    )

    attribute = parsed.extractions[0].scientific_context.process[0]
    assert attribute.context_scope == "simulation"
    grounded = source_validation._objective_retain_source_grounded_context(
        parsed.extractions[0].model_dump(exclude_unset=True),
        source={
            "source_kind": "text_window",
            "text": "The simulation used a laser power of 200 W.",
        },
    )
    assert grounded["scientific_context"]["process"][0]["context_scope"] == (
        "simulation"
    )


def test_simulation_context_does_not_close_experimental_process_gap() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-microstructure",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "microstructure-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": "without preheating",
                    "target_value": "preheating to 150 C",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["build platform preheating"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "P150 developed an equiaxed cellular structure.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "test": [{"name": "method", "value": "optical microscopy"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    simulation_context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "simulation-controls",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-ansys",
            "evidence_role": "condition_context",
            "scientific_context": {
                "process": [
                    {
                        "name": "laser power",
                        "value": 200,
                        "unit": "W",
                        "context_scope": "simulation",
                    },
                    {
                        "name": "scan speed",
                        "value": 1833,
                        "unit": "mm/s",
                        "context_scope": "simulation",
                    },
                ]
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert "process" in source_extraction._objective_missing_context_fields(
        result, objective
    )
    assert not source_extraction._objective_context_bundle_can_bind_result(
        result,
        context_seed=(simulation_context,),
        objective=objective,
    )


def test_adaptive_context_route_carries_missing_fields_to_extraction_prompt() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-roughness",
            "variables": ["thermal dose"],
            "outcomes": ["surface roughness"],
        }
    )
    result_route = _study_source_route(objective.objective_id, "results-roughness")
    candidate = source_extraction._needs_context_objective_evidence_draft(
        route=result_route
    )
    design = _study_source_block(
        "design-1",
        "Study design",
        "Groups A and B followed the same procedure before assessment.",
        2,
    )

    routes = source_extraction._build_adaptive_context_routes(
        objectives=(objective,),
        source_facts=(candidate,),
        objective_evidence_routes=(result_route,),
        blocks_by_document_id={"paper-1": [design]},
        tables_by_document_id={"paper-1": []},
    )

    assert routes[0].context_fields == ("comparison", "sample", "variable")
    _, prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": objective.to_record(),
            "evidence_route": {
                "role": routes[0].role,
                "context_fields": routes[0].context_fields,
            },
            "source": {"source_kind": "text_window", "text": design.text},
        }
    )
    assert '"comparison"' in prompt
    assert '"variable"' in prompt


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
        text=(
            "Background context about the specimen and treatment. " * 160
            + "The reported result was that yield strength improved after heat treatment."
        ),
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
    assert len(payload["source"]["text"]) <= 12000
    assert "The reported result was that yield strength improved" in payload["source"]["text"]
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


def test_objective_table_rows_skip_repeated_continuation_header_rows():
    headers, rows = source_validation._objective_table_matrix_rows(
        {
            "column_headers": ["Specimens", "Density (%)"],
            "header_row_count": 2,
            "table_matrix": [
                ["Table 2 (continued)", "Table 2 (continued)"],
                ["Specimens", "Density (%)"],
                ["HIP-SLM (140/280)", "94.68"],
            ],
        }
    )

    assert headers == ("Specimens", "Density (%)")
    assert rows == ((1, ("HIP-SLM (140/280)", "94.68")),)


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


def test_research_objective_rejects_long_table_repair_that_invents_label_tokens():
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

    assert repaired_source is source
    assert str(repair_error) == (
        "table matrix repair introduced tokens not present in source"
    )
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


def test_research_objective_table_repair_rejects_invented_label_tokens():
    class InventingRepairExtractor:
        def repair_table_matrix(self, _payload):
            return StructuredTableMatrixRepair(
                repaired_table_matrix=[
                    ["Specimens", "Density (%)"],
                    ["Invented-SLM (100/100)", "98.15"],
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

    repaired_source, repair_error = (
        source_extraction._repair_objective_table_source_if_needed(
            collection_id="col-test",
            route=route,
            source=source,
            paper_facts_extractor=InventingRepairExtractor(),
        )
    )

    assert repaired_source is source
    assert str(repair_error) == (
        "table matrix repair introduced tokens not present in source"
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


def test_research_objective_table_repair_accepts_multiple_parser_fragment_merges():
    original_matrix = [
        ["Specimen", "Density (%)"],
        ["A (", "1"],
        ["100) B (", "2"],
        ["100)", ""],
        ["C", "3"],
    ]
    repaired_matrix = [
        ["Specimen", "Density (%)"],
        ["A (100)", "1"],
        ["B (100)", "2"],
        ["C", "3"],
    ]

    class RepairingPaperFactsExtractor:
        def repair_table_matrix(self, _payload):
            return StructuredTableMatrixRepair(
                repaired_table_matrix=repaired_matrix,
                confidence=0.95,
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
        "column_headers": original_matrix[0],
        "header_row_count": 1,
        "table_matrix": original_matrix,
    }

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
        and unit.selection_status == "failed"
        and unit.failure_reason == (
            "ValueError: table matrix repair introduced tokens not present in source"
        )
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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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


def test_research_objective_service_allows_semantic_fallback_for_matrix_test_condition_table():
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

    assert not source_extraction._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_allows_semantic_fallback_for_untyped_table_test_condition():
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

    assert not source_extraction._objective_table_route_should_skip_llm_fallback(route)


def test_research_objective_service_allows_semantic_fallback_for_off_target_result_table():
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

    assert not source_extraction._objective_table_route_should_skip_llm_fallback(route)
    assert not source_extraction._objective_table_route_should_skip_llm_fallback(corrosion_route)

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

    assert not source_extraction._objective_table_route_should_skip_llm_fallback(eis_route)


def test_table_without_deterministic_result_mapping_uses_source_extractor() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect densification index?",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["densification index"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-semantic-result",
            "role": "test_condition",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    table = SimpleNamespace(
        table_id=route.source_ref,
        document_id=route.document_id,
        page=4,
        caption_text=(
            "Results for the selected processing conditions. DIDX means densification index."
        ),
        heading_path="Results",
        column_headers=["Specimen", "DIDX"],
        header_row_count=1,
        table_matrix=[
            ["Specimen", "DIDX"],
            ["LP-1", "99.1 %"],
        ],
    )
    extractor = _StudySourceEvidenceExtractor(
        {
            route.source_ref: {
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": None,
                "reported_result": {
                    "outcome": "DIDX",
                    "value": 99.1,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": "DIDX = 99.1 %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "Specimen", "value": "LP-1"}],
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        }
    )

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(
            PaperAnalysisFrame.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": route.document_id,
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "changed_variables": ["laser power"],
                }
            ),
        ),
        objective_evidence_routes=(route,),
        blocks_by_document_id={},
        tables_by_document_id={route.document_id: [table]},
        document_trees_by_document_id={},
    )

    assert extractor.calls == [route.source_ref]
    assert len(units) == 1
    assert units[0].reported_result is not None
    assert units[0].reported_result.value == 99.1


def test_primary_results_measurement_without_comparison_verb_is_direct_candidate() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    candidate = {
        "source_kind": "text_window",
        "source_ref": "result-measurement",
        "section_label": "Results",
        "text": "The relative density was 99.1 % at the selected laser setting.",
    }

    assert evidence_routing._route_text_candidate_is_direct_result(
        objective_context=objective,
        candidate=candidate,
    )


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


def test_objective_evidence_prompt_preserves_group_to_condition_mapping() -> None:
    """Context extraction must preserve the experimenter's group mapping.

    A Methods paragraph commonly defines more than one group in one Source.
    Flattening ``NP``/``P150`` and their two temperatures into parallel lists
    loses the one-to-one mapping a researcher uses to join Results to Methods.
    """

    system_prompt, _user_prompt = source_extraction.build_objective_evidence_prompt(
        {
            "objective": {
                "question": "How does treatment affect strength?",
                "variables": ["treatment temperature"],
                "outcomes": ["strength"],
            },
            "source": {
                "text": (
                    "Group R0 was untreated. Group R1 was treated at 150 C."
                )
            },
        }
    )

    assert "one context extraction per explicitly defined group" in system_prompt
    assert "Never combine multiple group labels" in system_prompt
    assert "explicit, unique one-to-one mapping" in system_prompt


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


def test_paper_reconstruction_does_not_fill_context_from_preliminary_scope() -> None:
    evidence = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "density-result",
            "objective_id": "obj-density",
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

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-1",
        source_facts=(evidence,),
        objectives=(),
    )[0]

    assert reconstructed.scientific_context.to_record() == {
        "material": [],
        "sample": [],
        "process": [
            {"name": "hatch space", "value": 0.1, "unit": "mm"},
        ],
        "test": [],
    }


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


def test_reconstruction_records_validated_context_closure():
    objective = _research_objective(
        {
            "objective_id": "obj-closure",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-closure",
            "objective_id": objective.objective_id,
            "document_id": "paper-closure",
            "source_kind": "text_window",
            "source_ref": "results-closure",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 150,
                    "target_value": 200,
                    "unit": "W",
                }
            ],
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
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
                "material": [
                    {"name": "material", "value": "316L stainless steel"}
                ],
                "sample": [{"name": "sample", "value": "S2"}],
                "process": [
                    {"name": "laser power", "value": 200, "unit": "W"},
                    {"name": "hatch spacing", "value": 0.1, "unit": "mm"},
                ],
                "test": [{"name": "test method", "value": "density measurement"}],
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-closure",
                    "supports": [
                        "reported_result",
                        "changed_variables",
                        "comparison.labels",
                        "scientific_context.material",
                        "scientific_context.sample",
                        "scientific_context.process",
                        "scientific_context.test",
                    ],
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        paper_experiment.reconstruct_paper_experiments(
            collection_id=objective.collection_id,
            source_facts=(draft,),
            objectives=(objective,),
        )

    audit = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_validated_context_closure"
    )
    assert audit["closure_basis"] == (
        "validated_source_grounding_and_same_paper_binding"
    )
    assert audit["result_count"] == 1
    assert audit["closed_result_count"] == 1
    assert audit["evidence_grounding_complete"] is True
    assert audit["closure_complete"] is True


def test_reconstruction_closure_counts_raw_result_anchors_once_when_rows_form_comparison():
    """A table's raw rows and derived interval are one closed experiment series."""

    objective = _research_objective(
        {
            "objective_id": "obj-closure-series",
            "material_scope": ["316L stainless steel"],
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )

    def row(evidence_id: str, value: float, power: int) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-closure-series",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [],
                "comparison": None,
                "reported_result": {
                    "outcome": "relative density",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density was {value}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "material": [
                        {"name": "material", "value": "316L stainless steel"}
                    ],
                    "sample": [
                        {"name": "geometry", "value": "dog-bone coupon"}
                    ],
                    "process": [
                        {"name": "laser power", "value": power, "unit": "W"},
                        {"name": "hatch spacing", "value": 0.1, "unit": "mm"},
                    ],
                    "test": [
                        {"name": "method", "value": "density measurement"}
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-density",
                        "row_index": 1 if power == 150 else 2,
                    }
                ],
                "resolution_status": "partial",
                "confidence": 0.9,
            }
        )

    with capture_analysis_diagnostics() as diagnostics:
        reconstructed = paper_experiment.reconstruct_paper_experiments(
            collection_id=objective.collection_id,
            source_facts=(
                row("row-low", 98.1, 150),
                row("row-high", 99.2, 200),
            ),
            objectives=(objective,),
        )

    assert any(item.evidence_id.startswith("oeu_cmp_") for item in reconstructed)
    audit = next(
        record
        for record in diagnostics.records
        if record["trace_type"] == "objective_validated_context_closure"
    )
    assert audit["result_count"] == 2
    assert audit["result_anchor_count"] == 2
    assert audit["derived_comparison_count"] == 1
    assert audit["closed_result_count"] == 2
    assert audit["incomplete_result_count"] == 0
    assert audit["closure_complete"] is True


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

    assert low_to_high.attribution_scope == "association_only"
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


def test_cycle_qualified_fatigue_table_binds_to_same_paper_ved_conditions():
    """A cycle-qualified result table remains usable when its condition table is separate."""

    objective = _research_objective(
        {
            "objective_id": "obj-high-cycle-ved",
            "question": "How does volumetric energy density affect high cycle fatigue strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["high cycle fatigue strength"],
        }
    )
    process_table = SimpleNamespace(
        table_id="table-2",
        document_id="paper-ved-fatigue",
        caption_text="Fabrication parameters for 316L samples with varying VED.",
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
        document_id="paper-ved-fatigue",
        caption_text="Fatigue strength at 10 4 cycles for structures printed at different VEDs.",
        heading_path="Results",
        page=10,
        column_headers=("Printed 316L", "FAT at 10 4 cycles [MPa]"),
        table_matrix=(
            ("Printed 316L", "FAT at 10 4 cycles [MPa]"),
            ("L-VED", "340"),
            ("M-VED", "450"),
            ("H-VED", "470"),
        ),
        row_count=4,
        col_count=2,
    )

    hints = evidence_routing._build_objective_table_routing_hints(
        objective,
        tables=(process_table, result_table),
    )
    assert {hint.table_id: hint.role for hint in hints} == {
        "table-2": "condition_context",
        "table-5": "result_table",
    }

    routes: list[EvidenceCandidate] = []
    evidence_routing._append_objective_context_hint_routes(
        routes=routes,
        seen=set(),
        frame=PaperAnalysisFrame.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-ved-fatigue",
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
            for table in (process_table, result_table)
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
                tables=[process_table, result_table],
            ),
            objective_context=objective,
        )
    )

    results = tuple(item for item in units if item.reported_result is not None)
    assert len(results) == 3
    assert {
        item.reported_result.outcome
        for item in results
        if item.reported_result is not None
    } == {"fatigue strength"}
    bound = paper_experiment._bind_objective_result_process_context(units)
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        bound,
        objectives=(objective,),
    )
    # Three jointly varied conditions need two source-local links to preserve
    # the condition series.  The third all-pairs contrast is redundant and
    # would overweight this paper during Finding synthesis.
    assert len(comparisons) == 2
    assert {
        source_ref.get("source_excerpt")
        for comparison in comparisons
        for source_ref in comparison.source_refs
        if source_ref.get("source_ref") == "table-5"
    } >= {
        "Printed 316L: L-VED | FAT at 10 4 cycles [MPa]: 340",
        "Printed 316L: M-VED | FAT at 10 4 cycles [MPa]: 450",
        "Printed 316L: H-VED | FAT at 10 4 cycles [MPa]: 470",
    }
    assert all(item.comparison is not None for item in comparisons)
    assert all(
        {
            property_matching.normalize_property_label(variable.name)
            for variable in item.changed_variables
        }
        >= {"volumetric energy density"}
        for item in comparisons
    )


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
    assert comparison.attribution_scope == "association_only"
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

    measurements = tuple(
        item for item in measurements if item.reported_result is not None
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


def test_objective_table_records_preserve_measured_and_predicted_result_kinds():
    objective = _research_objective(
        {
            "objective_id": "obj-yield",
            "question": "How does laser power affect yield strength?",
            "variables": ["laser power"],
            "outcomes": ["yield strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-yield",
            "source_kind": "table",
            "source_ref": "table-yield",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Laser power (W)": "process",
                "Yield strength Experiment (MPa)": "result",
                "Yield strength Prediction (MPa)": "result",
            },
            "confidence": 0.9,
        }
    )
    source = {
        "source_kind": "table",
        "source_ref": route.source_ref,
        "caption_text": "Measured and predicted yield strength.",
        "column_headers": [
            "Laser power (W)",
            "Yield strength Experiment (MPa)",
            "Yield strength Prediction (MPa)",
        ],
        "table_matrix": [
            ["Laser power (W)", "Yield strength Experiment (MPa)", "Yield strength Prediction (MPa)"],
            ["160", "412", "405"],
            ["200", "438", "431"],
        ],
    }

    records = source_extraction._objective_result_table_matrix_records(
        route=route,
        source=source,
        objective_context=objective,
        headers=(
            "Laser power (W)",
            "Yield strength Experiment (MPa)",
            "Yield strength Prediction (MPa)",
        ),
        data_rows=(
            (1, ("160", "412", "405")),
            (2, ("200", "438", "431")),
        ),
    )

    assert len(records) == 4
    assert sorted(item["reported_result"]["result_kind"] for item in records) == [
        "measured",
        "measured",
        "predicted",
        "predicted",
    ]
    assert {item["reported_result"]["outcome"] for item in records} == {
        "yield strength"
    }
    assert all(item["attribution_scope"] == "descriptive_only" for item in records)

    drafts = tuple(ExtractedEvidenceDraft.from_mapping(item) for item in records)
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        drafts,
        objectives=(objective,),
    )
    assert len(comparisons) == 2
    assert {item.reported_result.result_kind for item in comparisons if item.reported_result} == {
        "measured",
        "predicted",
    }


def test_predicted_result_cannot_enter_finding_result_sets():
    result = ObjectiveEvidenceResult.from_mapping(
        {
            "outcome": "yield strength",
            "value": 405,
            "unit": "MPa",
            "direction": "increase",
            "result_text": "Predicted yield strength was 405 MPa.",
            "result_kind": "predicted",
        }
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col-test",
            "objective_id": "obj-yield",
            "analysis_version": 1,
            "evidence_id": "ev-predicted",
            "document_id": "paper-yield",
            "source_kind": "table",
            "source_ref": "table-yield",
            "source_excerpt": "Predicted yield strength was 405 MPa.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "reported_result": result.to_record(),
            "attribution_scope": "association_only",
            "resolution_status": "resolved",
            "changed_variables": [
                {"name": "laser power", "baseline_value": 120, "target_value": 160, "unit": "W"}
            ],
            "comparison": {
                "baseline_label": "120 W",
                "target_label": "160 W",
                "axis_names": ["laser power"],
                "comparable": True,
                "incomparability_reasons": [],
            },
        }
    )

    assert result.result_kind == "predicted"
    assert evidence.evidence_status == "descriptive"
