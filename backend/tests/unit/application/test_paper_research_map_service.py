from __future__ import annotations

import json
from threading import Lock
from time import sleep
from types import SimpleNamespace
from typing import Any

import pytest

from application.core.objectives.discovery.paper_understanding.paper_map_outputs import (
    ExperimentalPaperMapModelOutput,
)
from application.core.objectives.discovery.paper_understanding.paper_map_results import (
    StructuredPaperResearchMap,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from application.core.objectives.paper_map_aggregation import PaperMapAggregator
from application.core.objectives.paper_map_extraction import (
    PaperMapExtractionService,
)
from domain.core import PaperResearchMap, PaperResearchScope
from domain.source import (
    SourceDocument,
    build_source_document_tree,
    source_documents_from_records,
)
from infra.llm.usage import capture_llm_usage, record_llm_completion


def test_experimental_paper_map_accepts_bounded_unresolved_signal_overflow() -> None:
    signals = [
        {
            "signal_type": "outcome",
            "label": f"outcome {index}",
            "variable_role": "not_applicable",
            "source_labels": ["S1"],
        }
        for index in range(9)
    ]

    parsed = ExperimentalPaperMapModelOutput.model_validate(
        {"unresolved_signals": signals}
    )

    assert len(parsed.unresolved_signals) == 9


class _WindowExtractor:
    def __init__(
        self,
        *,
        window_failure_marker: str | None = None,
    ) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.window_failure_marker = window_failure_marker

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        return 0

    def extract(self, payload: dict[str, Any], *, before_request=None) -> StructuredPaperResearchMap:
        if before_request is not None:
            before_request()
        self.payloads.append(payload)
        source_units = payload.get("source_units") or []
        text = " ".join(
            str(unit.get("content") or "")
            for unit in source_units
            if isinstance(unit, dict)
        )
        if self.window_failure_marker and self.window_failure_marker in text:
            raise RuntimeError("window extraction unavailable")

        def source_ids(marker: str) -> list[str]:
            return [
                str(unit["source_unit_id"])
                for unit in source_units
                if isinstance(unit, dict) and marker in str(unit.get("content") or "")
            ]

        studies: list[dict[str, Any]] = []
        if "METHOD_CANDIDATE" in text:
            studies.append(
                _study(
                    varied_factors=["laser power"],
                    outcome="relative density",
                    source_unit_ids=source_ids("METHOD_CANDIDATE"),
                    confidence=0.81,
                )
            )
        if "RESULT_CANDIDATE" in text:
            studies.append(
                _study(
                    varied_factors=["scan speed"],
                    outcome="porosity",
                    source_unit_ids=source_ids("RESULT_CANDIDATE"),
                    confidence=0.94,
                )
            )
        if "DUPLICATE_CANDIDATE" in text:
            studies.append(
                _study(
                    material_scope=["316L stainless steel"],
                    process_context=["LPBF", "laser powder bed fusion"],
                    varied_factors=["scanning speed"],
                    outcome="porosity",
                    source_unit_ids=source_ids("DUPLICATE_CANDIDATE"),
                    confidence=0.97,
                )
            )
        if "UNKNOWN_SOURCE_CANDIDATE" in text:
            studies.append(
                _study(
                    varied_factors=["laser power"],
                    outcome="relative density",
                    source_unit_ids=["invented-source-unit"],
                    confidence=0.99,
                )
            )
        unresolved_signals: list[dict[str, Any]] = []
        markers = text.split()
        for marker, signal_type, label, process_context in (
            ("VARIABLE_SIGNAL", "variable", "laser power", ["LPBF"]),
            ("OUTCOME_SIGNAL", "outcome", "relative density", ["LPBF"]),
            (
                "HEAT_VARIABLE_SIGNAL",
                "variable",
                "heat-treatment temperature",
                ["heat treatment"],
            ),
            (
                "CORROSION_OUTCOME_SIGNAL",
                "outcome",
                "corrosion potential",
                ["electrochemical testing"],
            ),
            (
                "HEAT_OUTCOME_SIGNAL",
                "outcome",
                "microhardness",
                ["heat treatment"],
            ),
            (
                "BROAD_OUTCOME_SIGNAL",
                "outcome",
                "tensile properties",
                ["LPBF"],
            ),
        ):
            if marker in markers:
                unresolved_signals.append(
                    {
                        "signal_type": signal_type,
                        "label": label,
                        "variable_role": (
                            "varied"
                            if signal_type == "variable"
                            else "not_applicable"
                        ),
                        "material_scope": ["316L stainless steel"],
                        "process_context": process_context,
                        "source_unit_ids": source_ids(marker),
                        "confidence": 0.88,
                    }
                )
        return StructuredPaperResearchMap(
            doc_role="experimental",
            studies=studies,
            unresolved_signals=unresolved_signals,
            evidence_density="high" if studies or unresolved_signals else "low",
            confidence=0.92 if studies or unresolved_signals else 0.55,
            warnings=(
                []
                if studies or unresolved_signals
                else ["no linked study in this window"]
            ),
        )


def _study(
    *,
    varied_factors: list[str],
    outcome: str,
    material_scope: list[str] | None = None,
    process_context: list[str] | None = None,
    source_unit_ids: list[str] | None = None,
    confidence: float,
) -> dict[str, Any]:
    relationship: dict[str, Any] = {
        "varied_factors": varied_factors,
        "outcome": outcome,
        "confidence": confidence,
    }
    if source_unit_ids is not None:
        relationship["source_unit_ids"] = source_unit_ids
    else:
        relationship["source_refs"] = [
            {
                "source_kind": "block",
                "source_ref": "study-source",
            }
        ]
    return {
        "experiment_label": "experiment-1",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": material_scope or ["316L stainless steel"],
        "process_context": process_context or ["LPBF"],
        "relationships": [relationship],
        "confidence": confidence,
    }


def _artifacts(
    *,
    document_id: str = "paper-1",
    blocks: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
    table_rows: list[dict[str, Any]] | None = None,
    figures: list[dict[str, Any]] | None = None,
) -> tuple[tuple[SourceDocument, ...], Any]:
    artifacts = source_documents_from_records(
        documents=[
            {
                "id": document_id,
                "document_order": 1,
                "title": "Section-aware objective study",
                "text": "",
            }
        ],
        blocks=blocks,
        tables=tables or [],
        table_rows=table_rows or [],
        figures=figures or [],
    )
    document = artifacts[0]
    tree = build_source_document_tree(
        document=document,
        blocks=document.blocks,
        tables=document.tables,
        figures=document.figures,
        collection_id="collection-test",
    )
    return artifacts, tree


def _heading(
    block_id: str,
    text: str,
    order: int,
    *,
    document_id: str = "paper-1",
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "document_id": document_id,
        "block_type": "heading",
        "text": text,
        "block_order": order,
        "heading_path": text,
        "heading_level": 1,
    }


def _paragraph(
    block_id: str,
    text: str,
    order: int,
    heading_path: str,
    *,
    document_id: str = "paper-1",
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "document_id": document_id,
        "block_type": "paragraph",
        "text": text,
        "block_order": order,
        "heading_path": heading_path,
    }


def _build_skims(
    artifacts: tuple[SourceDocument, ...],
    tree: Any,
    extractor: Any,
    *,
    progress: list[dict[str, Any]] | None = None,
) -> tuple[PaperResearchMap, ...]:
    return PaperResearchMapService().build_collection_paper_maps(
        "collection-test",
        documents=artifacts,
        profiles_by_document_id={},
        document_trees_by_document_id={artifacts[0].document_id: tree},
        paper_map_extractor=extractor,
        progress_callback=progress.append if progress is not None else None,
    )


def test_paper_map_record_keeps_only_the_stable_source_link():
    skim = PaperResearchMap.from_mapping({"document_id": "paper-1"})

    record = skim.to_record()

    assert record["document_id"] == "paper-1"
    assert "title" not in record
    assert "source_filename" not in record


def test_paper_map_record_preserves_explicit_map_insufficiency():
    skim = PaperResearchMap.from_mapping(
        {
            "document_id": "paper-1",
            "map_status": "insufficient_map",
            "map_limitations": ["missing_outcome"],
        }
    )

    restored = PaperResearchMap.from_mapping(skim.to_record())

    assert restored.map_status == "insufficient_map"
    assert restored.map_limitations == ("missing_outcome",)


def test_every_source_unit_receives_one_explicit_coverage_outcome():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("relationship", "RESULT_CANDIDATE", 2, "Results"),
            _paragraph("signal", "VARIABLE_SIGNAL", 3, "Results"),
            _paragraph("background", "BACKGROUND_ONLY", 4, "Results"),
        ]
    )

    skim = _build_skims(artifacts, tree, _WindowExtractor())[0]

    coverage_by_ref = {
        item.source_ref: item.status.value for item in skim.source_unit_coverage
    }
    assert coverage_by_ref == {
        "relationship": "relationship_emitted",
        "signal": "unresolved_signal_emitted",
        "background": "no_study_signal",
    }
    assert next(
        item.reason
        for item in skim.source_unit_coverage
        if item.source_ref == "background"
    ) == (
        "No study relationship or unresolved signal was emitted for this Source "
        "unit."
    )
    assert skim.coverage_complete is True


