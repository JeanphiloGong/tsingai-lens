"""Validate model-authored facts against a primary Source and paper bundle."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from hashlib import sha1, sha256
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from domain.core import ResearchObjective

# Source validation now distinguishes cited background from an unresolved
# current-paper result; invalidate checkpoints from the prior contract.
OBJECTIVE_SOURCE_GROUNDING_VERSION = "objective-source-grounding.v11"

_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_NO_CHANGE_RESULT_KEYS = (
    "no_change",
    "no_significant_change",
    "no_significant_difference",
    "no_statistically_significant_difference",
    "not_significantly_different",
    "not_statistically_different",
    "remained_constant",
    "remained_relatively_unchanged",
    "remained_unchanged",
    "unchanged",
)
_TABLE_CONTINUATION_MARKER = re.compile(
    r"^(?:table|tab\.?)[\s_-]*[A-Za-z0-9][A-Za-z0-9.\-]*"
    r"\s*(?:\(\s*continued\s*\)|continued)$",
    re.IGNORECASE,
)
_OBJECTIVE_ASSOCIATION_RELATION_MARKERS = re.compile(
    r"\b(?:associated|association|correlat(?:e|ed|es|ion)|relationship|"
    r"influence|influenced|effect|effects|impact|sensitivity|dependent|"
    r"sensitive|dependence|compared|comparison|different|varied|varying|as|while|"
    r"with|between|from|higher|lower|improve|improved|improves|improving|"
    r"enhance|enhanced|enhances|enhancing)\b",
    re.IGNORECASE,
)
_OBJECTIVE_INTERVENTION_RELATION_MARKERS = re.compile(
    r"\b(?:effect|effects|influence|influenced|impact|role|dependence|"
    r"relationship|correlation|sensitivity)\b",
    re.IGNORECASE,
)
_OBJECTIVE_OBSERVED_CHANGE_MARKERS = re.compile(
    r"\b(?:increase|increased|increases|increasing|decrease|decreased|"
    r"decreases|decreasing|reduce|reduced|reduces|reducing|change|changed|"
    r"changes|vary|varied|varies|varying|remove|removed|removal|"
    r"eliminate|eliminated|elimination|deplete|depleted|depletion)\b",
    re.IGNORECASE,
)
_OBJECTIVE_MEDIATOR_CAUSE_MARKERS = re.compile(
    r"\b(?:by|due to|because of|after|following|result(?:ed|s)? from|"
    r"as a result of|as|while)\b",
    re.IGNORECASE,
)
_SECONDARY_STUDY_NAMED_ATTRIBUTION = re.compile(
    r"\b(?:[A-Z][\w'’-]*\s+et\s+al\.?|previous|prior|earlier)\b.*?"
    r"\b(?:reported|compared|showed|found|observed|revealed|demonstrated|"
    r"identified|measured|indicated|investigated|studied|concluded)\b|"
    r"\bour\s+(?:prior|previous|earlier)\s+"
    r"(?:study|work|research|investigation|analysis)\b",
    re.IGNORECASE,
)
_SECONDARY_STUDY_PASSIVE_ATTRIBUTION = re.compile(
    r"\b(?:it|this|these)\s+(?:(?:has|have)\s+been\s+|(?:was|were)\s+)?"
    r"(?:previously\s+)?(?:reported|shown|found|observed|demonstrated)\s+that\b",
    re.IGNORECASE,
)
_SECONDARY_STUDY_PRONOUN_REPORT = re.compile(
    r"^\s*they\s+(?:reported|compared|showed|found|observed|revealed|"
    r"demonstrated|identified|measured|indicated|attributed|concluded)\b",
    re.IGNORECASE,
)
_SECONDARY_STUDY_CITED_REPORT = re.compile(
    r"\b(?:it|this|these|which)\s+(?:(?:has|have)\s+been\s+|"
    r"(?:was|were)\s+)?(?:previously\s+)?"
    r"(?:reported|shown|found|observed|demonstrated)\s+"
    r"(?:as|to|that)\b",
    re.IGNORECASE,
)
_SCIENTIFIC_CITATION_MARKER = re.compile(
    r"\[(?:\d+[a-z]?\s*(?:[-,;]\s*\d+[a-z]?\s*)*)\]|"
    r"\((?:[A-Z][\w'’-]+(?:\s+et\s+al\.?)?[^)]*\b(?:19|20)\d{2}[a-z]?)\)",
    re.IGNORECASE,
)
_CURRENT_STUDY_ATTRIBUTION = re.compile(
    r"\b(?:we|this\s+(?:study|work)|the\s+present\s+(?:study|work)|"
    r"current\s+(?:study|work)|our\s+(?:results?|findings?|experiments?|"
    r"measurements?|analysis))\b",
    re.IGNORECASE,
)
_STUDY_INTENT_MARKERS = re.compile(
    r"\b(?:aim|aimed|objective|purpose)\b|"
    r"\b(?:was|were|is|are|has\s+been|have\s+been)\s+"
    r"(?:investigated|examined|evaluated|assessed|analy[sz]ed|studied|"
    r"characteri[sz]ed|measured)\b",
    re.IGNORECASE,
)
_RESULT_OBSERVATION_MARKERS = re.compile(
    r"\b(?:increase|increased|increases|decrease|decreased|decreases|"
    r"reduce|reduced|reduces|improve|improved|improves|enhance|enhanced|"
    r"higher|lower|greater|smaller|more|less|different|difference|"
    r"observed|found|showed|revealed|exhibited|formed|formation|developed|"
    r"seen|resulted|remained|unchanged|similar|correlated|associated)\b|"
    r"[-+]?\d+(?:\.\d+)?\s*(?:%|mpa|gpa|kpa|pa|hv|°?c)\b",
    re.IGNORECASE,
)
_OBJECTIVE_DIRECTION_TERMS = {
    "increase": (
        "increase",
        "increased",
        "increases",
        "increasing",
        "higher",
        "greater",
        "larger",
    ),
    "decrease": (
        "decrease",
        "decreased",
        "decreases",
        "decreasing",
        "lower",
        "reduce",
        "reduced",
        "reduces",
        "reducing",
        "reduction",
        "smaller",
    ),
    "improve": (
        "improve",
        "improved",
        "improves",
        "improving",
        "better",
        "enhance",
        "enhanced",
    ),
    "worsen": (
        "worsen",
        "worsened",
        "worsens",
        "worsening",
        "worse",
        "degrade",
        "degraded",
        "deteriorate",
        "deteriorated",
    ),
    "no_change": (
        "no_change",
        "no_significant_difference",
        "similar",
        "unchanged",
        "remained_constant",
    ),
}


def _source_validation_failure_record(
    *,
    route: EvidenceCandidate,
    errors: tuple[str, ...],
) -> dict[str, Any]:
    """Keep a rejected model draft visible without treating it as science.

    A grounding rejection is a technical extraction failure, not evidence that
    the paper has no result.  Persist a stable, source-linked failed draft so
    the contribution warning and Evidence Map can distinguish the two cases.
    """

    identity = "|".join(
        (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            "source_grounding_failed",
        )
    )
    detail = "; ".join(error.strip() for error in errors if error.strip())
    return {
        "evidence_id": (
            f"oev_grounding_failed_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        ),
        "objective_id": route.objective_id,
        "document_id": route.document_id,
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "evidence_role": "irrelevant",
        "selection_status": "failed",
        "selection_reason": (
            "Model-authored fields failed deterministic Source grounding; "
            "the Source remains available for review or retry."
        ),
        "attribution_scope": "not_attributable",
        "scientific_context": {},
        "source_refs": [
            {
                "source_kind": route.source_kind,
                "source_ref": route.source_ref,
            }
        ],
        "resolution_status": "unknown",
        "failure_reason": (
            "Source grounding failed: "
            f"{detail or 'model output was not supported by the Source.'}"
        )[:1000],
        "confidence": 0.0,
    }


def _objective_table_matrix_rows(
    source: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[tuple[int, tuple[str, ...]], ...]]:
    headers = tuple(
        str(header).strip()
        for header in source.get("column_headers", ())
        if str(header).strip()
    )
    matrix = tuple(
        tuple(str(cell).strip() for cell in row)
        for row in source.get("table_matrix", ())
        if isinstance(row, (list, tuple))
    )
    if not headers or not matrix:
        return (), ()
    # Docling can expose a repeated continuation header as an additional
    # header row.  Honor the source's declared header depth first, then fall
    # back to the legacy first-row check for artifacts produced before that
    # field was persisted.
    header_depth_is_declared = "header_row_count" in source
    try:
        header_row_count = int(source.get("header_row_count", 1) or 0)
    except (TypeError, ValueError):
        header_row_count = 1
    header_row_count = max(0, min(header_row_count, len(matrix)))
    if (
        not header_depth_is_declared
        and header_row_count == 1
        and not _objective_row_matches_headers(
            matrix[0], headers
        )
    ):
        # Some legacy rows have no explicit header row despite the default
        # metadata value.  Preserve the old behavior for those artifacts.
        header_row_count = 0
    elif header_row_count <= 0 and _objective_row_matches_headers(matrix[0], headers):
        header_row_count = 1
    candidate_rows = matrix[header_row_count:]
    filtered_rows = tuple(
        row
        for row in candidate_rows
        if any(cell for cell in row)
        and not _objective_table_matrix_continuation_header_row(
            headers=headers,
            row=row,
        )
    )
    data_rows = tuple(
        (row_index, row) for row_index, row in enumerate(filtered_rows, start=1)
    )
    return headers, data_rows


def _objective_table_matrix_continuation_header_row(
    *,
    headers: tuple[str, ...],
    row: tuple[str, ...],
) -> bool:
    if not headers or not row:
        return False
    nonempty_cells = tuple(str(cell).strip() for cell in row if str(cell).strip())
    if nonempty_cells and all(
        _TABLE_CONTINUATION_MARKER.fullmatch(cell) for cell in nonempty_cells
    ):
        return True
    first_header_key = _objective_column_key(headers[0])
    if first_header_key not in {"sample", "sample_id", "sample_number"}:
        return False
    first_cell = str(row[0] if row else "").strip()
    matches_header = _objective_column_key(first_cell) == first_header_key
    continues_header = not first_cell and any(str(cell).strip() for cell in row[1:])
    return matches_header or continues_header


def _objective_row_matches_headers(
    row: tuple[str, ...],
    headers: tuple[str, ...],
) -> bool:
    return tuple(
        _objective_column_key(value) for value in row[: len(headers)]
    ) == tuple(_objective_column_key(value) for value in headers)


def _objective_table_row_values(
    *,
    headers: tuple[str, ...],
    row: tuple[str, ...],
) -> dict[str, str]:
    return {
        header: row[index]
        for index, header in enumerate(headers)
        if index < len(row) and row[index] not in (None, "")
    }


def validate_source_fact(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
    extracted_record: dict[str, Any],
    candidate_variables: tuple[str, ...] = (),
    grounding_sources: tuple[Mapping[str, Any], ...] = (),
    grounding_source_refs: tuple[Mapping[str, Any], ...] = (),
) -> tuple[dict[str, Any], ...]:
    # A result is often split across Results and Methods in the same paper.
    # The result Source remains authoritative for measured values and wording;
    # the bundle is allowed to ground conditions and comparison endpoints.
    grounding_source = _objective_source_with_grounding_sources(
        source,
        grounding_sources,
    )
    record = _objective_complete_extracted_variable_endpoints(
        extracted_record,
        source=grounding_source,
    )
    record = _objective_remove_observed_mediator_variables(record)
    record = _objective_remove_unattributed_objective_variables(
        record,
        source=grounding_source,
        objective_context=objective_context,
    )
    record = _objective_retain_source_grounded_context(
        record,
        source=grounding_source,
    )
    record = _objective_normalize_explicit_no_change_direction(record)
    reported_result = record.get("reported_result")
    if isinstance(reported_result, Mapping):
        normalized_result = dict(reported_result)
        normalized_result = _objective_reanchor_result_text(
            normalized_result,
            source=source,
            source_text=_objective_source_grounding_text(source),
            objective_context=objective_context,
        )
        result_value = normalized_result.get("value")
        direction = str(normalized_result.get("direction") or "unknown")
        result_text = (
            f"_{_objective_column_key(result_value)}_"
            f"{_objective_column_key(normalized_result.get('result_text'))}_"
        )
        direction_terms = _OBJECTIVE_DIRECTION_TERMS
        explicit_directions = [
            candidate_direction
            for candidate_direction, terms in direction_terms.items()
            if any(f"_{term}_" in result_text for term in terms)
        ]
        if direction == "unknown":
            result_text_value = str(normalized_result.get("result_text") or "")
            outcome_value = str(normalized_result.get("outcome") or "")
            result_direction = None
            if not _objective_result_is_non_directional_relation(
                result_text=result_text_value,
                outcome=outcome_value,
            ):
                result_direction = _objective_result_direction_near_outcome(
                    result_text=result_text_value,
                    outcome=outcome_value,
                    direction_terms=direction_terms,
                )
            if result_direction is not None:
                direction = result_direction
            elif len(explicit_directions) == 1:
                direction = explicit_directions[0]
            normalized_result["direction"] = direction
        if (
            not _NUMBER_PATTERN.search(str(result_value or ""))
            and direction in direction_terms
            and not any(
                f"_{term}_" in result_text for term in direction_terms[direction]
            )
        ):
            normalized_result["direction"] = "unknown"
        record["reported_result"] = normalized_result
        reported_result = normalized_result
        record = _objective_retain_outcome_applicable_test_context(record)
    if not isinstance(reported_result, Mapping):
        record["changed_variables"] = []
        record["comparison"] = None
    if isinstance(reported_result, Mapping):
        source_text = _objective_source_grounding_text(source)
        if (
            source.get("source_kind") == "text_window"
            and _objective_result_is_attributed_to_secondary_study(
                result_text=str(reported_result.get("result_text") or ""),
                source_text=source_text,
            )
        ):
            # The Source was inspected successfully, but the model transcribed
            # another study's result. It is neither a technical failure nor
            # Evidence from the current paper.
            return ()
        if _objective_result_text_is_study_intent_only(
            str(reported_result.get("result_text") or "")
        ):
            return ()
        result_grounding_errors = _objective_evidence_result_grounding_errors(
            record,
            source=source,
            source_text=source_text,
            objective_context=objective_context,
        )
        if result_grounding_errors:
            return (
                _source_validation_failure_record(
                    route=route,
                    errors=result_grounding_errors,
                ),
            )
        inferred_association_variable = _objective_source_association_variable(
            record,
            source=source,
            source_text=source_text,
            objective_context=objective_context,
            candidate_variables=candidate_variables,
        )
        explicit_association_variables = _objective_explicit_association_variables(
            record,
            source=source,
            source_text=source_text,
            objective_context=objective_context,
        )
        if inferred_association_variable is not None:
            record["changed_variables"] = [
                {
                    "name": inferred_association_variable,
                    "baseline_value": None,
                    "target_value": None,
                    "unit": None,
                }
            ]
            comparison = record.get("comparison")
            if not isinstance(comparison, Mapping) or comparison.get("comparable") is False:
                record["comparison"] = None
            record["attribution_scope"] = "association_only"
            record["resolution_status"] = "partial"
            record["selection_reason"] = (
                "Source explicitly names one Objective variable theme but does not "
                "provide complete comparison endpoints; retained as an association."
            )
        elif explicit_association_variables:
            record["attribution_scope"] = "association_only"
            record["resolution_status"] = "partial"
            record["selection_reason"] = (
                "Source explicitly links the reported outcome to the Objective "
                "variable, but does not provide complete comparison endpoints; "
                "retained as an association."
            )
        # An association variable is a canonical Objective theme inferred from
        # an explicitly named Source intervention (for example, "scanning
        # strategies" -> "laser exposure condition").  Its canonical name is
        # intentionally not required to occur verbatim in the Source, and its
        # endpoints remain empty until a later source supplies them.
        variable_grounding_errors = (
            ()
            if inferred_association_variable is not None
            else _objective_evidence_variable_grounding_errors(
                record,
                source=grounding_source,
                source_text=_objective_source_grounding_text(grounding_source),
                allow_missing_endpoints=bool(explicit_association_variables),
            )
        )
        comparison_grounding_errors = _objective_evidence_comparison_grounding_errors(
            record,
            source_text=_objective_source_grounding_text(grounding_source),
        )
        if (
            not variable_grounding_errors
            and not comparison_grounding_errors
            and inferred_association_variable is None
            and source.get("source_kind") == "table"
            and source.get("table_matrix")
            and not _objective_extracted_table_result_is_row_grounded(
                record,
                source=source,
            )
        ):
            record["changed_variables"] = []
            record["comparison"] = None
            record["attribution_scope"] = "descriptive_only"
            record["resolution_status"] = "partial"
            record["selection_reason"] = (
                "The result is grounded in this table, but its value cannot be "
                "bound deterministically to the reported comparison rows."
            )
        if variable_grounding_errors or comparison_grounding_errors:
            record["changed_variables"] = []
            record["resolution_status"] = "partial"
            if comparison_grounding_errors:
                record["comparison"] = None
                record["attribution_scope"] = "descriptive_only"
                record["selection_reason"] = (
                    "Grounded result retained without a source-grounded "
                    "comparison binding."
                )
            else:
                comparison = record.get("comparison")
                record["attribution_scope"] = (
                    "association_only"
                    if isinstance(comparison, Mapping)
                    and comparison.get("comparable") is True
                    else "not_attributable"
                )
                record["selection_reason"] = (
                    "Grounded result retained pending same-study process "
                    "context binding."
                )
        outcome = property_matching.normalize_source_defined_objective_property(
            reported_result.get("outcome"),
            source_text=source_text,
            objective_context=objective_context,
        )
        if not outcome:
            return ()
        normalized_result = dict(reported_result)
        normalized_result["outcome"] = outcome
        record["reported_result"] = normalized_result
        if (
            objective_context is not None
            and objective_context.outcomes
            and not property_matching.outcome_matches_objective_scope(
                outcome,
                objective_context.outcomes,
            )
        ):
            source_bound_outcome = _objective_result_text_unique_outcome(
                str(normalized_result.get("result_text") or "").strip(),
                objective_context,
            )
            if source_bound_outcome is not None:
                normalized_result["outcome"] = source_bound_outcome
                record["reported_result"] = normalized_result
                outcome = source_bound_outcome
            else:
                # A researcher records a reported result even when it answers
                # a neighboring question. Keep the source-backed fact in the
                # Evidence Bundle for audit and future objective formation, but
                # do not let this Objective treat it as a comparable result.
                record["comparison"] = None
                record["attribution_scope"] = "descriptive_only"
                record["selection_reason"] = (
                    "Source-backed result retained for audit, but its outcome is "
                    "outside the confirmed Objective outcome scope; excluded from "
                    "Finding comparison."
                )
    else:
        scientific_context = record.get("scientific_context")
        if not isinstance(scientific_context, Mapping) or not any(
            scientific_context.get(group)
            for group in ("material", "sample", "process", "test")
        ):
            return ()
        if (
            source.get("source_kind") == "text_window"
            and _objective_source_is_secondary_only_target_context(
                source_text=_objective_source_grounding_text(source),
                objective_context=objective_context,
            )
        ):
            record["evidence_role"] = "background_context"
            background_context: dict[str, list[dict[str, Any]]] = {}
            for group in ("material", "sample", "process", "test"):
                background_context[group] = [
                    {**dict(attribute), "context_scope": "background"}
                    for attribute in scientific_context.get(group, ())
                    if isinstance(attribute, Mapping)
                ]
            record["scientific_context"] = background_context
    supported_fields = list(
        _objective_primary_source_supported_fields(record, source=source)
    )
    record.update(
        {
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_refs": _objective_route_source_refs(
                route=route,
                source=source,
                source_excerpt=(
                    _objective_source_grounding_text(source)
                    if source.get("source_kind") == "text_window"
                    and isinstance(record.get("reported_result"), Mapping)
                    and not isinstance(record.get("comparison"), Mapping)
                    else None
                ),
                supports=tuple(supported_fields),
            ),
        }
    )
    if grounding_source_refs:
        source_refs = list(record["source_refs"])
        seen_refs = {
            (item.get("source_kind"), item.get("source_ref"))
            for item in source_refs
            if isinstance(item, Mapping)
        }
        for ref in grounding_source_refs:
            source_ref = str(ref.get("source_ref") or "").strip()
            source_kind = str(ref.get("source_kind") or "").strip()
            if not source_ref or not source_kind:
                continue
            key = (source_kind, source_ref)
            if key in seen_refs:
                continue
            context_ref = dict(ref)
            source_refs.append(context_ref)
            seen_refs.add(key)
        record["source_refs"] = source_refs
    if record.get("confidence") is None:
        record["confidence"] = route.confidence
    return (record,)


def _objective_source_with_grounding_sources(
    source: Mapping[str, Any],
    grounding_sources: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Build a same-paper grounding view without changing the primary Source.

    This view is intentionally text-only for context Sources. It is used for
    process/material/sample/test fields and never for reported-result checks.
    Keeping the primary table matrix and headers intact preserves table row
    validation while allowing a Results paragraph to bind to Methods facts.
    """

    merged = dict(source)
    context_texts = [
        _objective_source_grounding_text(context)
        for context in grounding_sources
        if context is not source
    ]
    context_texts = [text for text in context_texts if text]
    if context_texts:
        primary_text = str(merged.get("text") or "").strip()
        merged["text"] = "\n".join((primary_text, *context_texts)).strip()
    return merged


