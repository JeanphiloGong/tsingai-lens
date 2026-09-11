from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)
from .common import (
    PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT,
    PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    PAPER_RESEARCH_MAP_SOURCE_UNIT_LIMIT,
    PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    _PAPER_MAP_CONTEXT_LIMIT,
    _PAPER_MAP_STUDY_LIMIT,
    _PAPER_MAP_VARIED_FACTOR_LIMIT,
    _REVIEW_CITATION_LEAD_LIMIT,
    _REVIEW_KNOWLEDGE_ITEM_LIMIT,
    _SOURCE_SIGNAL_CONTEXT_LIMIT,
    _SOURCE_SIGNAL_LIMIT,
    _bounded_mapping_list,
    _mark_bounded_output,
)
from .paper_map_outputs import (
    ExperimentalPaperMapModelOutput,
    PaperSourceSignalScreenModelOutput,
    ReviewPaperMapModelOutput,
)
from .paper_map_results import StructuredPaperResearchMap

PAPER_RESEARCH_MAP_PROMPT_VERSION = "paper_map.v6"
PAPER_SOURCE_SIGNAL_PROMPT_VERSION = "paper_source_signal.v3"
PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT = 12_288
_MODEL_HIDDEN_CONTENT_KEYS = {
    "block_id",
    "cell_id",
    "collection_id",
    "column_id",
    "column_index",
    "document_id",
    "end_col",
    "end_row",
    "figure_id",
    "fragment_start",
    "page_index",
    "row_id",
    "row_index",
    "source_kind",
    "source_ref",
    "source_unit_id",
    "start_col",
    "start_row",
    "structured_path",
    "table_id",
    "window_id",
}

_MAX_COMPLETION_TOKENS = 2048
_SOURCE_SIGNAL_MAX_COMPLETION_TOKENS = 2048
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are mapping one paper's stated research scope for traceable Objective discovery.

Non-negotiable rules:
- This is lightweight paper mapping, not experiment reconstruction or Evidence extraction.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied short `source_labels`; the backend owns real Source identity.
- Do not infer material systems from filenames or section names.
""".strip()

_REVIEW_SYSTEM_PROMPT = """
You screen one bounded Source window from a review paper for traceable
review-author scientific synthesis.

Non-negotiable rules:
- This is synthesis screening, not reconstruction of every cited experiment.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied short `source_labels`; the backend owns real Source identity.
- A citation points to primary literature; it is not review-owned evidence.
""".strip()


def _normalize_experimental_paper_map_payload(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    overflows: list[str] = []
    studies = _bounded_mapping_list(
        payload,
        "studies",
        limit=_PAPER_MAP_STUDY_LIMIT,
        path="studies",
        overflows=overflows,
    )
    normalized_studies: list[object] = []
    for study_index, study in enumerate(studies):
        if not isinstance(study, Mapping):
            normalized_studies.append(study)
            continue
        normalized_study = dict(study)
        for field_name in ("material_scope", "process_context"):
            _bounded_mapping_list(
                normalized_study,
                field_name,
                limit=_PAPER_MAP_CONTEXT_LIMIT,
                path=f"studies[{study_index}].{field_name}",
                overflows=overflows,
            )
        relationships = _bounded_mapping_list(
            normalized_study,
            "relationships",
            limit=PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
            path=f"studies[{study_index}].relationships",
            overflows=overflows,
        )
        normalized_relationships: list[object] = []
        for relationship_index, relationship in enumerate(relationships):
            if not isinstance(relationship, Mapping):
                normalized_relationships.append(relationship)
                continue
            normalized_relationship = dict(relationship)
            _bounded_mapping_list(
                normalized_relationship,
                "factor_assertions",
                limit=_PAPER_MAP_VARIED_FACTOR_LIMIT,
                path=(
                    f"studies[{study_index}].relationships[{relationship_index}]"
                    ".factor_assertions"
                ),
                overflows=overflows,
            )
            normalized_relationships.append(normalized_relationship)
        normalized_study["relationships"] = normalized_relationships
        normalized_studies.append(normalized_study)
    payload["studies"] = normalized_studies

    signals = _bounded_mapping_list(
        payload,
        "unresolved_signals",
        limit=PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
        path="unresolved_signals",
        overflows=overflows,
    )
    normalized_signals: list[object] = []
    for signal_index, signal in enumerate(signals):
        if not isinstance(signal, Mapping):
            normalized_signals.append(signal)
            continue
        normalized_signal = dict(signal)
        for field_name in ("material_scope", "process_context"):
            _bounded_mapping_list(
                normalized_signal,
                field_name,
                limit=_PAPER_MAP_CONTEXT_LIMIT,
                path=f"unresolved_signals[{signal_index}].{field_name}",
                overflows=overflows,
            )
        normalized_signals.append(normalized_signal)
    payload["unresolved_signals"] = normalized_signals
    return _mark_bounded_output(payload, overflows=overflows)


def _normalize_source_signal_screen_payload(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    overflows: list[str] = []
    signals = _bounded_mapping_list(
        payload,
        "signals",
        limit=_SOURCE_SIGNAL_LIMIT,
        path="signals",
        overflows=overflows,
    )
    normalized_signals: list[object] = []
    for signal_index, signal in enumerate(signals):
        if not isinstance(signal, Mapping):
            normalized_signals.append(signal)
            continue
        normalized_signal = dict(signal)
        for field_name in ("material_scope", "process_context"):
            _bounded_mapping_list(
                normalized_signal,
                field_name,
                limit=_SOURCE_SIGNAL_CONTEXT_LIMIT,
                path=f"signals[{signal_index}].{field_name}",
                overflows=overflows,
            )
        normalized_signals.append(normalized_signal)
    payload["signals"] = normalized_signals
    return _mark_bounded_output(payload, overflows=overflows)


def _review_synthesis_only(response: StructuredPaperResearchMap) -> StructuredPaperResearchMap:
    """Keep only scientific synthesis owned by a review's authors."""

    return response.model_copy(
        update={
            "doc_role": "review",
            "studies": [
                study for study in response.studies if study.claim_scope == "synthesis"
            ],
            "unresolved_signals": [
                signal
                for signal in response.unresolved_signals
                if signal.claim_scope == "synthesis"
            ],
        }
    )


