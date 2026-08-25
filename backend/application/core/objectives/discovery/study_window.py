from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from application.core.objectives import property_matching
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)

PAPER_SKIM_PROMPT_VERSION = "paper_map.v1"
PAPER_SOURCE_SIGNAL_PROMPT_VERSION = "paper_source_signal.v1"
PAPER_SKIM_PROMPT_TOKEN_LIMIT = 12_288
PAPER_SKIM_SOURCE_UNIT_LIMIT = 12
PAPER_SKIM_WARNING_LIMIT = (2, 240)
PAPER_SKIM_STUDY_LIMIT = 4
PAPER_SKIM_RELATIONSHIP_LIMIT = 6
PAPER_SKIM_UNRESOLVED_SIGNAL_LIMIT = 8

_STUDY_CONTEXT_LIMIT = 12
_STUDY_CONTEXT_VALUE_CHARS = 160
_VARIED_FACTOR_LIMIT = 12
_SOURCE_SIGNAL_CONTEXT_LIMIT = 4
_SOURCE_SIGNAL_LIMIT = 12
_REVIEW_KNOWLEDGE_ITEM_LIMIT = 4
_REVIEW_CITATION_LEAD_LIMIT = 6

_MAX_COMPLETION_TOKENS = 2048
_SOURCE_SIGNAL_MAX_COMPLETION_TOKENS = 2048
_DOC_ROLES = {"experimental", "review", "modeling", "mixed", "uncertain"}
_EVIDENCE_DENSITIES = {"high", "medium", "low", "unknown"}

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are mapping one paper's stated research scope for traceable Objective discovery.

Non-negotiable rules:
- This is lightweight paper mapping, not experiment reconstruction or Evidence extraction.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied `source_unit_id` values; never invent or rewrite an id.
- Do not infer material systems from filenames or section names.
""".strip()

_REVIEW_SYSTEM_PROMPT = """
You screen one bounded Source window from a review paper for traceable
review-author scientific synthesis.