def test_one_context_window_preserves_all_repeated_signal_lineage():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            *[
                _paragraph(
                    f"variable-{position}",
                    "VARIABLE_SIGNAL",
                    position + 1,
                    "Methods",
                )
                for position in range(1, 7)
            ],
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert len(extractor.payloads[0]["source_units"]) == 6
    assert len(skim.unresolved_signals) == 1
    assert {
        source_ref.source_ref
        for signal in skim.unresolved_signals
        for source_ref in signal.source_refs
    } == {f"variable-{position}" for position in range(1, 7)}
    assert len(skim.source_unit_coverage) == 6
    assert skim.coverage_complete is True


def test_unrepaired_duplicate_study_identity_marks_the_whole_window_failed():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("duplicate-window", "RESULT_CANDIDATE", 2, "Results"),
        ]
    )

    class DuplicateStudyExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any], *, before_request=None) -> StructuredPaperResearchMap:
            if before_request is not None:
                before_request()
            parsed = super().extract(payload)
            return StructuredPaperResearchMap.model_construct(
                doc_role=parsed.doc_role,
                studies=[*parsed.studies, *parsed.studies],
                unresolved_signals=parsed.unresolved_signals,
                evidence_density=parsed.evidence_density,
                confidence=parsed.confidence,
                warnings=parsed.warnings,
            )

    skim = _build_skims(artifacts, tree, DuplicateStudyExtractor())[0]

    assert skim.studies == ()
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "extraction_failed"
    ]
    assert skim.source_unit_coverage[0].reason
    assert skim.coverage_complete is False


def test_failed_window_preserves_valid_results_from_other_windows():
    class PromptBoundExtractor(_WindowExtractor):
        def estimate_prompt_tokens(self, payload):
            return 20_000 if len(payload["source_units"]) > 1 else 1_000

    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("failed", "FAIL_WINDOW", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph("valid", "RESULT_CANDIDATE", 4, "Results"),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        PromptBoundExtractor(window_failure_marker="FAIL_WINDOW"),
    )[0]

    assert len(skim.studies) == 1
    assert {
        item.source_ref: item.status.value for item in skim.source_unit_coverage
    } == {
        "failed": "extraction_failed",
        "valid": "relationship_emitted",
    }
    assert skim.coverage_complete is False


def test_unstructured_paper_map_samples_edges_then_expands_once_without_duplicates():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            *[
                _paragraph(
                    f"result-{position}",
                    f"BACKGROUND_ONLY_{position}",
                    position + 2,
                    "Results",
                )
                for position in range(25)
            ],
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 4
    assert all(len(payload["source_units"]) <= 8 for payload in extractor.payloads)
    covered_refs = [item.source_ref for item in skim.source_unit_coverage]
    assert covered_refs[:8] == [
        "result-0", "result-1", "result-2", "result-3",
        "result-21", "result-22", "result-23", "result-24",
    ]
    assert len(covered_refs) == len(set(covered_refs)) == 25
    assert skim.map_status == "insufficient_map"