def _objective_source_sentences(text: str) -> tuple[str, ...]:
    """Return bounded prose units for source-local role checks.

    Association recovery must not treat every fact in a paper-sized Source as
    one claim. Sentence-sized units are the smallest useful boundary available
    here; tables and captions remain intact because they are handled by their
    dedicated grounding paths.
    """

    return tuple(
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
        if sentence.strip()
    )


def _objective_reanchor_result_text(
    result: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
    objective_context: ResearchObjective | None,
) -> dict[str, Any]:
    """Keep a reported result excerpt tied to its own outcome clause.

    Model output may copy a direction from one sentence and an outcome label
    from another sentence in the same paragraph.  Whole-Source substring
    grounding accepts that combination even though a researcher would not call
    it one result.  For prose, recover the smallest adjacent sentence span that
    contains the reported outcome and a source-named Objective variable.  The
    span remains verbatim Source text; no scientific wording is generated.
    """

    normalized = dict(result)
    if (
        not objective_context
        or not objective_context.outcomes
        or str(source.get("source_kind") or "") != "text_window"
    ):
        return normalized
    result_text = str(normalized.get("result_text") or "").strip()
    outcome = str(normalized.get("outcome") or "").strip()
    if not result_text or not outcome:
        return normalized
    if property_matching.source_text_mentions_axis(result_text, outcome):
        return normalized

    variables = tuple(str(item).strip() for item in objective_context.variables if str(item).strip())
    sentences = _objective_source_sentences(source_text)
    candidates: list[tuple[int, int, int, str]] = []
    for index, sentence in enumerate(sentences):
        if not property_matching.source_text_mentions_axis(sentence, outcome):
            continue
        spans = ((index, index),)
        if index > 0:
            spans += ((index - 1, index),)
        if index + 1 < len(sentences):
            spans += ((index, index + 1),)
        for start, end in spans:
            span = " ".join(sentences[start : end + 1]).strip()
            variable_match = any(
                property_matching.source_text_mentions_objective_variable(span, variable)
                for variable in variables
            )
            relationship_match = bool(
                _OBJECTIVE_ASSOCIATION_RELATION_MARKERS.search(span)
            )
            if not variable_match or not relationship_match:
                continue
            # Prefer the shortest source-local span, then one with both target
            # axes in the same sentence, then the earliest occurrence.
            same_sentence_match = any(
                property_matching.source_text_mentions_objective_variable(
                    sentence,
                    variable,
                )
                for variable in variables
            )
            same_sentence_bonus = 0 if same_sentence_match else 1
            candidates.append((end - start, same_sentence_bonus, start, span))
    if not candidates:
        return normalized
    _span_size, _same_sentence_bonus, _start, selected = min(candidates)
    normalized["result_text"] = selected
    # A direction inferred from the discarded clause is no longer trustworthy.
    # Recompute it later from the reanchored text; if no direction is stated,
    # the existing validation path will preserve ``unknown``.
    normalized["direction"] = "unknown"
    return normalized


