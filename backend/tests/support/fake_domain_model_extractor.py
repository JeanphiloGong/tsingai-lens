from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from application.core.document_profiles.extraction import DocumentProfileModelOutput
from application.core.objectives.analysis.evidence_routing import (
    EvidenceSelectionModelOutput,
    EvidenceSelectionsModelOutput,
)
from application.core.objectives.analysis.finding_synthesis import (
    StructuredFindingSynthesis,
)
from application.core.objectives.analysis.source_extraction import (
	DirectEvidenceExtractionsModelOutput,
	EvidenceExtractionModelOutput,
	EvidenceExtractionsModelOutput,
	RequestedContextFactsModelOutput,
	RequestedContextFactModelOutput,
)
from application.core.objectives.analysis.source_screening import (
    PaperFrameBatchModelOutput,
    PaperFrameBatchResult,
)
from application.core.objectives.discovery.axis_equivalence import (
    StructuredAxisCanonicalizationPlan,
)
from application.core.objectives.discovery.signal_reconciliation import (
    StructuredPaperSignalReconciliation,
)
from application.core.objectives.discovery.paper_understanding.paper_map_outputs import (
    ExperimentalPaperMapModelOutput,
    ReviewPaperMapModelOutput,
)
from application.core.objectives.discovery.paper_understanding.paper_map_results import (
    StructuredPaperResearchMap,
)
from tests.support.objective_extractor import paper_research_map_scope_outputs

_PROPERTY_HINTS = (
    ("yield strength", "yield_strength"),
    ("tensile strength", "tensile_strength"),
    ("flexural strength", "flexural_strength"),
    ("fatigue life", "fatigue_life"),
    ("retention", "retention"),
    ("hardness", "hardness"),
    ("conductivity", "conductivity"),
    ("modulus", "modulus"),
    ("elongation", "elongation"),
    ("strength", "strength"),
)
_FLOAT_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_TEMP_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:c|°c)\b", re.IGNORECASE)
_TIME_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs)\b",
    re.IGNORECASE,
)
_ATM_PATTERN = re.compile(r"\b(?:under|in)\s+(air|argon|ar|nitrogen|n2|vacuum)\b", re.IGNORECASE)


def _input_payload(user_prompt: str) -> dict[str, Any]:
    marker = "Input JSON:\n"
    marker_position = user_prompt.find(marker)
    if marker_position < 0:
        return {}
    payload_start = marker_position + len(marker)
    payload, _ = json.JSONDecoder().raw_decode(user_prompt[payload_start:])
    return payload if isinstance(payload, dict) else {}


def _source_extraction_payload(user_prompt: str) -> dict[str, Any]:
    prompt_fields: dict[str, str] = {}
    source_marker = "SOURCE:\n"
    source_position = user_prompt.find(source_marker)
    if source_position < 0:
        return {}
    for line in user_prompt[:source_position].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            prompt_fields[key] = value.strip()
    source_text = user_prompt[source_position + len(source_marker) :]
    source_text = source_text.rsplit("\nOUTPUT JSON:", maxsplit=1)[0].strip()
    source_kind = prompt_fields.get("SOURCE KIND", "")
    source: dict[str, Any] = {"source_kind": source_kind}
    if source_text.startswith("{"):
        decoded_source = json.loads(source_text)
        if isinstance(decoded_source, dict):
            source.update(decoded_source)
    else:
        source["text"] = source_text
    # The extraction prompt appends same-paper context after the authoritative
    # Source. Keep the test double's Source text source-local so a verbatim
    # result clause remains valid grounding evidence.
    source_text_without_bundle = source.get("text")
    if isinstance(source_text_without_bundle, str):
        source["text"] = source_text_without_bundle.split(
            "\nSAME-PAPER CONTEXT BUNDLE (CONTEXT ONLY):",
            maxsplit=1,
        )[0].rstrip()
    return {
        "objective": {
            "question": prompt_fields.get("OBJECTIVE QUESTION", ""),
            "variables": json.loads(
                prompt_fields.get("OBJECTIVE VARIABLES", "[]")
            ),
            "outcomes": json.loads(prompt_fields.get("OBJECTIVE OUTCOMES", "[]")),
        },
        "evidence_route": {
            "role": prompt_fields.get(
                "ROUTE HINT ONLY (DO NOT COPY AS EVIDENCE ROLE)",
                "",
            ),
            "source_kind": source_kind,
        },
        "source": source,
    }