def test_independent_windows_run_concurrently_and_merge_in_source_order(monkeypatch):
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            *[
                _paragraph(
                    f"abstract-{position:02d}",
                    f"ABSTRACT_SCOPE_{position}",
                    position + 2,
                    "Abstract",
                )
                for position in range(4)
            ],
            _heading("conclusion", "Conclusions", 10),
            *[
                _paragraph(
                    f"conclusion-{position:02d}",
                    f"CONCLUSION_SCOPE_{position}",
                    position + 11,
                    "Conclusions",
                )
                for position in range(4)
            ],
        ]
    )

    class ConcurrentExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self._lock = Lock()
            self._active_calls = 0
            self.max_active_calls = 0

        def estimate_prompt_tokens(self, payload):
            return 20_000 if len(payload["source_units"]) > 4 else 1_000

        def extract(self, payload: dict[str, Any], *, before_request=None) -> StructuredPaperResearchMap:
            if before_request is not None:
                before_request()
            with self._lock:
                self._active_calls += 1
                self.max_active_calls = max(
                    self.max_active_calls,
                    self._active_calls,
                )
            try:
                sleep(0.02)
                record_llm_completion(
                    SimpleNamespace(
                        model="test-model",
                        usage=SimpleNamespace(
                            prompt_tokens=10,
                            completion_tokens=5,
                            total_tokens=15,
                        ),
                    ),
                    requested_model="test-model",
                )
                return super().extract(payload)
            finally:
                with self._lock:
                    self._active_calls -= 1

    monkeypatch.setenv("CORE_EXTRACTION_MAX_CONCURRENCY", "2")
    extractor = ConcurrentExtractor()

    with capture_llm_usage() as usage:
        skim = _build_skims(artifacts, tree, extractor)[0]

    assert extractor.max_active_calls == 2
    assert usage.execution_stats().model_usage[0].request_count == 2
    assert [item.source_ref for item in skim.source_unit_coverage] == [
        *[f"abstract-{position:02d}" for position in range(4)],
        *[f"conclusion-{position:02d}" for position in range(4)],
    ]


def test_complete_prompt_budget_packs_source_units_beyond_four_thousand_chars():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result-a", "A" * 2500, 2, "Results"),
            _paragraph("result-b", "B" * 2500, 3, "Results"),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert [
        unit["source_ref"] for unit in extractor.payloads[0]["source_units"]
    ] == ["result-a", "result-b"]
    assert len(skim.source_unit_coverage) == 2


def test_paper_map_groups_bounded_sources_by_reading_role():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods-a", "Materials and Methods", 1),
            _paragraph("method-a", "BACKGROUND_ONLY_A", 2, "Materials and Methods"),
            _heading("methods-b", "Validation Methods", 3),
            _paragraph("method-b", "BACKGROUND_ONLY_B", 4, "Validation Methods"),
        ]
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)
    assert [payload["section_paths"] for payload in extractor.payloads] == [[
        "Materials and Methods",
        "Validation Methods",
    ]]
    assert [
        [unit["source_ref"] for unit in payload["source_units"]]
        for payload in extractor.payloads
    ] == [["method-a", "method-b"]]


def test_sparse_high_level_sources_are_all_read_before_quota_is_applied():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            *[
                _paragraph(
                    f"abstract-{position:02d}",
                    f"ABSTRACT_SCOPE_{position}",
                    position + 2,
                    "Abstract",
                )
                for position in range(6)
            ],
        ]
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    mapped_refs = [
        unit["source_ref"]
        for payload in extractor.payloads
        for unit in payload["source_units"]
    ]
    assert mapped_refs == [f"abstract-{position:02d}" for position in range(6)]


def test_complete_prompt_token_preflight_splits_before_model_execution():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result-a", "BACKGROUND_ONLY_A", 2, "Results"),
            _paragraph("result-b", "BACKGROUND_ONLY_B", 3, "Results"),
        ]
    )

    class PromptBoundExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.preflight_payloads: list[dict[str, Any]] = []

        def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
            if "source_units" not in payload:
                return super().estimate_prompt_tokens(payload)
            self.preflight_payloads.append(payload)
            return 20_000 if len(payload["source_units"]) > 1 else 1_000

    extractor = PromptBoundExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.preflight_payloads) == 3
    assert [len(payload["source_units"]) for payload in extractor.payloads] == [1, 1]
    assert [
        unit["source_unit_id"]
        for payload in extractor.payloads
        for unit in payload["source_units"]
    ] == ["source-unit-000001", "source-unit-000002"]
    assert len(skim.source_unit_coverage) == 2


def test_paper_map_reads_high_level_scope_before_detailed_experiment_sources():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph(
                "abstract-scope",
                "METHOD_CANDIDATE summarizes the paper research scope.",
                2,
                "Abstract",
            ),
            _heading("methods", "Materials and Methods", 3),
            _paragraph(
                "method-detail",
                "Detailed specimen preparation that must wait for an Objective.",
                4,
                "Materials and Methods",
            ),
            _heading("results", "Results", 5),
            _paragraph(
                "result-detail",
                "RESULT_CANDIDATE appears only in detailed Results.",
                6,
                "Results",
            ),
            _heading("conclusion", "Conclusions", 7),
            _paragraph(
                "conclusion-scope",
                "The paper concludes with its high-level material response scope.",
                8,
                "Conclusions",
            ),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert [
        relationship.varied_factors
        for study in skim.studies
        for relationship in study.relationships
    ] == [("laser power",)]
    mapped_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
    }
    assert mapped_refs == {"abstract-scope", "conclusion-scope"}


