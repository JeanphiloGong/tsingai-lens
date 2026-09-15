from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel

from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)
from .common import (
    PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    _PAPER_MAP_CONTEXT_LIMIT,
    _PAPER_MAP_STUDY_LIMIT,
    _PAPER_MAP_VARIED_FACTOR_LIMIT,
    _REVIEW_CITATION_LEAD_LIMIT,
    _REVIEW_KNOWLEDGE_ITEM_LIMIT,
    _bounded_mapping_list,
    _mark_bounded_output,
)
from .paper_map_outputs import (
    ExperimentalPaperMapModelOutput,
    ReviewPaperMapModelOutput,
)
from .paper_map_results import StructuredPaperResearchMap

PAPER_RESEARCH_MAP_PROMPT_VERSION = "paper_map.v7"
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
            overflow_count = len(overflows)
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
            if len(overflows) > overflow_count:
                # A truncated joint factor set describes a different study.
                # Omit that relationship, not individual factors within it.
                continue
            normalized_relationships.append(normalized_relationship)
        if relationships and not normalized_relationships:
            continue
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
        "4. Read connected passages together, but preserve a partial variable-only "
        "or outcome-only statement when the review does not establish its link. "
        "Do not borrow an axis from an unrelated statement.\n"
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
        "scope, confidence, and the directly supporting allowed `source_labels`.\n"
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
        "normally inspected after Objective confirmation. A targeted reread can "
        "include relevant Methods or Results passages to clarify missing scope; "
        "it still does not reconstruct experiments.\n\n"
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
        "5. Read the supplied passages together, using their section paths to follow "
        "the paper's argument. A factor and outcome may be stated in different Sources; "
        "link them only when the text establishes the same investigation and its "
        "measured response. Co-occurrence or proximity alone is not a link. "
        "When the Sources explicitly link factors to outcomes, return one "
        "relationship per outcome. Preserve the full jointly varied, compared, or "
        "modeled factor set. A single adopted apparatus or configuration is context, "
        "not a compared factor unless the text describes alternative groups or settings.\n"
        "6. Do not promote causal explanations or intermediate mechanisms introduced "
        "by phrases such as 'attributed to', 'due to', or 'allowing' unless the Source "
        "separately states that they were measured, observed, or predicted outcomes.\n"
        "7. If only one axis is explicit, or an outcome is a broad family such as "
        "microstructure or mechanical properties or combines distinct measurements, "
        "return the explicit axis in `unresolved_signals` instead of inventing a "
        "metric or link. First look across all supplied passages for named observations "
        "or measurements that resolve that family, such as grain morphology, tensile "
        "strength, and elongation. Use those explicit outcomes when linked; do not "
        "replace them with a broad family merely to shorten the output.\n"
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
        "- Copy `source_labels` only from the allowed list, without duplicates.\n"
        "- Return empty arrays rather than guessing unsupported study structure.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Joint factors: temperature and pressure changed together. Return both as "
        "factor_assertions with role=`varied` and return one relationship per outcome.\n"
        "- Explicit configuration comparison: 'We compared PTA-leading versus "
        "laser-leading and front versus rear wire feeding. PTA-leading with front "
        "feeding gave stable deposition and good bead appearance.' Return two relationships with "
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
        "- Distributed scope: S1 says laser power was varied in the current Ti-6Al-4V "
        "experiment. S2 says porosity was measured for those same power groups. Return "
        "laser power -> porosity citing S1 and S2. If S2 instead describes a separate "
        "heat-treatment experiment, do not link it to S1.\n"
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
        "- Apparatus context: 'All specimens used one beam profile. Density varied "
        "with energy input.' Link only energy input to density; the beam profile is "
        "not a varied or compared factor.\n"
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
        f"{_PAPER_MAP_VARIED_FACTOR_LIMIT} factor assertions, and up to 2 "
        "`warnings`, each at most 240 characters. Set output_saturated=true only if a "
        "distinct supported item exceeds these limits.\n\n"
        "BATCH LINEAGE\n"
        f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}\n"
        "Copy labels only from this exact list."
    )
    return _SYSTEM_PROMPT, user_prompt


class PaperResearchMapExtractor:
    """Map supported paper scope from one bounded high-level Source window."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def extract(
        self,
        payload: dict[str, Any],
        *,
        before_request: Callable[[], float] | None = None,
    ) -> StructuredPaperResearchMap:
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
                "unique Source labels from the input. "
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
                **({"before_request": before_request} if before_request else {}),
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_map")
            raise
        if not isinstance(response, StructuredPaperResearchMap):
            raise TypeError("unexpected paper research map response type")
        return response

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
    "PaperResearchMapExtractor",
    "build_paper_research_map_prompt",
]
