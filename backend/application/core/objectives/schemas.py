from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

_OBJECTIVE_DIRECTION_PATTERN = re.compile(
    r"\b(?:affects?|affecting|influences?|influencing|impacts?|impacting)\b",
    re.IGNORECASE,
)
_OBJECTIVE_EFFECT_PATTERN = re.compile(
    r"\beffects?\s+of\s+(?P<source>.+?)\s+on\s+(?P<result>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_OBJECTIVE_RELATIONSHIP_PATTERN = re.compile(
    r"\brelationship\s+between\s+(?P<axes>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_OBJECTIVE_QUESTION_PREFIX = re.compile(
    r"^(?:how|what|which)\s+(?:(?:does|do|did|can|could|will|would|is|are|"
    r"was|were)\s+)?",
    re.IGNORECASE,
)
_OBJECTIVE_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"(?:[;,]|\b(?:and|but|whereas|while)\b)",
    re.IGNORECASE,
)
_OBJECTIVE_ACRONYM_STOP_WORDS = {"a", "an", "and", "for", "of", "the", "to"}
_OBJECTIVE_ROLE_FILLER_WORDS = {"a", "an", "and", "for", "of", "the", "to"}
_OBJECTIVE_SCOPE_CONNECTOR_WORDS = {
    "after",
    "at",
    "by",
    "during",
    "for",
    "in",
    "of",
    "through",
    "under",
    "using",
    "via",
    "with",
}
_OBJECTIVE_SCOPE_FILLER_WORDS = {
    "fabricated",
    "manufactured",
    "processed",
    "produced",
}
_OBJECTIVE_TOKEN_NORMALIZATIONS = {
    "analyses": "analysis",
    "axes": "axis",
    "gases": "gas",
}
_OBJECTIVE_ROLE_SEARCH_STATE_LIMIT = 4096

_PAPER_SKIM_DOC_ROLES = {
    "experimental",
    "review",
    "modeling",
    "mixed",
    "uncertain",
}
_PAPER_SKIM_EVIDENCE_DENSITIES = {"high", "medium", "low", "unknown"}
_OBJECTIVE_FRAME_RELEVANCE = {"high", "medium", "low", "irrelevant", "uncertain"}
_OBJECTIVE_FRAME_PAPER_ROLES = {
    "primary_experiment",
    "supporting_method",
    "supporting_background",
    "review",
    "modeling_only",
    "irrelevant",
    "mixed",
    "uncertain",
}
_OBJECTIVE_EVIDENCE_ROUTE_ROLES = {
    "current_experimental_evidence",
    "process_or_treatment",
    "test_condition",
    "composition_or_background",
    "characterization",
    "literature_comparison",
    "modeling_or_prediction",
    "low_value_or_irrelevant",
}
_OBJECTIVE_EVIDENCE_ROLES = {
    "direct_result",
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
    "contradictory_result",
    "irrelevant",
}
_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES = {
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
}
_OBJECTIVE_EVIDENCE_RESULT_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES = {
    "resolved",
    "partial",
    "unresolved",
    "skipped",
    "unknown",
}
_FINDING_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_FINDING_ASSERTION_STRENGTHS = {"causal", "associative", "descriptive"}


def _normalize_underscored_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list_container(value: object) -> object:
    return [] if value is None else value


def _normalize_objective_axis_tokens(value: str) -> tuple[str, ...]:
    normalized_value = unicodedata.normalize("NFKC", value)
    tokens = re.findall(r"[^\W_]+", normalized_value.casefold(), flags=re.UNICODE)
    normalized: list[str] = []
    for token in tokens:
        if token in _OBJECTIVE_TOKEN_NORMALIZATIONS:
            normalized.append(_OBJECTIVE_TOKEN_NORMALIZATIONS[token])
        elif len(token) > 4 and token.endswith("ies"):
            normalized.append(f"{token[:-3]}y")
        elif len(token) > 4 and token.endswith(("ches", "shes", "sses", "xes", "zes")):
            normalized.append(token[:-2])
        elif len(token) > 3 and token.endswith("s") and not token.endswith(
            ("is", "ss", "us")
        ):
            normalized.append(token[:-1])
        else:
            normalized.append(token)
    return tuple(normalized)


