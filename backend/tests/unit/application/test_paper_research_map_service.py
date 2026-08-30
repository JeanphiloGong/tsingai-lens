from __future__ import annotations

import json
from threading import Lock
from time import sleep
from types import SimpleNamespace
from typing import Any

import pytest

from application.core.objectives.discovery.signal_reconciliation import (
    StructuredPaperSignalReconciliation,
)
from application.core.objectives.discovery.study_window import (
    StructuredPaperResearchMap,
)
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from domain.core import PaperResearchMap, PaperResearchScope
from domain.source import (
    SourceDocument,
    build_source_document_tree,
    source_documents_from_records,
)
from infra.llm.usage import capture_llm_usage, record_llm_completion


class _WindowExtractor:
    def __init__(
        self,
        *,
        reconciliation: str = "link",
        window_failure_marker: str | None = None,
    ) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.reconciliation_payloads: list[dict[str, Any]] = []
        self.reconciliation = reconciliation
        self.window_failure_marker = window_failure_marker

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        return 0

    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
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

    def reconcile(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperSignalReconciliation:
        self.reconciliation_payloads.append(payload)
        if self.reconciliation == "raise":
            raise RuntimeError("reconciliation unavailable")
        signals = payload["signals"]
        if self.reconciliation == "invalid_id":
            return StructuredPaperSignalReconciliation(
                studies=[
                    {
                        "relationships": [
                            {
                                "signal_ids": [
                                    signals[0]["signal_id"],
                                    "invented-signal",
                                ],
                                "confidence": 0.9,
                            }
                        ]
                    }
                ],
                unresolved_signals=[],
            )
        if self.reconciliation == "unresolved":
            return StructuredPaperSignalReconciliation(
                studies=[],
                unresolved_signals=[
                    {
                        "signal_id": signal["signal_id"],
                        "reason": "The excerpts describe different experiments.",
                    }
                    for signal in signals
                ],
            )
        if self.reconciliation == "mixed_conflict":
            signals_by_label = {signal["label"]: signal for signal in signals}
            relationships = []
            for variable_label, outcome_label, confidence in (
                ("laser power", "relative density", 0.9),
                ("heat-treatment temperature", "relative density", 0.8),
            ):
                if (
                    variable_label in signals_by_label
                    and outcome_label in signals_by_label
                ):
                    relationships.append(
                        {
                            "signal_ids": [
                                signals_by_label[variable_label]["signal_id"],
                                signals_by_label[outcome_label]["signal_id"],
                            ],
                            "confidence": confidence,
                        }
                    )
            return StructuredPaperSignalReconciliation(
                studies=[{"relationships": relationships}] if relationships else [],
                unresolved_signals=[],
            )
        if self.reconciliation == "grouped_contexts":
            signals_by_label = {signal["label"]: signal for signal in signals}
            relationships = []
            for variable_label, outcome_label, confidence in (
                ("laser power", "relative density", 0.9),
                ("heat-treatment temperature", "microhardness", 0.88),
            ):
                if (
                    variable_label in signals_by_label
                    and outcome_label in signals_by_label
                ):
                    relationships.append(
                        {
                            "signal_ids": [
                                signals_by_label[variable_label]["signal_id"],
                                signals_by_label[outcome_label]["signal_id"],
                            ],
                            "confidence": confidence,
                        }
                    )
            return StructuredPaperSignalReconciliation(
                studies=[{"relationships": relationships}] if relationships else [],
                unresolved_signals=[],
            )
        return StructuredPaperSignalReconciliation(
            studies=[
                {
                    "relationships": [
                        {
                            "signal_ids": [signal["signal_id"] for signal in signals],
                            "confidence": 0.86,
                        }
                    ]
                }
            ],
            unresolved_signals=[],
        )


class _BoundedSignalReconciliationExtractor(_WindowExtractor):
    def __init__(
        self,
        signal_specs: dict[str, dict[str, Any]],
        *,
        prompt_signal_limit: int = 3,
        reject_later_batches: bool = False,
        response_mode: str = "link_all",
    ) -> None:
        super().__init__()
        self.signal_specs = signal_specs
        self.prompt_signal_limit = prompt_signal_limit
        self.reject_later_batches = reject_later_batches
        self.response_mode = response_mode

    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        self.payloads.append(payload)
        signals = []
        for source_unit in payload.get("source_units") or ():
            source_ref = str(source_unit.get("source_ref") or "")
            spec = self.signal_specs.get(source_ref)
            if spec is None:
                continue
            signals.append(
                {
                    **spec,
                    "source_unit_ids": [source_unit["source_unit_id"]],
                    "confidence": 0.9,
                }
            )
        return StructuredPaperResearchMap(
            doc_role="experimental",
            unresolved_signals=signals,
            evidence_density="high" if signals else "low",
            confidence=0.9,
        )

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        if "signals" not in payload:
            return super().estimate_prompt_tokens(payload)
        return 20_000 if len(payload["signals"]) > self.prompt_signal_limit else 1_000

    def reconcile(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperSignalReconciliation:
        self.reconciliation_payloads.append(payload)
        signals = payload["signals"]
        if self.response_mode == "omit_all":
            return StructuredPaperSignalReconciliation()
        if self.response_mode == "duplicate_linked_unresolved":
            return StructuredPaperSignalReconciliation(
                studies=[
                    {
                        "relationships": [
                            {
                                "signal_ids": [
                                    signal["signal_id"] for signal in signals
                                ],
                                "confidence": 0.9,
                            }
                        ]
                    }
                ],
                unresolved_signals=[
                    {
                        "signal_id": next(
                            signal["signal_id"]
                            for signal in signals
                            if signal["signal_type"] == "outcome"
                        ),
                        "reason": "The outcome was repeated by the model.",
                    }
                ],
            )
        if self.response_mode == "separate_relationships":
            outcome = next(
                signal for signal in signals if signal["signal_type"] == "outcome"
            )
            variables = [
                signal for signal in signals if signal["signal_type"] == "variable"
            ]
            return StructuredPaperSignalReconciliation(
                studies=[
                    {
                        "relationships": [
                            {
                                "signal_ids": [
                                    variable["signal_id"],
                                    outcome["signal_id"],
                                ],
                                "confidence": 0.9,
                            }
                            for variable in variables
                        ]
                    }
                ]
            )
        if self.response_mode in {
            "duplicate_relationships",
            "duplicate_signal_id",
        }:
            outcome = next(
                signal for signal in signals if signal["signal_type"] == "outcome"
            )
            variables = [
                signal for signal in signals if signal["signal_type"] == "variable"
            ]
            first_signal_ids = [
                variables[0]["signal_id"],
                outcome["signal_id"],
            ]
            duplicate_signal_ids = (
                [variables[0]["signal_id"], *first_signal_ids]
                if self.response_mode == "duplicate_signal_id"
                else list(reversed(first_signal_ids))
            )
            return StructuredPaperSignalReconciliation(
                studies=[
                    {
                        "relationships": [
                            {
                                "signal_ids": first_signal_ids,
                                "confidence": 0.9,
                            },
                            {
                                "signal_ids": duplicate_signal_ids,
                                "confidence": 0.7,
                            },
                            *[
                                {
                                    "signal_ids": [
                                        variable["signal_id"],
                                        outcome["signal_id"],
                                    ],
                                    "confidence": 0.85,
                                }
                                for variable in variables[1:]
                            ],
                        ]
                    }
                ]
            )
        if self.reject_later_batches and len(self.reconciliation_payloads) > 1:
            return StructuredPaperSignalReconciliation(
                unresolved_signals=[
                    {
                        "signal_id": signal["signal_id"],
                        "reason": "No shared experiment was established in this batch.",
                    }
                    for signal in signals
                ]
            )
        return StructuredPaperSignalReconciliation(
            studies=[
                {
                    "relationships": [
                        {
                            "signal_ids": [signal["signal_id"] for signal in signals],
                            "confidence": 0.9,
                        }
                    ]
                }
            ]
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
        signal_reconciler=extractor,
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


def test_four_source_windows_preserve_all_repeated_signal_lineage():
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

    assert len(extractor.payloads) == 2
    assert all(len(payload["source_units"]) <= 4 for payload in extractor.payloads)
    assert len(skim.unresolved_signals) == 2
    assert {
        source_ref.source_ref
        for signal in skim.unresolved_signals
        for source_ref in signal.source_refs
    } == {f"variable-{position}" for position in range(1, 7)}
    assert len(skim.source_unit_coverage) == 6
    assert skim.coverage_complete is True


def test_failed_batch_splits_until_only_permanent_source_unit_failure_remains(
    caplog: pytest.LogCaptureFixture,
):
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("relationship", "RESULT_CANDIDATE", 2, "Results"),
            _paragraph("background", "BACKGROUND_ONLY", 3, "Results"),
            _paragraph("failed", "FAIL_WINDOW", 4, "Results"),
            _paragraph("signal", "VARIABLE_SIGNAL", 5, "Results"),
        ]
    )
    extractor = _WindowExtractor(window_failure_marker="FAIL_WINDOW")

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(skim.studies) == 1
    assert {
        item.source_ref: item.status.value for item in skim.source_unit_coverage
    } == {
        "relationship": "relationship_emitted",
        "background": "no_study_signal",
        "failed": "extraction_failed",
        "signal": "unresolved_signal_emitted",
    }
    assert skim.coverage_complete is False
    parent_ids = {
        unit["source_unit_id"] for unit in extractor.payloads[0]["source_units"]
    }
    assert len(parent_ids) == 4
    assert all(
        {unit["source_unit_id"] for unit in payload["source_units"]} <= parent_ids
        for payload in extractor.payloads[1:]
    )
    assert all(
        source_unit_id.startswith("source-unit-")
        for source_unit_id in parent_ids
    )
    assert len(extractor.payloads) == 5
    assert any(
        "attempt=1 source_unit_count=4 error=window extraction unavailable"
        in record.message
        for record in caplog.records
    )
    assert any(
        "attempt=3 source_unit_count=1 error=window extraction unavailable"
        in record.message
        for record in caplog.records
    )


def test_retry_consolidates_duplicate_successful_relationships_once():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("candidate-1", "RESULT_CANDIDATE", 2, "Results"),
            _paragraph("failed", "FAIL_WINDOW", 3, "Results"),
            _paragraph("candidate-2", "RESULT_CANDIDATE", 4, "Results"),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        _WindowExtractor(window_failure_marker="FAIL_WINDOW"),
    )[0]

    assert len(skim.studies) == 1
    assert len(skim.studies[0].relationships) == 1
    assert {
        source_ref.source_ref
        for source_ref in skim.studies[0].relationships[0].source_refs
    } == {"candidate-1", "candidate-2"}
    assert [
        item.source_ref
        for item in skim.source_unit_coverage
        if item.status.value == "extraction_failed"
    ] == ["failed"]


