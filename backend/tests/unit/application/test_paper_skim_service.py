from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.objectives.schemas import (
    StructuredPaperSignalReconciliation,
    StructuredPaperSkim,
)
from domain.core import PaperSkim, PaperStudy
from domain.source import SourceDocument, build_source_document_tree, source_documents_from_records


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

    def estimate_paper_skim_prompt_tokens(self, payload: dict[str, Any]) -> int:
        return 0

    def estimate_paper_signal_reconciliation_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        return 0

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
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
        return StructuredPaperSkim(
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

    def reconcile_paper_signals(
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

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
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
        return StructuredPaperSkim(
            doc_role="experimental",
            unresolved_signals=signals,
            evidence_density="high" if signals else "low",
            confidence=0.9,
        )

    def estimate_paper_signal_reconciliation_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        return 20_000 if len(payload["signals"]) > self.prompt_signal_limit else 1_000

    def reconcile_paper_signals(
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
) -> tuple[PaperSkim, ...]:
    return PaperSkimService().build_collection_paper_skims(
        "collection-test",
        documents=artifacts,
        profiles_by_document_id={},
        document_trees_by_document_id={artifacts[0].document_id: tree},
        extractor=extractor,
        progress_callback=progress.append if progress is not None else None,
    )


def _reconstruct_structured_value(
    source_units: list[dict[str, Any]],
    *path: str | int,
) -> Any:
    for unit in source_units:
        content = unit["content"]
        if not isinstance(content, dict) or "structured_path" in content:
            continue
        value: Any = content
        try:
            for part in path:
                value = value[part]
        except (KeyError, IndexError, TypeError):
            continue
        return value

    fragments = [
        content
        for unit in source_units
        if isinstance((content := unit["content"]), dict)
        and content.get("structured_path") == list(path)
    ]
    if not fragments:
        raise AssertionError(f"structured Source path was not transported: {path!r}")
    if "fragment" not in fragments[0]:
        return fragments[0]["value"]
    return "".join(
        str(fragment["fragment"])
        for fragment in sorted(
            fragments,
            key=lambda fragment: int(fragment["fragment_start"]),
        )
    )


def test_paper_skim_record_keeps_only_the_stable_source_link():
    skim = PaperSkim.from_mapping({"document_id": "paper-1"})

    record = skim.to_record()

    assert record["document_id"] == "paper-1"
    assert "title" not in record
    assert "source_filename" not in record


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


def test_six_source_refs_for_one_signal_do_not_split_a_valid_window():
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
    assert len(skim.unresolved_signals) == 1
    assert len(skim.unresolved_signals[0].source_refs) == 6


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
        def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
            parsed = super().extract_paper_skim(payload)
            return StructuredPaperSkim.model_construct(
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


def test_source_unit_count_bound_creates_more_windows_without_dropping_units():
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

    assert len(extractor.payloads) == 3
    assert all(len(payload["source_units"]) <= 12 for payload in extractor.payloads)
    assert len(skim.source_unit_coverage) == 25
    assert {item.source_ref for item in skim.source_unit_coverage} == {
        f"result-{position}" for position in range(25)
    }


def test_same_role_sections_are_screened_in_separate_contiguous_batches():
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

    assert [payload["section_paths"] for payload in extractor.payloads] == [
        ["Materials and Methods"],
        ["Validation Methods"],
    ]
    assert [
        [unit["source_ref"] for unit in payload["source_units"]]
        for payload in extractor.payloads
    ] == [["method-a"], ["method-b"]]


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

        def estimate_paper_skim_prompt_tokens(self, payload: dict[str, Any]) -> int:
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
        def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
            if len(payload["source_units"]) > 1:
                self.payloads.append(payload)
                return StructuredPaperSkim(output_saturated=True)
            return super().extract_paper_skim(payload)

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


def test_late_results_content_is_screened_after_the_first_four_thousand_characters():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("abstract", "Abstract", 1),
            _paragraph("lead", "A" * 4000, 2, "Abstract"),
            _heading("results", "Results", 3),
            _paragraph(
                "late-result",
                "RESULT_CANDIDATE appears only in the late results section.",
                4,
                "Results",
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
        ("scan speed",)
    ]
    assert any(
        payload["window_role"] == "results"
        and any(
            "RESULT_CANDIDATE" in str(unit["content"])
            for unit in payload["source_units"]
        )
        for payload in extractor.payloads
    )


def test_one_long_source_paragraph_is_split_into_bounded_windows_without_text_loss():
    source_text = "B" * 8500
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("long-result", source_text, 2, "Results"),
        ]
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    text_windows = [
        "".join(
            str(unit["content"])
            for unit in payload["source_units"]
            if unit["source_kind"] == "block"
        )
        for payload in extractor.payloads
    ]
    assert len(text_windows) == 3
    assert all(len(text) <= 4000 for text in text_windows)
    assert "".join(text_windows) == source_text


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

    text_windows = [
        "".join(
            str(unit["content"])
            for unit in payload["source_units"]
            if unit["source_kind"] == "block"
        )
        for payload in extractor.payloads
    ]
    assert text_windows[0].endswith(". ")
    assert all(len(text) <= 4000 for text in text_windows)
    assert "".join(text_windows) == source_text


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


def test_table_rows_are_screened_without_a_global_row_limit():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result", "Results summary.", 2, "Results"),
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

    row_records = [
        unit["content"]
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "table_row"
        and isinstance(unit["content"], dict)
        and "row_id" in unit["content"]
    ]
    assert [record["row_id"] for record in row_records] == [
        f"row-{position}" for position in range(1, 31)
    ]


def test_table_row_relationship_preserves_its_stable_row_locator():
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result", "Results summary.", 2, "Results"),
        ],
        tables=[
            {
                "table_id": "table-results",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "Process conditions and measured porosity",
                "heading_path": "Results",
                "column_headers": ["scan speed", "porosity"],
                "table_matrix": [],
            }
        ],
        table_rows=[
            {
                "row_id": "row-result-7",
                "document_id": "paper-1",
                "table_id": "table-results",
                "row_index": 7,
                "row_text": "RESULT_CANDIDATE scan speed=900 | porosity=0.2",
                "heading_path": "Results",
            }
        ],
    )
    extractor = _WindowExtractor()

    skim = _build_skims(artifacts, tree, extractor)[0]

    row_units = [
        unit
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if isinstance(unit.get("content"), dict)
        and unit["content"].get("row_id") == "row-result-7"
    ]
    assert [
        (unit["source_kind"], unit["source_ref"]) for unit in row_units
    ] == [("table_row", "row-result-7")]
    assert row_units[0]["content"]["table_context"]["caption_text"] == (
        "Process conditions and measured porosity"
    )
    assert row_units[0]["content"]["table_context"]["column_headers"] == [
        "scan speed",
        "porosity",
    ]
    assert row_units[0]["content"]["table_context"]["heading_path"] == "Results"
    assert [
        source_ref.to_record()
        for source_ref in skim.studies[0].relationships[0].source_refs
    ] == [{"source_kind": "table_row", "source_ref": "row-result-7"}]


