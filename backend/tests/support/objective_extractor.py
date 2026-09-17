from __future__ import annotations

from typing import Any

from application.core.document_profiles.extraction import DocumentProfileModelOutput
from application.core.objectives.analysis.finding_synthesis import (
    StructuredFindingSynthesis,
    StructuredFindingSynthesisItem,
)
from application.core.objectives.analysis.source_extraction import (
    EvidenceExtractionModelOutput,
    EvidenceExtractionsModelOutput,
)
from application.core.objectives.analysis.source_screening import (
    PaperFrameBatchResult,
)
from application.core.objectives.discovery.axis_equivalence import (
    AxisCanonicalizationPlanModelOutput,
)
from application.core.objectives.discovery.paper_understanding.paper_map_results import (
    StructuredPaperResearchMap,
)


def source_unit_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    source_unit_ids: list[str] = []
    for unit in payload.get("source_units") or ():
        if not isinstance(unit, dict):
            continue
        source_unit_id = str(unit.get("source_unit_id") or "").strip()
        if source_unit_id and source_unit_id not in source_unit_ids:
            source_unit_ids.append(source_unit_id)
    return source_unit_ids[:12]


def studies_with_source_units(
    payload: dict[str, Any],
    studies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_unit_ids = source_unit_ids_from_payload(payload)
    if not source_unit_ids:
        return []
    return [
        {
            **study,
            "relationships": [
                {**relationship, "source_unit_ids": source_unit_ids}
                for relationship in study.get("relationships") or ()
            ],
        }
        for study in studies
    ]


def paper_research_map_scope_outputs(
    payload: dict[str, Any],
    studies: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {"studies": studies_with_source_units(payload, studies)}


class FakeObjectiveExtractor:
    def __init__(self) -> None:
        self.skim_payloads: list[dict[str, Any]] = []
        self.canonicalization_payloads: list[dict[str, Any]] = []
        self.frame_payloads: list[dict[str, Any]] = []
        self.unit_payloads: list[dict[str, Any]] = []
        self.finding_payloads: list[dict[str, Any]] = []

    def estimate_prompt_tokens(
        self,
        payload: dict[str, Any] | None = None,
        **_: Any,
    ) -> int:
        return 0

    def extract_document_profile(
        self,
        payload: dict[str, Any],
    ) -> DocumentProfileModelOutput:
        title = str(payload.get("title") or "")
        return DocumentProfileModelOutput(
            doc_type="review" if "Review" in title else "experimental",
            profile_warnings=[],
            confidence=0.9,
        )

    def extract(self, payload: dict[str, Any], *, before_request=None) -> StructuredPaperResearchMap:
        if before_request is not None:
            before_request()
        self.skim_payloads.append(payload)
        title = str(payload.get("title") or "")
        if "Review" in title:
            return StructuredPaperResearchMap(
                doc_role="review",
                studies=[],
                unresolved_signals=[],
                evidence_density="low",
                confidence=0.72,
                warnings=[],
            )
        studies = studies_with_source_units(
            payload,
            [
                    {
                        "experiment_label": "LPBF heat-treatment study",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": ["316L stainless steel"],
                        "process_context": ["LPBF", "heat treatment"],
                        "relationships": [
                            {
                                "varied_factors": ["heat treatment temperature"],
                                "outcome": "corrosion current density",
                                "confidence": 0.91,
                            }
                        ],
                        "confidence": 0.91,
                    }
            ],
        )
        return StructuredPaperResearchMap(
            doc_role="experimental",
            studies=studies,
            unresolved_signals=[],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )


    def classify(
        self,
        payload: dict[str, Any],
    ) -> AxisCanonicalizationPlanModelOutput:
        self.canonicalization_payloads.append(payload)
        return AxisCanonicalizationPlanModelOutput(
            decisions=[
                {
                    "pair_id": pair["pair_id"],
                    "equivalent": True,
                    "same_research_topic": True,
                }
                for pair in payload.get("axis_pairs", ())
            ]
        )

    def screen_batch(
        self,
        payload: dict[str, Any],
    ) -> PaperFrameBatchResult:
        self.frame_payloads.append(payload)
        objective = payload["objective"]
        document = payload["document"]
        document_id = str(document.get("document_id") or "")
        source_units = payload["source_units"]
        source_unit_ids = [
            str(unit["source_unit_id"])
            for unit in source_units
            if unit.get("source_unit_id")
        ]
        if document_id in objective.get("excluded_document_ids", ()):
            return PaperFrameBatchResult(
                relevance="irrelevant",
                paper_role="review",
                screening_note="Excluded by objective discovery.",
                material_match=[],
                changed_variables=[],
                measured_property_scope=[],
                test_environment_scope=[],
                relevant_source_unit_ids=[],
                excluded_source_unit_ids=source_unit_ids,
            )
        relevant_source_unit_ids = self._matching_frame_source_unit_ids(
            source_units,
            axes=(
                *objective.get("variables", ()),
                *objective.get("outcomes", ()),
            ),
        )
        relevant_source_unit_ids.extend(
            source_unit_id
            for source_unit_id, unit in zip(source_unit_ids, source_units, strict=True)
            if unit.get("source_kind") == "section"
            and source_unit_id not in relevant_source_unit_ids
        )
        return PaperFrameBatchResult(
            relevance="high",
            paper_role="primary_experiment",
            screening_note="Paper directly supports the active research objective.",
            material_match=list(objective.get("material_scope") or []),
            changed_variables=list(objective.get("variables") or []),
            measured_property_scope=list(objective.get("outcomes") or []),
            test_environment_scope=[],
            relevant_source_unit_ids=relevant_source_unit_ids,
            excluded_source_unit_ids=[
                source_unit_id
                for source_unit_id in source_unit_ids
                if source_unit_id not in relevant_source_unit_ids
            ],
        )

    def _matching_frame_source_unit_ids(
        self,
        source_units: list[dict[str, Any]],
        *,
        axes: tuple[str, ...],
    ) -> list[str]:
        source_unit_ids: list[str] = []
        for unit in source_units:
            if unit.get("source_kind") != "table":
                continue
            text = " ".join(
                str(value or "")
                for value in (
                    unit.get("caption_text"),
                    unit.get("heading_path"),
                    " ".join(unit.get("column_headers") or []),
                )
            ).lower()
            if any(str(axis or "").lower() in text for axis in axes):
                source_unit_ids.append(str(unit["source_unit_id"]))
        return source_unit_ids

    def extract_source(
        self,
        payload: dict[str, Any],
    ) -> EvidenceExtractionsModelOutput:
        self.unit_payloads.append(payload)
        route = payload["evidence_route"]
        source = payload["source"]
        if route["source_kind"] == "table":
            return EvidenceExtractionsModelOutput(
                extractions=[
                    EvidenceExtractionModelOutput(
                        evidence_role="direct_result",
                        changed_variables=[
                            {
                                "name": "heat treatment",
                                "baseline_value": "as-built",
                                "target_value": "heat-treated",
                            }
                        ],
                        comparison={
                            "baseline_label": "as-built",
                            "target_label": "heat-treated",
                            "axis_names": ["heat treatment"],
                            "comparable": True,
                            "incomparability_reasons": [],
                        },
                        reported_result={
                            "outcome": "corrosion current",
                            "value": 1.2,
                            "unit": "uA/cm2",
                            "direction": "decrease",
                            "result_text": (
                                "Corrosion current decreased from 1.2 to "
                                "0.4 uA/cm2 after heat treatment."
                            ),
                        },
                        attribution_scope="isolated_effect",
                        scientific_context={
                            "material": [
                                {
                                    "name": "family",
                                    "value": "316L stainless steel",
                                }
                            ],
                            "process": [{"name": "process", "value": "LPBF"}],
                            "test": [
                                {"name": "method", "value": "corrosion test"}
                            ],
                        },
                        resolution_status="resolved",
                        confidence=0.86,
                    ),
                ]
            )
        if source.get("text"):
            return EvidenceExtractionsModelOutput(
                extractions=[
                    EvidenceExtractionModelOutput(
                        evidence_role="condition_context",
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "material": [
                                {
                                    "name": "family",
                                    "value": "316L stainless steel",
                                }
                            ],
                            "sample": [
                                {
                                    "name": "comparison",
                                    "value": "before and after heat treatment",
                                }
                            ],
                            "process": [
                                {"name": "process", "value": "LPBF"},
                                {
                                    "name": "post treatment",
                                    "value": "heat treatment",
                                },
                            ],
                        },
                        resolution_status="partial",
                        confidence=0.74,
                    )
                ]
            )
        return EvidenceExtractionsModelOutput()

    def judge_result_set(
        self,
        payload: dict[str, Any],
    ) -> StructuredFindingSynthesis:
        self.finding_payloads.append(payload)
        result_set = payload.get("result_set", {})
        factors = [
            str(value).strip()
            for value in result_set.get("factors", [])
            if str(value).strip()
        ]
        outcome = str(result_set.get("outcome") or "").strip()
        result_evidence = result_set.get("result_evidence", [])
        if not factors or not outcome or not result_evidence:
            return StructuredFindingSynthesis()
        return StructuredFindingSynthesis(
            findings=[
                StructuredFindingSynthesisItem(
                    assertion_strength="associative",
                    context_evidence_ids=[],
                    mechanisms=[],
                )
            ]
        )


__all__ = ["FakeObjectiveExtractor"]