def test_unrepaired_duplicate_study_identity_marks_the_whole_window_failed():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("duplicate-window", "RESULT_CANDIDATE", 2, "Results"),
        ]
    )

    class DuplicateStudyExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
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
        _WindowExtractor(window_failure_marker="FAIL_WINDOW"),
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
    assert all(len(payload["source_units"]) <= 4 for payload in extractor.payloads)
    covered_refs = [item.source_ref for item in skim.source_unit_coverage]
    assert covered_refs[:8] == [
        "result-0", "result-1", "result-2", "result-3",
        "result-21", "result-22", "result-23", "result-24",
    ]
    assert len(covered_refs) == len(set(covered_refs)) == 16
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

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
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


def test_model_declared_output_saturation_splits_without_losing_source_units():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result-a", "BACKGROUND_ONLY_A", 2, "Results"),
            _paragraph("result-b", "BACKGROUND_ONLY_B", 3, "Results"),
        ]
    )

    class SaturatingExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            if len(payload["source_units"]) > 1:
                self.payloads.append(payload)
                return StructuredPaperResearchMap(output_saturated=True)
            return super().extract(payload)

    extractor = SaturatingExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert [len(payload["source_units"]) for payload in extractor.payloads] == [2, 1, 1]
    assert {item.source_ref for item in skim.source_unit_coverage} == {
        "result-a",
        "result-b",
    }
    assert all(
        item.status.value == "no_study_signal"
        for item in skim.source_unit_coverage
    )


