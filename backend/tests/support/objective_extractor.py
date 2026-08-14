from __future__ import annotations

from typing import Any

from application.core.document_profiles.schemas import StructuredDocumentProfile
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
    StructuredEvidenceSelection,
    StructuredEvidenceSelections,
    StructuredFindingSynthesis,
    StructuredFindingSynthesisItem,
    StructuredPaperContributionDraft,
    StructuredPaperSkim,
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


def paper_skim_study_outputs(
    payload: dict[str, Any],
    studies: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {"studies": studies_with_source_units(payload, studies)}


class FakeObjectiveExtractor:
    def __init__(self) -> None:
        self.skim_payloads: list[dict[str, Any]] = []
        self.canonicalization_payloads: list[dict[str, Any]] = []
        self.frame_payloads: list[dict[str, Any]] = []
        self.route_payloads: list[dict[str, Any]] = []
        self.unit_payloads: list[dict[str, Any]] = []
        self.finding_payloads: list[dict[str, Any]] = []

    def estimate_paper_skim_prompt_tokens(self, payload: dict[str, Any]) -> int:
        return 0

    def estimate_paper_signal_reconciliation_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        return 0

    def extract_document_profile(
        self,
        payload: dict[str, Any],
    ) -> StructuredDocumentProfile:
        title = str(payload.get("title") or "")
        return StructuredDocumentProfile(
            doc_type="review" if "Review" in title else "experimental",
            parsing_warnings=[],
            confidence=0.9,
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        title = str(payload.get("title") or "")
        if "Review" in title:
            return StructuredPaperSkim(
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
                                "outcome": "corrosion resistance",
                                "confidence": 0.91,
                            }
                        ],
                        "confidence": 0.91,
                    }
            ],
        )
        return StructuredPaperSkim(
            doc_role="experimental",
            studies=studies,
            unresolved_signals=[],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            decisions=[
                {"pair_id": pair["pair_id"], "equivalent": True}
                for pair in payload.get("axis_pairs", ())
            ]
        )

    def assess_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperContributionDraft:
        self.frame_payloads.append(payload)
        objective = payload["objective"]
        document = payload["document"]
        paper_skim = payload["paper_skim"]
        document_id = str(document.get("document_id") or "")
        table_summaries = payload["table_summaries"]
        if document_id in objective.get("excluded_document_ids", ()):
            return StructuredPaperContributionDraft(
                relevance="irrelevant",
                paper_role="review",
                background="Excluded by objective discovery.",
                material_match=[],
                changed_variables=[],
                measured_property_scope=[],
                test_environment_scope=[],
                relevant_sections=[],
                relevant_tables=[],
                excluded_tables=[
                    table["table_id"]
                    for table in table_summaries
                    if table.get("table_id")
                ],
            )
        relevant_tables = self._matching_frame_table_ids(
            table_summaries,
            axes=(
                *objective.get("variables", ()),
                *objective.get("outcomes", ()),
            ),
        )
        section_labels = [
            item["section_label"]
            for item in payload["section_snippets"]
            if item.get("section_label")
        ]
        return StructuredPaperContributionDraft(
            relevance="high",
            paper_role="primary_experiment",
            background="Paper directly supports the active research objective.",
            material_match=list(objective.get("material_scope") or []),
            changed_variables=list(objective.get("variables") or []),
            measured_property_scope=list(objective.get("outcomes") or []),
            test_environment_scope=[],
            relevant_sections=section_labels[:2],
            relevant_tables=relevant_tables,
            excluded_tables=[
                table["table_id"]
                for table in table_summaries
                if table.get("table_id") and table["table_id"] not in relevant_tables
            ],
        )

    def _matching_frame_table_ids(
        self,
        table_summaries: list[dict[str, Any]],
        *,
        axes: tuple[str, ...],
    ) -> list[str]:
        table_ids: list[str] = []
        for table in table_summaries:
            text = " ".join(
                str(value or "")
                for value in (
                    table.get("caption_text"),
                    table.get("heading_path"),
                    " ".join(table.get("column_headers") or []),
                )
            ).lower()
            if any(str(axis or "").lower() in text for axis in axes):
                table_ids.append(str(table["table_id"]))
        return table_ids

    def select_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceSelections:
        self.route_payloads.append(payload)
        objective = payload["objective"]
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        candidates = [payload["current_source"]]
        routes: list[StructuredEvidenceSelection] = []
        for candidate in candidates:
            if candidate["frame_status"] == "excluded":
                routes.append(
                    StructuredEvidenceSelection(
                        role="low_value_or_irrelevant",
                        extractable=False,
                        confidence=0.7,
                    )
                )
                continue
            if candidate["source_kind"] == "text_window":
                routes.append(
                    StructuredEvidenceSelection(
                        role="process_or_treatment",
                        extractable=True,
                        confidence=0.72,
                    )
                )
                continue
            table_schema = candidate.get("table_schema") or {}
            column_headers = (
                table_schema.get("column_headers")
                if isinstance(table_schema.get("column_headers"), list)
                else candidate.get("column_headers")
                if isinstance(candidate.get("column_headers"), list)
                else []
            )
            text = " ".join(
                str(value or "")
                for value in (
                    candidate.get("caption_text"),
                    candidate.get("heading_path"),
                    " ".join(column_headers),
                )
            ).lower()
            outcomes = [
                str(axis or "").lower()
                for axis in objective.get("outcomes", ())
                if str(axis or "").strip()
            ]
            role = (
                "current_experimental_evidence"
                if any(axis in text for axis in outcomes)
                else "process_or_treatment"
            )
            routes.append(
                StructuredEvidenceSelection(
                    role=role,
                    extractable=True,
                    confidence=0.82,
                )
            )
        return StructuredEvidenceSelections(selections=routes)

    def extract_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceExtractions:
        self.unit_payloads.append(payload)
        route = payload["evidence_route"]
        source = payload["source"]
        if route["source_kind"] == "table":
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
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
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
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
        return StructuredEvidenceExtractions()

    def synthesize_findings(
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
        supporting_ids = [
            str(item["evidence_id"])
            for item in result_evidence
            if item.get("evidence_role") == "direct_result"
        ]
        contradicting_ids = [
            str(item["evidence_id"])
            for item in result_evidence
            if item.get("evidence_role") == "contradictory_result"
        ]
        if not factors or not outcome or not supporting_ids:
            return StructuredFindingSynthesis()
        direction = next(
            (
                str(item.get("reported_result", {}).get("direction") or "unknown")
                for item in result_evidence
                if item.get("evidence_id") == supporting_ids[0]
            ),
            "unknown",
        )
        factor_text = " + ".join(factors)
        return StructuredFindingSynthesis(
            findings=[
                StructuredFindingSynthesisItem(
                    result_set_id=str(result_set["result_set_id"]),
                    statement=f"{factor_text} changes {outcome}.",
                    direction=direction,
                    assertion_strength="associative",
                    supporting_evidence_ids=supporting_ids,
                    contradicting_evidence_ids=contradicting_ids,
                )
            ]
        )


__all__ = ["FakeObjectiveExtractor"]
