from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.core.objectives.extraction import ObjectiveExtractor

PAPER_SKIM_PROMPT_VERSION = "paper_skim.v2"
PAPER_SKIM_PROMPT_TOKEN_LIMIT = 12_288
PAPER_SKIM_SOURCE_UNIT_LIMIT = 12
PAPER_SKIM_WARNING_LIMIT = (2, 240)
PAPER_SKIM_STUDY_LIMIT = 8
PAPER_SKIM_RELATIONSHIP_LIMIT = 8
PAPER_SKIM_UNRESOLVED_SIGNAL_LIMIT = 12

_MAX_COMPLETION_TOKENS = 4096
_DOC_ROLES = {"experimental", "review", "modeling", "mixed", "uncertain"}
_EVIDENCE_DENSITIES = {"high", "medium", "low", "unknown"}

_SYSTEM_PROMPT = """
You are screening one bounded Source window for a traceable literature map.

Non-negotiable rules:
- This is high-recall study-design screening, not final fact extraction or synthesis.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied `source_unit_id` values; never invent or rewrite an id.
- Do not infer material systems from filenames or section names.
""".strip()


def _normalize_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list(value: object) -> object:
    return [] if value is None else value


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
    ] = Field(min_length=1, max_length=8)
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
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    sample_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    test_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
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
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    sample_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    test_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
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
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_SKIM_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_SKIM_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _downgrade_relationships_without_factors(cls, value: object) -> object:
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
                if not isinstance(varied_factors, list) or any(
                    str(item).strip() for item in varied_factors
                ):
                    retained_relationships.append(relationship)
                    continue
                outcome = str(relationship.get("outcome") or "").strip()
                source_unit_ids = relationship.get("source_unit_ids")
                if (
                    not outcome
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

    @field_validator("studies", "unresolved_signals", "warnings", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

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


def build_paper_skim_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Extract source-supported paper studies from one bounded Source window. "
        "This is high-recall study-structure extraction, not objective wording, "
        "collection grouping, final measurement extraction, or synthesis.\n\n"
        "INPUT SCHEMA\n"
        "- `document_id` and `title` identify the Source paper.\n"
        "- `window_id` is this bounded window's identity; `window_role` is one of "
        "overview, methods, results, conclusion, or unknown.\n"
        "- `source_units` contains every Source item assigned to this window. Each "
        "unit has an opaque `source_unit_id`, stable Source kind/reference, section "
        "path, and text or caption content. Source identity is provenance; content "
        "is the scientific authority.\n"
        "- `document_profile` is a coarse paper-level classification hint.\n"
        "This is one incomplete view of the paper; absence from this window is not "
        "evidence of absence elsewhere. Window metadata describes input provenance "
        "and must not appear in output.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Classify the paper role from explicit study-design signals.\n"
        "2. Identify each distinct experiment, observation, or model represented in "
        "this window. Keep different specimens, tests, processes, comparators, or "
        "experiment labels as separate studies.\n"
        "3. For each study, record design_type and claim_scope. Only claims about the "
        "paper's own work use claim_scope=current_work; review synthesis and cited "
        "background remain synthesis or background.\n"
        "4. Express every factor and outcome as a neutral scientific axis. A factor "
        "names what was varied, compared, or modeled, not its tested levels. An "
        "outcome names what was measured or predicted, not the result direction, "
        "value, or comparison sentence.\n"
        "5. Within each study, return one relationship per outcome. `varied_factors` "
        "must contain the full jointly varied, compared, or modeled factor set. Never "
        "split a joint-factor experiment into isolated effects.\n"
        "6. Record material, process, sample, test, comparator, and fixed-condition "
        "context only when explicitly supported.\n"
        "7. Copy every unique Source-unit id that directly supports each relationship "
        "or unresolved signal. Each item may contain at most 12 unique "
        "`source_unit_ids`.\n"
        "8. When the window explicitly identifies a varied/modeled variable but no "
        "response, or a measured/predicted outcome but no changed variable, return "
        "the explicit axis in `unresolved_signals` for paper-level reconciliation.\n"
        "9. Use evidence density, confidence, and warnings to expose incomplete or "
        "ambiguous input rather than filling gaps.\n\n"
        "HARD RULES\n"
        "- Return only the schema object. Return every distinct, explicitly supported "
        "study and relationship visible in this Source window; do not discard one "
        "because another appears more central.\n"
        "- Extract only relationships supported inside this window. Do not guess what "
        "another section may contain. Repeating a study fragment found in another "
        "window is acceptable; backend consolidation is authoritative.\n"
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
        "experiment/design/context fields and "
        "one or more relationships. A relationship has `varied_factors`, one "
        "`outcome`, `source_unit_ids`, and confidence.\n"
        "- Return up to 8 studies, up to 8 relationships per study, and up to 12 "
        "unresolved signals. If every visible fact fits, set "
        "`output_saturated=false`. If any distinct supported study, relationship, "
        "or signal would exceed those limits, set `output_saturated=true`; the "
        "backend will split and retry the Source window. Never silently choose a "
        "subset.\n"
        "- Each relationship and unresolved signal returns at most 12 unique "
        "`source_unit_ids`, matching the maximum Source units in one input window.\n"
        "- Return up to 2 `warnings`, each at most 240 characters.\n"
        "- Keep each value concise and preserve exact joint-factor-to-outcome links.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Supported relationship: text says laser power was varied and relative "
        "density and porosity were measured. Return one study with two relationships; "
        "each has varied_factors=['laser power'] and one distinct outcome.\n"
        "- Joint factors: power and speed changed together. Keep "
        "varied_factors=['power','speed']; do not emit isolated power or speed effects.\n"
        "- Factor levels: specimens use L-VED, M-VED, and H-VED. Return "
        "varied_factors=['volumetric energy density']; keep the level names in Source "
        "evidence rather than returning them as three factors.\n"
        "- Result clause: text says fatigue strength decreases with lower VED. Return "
        "outcome='fatigue strength'; the decrease and condition belong to later "
        "Evidence extraction, not the outcome axis.\n"
        "- Incomplete relationship: a Methods window names laser power but no "
        "measured or predicted response. Return `studies=[]`; do not "
        "borrow an outcome from another section. Return the explicit axis in "
        "`unresolved_signals` with its supporting Source-unit id.\n"
        "- No study signal: a unit contains only general background. Return no study "
        "or unresolved signal for that unit.\n"
        "- Separate relationships: one experiment links scan speed to porosity and "
        "another links heat treatment to yield strength. Return two studies."
    )
    return _SYSTEM_PROMPT, user_prompt


class PaperStudyWindowExtractor:
    """Extract supported study structure from one bounded Source window."""

    def __init__(self, response_client: ObjectiveExtractor) -> None:
        self.response_client = response_client

    def extract(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        system_prompt, user_prompt = build_paper_skim_prompt(payload)

        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous PaperSkim output was invalid: "
                f"{repair_detail}. Preserve every distinct supported study, "
                "relationship, and unresolved signal. Copy only unique Source-unit "
                f"IDs from the input, with at most {PAPER_SKIM_SOURCE_UNIT_LIMIT} IDs "
                "per relationship or unresolved signal. Set output_saturated=true "
                "instead of silently omitting a scientific item. Return only compact "
                "schema-valid JSON."
            )

        def validate_study_identities(response: BaseModel) -> None:
            if not isinstance(response, StructuredPaperSkim):
                raise TypeError("unexpected paper skim response type")
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

        def complete_json(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_study_identities,
                fail_on_output_saturation=True,
            )

        response = self.response_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSkim,
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
            json_text_parser=complete_json,
            parsed_validator=validate_study_identities,
            fail_on_output_saturation=True,
            task_type="paper_skim",
            prompt_version=PAPER_SKIM_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredPaperSkim):
            raise TypeError("unexpected paper skim response type")
        return response

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
    "PaperStudyWindowExtractor",
    "StructuredPaperSkim",
    "StructuredPaperStudy",
    "StructuredPaperStudyRelationship",
    "StructuredPaperStudySignal",
    "build_paper_skim_prompt",
]