def _token_sequence_spans(
    container: tuple[str, ...],
    sequence: tuple[str, ...],
) -> tuple[tuple[int, int], ...]:
    if not sequence:
        return ()
    return tuple(
        (index, index + len(sequence))
        for index in range(len(container) - len(sequence) + 1)
        if container[index : index + len(sequence)] == sequence
    )


def _axis_role_spans(
    axis: str,
    question_role: str,
    role_tokens: tuple[str, ...],
) -> tuple[tuple[int, int], ...]:
    axis_tokens = _normalize_objective_axis_tokens(axis)
    normalized_axis = unicodedata.normalize("NFKC", axis)
    normalized_role = unicodedata.normalize("NFKC", question_role)
    compact_axis = re.sub(r"[^A-Za-z0-9]", "", normalized_axis)
    axis_is_acronym = (
        2 <= len(compact_axis) <= 8
        and compact_axis.isupper()
        and any(character.isalpha() for character in compact_axis)
    )
    uppercase_role_indexes = {
        index
        for index, token in enumerate(
            re.findall(r"[^\W_]+", normalized_role, flags=re.UNICODE)
        )
        if len(token) >= 2
        and token.isupper()
        and any(character.isalpha() for character in token)
    }
    spans: set[tuple[int, int]] = set()

    if axis_is_acronym:
        acronym = compact_axis.casefold()
        spans.update(
            (index, index + 1)
            for index in uppercase_role_indexes
            if role_tokens[index] == acronym
        )
        return tuple(sorted(spans))

    spans.update(_token_sequence_spans(role_tokens, axis_tokens))
    explicit_axis_acronyms = {
        token.casefold()
        for token in re.findall(r"[^\W_]+", normalized_axis, flags=re.UNICODE)
        if 2 <= len(token) <= 8
        and token.isupper()
        and any(character.isalpha() for character in token)
    }
    spans.update(
        (index, index + 1)
        for index in uppercase_role_indexes
        if role_tokens[index] in explicit_axis_acronyms
    )

    significant_axis_tokens = tuple(
        token for token in axis_tokens if token not in _OBJECTIVE_ACRONYM_STOP_WORDS
    )
    if len(significant_axis_tokens) > 1:
        acronym = "".join(token[0] for token in significant_axis_tokens)
        if len(acronym) >= 2:
            spans.update(
                (index, index + 1)
                for index in uppercase_role_indexes
                if role_tokens[index] == acronym
            )
    return tuple(sorted(spans))


def _scope_role_spans(
    scope: str,
    question_role: str,
    role_tokens: tuple[str, ...],
) -> tuple[tuple[int, int], ...]:
    spans = set(_axis_role_spans(scope, question_role, role_tokens))
    normalized_scope = unicodedata.normalize("NFKC", scope)
    explicit_acronyms = {
        token.casefold()
        for token in re.findall(r"[^\W_]+", normalized_scope, flags=re.UNICODE)
        if 2 <= len(token) <= 8
        and token.isupper()
        and any(character.isalpha() for character in token)
    }
    if explicit_acronyms:
        long_form_tokens = tuple(
            token
            for token in _normalize_objective_axis_tokens(scope)
            if token not in explicit_acronyms
        )
        spans.update(_token_sequence_spans(role_tokens, long_form_tokens))
    return tuple(sorted(spans))