def test_paper_map_balances_table_and_figure_summaries():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph(
                "abstract-scope",
                "METHOD_CANDIDATE summarizes the research scope.",
                2,
                "Abstract",
            ),
        ],
        tables=[
            {
                "table_id": f"table-{position}",
                "document_id": "paper-1",
                "table_order": position,
                "caption_text": f"Table {position} scope",
                "heading_path": "Results",
                "column_headers": ["condition", "response"],
                "table_matrix": [],
            }
            for position in range(1, 5)
        ],
        figures=[
            {
                "figure_id": f"figure-{position}",
                "document_id": "paper-1",
                "figure_order": position,
                "caption_text": f"Figure {position} scope",
                "heading_path": "Results",
            }
            for position in range(1, 5)
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    selected_kinds = {
        str(unit["source_kind"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
    }
    assert {"table", "figure"} <= selected_kinds


def test_paper_map_expands_once_to_results_when_high_level_scope_lacks_outcome():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph(
                "abstract-variable",
                "VARIABLE_SIGNAL",
                2,
                "Abstract",
            ),
            _heading("results", "Results", 3),
            _paragraph(
                "result-scope",
                "RESULT_CANDIDATE",
                4,
                "Results",
            ),
            _heading("methods", "Materials and Methods", 5),
            _paragraph(
                "method-detail",
                "Detailed preparation remains deferred.",
                6,
                "Materials and Methods",
            ),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert [
        [unit["source_ref"] for unit in payload["source_units"]]
        for payload in extractor.payloads
    ] == [["abstract-variable"], ["abstract-variable", "result-scope"]]
    assert skim.map_status == "sufficient"
    assert skim.map_limitations == ()


def test_paper_map_stops_when_targeted_expansion_adds_no_new_scope():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph(
                "abstract-variable",
                "VARIABLE_SIGNAL",
                2,
                "Abstract",
            ),
            _heading("results", "Results", 3),
            _paragraph(
                "result-background",
                "No measured response is stated here.",
                4,
                "Results",
            ),
            _heading("methods", "Materials and Methods", 5),
            _paragraph(
                "method-background",
                "The specimen preparation does not identify a response.",
                6,
                "Materials and Methods",
            ),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 2
    assert extractor.payloads[1]["source_units"][-1]["source_ref"] == (
        "result-background"
    )
    assert skim.map_status == "insufficient_map"
    assert "missing_outcome" in skim.map_limitations


def test_spaced_abstract_heading_prevents_detailed_source_fallback():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "a b s t r a c t", 1),
            _paragraph(
                "abstract-scope",
                "METHOD_CANDIDATE states the paper research scope.",
                2,
                "a b s t r a c t",
            ),
            _heading("introduction", "1. Introduction", 3),
            _paragraph(
                "introduction-scope",
                "The introduction orients the research question.",
                4,
                "1. Introduction",
            ),
            _heading("methods", "2. Materials and Methods", 5),
            _paragraph(
                "method-detail",
                "RESULT_CANDIDATE belongs to confirmed-Objective inspection.",
                6,
                "2. Materials and Methods",
            ),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert [
        relationship.varied_factors
        for study in skim.studies
        for relationship in study.relationships
    ] == [("laser power",)]
    mapped_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
    }
    assert mapped_refs == {"abstract-scope", "introduction-scope"}


def test_paper_map_fallback_samples_both_ends_under_a_global_source_limit():
    artifacts, tree = _artifacts(
        blocks=[
            _paragraph(
                f"unstructured-{position:02d}",
                f"Unstructured paper content {position}",
                position,
                "Unsectioned",
            )
            for position in range(1, 41)
        ]
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    mapped_refs = [
        str(unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
    ]
    assert len(mapped_refs) <= 16
    assert "unstructured-01" in mapped_refs
    assert "unstructured-40" in mapped_refs


def test_one_long_source_paragraph_remains_whole_when_prompt_fits():
    source_text = "B" * 8500
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("long-result", source_text, 2, "Results"),
        ]
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    text_units = [
        str(unit["content"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "block"
    ]
    assert len(extractor.payloads) == 1
    assert len(text_units) == 1
    assert "".join(text_units) == source_text


def test_long_source_paragraph_preserves_sentence_boundary_when_prompt_fits():
    source_text = f"{'A' * 3500}. {'B' * 1000}"
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("long-result", source_text, 2, "Results"),
        ]
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    text_units = [
        str(unit["content"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "block"
    ]
    assert len(text_units) == 1
    assert ". " in text_units[0]
    assert "".join(text_units) == source_text


def test_methods_and_results_windows_retain_distinct_linked_candidates():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Materials and Methods", 1),
            _paragraph(
                "method-candidate",
                "METHOD_CANDIDATE",
                2,
                "Materials and Methods",
            ),
            _heading("results", "Results and Discussion", 3),
            _paragraph(
                "result-candidate",
                "RESULT_CANDIDATE",
                4,
                "Results and Discussion",
            ),
        ]
    )
    extractor = _WindowExtractor()

    skims = _build_skims(artifacts, tree, extractor)

    assert [
        relationship.varied_factors
        for study in skims[0].studies
        for relationship in study.relationships
    ] == [
        ("laser power",),
        ("scan speed",),
    ]
    assert {payload["window_role"] for payload in extractor.payloads} == {"overview"}
    assert extractor.payloads[0]["section_paths"] == ["Materials and Methods", "Results and Discussion"]


def test_later_table_captions_are_assigned_to_a_screening_window():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result", "Results summary.", 2, "Results"),
        ],
        tables=[
            {
                "table_id": f"table-{position}",
                "document_id": "paper-1",
                "table_order": position,
                "caption_text": f"Table {position} result caption",
                "heading_path": "Results",
                "column_headers": ["condition", f"property-{position}"],
                "table_matrix": [["condition", f"property-{position}"]],
            }
            for position in range(1, 5)
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    table_ids = [
        unit["source_ref"]
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "table"
        and isinstance(unit["content"], dict)
        and "caption_text" in unit["content"]
    ]
    assert table_ids == ["table-1", "table-2", "table-3", "table-4"]


def test_paper_map_keeps_table_caption_but_defers_table_rows_until_analysis():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph(
                "abstract-scope",
                "This paper studies process conditions and measured density.",
                2,
                "Abstract",
            ),
            _heading("results", "Results", 3),
        ],
        tables=[
            {
                "table_id": "table-results",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "Process conditions and measured density",
                "heading_path": "Results",
                "column_headers": ["power", "speed", "relative density"],
                "table_matrix": [],
            }
        ],
        table_rows=[
            {
                "row_id": f"row-{position}",
                "document_id": "paper-1",
                "table_id": "table-results",
                "row_index": position,
                "row_text": f"power={position} | density={90 + position}",
                "heading_path": "Results",
            }
            for position in range(1, 31)
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    source_units = [
        unit
        for payload in extractor.payloads
        for unit in payload["source_units"]
    ]
    assert not any(unit["source_kind"] == "table_row" for unit in source_units)
    assert any(
        unit["source_kind"] == "table"
        and unit["source_ref"] == "table-results"
        and isinstance(unit["content"], dict)
        and unit["content"]["caption_text"]
        == "Process conditions and measured density"
        for unit in source_units
    )


def test_paper_map_compacts_table_metadata_without_losing_axis_headers():
    caption = f"Table 1. {' '.join(['caption detail'] * 700)}"
    headers = [
        f"header-{position}-"
        f"{' '.join(['measurement context'] * (260 if position == 5 else 8))}"
        for position in range(7)
    ]
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result", "Results summary.", 2, "Results"),
        ],
        tables=[
            {
                "table_id": "table-long-metadata",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": caption,
                "heading_path": "Results",
                "column_headers": headers,
                "table_matrix": [],
            }
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    source_units = [
        unit
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "table"
        and unit["source_ref"] == "table-long-metadata"
    ]
    assert len(source_units) == 1
    assert source_units[0]["content"]["caption_text"] == caption[:1600]
    assert source_units[0]["content"]["column_headers"] == [
        value[:120] for value in headers
    ]
    assert all(
        len(json.dumps(unit["content"], ensure_ascii=False, separators=(",", ":")))
        <= 4000
        for unit in source_units
    )
    assert {
        (unit["source_kind"], unit["source_ref"]) for unit in source_units
    } == {("table", "table-long-metadata")}


def test_paper_map_compacts_figure_caption_before_model_screening():
    caption = (
        f"Figure 1. {' '.join(['microstructure detail'] * 600)} "
        "RESULT_CANDIDATE"
    )
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result", "Results summary.", 2, "Results"),
        ],
        figures=[
            {
                "figure_id": "figure-long-caption",
                "document_id": "paper-1",
                "figure_order": 1,
                "figure_label": "Figure 1",
                "caption_text": caption,
                "heading_path": "Results",
            }
        ],
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    source_units = [
        unit
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "figure"
        and unit["source_ref"] == "figure-long-caption"
    ]
    assert len(source_units) == 1
    assert source_units[0]["content"]["caption_text"] == caption[:3500]
    assert all(
        len(json.dumps(unit["content"], ensure_ascii=False, separators=(",", ":")))
        <= 4000
        for unit in source_units
    )
    assert {
        (unit["source_kind"], unit["source_ref"]) for unit in source_units
    } == {("figure", "figure-long-caption")}
    assert skim.studies == ()


def test_initial_high_level_map_can_expand_to_results_but_still_defers_methods():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph("overview", "OVERVIEW_SOURCE", 2, "Abstract"),
            _heading("methods", "Methods", 3),
            _paragraph("method", "METHOD_SOURCE", 4, "Methods"),
            _heading("results", "Results", 5),
            _paragraph("result", "RESULT_SOURCE", 6, "Results"),
            _heading("references", "References", 7),
            _paragraph("reference", "REFERENCE_SOURCE", 8, "References"),
        ],
        tables=[
            {
                "table_id": "table-source",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "TABLE_SOURCE",
                "heading_path": "Results",
                "column_headers": ["condition", "result"],
                "table_matrix": [["condition", "result"]],
            }
        ],
        figures=[
            {
                "figure_id": "figure-source",
                "document_id": "paper-1",
                "figure_order": 1,
                "figure_label": "Figure 1",
                "caption_text": "FIGURE_SOURCE",
                "heading_path": "Methods",
            }
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    all_text = "\n".join(
        str(unit["content"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "block"
    )
    all_table_captions = [
        item["content"]["caption_text"]
        for payload in extractor.payloads
        for item in payload["source_units"]
        if item["source_kind"] == "table"
        and "caption_text" in item["content"]
    ]
    all_figure_captions = [
        item["content"]["caption_text"]
        for payload in extractor.payloads
        for item in payload["source_units"]
        if item["source_kind"] == "figure"
    ]
    assert all_text.count("OVERVIEW_SOURCE") == 1
    assert "METHOD_SOURCE" not in all_text
    assert all_text.count("RESULT_SOURCE") == 1
    assert "REFERENCE_SOURCE" not in all_text
    assert all_table_captions == ["TABLE_SOURCE"]
    assert all_figure_captions == ["FIGURE_SOURCE"]


def test_tables_and_figures_with_filename_heading_paths_reach_paper_map_before_references():
    artifacts, tree = _artifacts(
        blocks=[
            {**_heading("results", "Results", 1), "page": 2},
            {
                **_paragraph("result", "RESULT_SOURCE", 2, "Results"),
                "page": 2,
            },
            {**_heading("references", "References", 10), "page": 9},
            {
                **_paragraph("reference", "REFERENCE_SOURCE", 11, "References"),
                "page": 9,
            },
        ],
        tables=[
            {
                "table_id": "table-filename-heading",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "TABLE_SOURCE",
                "page": 4,
                "heading_path": "uploaded-paper.pdf",
                "column_headers": ["condition", "result"],
                "table_matrix": [["condition", "result"], ["A", "99.1"]],
            }
        ],
        figures=[
            {
                "figure_id": "figure-filename-heading",
                "document_id": "paper-1",
                "figure_order": 1,
                "figure_label": "Figure 1",
                "caption_text": "FIGURE_SOURCE",
                "page": 5,
                "heading_path": "uploaded-paper.pdf",
            }
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    source_keys = {
        (unit["source_kind"], unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
    }
    all_content = "\n".join(
        str(unit["content"])
        for payload in extractor.payloads
        for unit in payload["source_units"]
    )
    assert ("table", "table-filename-heading") in source_keys
    assert ("figure", "figure-filename-heading") in source_keys
    assert "REFERENCE_SOURCE" not in all_content


def test_complete_window_candidate_keeps_its_stable_source_reference():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result-candidate", "RESULT_CANDIDATE", 2, "Results"),
        ]
    )

    skim = _build_skims(artifacts, tree, _WindowExtractor())[0]

    relationship = skim.studies[0].relationships[0]
    assert [ref.to_record() for ref in relationship.source_refs] == [
        {"source_kind": "block", "source_ref": "result-candidate"}
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("sample_context", ["vertical coupon"]),
        ("test_context", ["room-temperature tensile test"]),
        ("comparator", "preheated versus unheated build platform"),
        ("fixed_conditions", ["laser power = 200 W"]),
    ),
)
def test_pre_objective_map_contract_rejects_experiment_context(
    field_name: str,
    value: object,
):
    study = {
        "experiment_label": "316L build-platform preheating study",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": ["316L stainless steel"],
        "process_context": ["laser powder bed fusion"],
        "relationships": [
            {
                "varied_factors": ["build platform preheating temperature"],
                "outcome": "porosity",
                "source_unit_ids": ["source-preheating-result"],
                "confidence": 0.93,
            }
        ],
        "confidence": 0.9,
        field_name: value,
    }

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        StructuredPaperResearchMap(studies=[study])


def test_broad_microstructure_theme_is_not_retained_as_a_relationship():
    payload = {
        "window_id": "results-1",
        "source_units": [
            {
                "source_unit_id": "source-microstructure",
                "source_kind": "block",
                "source_ref": "results-microstructure",
                "section_path": "Results",
                "content": "Heat treatment changed the microstructure.",
            }
        ],
    }
    parsed = StructuredPaperResearchMap(
        studies=[
            {
                "experiment_label": "heat-treatment experiment",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": ["Ti-6Al-4V"],
                "process_context": ["heat treatment"],
                "relationships": [
                    {
                        "varied_factors": ["heat treatment"],
                        "outcome": "microstructure",
                        "source_unit_ids": ["source-microstructure"],
                        "confidence": 0.8,
                    }
                ],
                "confidence": 0.8,
            }
        ]
    )

    skim, signals = PaperMapExtractionService()._resolve_window_result(
        document_id="paper-heat-treatment",
        payload=payload,
        parsed=parsed,
    )

    assert skim.studies == ()
    assert len(signals) == 1
    assert signals[0].signal_type == "outcome"
    assert signals[0].label == "microstructure"
    assert signals[0].source_refs[0].source_ref == "results-microstructure"
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "unresolved_signal_emitted"
    ]


def test_review_cited_experiment_cannot_become_current_work():
    source_unit_id = "source-review-citation"
    payload = {
        "window_id": "results-1",
        "document_profile": {"doc_type": "review"},
        "source_units": [
            {
                "source_unit_id": source_unit_id,
                "source_kind": "block",
                "source_ref": "review-result-87",
                "section_path": "Results and discussion",
                "content": (
                    "In the SAAM experiment, C-Mn steel specimens were reheated "
                    "and the microstructure was characterized [87]."
                ),
            }
        ],
    }
    parsed = StructuredPaperResearchMap(
        doc_role="review",
        studies=[
            {
                "experiment_label": "SAAM C-Mn steel experiment",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": ["C-Mn steel"],
                "process_context": ["reheating"],
                "relationships": [
                    {
                        "varied_factors": ["reheating condition"],
                        "outcome": "martensite fraction",
                        "source_unit_ids": [source_unit_id],
                        "confidence": 0.9,
                    }
                ],
                "confidence": 0.9,
            }
        ],
        unresolved_signals=[
            {
                "signal_type": "outcome",
                "label": "phase constitution",
                "experiment_label": "SAAM C-Mn steel experiment",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "source_unit_ids": [source_unit_id],
                "confidence": 0.8,
            }
        ],
    )

    skim, signals = PaperMapExtractionService()._resolve_window_result(
        document_id="review-paper",
        payload=payload,
        parsed=parsed,
    )

    assert skim.studies == ()
    assert signals == ()
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "no_study_signal"
    ]


def test_resolve_window_result_merges_duplicate_relationships_and_preserves_sources():
    payload = {
        "window_id": "results-duplicate-relationship",
        "source_units": [
            {
                "source_unit_id": "source-result-1",
                "source_kind": "block",
                "source_ref": "results-1",
                "content": "Laser power was varied and porosity was measured.",
            },
            {
                "source_unit_id": "source-result-2",
                "source_kind": "table",
                "source_ref": "table-1",
                "content": "Porosity values for the laser-power series.",
            },
        ],
    }
    parsed = StructuredPaperResearchMap(
        doc_role="experimental",
        studies=[
            {
                "experiment_label": "laser-power study",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "relationships": [
                    {
                        "varied_factors": ["laser power"],
                        "outcome": "porosity",
                        "source_unit_ids": ["source-result-1"],
                        "confidence": 0.7,
                    },
                    {
                        "varied_factors": ["laser power"],
                        "outcome": "porosity",
                        "source_unit_ids": ["source-result-2"],
                        "confidence": 0.9,
                    },
                ],
            }
        ],
    )

    skim, signals = PaperMapExtractionService()._resolve_window_result(
        document_id="paper-duplicate-relationship",
        payload=payload,
        parsed=parsed,
    )

    assert signals == ()
    assert len(skim.studies) == 1
    assert len(skim.studies[0].relationships) == 1
    relationship = skim.studies[0].relationships[0]
    assert relationship.varied_factors == ("laser power",)
    assert relationship.outcome == "porosity"
    assert {(item.source_kind, item.source_ref) for item in relationship.source_refs} == {
        ("block", "results-1"),
        ("table", "table-1"),
    }
    assert relationship.confidence == 0.9


def test_review_skim_retains_author_synthesis_but_discards_cited_studies():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("review", "Review of preheating", 1),
            _paragraph(
                "review-citation",
                (
                    "Miranda et al. [20] increased build plate temperature and "
                    "reported lower residual stress."
                ),
                2,
                "Review of preheating",
            ),
            _paragraph(
                "review-synthesis",
                (
                    "Across the reviewed studies, preheating generally reduced "
                    "residual stress."
                ),
                3,
                "Review of preheating",
            ),
        ]
    )

    class ReviewExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any], *, before_request=None) -> StructuredPaperResearchMap:
            if before_request is not None:
                before_request()
            self.payloads.append(payload)
            source_ids = {
                str(unit["source_ref"]): str(unit["source_unit_id"])
                for unit in payload["source_units"]
            }
            return StructuredPaperResearchMap(
                doc_role="review",
                studies=[
                    {
                        "experiment_label": "Miranda et al.",
                        "design_type": "experimental",
                        "claim_scope": "background",
                        "relationships": [
                            {
                                "varied_factors": ["build plate temperature"],
                                "outcome": "residual stress",
                                "source_unit_ids": [source_ids["review-citation"]],
                            }
                        ],
                    },
                    {
                        "experiment_label": "review synthesis on preheating",
                        "design_type": "observational",
                        "claim_scope": "synthesis",
                        "relationships": [
                            {
                                "varied_factors": ["preheating condition"],
                                "outcome": "residual stress",
                                "source_unit_ids": [source_ids["review-synthesis"]],
                            }
                        ],
                    },
                ],
                unresolved_signals=[
                    {
                        "signal_type": "outcome",
                        "label": "porosity",
                        "experiment_label": "Smith et al.",
                        "claim_scope": "background",
                        "source_unit_ids": [source_ids["review-citation"]],
                    }
                ],
                review_synthesis={
                    "synthesis_claims": [
                        {
                            "content": (
                                "Across the reviewed studies, preheating generally "
                                "reduced residual stress."
                            ),
                            "variables": ["preheating condition"],
                            "outcomes": ["residual stress"],
                            "source_unit_ids": [source_ids["review-synthesis"]],
                            "confidence": 0.9,
                        }
                    ],
                    "disputes": [
                        {
                            "content": "Porosity trends disagree across scan strategies.",
                            "variables": ["scan strategy"],
                            "outcomes": ["porosity"],
                            "source_unit_ids": [source_ids["review-synthesis"]],
                            "confidence": 0.7,
                        }
                    ],
                    "evidence_gaps": [
                        {
                            "content": "Few studies validate residual stress in situ.",
                            "outcomes": ["residual stress"],
                            "conditions": ["in situ validation"],
                            "source_unit_ids": [source_ids["review-synthesis"]],
                            "confidence": 0.75,
                        }
                    ],
                    "citation_leads": [
                        {
                            "content": "Miranda et al. [20]",
                            "variables": ["build plate temperature"],
                            "outcomes": ["residual stress"],
                            "source_unit_ids": [source_ids["review-citation"]],
                            "confidence": 0.8,
                        }
                    ],
                },
            )

    extractor = ReviewExtractor()
    skim = PaperResearchMapService().build_collection_paper_maps(
        "collection-test",
        documents=artifacts,
        profiles_by_document_id={
            "paper-1": SimpleNamespace(
                doc_type="review",
                profile_warnings=(),
                confidence=0.95,
            )
        },
        document_trees_by_document_id={"paper-1": tree},
        paper_map_extractor=extractor,
    )[0]

    assert [study.claim_scope for study in skim.studies] == ["synthesis"]
    assert skim.studies[0].relationships[0].source_refs[0].source_ref == (
        "review-synthesis"
    )
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "no_study_signal",
        "relationship_emitted",
    ]
    assert skim.review_synthesis.synthesis_claims[0].source_refs[0].source_ref == (
        "review-synthesis"
    )
    assert skim.review_synthesis.disputes[0].outcomes == ("porosity",)
    assert skim.review_synthesis.evidence_gaps[0].conditions == (
        "in situ validation",
    )
    assert skim.review_synthesis.citation_leads[0].content == "Miranda et al. [20]"
    assert all(
        study.experiment_label != "Miranda et al." for study in skim.studies
    )