def test_table_metadata_is_lossless_across_bounded_source_chunks():
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
    assert _reconstruct_structured_value(source_units, "caption_text") == caption
    assert [
        _reconstruct_structured_value(source_units, "column_headers", position)
        for position in range(len(headers))
    ] == headers
    assert all(
        len(json.dumps(unit["content"], ensure_ascii=False, separators=(",", ":")))
        <= 4000
        for unit in source_units
    )
    assert {
        (unit["source_kind"], unit["source_ref"]) for unit in source_units
    } == {("table", "table-long-metadata")}


def test_figure_caption_is_lossless_across_bounded_source_chunks():
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
    assert _reconstruct_structured_value(source_units, "caption_text") == caption
    assert all(
        len(json.dumps(unit["content"], ensure_ascii=False, separators=(",", ":")))
        <= 4000
        for unit in source_units
    )
    assert {
        (unit["source_kind"], unit["source_ref"]) for unit in source_units
    } == {("figure", "figure-long-caption")}
    assert [
        ref.to_record()
        for ref in skim.studies[0].relationships[0].source_refs
    ] == [{"source_kind": "figure", "source_ref": "figure-long-caption"}]


def test_oversized_structured_table_row_is_split_without_text_loss():
    row_text = f"sample=A | {'reported result ' * 700}"
    artifacts, tree = _artifacts(
        blocks=[
            _heading("results", "Results", 1),
            _paragraph("result", "Results summary.", 2, "Results"),
        ],
        tables=[
            {
                "table_id": "table-long-row",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "Long result row",
                "heading_path": "Results",
                "column_headers": ["sample", "reported result"],
                "table_matrix": [],
            }
        ],
        table_rows=[
            {
                "row_id": "row-long",
                "document_id": "paper-1",
                "table_id": "table-long-row",
                "row_index": 1,
                "row_text": row_text,
                "heading_path": "Results",
            }
        ],
    )
    extractor = _WindowExtractor()

    _build_skims(artifacts, tree, extractor)

    source_units = [
        unit
        for payload in extractor.payloads
        for unit in payload["source_units"]
        if unit["source_kind"] == "table_row"
        and unit["source_ref"] == "row-long"
        and isinstance(unit["content"], dict)
        and unit["content"].get("structured_path") == ["row_text"]
    ]
    assert _reconstruct_structured_value(source_units, "row_text") == row_text
    assert all(
        len(json.dumps(unit["content"], ensure_ascii=False, separators=(",", ":")))
        <= 4000
        for unit in source_units
    )
    assert {
        (unit["source_kind"], unit["source_ref"]) for unit in source_units
    } == {("table_row", "row-long")}
    assert all(
        unit["content"]["table_context"]["caption_text"] == "Long result row"
        for unit in source_units
    )
    assert all(
        unit["content"]["table_context"]["column_headers"]
        == ["sample", "reported result"]
        for unit in source_units
    )
    assert all(
        unit["content"]["table_context"]["heading_path"] == "Results"
        for unit in source_units
    )


