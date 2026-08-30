from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from application.core.objectives.discovery.signal_reconciliation import (
    StructuredPaperSignalReconciliation,
)
from application.core.objectives.discovery.study_window import (
    StructuredPaperResearchMap,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from domain.core import PaperResearchMap
from domain.source import build_source_document_tree, source_documents_from_records


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "paper_map_policy"
    / "tc4_gold_baseline.json"
)


def _tc4_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _study(*, outcome: str, source_unit_ids: list[str]) -> dict[str, Any]:
    return {
        "experiment_label": "laser-energy multi-axis experiment",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": ["Ti-6Al-4V"],
        "process_context": ["laser powder bed fusion"],
        "relationships": [
            {
                "varied_factors": ["laser energy"],
                "outcome": outcome,
                "source_unit_ids": source_unit_ids,
                "confidence": 0.9,
            }
        ],
        "confidence": 0.9,
    }


class _MultiAxisExtractor:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.reconciliation_payloads: list[dict[str, Any]] = []

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        return 0

    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        self.payloads.append(payload)
        units = payload.get("source_units") or ()
        text = " ".join(str(unit.get("content") or "") for unit in units)

        def source_ids(marker: str) -> list[str]:
            return [
                str(unit["source_unit_id"])
                for unit in units
                if marker in str(unit.get("content") or "")
            ]

        studies: list[dict[str, Any]] = []
        for marker, outcome in (
            ("AXIS_POROSITY", "porosity"),
            ("AXIS_MICROSTRUCTURE", "grain morphology"),
            ("AXIS_TENSILE", "tensile strength"),
            ("AXIS_ELONGATION", "elongation"),
            ("AXIS_DUCTILITY", "elongation"),
        ):
            if marker in text:
                studies.append(
                    _study(outcome=outcome, source_unit_ids=source_ids(marker))
                )

        signals: list[dict[str, Any]] = []
        if "VARIABLE_SIGNAL" in text:
            signals.append(
                {
                    "signal_type": "variable",
                    "label": "laser energy",
                    "source_unit_ids": source_ids("VARIABLE_SIGNAL"),
                    "confidence": 0.9,
                }
            )
        for marker, outcome in (
            ("MICRO_SIGNAL", "grain morphology"),
            ("TENSILE_SIGNAL", "tensile strength"),
            ("BROAD_MECHANICAL_SIGNAL", "mechanical properties"),
            ("DUCTILITY_SIGNAL", "elongation"),
        ):
            if marker in text:
                signals.append(
                    {
                        "signal_type": "outcome",
                        "label": outcome,
                        "source_unit_ids": source_ids(marker),
                        "confidence": 0.9,
                    }
                )

        return StructuredPaperResearchMap(
            doc_role="experimental",
            studies=studies,
            unresolved_signals=signals,
            evidence_density="high",
            confidence=0.9,
        )

    def reconcile(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperSignalReconciliation:
        self.reconciliation_payloads.append(payload)
        signals = payload["signals"]
        variable = next(
            signal for signal in signals if signal["signal_type"] == "variable"
        )
        return StructuredPaperSignalReconciliation(
            studies=[
                {
                    "relationships": [
                        {
                            "signal_ids": [variable["signal_id"], signal["signal_id"]],
                            "confidence": 0.9,
                        }
                        for signal in signals
                        if signal["signal_type"] == "outcome"
                    ]
                }
            ]
        )


class _BoundedExpansionExtractor(_MultiAxisExtractor):
    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        parsed = super().extract(payload)
        result_units = [
            unit
            for unit in payload.get("source_units") or ()
            if str(unit.get("source_ref") or "").startswith("results-")
        ]
        if not result_units:
            return parsed
        dynamic_studies = [
            _study(
                outcome=f"dynamic-{unit['source_ref']}",
                source_unit_ids=[str(unit["source_unit_id"])],
            )
            for unit in result_units
        ]
        return StructuredPaperResearchMap(
            doc_role=parsed.doc_role,
            studies=[*parsed.studies, *dynamic_studies],
            unresolved_signals=parsed.unresolved_signals,
            evidence_density=parsed.evidence_density,
            confidence=parsed.confidence,
        )


def _artifacts_for_scenario(
    scenario: dict[str, Any],
) -> tuple[Any, Any]:
    blocks: list[dict[str, Any]] = []
    order = 1
    for unit in scenario["source_units"]:
        source_ref = str(unit["source_ref"])
        section = str(unit["section"])
        blocks.append(
            {
                "block_id": f"{source_ref}-heading",
                "document_id": "tc4-baseline-paper",
                "block_type": "heading",
                "text": section,
                "block_order": order,
                "heading_path": section,
                "heading_level": 1,
            }
        )
        order += 1
        blocks.append(
            {
                "block_id": source_ref,
                "document_id": "tc4-baseline-paper",
                "block_type": "paragraph",
                "text": str(unit["text"]),
                "block_order": order,
                "heading_path": section,
            }
        )
        order += 1

    artifacts = source_documents_from_records(
        documents=[
            {
                "id": "tc4-baseline-paper",
                "document_order": 1,
                "title": "TC4 multi-axis baseline paper",
                "text": "",
            }
        ],
        blocks=blocks,
        tables=[],
        table_rows=[],
        figures=[],
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


def test_tc4_multi_axis_map_reads_results_after_a_visible_relationship():
    scenario = next(
        item
        for item in _tc4_fixture()["scenarios"]
        if item["id"] == "multi_axis_experiment"
    )
    artifacts, tree = _artifacts_for_scenario(scenario)
    extractor = _MultiAxisExtractor()

    paper_map = PaperResearchMapService().build_document_paper_map(
        "collection-test",
        document=artifacts[0],
        profile=None,
        document_tree=tree,
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
    )

    outcomes = {
        relationship.outcome
        for study in paper_map.studies
        for relationship in study.relationships
    }
    mapped_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload.get("source_units") or ()
    }

    assert {"porosity", "grain morphology", "tensile strength"} <= outcomes
    assert {"results-microstructure", "results-tensile"} <= mapped_refs
    assert len(extractor.payloads) > 1
    assert paper_map.map_status == "sufficient"


def test_tc4_paper_map_caps_expansion_sources_and_keeps_round_ids_distinct():
    scenario = {
        "id": "many_expansion_sources",
        "source_units": [
            {
                "source_ref": "abstract",
                "section": "Abstract",
                "text": "AXIS_POROSITY VARIABLE_SIGNAL MICRO_SIGNAL TENSILE_SIGNAL",
            },
            *[
                {
                    "source_ref": f"results-{position:02d}",
                    "section": "Results",
                    "text": f"AXIS_DYNAMIC_{position:02d}",
                }
                for position in range(32)
            ],
        ],
    }
    artifacts, tree = _artifacts_for_scenario(scenario)
    extractor = _BoundedExpansionExtractor()

    PaperResearchMapService().build_document_paper_map(
        "collection-test",
        document=artifacts[0],
        profile=None,
        document_tree=tree,
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
    )

    expansion_rounds = {
        int(payload["reading_round"])
        for payload in extractor.payloads
        if "reading_round" in payload
    }
    expansion_source_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        if "reading_round" in payload
        for unit in payload.get("source_units") or ()
    }
    assert expansion_rounds == {2, 3, 4}
    assert len(expansion_source_refs) == 24
    assert all(
        payload["window_id"].startswith(f"round-{payload['reading_round']}.")
        for payload in extractor.payloads
        if "reading_round" in payload
    )