Non-negotiable rules:
- This is synthesis screening, not reconstruction of every cited experiment.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied `source_unit_id` values; never invent or rewrite an id.
- A citation points to primary literature; it is not review-owned evidence.
""".strip()


def _normalize_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list(value: object) -> object:
    return [] if value is None else value


def _normalize_warnings(value: object) -> object:
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    normalized: list[object] = []
    for item in value[: PAPER_SKIM_WARNING_LIMIT[0]]:
        if not isinstance(item, str):
            normalized.append(item)
            continue
        text = item.strip()
        if text:
            normalized.append(text[: PAPER_SKIM_WARNING_LIMIT[1]])
    return normalized


class _PaperSkimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)


class StructuredPaperStudyRelationship(_PaperSkimResponse):
    varied_factors: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(min_length=1, max_length=_VARIED_FACTOR_LIMIT)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1, max_length=PAPER_SKIM_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator("varied_factors", "source_unit_ids", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_unit_ids(self) -> StructuredPaperStudyRelationship:
        normalized = [value.strip() for value in self.source_unit_ids]
        if any(not value for value in normalized):
            raise ValueError("paper relationship source-unit ids cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper relationship source-unit ids must be unique")
        return self


class StructuredPaperStudy(_PaperSkimResponse):
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "synthesis",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=8)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_STUDY_CONTEXT_LIMIT)
    sample_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_STUDY_CONTEXT_LIMIT)
    test_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_STUDY_CONTEXT_LIMIT)
    comparator: str | None = Field(default=None, max_length=160)
    fixed_conditions: list[
        Annotated[str, Field(max_length=120)]
    ] = Field(default_factory=list, max_length=12)
    relationships: list[StructuredPaperStudyRelationship] = Field(
        min_length=1,
        max_length=PAPER_SKIM_RELATIONSHIP_LIMIT,
    )
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "sample_context",
        "test_context",
        "fixed_conditions",
        "relationships",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    def identity_key(
        self,
        source_keys: Mapping[str, tuple[str, str]] | None = None,
    ) -> tuple[object, ...]:
        def normalized_values(values: list[str]) -> tuple[str, ...]:
            return tuple(
                sorted(
                    {
                        str(value).strip().casefold()
                        for value in values
                        if str(value).strip()
                    }
                )
            )

        relationships = tuple(
            sorted(
                (
                    normalized_values(relationship.varied_factors),
                    relationship.outcome.strip().casefold(),
                    tuple(
                        sorted(
                            {
                                source_keys.get(
                                    source_unit_id.strip(),
                                    ("source_unit", source_unit_id.strip()),
                                )
                                if source_keys is not None
                                else ("source_unit", source_unit_id.strip())
                                for source_unit_id in relationship.source_unit_ids
                                if source_unit_id.strip()
                            }
                        )
                    ),
                )
                for relationship in self.relationships
            )
        )
        return (
            self.design_type,
            self.claim_scope,
            self.experiment_label.strip().casefold()
            if self.experiment_label
            else None,
            normalized_values(self.material_scope),
            normalized_values(self.process_context),
            normalized_values(self.sample_context),
            normalized_values(self.test_context),
            self.comparator.strip().casefold() if self.comparator else None,
            normalized_values(self.fixed_conditions),
            relationships,
        )


class StructuredPaperStudySignal(_PaperSkimResponse):
    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "synthesis",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=8)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_STUDY_CONTEXT_LIMIT)
    sample_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_STUDY_CONTEXT_LIMIT)
    test_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_STUDY_CONTEXT_LIMIT)
    comparator: str | None = Field(default=None, max_length=160)
    fixed_conditions: list[
        Annotated[str, Field(max_length=120)]
    ] = Field(default_factory=list, max_length=12)
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1, max_length=PAPER_SKIM_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "sample_context",
        "test_context",
        "fixed_conditions",
        "source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_unit_ids(self) -> StructuredPaperStudySignal:
        normalized = [value.strip() for value in self.source_unit_ids]
        if any(not value for value in normalized):
            raise ValueError("paper signal source-unit ids cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper signal source-unit ids must be unique")
        return self


class StructuredPaperSourceSignal(_PaperSkimResponse):
    """One explicit scientific axis from one Source, before relationship assembly."""

    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "synthesis",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    sample_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    test_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    comparator: str | None = Field(default=None, max_length=160)
    fixed_conditions: list[
        Annotated[str, Field(max_length=120)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "sample_context",
        "test_context",
        "fixed_conditions",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    def identity_key(self) -> tuple[object, ...]:
        def normalized_values(values: list[str]) -> tuple[str, ...]:
            return tuple(
                sorted(
                    {
                        value.strip().casefold()
                        for value in values
                        if value.strip()
                    }
                )
            )

        return (
            self.signal_type,
            self.label.strip().casefold(),
            self.experiment_label.strip().casefold()
            if self.experiment_label
            else None,
            self.design_type,
            self.claim_scope,
            normalized_values(self.material_scope),
            normalized_values(self.process_context),
            normalized_values(self.sample_context),
            normalized_values(self.test_context),
            self.comparator.strip().casefold() if self.comparator else None,
            normalized_values(self.fixed_conditions),
        )


class StructuredPaperSourceSignalScreen(_PaperSkimResponse):
    """Bounded source-local signals used when paper-scope mapping fails."""

    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    signals: list[StructuredPaperSourceSignal] = Field(
        default_factory=list,
        max_length=_SOURCE_SIGNAL_LIMIT,
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_SKIM_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_SKIM_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _isolate_malformed_signals(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw_signals = value.get("signals")
        if not isinstance(raw_signals, list):
            return value

        signals: list[StructuredPaperSourceSignal] = []
        malformed_count = 0
        for raw_signal in raw_signals:
            try:
                signals.append(StructuredPaperSourceSignal.model_validate(raw_signal))
            except ValidationError:
                malformed_count += 1
        if not malformed_count:
            return value

        signal_label = "signal" if malformed_count == 1 else "signals"
        warning = (
            f"Omitted {malformed_count} malformed source {signal_label}; retained "
            "the valid source-local signals."
        )
        existing_warnings = (
            value.get("warnings") if isinstance(value.get("warnings"), list) else []
        )
        updated = dict(value)
        updated["signals"] = signals
        updated["warnings"] = [warning, *existing_warnings][
            : PAPER_SKIM_WARNING_LIMIT[0]
        ]
        if raw_signals and not signals:
            updated["output_saturated"] = True
        return updated

    @field_validator("signals", mode="before")
    @classmethod
    def _normalize_signals(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_DOC_ROLES, default="uncertain")

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_EVIDENCE_DENSITIES, default="unknown")

    @model_validator(mode="after")
    def _validate_signal_identities(self) -> StructuredPaperSourceSignalScreen:
        identities = [signal.identity_key() for signal in self.signals]
        if len(identities) != len(set(identities)):
            raise ValueError("source signal screen contains duplicate signal identities")
        return self


class StructuredReviewKnowledgeItem(_PaperSkimResponse):
    """One bounded, Source-linked review-author statement or citation lead."""

    content: Annotated[str, Field(min_length=1, max_length=400)]
    material_scope: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=4,
    )
    variables: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=4,
    )
    outcomes: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=4,
    )
    conditions: list[Annotated[str, Field(max_length=160)]] = Field(
        default_factory=list,
        max_length=4,
    )
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1, max_length=4)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "variables",
        "outcomes",
        "conditions",
        "source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_unit_ids(self) -> "StructuredReviewKnowledgeItem":
        normalized = [value.strip() for value in self.source_unit_ids]
        if len(normalized) != len(set(normalized)):
            raise ValueError("review knowledge Source-unit ids must be unique")
        return self


class StructuredReviewSynthesisMap(_PaperSkimResponse):
    synthesis_claims: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    disputes: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    evidence_gaps: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    citation_leads: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_CITATION_LEAD_LIMIT,
    )

    @field_validator(
        "synthesis_claims",
        "disputes",
        "evidence_gaps",
        "citation_leads",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)


class StructuredPaperSkim(_PaperSkimResponse):
    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    studies: list[StructuredPaperStudy] = Field(
        default_factory=list,
        max_length=PAPER_SKIM_STUDY_LIMIT,
    )
    unresolved_signals: list[StructuredPaperStudySignal] = Field(
        default_factory=list,
        max_length=PAPER_SKIM_UNRESOLVED_SIGNAL_LIMIT,
    )
    review_synthesis: StructuredReviewSynthesisMap = Field(
        default_factory=StructuredReviewSynthesisMap
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_SKIM_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_SKIM_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _downgrade_unresolved_relationships(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        studies = value.get("studies")
        unresolved_signals = value.get("unresolved_signals")
        if not isinstance(studies, list):
            return value
        if unresolved_signals is not None and not isinstance(
            unresolved_signals,
            list,
        ):
            return value

        retained_studies: list[object] = []
        downgraded_signals: list[dict[str, object]] = []
        changed = False
        for study in studies:
            if not isinstance(study, Mapping):
                retained_studies.append(study)
                continue
            relationships = study.get("relationships")
            if not isinstance(relationships, list):
                retained_studies.append(study)
                continue

            retained_relationships: list[object] = []
            study_changed = False
            for relationship in relationships:
                if not isinstance(relationship, Mapping):
                    retained_relationships.append(relationship)
                    continue
                varied_factors = relationship.get("varied_factors")
                has_varied_factor = not isinstance(varied_factors, list) or (
                    bool(varied_factors)
                    and all(
                        0 < len(str(item).strip()) <= 80
                        for item in varied_factors
                    )
                )
                outcome = str(relationship.get("outcome") or "").strip()
                if has_varied_factor and not (
                    property_matching.outcome_label_requires_resolution(outcome)
                ):
                    retained_relationships.append(relationship)
                    continue
                source_unit_ids = relationship.get("source_unit_ids")
                if (
                    not outcome
                    or len(outcome) > 80
                    or not isinstance(source_unit_ids, list)
                    or not any(str(item).strip() for item in source_unit_ids)
                ):
                    retained_relationships.append(relationship)
                    continue

                signal = {
                    "signal_type": "outcome",
                    "label": outcome,
                    "source_unit_ids": list(source_unit_ids),
                    "confidence": relationship.get(
                        "confidence",
                        study.get("confidence"),
                    ),
                }
                for field_name in (
                    "experiment_label",
                    "design_type",
                    "claim_scope",
                    "material_scope",
                    "process_context",
                    "sample_context",
                    "test_context",
                    "comparator",
                    "fixed_conditions",
                ):
                    if field_name in study:
                        signal[field_name] = study[field_name]
                downgraded_signals.append(signal)
                study_changed = True
                changed = True

            if retained_relationships or not study_changed:
                retained_study = dict(study)
                retained_study["relationships"] = retained_relationships
                retained_studies.append(retained_study)

        if not changed:
            return value
        normalized = dict(value)
        normalized["studies"] = retained_studies
        normalized["unresolved_signals"] = [
            *(unresolved_signals or []),
            *downgraded_signals,
        ]
        return normalized

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_DOC_ROLES, default="uncertain")

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_EVIDENCE_DENSITIES, default="unknown")

    @model_validator(mode="after")
    def _validate_study_identities(self) -> StructuredPaperSkim:
        study_identities = [study.identity_key() for study in self.studies]
        if len(study_identities) != len(set(study_identities)):
            raise ValueError("studies contain duplicate study identities")
        return self


def _review_synthesis_only(response: StructuredPaperSkim) -> StructuredPaperSkim:
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


def _build_review_synthesis_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    allowed_source_unit_ids = [
        str(source_unit.get("source_unit_id") or "").strip()
        for source_unit in payload.get("source_units") or ()
        if isinstance(source_unit, Mapping)
        and str(source_unit.get("source_unit_id") or "").strip()
    ]
    allowed_source_unit_ids_json = json.dumps(
        allowed_source_unit_ids,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    user_prompt = (
        "TASK MODEL\n"
        "Perform lightweight review-author synthesis mapping for one bounded "
        "high-level Source window. "
        "This is thematic and comparative synthesis extraction, not cited-study "
        "reconstruction, primary-paper Evidence extraction, or Objective generation. "
        "The downstream backend uses the result to identify research themes worth "
        "checking against primary papers.\n\n"
        "INPUT SCHEMA\n"
        "- `document_id` and `title` identify the review paper.\n"
        "- `document_profile.doc_type=review` selects this scientific responsibility.\n"
        "- `window_id`, `window_role`, and `section_paths` orient this incomplete "
        "window but are not scientific evidence.\n"
        "- `source_units` contain text, review tables, or figure captions. Their "
        "content is the authority and their IDs provide lineage.\n"
        "- A citation or named prior author identifies primary literature that may "
        "later be inspected; it does not make that experiment a study owned by this "
        "review.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Separate statements authored as review synthesis from reports of one "
        "named or numbered cited study. Signals such as 'across studies', 'overall', "
        "'the literature shows', explicit agreement/disagreement, taxonomies, and "
        "review-author conclusions can establish synthesis. Citation count alone "
        "cannot.\n"
        "2. For an explicit review-author comparison linking a factor or condition "
        "to one specific outcome, return one study with claim_scope=synthesis and "
        "one relationship per outcome. Preserve the full jointly compared factor set.\n"
        "3. When review-author synthesis explicitly names only a variable or only an "
        "outcome, return that axis as an unresolved signal with "
        "claim_scope=synthesis. Do not borrow its missing counterpart from a cited "
        "study or another Source.\n"
        "4. If the Source only describes individual cited experiments, generic "
        "background, review methods, or bibliographic navigation, return no study or "
        "unresolved signal.\n"
        "5. Copy only context and Source-unit IDs that directly support the retained "
        "review-author synthesis. Preserve ambiguity with confidence and warnings.\n\n"
        "6. Record the review authors' statement in `review_synthesis`: use "
        "`synthesis_claims` for cross-study judgments, `disputes` for explicit "
        "conflict, `evidence_gaps` for missing evidence or validation, and "
        "`citation_leads` for named or numbered primary papers worth inspecting.\n\n"
        "HARD RULES\n"
        "- Return no claim_scope=current_work, background, or uncertain study or "
        "signal from a review window; only claim_scope=synthesis is eligible.\n"
        "- Do not reconstruct the design, samples, controls, conditions, or outcomes "
        "of an individually cited paper. Those facts require the primary Source.\n"
        "- Do not turn a list of citations into independent support or a causal "
        "relationship.\n"
        "- Citation leads are navigation only and are never primary Evidence. Keep "
        "them out of studies and unresolved_signals.\n"
        "- Do not infer scientific content from the title, section name, filename, "
        "or general knowledge.\n"
        "- Return empty arrays when the review authors do not make an eligible "
        "synthesis statement in this window.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Cited result only: 'Miranda et al. [20] reported lower residual stress.' "
        "This is a pointer to one primary study; return no study or unresolved signal.\n"
        "- Review synthesis: 'Across studies, preheating generally reduced residual "
        "stress.' Return one synthesis relationship with factor='preheating "
        "condition', outcome='residual stress', and only the supporting Source ID.\n"
        "- Conflict: 'Reported porosity trends disagree across scan strategies.' "
        "Return synthesis axes only when the review authors identify the compared "
        "factor and outcome; preserve disagreement as uncertainty rather than "
        "inventing one direction.\n"
        "- Review method only: 'We searched Web of Science using these keywords.' "
        "Return empty studies and unresolved_signals.\n\n"
        "OUTPUT CONTRACT\n"
        "- Return doc_role='review', studies, unresolved_signals, evidence_density, "
        "confidence, warnings, output_saturated, and `review_synthesis` with "
        "`synthesis_claims`, `disputes`, `evidence_gaps`, and `citation_leads`.\n"
        "- Every returned study or signal must use claim_scope=synthesis. A study "
        "contains one or more source-supported relationships; every relationship and "
        "signal copies only allowed Source-unit IDs.\n"
        "- Return at most 4 synthesis studies, 6 relationships per study, and 8 "
        "unresolved synthesis signals. Set output_saturated=true only if eligible "
        "review-author synthesis exceeds these limits. Individually cited studies do "
        "not count toward saturation.\n"
        "- Return at most 4 synthesis claims, 4 disputes, 4 evidence gaps, and 6 "
        "citation leads. Each item copies 1-4 allowed Source-unit IDs and includes "
        "content, scientific scope, and confidence.\n"
        "- Return only compact schema-valid JSON.\n\n"
        "BATCH LINEAGE CONTRACT\n"
        f"ALLOWED SOURCE-UNIT IDS: {allowed_source_unit_ids_json}\n"
        "Copy IDs only from this exact list."
    )
    return _REVIEW_SYSTEM_PROMPT, user_prompt


def build_paper_skim_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    document_profile = payload.get("document_profile")
    if isinstance(document_profile, Mapping) and (
        str(document_profile.get("doc_type") or "").strip() == "review"
    ):
        return _build_review_synthesis_prompt(payload)

    allowed_source_unit_ids = [
        str(source_unit.get("source_unit_id") or "").strip()
        for source_unit in payload.get("source_units") or ()
        if isinstance(source_unit, Mapping)
        and str(source_unit.get("source_unit_id") or "").strip()
    ]
    allowed_source_unit_ids_json = json.dumps(
        allowed_source_unit_ids,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    user_prompt = (
        "TASK MODEL\n"
        "Map the paper's stated research scope from one bounded high-level Source "
        "window. This is candidate-scope extraction for Objective discovery, not "
        "full experiment reconstruction, final fact extraction, causal synthesis, "
        "or Objective wording. A returned relationship is candidate scope, not "
        "proven Evidence.\n\n"
        "INPUT SCHEMA\n"
        "- `document_id` and `title` identify the Source paper.\n"
        "- `window_id` is this bounded window's identity; `window_role` is one of "
        "overview, methods, results, conclusion, or unknown.\n"
        "- `source_units` contains a bounded researcher-like skim selected from "
        "abstract, conclusion or summary, overview, and visual captions. Each "
        "unit has an opaque `source_unit_id`, stable Source kind/reference, section "
        "path, and text or caption content. Source identity is provenance; content "
        "is the scientific authority.\n"
        "- `document_profile` is a coarse paper-level classification hint.\n"
        "This is one incomplete view of the paper; absence from this window is not "
        "evidence of absence elsewhere. Detailed Methods, Results, and table rows "
        "are inspected only after a user confirms an Objective. Window metadata "
        "describes input provenance and must not appear in output.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Classify the paper role from explicit high-level study-design signals.\n"
        "2. Identify the paper-owned research themes stated in the supplied Source: "
        "material scope, process or treatment family, changed/compared/modeled axes, "
        "and measured/observed/predicted outcome axes. Do not reconstruct specimen "
        "groups, factor levels, controls, test settings, or experimental routes.\n"
        "3. Use claim_scope=current_work only for the paper's own stated research. "
        "Review synthesis and cited background remain synthesis or background. When "
        "a Source mixes the paper's scope with Miranda et al. [20] or another named "
        "citation, never label the cited study current_work.\n"
        "4. Express every factor and outcome as a neutral scientific axis. A factor "
        "names what the paper states was varied, compared, or modeled, not its levels. "
        "An outcome names one specific outcome that was measured, observed, or "
        "predicted, not the result direction, value, or comparison sentence. Split "
        "strength and ductility into separate relationships when both are explicit. "
        "If only a broad family such as mechanical properties or microstructure, or "
        "a compound outcome without one measurement identity, is supplied, retain it "
        "as an unresolved outcome signal instead of inventing a metric.\n"
        "5. Group axes only when the supplied high-level Source explicitly states that "
        "they belong to the same paper-owned research scope. Within each group, return "
        "one relationship per outcome. `varied_factors` must contain the full jointly "
        "varied, compared, or modeled factor set.\n"
        "6. Record material_scope and concise process_context when explicit. Leave "
        "sample_context, test_context, comparator, and fixed_conditions empty; those "
        "belong to confirmed-Objective experiment reconstruction.\n"
        "7. Copy every unique Source-unit id that directly supports each relationship "
        "or unresolved signal. Each item may contain at most 12 unique "
        "`source_unit_ids`.\n"
        "8. When the Source explicitly identifies a varied/modeled variable but no "
        "response, or a measured/predicted outcome but no changed variable, return "
        "the explicit axis in `unresolved_signals` for bounded paper-level "
        "reconciliation.\n"
        "9. Use evidence density, confidence, and warnings to expose incomplete or "
        "ambiguous input rather than filling gaps.\n\n"
        "HARD RULES\n"
        "- Return only the schema object and only axes supported inside this window.\n"
        "- Never move a factor, outcome, or context between studies.\n"
        "- Every relationship and unresolved signal must copy `source_unit_ids` that "
        "directly support it. Do not return an id absent from `source_units`, repeat an "
        "id inside one item, or return more than 12 IDs for one item.\n"
        "- Do not repeat an axis in `unresolved_signals` when it is already part of a "
        "complete relationship in this window. Material and fixed process context are "
        "not partial variable/outcome signals.\n"
        "- Do not generate a research question or collection-level objective.\n"
        "- Do not infer scientific content from filenames or generic section names.\n"
        "- Return empty arrays rather than guessing unsupported study structure.\n\n"
        "OUTPUT CONTRACT\n"
        "- Return `studies`, `unresolved_signals`, doc_role, evidence_density, "
        "confidence, warnings, and `output_saturated`. A study has "
        "paper-scope design/context fields and "
        "one or more relationships. A relationship has `varied_factors`, one "
        "`outcome`, `source_unit_ids`, and confidence.\n"
        "- Return up to 4 studies, up to 6 relationships per study, and up to 8 "
        "unresolved signals. If every visible fact fits, set "
        "`output_saturated=false`. If any distinct supported study, relationship, "
        "or signal would exceed those limits, set `output_saturated=true`; the "
        "backend may inspect a smaller high-level Source window.\n"
        "- Each relationship and unresolved signal returns at most 12 unique "
        "`source_unit_ids`, matching the maximum Source units in one input window.\n"
        "- Each relationship returns at most 12 varied-factor labels, each at most 80 "
        "characters. Preserve the full joint-factor set within these bounds.\n"
        "- Return up to 2 `warnings`, each at most 240 characters.\n"
        "- Keep each value concise and preserve exact joint-factor-to-outcome links.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Common path: an abstract says laser power was varied and relative density "
        "and porosity were measured. Return one paper-scope study with two "
        "relationships; each has varied_factors=['laser power'] and one outcome.\n"
        "- Joint factors: power and speed changed together. Keep "
        "varied_factors=['power','speed']; do not emit isolated power or speed effects.\n"
        "- Factor levels: specimens use L-VED, M-VED, and H-VED. Return "
        "varied_factors=['volumetric energy density']; keep the level names in Source "
        "evidence rather than returning them as three factors.\n"
        "- Result clause: text says fatigue strength decreases with lower VED. Return "
        "outcome='fatigue strength'; the decrease and condition belong to later "
        "Evidence extraction, not the outcome axis.\n"
        "- Broad theme only: text says heat treatment changed the microstructure but "
        "does not identify what was observed. Return outcome signal "
        "label='microstructure' in `unresolved_signals`; do not guess grain size, "
        "texture, morphology, or phase fraction.\n"
        "- Specific microstructural observations: text explicitly reports that heat "
        "treatment removed the cellular structure and increased grain size. Return "
        "separate outcomes 'cellular structure' and 'grain size' with the same full "
        "factor set and Source lineage.\n"
        "- Incomplete relationship: a Methods window names laser power but no "
        "measured or predicted response. Return `studies=[]`; do not "
        "borrow an outcome from another section. Return the explicit axis in "
        "`unresolved_signals` with its supporting Source-unit id.\n"
        "- No study signal: a unit contains only general background. Return no study "
        "or unresolved signal for that unit.\n"
        "- Cited result: text says 'Miranda et al. [20] increased laser power and "
        "reduced porosity.' This is a background study, not the current paper's "
        "experiment; use claim_scope=background and do not merge it with current work.\n"
        "- Detailed condition: a caption lists sample A, 200 W, and 900 mm/s but does "
        "not say which axis was compared. Do not turn settings into varied factors; "
        "confirmed-Objective extraction will inspect the table rows and Methods.\n\n"
        "BATCH LINEAGE CONTRACT\n"
        f"ALLOWED SOURCE-UNIT IDS: {allowed_source_unit_ids_json}\n"
        "Copy IDs only from this exact list. Do not continue its numbering or cite "
        "a Source unit from another window."
    )
    return _SYSTEM_PROMPT, user_prompt


_SOURCE_SIGNAL_SYSTEM_PROMPT = """
You screen one Source from a scientific paper for explicit research signals.
Return one compact JSON object. Preserve uncertainty and Source-local meaning.
Do not construct experiments, relationships, findings, or research objectives.
""".strip()


def build_paper_source_signal_prompt(payload: dict[str, Any]) -> tuple[str, str]:
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
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Decide whether the Source explicitly names a changed, compared, or modeled "
        "variable and/or a measured, observed, or predicted outcome.\n"
        "2. Return each explicit research axis as one neutral, concise signal. An "
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
        "- Primary result: 'We varied laser power and measured porosity.' Return a "
        "current_work variable signal 'laser power' and outcome signal 'porosity'.\n"
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
        "Return signals=[].\n\n"
        "OUTPUT CONTRACT\n"
        "Return doc_role, signals, output_saturated, evidence_density, confidence, and "
        "warnings. Return at most 12 signals and at most four values in each context "
        "list. Set output_saturated=true only when more than 12 distinct explicit "
        "research axes are present; omitted descriptive details do not count as omitted "
        "axes. Return only schema-valid JSON."
    )
    return _SOURCE_SIGNAL_SYSTEM_PROMPT, user_prompt


class PaperStudyWindowExtractor:
    """Map supported paper scope from one bounded high-level Source window."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def extract(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        system_prompt, user_prompt = build_paper_skim_prompt(payload)
        allowed_source_unit_ids = [
            str(source_unit.get("source_unit_id") or "").strip()
            for source_unit in payload.get("source_units") or ()
            if isinstance(source_unit, Mapping)
            and str(source_unit.get("source_unit_id") or "").strip()
        ]
        allowed_source_unit_ids_json = json.dumps(
            allowed_source_unit_ids,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        is_review = (
            isinstance(payload.get("document_profile"), Mapping)
            and str(payload["document_profile"].get("doc_type") or "").strip()
            == "review"
        )

        def build_repair_instruction(repair_detail: str) -> str:
            if is_review:
                return (
                    "Previous review synthesis output was invalid: "
                    f"{repair_detail}. Retain only explicit scientific synthesis "
                    "authored by the review. Discard individually cited experiments "
                    "and every current_work, background, or uncertain study or signal. "
                    "Only claim_scope=synthesis is eligible and only omitted synthesis "
                    "counts toward output_saturated. Copy only unique Source-unit IDs "
                    "from the input and return compact schema-valid JSON.\n"
                    f"ALLOWED SOURCE-UNIT IDS: {allowed_source_unit_ids_json}"
                )
            return (
                "Previous paper-map output was invalid: "
                f"{repair_detail}. Preserve every distinct supported paper-scope "
                "group, relationship, and unresolved signal. Do not reconstruct "
                "samples, tests, comparators, fixed conditions, or factor levels. "
                "Leave sample_context, test_context, comparator, and fixed_conditions "
                "empty. Copy only unique Source-unit "
                f"IDs from the input, with at most {PAPER_SKIM_SOURCE_UNIT_LIMIT} IDs "
                "per relationship or unresolved signal. Keep at most 12 varied factors "
                "per relationship. Set output_saturated=true "
                "instead of silently omitting a scientific item. Return only compact "
                "schema-valid JSON.\n"
                f"ALLOWED SOURCE-UNIT IDS: {allowed_source_unit_ids_json}"
            )

        def validate_output_contract(response: BaseModel) -> BaseModel | None:
            if not isinstance(response, StructuredPaperSkim):
                raise TypeError("unexpected paper skim response type")
            if is_review:
                response = _review_synthesis_only(response)
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
                study.identity_key(source_keys) for study in response.studies
            ]
            if len(study_identities) != len(set(study_identities)):
                raise ValueError("studies contain duplicate study identities")
            referenced_source_unit_ids = {
                source_unit_id.strip()
                for study in response.studies
                for relationship in study.relationships
                for source_unit_id in relationship.source_unit_ids
            } | {
                source_unit_id.strip()
                for signal in response.unresolved_signals
                for source_unit_id in signal.source_unit_ids
            }
            unknown_source_unit_ids = sorted(
                referenced_source_unit_ids - source_keys.keys()
            )
            if unknown_source_unit_ids:
                raise ValueError(
                    "paper skim references unknown Source-unit ids: "
                    f"{unknown_source_unit_ids}"
                )
            return response

        def parse_json_text_with_contract(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_output_contract,
                fail_on_output_saturation=True,
            )

        try:
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=StructuredPaperSkim,
                max_completion_tokens=_MAX_COMPLETION_TOKENS,
                json_text_parser=parse_json_text_with_contract,
                parsed_validator=validate_output_contract,
                fail_on_output_saturation=True,
                task_type="paper_skim",
                prompt_version=PAPER_SKIM_PROMPT_VERSION,
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_skim")
            raise
        if not isinstance(response, StructuredPaperSkim):
            raise TypeError("unexpected paper skim response type")
        return response

    def extract_source_signals(self, payload: dict[str, Any]) -> StructuredPaperSkim:
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
        try:
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=StructuredPaperSourceSignalScreen,
                max_completion_tokens=_SOURCE_SIGNAL_MAX_COMPLETION_TOKENS,
                fail_on_output_saturation=True,
                task_type="paper_source_signal",
                prompt_version=PAPER_SOURCE_SIGNAL_PROMPT_VERSION,
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_source_signal")
            raise
        if not isinstance(response, StructuredPaperSourceSignalScreen):
            raise TypeError("unexpected paper source signal response type")
        if response.output_saturated:
            self._log_saturation_trace(payload, contract="paper_source_signal")
            raise StructuredOutputSaturatedError(
                "Paper source signal output omitted visible scientific axes"
            )

        return StructuredPaperSkim.model_validate(
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
            "Paper skim saturation trace contract=%s window_id=%s "
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

        system_prompt, user_prompt = build_paper_skim_prompt(payload)
        return self.response_client.estimate_prompt_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSkim,
        )


__all__ = [
    "PAPER_SKIM_PROMPT_TOKEN_LIMIT",
    "PAPER_SKIM_SOURCE_UNIT_LIMIT",
    "PAPER_SOURCE_SIGNAL_PROMPT_VERSION",
    "PaperStudyWindowExtractor",
    "StructuredPaperSkim",
    "StructuredPaperSourceSignal",
    "StructuredPaperSourceSignalScreen",
    "StructuredPaperStudy",
    "StructuredPaperStudyRelationship",
    "StructuredPaperStudySignal",
    "build_paper_skim_prompt",
    "build_paper_source_signal_prompt",
]