def _model_visible_content(value: object) -> object:
    """Remove backend identity and slicing coordinates from scientific content."""

    if isinstance(value, Mapping):
        return {
            str(key): _model_visible_content(item)
            for key, item in value.items()
            if str(key) not in _MODEL_HIDDEN_CONTENT_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_model_visible_content(item) for item in value]
    return value


def _paper_map_model_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    """Project backend input into the scientific contract visible to the model."""

    source_units_by_label: dict[str, Mapping[str, Any]] = {}
    source_unit_ids: set[str] = set()
    model_sources: list[dict[str, Any]] = []
    for source_unit in payload.get("source_units") or ():
        if not isinstance(source_unit, Mapping):
            continue
        source_unit_id = str(source_unit.get("source_unit_id") or "").strip()
        if not source_unit_id:
            raise ValueError("paper map Source-unit ids must be non-empty")
        if source_unit_id in source_unit_ids:
            raise ValueError("paper map Source-unit ids must be unique")
        source_unit_ids.add(source_unit_id)
        label = f"S{len(model_sources) + 1}"
        source_units_by_label[label] = source_unit
        model_sources.append(
            {
                "label": label,
                "section_path": str(source_unit.get("section_path") or "").strip(),
                "content": _model_visible_content(source_unit.get("content")),
            }
        )

    profile = payload.get("document_profile")
    document_type = (
        str(profile.get("doc_type") or "").strip()
        if isinstance(profile, Mapping)
        else ""
    )
    return (
        {
            "title": str(payload.get("title") or "").strip(),
            "document_type": document_type,
            "window_role": str(payload.get("window_role") or "unknown").strip()
            or "unknown",
            "sources": model_sources,
        },
        source_units_by_label,
    )