def _role_matches_declared_axes(
    question_role: str,
    axes: list[str],
    *,
    declared_scope: list[str] | None = None,
) -> bool:
    role_tokens = _normalize_objective_axis_tokens(question_role)
    spans_by_axis = sorted(
        [_axis_role_spans(axis, question_role, role_tokens) for axis in axes],
        key=len,
    )
    if not role_tokens or any(not spans for spans in spans_by_axis):
        return False
    scope_indexes = frozenset(
        index
        for scope in declared_scope or []
        for start, end in _scope_role_spans(scope, question_role, role_tokens)
        for index in range(start, end)
    )

    search_state_count = 0

    @lru_cache(maxsize=None)
    def covers_role(axis_index: int, covered_indexes: frozenset[int]) -> bool:
        nonlocal search_state_count
        if search_state_count >= _OBJECTIVE_ROLE_SEARCH_STATE_LIMIT:
            return False
        search_state_count += 1
        if axis_index == len(spans_by_axis):
            uncovered = tuple(
                index
                for index, token in enumerate(role_tokens)
                if index not in covered_indexes
                and token not in _OBJECTIVE_ROLE_FILLER_WORDS
            )
            if not uncovered:
                return True
            if not declared_scope or not covered_indexes:
                return False
            last_axis_index = max(covered_indexes)
            if any(index <= last_axis_index for index in uncovered):
                return False
            trailing_scope_indexes = tuple(
                index for index in scope_indexes if index > last_axis_index
            )
            if not trailing_scope_indexes:
                return False
            first_scope_index = min(trailing_scope_indexes)
            connector_indexes = tuple(
                index
                for index in range(last_axis_index + 1, first_scope_index + 1)
                if role_tokens[index] in _OBJECTIVE_SCOPE_CONNECTOR_WORDS
            )
            if not connector_indexes:
                return False
            return all(
                index in scope_indexes
                or token in _OBJECTIVE_ROLE_FILLER_WORDS
                or token in _OBJECTIVE_SCOPE_CONNECTOR_WORDS
                or token in _OBJECTIVE_SCOPE_FILLER_WORDS
                for index, token in enumerate(
                    role_tokens[last_axis_index + 1 :],
                    start=last_axis_index + 1,
                )
            )
        for start, end in spans_by_axis[axis_index]:
            if search_state_count >= _OBJECTIVE_ROLE_SEARCH_STATE_LIMIT:
                return False
            span_indexes = frozenset(range(start, end))
            if covered_indexes.isdisjoint(span_indexes) and covers_role(
                axis_index + 1,
                covered_indexes | span_indexes,
            ):
                return True
        return False

    return covers_role(0, frozenset())


def _strip_objective_question_prefix(value: str) -> str:
    return _OBJECTIVE_QUESTION_PREFIX.sub("", value, count=1).strip(" ,:")


def _objective_question_roles(question: str) -> tuple[tuple[str, str], ...]:
    effect_match = _OBJECTIVE_EFFECT_PATTERN.search(question)
    relationship_match = _OBJECTIVE_RELATIONSHIP_PATTERN.search(question)
    direction_matches = tuple(_OBJECTIVE_DIRECTION_PATTERN.finditer(question))
    if effect_match and relationship_match:
        return ()
    nominal_match = effect_match or relationship_match
    if nominal_match and any(
        match.start() < nominal_match.start() for match in direction_matches
    ):
        return ()
    if effect_match:
        return ((effect_match.group("source"), effect_match.group("result")),)

    if relationship_match:
        axes = relationship_match.group("axes")
        separators = tuple(re.finditer(r"\s+and\s+", axes, flags=re.IGNORECASE))
        return tuple(
            (axes[: separator.start()].strip(), axes[separator.end() :].strip())
            for separator in separators
        )

    if any(
        _OBJECTIVE_CLAUSE_BOUNDARY_PATTERN.search(
            question[current.end() : following.start()]
        )
        for current, following in zip(direction_matches, direction_matches[1:])
    ):
        return ()

    return tuple(
        (
            _strip_objective_question_prefix(question[: direction_match.start()]),
            question[
                direction_match.end() : (
                    direction_matches[index + 1].start()
                    if index + 1 < len(direction_matches)
                    else len(question)
                )
            ].strip(" ,:?\t\n"),
        )
        for index, direction_match in enumerate(direction_matches)
    )