def test_short_singleton_saturation_recovers_through_source_local_signals():
    source_text = (
        "Miranda et al. increased build plate temperature and reported lower "
        "residual stress in laser powder bed fusion Ti-6Al-4V."
    )
    artifacts, tree = _artifacts(
        blocks=[
            _heading("review", "Review", 1),
            _paragraph("short-review-result", source_text, 2, "Review"),
        ]
    )

    class CompactFallbackExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.compact_payloads: list[dict[str, Any]] = []

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise StructuredOutputSaturatedError("singleton output saturated")

        def extract_source_signals(
            self,
            payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_payloads.append(payload)
            source_unit_id = payload["source_units"][0]["source_unit_id"]
            return StructuredPaperResearchMap.model_validate(
                {
                    "doc_role": "review",
                    "unresolved_signals": [
                        {
                            "signal_type": "variable",
                            "label": "build plate temperature",
                            "experiment_label": "Miranda et al.",
                            "claim_scope": "background",
                            "material_scope": ["Ti-6Al-4V"],
                            "process_context": ["laser powder bed fusion"],
                            "source_unit_ids": [source_unit_id],
                            "confidence": 0.88,
                        },
                        {
                            "signal_type": "outcome",
                            "label": "residual stress",
                            "experiment_label": "Miranda et al.",
                            "claim_scope": "background",
                            "material_scope": ["Ti-6Al-4V"],
                            "process_context": ["laser powder bed fusion"],
                            "source_unit_ids": [source_unit_id],
                            "confidence": 0.86,
                        },
                    ],
                    "evidence_density": "medium",
                    "confidence": 0.87,
                    "warnings": ["model warning one", "model warning two"],
                }
            )

    extractor = CompactFallbackExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert len(extractor.compact_payloads) == 1
    assert len(skim.studies) == 1
    assert skim.studies[0].claim_scope == "background"
    assert skim.studies[0].relationships[0].varied_factors == (
        "build plate temperature",
    )
    assert skim.studies[0].relationships[0].outcome == "residual stress"
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "unresolved_signal_emitted"
    ]
    assert skim.coverage_complete is True
    assert "source-local signals" in skim.warnings[0]
    assert skim.warnings[1] == "model warning one"


@pytest.mark.parametrize(
    "full_failure",
    [
        RuntimeError("structured extraction returned no JSON object"),
        json.JSONDecodeError("Expecting ':' delimiter", "{bad", 4),
        RuntimeError("structured extraction returned empty response content"),
    ],
    ids=["no-json-object", "malformed-json", "empty-response"],
)
def test_short_singleton_structured_failure_recovers_source_local_signals(
    full_failure: Exception,
):
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph(
                "short-result",
                "Reheating changed the observed grain morphology.",
                2,
                "Results",
            ),
        ]
    )

    class CompactFallbackExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.compact_payloads: list[dict[str, Any]] = []

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise full_failure

        def extract_source_signals(
            self,
            payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_payloads.append(payload)
            source_unit_id = payload["source_units"][0]["source_unit_id"]
            return StructuredPaperResearchMap.model_validate(
                {
                    "doc_role": "experimental",
                    "unresolved_signals": [
                        {
                            "signal_type": "outcome",
                            "label": "grain morphology",
                            "claim_scope": "current_work",
                            "source_unit_ids": [source_unit_id],
                            "confidence": 0.86,
                        }
                    ],
                }
            )

    extractor = CompactFallbackExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert len(extractor.compact_payloads) == 1
    assert [signal.label for signal in skim.unresolved_signals] == ["grain morphology"]
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "unresolved_signal_emitted"
    ]
    assert skim.coverage_complete is True
    assert "source-local signals" in skim.warnings[0]


def test_compact_singleton_retries_one_transient_empty_response():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("review", "Review", 1),
            _paragraph(
                "review-result",
                "Three reheating cycles changed the observed microstructure.",
                2,
                "Review",
            ),
        ]
    )

    class TransientCompactExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.compact_attempts = 0

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise StructuredOutputSaturatedError("singleton output saturated")

        def extract_source_signals(
            self,
            payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_attempts += 1
            if self.compact_attempts == 1:
                raise RuntimeError(
                    "structured extraction returned empty response content"
                )
            source_unit_id = payload["source_units"][0]["source_unit_id"]
            return StructuredPaperResearchMap.model_validate(
                {
                    "doc_role": "review",
                    "unresolved_signals": [
                        {
                            "signal_type": "outcome",
                            "label": "microstructure",
                            "claim_scope": "background",
                            "source_unit_ids": [source_unit_id],
                        }
                    ],
                }
            )

    extractor = TransientCompactExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert extractor.compact_attempts == 2
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "unresolved_signal_emitted"
    ]