def test_unknown_source_unit_id_marks_the_window_failed():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph(
                "result-candidate",
                "UNKNOWN_SOURCE_CANDIDATE",
                2,
                "Results",
            ),
        ]
    )

    skim = _build_skims(artifacts, tree, _WindowExtractor())[0]

    assert skim.studies == ()
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "extraction_failed"
    ]


def test_equivalent_candidates_from_multiple_windows_are_consolidated_once():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("method", "RESULT_CANDIDATE", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph("result", "DUPLICATE_CANDIDATE", 4, "Results"),
        ]
    )
    extractor = _WindowExtractor()

    skims = _build_skims(artifacts, tree, extractor)

    assert len(skims[0].studies) == 1
    study = skims[0].studies[0]
    assert study.relationships[0].varied_factors == ("scan speed",)
    assert study.relationships[0].outcome == "porosity"
    assert study.material_scope == ("316L stainless steel",)
    assert study.process_context == ("LPBF", "laser powder bed fusion")
    assert study.confidence == 0.97


def test_complementary_outcomes_with_one_experiment_identity_share_a_study():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        "document_id": "paper-1",
                        "experiment_label": "Ti-6Al-4V heat-treatment experiment",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["heat treatment at 920 C"],
                        "relationships": [
                            {
                                "varied_factors": ["heat treatment temperature"],
                                "outcome": "grain size",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": "results-grain-size",
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                        "confidence": 0.9,
                    }
                ],
            }
        ),
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        "document_id": "paper-1",
                        "experiment_label": "Ti-6Al-4V heat-treatment experiment",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["heat treatment at 920 C"],
                        "relationships": [
                            {
                                "varied_factors": ["heat treatment temperature"],
                                "outcome": "alpha phase fraction",
                                "source_refs": [
                                    {
                                        "source_kind": "table",
                                        "source_ref": "phase-fraction-table",
                                    }
                                ],
                                "confidence": 0.85,
                            }
                        ],
                        "confidence": 0.85,
                    }
                ],
            }
        ),
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 1
    assert {
        relationship.outcome for relationship in skim.studies[0].relationships
    } == {"grain size", "alpha phase fraction"}