def _objective_result_is_attributed_to_secondary_study(
    *,
    result_text: str,
    source_text: str,
) -> bool:
    """Identify a cited study as the owner of one extracted result statement.

    A Source block can mix cited literature and current-work prose, so the
    decision is made around the sentence containing the extracted result, not
    from the whole paragraph. Pronoun-led reports inherit attribution only
    from the immediately preceding named-study sentence.
    """

    result_key = _objective_column_key(result_text)
    if not result_key:
        return False
    sentences = _objective_source_sentences(source_text)
    for index, sentence in enumerate(sentences):
        sentence_key = _objective_column_key(sentence)
        if not sentence_key or result_key not in sentence_key:
            continue
        if _CURRENT_STUDY_ATTRIBUTION.search(sentence):
            return False
        if (
            _SECONDARY_STUDY_PASSIVE_ATTRIBUTION.search(sentence)
            or _SECONDARY_STUDY_NAMED_ATTRIBUTION.search(sentence)
        ):
            return True
        if _SECONDARY_STUDY_PRONOUN_REPORT.search(sentence) and index > 0:
            # Sentence tokenizers commonly split the abbreviation in
            # ``et al. [12] investigated ...``. Rejoin a bounded attribution
            # prefix without widening the scientific claim boundary.
            attribution_prefix = " ".join(sentences[max(0, index - 2) : index])
            if _SECONDARY_STUDY_NAMED_ATTRIBUTION.search(attribution_prefix):
                return True
    return False


def _objective_result_text_is_study_intent_only(result_text: str) -> bool:
    """Distinguish a study action from an observed scientific result."""

    text = str(result_text or "").strip()
    return bool(
        text
        and _STUDY_INTENT_MARKERS.search(text)
        and not _RESULT_OBSERVATION_MARKERS.search(text)
    )


def _objective_source_is_secondary_only_target_context(
    *,
    source_text: str,
    objective_context: ResearchObjective | None,
) -> bool:
    """Return true only when every target-outcome claim is explicitly secondary.

    This gate prevents cited background from becoming current-experiment
    context while preserving mixed paragraphs and ordinary Results prose for
    further reading. PDF sentence splitting may separate ``et al.``, a citation,
    and its report; attribution therefore carries across that bounded sequence.
    """

    text = str(source_text or "").strip()
    if not text or objective_context is None or not objective_context.outcomes:
        return False
    if _CURRENT_STUDY_ATTRIBUTION.search(text):
        return False
    sentences = _objective_source_sentences(text)
    target_seen = False
    secondary_attribution_active = False
    for index, sentence in enumerate(sentences):
        attribution_window = " ".join(sentences[max(0, index - 1) : index + 1])
        named_secondary = bool(
            _SECONDARY_STUDY_NAMED_ATTRIBUTION.search(attribution_window)
        )
        passive_secondary = bool(
            _SECONDARY_STUDY_PASSIVE_ATTRIBUTION.search(sentence)
        )
        if named_secondary or passive_secondary:
            secondary_attribution_active = True

        is_target_sentence = any(
            property_matching.source_text_mentions_axis(sentence, outcome)
            for outcome in objective_context.outcomes
        )
        if not is_target_sentence:
            continue
        target_seen = True
        nearby_text = " ".join(
            sentences[max(0, index - 1) : min(len(sentences), index + 2)]
        )
        is_secondary = (
            named_secondary
            or passive_secondary
            or (
                bool(_SECONDARY_STUDY_PRONOUN_REPORT.search(sentence))
                and secondary_attribution_active
            )
            or (
                bool(_SECONDARY_STUDY_CITED_REPORT.search(sentence))
                and bool(_SCIENTIFIC_CITATION_MARKER.search(nearby_text))
            )
        )
        if not is_secondary:
            return False
    return target_seen