def test_compact_singleton_records_the_final_technical_failure_kind():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("review", "Review", 1),
            _paragraph(
                "review-result",
                "Three reheating cycles changed the observed microstructure.",
                2,
                "Review",
            ),
        ]
    )

    class EmptyCompactExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.compact_attempts = 0

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise StructuredOutputSaturatedError("singleton output saturated")

        def extract_source_signals(
            self,
            _payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_attempts += 1
            raise RuntimeError(
                "structured extraction returned empty response content"
            )

    extractor = EmptyCompactExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert extractor.compact_attempts == 2
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "extraction_failed"
    ]
    assert "compact_empty_response" in skim.source_unit_coverage[0].reason


def test_dense_single_source_recovers_through_lossless_content_fragments():
    source_text = (
        "VARIABLE_SIGNAL "
        + "A" * 1000
        + ". "
        + "OUTCOME_SIGNAL "
        + "B" * 1000
    )
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("dense-result", source_text, 2, "Results"),
        ]
    )

    class DenseSourceExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            content = str(payload["source_units"][0]["content"])
            if len(content) > 1200:
                self.payloads.append(payload)
                raise StructuredOutputSaturatedError("dense singleton output")
            return super().extract(payload)

    extractor = DenseSourceExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 3
    parent_id = extractor.payloads[0]["source_units"][0]["source_unit_id"]
    child_units = [
        payload["source_units"][0] for payload in extractor.payloads[1:]
    ]
    assert "".join(str(unit["content"]) for unit in child_units) == source_text
    assert {unit["source_unit_id"] for unit in child_units} == {parent_id}
    assert {unit["source_kind"] for unit in child_units} == {"block"}
    assert {unit["source_ref"] for unit in child_units} == {"dense-result"}
    assert [payload["window_id"] for payload in extractor.payloads[1:]] == [
        "results-1.content-left",
        "results-1.content-right",
    ]
    assert len(skim.source_unit_coverage) == 1
    assert skim.source_unit_coverage[0].source_unit_id == parent_id
    assert skim.source_unit_coverage[0].status.value == (
        "unresolved_signal_emitted"
    )
    assert skim.coverage_complete is True
    assert len(skim.studies) == 1
    assert skim.studies[0].relationships[0].varied_factors == ("laser power",)
    assert skim.studies[0].relationships[0].outcome == "relative density"


def test_successful_fragment_survives_while_failed_parent_coverage_stays_incomplete():
    source_text = (
        "RESULT_CANDIDATE "
        + "A" * 1000
        + ". "
        + "PERMANENT_EMPTY "
        + "B" * 1000
    )
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("partial-result", source_text, 2, "Results"),
        ]
    )

    class PartiallyRecoveringExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            content = str(payload["source_units"][0]["content"])
            if len(content) > 1200:
                self.payloads.append(payload)
                raise StructuredOutputSaturatedError("dense singleton output")
            if "PERMANENT_EMPTY" in content:
                self.payloads.append(payload)
                raise RuntimeError(
                    "structured extraction returned empty response content"
                )
            return super().extract(payload)

        def extract_source_signals(
            self,
            _payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            raise RuntimeError("structured extraction returned empty response content")

    extractor = PartiallyRecoveringExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 3
    assert len(skim.studies) == 1
    assert skim.studies[0].relationships[0].outcome == "porosity"
    assert len(skim.source_unit_coverage) == 1
    assert skim.source_unit_coverage[0].status.value == "extraction_failed"
    assert "empty_response" in str(skim.source_unit_coverage[0].reason)
    assert skim.coverage_complete is False


def test_single_source_content_recovery_preserves_structured_table_context():
    row_text = "sample A | 950 MPa | " + "B" * 1900
    source_unit = {
        "source_unit_id": "source-unit-000123",
        "source_kind": "table_row",
        "source_ref": "row-7",
        "section_path": "Results > Tensile properties",
        "content": {
            "table_context": {
                "caption_text": "Table 3. Tensile properties",
                "column_headers": ["Sample", "Yield strength (MPa)"],
            },
            "row_id": "row-7",
            "row_text": row_text,
        },
    }

    fragments = PaperResearchMapService._split_single_source_unit_for_retry(source_unit)

    assert len(fragments) == 2
    assert "".join(
        str(fragment["content"]["row_text"]) for fragment in fragments
    ) == row_text
    assert all(
        fragment["content"]["table_context"]
        == source_unit["content"]["table_context"]
        for fragment in fragments
    )
    assert {
        (
            fragment["source_unit_id"],
            fragment["source_kind"],
            fragment["source_ref"],
        )
        for fragment in fragments
    } == {("source-unit-000123", "table_row", "row-7")}


def test_semantic_single_source_failure_does_not_trigger_content_splitting():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("invalid-result", "A" * 2500, 2, "Results"),
        ]
    )

    class SemanticFailureExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise ValueError("paper research map references unknown Source-unit ids")

    extractor = SemanticFailureExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "extraction_failed"
    ]


@pytest.mark.parametrize(
    ("error", "expected_kind"),
    [
        (
            StructuredOutputSaturatedError("completion limit reached"),
            "output_saturated",
        ),
        (
            RuntimeError("structured extraction returned empty response content"),
            "empty_response",
        ),
        (
            RuntimeError("structured extraction returned no JSON object"),
            "no_json_object",
        ),
        (
            json.JSONDecodeError("invalid JSON", "{", 1),
            "malformed_json",
        ),
        (RuntimeError("model unavailable"), None),
        (ValueError("unknown Source-unit id"), None),
    ],
)
def test_single_source_recovery_classifies_only_density_shaped_failures(
    error: Exception,
    expected_kind: str | None,
) -> None:
    assert PaperResearchMapService._single_source_recovery_kind(error) == expected_kind