def test_labeled_and_unlabeled_claims_without_shared_source_stay_separate():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        "document_id": "paper-1",
                        "experiment_label": "Ti-6Al-4V heat-treatment experiment",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["heat treatment"],
                        "relationships": [
                            {
                                "varied_factors": ["heat treatment temperature"],
                                "outcome": "grain size",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": "abstract-claim",
                                    }
                                ],
                                "confidence": 0.8,
                            }
                        ],
                        "confidence": 0.8,
                    }
                ],
            }
        ),
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        "document_id": "paper-1",
                        "experiment_label": None,
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["heat treatment"],
                        "relationships": [
                            {
                                "varied_factors": ["heat treatment temperature"],
                                "outcome": "grain size",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": "results-claim",
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                        "confidence": 0.9,
                    }
                ],
            }
        ),
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2
    assert {
        source_ref.source_ref
        for study in skim.studies
        for relationship in study.relationships
        for source_ref in relationship.source_refs
    } == {"abstract-claim", "results-claim"}


def test_different_experiment_labels_keep_equal_relationship_axes_separate():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        **_study(
                            varied_factors=["heat treatment temperature"],
                            outcome="grain size",
                            material_scope=["Ti-6Al-4V"],
                            process_context=["heat treatment"],
                            confidence=0.9,
                        ),
                        "experiment_label": experiment_label,
                    }
                ],
            }
        )
        for experiment_label in ("experiment A", "experiment B")
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_merged_relationship_identity_keeps_its_final_study_boundary():
    def merge_for_experiment(experiment_kind: str) -> PaperResearchScope:
        studies = tuple(
            PaperResearchScope.from_mapping(
                {
                    "document_id": "paper-1",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": f"{experiment_kind} experiment",
                    "relationships": [
                        {
                            "varied_factors": ["laser power"],
                            "outcome": "yield strength",
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": source_ref,
                                }
                            ],
                        }
                    ],
                }
            )
            for source_ref in ("methods-1", "results-1")
        )
        return PaperMapAggregator._merge_studies(
            studies[0],
            studies[1],
            document_id="paper-1",
        )

    tensile = merge_for_experiment("tensile")
    hardness = merge_for_experiment("microhardness")

    assert tensile.relationships[0].relationship_id != hardness.relationships[0].relationship_id