def _objective_variable_is_observed_mediator(
    text: str,
    variable: str,
    outcome: str | None = None,
) -> bool:
    """Detect a variable described as an observed change caused by another factor.

    For example, in ``porosity decreased by preheating`` porosity is an
    observed mediator, not the intervention in a ``porosity -> elongation``
    Objective. This is deliberately lexical and conservative: uncertain cases
    remain descriptive instead of being promoted to an attributable result.
    """

    normalized_variable = property_matching.normalize_property_label(variable)
    variable_terms = tuple(
        dict.fromkeys(
            term
            for term in (
                str(variable or "").strip(),
                normalized_variable or "",
            )
            if term
        )
    )
    lowered = str(text or "").casefold()
    for term in variable_terms:
        term_pattern = re.escape(term.casefold()).replace(r"\ ", r"\s+")
        pattern = re.compile(
            rf"\b{term_pattern}\b.{{0,80}}?"
            rf"{_OBJECTIVE_OBSERVED_CHANGE_MARKERS.pattern}.{{0,50}}?"
            rf"(?P<cause>{_OBJECTIVE_MEDIATOR_CAUSE_MARKERS.pattern})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(lowered):
            if match.group("cause") == "by":
                connector_prefix = lowered[max(0, match.start("cause") - 24) : match.start("cause")]
                if re.search(
                    r"\b(?:measured|tested|assessed|evaluated|characterized|determined)\s*$",
                    connector_prefix,
                ):
                    continue
            if outcome:
                cause_tail = lowered[match.end() :].split(",", 1)[0]
                cause_tail = re.split(r"\bwhile\b", cause_tail, maxsplit=1)[0]
                if property_matching.source_text_mentions_axis(cause_tail, outcome):
                    continue
            return True
        # Papers often phrase a mediated change as "the removal of X" or
        # "the reduction of X", placing the observed variable after the
        # change marker. Require a nearby causal verb so a plain noun phrase
        # such as "porosity removal" is not treated as an intervention.
        phrase_pattern = re.compile(
            rf"\b(?:removal|elimination|reduction|depletion)\s+of\s+"
            rf"{term_pattern}\b",
            re.IGNORECASE,
        )
        for sentence in _objective_source_sentences(text):
            if not phrase_pattern.search(sentence):
                continue
            if re.search(
                r"\b(?:induced|caused|promoted|led\s+to|due\s+to|after|"
                r"following|through|by)\b",
                sentence,
                re.IGNORECASE,
            ):
                return True
    return False


def _objective_source_explicitly_links_variable_to_result(
    *,
    variable: str,
    outcome: str,
    result_text: str,
    source_text: str,
    source: Mapping[str, Any] | None = None,
) -> bool:
    """Require source-local language before recovering a missing variable.

    A result sentence that names the factor can support an association when it
    contains relationship language. If the result sentence only names the
    outcome, a separate Source sentence is accepted only for an explicit
    ``effect/influence/impact of X on Y`` style statement. This prevents
    unrelated Methods or mechanism sentences from closing an attribution gap.
    """

    outcome_text = str(outcome or "").strip()
    result = str(result_text or "").strip()
    source_prose = str(source_text or "").strip()
    if not outcome_text or not source_prose:
        return False

    if source is not None and source.get("source_kind") == "table":
        headers = tuple(
            str(header).strip()
            for header in source.get("column_headers", ())
            if str(header).strip()
        )
        variable_header = any(
            property_matching.source_text_mentions_objective_variable(
                header,
                variable,
            )
            for header in headers
        )
        outcome_header = any(
            property_matching.source_text_mentions_axis(header, outcome)
            for header in headers
        )
        if variable_header and outcome_header:
            return True

    result_mentions_variable = property_matching.source_text_mentions_objective_variable(
        result,
        variable,
    )
    if result_mentions_variable:
        if _objective_variable_is_observed_mediator(
            result,
            variable,
            outcome=outcome_text,
        ):
            return False
        return bool(_OBJECTIVE_ASSOCIATION_RELATION_MARKERS.search(result))

    for sentence in _objective_source_sentences(source_prose):
        if not property_matching.source_text_mentions_objective_variable(
            sentence,
            variable,
        ) or not property_matching.source_text_mentions_axis(sentence, outcome):
            continue
        if _objective_variable_is_observed_mediator(
            sentence,
            variable,
            outcome=outcome_text,
        ):
            continue
        if not _OBJECTIVE_INTERVENTION_RELATION_MARKERS.search(sentence):
            continue
        # In ``effect of preheating on porosity`` the Objective variable is the
        # observed target, not the intervention. Reject that orientation when a
        # source-local label is available verbatim.
        variable_key = property_matching.normalize_property_label(variable)
        if variable_key:
            variable_pattern = re.escape(variable_key).replace("\\ ", "\\s+")
            target_pattern = re.compile(
                rf"\bon\s+(?:the\s+)?{variable_pattern}\b",
                re.IGNORECASE,
            )
            if target_pattern.search(sentence):
                continue
        return True
    return False


def _objective_remove_observed_mediator_variables(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove model-labelled variables that SOURCE presents as observations.

    Model output is a candidate transcription, not a scientific authority. A
    complete-looking endpoint pair can still describe a measured mediator (for
    example, porosity changing after preheating). Drop only that variable and
    keep any remaining explicit intervention variables in the same extraction.
    """

    normalized = dict(record)
    variables = normalized.get("changed_variables")
    result = normalized.get("reported_result")
    if not isinstance(variables, list) or not isinstance(result, Mapping):
        return normalized
    result_text = str(result.get("result_text") or "").strip()
    outcome = str(result.get("outcome") or "").strip()
    if not result_text or not outcome:
        return normalized
    retained: list[Any] = []
    removed_names: list[str] = []
    for variable in variables:
        if not isinstance(variable, Mapping):
            retained.append(variable)
            continue
        name = str(variable.get("name") or "").strip()
        if name and _objective_variable_is_observed_mediator(
            result_text,
            name,
            outcome=outcome,
        ):
            removed_names.append(name)
            continue
        retained.append(variable)
    if not removed_names:
        return normalized

    normalized["changed_variables"] = retained
    comparison = normalized.get("comparison")
    if isinstance(comparison, Mapping):
        remaining_names = {
            str(variable.get("name") or "").strip().casefold()
            for variable in retained
            if isinstance(variable, Mapping) and str(variable.get("name") or "").strip()
        }
        normalized_comparison = dict(comparison)
        axes = comparison.get("axis_names")
        if isinstance(axes, list):
            normalized_comparison["axis_names"] = [
                axis
                for axis in axes
                if str(axis).strip().casefold() in remaining_names
            ]
        if not normalized_comparison.get("axis_names"):
            normalized["comparison"] = None
        else:
            normalized["comparison"] = normalized_comparison
    remaining_comparison = normalized.get("comparison")
    if retained and isinstance(remaining_comparison, Mapping):
        normalized["attribution_scope"] = (
            "association_only"
            if remaining_comparison.get("comparable") is True
            else "not_attributable"
        )
    else:
        normalized["attribution_scope"] = "descriptive_only"
    normalized["resolution_status"] = "partial"
    normalized["selection_reason"] = (
        "SOURCE describes the removed Objective variable as an observed "
        "mediator caused by another factor; the result is retained without "
        "attributing it to that mediator."
    )
    return normalized


def _objective_remove_unattributed_objective_variables(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    objective_context: ResearchObjective | None,
) -> dict[str, Any]:
    """Keep Objective factors only when SOURCE establishes their role.

    A result Source may mention an Objective property as an intermediate state
    while reporting an intervention's effect (for example, treatment reduced
    porosity and improved elongation). A model can copy that property into
    ``changed_variables`` even though the paper never compares porosity as the
    intervention. Preserve the reported result for audit, but remove the
    unsupported factor so it cannot become a misleading Finding.
    """

    normalized = dict(record)
    variables = normalized.get("changed_variables")
    result = normalized.get("reported_result")
    if (
        not isinstance(variables, list)
        or not variables
        or not isinstance(result, Mapping)
        or objective_context is None
    ):
        return normalized

    result_text = str(result.get("result_text") or "").strip()
    outcome = str(result.get("outcome") or "").strip()
    source_text = _objective_source_grounding_text(source)
    if not result_text or not outcome or not source_text:
        return normalized

    objective_variables = tuple(objective_context.variables)
    retained: list[Any] = []
    removed_names: list[str] = []
    for variable in variables:
        if not isinstance(variable, Mapping):
            retained.append(variable)
            continue
        name = str(variable.get("name") or "").strip()
        is_objective_variable = any(
            property_matching.variable_matches_objective_scope(name, candidate)
            or property_matching.process_axis_matches_objective_scope(name, candidate)
            for candidate in objective_variables
        )
        if (
            name
            and is_objective_variable
            and (
                _objective_variable_is_observed_mediator(
                    result_text,
                    name,
                    outcome=outcome,
                )
                or _objective_variable_is_observed_mediator(
                    source_text,
                    name,
                    outcome=outcome,
                )
            )
            and not _objective_source_explicitly_links_variable_to_result(
                variable=name,
                outcome=outcome,
                result_text=result_text,
                source_text=source_text,
                source=source,
            )
        ):
            removed_names.append(name)
            continue
        retained.append(variable)

    if not removed_names:
        return normalized

    normalized["changed_variables"] = retained
    comparison = normalized.get("comparison")
    if isinstance(comparison, Mapping):
        remaining_names = {
            str(variable.get("name") or "").strip().casefold()
            for variable in retained
            if isinstance(variable, Mapping) and str(variable.get("name") or "").strip()
        }
        normalized_comparison = dict(comparison)
        axes = comparison.get("axis_names")
        if isinstance(axes, list):
            normalized_comparison["axis_names"] = [
                axis
                for axis in axes
                if str(axis).strip().casefold() in remaining_names
            ]
        normalized["comparison"] = (
            normalized_comparison
            if normalized_comparison.get("axis_names")
            else None
        )

    if not retained or normalized.get("comparison") is None:
        normalized["attribution_scope"] = "descriptive_only"
    elif normalized["comparison"].get("comparable") is True:
        normalized["attribution_scope"] = "association_only"
    else:
        normalized["attribution_scope"] = "not_attributable"
    normalized["resolution_status"] = "partial"
    normalized["selection_reason"] = (
        "SOURCE mentions the Objective variable as an intermediate or context "
        "fact but does not establish it as the compared intervention; the "
        "reported result is retained without attributing it to that variable."
    )
    return normalized


def _objective_source_association_variable(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
    objective_context: ResearchObjective | None,
    candidate_variables: tuple[str, ...] = (),
) -> str | None:
    """Recover one explicit Objective variable without inventing endpoints."""

    if objective_context is None or record.get("changed_variables"):
        return None
    if not isinstance(record.get("reported_result"), Mapping):
        return None
    comparison = record.get("comparison")
    result_text = str(
        record["reported_result"].get("result_text") or ""
    ).strip()
    result_outcome = str(
        record["reported_result"].get("outcome") or ""
    ).strip()
    # If the result sentence omits the Objective variable and the same-paper
    # bundle only describes that variable as a treatment-mediated observation,
    # do not recover it from a broad document-level mention.  Otherwise a
    # sentence such as "heat treatment improved elongation" can be paired with
    # "heat treatment removed porosity" and misreported as a porosity effect.
    # When the result sentence names the variable itself, its local relation
    # check below is authoritative; an upstream mediator mention must not mask
    # that explicit observation.
    if result_text and objective_context.variables:
        for variable in objective_context.variables:
            if property_matching.source_text_mentions_objective_variable(
                result_text,
                variable,
            ):
                continue
            if _objective_variable_is_observed_mediator(
                source_text,
                variable,
                outcome=result_outcome,
            ):
                return None
    if isinstance(comparison, Mapping) and comparison.get("comparable") is False:
        # An unresolved pair still carries a real scientific observation when
        # the result sentence explicitly names the Objective variable. Keep
        # that observation as an association, but do not infer endpoints from
        # opaque paper-local labels such as S1/S2 or alpha/beta.
        explicit_result_variables = tuple(
            dict.fromkeys(
                variable
                for variable in (
                    *candidate_variables,
                    *objective_context.variables,
                )
                if property_matching.source_text_mentions_axis(
                    result_text,
                    variable,
                )
            )
        )
        explicit_result_variables = tuple(
            variable
            for variable in explicit_result_variables
            if _objective_source_explicitly_links_variable_to_result(
                variable=variable,
                outcome=result_outcome,
                result_text=result_text,
                source_text=source_text,
                source=source,
            )
        )
        if not explicit_result_variables:
            return None
    # A comparison can use source-local group labels (for example, Sample S1
    # and Sample S2) while the result sentence still names the actual Objective
    # factor (for example, medium and high VED).  The group labels do not justify
    # a variable by themselves; only one explicit Source match may restore it.
    frame_candidates = tuple(
        dict.fromkeys(
            str(variable).strip()
            for variable in candidate_variables
            if str(variable).strip()
        )
    )
    result_candidates = tuple(
        variable
        for variable in frame_candidates
        if property_matching.source_text_mentions_axis(result_text, variable)
        and _objective_source_explicitly_links_variable_to_result(
            variable=variable,
            outcome=result_outcome,
            result_text=result_text,
            source_text=source_text,
            source=source,
        )
    )
    if len(result_candidates) == 1:
        return result_candidates[0]
    if len(result_candidates) > 1:
        return None
    source_candidates = tuple(
        variable
        for variable in frame_candidates
        if property_matching.source_text_mentions_axis(source_text, variable)
        and _objective_source_explicitly_links_variable_to_result(
            variable=variable,
            outcome=result_outcome,
            result_text=result_text,
            source_text=source_text,
            source=source,
        )
    )
    if len(source_candidates) == 1:
        return source_candidates[0]
    if len(source_candidates) > 1:
        return None
    matches = tuple(
        variable
        for variable in objective_context.variables
        if property_matching.source_text_mentions_objective_variable(
            source_text,
            variable,
        )
        and _objective_source_explicitly_links_variable_to_result(
            variable=variable,
            outcome=result_outcome,
            result_text=result_text,
            source_text=source_text,
            source=source,
        )
    )
    return matches[0] if len(matches) == 1 else None


def _objective_explicit_association_variables(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
    objective_context: ResearchObjective | None,
) -> tuple[Mapping[str, Any], ...]:
    """Keep source-named relation variables when only endpoints are missing.

    A model may return a variable with null endpoints after reading an explicit
    qualitative relation such as ``ductility was sensitive to porosity``. The
    missing endpoints limit the claim to an association, but they do not erase
    the source-backed variable. Preserve the full candidate only when every
    variable is named and linked to the reported outcome by this Source.
    """

    if objective_context is None or not isinstance(record.get("reported_result"), Mapping):
        return ()
    variables = tuple(
        variable
        for variable in record.get("changed_variables") or ()
        if isinstance(variable, Mapping)
    )
    if not variables or any(
        variable.get("baseline_value") not in (None, "")
        or variable.get("target_value") not in (None, "")
        for variable in variables
    ):
        return ()
    reported_result = record["reported_result"]
    outcome = str(reported_result.get("outcome") or "").strip()
    result_text = str(reported_result.get("result_text") or "").strip()
    if not outcome or not result_text:
        return ()
    if not all(
        _objective_axis_is_source_grounded(
            variable.get("name"),
            source=source,
            source_text=source_text,
        )
        and _objective_source_explicitly_links_variable_to_result(
            variable=str(variable.get("name") or ""),
            outcome=outcome,
            result_text=result_text,
            source_text=source_text,
            source=source,
        )
        and (
            not str(variable.get("unit") or "").strip()
            or _objective_column_key(str(variable.get("unit")))
            in _objective_column_key(source_text)
        )
        for variable in variables
    ):
        return ()
    return variables


def _objective_result_direction_near_outcome(
    *,
    result_text: str,
    outcome: str,
    direction_terms: Mapping[str, tuple[str, ...]],
) -> str | None:
    """Resolve direction from the clause attached to the reported outcome.

    A Source may report several properties in one sentence. Counting all
    direction words would make a sentence such as "strength increased while
    elongation decreased" ambiguous even though the target outcome is clear.
    The nearest direction word to the target outcome is the source-local
    signal; conflicting signals remain ``mixed``.
    """

    text = str(result_text or "").strip().casefold()
    target = str(outcome or "").strip().casefold()
    if not text or not target:
        return None
    outcome_positions = [
        match.start() for match in re.finditer(re.escape(target), text)
    ]
    direction_matches: list[tuple[int, str]] = []
    for direction, terms in direction_terms.items():
        for term in terms:
            for match in re.finditer(
                rf"(?<![a-z]){re.escape(term)}(?![a-z])",
                text,
            ):
                direction_matches.append((match.start(), direction))
    if not direction_matches:
        return None
    if not outcome_positions:
        directions = {direction for _position, direction in direction_matches}
        return next(iter(directions)) if len(directions) == 1 else None
    nearest: list[tuple[int, str]] = []
    for outcome_position in outcome_positions:
        position, direction = min(
            direction_matches,
            key=lambda item: abs(item[0] - outcome_position),
        )
        nearest.append((abs(position - outcome_position), direction))
    nearest_distance = min(distance for distance, _direction in nearest)
    nearest_directions = {
        direction
        for distance, direction in nearest
        if distance == nearest_distance
    }
    if len(nearest_directions) != 1:
        return None
    return next(iter(nearest_directions))


def _objective_result_is_non_directional_relation(
    *,
    result_text: str,
    outcome: str,
) -> bool:
    """Return whether wording describes a relationship rather than outcome change.

    Phrases such as ``ductility was more sensitive to porosity`` compare
    sensitivity or association. They do not say that elongation increased or
    decreased. Treating ``more`` as an increase would manufacture a directional
    Finding from a qualitative relationship, which is not a conclusion a
    researcher could support from the Source.
    """

    text = str(result_text or "").strip().casefold()
    target = str(outcome or "").strip().casefold()
    if not text or not target:
        return False
    if not re.search(r"\bsensitiv(?:e|ity)\b", text):
        return False
    # A sensitivity phrase attached to the reported outcome is non-directional.
    # Keep an explicit change clause (``elongation increased and was sensitive``)
    # eligible for ordinary direction inference.
    target_positions = [match.start() for match in re.finditer(re.escape(target), text)]
    if not target_positions:
        return True
    for match in re.finditer(r"\bsensitiv(?:e|ity)\b", text):
        if min(abs(match.start() - position) for position in target_positions) <= 80:
            return not bool(
                re.search(
                    r"\b(?:increase|increased|increases|increasing|decrease|"
                    r"decreased|decreases|decreasing|reduced|reduces|improved|"
                    r"improves|worsened|worsens|higher|lower)\b",
                    text,
                    re.IGNORECASE,
                )
            )
    return False


def _objective_normalize_explicit_no_change_direction(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(record)
    result = normalized.get("reported_result")
    if not isinstance(result, Mapping):
        return normalized

    normalized_result = dict(result)
    result_text = str(normalized_result.get("result_text") or "").strip()
    result_key = _objective_column_key(result_text)
    explicitly_unchanged = any(
        phrase in result_key for phrase in _NO_CHANGE_RESULT_KEYS
    )
    if not explicitly_unchanged:
        return normalized
    if str(normalized_result.get("direction") or "unknown") == "unknown":
        normalized_result["direction"] = "no_change"
        normalized["reported_result"] = normalized_result
    return normalized


def _objective_complete_extracted_variable_endpoints(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    completed = dict(record)
    variables = completed.get("changed_variables")
    comparison = completed.get("comparison")
    if (
        not isinstance(variables, list)
        or len(variables) != 1
        or not isinstance(variables[0], Mapping)
        or not isinstance(comparison, Mapping)
    ):
        return completed
    variable = dict(variables[0])
    axis_names = comparison.get("axis_names")
    if (
        not isinstance(axis_names, list)
        or len(axis_names) != 1
        or not property_matching.axis_values_match(
            str(variable.get("name") or ""),
            str(axis_names[0] or ""),
        )
    ):
        return completed
    source_text = _objective_source_grounding_text(source)
    if not source_text:
        return completed
    endpoints = (
        ("baseline_value", comparison.get("baseline_label")),
        ("target_value", comparison.get("target_label")),
    )
    comparison_labels_are_grounded = all(
        str(label or "").strip()
        and property_matching.axis_label_is_mentioned(
            source_text,
            str(label).strip(),
        )
        for _field, label in endpoints
    )
    variable_unit = str(variable.get("unit") or "").strip()
    variable_values_are_grounded = all(
        _objective_value_is_source_grounded(variable.get(field), source_text)
        for field, _label in endpoints
    )
    variable_unit_is_grounded = not variable_unit or (
        _objective_column_key(variable_unit) in _objective_column_key(source_text)
    )
    if comparison_labels_are_grounded and (
        not variable_values_are_grounded or not variable_unit_is_grounded
    ):
        normalized_comparison = dict(comparison)
        incomparability_reasons = list(
            normalized_comparison.get("incomparability_reasons") or ()
        )
        reason = (
            "SOURCE names comparison labels but does not bind both labels to "
            "complete levels of the Objective variable"
        )
        if reason not in incomparability_reasons:
            incomparability_reasons.append(reason)
        normalized_comparison.update(
            {
                "comparable": False,
                "incomparability_reasons": incomparability_reasons,
            }
        )
        completed["changed_variables"] = []
        completed["comparison"] = normalized_comparison
        completed["attribution_scope"] = "not_attributable"
        completed["resolution_status"] = "partial"
        completed["selection_reason"] = (
            "Source-backed result retained descriptively: comparison labels are "
            "not sufficient to establish complete Objective variable levels."
        )
        return completed
    if variable.get("baseline_value") == variable.get("target_value"):
        return completed
    completed["changed_variables"] = [variable]
    return completed


def _objective_extracted_result_is_source_grounded(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> bool:
    return not _objective_evidence_grounding_errors(record, source=source)


def authored_source_fact_grounding_warnings(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> tuple[str, ...]:
    """Report authored scientific fields that may exceed one canonical Source.

    Automatic extraction applies its own strict publication policy. In the
    Deep Path, a human or Agent may combine a source-local fact with reviewed
    context, so these lexical mismatches stay attached to the immutable
    Evidence record for later review instead of rejecting the authored write.
    Canonical Source identity, excerpt, digest, scope, and version are enforced
    separately.
    """

    source_text = _objective_source_grounding_text(source)
    if not source_text:
        return ("source has no text or table content for grounding",)
    allow_missing_endpoints = str(record.get("attribution_scope") or "") not in {
        "isolated_effect",
        "joint_effect",
    }
    errors = [
        *_objective_evidence_variable_grounding_errors(
            record,
            source=source,
            source_text=source_text,
            allow_missing_endpoints=allow_missing_endpoints,
        ),
        *_objective_evidence_comparison_grounding_errors(
            record,
            source_text=source_text,
        ),
        *_objective_evidence_result_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        ),
        *_objective_authored_result_direction_grounding_errors(record),
        *_objective_evidence_context_grounding_errors(
            record,
            source=source,
        ),
    ]
    reported_result = record.get("reported_result")
    if isinstance(reported_result, Mapping) and not _objective_axis_is_source_grounded(
        reported_result.get("outcome"),
        source=source,
        source_text=source_text,
    ):
        errors.append(
            "reported_result.outcome="
            f"{reported_result.get('outcome')!r} is not grounded in SOURCE"
        )
    comparison = record.get("comparison")
    if (
        isinstance(reported_result, Mapping)
        and isinstance(comparison, Mapping)
        and comparison.get("comparable") is True
        and source.get("source_kind") == "table"
        and source.get("table_matrix")
        and not _objective_extracted_table_result_is_row_grounded(
            record,
            source=source,
        )
    ):
        errors.append(
            "table_rows do not bind the reported result to the selected "
            "comparison endpoints in SOURCE"
        )
    return tuple(dict.fromkeys(errors))


def _objective_authored_result_direction_grounding_errors(
    record: Mapping[str, Any],
) -> tuple[str, ...]:
    reported_result = record.get("reported_result")
    if not isinstance(reported_result, Mapping):
        return ()
    direction = str(reported_result.get("direction") or "unknown").strip()
    if direction in {"unknown", "mixed"}:
        return ()
    result_text = f"_{_objective_column_key(reported_result.get('result_text'))}_"
    if direction == "changed":
        return (
            ()
            if _OBJECTIVE_OBSERVED_CHANGE_MARKERS.search(
                str(reported_result.get("result_text") or "")
            )
            else ("reported_result.direction='changed' is not grounded in SOURCE",)
        )

    numeric_direction = _objective_numeric_result_direction(reported_result)
    if (
        numeric_direction is not None
        and direction in {"increase", "decrease", "no_change"}
        and numeric_direction != direction
    ):
        return (
            f"reported_result.direction={direction!r} conflicts with its numeric "
            "baseline and target values",
        )
    text_direction = _objective_result_direction_near_outcome(
        result_text=str(reported_result.get("result_text") or ""),
        outcome=str(reported_result.get("outcome") or ""),
        direction_terms=_OBJECTIVE_DIRECTION_TERMS,
    )
    if text_direction is not None and text_direction != direction:
        return (
            f"reported_result.direction={direction!r} conflicts with the "
            f"source-grounded result text direction {text_direction!r}",
        )
    if numeric_direction == direction or text_direction == direction:
        return ()
    terms = _OBJECTIVE_DIRECTION_TERMS.get(direction, ())
    if any(f"_{term}_" in result_text for term in terms):
        return ()
    return (
        f"reported_result.direction={direction!r} is not grounded in SOURCE",
    )


def _objective_numeric_result_direction(
    reported_result: Mapping[str, Any],
) -> str | None:
    endpoint_numbers: list[float] = []
    for field in ("baseline_value", "target_value"):
        value = reported_result.get(field)
        numbers = tuple(
            float(match.group(0))
            for match in _NUMBER_PATTERN.finditer(
                str("" if value is None else value)
                .replace(",", "")
                .replace("\u2212", "-")
            )
        )
        if len(numbers) != 1:
            return None
        endpoint_numbers.append(numbers[0])
    baseline, target = endpoint_numbers
    if target > baseline:
        return "increase"
    if target < baseline:
        return "decrease"
    return "no_change"


def _objective_evidence_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> tuple[str, ...]:
    source_text = _objective_source_grounding_text(source)
    if not source_text:
        return ("source has no text or table content for grounding",)
    errors = [
        *_objective_evidence_variable_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        ),
        *_objective_evidence_comparison_grounding_errors(
            record,
            source_text=source_text,
        ),
        *_objective_evidence_result_grounding_errors(
            record,
            source=source,
            source_text=source_text,
        ),
    ]
    if (
        not errors
        and source.get("source_kind") == "table"
        and source.get("table_matrix")
        and record.get("reported_result") is not None
        and not _objective_extracted_table_result_is_row_grounded(
            record,
            source=source,
        )
    ):
        errors.append(
            "table_rows do not bind the reported result to the selected "
            "comparison endpoints in SOURCE"
        )
    return tuple(errors)


def _objective_evidence_context_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> tuple[str, ...]:
    scientific_context = record.get("scientific_context")
    if not isinstance(scientific_context, Mapping):
        return ()
    grounded = _objective_retain_source_grounded_context(
        record,
        source=source,
    ).get("scientific_context")
    grounded_context = grounded if isinstance(grounded, Mapping) else {}
    errors: list[str] = []
    for group in ("material", "sample", "process", "test"):
        grounded_attributes = tuple(
            dict(attribute)
            for attribute in grounded_context.get(group) or ()
            if isinstance(attribute, Mapping)
        )
        for position, attribute in enumerate(scientific_context.get(group) or ()):
            if not isinstance(attribute, Mapping):
                errors.append(
                    f"scientific_context.{group}[{position}] is not a structured "
                    "attribute"
                )
                continue
            if dict(attribute) not in grounded_attributes:
                errors.append(
                    f"scientific_context.{group}[{position}]={dict(attribute)!r} "
                    "is not grounded in SOURCE"
                )
    return tuple(errors)


def _objective_evidence_variable_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
    allow_missing_endpoints: bool = False,
) -> tuple[str, ...]:
    errors: list[str] = []
    for position, variable in enumerate(record.get("changed_variables") or ()):
        path = f"changed_variables[{position}]"
        if not isinstance(variable, Mapping):
            errors.append(f"{path} is not a structured variable")
            continue
        if not _objective_axis_is_source_grounded(
            variable.get("name"),
            source=source,
            source_text=source_text,
        ):
            errors.append(
                f"{path}.name={variable.get('name')!r} is not grounded in SOURCE"
            )
        for field in ("baseline_value", "target_value"):
            value = variable.get(field)
            if allow_missing_endpoints and value in (None, ""):
                continue
            if not _objective_value_is_source_grounded(value, source_text):
                errors.append(f"{path}.{field}={value!r} is not grounded in SOURCE")
        variable_unit = str(variable.get("unit") or "").strip()
        if variable_unit and _objective_column_key(
            variable_unit
        ) not in _objective_column_key(source_text):
            errors.append(f"{path}.unit={variable_unit!r} is not grounded in SOURCE")
    return tuple(errors)


def _objective_evidence_comparison_grounding_errors(
    record: Mapping[str, Any],
    *,
    source_text: str,
) -> tuple[str, ...]:
    comparison = record.get("comparison")
    if not isinstance(comparison, Mapping):
        return ()
    errors: list[str] = []
    for field in ("baseline_label", "target_label"):
        value = comparison.get(field)
        if not _objective_value_is_source_grounded(value, source_text):
            errors.append(f"comparison.{field}={value!r} is not grounded in SOURCE")
    return tuple(errors)


def _objective_primary_source_supported_fields(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> tuple[str, ...]:
    """List fields supported by the current Source itself.

    A same-paper Bundle can make a record complete, but its context must not be
    attributed to the current Results/table Source.  Bundle refs carry their
    own ``bundle_context`` marker; this helper keeps the primary ref honest.
    """

    source_text = _objective_source_grounding_text(source)
    if not source_text:
        return ()
    supported: list[str] = []
    variables = record.get("changed_variables")
    variable_errors = _objective_evidence_variable_grounding_errors(
        record,
        source=source,
        source_text=source_text,
    )
    if isinstance(variables, list) and variables and not variable_errors:
        supported.append("changed_variables")
        if isinstance(record.get("comparison"), Mapping):
            supported.append("comparison.axis_names")
    comparison = record.get("comparison")
    if isinstance(comparison, Mapping) and not _objective_evidence_comparison_grounding_errors(
        record,
        source_text=source_text,
    ):
        supported.append("comparison.labels")
    if isinstance(record.get("reported_result"), Mapping):
        supported.append("reported_result")
    grounded_context = _objective_retain_source_grounded_context(
        record,
        source=source,
    ).get("scientific_context")
    if isinstance(grounded_context, Mapping):
        supported.extend(
            f"scientific_context.{group}"
            for group in ("material", "sample", "process", "test")
            if grounded_context.get(group)
        )
    return tuple(dict.fromkeys(supported))


def _objective_evidence_result_grounding_errors(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    source_text: str,
    objective_context: ResearchObjective | None = None,
) -> tuple[str, ...]:
    reported_result = record.get("reported_result")
    if not isinstance(reported_result, Mapping):
        return ()
    errors: list[str] = []
    outcome = reported_result.get("outcome")
    outcome_grounded = _objective_axis_is_source_grounded(
        outcome,
        source=source,
        source_text=source_text,
    )
    result_text = str(reported_result.get("result_text") or "").strip()
    if not outcome_grounded and not _objective_result_text_is_source_grounded(
        result_text,
        source_text,
    ):
        errors.append(f"reported_result.outcome={outcome!r} is not grounded in SOURCE")
    unit = str(reported_result.get("unit") or "").strip()
    if unit and _objective_column_key(unit) not in _objective_column_key(source_text):
        errors.append(f"reported_result.unit={unit!r} is not grounded in SOURCE")
    for field in ("value", "baseline_value", "target_value"):
        result_value = reported_result.get(field)
        if result_value in (None, "") or _objective_value_is_source_grounded(
            result_value,
            source_text,
        ):
            continue
        errors.append(
            f"reported_result.{field}={result_value!r} is not grounded in SOURCE"
        )
    result_text_is_grounded = _objective_result_text_is_source_grounded(
        result_text,
        source_text,
    )
    if not result_text_is_grounded:
        errors.append(
            f"reported_result.result_text={result_text!r} is not grounded in SOURCE"
        )
    return tuple(errors)


def _objective_result_text_is_source_grounded(
    result_text: str,
    source_text: str,
) -> bool:
    if not result_text:
        return False
    if _NUMBER_PATTERN.search(result_text):
        return _objective_value_is_source_grounded(result_text, source_text)
    return property_matching.axis_label_is_mentioned(source_text, result_text)


def _objective_result_text_unique_outcome(
    result_text: str,
    objective_context: ResearchObjective | None,
) -> str | None:
    """Allow a composite model label only when the Source names one target outcome."""

    if objective_context is None or not result_text:
        return None
    matches = tuple(
        dict.fromkeys(
            property_matching.normalize_property_label(objective_outcome)
            for objective_outcome in objective_context.outcomes
            if property_matching.source_text_mentions_axis(
                result_text,
                objective_outcome,
            )
        )
    )
    return matches[0] if len(matches) == 1 else None


def _objective_extracted_table_result_is_row_grounded(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> bool:
    headers, data_rows = _objective_table_matrix_rows(dict(source))
    reported_result = record.get("reported_result")
    if not headers or not data_rows or not isinstance(reported_result, Mapping):
        return False
    outcome = str(reported_result.get("outcome") or "").strip()
    result_unit = _objective_column_key(str(reported_result.get("unit") or ""))
    outcome_headers: list[str] = []
    for header in headers:
        property_name, header_unit = _split_property_unit(header)
        if not property_matching.axis_values_match(property_name, outcome):
            continue
        if (
            result_unit
            and header_unit
            and (_objective_column_key(header_unit) != result_unit)
        ):
            continue
        outcome_headers.append(header)
    if not outcome_headers:
        return False

    variable_headers: dict[str, tuple[str, ...]] = {}
    for variable in record.get("changed_variables") or ():
        if not isinstance(variable, Mapping):
            return False
        name = str(variable.get("name") or "").strip()
        matching_headers = tuple(
            header
            for header in headers
            if property_matching.axis_values_match(
                _split_property_unit(header)[0],
                name,
            )
            or any(
                property_matching.axis_values_match(axis, name)
                for axis in property_matching.process_column_axis_keys(header)
            )
        )
        if not matching_headers:
            return False
        variable_headers[name] = matching_headers

    row_values = [
        _objective_table_row_values(headers=headers, row=row)
        for _row_index, row in data_rows
    ]

    def matching_rows(value_field: str) -> list[dict[str, str]]:
        matches: list[dict[str, str]] = []
        for values in row_values:
            if all(
                any(
                    _objective_table_cell_matches_value(
                        values.get(header),
                        variable.get(value_field),
                    )
                    for header in variable_headers[
                        str(variable.get("name") or "").strip()
                    ]
                )
                for variable in record.get("changed_variables") or ()
                if isinstance(variable, Mapping)
            ):
                matches.append(values)
        return matches

    baseline_rows = matching_rows("baseline_value")
    target_rows = matching_rows("target_value")
    if record.get("changed_variables") and (not baseline_rows or not target_rows):
        return False
    if not target_rows:
        target_rows = row_values
    if not baseline_rows:
        baseline_rows = target_rows
    for baseline in baseline_rows:
        for target in target_rows:
            if not any(
                _objective_value_is_source_grounded(
                    reported_result.get("value"),
                    target.get(header, ""),
                )
                for header in outcome_headers
            ):
                continue
            bound_text = "\n".join(
                str(value) for value in (*baseline.values(), *target.values())
            )
            result_text = str(reported_result.get("result_text") or "")
            if not _NUMBER_PATTERN.search(
                result_text
            ) or _objective_value_is_source_grounded(result_text, bound_text):
                return True
    return False


def _objective_retain_source_grounded_context(
    record: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    grounded_record = dict(record)
    scientific_context = record.get("scientific_context")
    if not isinstance(scientific_context, Mapping):
        grounded_record["scientific_context"] = {
            "material": [],
            "sample": [],
            "process": [],
            "test": [],
        }
        return grounded_record
    source_text = _objective_source_grounding_text(source)
    grounded_context: dict[str, list[dict[str, Any]]] = {}
    for group in ("material", "sample", "process", "test"):
        grounded_attributes: list[dict[str, Any]] = []
        for attribute in scientific_context.get(group) or ():
            if not isinstance(attribute, Mapping):
                continue
            value = attribute.get("value")
            value_is_grounded = _objective_value_is_source_grounded(
                value,
                source_text,
            )
            if group == "material" and value not in (None, ""):
                value_is_grounded = value_is_grounded or (
                    property_matching.source_text_mentions_material(
                        source_text,
                        str(value),
                    )
                )
            if value not in (None, "") and not value_is_grounded:
                continue
            name_is_grounded = _objective_axis_is_source_grounded(
                attribute.get("name"),
                source=source,
                source_text=source_text,
            )
            if not name_is_grounded:
                # Papers commonly label a row only as ``S1``/``S2`` or
                # ``specimen A``. The model's generic context name is valid
                # when the concrete value is present in the same Source.
                generic_context_names = {
                    "material",
                    "alloy",
                    "sample",
                    "specimen",
                    "coupon",
                    "group",
                    "condition",
                    "process",
                    "fabrication",
                    "manufacturing",
                    "technique",
                    "test",
                    "method",
                    "test method",
                    "measurement method",
                    "orientation",
                }
                if (
                    str(attribute.get("name") or "").strip().casefold()
                    not in generic_context_names
                    or value in (None, "")
                ):
                    continue
            unit = str(attribute.get("unit") or "").strip()
            if unit and _objective_column_key(unit) not in _objective_column_key(
                source_text
            ):
                continue
            grounded_attribute = dict(attribute)
            applies_to_outcomes = attribute.get("applies_to_outcomes")
            if isinstance(applies_to_outcomes, (list, tuple)):
                grounded_outcomes = [
                    str(outcome).strip()
                    for outcome in applies_to_outcomes
                    if str(outcome).strip()
                    and _objective_axis_is_source_grounded(
                        outcome,
                        source=source,
                        source_text=source_text,
                    )
                ]
                if grounded_outcomes:
                    grounded_attribute["applies_to_outcomes"] = list(
                        dict.fromkeys(grounded_outcomes)
                    )
                else:
                    grounded_attribute.pop("applies_to_outcomes", None)
            grounded_attributes.append(grounded_attribute)
        grounded_context[group] = grounded_attributes
    grounded_record["scientific_context"] = grounded_context
    return grounded_record


def _objective_retain_outcome_applicable_test_context(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep result-bound test facts only when their measured outcome matches."""

    retained = dict(record)
    result = retained.get("reported_result")
    context = retained.get("scientific_context")
    if not isinstance(result, Mapping) or not isinstance(context, Mapping):
        return retained
    outcome = str(result.get("outcome") or "").strip()
    if not outcome:
        return retained
    test_attributes = context.get("test")
    if not isinstance(test_attributes, (list, tuple)):
        return retained

    def has_explicit_outcome_scope(attribute: Mapping[str, Any]) -> bool:
        raw_outcomes = attribute.get("applies_to_outcomes")
        return isinstance(raw_outcomes, (list, tuple)) and any(
            str(outcome).strip() for outcome in raw_outcomes
        )

    scoped = [
        dict(attribute)
        for attribute in test_attributes
        if isinstance(attribute, Mapping)
        and has_explicit_outcome_scope(attribute)
        and property_matching.outcome_matches_objective_scope(
            outcome,
            tuple(attribute["applies_to_outcomes"]),
        )
    ]
    unscoped = [
        dict(attribute)
        for attribute in test_attributes
        if isinstance(attribute, Mapping)
        and not has_explicit_outcome_scope(attribute)
    ]
    # A single source-local test method without an explicit outcome tag is
    # still usable when the Source exposes no competing test.  If multiple
    # unscoped methods are present, keep the family unresolved instead of
    # assigning one to the result by position or model confidence.
    applicable = scoped or (unscoped if len(unscoped) == 1 else [])
    scientific_context = dict(context)
    scientific_context["test"] = applicable
    retained["scientific_context"] = scientific_context
    return retained


def _objective_table_cell_matches_value(cell: Any, value: Any) -> bool:
    if value in (None, ""):
        return True
    cell_text = str(cell or "").strip()
    value_text = str(value).strip()
    if not cell_text:
        return False
    if _NUMBER_PATTERN.search(value_text):
        return _objective_value_is_source_grounded(
            value_text,
            cell_text,
        )
    cell_key = _objective_column_key(cell_text)
    value_key = _objective_column_key(value_text)
    return bool(cell_key and value_key and cell_key == value_key)


def _objective_axis_is_source_grounded(
    value: Any,
    *,
    source: Mapping[str, Any],
    source_text: str,
) -> bool:
    axis = str(value or "").strip()
    if not axis:
        return False
    if property_matching.source_text_mentions_axis(source_text, axis):
        return True
    labels = [
        *source.get("column_headers", ()),
        *(
            cell.get("header_path")
            for cell in source.get("table_cells", ())
            if isinstance(cell, Mapping)
        ),
    ]
    for label in labels:
        label_text = str(label or "").strip()
        if not label_text:
            continue
        symbol_axes = property_matching.process_column_axis_keys(label_text)
        if any(property_matching.axis_values_match(axis, item) for item in symbol_axes):
            return True
        if (
            property_matching.axis_values_match(label_text, axis)
            or property_matching.axis_label_is_mentioned(label_text, axis)
            or property_matching.axis_label_is_mentioned(axis, label_text)
        ):
            return True
    return any(
        property_matching.axis_values_match(token, axis)
        for token in re.findall(r"[A-Za-z\u0370-\u03ff]+", source_text)
    )


def _objective_source_grounding_text(source: Mapping[str, Any]) -> str:
    values: list[str] = []
    for field in (
        "text",
        "caption_text",
        "heading_path",
        "table_markdown",
        "table_visual_text",
    ):
        value = str(source.get(field) or "").strip()
        if value:
            values.append(value)
    values.extend(
        str(value).strip()
        for value in source.get("column_headers", ())
        if str(value).strip()
    )
    values.extend(
        str(cell).strip()
        for row in source.get("table_matrix", ())
        if isinstance(row, (list, tuple))
        for cell in row
        if str(cell).strip()
    )
    values.extend(
        str(cell.get("cell_text") or "").strip()
        for cell in source.get("table_cells", ())
        if isinstance(cell, Mapping) and str(cell.get("cell_text") or "").strip()
    )
    return "\n".join(values)


def _objective_value_is_source_grounded(value: Any, source_text: str) -> bool:
    expected = {
        float(match.group(0))
        for match in _NUMBER_PATTERN.finditer(
            str("" if value is None else value).replace(",", "").replace("\u2212", "-")
        )
    }
    if not expected:
        value_key = _objective_column_key(str("" if value is None else value))
        source_key = _objective_column_key(source_text)
        return bool(value_key and value_key in source_key)
    actual = {
        float(match.group(0))
        for match in _NUMBER_PATTERN.finditer(
            source_text.replace(",", "").replace("\u2212", "-")
        )
    }
    return expected <= actual


def _objective_column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _split_property_unit(value: str) -> tuple[str, str | None]:
    text = str(value or "").strip()
    text = re.sub(r"\s*>\s*(?=[\[(])", " ", text).strip()
    if text.endswith("]") and "[" in text:
        name, _, suffix = text.rpartition("[")
        unit = suffix[:-1].strip()
        return name.strip() or text, unit or None
    if text.endswith(")") and "(" in text:
        name, _, suffix = text.rpartition("(")
        unit = suffix[:-1].strip()
        return name.strip() or text, unit or None
    # Tables frequently attach a compact unit directly to a metric header
    # (for example ``El%`` or ``Hardness HV``).  Preserve that source-local
    # unit without treating ordinary words in a property name as units.
    compact_suffix = re.search(
        r"(?P<name>.+?)(?P<unit>%|(?:°|º)?(?:MPa|GPa|kPa|Pa|HV|HRC|HB|J(?:/|\s+)[A-Za-z0-9µμ³²^/-]+|[A-Za-zµμ]+/[A-Za-z0-9µμ³²^/-]+))$",
        text,
        flags=re.IGNORECASE,
    )
    if compact_suffix is not None:
        name = compact_suffix.group("name").strip()
        unit = compact_suffix.group("unit").strip()
        if name and not name.endswith((" ", "-", "/")):
            return name, unit
    return text, None


def _objective_route_source_refs(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    row_index: int | None = None,
    col_index: int | None = None,
    header_path: str | None = None,
    source_excerpt: str | None = None,
    supports: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    ref = {
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "role": route.role,
        "evidence_role": route.join_plan.get("evidence_role"),
        "page": source.get("page"),
        "row_index": row_index,
        "col_index": col_index,
        "header_path": header_path,
        "source_excerpt": source_excerpt,
        "supports": list(supports),
    }
    repair_attestation = source.get("table_matrix_repair_attestation")
    if route.source_kind == "table" and isinstance(repair_attestation, Mapping):
        attestation = dict(repair_attestation)
        matrix = source.get("table_matrix")
        if (
            row_index is not None
            and isinstance(matrix, (list, tuple))
            and 0 <= row_index < len(matrix)
            and isinstance(matrix[row_index], (list, tuple))
        ):
            repaired_row = [str(cell).strip() for cell in matrix[row_index]]
            attestation.update(
                {
                    "repaired_row_index": row_index,
                    "repaired_row_sha256": _objective_source_matrix_sha256(
                        repaired_row
                    ),
                }
            )
        if source_excerpt:
            attestation["source_excerpt_sha256"] = (
                _objective_source_excerpt_sha256(source_excerpt)
            )
        ref["table_matrix_repair_attestation"] = attestation
    return (
        {key: value for key, value in ref.items() if value not in (None, "", [], {})},
    )


def _objective_source_matrix_sha256(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _objective_source_excerpt_sha256(value: Any) -> str:
    normalized = " ".join(str(value or "").split()).casefold()
    return sha256(normalized.encode("utf-8")).hexdigest()