def test_tc4_expansion_prioritizes_specific_metrics_for_a_broad_outcome():
    scenario = {
        "id": "late_specific_metric",
        "source_units": [
            {
                "source_ref": "abstract",
                "section": "Abstract",
                "text": "VARIABLE_SIGNAL BROAD_MECHANICAL_SIGNAL",
            },
            *[
                {
                    "source_ref": f"results-{position:02d}",
                    "section": "Results",
                    "text": (
                        "ductility AXIS_DUCTILITY"
                        if position == 31
                        else f"OTHER_RESULT_{position:02d}"
                    ),
                }
                for position in range(32)
            ],
        ],
    }
    artifacts, tree = _artifacts_for_scenario(scenario)
    extractor = _MultiAxisExtractor()

    paper_map = PaperResearchMapService().build_document_paper_map(
        "collection-test",
        document=artifacts[0],
        profile=None,
        document_tree=tree,
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
    )

    mapped_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload.get("source_units") or ()
    }
    outcomes = {
        relationship.outcome
        for study in paper_map.studies
        for relationship in study.relationships
    }
    assert "results-31" in mapped_refs
    assert "elongation" in outcomes


def test_tc4_concrete_relationship_resolves_same_source_broad_signals():
    scenario = {
        "id": "same_source_specific_metric",
        "source_units": [
            {
                "source_ref": "abstract",
                "section": "Abstract",
                "text": (
                    "VARIABLE_SIGNAL BROAD_MECHANICAL_SIGNAL "
                    "AXIS_DUCTILITY"
                ),
            }
        ],
    }
    artifacts, tree = _artifacts_for_scenario(scenario)
    extractor = _MultiAxisExtractor()

    paper_map = PaperResearchMapService().build_document_paper_map(
        "collection-test",
        document=artifacts[0],
        profile=None,
        document_tree=tree,
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
    )

    assert not any(
        signal.signal_type == "outcome"
        for signal in paper_map.unresolved_signals
    )
    assert paper_map.map_status == "sufficient"