def _validate_objective_question_roles(
    *,
    question: str,
    variables: list[str],
    outcomes: list[str],
    declared_scope: list[str],
) -> None:
    role_keys: dict[str, set[tuple[str, ...]]] = {}
    for role_name, role_axes in (("variables", variables), ("outcomes", outcomes)):
        seen_keys: set[tuple[str, ...]] = set()
        for axis in role_axes:
            axis_key = _normalize_objective_axis_tokens(axis)
            if axis_key in seen_keys:
                raise ValueError(
                    "question roles do not align; duplicate axis in "
                    f"{role_name}: {axis}"
                )
            seen_keys.add(axis_key)
        role_keys[role_name] = seen_keys
    if role_keys["variables"] & role_keys["outcomes"]:
        raise ValueError(
            "question roles do not align; the same axis cannot appear in both "
            "variables and outcomes"
        )

    role_candidates = _objective_question_roles(question)
    if not role_candidates:
        raise ValueError("question roles must use a supported active variable-to-outcome form")

    candidate_errors: list[tuple[bool, bool, str, str]] = []
    for source_role, result_role in role_candidates:
        variables_align = _role_matches_declared_axes(source_role, variables)
        outcomes_align = _role_matches_declared_axes(
            result_role,
            outcomes,
            declared_scope=declared_scope,
        )
        if variables_align and outcomes_align:
            return
        candidate_errors.append(
            (variables_align, outcomes_align, source_role, result_role)
        )

    variables_align, outcomes_align, source_role, result_role = max(
        candidate_errors,
        key=lambda alignment: int(alignment[0]) + int(alignment[1]),
    )
    details: list[str] = []
    if not variables_align:
        missing_variables = [
            axis
            for axis in variables
            if not _axis_role_spans(
                axis,
                source_role,
                _normalize_objective_axis_tokens(source_role),
            )
        ]
        details.append(
            "source side does not exactly contain the declared variables"
            + (f": {', '.join(missing_variables)}" if missing_variables else "")
        )
    if not outcomes_align:
        missing_outcomes = [
            axis
            for axis in outcomes
            if not _axis_role_spans(
                axis,
                result_role,
                _normalize_objective_axis_tokens(result_role),
            )
        ]
        details.append(
            "result side does not exactly contain the declared outcomes"
            + (f": {', '.join(missing_outcomes)}" if missing_outcomes else "")
        )
    raise ValueError("question roles do not align; " + "; ".join(details))

class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)

    @field_validator("epistemic_status", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_epistemic_status(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["epistemic_status"].get_default(
            call_default_factory=True
        )


class StructuredPaperSkim(_StrictModel):
    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    candidate_materials: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=2
    )
    candidate_processes: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=2
    )
    candidate_properties: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    changed_variables: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    possible_objectives: list[Annotated[str, Field(max_length=180)]] = Field(
        default_factory=list, max_length=3
    )
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=2
    )

    @field_validator(
        "candidate_materials",
        "candidate_processes",
        "candidate_properties",
        "changed_variables",
        "possible_objectives",
        "warnings",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_PAPER_SKIM_DOC_ROLES,
            default="uncertain",
        )

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_PAPER_SKIM_EVIDENCE_DENSITIES,
            default="unknown",
        )