class FakeDomainModelExtractor:
    """Deterministic test double for document triage and Objective analysis."""

    def estimate_prompt_tokens(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[Any],
    ) -> int:
        del system_prompt, user_prompt, response_model
        return 0

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[Any],
        postprocess_response: Callable[[Any], Any | None] | None = None,
        **_options: Any,
    ) -> Any:
        del system_prompt
        payload = _input_payload(user_prompt)
        if response_model is ExperimentalPaperMapModelOutput:
            skim = self.extract(payload)
            response = ExperimentalPaperMapModelOutput.model_validate(
                skim.model_dump(exclude={"review_synthesis"})
            )
        elif response_model is ReviewPaperMapModelOutput:
            response = ReviewPaperMapModelOutput(
                evidence_density="low",
                confidence=0.72,
            )
        elif response_model is StructuredPaperResearchMap:
            response = self.extract(payload)
        elif response_model is StructuredPaperSignalReconciliation:
            response = self.reconcile(payload)
        elif response_model is StructuredAxisCanonicalizationPlan:
            response = self.classify(payload)
        elif response_model is PaperFrameBatchModelOutput:
            frame = self.screen_batch(payload)
            source_labels = {
                str(unit.get("source_unit_id") or ""): f"S{index}"
                for index, unit in enumerate(payload.get("source_units") or (), start=1)
                if isinstance(unit, dict) and str(unit.get("source_unit_id") or "")
            }
            response = PaperFrameBatchModelOutput(
                **frame.model_dump(
                    exclude={
                        "relevant_source_unit_ids",
                        "excluded_source_unit_ids",
                    }
                ),
                relevant_source_labels=[
                    source_labels[source_unit_id]
                    for source_unit_id in frame.relevant_source_unit_ids
                    if source_unit_id in source_labels
                ],
                excluded_source_labels=[
                    source_labels[source_unit_id]
                    for source_unit_id in frame.excluded_source_unit_ids
                    if source_unit_id in source_labels
                ],
            )
        elif response_model is EvidenceSelectionsModelOutput:
            response = self.route_source(payload)
        elif response_model is EvidenceExtractionsModelOutput:
            response = self.extract_source(_source_extraction_payload(user_prompt))
        elif response_model is RequestedContextFactsModelOutput:
            source_payload = _source_extraction_payload(user_prompt)
            extracted = self.extract_source(source_payload)
            route = source_payload.get("evidence_route")
            role = str(route.get("role") or "") if isinstance(route, dict) else ""
            context_field = {
                "process_or_treatment": "process",
                "test_condition": "test",
                "composition_or_background": "material",
            }.get(role, "process")
            facts = [
                RequestedContextFactModelOutput(
                    name=str(attribute.get("name") or "source_statement"),
                    value=attribute.get("value")
                    if attribute.get("value") is not None
                    else "",
                    unit=attribute.get("unit"),
                    context_scope=attribute.get("context_scope", "unknown"),
                    group_label=None,
                )
                for extraction in extracted.extractions
                for attribute in (
                    extraction.scientific_context.model_dump().get(context_field, [])
                    if extraction.scientific_context is not None
                    else []
                )
                if isinstance(attribute, dict)
                and str(attribute.get("name") or "").strip()
            ]
            response = RequestedContextFactsModelOutput(facts=facts)
        elif response_model is DirectEvidenceExtractionsModelOutput:
            extracted = self.extract_source(_source_extraction_payload(user_prompt))
            response = DirectEvidenceExtractionsModelOutput.model_validate(
                {
                    "extractions": [
                        item.model_dump()
                        for item in extracted.extractions
                        if item.reported_result is not None
                    ]
                }
            )
        elif response_model is StructuredFindingSynthesis:
            response = StructuredFindingSynthesis()
        else:
            raise TypeError(
                f"unsupported fake structured response: {response_model.__name__}"
            )
        if postprocess_response is not None:
            validated = postprocess_response(response)
            if validated is not None:
                response = validated
        return response

    def extract_document_profile(self, payload: dict[str, Any]) -> DocumentProfileModelOutput:
        title = str(payload.get("title") or "").strip()
        source_filename = str(payload.get("source_filename") or "").strip()
        lead_text = str(payload.get("abstract_or_lead_text") or "")
        headings = payload.get("headings") if isinstance(payload.get("headings"), list) else []

        heading_text = " ".join(str(item) for item in headings)
        combined_text = " ".join(part for part in (title, source_filename, heading_text, lead_text) if part)
        lowered_text = combined_text.lower()

        review_hits = sum(
            marker in lowered_text
            for marker in (
                "review",
                "overview",
                "survey",
                "recent advances",
                "progress in",
            )
        )
        methods_hits = sum(
            marker in lowered_text
            for marker in (
                "experimental",
                "materials and methods",
                "method",
                "methods",
                "experiment",
            )
        )
        characterization_hits = sum(
            marker in lowered_text
            for marker in (
                "characterization",
                "xrd",
                "sem",
                "tem",
                "xps",
                "ftir",
                "raman",
            )
        )
        procedural_hits = sum(
            marker in lowered_text
            for marker in (
                "mixed",
                "stir",
                "anneal",
                "annealed",
                "dried",
                "fabricated",
                "prepared",
                "sintered",
            )
        )
        results_hits = (
            len(_TEMP_PATTERN.findall(combined_text))
            + len(_TIME_PATTERN.findall(combined_text))
            + sum(
                marker in lowered_text
                for marker in ("mpa", "gpa", "%", "w/mk", "conductivity", "strength")
            )
        )

        experimental_score = (
            methods_hits + characterization_hits + procedural_hits + results_hits
        )

        warnings: list[str] = []
        if review_hits and experimental_score >= 3:
            doc_type = "mixed"
        elif review_hits:
            doc_type = "review"
        elif experimental_score >= 5:
            doc_type = "experimental"
        elif experimental_score >= 2:
            doc_type = "experimental"
        else:
            doc_type = "uncertain"
            warnings.append("classification_uncertain")

        return DocumentProfileModelOutput(
            doc_type=doc_type,
            profile_warnings=sorted(set(warnings)),
            confidence=0.86 if doc_type == "experimental" else 0.82 if doc_type == "review" else 0.78,
        )

    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        title = str(payload.get("title") or "").strip()
        profile_hint = (
            payload.get("profile_hint")
            if isinstance(payload.get("profile_hint"), dict)
            else {}
        )
        headings = payload.get("headings") if isinstance(payload.get("headings"), list) else []
        text_preview = str(payload.get("text_preview") or "")
        table_text = " ".join(
            str(item.get("caption_text") or "")
            for item in payload.get("table_captions", [])
            if isinstance(item, dict)
        )
        figure_text = " ".join(
            str(item.get("caption_text") or "")
            for item in payload.get("figure_captions", [])
            if isinstance(item, dict)
        )
        combined_text = " ".join(
            part
            for part in (
                title,
                " ".join(str(item) for item in headings),
                text_preview,
                table_text,
                figure_text,
            )
            if part
        )
        lowered_text = combined_text.lower()

        material_system = self._infer_material_system(title, combined_text)
        material_family = material_system.get("family")
        candidate_materials = (
            []
            if material_family == "unspecified material system"
            else [str(material_family)]
        )
        candidate_processes: list[str] = []
        if any(token in lowered_text for token in ("lpbf", "slm", "laser powder bed fusion")):
            candidate_processes.append("LPBF")
        if any(token in lowered_text for token in ("anneal", "heat treatment", "heated")):
            candidate_processes.append("heat treatment")
        if "mixed" in lowered_text or "stirred" in lowered_text:
            candidate_processes.append("mixing")

        candidate_properties = []
        property_name = self._infer_property(combined_text)
        if property_name:
            candidate_properties.append(property_name)
        changed_variables = []
        if self._extract_process_context(combined_text).get("temperatures_c"):
            changed_variables.append("temperature")
        if self._extract_process_context(combined_text).get("durations"):
            changed_variables.append("duration")
        if "anneal" in lowered_text:
            changed_variables.append("annealing")

        variables = changed_variables or candidate_processes or ["processing"]
        studies = []
        if candidate_materials and candidate_properties:
            studies.append(
                {
                    "experiment_label": "inferred primary study",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "material_scope": candidate_materials,
                    "process_context": candidate_processes,
                    "relationships": [
                        {
                            "varied_factors": variables,
                            "outcome": outcome,
                            "confidence": 0.86,
                        }
                        for outcome in candidate_properties
                    ],
                    "confidence": 0.86,
                }
            )

        doc_role = str(profile_hint.get("role_hint") or "").strip() or "uncertain"
        if doc_role not in {"experimental", "review", "mixed", "uncertain"}:
            doc_role = "uncertain"
        evidence_density = (
            "high"
            if studies
            else "medium" if candidate_materials or candidate_properties else "low"
        )
        return StructuredPaperResearchMap(
            doc_role=doc_role,
            **paper_research_map_scope_outputs(
                payload,
                studies,
            ),
            unresolved_signals=[],
            evidence_density=evidence_density,
            confidence=0.86 if studies else 0.62,
            warnings=[] if studies else ["objective_uncertain"],
        )

    def reconcile(
        self,
        payload: dict[str, Any],
    ) -> StructuredPaperSignalReconciliation:
        return StructuredPaperSignalReconciliation()

    def classify(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        return StructuredAxisCanonicalizationPlan(
            decisions=[
                {
                    "pair_id": str(pair["pair_id"]),
                    "equivalent": True,
                    "same_research_topic": True,
                }
                for pair in payload.get("axis_pairs") or ()
                if isinstance(pair, dict) and str(pair.get("pair_id") or "").strip()
            ]
        )

    def screen_batch(
        self,
        payload: dict[str, Any],
    ) -> PaperFrameBatchResult:
        objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
        paper_prior = payload.get("paper_prior") if isinstance(payload.get("paper_prior"), dict) else {}
        document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
        document_id = str(document.get("document_id") or "")
        source_units = (
            payload.get("source_units")
            if isinstance(payload.get("source_units"), list)
            else []
        )
        source_unit_ids = [
            str(unit.get("source_unit_id") or "")
            for unit in source_units
            if isinstance(unit, dict) and str(unit.get("source_unit_id") or "")
        ]
        excluded_document_ids = {
            str(value)
            for value in objective.get("excluded_document_ids", [])
            if str(value).strip()
        }
        if document_id in excluded_document_ids or paper_prior.get("doc_role") == "review":
            return PaperFrameBatchResult(
                relevance="irrelevant",
                paper_role="review",
                screening_note="Paper does not directly support the objective.",
                excluded_source_unit_ids=source_unit_ids,
            )

        axes = [
            str(value).lower()
            for value in (
                *(objective.get("variables") or []),
                *(objective.get("outcomes") or []),
            )
            if str(value).strip()
        ]
        relevant_source_unit_ids: list[str] = []
        excluded_source_unit_ids: list[str] = []
        for unit in source_units:
            if not isinstance(unit, dict):
                continue
            source_unit_id = str(unit.get("source_unit_id") or "")
            if unit.get("source_kind") == "section":
                if source_unit_id:
                    relevant_source_unit_ids.append(source_unit_id)
                continue
            source_text = " ".join(
                str(value or "")
                for value in (
                    unit.get("caption_text"),
                    unit.get("heading_path"),
                    " ".join(str(item) for item in unit.get("column_headers") or []),
                )
            ).lower()
            if source_unit_id and any(axis in source_text for axis in axes):
                relevant_source_unit_ids.append(source_unit_id)
            elif source_unit_id:
                excluded_source_unit_ids.append(source_unit_id)

        return PaperFrameBatchResult(
            relevance="high" if paper_prior else "uncertain",
            paper_role="primary_experiment",
            screening_note="Paper directly supports the objective.",
            material_match=list(objective.get("material_scope") or []),
            changed_variables=list(objective.get("variables") or []),
            measured_property_scope=[
                str(item)
                for item in objective.get("outcomes", [])
                if str(item).strip()
            ],
            test_environment_scope=[],
            relevant_source_unit_ids=relevant_source_unit_ids,
            excluded_source_unit_ids=excluded_source_unit_ids,
        )

    def route_source(
        self,
        payload: dict[str, Any],
    ) -> EvidenceSelectionsModelOutput:
        objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
        outcomes = [
            str(value).lower()
            for value in objective.get("outcomes", [])
            if str(value).strip()
        ]
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        candidates = [payload["current_source"]]
        routes: list[EvidenceSelectionModelOutput] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            source_kind = str(candidate.get("source_kind") or "text_window")
            source_ref = str(candidate.get("source_ref") or "")
            if not source_ref:
                continue
            if candidate.get("frame_status") == "excluded":
                routes.append(
                    EvidenceSelectionModelOutput(
                        role="low_value_or_irrelevant",
                        extractable=False,
                        confidence=0.7,
                    )
                )
                continue
            if source_kind == "table":
                table_schema = (
                    candidate.get("table_schema")
                    if isinstance(candidate.get("table_schema"), dict)
                    else {}
                )
                column_headers = (
                    table_schema.get("column_headers")
                    if isinstance(table_schema.get("column_headers"), list)
                    else candidate.get("column_headers")
                    if isinstance(candidate.get("column_headers"), list)
                    else []
                )
                table_text = " ".join(
                    str(value or "")
                    for value in (
                        candidate.get("caption_text"),
                        candidate.get("heading_path"),
                        " ".join(
                            str(item)
                            for item in column_headers
                        ),
                    )
                ).lower()
                role = (
                    "current_experimental_evidence"
                    if any(axis in table_text for axis in outcomes)
                    else "process_or_treatment"
                )
                routes.append(
                    EvidenceSelectionModelOutput(
                        role=role,
                        extractable=True,
                        confidence=0.82,
                    )
                )
                continue
            routes.append(
                EvidenceSelectionModelOutput(
                    role="process_or_treatment",
                    extractable=True,
                    confidence=0.72,
                )
            )
        return EvidenceSelectionsModelOutput(selections=routes)

    def extract_source(
        self,
        payload: dict[str, Any],
    ) -> EvidenceExtractionsModelOutput:
        route = payload.get("evidence_route")
        source = payload.get("source")
        if not isinstance(route, dict) or not isinstance(source, dict):
            return EvidenceExtractionsModelOutput()
        if route.get("source_kind") == "table":
            headers = [
                str(value)
                for value in source.get("column_headers", [])
                if str(value).strip()
            ]
            matrix = source.get("table_matrix") if isinstance(source.get("table_matrix"), list) else []
            property_header = next(
                (
                    header
                    for header in headers
                    if any(
                        token in header.lower()
                        for token in (
                            "strength",
                            "elongation",
                            "hardness",
                            "corrosion",
                            "density",
                        )
                    )
                ),
                headers[-1] if headers else "value",
            )
            for row in matrix[1:]:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                sample_label = str(row[0]).strip()
                value_text = str(row[-1]).strip()
                if not sample_label or not value_text:
                    continue
                numeric_match = _FLOAT_PATTERN.search(value_text.replace(",", ""))
                return EvidenceExtractionsModelOutput(
                    extractions=[
                        EvidenceExtractionModelOutput(
                            evidence_role="direct_result",
                            reported_result={
                                "outcome": property_header,
                                "value": (
                                    float(numeric_match.group(0))
                                    if numeric_match
                                    else value_text
                                ),
                                "unit": None,
                                "direction": "unknown",
                                "result_text": (
                                    f"{sample_label}: {property_header} = {value_text}"
                                ),
                            },
                            attribution_scope="descriptive_only",
                            scientific_context={
                                "sample": [
                                    {"name": "label", "value": sample_label}
                                ]
                            },
                            resolution_status="partial",
                            confidence=0.78,
                        )
                    ]
                )
            return EvidenceExtractionsModelOutput()
        if route.get("source_kind") == "text_window" and source.get("text"):
            return EvidenceExtractionsModelOutput(
                extractions=[
                    EvidenceExtractionModelOutput(
                        evidence_role="condition_context",
                        attribution_scope="not_attributable",
                        scientific_context={
                            "process": [
                                {
                                    "name": "source_statement",
                                    "value": str(source.get("text"))[:160],
                                }
                            ]
                        },
                        resolution_status="partial",
                        confidence=0.7,
                    )
                ]
            )
        return EvidenceExtractionsModelOutput()

    def _infer_material_system(self, title: str, text: str):
        lowered = f"{title}\n{text}".lower()
        if "316l" in lowered or "stainless steel" in lowered:
            family = "316L stainless steel"
        elif "epoxy" in lowered:
            family = "epoxy composite"
        elif "ti alloy" in lowered or "titanium" in lowered:
            family = "Ti alloy"
        elif "ceramic" in lowered:
            family = "ceramic"
        elif "coating" in lowered:
            family = "coating"
        elif "composite" in lowered:
            family = "composite"
        else:
            family = "unspecified material system"
        return {"family": family, "composition": None}

    def _extract_process_context(self, text: str):
        temperatures = [float(match.group(1)) for match in _TEMP_PATTERN.finditer(text)]
        durations = [match.group(0) for match in _TIME_PATTERN.finditer(text)]
        atmosphere_match = _ATM_PATTERN.search(text)
        return {
            "temperatures_c": temperatures,
            "durations": durations,
            "atmosphere": atmosphere_match.group(1) if atmosphere_match else None,
        }

    def _infer_property(self, text: str) -> str | None:
        lowered = str(text or "").lower()
        if "yield strength" in lowered:
            return "yield_strength"
        if "tensile strength" in lowered:
            return "tensile_strength"
        if "flexural strength" in lowered:
            return "flexural_strength"
        if "strength" in lowered:
            return "tensile_strength"
        for token, normalized in _PROPERTY_HINTS:
            if token in lowered:
                return normalized
        return None