def test_each_source_text_and_caption_is_assigned_once_and_references_are_excluded():
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
    assert all_text.count("METHOD_SOURCE") == 1
    assert all_text.count("RESULT_SOURCE") == 1
    assert "REFERENCE_SOURCE" not in all_text
    assert all_table_captions == ["TABLE_SOURCE"]
    assert all_figure_captions == ["FIGURE_SOURCE"]


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
        signal.reason == "no experiment-evidence bridge was found in this paper"
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
    assert len(skim.unresolved_signals) == 2


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


def test_merged_relationship_identity_keeps_its_final_study_boundary():
    def merge_for_test_context(test_context: str) -> PaperStudy:
        studies = tuple(
            PaperStudy.from_mapping(
                {
                    "document_id": "paper-1",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": f"{test_context} experiment",
                    "test_context": [test_context],
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
        return PaperSkimService._merge_studies(
            studies[0],
            studies[1],
            document_id="paper-1",
        )

    tensile = merge_for_test_context("ASTM E8 tensile test")
    hardness = merge_for_test_context("Vickers microhardness test")

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
    service = PaperSkimService()
    window_skims = [
        PaperSkim.from_mapping(
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
        PaperSkim.from_mapping(
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

    skim = service._consolidate_window_skims(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_same_axes_with_partially_overlapping_material_scopes_are_not_merged():
    service = PaperSkimService()
    window_skims = [
        PaperSkim.from_mapping(
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
        PaperSkim.from_mapping(
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

    skim = service._consolidate_window_skims(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_same_axes_and_context_without_shared_study_identity_are_not_merged():
    service = PaperSkimService()
    window_skims = [
        PaperSkim.from_mapping(
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
        PaperSkim.from_mapping(
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

    skim = service._consolidate_window_skims(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert len(skim.studies) == 2


def test_consolidation_keeps_only_the_first_two_unique_paper_warnings():
    service = PaperSkimService()
    window_skims = [
        PaperSkim.from_mapping(
            {
                "document_id": "paper-1",
                "warnings": [f"warning-{position}"],
            }
        )
        for position in range(4)
    ]

    skim = service._consolidate_window_skims(
        "paper-1",
        window_skims,
        profile=None,
    )

    assert skim.warnings == ("warning-0", "warning-1")


def test_document_profile_owns_the_paper_role_across_windows():
    service = PaperSkimService()
    window_skims = [
        PaperSkim.from_mapping({"document_id": "paper-1", "doc_role": "review"}),
        PaperSkim.from_mapping(
            {"document_id": "paper-1", "doc_role": "experimental"}
        ),
    ]

    skim = service._consolidate_window_skims(
        "paper-1",
        window_skims,
        profile=SimpleNamespace(doc_type="experimental"),
    )

    assert skim.doc_role == "experimental"


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

    assert [item["current"] for item in progress] == [1, 1, 1]
    assert [item["total"] for item in progress] == [1, 1, 1]
    assert [item["unit"] for item in progress] == ["documents"] * 3
    assert [item["active_window_position"] for item in progress] == [1, 2, 3]
    assert [item["active_window_count"] for item in progress] == [3, 3, 3]
    assert [item["active_window_role"] for item in progress] == [
        "overview",
        "methods",
        "results",
    ]