class StructuredResearchObjective(_StrictModel):
    question: str = Field(max_length=180)
    material_scope: list[str] = Field(default_factory=list)
    variables: list[str] = Field(min_length=1)
    outcomes: list[str] = Field(min_length=1)
    mechanisms: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    requested_comparator: str | None = Field(default=None, max_length=160)
    seed_document_ids: list[str] = Field(default_factory=list)
    excluded_document_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str | None = Field(default=None, max_length=120)

    @field_validator(
        "material_scope",
        "variables",
        "outcomes",
        "mechanisms",
        "constraints",
        "seed_document_ids",
        "excluded_document_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @model_validator(mode="after")
    def _validate_question_roles(self) -> "StructuredResearchObjective":
        _validate_objective_question_roles(
            question=self.question,
            variables=self.variables,
            outcomes=self.outcomes,
            declared_scope=[*self.material_scope, *self.constraints],
        )
        return self


class StructuredResearchObjectives(_StrictModel):
    objectives: list[StructuredResearchObjective] = Field(
        default_factory=list,
        max_length=6,
    )

    @field_validator("objectives", mode="before")
    @classmethod
    def _normalize_objectives(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredAxisCanonicalizationGroup(_StrictModel):
    axis_type: Literal["material", "variable", "outcome", "mechanism", "constraint"]
    canonical: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str

    @field_validator("aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredAxisCanonicalizationPlan(_StrictModel):
    axis_groups: list[StructuredAxisCanonicalizationGroup] = Field(
        default_factory=list
    )

    @field_validator("axis_groups", mode="before")
    @classmethod
    def _normalize_axis_groups(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectiveMergeGroup(_StrictModel):
    source_objective_ids: list[str] = Field(default_factory=list)
    question: str
    material_scope: list[str] = Field(default_factory=list)
    variables: list[str] = Field(min_length=1)
    outcomes: list[str] = Field(min_length=1)
    mechanisms: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    requested_comparator: str | None = None
    confidence: float = 0.0
    reason: str

    @field_validator(
        "source_objective_ids",
        "material_scope",
        "variables",
        "outcomes",
        "mechanisms",
        "constraints",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @model_validator(mode="after")
    def _validate_question_roles(self) -> "StructuredObjectiveMergeGroup":
        _validate_objective_question_roles(
            question=self.question,
            variables=self.variables,
            outcomes=self.outcomes,
            declared_scope=[*self.material_scope, *self.constraints],
        )
        return self


class StructuredPaperContributionDraft(_StrictModel):
    relevance: Literal["high", "medium", "low", "irrelevant", "uncertain"] = (
        "uncertain"
    )
    paper_role: Literal[
        "primary_experiment",
        "supporting_method",
        "supporting_background",
        "review",
        "modeling_only",
        "irrelevant",
        "mixed",
        "uncertain",
    ] = "uncertain"
    background: str | None = None
    material_match: list[str] = Field(default_factory=list)
    changed_variables: list[str] = Field(default_factory=list)
    measured_property_scope: list[str] = Field(default_factory=list)
    test_environment_scope: list[str] = Field(default_factory=list)
    relevant_sections: list[str] = Field(default_factory=list)
    relevant_tables: list[str] = Field(default_factory=list)
    excluded_tables: list[str] = Field(default_factory=list)

    @field_validator(
        "material_match",
        "changed_variables",
        "measured_property_scope",
        "test_environment_scope",
        "relevant_sections",
        "relevant_tables",
        "excluded_tables",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @field_validator("relevance", mode="before")
    @classmethod
    def _normalize_relevance(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_FRAME_RELEVANCE,
            default="uncertain",
        )

    @field_validator("paper_role", mode="before")
    @classmethod
    def _normalize_paper_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_FRAME_PAPER_ROLES,
            default="uncertain",
        )


class StructuredEvidenceSelection(_StrictModel):
    role: Literal[
        "current_experimental_evidence",
        "process_or_treatment",
        "test_condition",
        "composition_or_background",
        "characterization",
        "literature_comparison",
        "modeling_or_prediction",
        "low_value_or_irrelevant",
    ] = "low_value_or_irrelevant"
    extractable: bool = False
    confidence: float = 0.0

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ROUTE_ROLES,
            default="low_value_or_irrelevant",
        )


class StructuredEvidenceSelections(_StrictModel):
    selections: list[StructuredEvidenceSelection] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("selections", mode="before")
    @classmethod
    def _normalize_selections(cls, value: object) -> object:
        return _normalize_list_container(value)


ScientificScalar = str | int | float | bool


class StructuredEvidenceAttribute(_StrictModel):
    name: str
    value: ScientificScalar
    unit: str | None = None


class StructuredEvidenceVariable(_StrictModel):
    name: str
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    unit: str | None = None


class StructuredEvidenceComparison(_StrictModel):
    baseline_label: str
    target_label: str
    axis_names: list[str] = Field(min_length=1)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_comparability(self) -> "StructuredEvidenceComparison":
        if not self.comparable and not self.incomparability_reasons:
            raise ValueError("incomparable evidence requires reasons")
        if self.comparable and self.incomparability_reasons:
            raise ValueError("comparable evidence cannot have incomparability reasons")
        return self


class StructuredEvidenceResult(_StrictModel):
    outcome: str
    value: ScientificScalar | None = None
    unit: str | None = None
    direction: Literal[
        "increase",
        "decrease",
        "improve",
        "worsen",
        "no_change",
        "mixed",
        "unknown",
    ] = "unknown"
    result_text: str

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESULT_DIRECTIONS,
            default="unknown",
        )


class StructuredEvidenceContext(_StrictModel):
    material: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    sample: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    process: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    test: list[StructuredEvidenceAttribute] = Field(default_factory=list)

    @field_validator("material", "sample", "process", "test", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object, info: ValidationInfo) -> object:
        items = _normalize_list_container(value)
        if not isinstance(items, list):
            return items
        normalized_items: list[object] = []
        for item in items:
            if isinstance(item, StructuredEvidenceAttribute):
                normalized_items.append(item)
                continue
            if isinstance(item, (str, int, float, bool)):
                normalized_items.append(
                    {"name": info.field_name, "value": item, "unit": None}
                )
                continue
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue

            name = str(item.get("name") or info.field_name).strip()
            unit = item.get("unit")
            if "value" in item:
                attribute_value = item["value"]
                if isinstance(attribute_value, (dict, list)):
                    attribute_value = json.dumps(
                        attribute_value,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                normalized_items.append(
                    {"name": name, "value": attribute_value, "unit": unit}
                )
                continue

            details = {
                key: detail
                for key, detail in item.items()
                if key not in {"name", "unit"}
            }
            normalized_items.append(
                {
                    "name": name if details else info.field_name,
                    "value": (
                        json.dumps(
                            details,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        if details
                        else name
                    ),
                    "unit": unit,
                }
            )
        return normalized_items


class StructuredEvidenceExtraction(_StrictModel):
    evidence_role: Literal[
        "direct_result",
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
        "contradictory_result",
        "irrelevant",
    ] = "irrelevant"
    changed_variables: list[StructuredEvidenceVariable] = Field(
        default_factory=list,
        max_length=12,
    )
    comparison: StructuredEvidenceComparison | None = None
    reported_result: StructuredEvidenceResult | None = None
    attribution_scope: Literal[
        "isolated_effect",
        "joint_effect",
        "association_only",
        "descriptive_only",
        "not_attributable",
    ] = "not_attributable"
    scientific_context: StructuredEvidenceContext = Field(
        default_factory=StructuredEvidenceContext
    )
    resolution_status: Literal[
        "resolved",
        "partial",
        "unresolved",
        "skipped",
        "unknown",
    ] = "partial"
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _normalize_attribution_cardinality(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        attribution_scope = _normalize_underscored_choice(
            value.get("attribution_scope"),
            allowed=_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES,
            default="not_attributable",
        )
        changed_variables = value.get("changed_variables")
        if (
            attribution_scope == "joint_effect"
            and isinstance(changed_variables, list)
            and len(changed_variables) == 1
        ):
            attribution_scope = "isolated_effect"
        if (
            attribution_scope in {"isolated_effect", "joint_effect"}
            and isinstance(changed_variables, list)
            and any(
                (
                    item.get("baseline_value") is None
                    or item.get("target_value") is None
                )
                for item in changed_variables
                if isinstance(item, dict)
            )
        ):
            attribution_scope = "association_only"
        if attribution_scope != value.get("attribution_scope"):
            return {**value, "attribution_scope": attribution_scope}
        return value

    @field_validator("evidence_role", mode="before")
    @classmethod
    def _normalize_evidence_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ROLES,
            default="irrelevant",
        )

    @field_validator("attribution_scope", mode="before")
    @classmethod
    def _normalize_attribution_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES,
            default="not_attributable",
        )

    @field_validator("resolution_status", mode="before")
    @classmethod
    def _normalize_resolution_status(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES,
            default="partial",
        )

    @field_validator("changed_variables", mode="before")
    @classmethod
    def _normalize_changed_variables(cls, value: object) -> object:
        return _normalize_list_container(value)

    @model_validator(mode="after")
    def _validate_scientific_contract(self) -> "StructuredEvidenceExtraction":
        result_role = self.evidence_role in {"direct_result", "contradictory_result"}
        if result_role and self.reported_result is None:
            raise ValueError("result evidence requires one reported result")
        if not result_role and self.reported_result is not None:
            raise ValueError("context evidence cannot report an experimental result")
        if not result_role and self.attribution_scope in {
            "isolated_effect",
            "joint_effect",
        }:
            raise ValueError("context evidence cannot claim experimental attribution")
        if self.comparison is not None and not self.comparison.comparable:
            if self.attribution_scope != "not_attributable":
                raise ValueError("incomparable evidence cannot be attributed")
        if self.attribution_scope in {"isolated_effect", "joint_effect"}:
            if self.comparison is None or not self.comparison.comparable:
                raise ValueError("experimental attribution requires comparison")
            variables = {item.name.casefold() for item in self.changed_variables}
            axes = {item.casefold() for item in self.comparison.axis_names}
            if variables != axes:
                raise ValueError("comparison axes must match changed variables")
            if any(
                item.baseline_value is None or item.target_value is None
                for item in self.changed_variables
            ):
                raise ValueError(
                    "experimental attribution requires baseline and target values"
                )
            if any(
                item.baseline_value == item.target_value
                for item in self.changed_variables
            ):
                raise ValueError(
                    "experimental attribution requires changed variable values"
                )
            if self.attribution_scope == "isolated_effect" and len(variables) != 1:
                raise ValueError("isolated effect requires one changed variable")
            if self.attribution_scope == "joint_effect" and len(variables) < 2:
                raise ValueError("joint effect requires multiple changed variables")
        return self


class StructuredEvidenceExtractions(_StrictModel):
    extractions: list[StructuredEvidenceExtraction] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("extractions", mode="before")
    @classmethod
    def _normalize_extractions(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredFindingMechanism(_StrictModel):
    source_term: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    target_term: str = Field(min_length=1)
    direction: str | None = None
    assertion_strength: Literal["causal", "associative", "descriptive"] = (
        "descriptive"
    )
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=16)

    @field_validator("source_term", "relation_type", "target_term")
    @classmethod
    def _require_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("finding mechanism terms cannot be blank")
        return text

    @field_validator("supporting_evidence_ids")
    @classmethod
    def _require_unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("finding mechanism evidence ids must be unique")
        return value

    @field_validator("assertion_strength", mode="before")
    @classmethod
    def _normalize_assertion_strength(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_ASSERTION_STRENGTHS,
            default="descriptive",
        )


class StructuredFindingSynthesisItem(_StrictModel):
    result_set_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    direction: Literal[
        "increase",
        "decrease",
        "improve",
        "worsen",
        "no_change",
        "mixed",
        "unknown",
    ] = "unknown"
    assertion_strength: Literal["causal", "associative", "descriptive"] = (
        "descriptive"
    )
    condition_boundary_evidence_ids: list[str] = Field(
        default_factory=list, max_length=24
    )
    context_evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    mechanisms: list[StructuredFindingMechanism] = Field(
        default_factory=list, max_length=8
    )
    limitations: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_DIRECTIONS,
            default="unknown",
        )

    @field_validator("assertion_strength", mode="before")
    @classmethod
    def _normalize_assertion_strength(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_ASSERTION_STRENGTHS,
            default="descriptive",
        )

    @field_validator(
        "condition_boundary_evidence_ids",
        "context_evidence_ids",
    )
    @classmethod
    def _require_unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("finding evidence ids must be unique within each role")
        return value


class StructuredFindingSynthesis(_StrictModel):
    findings: list[StructuredFindingSynthesisItem] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("findings", mode="before")
    @classmethod
    def _normalize_findings(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectiveMergePlan(_StrictModel):
    merged_objectives: list[StructuredObjectiveMergeGroup] = Field(default_factory=list)

    @field_validator("merged_objectives", mode="before")
    @classmethod
    def _normalize_merged_objectives(cls, value: object) -> object:
        return _normalize_list_container(value)