def test_single_source_content_recovery_has_a_fixed_request_bound():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("always-dense", "A" * 4000, 2, "Results"),
        ]
    )

    class AlwaysSaturatedExtractor(_WindowExtractor):
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise StructuredOutputSaturatedError("dense singleton output")

    extractor = AlwaysSaturatedExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 6
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "extraction_failed"
    ]
    assert skim.coverage_complete is False


def test_paper_recovery_budget_bounds_saturated_batch_and_preserves_coverage():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("supported-method", "METHOD_CANDIDATE", 2, "Methods"),
            _heading("results", "Results", 3),
            *[
                _paragraph(
                    f"result-{position:02d}",
                    f"SATURATED_SOURCE_{position:02d}",
                    position + 4,
                    "Results",
                )
                for position in range(12)
            ],
        ]
    )

    class AlwaysSaturatedExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.compact_payloads: list[dict[str, Any]] = []

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            source_units = payload.get("source_units") or []
            if any(
                "METHOD_CANDIDATE" in str(unit.get("content") or "")
                for unit in source_units
            ):
                return StructuredPaperResearchMap(
                    doc_role="experimental",
                    studies=[
                        _study(
                            varied_factors=["laser power"],
                            outcome="relative density",
                            source_unit_ids=[source_units[0]["source_unit_id"]],
                            confidence=0.9,
                        )
                    ],
                )
            raise StructuredOutputSaturatedError("dense review output")

        def extract_source_signals(
            self,
            payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_payloads.append(payload)
            raise StructuredOutputSaturatedError("dense compact output")

    extractor = AlwaysSaturatedExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) + len(extractor.compact_payloads) <= 11
    assert len(skim.source_unit_coverage) == 8
    assert [study.relationships[0].outcome for study in skim.studies] == [
        "relative density"
    ]
    assert {item.status.value for item in skim.source_unit_coverage} == {
        "relationship_emitted",
        "extraction_failed",
    }
    assert all(
        "compact_output_saturated" in str(item.reason)
        for item in skim.source_unit_coverage
        if item.status.value == "extraction_failed"
    )


def test_saturated_paper_map_recovers_each_source_directly_with_compact_screening():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("scope", "Scope", 1),
            *[
                _paragraph(
                    f"scope-{position}",
                    f"Explicit research outcome {position}.",
                    position + 2,
                    "Scope",
                )
                for position in range(4)
            ],
        ]
    )

    class SaturatedMapExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__(reconciliation="unresolved")
            self.compact_payloads: list[dict[str, Any]] = []

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            raise StructuredOutputSaturatedError("paper map output saturated")

        def extract_source_signals(
            self,
            payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_payloads.append(payload)
            source_unit = payload["source_units"][0]
            return StructuredPaperResearchMap.model_validate(
                {
                    "doc_role": "experimental",
                    "unresolved_signals": [
                        {
                            "signal_type": "outcome",
                            "label": str(source_unit["content"]),
                            "claim_scope": "current_work",
                            "source_unit_ids": [source_unit["source_unit_id"]],
                            "confidence": 0.8,
                        }
                    ],
                }
            )

    extractor = SaturatedMapExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert len(extractor.compact_payloads) == 4
    assert len(skim.source_unit_coverage) == 4
    assert {item.status.value for item in skim.source_unit_coverage} == {
        "unresolved_signal_emitted"
    }
    assert skim.coverage_complete is True


def test_dense_source_in_saturated_map_uses_bounded_content_fragments():
    dense_text = "Dense explicit outcome " + "A" * 2200
    artifacts, tree = _artifacts(
        blocks=[
            _heading("scope", "Scope", 1),
            _paragraph("dense-scope", dense_text, 2, "Scope"),
            _paragraph("scope-2", "Explicit outcome 2.", 3, "Scope"),
            _paragraph("scope-3", "Explicit outcome 3.", 4, "Scope"),
            _paragraph("scope-4", "Explicit outcome 4.", 5, "Scope"),
        ]
    )

    class DenseSourceExtractor(_WindowExtractor):
        def __init__(self) -> None:
            super().__init__(reconciliation="unresolved")
            self.compact_payloads: list[dict[str, Any]] = []

        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
            self.payloads.append(payload)
            source_units = payload["source_units"]
            if len(source_units) > 1:
                raise StructuredOutputSaturatedError("paper map output saturated")
            source_unit = source_units[0]
            return StructuredPaperResearchMap.model_validate(
                {
                    "doc_role": "experimental",
                    "unresolved_signals": [
                        {
                            "signal_type": "outcome",
                            "label": "dense explicit outcome",
                            "claim_scope": "current_work",
                            "source_unit_ids": [source_unit["source_unit_id"]],
                            "confidence": 0.8,
                        }
                    ],
                }
            )

        def extract_source_signals(
            self,
            payload: dict[str, Any],
        ) -> StructuredPaperResearchMap:
            self.compact_payloads.append(payload)
            source_unit = payload["source_units"][0]
            if len(str(source_unit["content"])) > 1600:
                raise StructuredOutputSaturatedError("dense compact output")
            return StructuredPaperResearchMap.model_validate(
                {
                    "doc_role": "experimental",
                    "unresolved_signals": [
                        {
                            "signal_type": "outcome",
                            "label": str(source_unit["content"]),
                            "claim_scope": "current_work",
                            "source_unit_ids": [source_unit["source_unit_id"]],
                            "confidence": 0.8,
                        }
                    ],
                }
            )

    extractor = DenseSourceExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.compact_payloads) == 4
    assert len(extractor.payloads) == 3
    assert len(skim.source_unit_coverage) == 4
    assert all(
        item.status.value != "extraction_failed"
        for item in skim.source_unit_coverage
    )
    assert skim.coverage_complete is True


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
    ] == [["abstract-variable"], ["result-scope"]]
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
    extractor = _WindowExtractor(reconciliation="unresolved")

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 2
    assert extractor.payloads[1]["source_units"][0]["source_ref"] == (
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


def test_one_long_source_paragraph_is_split_into_bounded_units_without_text_loss():
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
    assert len(text_units) == 3
    assert all(len(text) <= 4000 for text in text_units)
    assert "".join(text_units) == source_text


def test_long_source_paragraph_prefers_a_natural_split_without_text_loss():
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
    assert text_units[0].endswith(". ")
    assert all(len(text) <= 4000 for text in text_units)
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
    assert {payload["window_role"] for payload in extractor.payloads} == {
        "methods",
        "results",
    }


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

    skim, signals = PaperResearchMapService()._resolve_window_result(
        document_id="paper-heat-treatment",
        payload=payload,
        parsed=parsed,
    )

    assert skim.studies == ()
    assert len(signals) == 1
    assert signals[0].signal.signal_type == "outcome"
    assert signals[0].signal.label == "microstructure"
    assert signals[0].signal.source_refs[0].source_ref == "results-microstructure"
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

    skim, signals = PaperResearchMapService()._resolve_window_result(
        document_id="review-paper",
        payload=payload,
        parsed=parsed,
    )

    assert skim.studies == ()
    assert signals == ()
    assert [item.status.value for item in skim.source_unit_coverage] == [
        "no_study_signal"
    ]


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
        def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
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
                parsing_warnings=(),
                confidence=0.95,
            )
        },
        document_trees_by_document_id={"paper-1": tree},
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
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