def test_tc4_concrete_result_resolves_cross_source_broad_scope_and_stops_reading():
    scenario = {
        "id": "cross_source_specific_metric",
        "source_units": [
            {
                "source_ref": "abstract",
                "section": "Abstract",
                "text": "VARIABLE_SIGNAL BROAD_MECHANICAL_SIGNAL",
            },
            *[
                {
                    "source_ref": f"results-{position:02d}",
                    "section": "Results",
                    "text": (
                        "ductility AXIS_DUCTILITY"
                        if position == 31
                        else f"OTHER_RESULT_{position:02d}"
                    ),
                }
                for position in range(32)
            ],
        ],
    }
    artifacts, tree = _artifacts_for_scenario(scenario)
    extractor = _MultiAxisExtractor()

    paper_map = PaperResearchMapService().build_document_paper_map(
        "collection-test",
        document=artifacts[0],
        profile=None,
        document_tree=tree,
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
    )

    expansion_source_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        if "reading_round" in payload
        for unit in payload.get("source_units") or ()
    }
    assert "results-31" in expansion_source_refs
    assert len(expansion_source_refs) <= 8
    assert not any(
        signal.signal_type == "outcome"
        for signal in paper_map.unresolved_signals
    )
    assert paper_map.map_status == "sufficient"


def test_tc4_specific_unlinked_signal_remains_visible_without_blocking_discovery():
    paper_map = PaperResearchMap.from_mapping(
        {
            "document_id": "tc4-paper",
            "doc_role": "experimental",
            "studies": [
                {
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "varied_factors": ["laser power"],
                            "outcome": "porosity",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "results"}
                            ],
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            "unresolved_signals": [
                {
                    "signal_type": "outcome",
                    "label": "residual stress",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "abstract"}
                    ],
                    "confidence": 0.8,
                }
            ],
            "evidence_density": "medium",
            "confidence": 0.8,
            "warnings": [],
        }
    )

    filtered = PaperResearchMapService()._drop_signals_resolved_by_relationships(
        paper_map
    )
    assessment = PaperResearchMapService()._assess_paper_map(
        filtered,
        signals=filtered.unresolved_signals,
        final=True,
    )

    assert [signal.label for signal in filtered.unresolved_signals] == [
        "residual stress"
    ]
    assert assessment.status == "sufficient"