def test_merging_studies_collapses_duplicate_relationships_before_rebuilding_ids():
    """Repeated model aliases for one Source fact must not invalidate the paper map."""

    existing = PaperResearchScope.from_mapping(
        {
            "document_id": "paper-1",
            "design_type": "experimental",
            "claim_scope": "current_work",
            "experiment_label": "experiment-1",
            "material_scope": ["316L stainless steel"],
            "process_context": ["LPBF"],
            "relationships": [
                {
                    "relationship_id": "relationship-laser-power-1",
                    "varied_factors": ["laser power"],
                    "outcome": "porosity",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "results-1"}
                    ],
                },
                {
                    "relationship_id": "relationship-laser-power-2",
                    "varied_factors": ["laser power"],
                    "outcome": "Porosity",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "results-1"}
                    ],
                },
            ],
        }
    )
    duplicate = PaperResearchScope.from_mapping(
        {
            "document_id": "paper-1",
            "design_type": "experimental",
            "claim_scope": "current_work",
            "experiment_label": "experiment-1",
            "material_scope": ["316L stainless steel"],
            "process_context": ["LPBF"],
            "relationships": [
                {
                    "relationship_id": "relationship-scan-speed",
                    "varied_factors": ["scanning speed"],
                    "outcome": "porosity",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "results-1"}
                    ],
                },
                {
                    "relationship_id": "relationship-laser-power-alias",
                    "varied_factors": ["laser-power"],
                    "outcome": "porosity",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "results-1"}
                    ],
                },
            ],
        }
    )

    merged = PaperMapAggregator._merge_studies(
        existing,
        duplicate,
        document_id="paper-1",
    )

    assert len(merged.relationships) == 2
    assert len(
        {relationship.relationship_id for relationship in merged.relationships}
    ) == 2
    assert {
        tuple(relationship.varied_factors)
        for relationship in merged.relationships
    } == {("laser power",), ("scanning speed",)}