def test_methods_variable_and_results_outcome_reconcile_into_one_candidate():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("variable", "VARIABLE_SIGNAL", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph("outcome", "OUTCOME_SIGNAL", 4, "Results"),
        ]
    )
    progress: list[dict[str, Any]] = []
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor, progress=progress)[0]

    assert len(skim.studies) == 1
    relationship = skim.studies[0].relationships[0]
    assert relationship.varied_factors == ("laser power",)
    assert relationship.outcome == "relative density"
    assert {ref.source_ref for ref in relationship.source_refs} == {
        "variable",
        "outcome",
    }
    assert skim.unresolved_signals == ()
    assert len(extractor.reconciliation_payloads) == 1
    assert any(
        item.get("active_operation") == "paper_reconciliation" for item in progress
    )


def test_reconciliation_shares_the_paper_judgment_budget(monkeypatch):
    monkeypatch.setenv("CORE_PAPER_RESEARCH_MAP_MAX_RECOVERY_CALLS", "0")
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph(
                "scope-signals",
                "VARIABLE_SIGNAL OUTCOME_SIGNAL",
                2,
                "Abstract",
            ),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert extractor.reconciliation_payloads == []
    assert skim.studies == ()
    assert {signal.label for signal in skim.unresolved_signals} == {
        "laser power",
        "relative density",
    }
    assert all(
        signal.reason == "paper-map judgment budget exhausted before reconciliation"
        for signal in skim.unresolved_signals
    )
    assert {item.status.value for item in skim.source_unit_coverage} == {
        "unresolved_signal_emitted"
    }