def _source_unit_ids_from_labels(
    source_labels: list[str],
    source_units_by_label: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    unknown_labels = sorted(set(source_labels) - source_units_by_label.keys())
    if unknown_labels:
        raise ValueError(
            "paper research map references unknown Source labels: "
            f"{unknown_labels}"
        )
    return [
        str(source_units_by_label[label].get("source_unit_id") or "").strip()
        for label in source_labels
    ]


def _paper_map_response_model(
    payload: Mapping[str, Any],
) -> type[ExperimentalPaperMapModelOutput] | type[ReviewPaperMapModelOutput]:
    profile = payload.get("document_profile")
    if (
        isinstance(profile, Mapping)
        and str(profile.get("doc_type") or "").strip() == "review"
    ):
        return ReviewPaperMapModelOutput
    return ExperimentalPaperMapModelOutput


def _paper_map_response(
    response: ExperimentalPaperMapModelOutput | ReviewPaperMapModelOutput,
    source_units_by_label: Mapping[str, Mapping[str, Any]],
) -> StructuredPaperResearchMap:
    if isinstance(response, ExperimentalPaperMapModelOutput):
        payload = response.model_dump()
        for study in payload["studies"]:
            for relationship in study["relationships"]:
                factor_assertions = relationship.pop("factor_assertions")
                relationship["varied_factors"] = [
                    assertion["label"] for assertion in factor_assertions
                ]
                source_labels = list(relationship.pop("source_labels"))
                source_labels.extend(
                    source_label
                    for assertion in factor_assertions
                    for source_label in assertion["source_labels"]
                )
                relationship["source_unit_ids"] = _source_unit_ids_from_labels(
                    list(dict.fromkeys(source_labels)),
                    source_units_by_label,
                )
        for signal in payload["unresolved_signals"]:
            signal["source_unit_ids"] = _source_unit_ids_from_labels(
                signal.pop("source_labels"),
                source_units_by_label,
            )
        return StructuredPaperResearchMap.model_validate(payload)

    studies: list[dict[str, Any]] = []
    unresolved_signals: list[dict[str, Any]] = []
    study_keys: set[tuple[object, ...]] = set()
    signal_keys: set[tuple[object, ...]] = set()
    candidate_items = (
        *response.review_synthesis.synthesis_claims,
        *response.review_synthesis.disputes,
    )
    for item in candidate_items:
        variables = tuple(
            dict.fromkeys(value.strip() for value in item.variables if value.strip())
        )
        outcomes = tuple(
            dict.fromkeys(value.strip() for value in item.outcomes if value.strip())
        )
        source_unit_ids = tuple(
            _source_unit_ids_from_labels(
                list(dict.fromkeys(item.source_labels)),
                source_units_by_label,
            )
        )
        material_scope = tuple(
            dict.fromkeys(value.strip() for value in item.material_scope if value.strip())
        )
        if variables and outcomes:
            study_key = (variables, outcomes, source_unit_ids, material_scope)
            if study_key in study_keys:
                continue
            study_keys.add(study_key)
            studies.append(
                {
                    "design_type": "observational",
                    "claim_scope": "synthesis",
                    "material_scope": list(material_scope),
                    "relationships": [
                        {
                            "varied_factors": list(variables),
                            "outcome": outcome,
                            "source_unit_ids": list(source_unit_ids),
                            "confidence": item.confidence,
                        }
                        for outcome in outcomes
                    ],
                    "confidence": item.confidence,
                }
            )
            continue

        for signal_type, labels in (("variable", variables), ("outcome", outcomes)):
            for label in labels:
                signal_key = (signal_type, label, source_unit_ids, material_scope)
                if signal_key in signal_keys:
                    continue
                signal_keys.add(signal_key)
                unresolved_signals.append(
                    {
                        "signal_type": signal_type,
                        "label": label,
                        "variable_role": (
                            "uncertain"
                            if signal_type == "variable"
                            else "not_applicable"
                        ),
                        "design_type": "observational",
                        "claim_scope": "synthesis",
                        "material_scope": list(material_scope),
                        "source_unit_ids": list(source_unit_ids),
                        "confidence": item.confidence,
                    }
                )

    derived_saturated = len(unresolved_signals) > PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT
    return StructuredPaperResearchMap.model_validate(
        {
            "doc_role": "review",
            "studies": studies,
            "unresolved_signals": unresolved_signals[
                :PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT
            ],
            "review_synthesis": {
                field_name: [
                    {
                        **item.model_dump(exclude={"source_labels"}),
                        "source_unit_ids": _source_unit_ids_from_labels(
                            item.source_labels,
                            source_units_by_label,
                        ),
                    }
                    for item in getattr(response.review_synthesis, field_name)
                ]
                for field_name in (
                    "synthesis_claims",
                    "disputes",
                    "evidence_gaps",
                    "citation_leads",
                )
            },
            "output_saturated": response.output_saturated or derived_saturated,
            "evidence_density": response.evidence_density,
            "confidence": response.confidence,
            "warnings": response.warnings,
        }
    )


def _build_review_synthesis_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    allowed_source_labels = [
        str(source.get("label") or "").strip()
        for source in payload.get("sources") or ()
        if isinstance(source, Mapping) and str(source.get("label") or "").strip()
    ]
    allowed_source_labels_json = json.dumps(
        allowed_source_labels,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    user_prompt = (
        "TASK MODEL\n"
        "Map only scientific synthesis authored by one review paper from one bounded "
        "high-level Source window. This is thematic review screening, not reconstruction "
        "of cited experiments, primary Evidence extraction, or Objective wording. The "
        "backend derives candidate factor/outcome pairs from the returned review-author "
        "statements; do not return a second study representation.\n\n"
        "INPUT SCHEMA\n"
        "- `title` identifies the review paper; `document_type` is a coarse role hint.\n"
        "- `window_role` describes this incomplete reading view but is not scientific "
        "evidence.\n"
        "- `sources` contain review text, table summaries, or figure captions. Content "
        "is the authority; each short label lets the backend restore lineage.\n"
        "- Named authors and numbered citations are navigation to primary literature, "
        "not review-owned experimental Evidence.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Separate review-author synthesis from descriptions of individual cited "
        "studies. Phrases such as 'across studies', 'overall', explicit agreement or "
        "disagreement, taxonomies, and review conclusions can establish synthesis.\n"
        "2. Record each retained statement exactly once in `review_synthesis`: use "
        "`synthesis_claims` for cross-study judgments, `disputes` for explicit conflict, "
        "`evidence_gaps` for missing evidence or validation, and `citation_leads` for "
        "primary papers worth inspecting.\n"
        "3. For claims and disputes, record neutral variable and outcome axes only when "
        "the review authors explicitly connect them. Preserve the full joint variable "
        "set and keep specific outcomes separate. The backend derives candidate scope "
        "relationships from these fields.\n"
        "4. Preserve a partial variable-only or outcome-only statement in the same "
        "knowledge item. Do not borrow its missing axis from another Source.\n"
        "5. Copy only the Source labels that directly support each retained statement. "
        "Use confidence and warnings for ambiguity instead of filling gaps.\n\n"
        "HARD RULES\n"
        "- Do not return `studies` or `unresolved_signals`; those are derived by the "
        "backend so the same review judgment is not generated twice.\n"
        "- Do not reconstruct samples, controls, conditions, or outcomes of one cited "
        "paper. Those facts require its primary Source.\n"
        "- Citation leads are navigation only and never primary Evidence.\n"
        "- Do not infer scientific content from titles, filenames, section names, or "
        "general knowledge.\n"
        "- Return empty arrays when no eligible review-author statement is supplied.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Cited result only: 'Miranda et al. [20] reported lower residual stress.' "
        "Return it only as a citation lead when it is useful navigation.\n"
        "- Review synthesis: 'Across studies, preheating generally reduced residual "
        "stress.' Return one synthesis claim with variable='preheating condition' and "
        "outcome='residual stress'.\n"
        "- Conflict: 'Porosity trends disagree across scan strategies.' Return one "
        "dispute with variable='scan strategy' and outcome='porosity'; do not invent a "
        "direction.\n"
        "- Review method only: 'We searched Web of Science.' Return empty arrays.\n\n"
        "OUTPUT CONTRACT\n"
        "- Return doc_role='review', `review_synthesis`, evidence_density, confidence, "
        "warnings, and output_saturated.\n"
        f"- Return at most {_REVIEW_KNOWLEDGE_ITEM_LIMIT} synthesis claims, "
        f"{_REVIEW_KNOWLEDGE_ITEM_LIMIT} disputes, "
        f"{_REVIEW_KNOWLEDGE_ITEM_LIMIT} evidence gaps, and "
        f"{_REVIEW_CITATION_LEAD_LIMIT} citation leads.\n"
        "- Each item contains one concise review-author statement, compact scientific "
        "scope, confidence, and 1-4 allowed `source_labels`.\n"
        "- Set output_saturated=true when eligible review-author knowledge exceeds "
        "these limits. Return only compact schema-valid JSON.\n\n"
        "BATCH LINEAGE CONTRACT\n"
        f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}\n"
        "Copy labels only from this exact list."
    )
    return _REVIEW_SYSTEM_PROMPT, user_prompt


def build_paper_research_map_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    model_payload, _ = _paper_map_model_payload(payload)
    document_profile = payload.get("document_profile")
    if isinstance(document_profile, Mapping) and (
        str(document_profile.get("doc_type") or "").strip() == "review"
    ):
        return _build_review_synthesis_prompt(model_payload)

    allowed_source_labels = [
        str(source.get("label") or "").strip()
        for source in model_payload.get("sources") or ()
        if isinstance(source, Mapping) and str(source.get("label") or "").strip()
    ]
    allowed_source_labels_json = json.dumps(
        allowed_source_labels,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    user_prompt = (
        "TASK MODEL\n"
        "Map the paper's stated research scope from one bounded high-level Source "
        "window for Objective discovery. This is candidate-scope extraction, not "
        "full experiment reconstruction, Evidence extraction, causal synthesis, or "
        "Objective wording. A relationship is candidate scope, not proven Evidence.\n\n"
        "INPUT SCHEMA\n"
        "- `title` identifies the paper and `document_type` is a coarse role hint.\n"
        "- `window_role` describes this bounded reading view.\n"
        "- `sources` contains high-level abstract, conclusion, overview, or caption "
        "content. Each Source has a short label for backend lineage. Source content "
        "is the scientific authority.\n"
        "This is one incomplete view of the paper; absence from this window is not "
        "evidence of absence elsewhere. Detailed Methods, Results, and table rows are "
        "inspected after Objective confirmation.\n\n"
        f"Input JSON:\n{json.dumps(model_payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. First decide whether the Source reports or proposes a scientific "
        "investigation: an explicit change, comparison, model, measurement, or "
        "observation. General statements of prevalence, use, importance, or motivation "
        "do not name a research variable or outcome; return empty studies and signals "
        "for them.\n"
        "2. Identify whose work is described. Use claim_scope=current_work only for "
        "this paper; synthesis and named citations remain separate. Never label a "
        "cited study current_work.\n"
        "3. Keep only explicitly changed, compared, or modeled factors and explicitly "
        "measured, observed, or predicted outcomes. Use neutral scientific axis names, "
        "not levels, values, directions, settings, samples, controls, or test details.\n"
        "4. For every retained factor, classify its paper-stated role as `varied`, "
        "`compared`, or `modeled` and copy the Source labels that establish that role. "
        "A parameter that is fixed, merely mentioned, or whose role is uncertain cannot "
        "appear in a relationship; keep it as an unresolved variable signal with "
        "variable_role=`fixed`, `context`, or `uncertain` only when retaining it helps "
        "explain incomplete scope. Outcome signals use `not_applicable`.\n"
        "5. When the Source explicitly links factors to outcomes, return one "
        "relationship per outcome. Preserve the full jointly varied, compared, or "
        "modeled factor set. Do not demote an explicit configuration-to-outcome link "
        "to unresolved signals.\n"
        "6. Do not promote causal explanations or intermediate mechanisms introduced "
        "by phrases such as 'attributed to', 'due to', or 'allowing' unless the Source "
        "separately states that they were measured, observed, or predicted outcomes.\n"
        "7. If only one axis is explicit, or an outcome is a broad family such as "
        "microstructure or mechanical properties or combines distinct measurements, "
        "return the explicit axis in `unresolved_signals` instead of inventing a "
        "metric or link.\n"
        "8. Keep one study unless the Source explicitly names distinct experiments or "
        "designs. Do not invent an experiment label to split one paper-owned study by "
        "Source or axis family.\n"
        "9. Record material_scope and concise process_context only when explicit. "
        "Detailed experiment fields are intentionally absent.\n"
        "10. Copy every directly supporting Source label. Use uncertainty or empty "
        "arrays rather than filling gaps.\n\n"
        "HARD RULES\n"
        "- Use only supplied Source content; do not infer from filenames, headings, or "
        "general knowledge.\n"
        "- Do not merge cited work with current work or move axes between studies.\n"
        "- Do not treat factor levels, fixed settings, result values, or result "
        "direction as research axes.\n"
        "- Do not repeat an axis as unresolved when it is already in a relationship.\n"
        "- Unresolved signals represent incomplete links, not relationship overflow. "
        "If a supported relationship exceeds the relationship limit, set "
        "output_saturated=true.\n"
        "- Copy `source_labels` only from the allowed list, without duplicates, at "
        f"most {PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT} per item.\n"
        "- Return empty arrays rather than guessing unsupported study structure.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Joint factors: temperature and pressure changed together. Return both as "
        "factor_assertions with role=`varied` and return one relationship per outcome.\n"
        "- Explicit configuration effect: 'PTA leading with front wire feeding gave "
        "stable deposition and good bead appearance.' Return two relationships with "
        "the full factors ['heat-source configuration','wire-feeding direction'] and "
        "outcomes 'deposition stability' and 'bead appearance'.\n"
        "- Broad outcome: 'Heat treatment changed the microstructure.' Return the "
        "outcome as unresolved; do not invent grain size or phase fraction.\n"
        "- Mechanism clause: 'Higher deposition rate is attributed to extended energy "
        "distribution and melt pool size.' Keep deposition rate; do not create energy "
        "distribution or melt pool size outcomes unless the Source says they were "
        "measured, observed, or predicted.\n"
        "- Factor levels: low, medium, and high input are levels. Return one varied "
        "factor assertion for the input axis, not three factor names.\n"
        "- Result direction: 'fatigue strength decreases with lower VED.' Return "
        "outcome='fatigue strength'; result direction, value, or comparison sentence "
        "belongs to later Evidence extraction.\n"
        "- Incomplete link: a Methods Source names laser power but no response. Return "
        "`studies=[]`; do not borrow an outcome. Return the explicit axis in "
        "`unresolved_signals`.\n"
        "- Cited result: 'Miranda et al. [20] increased laser power and reduced "
        "porosity.' Keep claim_scope=background.\n"
        "- General background: 'Additive manufacturing is widely used in aerospace.' "
        "Return empty studies and unresolved_signals; usage context is not a measured "
        "outcome.\n"
        "- Fixed versus varied: 'All groups used 25 C while pressure varied from 1 to "
        "3 MPa.' Return only pressure as a varied factor assertion; temperature may be "
        "an unresolved fixed signal but cannot enter the relationship.\n"
        "- Generic parameter list: 'Parameters such as temperature, pressure, and time "
        "can matter. Here, time was varied and conversion was measured.' Only time is a "
        "varied factor; the generic list does not make temperature or pressure study "
        "axes.\n\n"
        "OUTPUT CONTRACT\n"
        "Return one compact schema object with doc_role, studies, unresolved_signals, "
        "output_saturated, evidence_density, confidence, and warnings.\n"
        "A study contains optional experiment_label only when explicitly named, plus "
        "design_type, claim_scope, material_scope, process_context, relationships, and "
        "confidence. A relationship contains factor_assertions, one outcome, "
        "source_labels, and confidence. Each factor assertion contains label, role, and "
        "the Source labels establishing that role.\n"
        f"Limits: up to {_PAPER_MAP_STUDY_LIMIT} studies, up to "
        f"{PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT} relationships per study, up to "
        f"{PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT} unresolved signals, at most "
        f"{_PAPER_MAP_VARIED_FACTOR_LIMIT} factor assertions, at most "
        f"{PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT} unique `source_labels`, and up to 2 "
        "`warnings`, each at most 240 characters. Set output_saturated=true only if a "
        "distinct supported item exceeds these limits.\n\n"
        "BATCH LINEAGE\n"
        f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}\n"
        "Copy labels only from this exact list."
    )
    return _SYSTEM_PROMPT, user_prompt


_SOURCE_SIGNAL_SYSTEM_PROMPT = """
You screen one Source from a scientific paper for explicit research signals.
Return one compact JSON object. Preserve uncertainty and Source-local meaning.
Do not construct experiments, relationships, findings, or research objectives.
""".strip()


def build_paper_source_signal_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    model_payload, _ = _paper_map_model_payload(payload)
    user_prompt = (
        "TASK MODEL\n"
        "Perform source-local scientific signal screening after paper-scope mapping "
        "could not produce bounded structured output. This is explicit-axis "
        "extraction for later paper-level reconciliation, not relationship "
        "construction, causal interpretation, evidence synthesis, or objective "
        "generation.\n\n"
        "INPUT SCHEMA\n"
        "- The input contains exactly one Source unit from one paper.\n"
        "- Source content is the scientific authority. Document and section metadata "
        "provide provenance and orientation only.\n"
        "- The downstream backend binds Source identity and performs paper-level "
        "reconciliation.\n\n"
        f"Input JSON:\n{json.dumps(model_payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Decide whether the Source explicitly names a changed, compared, or modeled "
        "variable and/or a measured, observed, or predicted outcome.\n"
        "2. Return each explicit research axis as one neutral, concise signal. For a "
        "variable, set variable_role to `varied`, `compared`, or `modeled` only when "
        "this Source establishes that role. Use `fixed` for a controlled setting, "
        "`context` for a generic or background parameter mention, and `uncertain` when "
        "the role cannot be established. Outcome signals use `not_applicable`. An "
        "axis is what was changed or measured, not a value, direction, phase, grain "
        "shape, or other observation on that axis. Group multiple morphology or phase "
        "observations from one characterization result under one outcome such as "
        "microstructure or phase constitution. Keep genuinely different measurements, "
        "such as tensile strength and hardness, as separate outcomes. Do not return an "
        "umbrella outcome and its explicitly named members together.\n"
        "3. Classify whose work the statement describes. Use "
        "claim_scope=current_work only for this paper's own work, synthesis for the "
        "review authors' explicit synthesis, and claim_scope=background for a cited "
        "or named prior study.\n"
        "4. Copy only context explicitly supported by this Source. Use a concise "
        "experiment label when the Source supplies an author name, group label, or "
        "other identity needed to keep studies separate.\n"
        "5. If no explicit scientific axis is present, return signals=[].\n\n"
        "HARD RULES\n"
        "- Do not infer a causal relationship or pair variable and outcome signals.\n"
        "- Do not turn fixed settings, material identity, or test conditions into "
        "variables.\n"
        "- Do not return or copy Source-unit IDs; the backend owns identity and "
        "lineage.\n"
        "- Do not complete missing experiment context from general knowledge.\n"
        "- Open-list words such as 'etc.' or 'including' do not name hidden axes and "
        "must not cause output_saturated=true.\n"
        "- Keep cited studies in reviews separate from the review authors' synthesis "
        "and from this paper's own experiments.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Primary result: 'We varied pressure and measured conversion.' Return a "
        "current_work variable signal 'pressure' with variable_role=`varied` and an "
        "outcome signal 'conversion' with variable_role=`not_applicable`.\n"
        "- Review citation: 'Miranda et al. increased build plate temperature and "
        "reported lower residual stress.' Return background signals with "
        "experiment_label='Miranda et al.'; do not treat them as current_work.\n"
        "- Synthesis: 'Across the reviewed studies, preheating generally reduced "
        "residual stress.' Return synthesis signals only for axes explicitly named.\n"
        "- One characterization axis: 'After three reheats, the CGHAZ contained "
        "equiaxed ferrite, refined ferrite, and scattered lamellar pearlite.' Return "
        "variable='reheating cycles' and outcome='microstructure'; the named "
        "morphologies are observations, not separate outcome axes.\n"
        "- Explicit measurement list: 'IHT enhanced tensile strength, hardness, "
        "ductility, and fatigue.' Return one IHT variable and four distinct outcome "
        "signals; do not also return 'mechanical properties'.\n"
        "- Background only: 'Additive manufacturing is widely used in aerospace.' "
        "Return signals=[].\n"
        "- Fixed versus varied: 'All groups used 25 C while pressure varied from 1 to "
        "3 MPa.' Temperature is `fixed` and pressure is `varied`; only pressure may "
        "later enter a relationship.\n"
        "- Generic list: 'Temperature, pressure, and time can affect conversion. In this "
        "work time was varied.' Temperature and pressure are `context`; time is "
        "`varied`.\n\n"
        "OUTPUT CONTRACT\n"
        "Return doc_role, signals, output_saturated, evidence_density, confidence, and "
        f"warnings. Return at most {_SOURCE_SIGNAL_LIMIT} signals and at most four "
        "values in each context list. Set output_saturated=true only when more than "
        f"{_SOURCE_SIGNAL_LIMIT} distinct explicit "
        "research axes are present; omitted descriptive details do not count as omitted "
        "axes. Return only schema-valid JSON."
    )
    return _SOURCE_SIGNAL_SYSTEM_PROMPT, user_prompt


class PaperResearchMapExtractor:
    """Map supported paper scope from one bounded high-level Source window."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        system_prompt, user_prompt = build_paper_research_map_prompt(payload)
        _, source_units_by_label = _paper_map_model_payload(payload)
        allowed_source_labels_json = json.dumps(
            list(source_units_by_label),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        is_review = (
            isinstance(payload.get("document_profile"), Mapping)
            and str(payload["document_profile"].get("doc_type") or "").strip()
            == "review"
        )

        def build_retry_prompt(repair_detail: str) -> str:
            if is_review:
                return (
                    "Previous review synthesis output was invalid: "
                    f"{repair_detail}. Retain only explicit scientific synthesis "
                    "authored by the review. Return each judgment once inside "
                    "review_synthesis; do not return studies or unresolved_signals. "
                    "Discard reconstructions of individually cited experiments. Copy "
                    "only unique Source labels from the input and return compact "
                    "schema-valid JSON.\n"
                    f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}"
                )
            return (
                "Previous paper-map output was invalid: "
                f"{repair_detail}. Preserve every distinct supported paper-scope "
                "group, relationship, and unresolved signal. Do not reconstruct "
                "samples, tests, comparators, fixed conditions, or factor levels. "
                "Those detailed fields are not part of this output contract. Every "
                "relationship factor requires a factor_assertion with an eligible "
                "paper-stated role and its supporting Source labels. Fixed, contextual, "
                "or uncertain parameters cannot enter relationships. Copy only "
                "unique Source labels from the input, with at most "
                f"{PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT} labels per relationship or signal. "
                f"Keep at most {_PAPER_MAP_VARIED_FACTOR_LIMIT} factor assertions per "
                "relationship. Set output_saturated=true "
                "instead of silently omitting a scientific item. Return only compact "
                "schema-valid JSON.\n"
                f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}"
            )

        def validate_output_contract(response: BaseModel) -> BaseModel | None:
            if not isinstance(
                response,
                (ExperimentalPaperMapModelOutput, ReviewPaperMapModelOutput),
            ):
                raise TypeError("unexpected paper research map response type")
            paper_map = _paper_map_response(response, source_units_by_label)
            source_keys = {
                str(source_unit.get("source_unit_id") or "").strip(): (
                    str(source_unit.get("source_kind") or "").strip(),
                    str(source_unit.get("source_ref") or "").strip(),
                )
                for source_unit in payload.get("source_units") or ()
                if isinstance(source_unit, Mapping)
                and str(source_unit.get("source_unit_id") or "").strip()
            }
            study_identities = [
                study.identity_key(source_keys) for study in paper_map.studies
            ]
            if len(study_identities) != len(set(study_identities)):
                raise ValueError("studies contain duplicate study identities")
            return paper_map

        def complete_json_with_contract(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                build_retry_prompt=build_retry_prompt,
                normalize_response_payload=(
                    _normalize_experimental_paper_map_payload
                    if kwargs.get("response_model") is ExperimentalPaperMapModelOutput
                    else None
                ),
                postprocess_response=validate_output_contract,
                fail_on_output_saturation=True,
            )

        try:
            response_model = _paper_map_response_model(payload)
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                max_completion_tokens=_MAX_COMPLETION_TOKENS,
                json_completion=complete_json_with_contract,
                postprocess_response=validate_output_contract,
                fail_on_output_saturation=True,
                task_type="paper_map",
                prompt_version=PAPER_RESEARCH_MAP_PROMPT_VERSION,
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_map")
            raise
        if not isinstance(response, StructuredPaperResearchMap):
            raise TypeError("unexpected paper research map response type")
        return response

    def extract_source_signals(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        source_units = [
            unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping)
        ]
        if len(source_units) != 1:
            raise ValueError("source signal screening requires exactly one Source unit")
        source_unit_id = str(source_units[0].get("source_unit_id") or "").strip()
        if not source_unit_id:
            raise ValueError("source signal screening requires a Source-unit id")

        system_prompt, user_prompt = build_paper_source_signal_prompt(payload)

        def complete_json_with_contract(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                normalize_response_payload=_normalize_source_signal_screen_payload,
                fail_on_output_saturation=True,
            )

        try:
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=PaperSourceSignalScreenModelOutput,
                max_completion_tokens=_SOURCE_SIGNAL_MAX_COMPLETION_TOKENS,
                json_completion=complete_json_with_contract,
                fail_on_output_saturation=True,
                task_type="paper_source_signal",
                prompt_version=PAPER_SOURCE_SIGNAL_PROMPT_VERSION,
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_source_signal")
            raise
        if not isinstance(response, PaperSourceSignalScreenModelOutput):
            raise TypeError("unexpected paper source signal response type")
        if response.output_saturated:
            self._log_saturation_trace(payload, contract="paper_source_signal")
            raise StructuredOutputSaturatedError(
                "Paper source signal output omitted visible scientific axes"
            )

        return StructuredPaperResearchMap.model_validate(
            {
                "doc_role": response.doc_role,
                "unresolved_signals": [
                    {
                        **signal.model_dump(),
                        "source_unit_ids": [source_unit_id],
                    }
                    for signal in response.signals
                ],
                "evidence_density": response.evidence_density,
                "confidence": response.confidence,
                "warnings": response.warnings,
            }
        )

    def _log_saturation_trace(
        self,
        payload: Mapping[str, Any],
        *,
        contract: str,
    ) -> None:
        source_units = [
            unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping)
        ]
        source_unit_ids = [
            str(unit.get("source_unit_id") or "").strip()
            for unit in source_units
            if str(unit.get("source_unit_id") or "").strip()
        ]
        input_chars = sum(
            self._source_content_chars(unit.get("content"))
            for unit in source_units
        )
        trace = self.response_client.peek_last_trace() or {}
        attempts = []
        for attempt in trace.get("attempts") or ():
            if not isinstance(attempt, Mapping):
                continue
            attempts.append(
                {
                    "attempt": attempt.get("attempt"),
                    "finish_reason": attempt.get("finish_reason"),
                    "response_chars": attempt.get("response_chars"),
                    "response_preview": str(
                        attempt.get("response_preview") or ""
                    )[:1000],
                }
            )
        logger.warning(
            "Paper research map saturation trace contract=%s window_id=%s "
            "source_unit_ids=%s input_chars=%s attempts=%s",
            contract,
            payload.get("window_id"),
            json.dumps(source_unit_ids, ensure_ascii=True, separators=(",", ":")),
            input_chars,
            json.dumps(attempts, ensure_ascii=True, separators=(",", ":")),
        )

    @staticmethod
    def _source_content_chars(content: object) -> int:
        if isinstance(content, str):
            return len(content)
        if content is None:
            return 0
        return len(json.dumps(content, ensure_ascii=False, separators=(",", ":")))

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        """Count the complete repair-capable prompt before model execution."""

        system_prompt, user_prompt = build_paper_research_map_prompt(payload)
        return self.response_client.estimate_prompt_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=_paper_map_response_model(payload),
        )


__all__ = [
    "PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT",
    "PAPER_RESEARCH_MAP_SOURCE_UNIT_LIMIT",
    "PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT",
    "PAPER_SOURCE_SIGNAL_PROMPT_VERSION",
    "PaperResearchMapExtractor",
    "build_paper_research_map_prompt",
    "build_paper_source_signal_prompt",
]