def test_candidates_with_different_variable_outcome_links_are_not_merged():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("method", "METHOD_CANDIDATE", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph("result", "RESULT_CANDIDATE", 4, "Results"),
        ]
    )

    skims = _build_skims(artifacts, tree, _WindowExtractor())

    assert len(skims[0].studies) == 2


def test_same_axes_with_incompatible_process_context_are_not_merged():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    _study(
                        varied_factors=["scan speed"],
                        outcome="porosity",
                        process_context=["LPBF"],
                        confidence=0.9,
                    )
                ],
            }
        ),
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    _study(
                        varied_factors=["scan speed"],
                        outcome="porosity",
                        process_context=["directed energy deposition"],
                        confidence=0.9,
                    )
                ],
            }
        ),
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_same_axes_with_partially_overlapping_material_scopes_are_not_merged():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    _study(
                        varied_factors=["scan speed"],
                        outcome="porosity",
                        material_scope=["316L stainless steel", "Inconel 718"],
                        confidence=0.9,
                    )
                ],
            }
        ),
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    _study(
                        varied_factors=["scan speed"],
                        outcome="porosity",
                        material_scope=["316L stainless steel", "Ti-6Al-4V"],
                        confidence=0.9,
                    )
                ],
            }
        ),
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_same_axes_and_context_without_shared_study_identity_are_not_merged():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        **_study(
                            varied_factors=["scan speed"],
                            outcome="porosity",
                            material_scope=["316L stainless steel"],
                            process_context=["LPBF"],
                            confidence=0.9,
                        ),
                        "experiment_label": None,
                        "relationships": [
                            {
                                "varied_factors": ["scan speed"],
                                "outcome": "porosity",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": "experiment-a-results",
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
            }
        ),
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "studies": [
                    {
                        **_study(
                            varied_factors=["scan speed"],
                            outcome="porosity",
                            material_scope=["316L stainless steel"],
                            process_context=["LPBF"],
                            confidence=0.9,
                        ),
                        "experiment_label": None,
                        "relationships": [
                            {
                                "varied_factors": ["scan speed"],
                                "outcome": "porosity",
                                "source_refs": [
                                    {
                                        "source_kind": "block",
                                        "source_ref": "experiment-b-results",
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                    }
                ],
            }
        ),
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_consolidation_keeps_only_the_first_two_unique_paper_warnings():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping(
            {
                "document_id": "paper-1",
                "warnings": [f"warning-{position}"],
            }
        )
        for position in range(4)
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert skim.warnings == ("warning-0", "warning-1")


def test_document_profile_owns_the_paper_role_across_windows():
    service = PaperResearchMapService()
    window_skims = [
        PaperResearchMap.from_mapping({"document_id": "paper-1", "doc_role": "review"}),
        PaperResearchMap.from_mapping(
            {"document_id": "paper-1", "doc_role": "experimental"}
        ),
    ]

    skim = service._paper_map_aggregator.consolidate_window_maps(
        "paper-1",
        window_skims,
        profile=SimpleNamespace(doc_type="experimental"),
    )

    assert skim.doc_role == "experimental"


@pytest.mark.parametrize(
    ("profile_doc_type", "input_scope", "expected_scope"),
    [
        ("review", "synthesis", "synthesis"),
        ("review", "current_work", "uncertain"),
        ("experimental", "current_work", "current_work"),
    ],
)
def test_document_profile_bounds_study_claim_scope(
    profile_doc_type: str,
    input_scope: str,
    expected_scope: str,
):
    study = PaperResearchScope.from_mapping(
        {
            **_study(
                varied_factors=["reheating condition"],
                outcome="martensite fraction",
                confidence=0.9,
            ),
            "document_id": "paper-1",
            "claim_scope": input_scope,
        }
    )

    skim = PaperMapAggregator().consolidate_window_maps(
        "paper-1",
        [
            PaperResearchMap.from_mapping(
                {
                    "document_id": "paper-1",
                    "doc_role": profile_doc_type,
                    "studies": [study.to_record()],
                }
            )
        ],
        profile=SimpleNamespace(doc_type=profile_doc_type),
    )

    assert skim.studies[0].claim_scope == expected_scope


def test_progress_remains_document_scoped_and_exposes_window_position():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph("overview", "Overview.", 2, "Abstract"),
            _heading("methods", "Methods", 3),
            _paragraph("method", "Methods.", 4, "Methods"),
            _heading("results", "Results", 5),
            _paragraph("result", "Results.", 6, "Results"),
        ]
    )
    progress: list[dict[str, Any]] = []

    _build_skims(artifacts, tree, _WindowExtractor(), progress=progress)

    assert [item["current"] for item in progress] == [1, 1]
    assert [item["total"] for item in progress] == [1, 1]
    assert [item["unit"] for item in progress] == ["documents", "documents"]
    assert [item["active_window_position"] for item in progress] == [1, 1]
    assert [item["active_window_count"] for item in progress] == [1, 1]
    assert [item["active_window_role"] for item in progress] == [
        "overview",
        "targeted_missing_outcome",
    ]