def test_tc4_broad_family_signal_matches_expanded_specific_relationship():
    paper_map = PaperResearchMap.from_mapping(
        {
            "document_id": "tc4-paper",
            "doc_role": "experimental",
            "studies": [
                {
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "varied_factors": ["laser power"],
                            "outcome": "yield strength",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "results"}
                            ],
                        }
                    ],
                }
            ],
            "unresolved_signals": [
                {
                    "signal_type": "outcome",
                    "label": "mechanical property anisotropy",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "abstract"}
                    ],
                    "confidence": 0.8,
                }
            ],
            "evidence_density": "medium",
            "confidence": 0.8,
            "warnings": [],
        }
    )

    filtered = PaperResearchMapService()._drop_signals_resolved_by_relationships(
        paper_map
    )
    assert filtered.unresolved_signals == ()


def test_tc4_microstructure_family_signal_matches_observed_martensite_axis():
    paper_map = PaperResearchMap.from_mapping(
        {
            "document_id": "tc4-paper",
            "doc_role": "experimental",
            "studies": [
                {
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "varied_factors": ["heat treatment"],
                            "outcome": "martensite lamellae thickness",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "results"}
                            ],
                        }
                    ],
                }
            ],
            "unresolved_signals": [
                {
                    "signal_type": "outcome",
                    "label": "microstructural anisotropy",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "abstract"}
                    ],
                    "confidence": 0.8,
                }
            ],
            "evidence_density": "medium",
            "confidence": 0.8,
            "warnings": [],
        }
    )

    filtered = PaperResearchMapService()._drop_signals_resolved_by_relationships(
        paper_map
    )
    assert filtered.unresolved_signals == ()


def test_tc4_later_expansion_reads_methods_after_finding_a_specific_outcome():
    scenario = {
        "id": "outcome_then_method_context",
        "source_units": [
            {
                "source_ref": "abstract",
                "section": "Abstract",
                "text": "BROAD_MECHANICAL_SIGNAL",
            },
            {
                "source_ref": "methods-treatment",
                "section": "Methods",
                "text": "VARIABLE_SIGNAL post-treatment context",
            },
            *[
                {
                    "source_ref": f"results-{position:02d}",
                    "section": "Results",
                    "text": (
                        "ductility DUCTILITY_SIGNAL"
                        if position == 31
                        else f"OTHER_RESULT_{position:02d}"
                    ),
                }
                for position in range(32)
            ],
        ],
    }
    artifacts, tree = _artifacts_for_scenario(scenario)
    extractor = _MultiAxisExtractor()

    PaperResearchMapService().build_document_paper_map(
        "collection-test",
        document=artifacts[0],
        profile=None,
        document_tree=tree,
        paper_map_extractor=extractor,
        signal_reconciler=extractor,
    )

    mapped_refs = {
        str(unit["source_ref"])
        for payload in extractor.payloads
        for unit in payload.get("source_units") or ()
    }
    assert "results-31" in mapped_refs
    assert "methods-treatment" in mapped_refs


def test_tc4_background_relationship_is_not_unclear_ownership():
    paper_map = PaperResearchMap.from_mapping(
        {
            "document_id": "tc4-paper",
            "doc_role": "experimental",
            "studies": [
                {
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "varied_factors": ["laser power"],
                            "outcome": "yield strength",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "abstract"}
                            ],
                            "confidence": 0.9,
                        }
                    ],
                },
                {
                    "claim_scope": "background",
                    "relationships": [
                        {
                            "varied_factors": ["energy density"],
                            "outcome": "porosity",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "introduction"}
                            ],
                            "confidence": 0.8,
                        }
                    ],
                },
            ],
                "unresolved_signals": [
                    {
                        "signal_type": "outcome",
                        "label": "microstructure",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "abstract"}
                    ],
                    "confidence": 0.8,
                }
            ],
            "evidence_density": "medium",
            "confidence": 0.8,
            "warnings": [],
        }
    )

    assessment = PaperResearchMapService()._assess_paper_map(
        paper_map,
        signals=(),
        final=True,
    )

    assert "outcome_too_broad" in assessment.limitations
    assert "unclear_ownership" not in assessment.limitations