def test_reconciliation_stops_after_using_the_remaining_paper_budget(monkeypatch):
    monkeypatch.setenv("CORE_PAPER_RESEARCH_MAP_MAX_RECOVERY_CALLS", "1")
    signal_specs = {
        "power": {
            "signal_type": "variable",
            "label": "laser power",
            "process_context": ["LPBF"],
        },
        "speed": {
            "signal_type": "variable",
            "label": "scan speed",
            "process_context": ["LPBF"],
        },
        "density": {
            "signal_type": "outcome",
            "label": "relative density",
            "process_context": ["LPBF"],
        },
        "porosity": {
            "signal_type": "outcome",
            "label": "porosity",
            "process_context": ["LPBF"],
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            *[
                _paragraph(source_ref, source_ref, position + 2, "Abstract")
                for position, source_ref in enumerate(signal_specs)
            ],
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(signal_specs)

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.payloads) == 1
    assert len(extractor.reconciliation_payloads) == 1
    assert {
        relationship.outcome
        for study in skim.studies
        for relationship in study.relationships
    } == {"relative density"}
    assert [(signal.label, signal.reason) for signal in skim.unresolved_signals] == [
        (
            "porosity",
            "paper-map judgment budget exhausted before reconciliation",
        )
    ]


def test_reconciliation_batches_repeat_one_outcome_without_dropping_variables():
    signal_specs = {
        f"variable-{position}": {
            "signal_type": "variable",
            "label": f"process variable {position}",
            "process_context": ["LPBF"],
        }
        for position in range(1, 6)
    }
    signal_specs["outcome"] = {
        "signal_type": "outcome",
        "label": "relative density",
        "process_context": ["LPBF"],
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("study", "Study", 1),
            *[
                _paragraph(
                    source_ref,
                    source_ref,
                    position + 1,
                    "Study",
                )
                for position, source_ref in enumerate(signal_specs)
            ],
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(signal_specs)

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert [
        len(payload["signals"]) for payload in extractor.reconciliation_payloads
    ] == [3, 3, 2]
    outcome_ids = [
        next(
            signal["signal_id"]
            for signal in payload["signals"]
            if signal["signal_type"] == "outcome"
        )
        for payload in extractor.reconciliation_payloads
    ]
    assert len(set(outcome_ids)) == 1
    assert all(
        sum(signal["signal_type"] == "outcome" for signal in payload["signals"])
        == 1
        for payload in extractor.reconciliation_payloads
    )
    assert {
        factor
        for study in skim.studies
        for relationship in study.relationships
        for factor in relationship.varied_factors
    } == {f"process variable {position}" for position in range(1, 6)}
    assert skim.unresolved_signals == ()


@pytest.mark.parametrize(
    "response_mode",
    ["duplicate_relationships", "duplicate_signal_id"],
)
def test_duplicate_reconciliation_relationship_keeps_valid_siblings(response_mode):
    signal_specs = {
        "power": {
            "signal_type": "variable",
            "label": "laser power",
            "process_context": ["LPBF"],
        },
        "speed": {
            "signal_type": "variable",
            "label": "scan speed",
            "process_context": ["LPBF"],
        },
        "outcome": {
            "signal_type": "outcome",
            "label": "relative density",
            "process_context": ["LPBF"],
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("study", "Study", 1),
            *[
                _paragraph(source_ref, source_ref, position + 1, "Study")
                for position, source_ref in enumerate(signal_specs)
            ],
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(
        signal_specs,
        response_mode=response_mode,
    )

    skim = _build_skims(artifacts, tree, extractor)[0]

    relationships = [
        relationship
        for study in skim.studies
        for relationship in study.relationships
    ]
    assert len(relationships) == 2
    assert {relationship.varied_factors for relationship in relationships} == {
        ("laser power",),
        ("scan speed",),
    }
    assert next(
        relationship
        for relationship in relationships
        if relationship.varied_factors == ("laser power",)
    ).confidence == pytest.approx(0.7)
    assert len({relationship.relationship_id for relationship in relationships}) == 2
    assert skim.unresolved_signals == ()


def test_material_only_distant_signals_do_not_enter_reconciliation():
    signal_specs = {
        "variable": {
            "signal_type": "variable",
            "label": "laser power",
            "material_scope": ["316L stainless steel"],
        },
        "outcome": {
            "signal_type": "outcome",
            "label": "relative density",
            "material_scope": ["316L stainless steel"],
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("variable", "variable", 2, "Methods"),
            *[
                _paragraph(
                    f"background-{position}",
                    "background",
                    position + 2,
                    "Methods",
                )
                for position in range(1, 14)
            ],
            _paragraph("outcome", "outcome", 16, "Methods"),
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(signal_specs)

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert extractor.reconciliation_payloads == []
    assert skim.studies == ()
    assert {signal.label for signal in skim.unresolved_signals} == {
        "laser power",
        "relative density",
    }
    assert all(
        signal.reason == "no paper-scope bridge was found in this paper"
        for signal in skim.unresolved_signals
    )


def test_a_linked_outcome_is_not_unresolved_by_a_later_candidate_batch():
    signal_specs = {
        "variable-1": {
            "signal_type": "variable",
            "label": "laser power",
            "process_context": ["LPBF"],
        },
        "variable-2": {
            "signal_type": "variable",
            "label": "scan speed",
            "process_context": ["LPBF"],
        },
        "outcome": {
            "signal_type": "outcome",
            "label": "relative density",
            "process_context": ["LPBF"],
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("study", "Study", 1),
            *[
                _paragraph(source_ref, source_ref, position + 1, "Study")
                for position, source_ref in enumerate(signal_specs)
            ],
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(
        signal_specs,
        prompt_signal_limit=2,
        reject_later_batches=True,
    )

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(extractor.reconciliation_payloads) == 2
    assert len(skim.studies) == 1
    assert skim.studies[0].relationships[0].outcome == "relative density"
    assert [signal.label for signal in skim.unresolved_signals] == ["scan speed"]


def test_backend_derives_unresolved_signals_omitted_by_one_batch_response():
    signal_specs = {
        "variable": {
            "signal_type": "variable",
            "label": "laser power",
            "process_context": ["LPBF"],
        },
        "outcome": {
            "signal_type": "outcome",
            "label": "relative density",
            "process_context": ["LPBF"],
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("study", "Study", 1),
            _paragraph("variable", "variable", 2, "Study"),
            _paragraph("outcome", "outcome", 3, "Study"),
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(
        signal_specs,
        response_mode="omit_all",
    )

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert skim.studies == ()
    assert len(skim.unresolved_signals) == 2
    assert all(
        signal.reason == "not linked in this candidate batch"
        for signal in skim.unresolved_signals
    )


def test_backend_ignores_model_unresolved_copy_of_a_linked_signal():
    signal_specs = {
        "variable": {
            "signal_type": "variable",
            "label": "laser power",
            "process_context": ["LPBF"],
        },
        "outcome": {
            "signal_type": "outcome",
            "label": "relative density",
            "process_context": ["LPBF"],
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("study", "Study", 1),
            _paragraph("variable", "variable", 2, "Study"),
            _paragraph("outcome", "outcome", 3, "Study"),
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(
        signal_specs,
        response_mode="duplicate_linked_unresolved",
    )

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(skim.studies) == 1
    assert skim.unresolved_signals == ()


def test_one_outcome_can_support_separate_context_compatible_study_groups():
    signal_specs = {
        "lpbf-variable": {
            "signal_type": "variable",
            "label": "laser power",
            "process_context": ["LPBF"],
        },
        "heat-variable": {
            "signal_type": "variable",
            "label": "heat-treatment temperature",
            "process_context": ["heat treatment"],
        },
        "outcome": {
            "signal_type": "outcome",
            "label": "microhardness",
        },
    }
    artifacts, tree = _artifacts(
        blocks=[
            _heading("study", "Study", 1),
            _paragraph("lpbf-variable", "lpbf-variable", 2, "Study"),
            _paragraph("heat-variable", "heat-variable", 3, "Study"),
            _paragraph("outcome", "outcome", 4, "Study"),
        ]
    )
    extractor = _BoundedSignalReconciliationExtractor(
        signal_specs,
        response_mode="separate_relationships",
    )

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert len(skim.studies) == 2
    assert {
        (study.process_context, study.relationships[0].varied_factors)
        for study in skim.studies
    } == {
        (("LPBF",), ("laser power",)),
        (("heat treatment",), ("heat-treatment temperature",)),
    }
    assert {
        relationship.outcome
        for study in skim.studies
        for relationship in study.relationships
    } == {"microhardness"}
    assert skim.unresolved_signals == ()


def test_signals_from_different_experiments_remain_unresolved():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("heat-variable", "HEAT_VARIABLE_SIGNAL", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph(
                "corrosion-outcome",
                "CORROSION_OUTCOME_SIGNAL",
                4,
                "Results",
            ),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        _WindowExtractor(reconciliation="unresolved"),
    )[0]

    assert skim.studies == ()
    assert {signal.label for signal in skim.unresolved_signals} == {
        "heat-treatment temperature",
        "corrosion potential",
    }
    assert all(signal.reason for signal in skim.unresolved_signals)


def test_reconciliation_keeps_broad_outcome_and_candidate_variable_unresolved():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("variable", "VARIABLE_SIGNAL", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph("outcome", "BROAD_OUTCOME_SIGNAL", 4, "Results"),
        ]
    )

    skim = _build_skims(artifacts, tree, _WindowExtractor())[0]

    assert skim.studies == ()
    assert {signal.label for signal in skim.unresolved_signals} == {
        "laser power",
        "tensile properties",
    }
    assert all(
        signal.reason == "outcome requires one specific measurable property"
        for signal in skim.unresolved_signals
    )


def test_conflicting_relationship_does_not_discard_valid_reconciliation():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph(
                "variables",
                "VARIABLE_SIGNAL HEAT_VARIABLE_SIGNAL",
                2,
                "Methods",
            ),
            _heading("results", "Results", 3),
            _paragraph("outcome", "OUTCOME_SIGNAL", 4, "Results"),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        _WindowExtractor(reconciliation="mixed_conflict"),
    )[0]

    assert len(skim.studies) == 1
    assert skim.studies[0].relationships[0].varied_factors == ("laser power",)
    assert skim.studies[0].relationships[0].outcome == "relative density"
    assert [signal.label for signal in skim.unresolved_signals] == [
        "heat-treatment temperature"
    ]
    assert "process_context" in (skim.unresolved_signals[0].reason or "")


def test_relationships_with_distinct_contexts_become_separate_studies():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph(
                "variables",
                "VARIABLE_SIGNAL HEAT_VARIABLE_SIGNAL",
                2,
                "Methods",
            ),
            _heading("results", "Results", 3),
            _paragraph(
                "outcomes",
                "OUTCOME_SIGNAL HEAT_OUTCOME_SIGNAL",
                4,
                "Results",
            ),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        _WindowExtractor(reconciliation="grouped_contexts"),
    )[0]

    assert len(skim.studies) == 2
    assert {
        (study.process_context, study.relationships[0].outcome)
        for study in skim.studies
    } == {
        (("LPBF",), "relative density"),
        (("heat treatment",), "microhardness"),
    }
    assert skim.unresolved_signals == ()


def test_invalid_reconciliation_ids_retain_all_signals_as_unresolved():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("variable", "VARIABLE_SIGNAL", 2, "Methods"),
            _heading("results", "Results", 3),
            _paragraph("outcome", "OUTCOME_SIGNAL", 4, "Results"),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        _WindowExtractor(reconciliation="invalid_id"),
    )[0]

    assert skim.studies == ()
    assert len(skim.unresolved_signals) == 2
    assert all(signal.reason == "paper signal reconciliation failed" for signal in skim.unresolved_signals)


def test_complete_candidate_survives_signal_reconciliation_failure():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph(
                "method-candidate",
                "METHOD_CANDIDATE VARIABLE_SIGNAL",
                2,
                "Methods",
            ),
            _heading("results", "Results", 3),
            _paragraph("outcome", "OUTCOME_SIGNAL", 4, "Results"),
        ]
    )

    skim = _build_skims(
        artifacts,
        tree,
        _WindowExtractor(reconciliation="raise"),
    )[0]

    assert len(skim.studies) == 1
    assert skim.studies[0].relationships[0].varied_factors == ("laser power",)
    assert [signal.label for signal in skim.unresolved_signals] == [
        "relative density"
    ]


def test_one_signal_role_is_retained_without_a_reconciliation_call():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("methods", "Methods", 1),
            _paragraph("variable", "VARIABLE_SIGNAL", 2, "Methods"),
        ]
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    assert extractor.reconciliation_payloads == []
    assert len(skim.unresolved_signals) == 1
    assert skim.unresolved_signals[0].reason == "no outcome signal was found in this paper"


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

    skim = service._consolidate_window_maps(
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

    skim = service._consolidate_window_maps(
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

    skim = service._consolidate_window_maps(
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
        return PaperResearchMapService._merge_studies(
            studies[0],
            studies[1],
            document_id="paper-1",
        )

    tensile = merge_for_experiment("tensile")
    hardness = merge_for_experiment("microhardness")

    assert tensile.relationships[0].relationship_id != hardness.relationships[0].relationship_id


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

    skim = service._consolidate_window_maps(
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

    skim = service._consolidate_window_maps(
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

    skim = service._consolidate_window_maps(
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

    skim = service._consolidate_window_maps(
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

    skim = service._consolidate_window_maps(
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

    skim = PaperResearchMapService()._consolidate_window_maps(
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
