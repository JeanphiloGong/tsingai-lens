"""Extract source-local facts for one confirmed ResearchObjective."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from functools import partial
from hashlib import sha1
from typing import Any, Callable, Literal, Mapping

from openai import APIConnectionError, APIStatusError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_routing import (
    EvidenceCandidate,
    order_routes_for_extraction,
)
from application.core.objectives.analysis.diagnostics import (
    record_analysis_diagnostic,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from application.core.objectives.analysis.source_validation import (
    _objective_axis_is_source_grounded,
    _objective_column_key,
    _objective_source_grounding_text,
    _objective_value_is_source_grounded,
    _objective_route_source_refs,
    _objective_row_matches_headers,
    _objective_table_matrix_rows,
    _objective_table_row_values,
    _split_property_unit,
    validate_source_fact,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.paper_facts.extraction import (
    PaperFactsExtractor,
    build_default_paper_facts_extractor,
)
from domain.core import (
    ObjectiveEvidenceComparison,
    ObjectiveEvidenceContext,
    ObjectiveEvidenceResult,
    ObjectiveEvidenceVariable,
    ResearchObjective,
    normalize_objective_confidence,
    normalize_objective_terms,
)
from domain.source import SourceDocumentTree, render_markdown_table

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_ROUTE_PROMPT_TEXT_CHARS = 320
_ROUTE_PROMPT_HEADER_LIMIT = 8
_OBJECTIVE_STATE_ITEM_LIMIT = 12
_OBJECTIVE_STATE_TEXT_CHARS = 220
# A Source block is normally one paragraph, but tables and figure captions can
# carry longer result clauses.  Keep a generous bounded window so extraction
# sees the whole local claim without sending an unbounded document section.
_OBJECTIVE_EVIDENCE_TEXT_CHARS = 12_000
# Keep the complete bounded Source block available to extraction.  A second,
# smaller head-only limit silently removed result clauses that appeared later
# in a paragraph, which is not a valid evidence-preserving reduction.
_OBJECTIVE_EVIDENCE_PROMPT_TEXT_CHARS = _OBJECTIVE_EVIDENCE_TEXT_CHARS
_OBJECTIVE_CONTEXT_BUNDLE_MAX_SOURCES = 16
_OBJECTIVE_CONTEXT_BUNDLE_MAX_CHARS = 40_000
# Same-paper closure is a targeted research read, not a license to inspect an
# entire paper after every partial result. Two rounds are enough for the normal
# Results -> Methods -> linked-label chain while leaving unresolved scope
# explicit when the paper requires a broader review.
_OBJECTIVE_ADAPTIVE_CONTEXT_MAX_ROUNDS = 2
_TABLE_MATRIX_REPAIR_PROMPT_TOKEN_LIMIT = 12_000
_OBJECTIVE_NON_RESULT_VALUE_COLUMN_TERMS = (
    "standard deviation",
    "std",
    "sd",
    "variance",
    "error bar",
    "condition number",
    "sample number",
)
_OBJECTIVE_PREDICTED_RESULT_TERMS = (
    "predict",
    "forecast",
    "simulation",
    "simulated",
    "model prediction",
    "predicted",
)
_OBJECTIVE_MEASURED_RESULT_TERMS = (
    "experiment",
    "experimental",
    "measured",
    "measurement",
    "observed",
)
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_GROUP_LABEL_PATTERN = re.compile(
    r"\b(?:sample|specimen|group|condition)\s*[A-Za-z]?\d+\b|\b[A-Z]{1,3}\d+\b"
)
_SOURCE_EXTRACTION_MAX_COMPLETION_TOKENS = 3072
_SOURCE_EXTRACTION_MAX_ITEMS = 8
# Candidate selection and bounded same-paper rereads are part of the scientific
# extraction contract. Bump it so persisted checkpoints are rebuilt rather than
# replaying the pre-closure route set.
OBJECTIVE_SOURCE_EXTRACTION_PROMPT_VERSION = "objective_evidence_extraction.v17"
_ADAPTIVE_CONTEXT_HEADING_MARKERS = (
    "design",
    "method",
    "material",
    "experimental",
    "process",
    "processing",
    "fabricat",
    "manufactur",
    "specimen",
    "sample",
    "condition",
    "characteriz",
    "post process",
    "heat treat",
    "protocol",
    "procedure",
    "setup",
    "result",
    "analysis",
)
_ADAPTIVE_CONTEXT_TEST_MARKERS = (
    "test",
    "measure",
    "measurement",
    "assess",
    "evaluation",
    "characteriz",
    "analysis",
)
_SOURCE_EXTRACTION_ROLES = {
    "direct_result",
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
    "contradictory_result",
    "irrelevant",
}
_SOURCE_EXTRACTION_ATTRIBUTION_SCOPES = {
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
}
_SOURCE_EXTRACTION_RESULT_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_SOURCE_CONTEXT_SCOPES = {
    "experimental",
    "simulation",
    "background",
    "unknown",
}
_SOURCE_EXTRACTION_RESOLUTION_STATUSES = {
    "resolved",
    "partial",
    "unresolved",
    "skipped",
    "unknown",
}
_SOURCE_EXTRACTION_ECHOED_PROMPT_KEYS = {
    "OBJECTIVE",
    "OBJECTIVE VARIABLES",
    "OBJECTIVE OUTCOMES",
    "ROUTE HINT ONLY (DO NOT COPY AS EVIDENCE ROLE)",
    "SOURCE KIND",
    "SOURCE",
}
_SOURCE_EXTRACTION_SYSTEM_PROMPT = """
TASK MODEL
Extract every objective-relevant, source-local atomic fact from one selected
source unit, up to eight compact extractions. A Source may contain several
outcomes, condition intervals, or independent observations; preserve each one
as a separate extraction instead of dropping later facts. This is evidence
extraction, not routing, whole-paper joining, terminology canonicalization,
summarization, or Finding synthesis. The downstream consumer reconstructs the
paper's actual experiment before comparing it with other papers, so fixed
experimental context is a scientific input even when it is not the OBJECTIVE
variable.

INPUT SCHEMA AND AUTHORITY
- `OBJECTIVE` limits relevance and allowed outcomes; its variable and outcome
  names are not evidence and must not be copied when absent from SOURCE.
- `ROUTE HINT` is only a selection hint.
- `SAME-PAPER CONTEXT BUNDLE` contains additional Sources from this paper that
  a researcher would inspect together with the current Source. It may supply
  explicit material, sample, process, test, and comparison context, including
  condition endpoints that are defined in another part of the same paper. It
  is not a substitute for the current Source's reported result.
- `CONTEXT FIELDS TO CLOSE` is a checklist for the current Source plus its
  same-paper bundle. When it is non-empty, inspect both for explicit values that
  can close those fields; the checklist itself is never a scientific value and
  must not appear in the returned Evidence.
- The current `SOURCE` is the sole authority for reported result values, units,
  directions, outcomes, and `result_text`. A bundle Source may support only
  explicit context fields or condition endpoints, and those fields remain
  bound to their bundle Source reference.
- Context attributes use `{name, value, unit, context_scope}`. `context_scope`
  is `experimental` for settings applied to fabricated specimens or measured
  tests, `simulation` for model inputs or outputs, `background` for general or
  cited context, and `unknown` only when SOURCE does not establish the scope.

DECISION PROCESS
1. If SOURCE does not report an objective outcome or useful objective-specific
   context, return `{"extractions":[]}`.
2. Context source: choose its context role and return only the explicit
   context fields found in SOURCE. Return no changed variables, no comparison,
   and no reported result; use `not_attributable`. If SOURCE does not contain
   one of the requested context fields, leave that field empty rather than
   inferring it. If one SOURCE explicitly defines multiple experimental groups
   or conditions, return one context extraction per explicitly defined group.
   Put that group's exact label in `scientific_context.sample` and put only the
   process and test fields explicitly attached to that group in the same
   extraction. Repeat a shared material or test field only when SOURCE says it
   applies to all groups. Never combine multiple group labels or multiple
   condition values into parallel lists in one extraction: that loses the
   one-to-one mapping needed to join Results to Methods. If SOURCE does not
   explicitly attach a condition to a group, return the shared fact without
   inventing a pairing. If SOURCE does not distinguish separate group labels or
   separate condition records, return exactly one context extraction and never
   duplicate the same fact set. Classify explicit context by its experimental
   role: material identity and feedstock belong in `material`; build or specimen
   orientation and geometry belong in `sample`; process family, machine or
   equipment, and processing atmosphere belong in `process`; measurement method
   and measurement conditions belong in `test`. When a requested process
   context Source lists several explicit settings, extract every explicit
   process setting, including ones outside the Objective variables, and give
   each its SOURCE-supported `context_scope`; do not discard a fixed fact merely
   because it is not an OBJECTIVE variable, and do not silently omit a setting
   because it is a simulation input or a fixed control. Extract fixed
   manufacturing facts when SOURCE states that they were used for the current
   experiment, including when they were shared by every compared group. They
   define material state and cross-paper comparability; they are not changed
   variables unless SOURCE explicitly compares different values.
3. Result source: include one `reported_result` per atomic outcome. Keep the
   exact concise SOURCE term for each measured outcome in
   `reported_result.outcome`; the backend canonicalizes it to the OBJECTIVE only
   after grounding. Copy one short verbatim result clause into `result_text`.
   Set `reported_result.result_kind` to `measured` when SOURCE labels the value
   as experimental/measured, to `predicted`, `simulated`, or `modeled` when
   SOURCE labels it as a model result, and to `observed` when SOURCE reports a
   result without either explicit label. Never treat a prediction as a measured
   result.
4. Return a changed variable when either (a) this SOURCE explicitly names the
   factor and both endpoints, or (b) this SOURCE names the compared groups and
   the SAME-PAPER CONTEXT BUNDLE contains an explicit, unique one-to-one mapping
   from each group label to that factor's endpoint. In case (b), copy the exact
   endpoint values from the matching context Source and keep the context Source
   as supporting provenance; do not use a value merely because it appears in the
   same paragraph or at the same list position. Never borrow a factor or endpoint
   from the OBJECTIVE, ROUTE HINT, another paper, or general scientific
   knowledge. The current SOURCE remains the sole authority for the reported
   result value, unit, direction, outcome, and `result_text`. Set
   `comparison.comparable` to true only when every changed factor has complete
   source-grounded endpoints and the comparison context is compatible. If this
   SOURCE compares explicit group labels such as Sample S1 and Sample S2 but the
   bundle does not contain a unique mapping, keep those exact labels in
   `comparison`, set `comparable` to false with a reason that the factor levels
   are unresolved, and use `descriptive_only` or `not_attributable`. When SOURCE
   explicitly names the varied factor, use that exact factor in `axis_names`;
   otherwise use only a SOURCE-local grouping axis such as `sample`.
5. One extraction represents one baseline-to-target comparison interval. If SOURCE
   reports an ordered condition series and explicitly states how the objective
   outcome changes with that order, choose one adjacent source-supported pair. For
   named groups whose process definitions are elsewhere, copy the exact group labels,
   keep changed variables empty, name only the SOURCE-local varied axis in comparison,
   and use association_only. Use no_change when SOURCE explicitly reports no change or
   no statistically significant difference across those groups. Never convert an
   absent, off, or without condition to numeric 0; retain the exact source phrase as
   a categorical endpoint with a null unit. A complete comparison may bind endpoint
   phrases stated in separate sentences of the same SOURCE unit.
6. Never repeat a changed-variable name. Use `isolated_effect` only for one
   distinct changed factor with a complete comparable baseline/target comparison.
   Use `joint_effect` for two or more distinct changed factors. Otherwise use
   `association_only`, `descriptive_only`, or `not_attributable`. Parameters with
   identical baseline and target values are fixed context, never changed variables
   or comparison axes.
7. Return empty output rather than inventing a missing result or useful context.
   A value copied from the context bundle must be explicit in one of its
   Sources; do not merge unrelated experiments or papers.

HARD RULES
- Return exactly one compact JSON object with one top-level key: `extractions`.
- Return at most eight extractions, in Source order. Each extraction must be
  atomic: one outcome and one comparison interval (or one descriptive result).
  Do not combine unrelated outcomes into one record. Never repeat the input or
  output reasoning, markdown, source ids, or backend ids.
- Every reported result term, value, unit, direction, and `result_text` must be
  present in the current SOURCE. Context attributes and condition endpoints may
  be copied from a SAME-PAPER CONTEXT BUNDLE Source only when explicit there and
  uniquely mapped to the current Source's group labels; preserve source-local
  wording until backend canonicalization and retain the supporting Source
  reference. Do not replace a narrow observed outcome with a broader OBJECTIVE
  label.
- `result_text` is the only source text allowed in output and must be a short
  verbatim substring: one contiguous span copied from SOURCE. Never synthesize it
  from separate clauses or copy wording from a boundary example.
- A result direction describes the objective outcome, never an intermediate
  mechanism. Use `mixed` for an unordered qualitative change.
- When SOURCE mixes current work with cited literature, extract current work only.
  Conditions from cited literature are not current-work comparison conditions.
- For a direct result, return the material in `scientific_context.material` when
  SOURCE explicitly binds a material to that result. If SOURCE discusses several
  materials or cited studies and does not bind one material to the returned result,
  return no direct result. Never copy the OBJECTIVE material into this field.
- Generic composition or background is irrelevant unless OBJECTIVE explicitly
  asks about that composition, material identity, or background concept.
- For a comparable comparison, `incomparability_reasons` must be empty. For an
  incomparable comparison, provide at least one source-supported reason.
- Include `resolution_status` and numeric `confidence` for every extraction.
- Context attributes must include `context_scope` when SOURCE establishes it;
  use `unknown` only when the physical or modeled scope is genuinely unclear.
- Preserve every explicit context setting that is relevant to the selected
  experiment. `simulation` settings are auditable context but never prove an
  experimental control; use `experimental` only when SOURCE says the setting
  was applied to specimens or tests.

BOUNDARY EXAMPLES
Context source:
{"extractions":[{"evidence_role":"condition_context","changed_variables":[],"comparison":null,"reported_result":null,"attribution_scope":"not_attributable","scientific_context":{"material":[],"sample":[],"process":[{"name":"build platform temperature","value":100,"unit":"C"}],"test":[]},"resolution_status":"resolved","confidence":0.9}]}

Categorical endpoint and source-local outcome wording:
OBJECTIVE OUTCOME: crack formation
SOURCE: Cracks were abundant without preheating. Application of preheating largely reduces this cracking behavior, though cracks remain after preheating at 400 C.
OUTPUT: {"extractions":[{"evidence_role":"direct_result","changed_variables":[{"name":"preheating","baseline_value":"without preheating","target_value":"preheating at 400 C","unit":null}],"comparison":{"baseline_label":"without preheating","target_label":"preheating at 400 C","axis_names":["preheating"],"comparable":true,"incomparability_reasons":[]},"reported_result":{"outcome":"cracking behavior","value":null,"unit":null,"direction":"decrease","result_text":"Application of preheating largely reduces this cracking behavior"},"attribution_scope":"isolated_effect","scientific_context":{"material":[],"sample":[],"process":[],"test":[]},"resolution_status":"resolved","confidence":0.9}]}

Result groups whose process definitions are in another Source:
OBJECTIVE VARIABLES: laser power, scanning speed
OBJECTIVE OUTCOME: microstructure
SOURCE: Sample S1 showed equiaxed grains, whereas S2 displayed a cellular-dendritic microstructure.
OUTPUT: {"extractions":[{"evidence_role":"direct_result","changed_variables":[],"comparison":{"baseline_label":"S1","target_label":"S2","axis_names":["sample"],"comparable":false,"incomparability_reasons":["factor levels are unresolved in SOURCE"]},"reported_result":{"outcome":"cellular-dendritic microstructure","value":null,"unit":null,"direction":"mixed","result_text":"S2 displayed a cellular-dendritic microstructure"},"attribution_scope":"descriptive_only","scientific_context":{},"resolution_status":"partial","confidence":0.85}]}

Multiple condition groups in one context Source:
SOURCE: Group R0 was fabricated without treatment. Group R1 was treated at 150 C. Both groups used the same alloy and tensile test.
OUTPUT: {"extractions":[{"evidence_role":"condition_context","changed_variables":[],"comparison":null,"reported_result":null,"attribution_scope":"not_attributable","scientific_context":{"material":[{"name":"material","value":"same alloy"}],"sample":[{"name":"group","value":"R0"}],"process":[{"name":"treatment","value":"without treatment"}],"test":[{"name":"test","value":"tensile test"}]},"resolution_status":"resolved","confidence":0.9},{"evidence_role":"condition_context","changed_variables":[],"comparison":null,"reported_result":null,"attribution_scope":"not_attributable","scientific_context":{"material":[{"name":"material","value":"same alloy"}],"sample":[{"name":"group","value":"R1"}],"process":[{"name":"treatment","value":"150 C"}],"test":[{"name":"test","value":"tensile test"}]},"resolution_status":"resolved","confidence":0.9}]}

Fixed manufacturing context shared by all groups:
CONTEXT FIELDS TO CLOSE: process
SOURCE: All specimens were manufactured by laser powder bed fusion on System M in the vertical orientation under argon.
OUTPUT: {"extractions":[{"evidence_role":"condition_context","changed_variables":[],"comparison":null,"reported_result":null,"attribution_scope":"not_attributable","scientific_context":{"material":[],"sample":[{"name":"build orientation","value":"vertical","context_scope":"experimental"}],"process":[{"name":"manufacturing process","value":"laser powder bed fusion","context_scope":"experimental"},{"name":"machine","value":"System M","context_scope":"experimental"},{"name":"processing atmosphere","value":"argon","context_scope":"experimental"}],"test":[]},"resolution_status":"resolved","confidence":0.9}]}

Ordered named groups with unchanged outcome:
OBJECTIVE VARIABLES: cooling rate
OBJECTIVE OUTCOME: total elongation
SOURCE: At 800 C, groups 800-S, 800-M, and 800-F used progressively faster cooling. Total elongation was not statistically different between the three groups.
OUTPUT: {"extractions":[{"evidence_role":"direct_result","changed_variables":[],"comparison":{"baseline_label":"800-M","target_label":"800-F","axis_names":["cooling rate"],"comparable":true,"incomparability_reasons":[]},"reported_result":{"outcome":"total elongation","value":null,"unit":null,"direction":"no_change","result_text":"Total elongation was not statistically different between the three groups"},"attribution_scope":"association_only","scientific_context":{},"resolution_status":"partial","confidence":0.85}]}

Directional result groups whose process values are in another Source:
OBJECTIVE VARIABLES: energy input
OBJECTIVE OUTCOME: ductility
SOURCE: With decreasing laser power, elongation decreases from 20.1% (200-1000) to 17.0% (200-850).
OUTPUT: {"extractions":[{"evidence_role":"direct_result","changed_variables":[],"comparison":{"baseline_label":"200-1000","target_label":"200-850","axis_names":["laser power"],"comparable":true,"incomparability_reasons":[]},"reported_result":{"outcome":"elongation","value":17.0,"baseline_value":20.1,"target_value":17.0,"unit":"%","direction":"decrease","result_text":"elongation decreases from 20.1% (200-1000) to 17.0% (200-850)"},"attribution_scope":"association_only","scientific_context":{},"resolution_status":"partial","confidence":0.9}]}

Joint result source:
{"extractions":[{"evidence_role":"direct_result","changed_variables":[{"name":"laser power","baseline_value":100,"target_value":200,"unit":"W"},{"name":"scan speed","baseline_value":500,"target_value":900,"unit":"mm/s"}],"comparison":{"baseline_label":"A","target_label":"B","axis_names":["laser power","scan speed"],"comparable":true,"incomparability_reasons":[]},"reported_result":{"outcome":"relative density","value":98.0,"unit":"%","direction":"increase","result_text":"relative density increased to 98.0%"},"attribution_scope":"joint_effect","scientific_context":{"material":[],"sample":[],"process":[],"test":[]},"resolution_status":"resolved","confidence":0.9}]}

Unsupported or ambiguous source:
{"extractions":[]}

Unrelated composition example:
OBJECTIVE OUTCOME: fatigue life
ROUTE HINT: composition_or_background
SOURCE: The nominal alloy composition contains chromium and nickel.
OUTPUT: {"extractions":[]}

OUTPUT CONTRACT
Allowed result directions are `increase`, `decrease`, `improve`, `worsen`,
`no_change`, `mixed`, and `unknown`. Allowed resolution statuses are `resolved`,
`partial`, `unresolved`, `skipped`, and `unknown`. Return up to eight compact
atomic objects in Source order. If the Source contains no supported fact, return
`{"extractions":[]}`.
""".strip()

_SOURCE_CONTEXT_EXTRACTION_SYSTEM_PROMPT = """
TASK MODEL
You transcribe facts for one requested experimental-context family from one
Methods or characterization Source. This is not result extraction, causal
attribution, or classification of adjacent context families.

INPUT
`CONTEXT FAMILY` names the single requested family but supplies no scientific
values. `SOURCE` is the only authority for returned values.

DECISION PROCESS
1. Read only SOURCE.
2. Transcribe only facts belonging to CONTEXT FAMILY; ignore adjacent material,
   sample, process, result, or test facts that belong to another family.
3. Keep fixed conditions even when they are not varied and are shared by every
   compared group.
4. When SOURCE explicitly attaches a fact to a named group, copy that exact
   label to `group_label`; otherwise use null.
5. If SOURCE has no explicit fact in CONTEXT FAMILY, return `{"facts":[]}`.

HARD RULES
- Return one JSON object with only `facts`; return no more than sixteen.
- Every value must be explicit in SOURCE. Do not infer missing facts.
- Context applied to fabricated specimens or measured tests uses
  `context_scope: "experimental"`; modeled settings use `"simulation"`.
- Do not duplicate a fact or invent groups from a plural word.

OUTPUT SHAPE
{"facts":[{"name":"descriptive field name","value":"exact SOURCE value","unit":null,"context_scope":"experimental","group_label":null}]}
Replace the descriptive strings with SOURCE facts. Do not return the example
strings literally.
""".strip()


def _provider_is_temporarily_unavailable(error: Exception) -> bool:
    if isinstance(error, APIConnectionError):
        return True
    if not isinstance(error, APIStatusError):
        return False
    status_code = int(error.status_code)
    return status_code in {408, 409, 429} or status_code >= 500


def _normalize_underscored_choice(
    value: object,
    *,
    allowed: set[str],
    default: str,
) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _normalize_list_container(value: object) -> object:
    return [] if value is None else value


class _SourceExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)


ScientificScalar = str | int | float | bool


class StructuredEvidenceAttribute(_SourceExtractionResponse):
    name: str
    value: ScientificScalar
    unit: str | None = None
    context_scope: Literal["experimental", "simulation", "background", "unknown"] = (
        "unknown"
    )

    @field_validator("context_scope", mode="before")
    @classmethod
    def _normalize_context_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_SOURCE_CONTEXT_SCOPES,
            default="unknown",
        )


class StructuredEvidenceVariable(_SourceExtractionResponse):
    name: str
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    unit: str | None = None


class StructuredEvidenceComparison(_SourceExtractionResponse):
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


class StructuredEvidenceResult(_SourceExtractionResponse):
    outcome: str
    value: ScientificScalar | None = None
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
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
    result_kind: Literal[
        "measured",
        "observed",
        "predicted",
        "simulated",
        "modeled",
        "unknown",
    ] = "observed"

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_SOURCE_EXTRACTION_RESULT_DIRECTIONS,
            default="unknown",
        )

    @field_validator("result_kind", mode="before")
    @classmethod
    def _normalize_result_kind(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed={
                "measured",
                "observed",
                "predicted",
                "simulated",
                "modeled",
                "unknown",
            },
            default="observed",
        )


class StructuredEvidenceContext(_SourceExtractionResponse):
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
            context_scope = item.get("context_scope")

            def with_context_scope(attribute: dict[str, object]) -> dict[str, object]:
                if context_scope is not None:
                    attribute["context_scope"] = context_scope
                return attribute

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
                    with_context_scope(
                        {"name": name, "value": attribute_value, "unit": unit}
                    )
                )
                continue

            details = {
                key: detail
                for key, detail in item.items()
                if key not in {"name", "unit"}
            }
            normalized_items.append(
                with_context_scope(
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
            )
        return normalized_items


class StructuredRequestedContextFact(StructuredEvidenceAttribute):
    context_scope: Literal["experimental", "simulation", "background", "unknown"]
    group_label: str | None = None


class StructuredRequestedContextFacts(_SourceExtractionResponse):
    facts: list[StructuredRequestedContextFact] = Field(
        default_factory=list,
        max_length=16,
    )

    @field_validator("facts", mode="before")
    @classmethod
    def _normalize_facts(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredEvidenceExtraction(_SourceExtractionResponse):
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

    @field_validator("evidence_role", mode="before")
    @classmethod
    def _normalize_evidence_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_SOURCE_EXTRACTION_ROLES,
            default="irrelevant",
        )

    @field_validator("attribution_scope", mode="before")
    @classmethod
    def _normalize_attribution_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_SOURCE_EXTRACTION_ATTRIBUTION_SCOPES,
            default="not_attributable",
        )

    @field_validator("resolution_status", mode="before")
    @classmethod
    def _normalize_resolution_status(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_SOURCE_EXTRACTION_RESOLUTION_STATUSES,
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
        variable_names = [item.name.casefold() for item in self.changed_variables]
        if len(variable_names) != len(set(variable_names)):
            raise ValueError("changed variable names must be unique per extraction")
        if any(
            item.baseline_value is not None
            and item.target_value is not None
            and item.baseline_value == item.target_value
            for item in self.changed_variables
        ):
            raise ValueError(
                "changed variables require distinct baseline and target values"
            )
        if self.attribution_scope in {"isolated_effect", "joint_effect"}:
            if self.comparison is None or not self.comparison.comparable:
                raise ValueError("experimental attribution requires comparison")
            variables = set(variable_names)
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
            if self.attribution_scope == "isolated_effect" and len(variables) != 1:
                raise ValueError("isolated effect requires one changed variable")
            if self.attribution_scope == "joint_effect" and len(variables) < 2:
                raise ValueError("joint effect requires multiple changed variables")
        return self


class StructuredEvidenceExtractions(_SourceExtractionResponse):
    extractions: list[StructuredEvidenceExtraction] = Field(
        default_factory=list,
        max_length=_SOURCE_EXTRACTION_MAX_ITEMS,
    )

    @field_validator("extractions", mode="before")
    @classmethod
    def _normalize_extractions(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredDirectEvidenceResult(StructuredEvidenceResult):
    """Result-route fields that must be explicit in model output."""

    direction: Literal[
        "increase",
        "decrease",
        "improve",
        "worsen",
        "no_change",
        "mixed",
        "unknown",
    ]


class StructuredDirectEvidenceExtraction(StructuredEvidenceExtraction):
    """Result-route contract requiring a source-backed reported result."""

    reported_result: StructuredDirectEvidenceResult


class StructuredDirectEvidenceExtractions(_SourceExtractionResponse):
    extractions: list[StructuredDirectEvidenceExtraction] = Field(
        default_factory=list,
        max_length=_SOURCE_EXTRACTION_MAX_ITEMS,
    )

    @field_validator("extractions", mode="before")
    @classmethod
    def _normalize_extractions(cls, value: object) -> object:
        return _normalize_list_container(value)


_DIRECT_RESULT_ROUTE_ROLES = {
    "current_experimental_evidence",
    "direct_result",
    "contradictory_result",
}
_OBJECTIVE_CONTEXT_ROLES = frozenset(
    {
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
    }
)
_OBJECTIVE_CONTEXT_FIELD_NAMES = frozenset(
    {"material", "sample", "variable", "process", "comparison", "test", "outcome"}
)
_OBJECTIVE_ROUTE_DEFAULT_CONTEXT_FIELDS = {
    "process_or_treatment": ("process",),
    "test_condition": ("test",),
    "characterization": ("test",),
}
_OBJECTIVE_CONTEXT_FAMILY_GUIDANCE = {
    "material": "material identity, alloy composition, or feedstock",
    "sample": "sample identity, specimen geometry, or build/test orientation",
    "process": (
        "manufacturing or process family, machine or equipment, treatment, "
        "processing atmosphere, or fixed process setting"
    ),
    "test": "measurement, test, or characterization method and its conditions",
}
_OBJECTIVE_CONTEXT_FAMILY_EXCLUSIONS = {
    "material": "sample geometry, manufacturing process, and test method",
    "sample": "material identity, manufacturing process or machine, and test method",
    "process": (
        "material or feedstock identity, specimen or build orientation and "
        "geometry, and measurement or test method"
    ),
    "test": "material identity, specimen geometry, and manufacturing process",
}
_ADAPTIVE_CONTEXT_NEIGHBOR_RADIUS = 3


def _objective_route_requires_reported_result(payload: Mapping[str, Any]) -> bool:
    route = payload.get("evidence_route")
    if not isinstance(route, Mapping):
        return False
    return str(route.get("role") or "").strip().casefold() in {
        role.casefold() for role in _DIRECT_RESULT_ROUTE_ROLES
    }


def _objective_route_narrow_context_field(
    payload: Mapping[str, Any],
) -> str | None:
    route = payload.get("evidence_route")
    if not isinstance(route, Mapping):
        return None
    role = str(route.get("role") or "").strip().casefold()
    if role not in _OBJECTIVE_ROUTE_DEFAULT_CONTEXT_FIELDS:
        return None
    explicit_fields = tuple(
        str(field).strip().casefold()
        for field in route.get("context_fields", ())
        if str(field).strip().casefold() in _OBJECTIVE_CONTEXT_FIELD_NAMES
    )
    context_fields = explicit_fields or _OBJECTIVE_ROUTE_DEFAULT_CONTEXT_FIELDS[role]
    return (
        context_fields[0]
        if len(context_fields) == 1
        and context_fields[0] in {"material", "sample", "process", "test"}
        else None
    )


def _objective_context_repair_instruction(
    *,
    repair_detail: str,
    context_field: str,
) -> str:
    return (
        "Your previous context transcription was invalid. Re-read the original "
        f"SOURCE and transcribe only `{context_field}` facts. Return one compact "
        "JSON object with only `facts`; each fact requires name, value, unit, "
        "context_scope, and group_label. Do not return adjacent context families "
        "and do not duplicate a fact. If SOURCE has no explicit requested fact, "
        "return {\"facts\":[]}. Do not add facts absent from "
        f"SOURCE. Validation error: {repair_detail[:1000]}"
    )


def _objective_context_facts_as_extractions(
    parsed: StructuredRequestedContextFacts,
    *,
    context_field: str,
) -> StructuredEvidenceExtractions:
    if not parsed.facts:
        return StructuredEvidenceExtractions()
    grouped_facts: dict[str | None, list[dict[str, Any]]] = {}
    for fact in parsed.facts:
        group_label = str(fact.group_label or "").strip() or None
        grouped_facts.setdefault(group_label, []).append(
            fact.model_dump(mode="json", exclude={"group_label"})
        )
    extractions: list[dict[str, Any]] = []
    for group_label, facts in grouped_facts.items():
        scientific_context: dict[str, list[dict[str, Any]]] = {
            "material": [],
            "sample": [],
            "process": [],
            "test": [],
        }
        scientific_context[context_field] = facts
        if group_label is not None and context_field != "sample":
            scientific_context["sample"] = [
                {
                    "name": "group",
                    "value": group_label,
                    "unit": None,
                    "context_scope": facts[0]["context_scope"],
                }
            ]
        extractions.append(
            {
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": scientific_context,
                "resolution_status": "resolved",
            }
        )
    return StructuredEvidenceExtractions.model_validate(
        {"extractions": extractions}
    )


def build_objective_evidence_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    objective = (
        payload.get("objective")
        if isinstance(payload.get("objective"), dict)
        else {}
    )
    route = (
        payload.get("evidence_route")
        if isinstance(payload.get("evidence_route"), dict)
        else {}
    )
    source = (
        payload.get("source") if isinstance(payload.get("source"), dict) else {}
    )
    if str(source.get("source_kind") or route.get("source_kind") or "") == "table":
        source_text = "\n\n".join(
            part
            for part in (
                f"CAPTION: {str(source.get('caption_text') or '').strip()}"
                if str(source.get("caption_text") or "").strip()
                else "",
                f"HEADING: {str(source.get('heading_path') or '').strip()}"
                if str(source.get("heading_path") or "").strip()
                else "",
                str(source.get("table_markdown") or "").strip(),
                (
                    "PDF LAYOUT TEXT (same table region; use only to resolve "
                    "wrapped rows):\n"
                    + str(source.get("table_visual_text") or "").strip()
                )
                if str(source.get("table_visual_text") or "").strip()
                else "",
            )
            if part
        )
    else:
        source_text = str(source.get("text") or "").strip()
    explicit_context_fields = tuple(
        str(field).strip().casefold()
        for field in route.get("context_fields", ())
        if str(field).strip().casefold() in _OBJECTIVE_CONTEXT_FIELD_NAMES
    )
    route_role = str(route.get("role") or "").strip().casefold()
    context_fields = explicit_context_fields or _OBJECTIVE_ROUTE_DEFAULT_CONTEXT_FIELDS.get(
        route_role,
        (),
    )
    context_fields_text = json.dumps(
        list(dict.fromkeys(context_fields)),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if not source_text:
        source_text = json.dumps(
            {
                key: source[key]
                for key in (
                    "source_kind",
                    "page",
                    "heading_path",
                    "column_headers",
                    "table_markdown",
                    "table_visual_text",
                )
                if source.get(key) not in (None, "", [], {})
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    narrow_context_field = _objective_route_narrow_context_field(payload)
    if narrow_context_field is not None:
        user_prompt = (
            f"CONTEXT FAMILY: {narrow_context_field}\n"
            "INCLUDE ONLY: "
            f"{_OBJECTIVE_CONTEXT_FAMILY_GUIDANCE[narrow_context_field]}\n"
            "EXCLUDE: "
            f"{_OBJECTIVE_CONTEXT_FAMILY_EXCLUSIONS[narrow_context_field]}\n"
            "SOURCE KIND: "
            f"{str(source.get('source_kind') or route.get('source_kind') or '').strip()}\n"
            f"SOURCE:\n{source_text}\n"
            "OUTPUT JSON:"
        )
        return _SOURCE_CONTEXT_EXTRACTION_SYSTEM_PROMPT, user_prompt
    context_bundle = payload.get("same_paper_context_bundle")
    if not isinstance(context_bundle, list):
        context_bundle = []
    context_bundle_text = json.dumps(
        context_bundle,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    user_prompt = (
        f"OBJECTIVE QUESTION: {str(objective.get('question') or '').strip()}\n"
        "OBJECTIVE VARIABLES: "
        f"{json.dumps(objective.get('variables') or [], ensure_ascii=False, separators=(',', ':'))}\n"
        "OBJECTIVE OUTCOMES: "
        f"{json.dumps(objective.get('outcomes') or [], ensure_ascii=False, separators=(',', ':'))}\n"
        "ROUTE HINT ONLY (DO NOT COPY AS EVIDENCE ROLE): "
        f"{str(route.get('role') or '').strip()}\n"
        "CONTEXT FIELDS TO CLOSE (SOURCE MUST SUPPORT THEM): "
        f"{context_fields_text}\n"
        "SOURCE KIND: "
        f"{str(source.get('source_kind') or route.get('source_kind') or '').strip()}\n"
        f"SOURCE:\n{source_text}\n"
        "SAME-PAPER CONTEXT BUNDLE (CONTEXT ONLY):\n"
        f"{context_bundle_text}\n"
        "OUTPUT JSON:"
    )
    return _SOURCE_EXTRACTION_SYSTEM_PROMPT, user_prompt


def _normalize_objective_evidence_payload(payload: Any) -> Any:
    def identical_nonempty_scalar(left: Any, right: Any) -> bool:
        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left == right
        if isinstance(left, str) and isinstance(right, str):
            return bool(left.strip()) and left == right
        return False

    def complete_changed_variable_names(
        variables: list[Any],
    ) -> tuple[str, ...]:
        def is_complete_scalar(value: Any) -> bool:
            if isinstance(value, str):
                return bool(value.strip())
            return isinstance(value, (int, float, bool))

        names: list[str] = []
        seen: set[str] = set()
        for variable in variables:
            if not isinstance(variable, Mapping):
                return ()
            name = str(variable.get("name") or "").strip()
            baseline = variable.get("baseline_value")
            target = variable.get("target_value")
            if (
                not name
                or not is_complete_scalar(baseline)
                or not is_complete_scalar(target)
                or identical_nonempty_scalar(baseline, target)
            ):
                return ()
            canonical_name = name.casefold()
            if canonical_name in seen:
                return ()
            seen.add(canonical_name)
            names.append(name)
        return tuple(names)

    if not isinstance(payload, Mapping):
        return payload
    extractions = payload.get("extractions")
    if not isinstance(extractions, list):
        return payload

    changed = False
    normalized_extractions: list[Any] = []
    for extraction in extractions:
        if not isinstance(extraction, Mapping):
            normalized_extractions.append(extraction)
            continue
        normalized_extraction = dict(extraction)
        variables = normalized_extraction.get("changed_variables")
        scientific_context = normalized_extraction.get("scientific_context")
        has_context_fact = isinstance(scientific_context, Mapping) and any(
            isinstance(scientific_context.get(family), list)
            and bool(scientific_context.get(family))
            for family in _OBJECTIVE_CONTEXT_FIELD_NAMES
        )
        if (
            str(normalized_extraction.get("evidence_role") or "")
            in _DIRECT_RESULT_ROUTE_ROLES
            and normalized_extraction.get("reported_result") is None
            and not variables
            and normalized_extraction.get("comparison") is None
            and has_context_fact
        ):
            # Role selection is model metadata, while the context values still
            # pass deterministic Source grounding below. Preserve an otherwise
            # valid Methods/sample transcription as context instead of losing
            # the complete Source to schema failure. This never upgrades the
            # route to result Evidence: the selected result remains unresolved
            # until a Source-backed reported_result is extracted.
            normalized_extraction.update(
                {
                    "evidence_role": "condition_context",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                }
            )
            variables = normalized_extraction["changed_variables"]
            changed = True
        if not isinstance(variables, list):
            normalized_extractions.append(normalized_extraction)
            continue

        fixed_names: set[str] = set()
        changed_variables: list[Any] = []
        for variable in variables:
            if not isinstance(variable, Mapping):
                changed_variables.append(variable)
                continue
            baseline = variable.get("baseline_value")
            target = variable.get("target_value")
            variable_name = str(variable.get("name") or "").strip().casefold()
            if not variable_name or not identical_nonempty_scalar(
                baseline,
                target,
            ):
                changed_variables.append(variable)
                continue
            fixed_names.add(variable_name)
            changed = True

        if fixed_names:
            normalized_extraction["changed_variables"] = changed_variables
        remaining_variable_names = {
            str(variable.get("name") or "").strip().casefold()
            for variable in changed_variables
            if isinstance(variable, Mapping)
            and str(variable.get("name") or "").strip()
        }
        comparison = extraction.get("comparison")
        if isinstance(comparison, Mapping) and isinstance(
            comparison.get("axis_names"), list
        ):
            normalized_comparison = dict(comparison)
            normalized_comparison["axis_names"] = [
                axis
                for axis in comparison["axis_names"]
                if str(axis).strip().casefold() not in fixed_names
                or str(axis).strip().casefold() in remaining_variable_names
            ]
            normalized_extraction["comparison"] = normalized_comparison
        comparison = normalized_extraction.get("comparison")
        if isinstance(comparison, Mapping):
            axis_names = comparison.get("axis_names")
            missing_axis_names = axis_names is None or (
                isinstance(axis_names, list)
                and not any(str(axis).strip() for axis in axis_names)
            )
            recovered_axis_names = (
                complete_changed_variable_names(changed_variables)
                if missing_axis_names
                else ()
            )
            if recovered_axis_names:
                normalized_comparison = dict(comparison)
                normalized_comparison["axis_names"] = list(recovered_axis_names)
                normalized_extraction["comparison"] = normalized_comparison
                changed = True
        comparison = normalized_extraction.get("comparison")
        complete_variable_names = complete_changed_variable_names(changed_variables)
        if (
            extraction.get("reported_result") is not None
            and extraction.get("attribution_scope")
            in {"isolated_effect", "joint_effect"}
            and not complete_variable_names
        ):
            normalized_extraction["attribution_scope"] = (
                "association_only"
                if isinstance(comparison, Mapping)
                and comparison.get("comparable") is True
                else (
                    "not_attributable"
                    if isinstance(comparison, Mapping)
                    else "descriptive_only"
                )
            )
            normalized_extraction["resolution_status"] = "partial"
            changed = True
        comparison_has_no_axes = (
            isinstance(comparison, Mapping)
            and isinstance(comparison.get("axis_names"), list)
            and not any(str(axis).strip() for axis in comparison["axis_names"])
        )
        if not changed_variables and (fixed_names or comparison_has_no_axes):
            normalized_extraction["comparison"] = None
            if extraction.get("attribution_scope") in {
                "isolated_effect",
                "joint_effect",
                "association_only",
            }:
                normalized_extraction["attribution_scope"] = (
                    "descriptive_only"
                    if extraction.get("reported_result") is not None
                    else "not_attributable"
                )
            changed = True
        if (
            extraction.get("attribution_scope") == "joint_effect"
            and len(changed_variables) == 1
            and len(remaining_variable_names) == 1
        ):
            normalized_extraction["attribution_scope"] = "isolated_effect"
        normalized_extractions.append(normalized_extraction)

    if not changed:
        return payload
    normalized_payload = dict(payload)
    normalized_payload["extractions"] = normalized_extractions
    return normalized_payload


def _first_objective_evidence_extraction(
    payload: Any,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    extractions = payload.get("extractions")
    if not isinstance(extractions, list) or not extractions:
        return None
    item = extractions[0]
    return dict(item) if isinstance(item, Mapping) else None


def _objective_evidence_repair_instruction(
    *,
    repair_detail: str,
    invalid_extraction: Mapping[str, Any] | None,
) -> str:
    invalid_json = (
        json.dumps(
            dict(invalid_extraction),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if invalid_extraction is not None
        else "null"
    )
    return (
        "TASK\nRepair invalid Evidence extractions against the original SOURCE "
        "and its explicit SAME-PAPER CONTEXT BUNDLE. "
        "This is correction of the supplied candidates, not a new Source search "
        "or a new extraction task. Preserve every valid extraction and repair or "
        "remove only entries named by the validation error.\n"
        "REPAIR INPUT\n"
        f"- VALIDATION ERRORS: {repair_detail[:1000]}\n"
        f"- INVALID EXTRACTION: {invalid_json}\n"
        "DECISION PROCESS\n"
        "1. Check result fields against SOURCE and context fields or comparison "
        "endpoints against SOURCE plus its SAME-PAPER CONTEXT BUNDLE; keep every valid "
        "field unchanged.\n"
        "2. Correct a result field only when its replacement is explicit in SOURCE. "
        "A context field or comparison endpoint may use a bundle Source only when "
        "it is explicitly and uniquely mapped to a group named by SOURCE. "
        "When SOURCE does not support a valid correction, remove the unsupported "
        "claim only if the remaining item still has honest scientific meaning; "
        "otherwise abstain with {\"extractions\":[]}.\n"
        "3. A validation error saying `result evidence requires one reported result` "
        "means `direct_result` requires reported_result. Re-read SOURCE and return "
        "a complete direct_result object with `reported_result.outcome` and one "
        "contiguous verbatim `reported_result.result_text` copied from SOURCE. "
        "Include the result direction only when SOURCE states it. Do not return a "
        "direct_result object containing only scientific_context or changed_variables. "
        "If SOURCE has no objective result sentence, return an empty extraction or "
        "change the item to a context role with reported_result null.\n"
        "4. If `reported_result` is non-null, use `direct_result` or "
        "`contradictory_result` as `evidence_role`. If keeping a context role, "
        "set `reported_result` to null, `changed_variables` to [], `comparison` "
        "to null, and `attribution_scope` to `not_attributable`.\n"
        "5. `isolated_effect` and `joint_effect` require distinct baseline and "
        "target values for every changed variable. `comparison.axis_names` must "
        "exactly match the distinct `changed_variables` names. If SOURCE lacks "
        "complete endpoints, use `association_only` only for an explicit "
        "association; otherwise use `descriptive_only` or abstain.\n"
        "6. If `comparison.comparable` is false, use `not_attributable`; do not "
        "change it to true unless SOURCE explicitly supports a complete "
        "comparison. Remove each fixed parameter from `changed_variables` and "
        "`comparison.axis_names` when its endpoints are identical. A fixed "
        "control does not make the comparison incomparable. For a condition "
        "series, choose one complete Source-supported interval.\n"
        "HARD RULES\n"
        "- Correct only values supported by SOURCE or an explicitly matched "
        "SAME-PAPER CONTEXT BUNDLE Source; do not invent comparison endpoints or "
        "scientific context. Reported results must remain in SOURCE.\n"
        "- A fixed parameter is fixed context, not a changed variable.\n"
        "- For a condition series, choose one complete source-supported interval "
        "and never merge separate intervals.\n"
        "- Preserve valid fields that do not require correction.\n"
        "BOUNDARY EXAMPLES\n"
        "- If candidate target is 160 W but SOURCE explicitly compares 100 W "
        "with 140 W, 140 W may replace 160 W; other grounded fields stay fixed.\n"
        "- If candidate unit is MPa but SOURCE gives no unit, set that unit to "
        "null only when the remaining result is still meaningful; never infer a "
        "unit from domain knowledge.\n"
        "- If SOURCE contains no complete comparison or attributable result, "
        "return {\"extractions\":[]}.\n"
        "OUTPUT SCHEMA\nReturn only "
        "{\"extractions\":[<up to eight corrected atomic extractions>]} or "
        "{\"extractions\":[]}."
    )


class ObjectiveSourceExtractor:
    """Extract bounded atomic facts from one primary Source.

    A later context revisit may supply an explicit same-paper Evidence Bundle
    for validating conditions; the primary Source still owns measured results.
    """

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def extract_source(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceExtractions:
        system_prompt, user_prompt = build_objective_evidence_prompt(payload)
        narrow_context_field = _objective_route_narrow_context_field(payload)
        response_model: type[BaseModel] = StructuredEvidenceExtractions
        json_text_parser = self._parse_json_response
        if narrow_context_field is not None:
            response_model = StructuredRequestedContextFacts
            json_text_parser = partial(
                self._parse_context_json_response,
                context_field=narrow_context_field,
            )
        elif _objective_route_requires_reported_result(payload):
            response_model = StructuredDirectEvidenceExtractions
        response = self.response_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            max_completion_tokens=_SOURCE_EXTRACTION_MAX_COMPLETION_TOKENS,
            force_json_text=True,
            include_schema_for_forced_json=False,
            json_text_parser=json_text_parser,
            task_type="objective_evidence_extraction",
            prompt_version=OBJECTIVE_SOURCE_EXTRACTION_PROMPT_VERSION,
        )
        if isinstance(response, StructuredRequestedContextFacts):
            if narrow_context_field is None:
                raise TypeError("context extraction returned without a context field")
            return _objective_context_facts_as_extractions(
                response,
                context_field=narrow_context_field,
            )
        if isinstance(response, StructuredDirectEvidenceExtractions):
            return StructuredEvidenceExtractions.model_validate(response.model_dump())
        if not isinstance(response, StructuredEvidenceExtractions):
            raise TypeError("unexpected objective evidence extraction response type")
        return response

    def _parse_json_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
    ) -> tuple[BaseModel, str | None]:
        last_invalid_extraction: dict[str, Any] | None = None

        def normalize_payload(payload: Any) -> Any:
            nonlocal last_invalid_extraction
            normalized = _normalize_objective_evidence_payload(payload)
            last_invalid_extraction = _first_objective_evidence_extraction(
                normalized
            )
            if not isinstance(normalized, dict):
                return normalized
            extractions = normalized.get("extractions")
            extra_keys = set(normalized) - {"extractions"}
            if (
                isinstance(extractions, list)
                and extra_keys
                and extra_keys <= _SOURCE_EXTRACTION_ECHOED_PROMPT_KEYS
            ):
                return {"extractions": extractions}
            if (
                "extractions" not in normalized
                and normalized
                and set(normalized) <= _SOURCE_EXTRACTION_ECHOED_PROMPT_KEYS
            ):
                raise ValueError(
                    "objective evidence response echoed input fields instead of "
                    "returning extractions"
                )
            return normalized

        def build_repair_instruction(repair_detail: str) -> str:
            if "echoed input fields" in repair_detail:
                return (
                    "Your previous response only echoed the input fields and did "
                    "not perform evidence extraction. Do not repeat OBJECTIVE, "
                    "OBJECTIVE VARIABLES, OBJECTIVE OUTCOMES, ROUTE HINT, SOURCE "
                    "KIND, or SOURCE. Re-read SOURCE and return one compact "
                    "JSON object with the single top-level key `extractions`. Use "
                    "{\"extractions\":[]} only when SOURCE contains no comparison "
                    "that answers the objective."
                )
            return _objective_evidence_repair_instruction(
                repair_detail=repair_detail,
                invalid_extraction=last_invalid_extraction,
            )

        return self.response_client.complete_json(
            messages=messages,
            response_model=response_model,
            max_completion_tokens=max_completion_tokens,
            repair_instruction_builder=build_repair_instruction,
            payload_normalizer=normalize_payload,
            max_attempts=3,
            json_schema_name="structured_evidence_extractions",
        )

    def _parse_context_json_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
        context_field: str,
    ) -> tuple[BaseModel, str | None]:
        return self.response_client.complete_json(
            messages=messages,
            response_model=response_model,
            max_completion_tokens=max_completion_tokens,
            repair_instruction_builder=partial(
                _objective_context_repair_instruction,
                context_field=context_field,
            ),
            max_attempts=3,
            json_schema_name="structured_requested_context_facts",
        )


@dataclass(frozen=True)
class ExtractedEvidenceDraft:
    """Transient structured extraction before Source text is attached."""

    evidence_id: str
    objective_id: str
    document_id: str
    source_kind: str | None
    source_ref: str | None
    evidence_role: str | None
    selection_reason: str | None
    selection_status: str
    changed_variables: tuple[ObjectiveEvidenceVariable, ...]
    comparison: ObjectiveEvidenceComparison | None
    reported_result: ObjectiveEvidenceResult | None
    attribution_scope: str
    scientific_context: ObjectiveEvidenceContext
    source_refs: tuple[dict[str, Any], ...]
    evidence_anchor_ids: tuple[str, ...]
    resolution_status: str
    failure_reason: str | None
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExtractedEvidenceDraft":
        source_refs = _mapping_tuple(payload.get("source_refs"))
        first_source_ref = source_refs[0] if source_refs else {}
        objective_id = _text(payload.get("objective_id"))
        document_id = _text(payload.get("document_id"))
        source_kind = _optional_text(
            payload.get("source_kind") or first_source_ref.get("source_kind")
        )
        source_ref = _optional_text(
            payload.get("source_ref") or first_source_ref.get("source_ref")
        )
        evidence_role = _optional_text(
            payload.get("evidence_role") or first_source_ref.get("evidence_role")
        )
        reported_result_payload = payload.get("reported_result")
        reported_result = (
            ObjectiveEvidenceResult.from_mapping(reported_result_payload)
            if isinstance(reported_result_payload, Mapping)
            else None
        )
        evidence_id = _optional_text(payload.get("evidence_id"))
        if evidence_id is None:
            # A context Source can legitimately yield multiple facts (for
            # example one condition record for S1 and another for S2). Keep
            # those facts distinct without changing the stable identity of a
            # result while it gains same-paper context during reconstruction.
            context_identity = (
                payload.get("scientific_context")
                if reported_result is None
                and _text(payload.get("evidence_role")) in _OBJECTIVE_CONTEXT_ROLES
                else None
            )
            identity = json.dumps(
                [
                    objective_id,
                    document_id,
                    evidence_role,
                    source_refs,
                    context_identity,
                    payload.get("changed_variables"),
                    payload.get("comparison"),
                    payload.get("reported_result"),
                ],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            evidence_id = f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        return cls(
            evidence_id=evidence_id,
            objective_id=objective_id,
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            evidence_role=evidence_role,
            selection_reason=_optional_text(
                payload.get("selection_reason")
                or first_source_ref.get("selection_reason")
            ),
            selection_status=_text(payload.get("selection_status")) or "extracted",
            changed_variables=tuple(
                ObjectiveEvidenceVariable.from_mapping(item)
                for item in payload.get("changed_variables", ())
                if isinstance(item, Mapping)
            ),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=reported_result,
            attribution_scope=_text(payload.get("attribution_scope"))
            or "not_attributable",
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ObjectiveEvidenceContext()
            ),
            source_refs=source_refs,
            evidence_anchor_ids=normalize_objective_terms(
                payload.get("evidence_anchor_ids")
            ),
            resolution_status=_text(payload.get("resolution_status")) or "unknown",
            failure_reason=_optional_text(payload.get("failure_reason")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "evidence_role": self.evidence_role,
            "selection_reason": self.selection_reason,
            "selection_status": self.selection_status,
            "changed_variables": [item.to_record() for item in self.changed_variables],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "attribution_scope": self.attribution_scope,
            "scientific_context": self.scientific_context.to_record(),
            "source_refs": [dict(item) for item in self.source_refs],
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "resolution_status": self.resolution_status,
            "failure_reason": self.failure_reason,
            "confidence": self.confidence,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


_EXTRACTION_ROUTE_ROLE_PRIORITY = {
    "current_experimental_evidence": 5,
    "contradictory_result": 5,
    "characterization": 4,
    "process_or_treatment": 3,
    "test_condition": 3,
    "condition_context": 3,
    "comparison_context": 3,
    "baseline_context": 3,
    "mechanism_context": 2,
    "background_context": 1,
}


def _dedupe_extraction_routes(
    routes: tuple[EvidenceCandidate, ...],
) -> tuple[EvidenceCandidate, ...]:
    """Keep one extraction decision per stable Source locator.

    Routing may mention the same Source through framing, a table hint, and
    adaptive context expansion.  The Source is still one research object, so
    reading it repeatedly would inflate Evidence and could produce divergent
    facts.  Prefer the route with the most specific scientific role while
    keeping the first route's stable order for ties.
    """

    selected: dict[tuple[str, str, str, str], EvidenceCandidate] = {}
    for route in routes:
        key = (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
        )
        existing = selected.get(key)
        if existing is None:
            selected[key] = route
            continue
        existing_priority = _EXTRACTION_ROUTE_ROLE_PRIORITY.get(existing.role, 0)
        route_priority = _EXTRACTION_ROUTE_ROLE_PRIORITY.get(route.role, 0)
        if route_priority > existing_priority:
            selected[key] = route
    return tuple(selected.values())


def extract_and_validate_source_facts(
    *,
    collection_id: str,
    source_extractor: ObjectiveSourceExtractor,
    paper_facts_extractor: PaperFactsExtractor | None = None,
    objectives: tuple[ResearchObjective, ...],
    objective_paper_frames: tuple[PaperAnalysisFrame, ...],
    objective_evidence_routes: tuple[EvidenceCandidate, ...],
    blocks_by_document_id: dict[str, list[Any]],
    tables_by_document_id: dict[str, list[Any]],
    figures_by_document_id: dict[str, list[Any]] | None = None,
    document_trees_by_document_id: dict[str, SourceDocumentTree],
    table_cells_by_document_id: dict[str, list[Any]] | None = None,
    progress_callback: ProgressCallback | None = None,
    _allow_adaptive_context_expansion: bool = True,
    _document_state_seed: tuple[ExtractedEvidenceDraft, ...] = (),
) -> tuple[ExtractedEvidenceDraft, ...]:
    objective_by_id = {objective.objective_id: objective for objective in objectives}
    frame_by_key = {
        (frame.objective_id, frame.document_id): frame
        for frame in objective_paper_frames
    }
    extractable_routes = order_routes_for_extraction(
        _dedupe_extraction_routes(
            tuple(
                route
                for route in objective_evidence_routes
                if route.extractable and route.role != "low_value_or_irrelevant"
            )
        ),
        document_trees_by_document_id=document_trees_by_document_id,
    )
    logger.info(
        "Research objective evidence extraction started collection_id=%s route_count=%s extractable_route_count=%s",
        collection_id,
        len(objective_evidence_routes),
        len(extractable_routes),
    )
    units: list[ExtractedEvidenceDraft] = []
    seen: set[str] = set()
    document_state_units: dict[tuple[str, str], list[ExtractedEvidenceDraft]] = {}
    for seed in _document_state_seed:
        document_state_units.setdefault(
            (seed.objective_id, seed.document_id),
            [],
        ).append(seed)
    llm_evidence_unavailable: dict[tuple[str, str], Exception] = {}
    llm_table_repair_unavailable: dict[tuple[str, str], Exception] = {}
    resolved_paper_facts_extractor = paper_facts_extractor
    document_metadata = _progress_document_metadata(
        document_trees_by_document_id=document_trees_by_document_id,
    )
    for route_position, route in enumerate(extractable_routes, start=1):
        document_key = (route.objective_id, route.document_id)
        route_document_metadata = document_metadata.get(route.document_id, {})
        _notify_progress(
            progress_callback,
            phase="objective_evidence_extraction_started",
            current=route_position,
            total=len(extractable_routes),
            unit="selections",
            message="Extracting objective evidence from selected sources.",
            active_document_id=route.document_id,
            active_document_title=route_document_metadata.get("title"),
            active_source_filename=route_document_metadata.get("source_filename"),
            active_objective_id=route.objective_id,
        )
        objective = objective_by_id.get(route.objective_id)
        if objective is None:
            logger.info(
                "Research objective evidence extraction route skipped collection_id=%s source_ref=%s reason=missing_objective route_position=%s route_count=%s",
                collection_id,
                route.source_ref,
                route_position,
                len(extractable_routes),
            )
            continue
        source = _build_objective_route_source_payload(
            route=route,
            blocks=blocks_by_document_id.get(route.document_id, []),
            tables=tables_by_document_id.get(route.document_id, []),
            document_tree=document_trees_by_document_id.get(route.document_id),
            table_cells=(
                table_cells_by_document_id.get(route.document_id, [])
                if table_cells_by_document_id is not None
                else []
            ),
        )
        if not source:
            raise RuntimeError(
                "selected Evidence Source is missing: "
                f"objective_id={route.objective_id} "
                f"document_id={route.document_id} "
                f"source_kind={route.source_kind} "
                f"source_ref={route.source_ref}"
            )
        objective_context = objective_by_id.get(route.objective_id)
        frame = frame_by_key.get((route.objective_id, route.document_id))
        tree_position = _route_tree_position(
            _source_candidate_from_route(
                route=route,
                source=source,
                document_tree=document_trees_by_document_id.get(route.document_id),
            )
        )
        prior_document_state = _objective_document_state_payload(
            document_state_units.get((route.objective_id, route.document_id), [])
        )
        payload = {
            "collection_id": collection_id,
            "objective": _route_prompt_objective_record(objective),
            "paper_frame": _route_prompt_paper_frame_record(
                frame_by_key[(route.objective_id, route.document_id)]
            )
            if (route.objective_id, route.document_id) in frame_by_key
            else {},
            "evidence_route": _objective_evidence_prompt_route_record(route),
            "tree_position": tree_position,
            "document_state": prior_document_state,
            "source": _objective_evidence_prompt_source(source),
        }
        if (
            resolved_paper_facts_extractor is None
            and _objective_table_source_needs_llm_structural_repair(
                route=route,
                source=source,
            )
        ):
            resolved_paper_facts_extractor = build_default_paper_facts_extractor()
        source, table_repair_error = _repair_objective_table_source_if_needed(
            collection_id=collection_id,
            route=route,
            source=source,
            paper_facts_extractor=resolved_paper_facts_extractor,
            unavailable_error=llm_table_repair_unavailable.get(document_key),
        )
        if table_repair_error is not None and _provider_is_temporarily_unavailable(
            table_repair_error
        ):
            llm_table_repair_unavailable.setdefault(
                document_key,
                table_repair_error,
            )
        payload["source"] = _objective_evidence_prompt_source(source)
        context_bundle = (
            _build_objective_same_paper_context_bundle(
                route=route,
                routes=tuple(
                    [
                        *extractable_routes,
                        *_objective_seed_context_routes(
                            units=document_state_units.get(document_key, []),
                            route=route,
                        ),
                    ]
                ),
                blocks=blocks_by_document_id.get(route.document_id, []),
                tables=tables_by_document_id.get(route.document_id, []),
                figures=(figures_by_document_id or {}).get(route.document_id, []),
                document_tree=document_trees_by_document_id.get(route.document_id),
                table_cells=(
                    table_cells_by_document_id.get(route.document_id, [])
                    if table_cells_by_document_id is not None
                    else []
                ),
            )
            if route.role in _DIRECT_RESULT_ROUTE_ROLES
            else ()
        )
        payload["same_paper_context_bundle"] = [
            dict(item) for item in context_bundle
        ]
        route_unit_start = len(units)
        if (
            table_repair_error is not None
            and _objective_table_source_needs_llm_structural_repair(
                route=route,
                source=source,
            )
        ):
            failed_unit = _failed_objective_evidence_draft(
                route=route,
                error=table_repair_error,
            )
            if failed_unit.evidence_id not in seen:
                seen.add(failed_unit.evidence_id)
                units.append(failed_unit)
            continue
        route_records = _objective_table_matrix_evidence_records(
            route=route,
            source=source,
            objective_context=objective_context,
        )
        needs_structural_repair = _objective_table_source_needs_llm_structural_repair(
            route=route,
            source=source,
        ) and not (
            source.get("table_matrix_structural_repair_applied") and route_records
        )
        needs_model_extraction = (
            not route_records or needs_structural_repair
        ) and not _objective_table_route_should_skip_llm_fallback(route)
        if needs_model_extraction:
            extraction_error = llm_evidence_unavailable.get(document_key)
            if extraction_error is None:
                try:
                    parsed = source_extractor.extract_source(payload)
                    grounding_source_pairs = _objective_document_grounding_sources(
                        document_state_units.get(document_key, []),
                        route=route,
                        blocks=blocks_by_document_id.get(route.document_id, []),
                        tables=tables_by_document_id.get(route.document_id, []),
                        figures=(figures_by_document_id or {}).get(
                            route.document_id, []
                        ),
                        document_tree=document_trees_by_document_id.get(
                            route.document_id
                        ),
                        table_cells=(
                            table_cells_by_document_id.get(route.document_id, [])
                            if table_cells_by_document_id is not None
                            else []
                        ),
                    )
                    bundle_grounding_pairs = _objective_bundle_grounding_sources(
                        context_bundle
                    )
                    llm_route_records_list: list[dict[str, Any]] = []
                    existing_grounding_keys = {
                        (
                            _text(ref.get("source_kind")),
                            _text(ref.get("source_ref")),
                        )
                        for _context_source, ref in grounding_source_pairs
                    }
                    for item in parsed.extractions:
                        item_bundle_pairs = (
                            bundle_grounding_pairs
                            if item.reported_result is not None
                            and route.role in _DIRECT_RESULT_ROUTE_ROLES
                            else ()
                        )
                        item_grounding_pairs = _merge_objective_grounding_source_pairs(
                            grounding_source_pairs,
                            item_bundle_pairs,
                        )
                        item_bundle_refs = _objective_bundle_source_refs_for_record(
                            item,
                            item_bundle_pairs,
                            existing_grounding_keys=existing_grounding_keys,
                        )
                        llm_route_records_list.extend(
                            validate_source_fact(
                                route=route,
                                source=source,
                                objective_context=objective_context,
                                # Do not materialize Pydantic defaults into the
                                # scientific record.  In particular, an omitted
                                # model confidence must remain distinguishable
                                # from an explicit zero so validation can use the
                                # route's conservative fallback.
                                extracted_record=item.model_dump(
                                    exclude_unset=True
                                ),
                                candidate_variables=(
                                    frame.changed_variables
                                    if frame is not None
                                    else ()
                                ),
                                grounding_sources=tuple(
                                    context_source
                                    for context_source, _context_ref in item_grounding_pairs
                                ),
                                grounding_source_refs=item_bundle_refs,
                            )
                        )
                    llm_route_records = tuple(llm_route_records_list)
                except Exception as exc:
                    extraction_error = exc
                    provider_unavailable = _provider_is_temporarily_unavailable(exc)
                    if provider_unavailable:
                        llm_evidence_unavailable[document_key] = exc
                    logger.exception(
                        "Research objective evidence extraction route failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s completed_routes=%s remaining_routes=%s provider_unavailable=%s",
                        collection_id,
                        route.source_ref,
                        route.objective_id,
                        route.document_id,
                        route.source_kind,
                        route.source_ref,
                        route_position,
                        len(extractable_routes),
                        route_position - 1,
                        max(len(extractable_routes) - route_position, 0),
                        provider_unavailable,
                    )
                else:
                    route_records = _objective_merge_table_repair_records(
                        deterministic_records=route_records,
                        llm_records=llm_route_records,
                    )
            if extraction_error is not None:
                failed_unit = _failed_objective_evidence_draft(
                    route=route,
                    error=extraction_error,
                )
                if failed_unit.evidence_id not in seen:
                    seen.add(failed_unit.evidence_id)
                    units.append(failed_unit)
                if not route_records:
                    continue
            if (
                not route_records
                and extraction_error is None
                and not _objective_route_is_context_inspection(route)
                and route.role == "current_experimental_evidence"
                and objective_context is not None
                and bool(objective_context.outcomes)
                and bool(route.reason)
            ):
                # A direct result route is already a researcher-facing recall
                # decision. Do not run a second lexical outcome detector here:
                # synonyms, OCR, abbreviations, and figure/table wording can
                # make that detector miss a valid result Source. Preserve the
                # Source as an unresolved result candidate so same-paper
                # context expansion can inspect it and the Evidence Map can
                # show the unresolved read.
                route_records = (
                    _needs_context_objective_evidence_draft(
                        route=route,
                        selection_reason=(
                            _SELECTED_RESULT_NEEDS_CONTEXT_SELECTION_REASON
                        ),
                        ).to_record(),
                )
            elif (
                not route_records
                and extraction_error is None
                and not _objective_route_is_context_inspection(route)
                and objective_context is not None
                and _objective_source_mentions_target_outcome(
                    source,
                    objective=objective_context,
                )
            ):
                # Keep the legacy target-mentioned route for callers that do
                # not carry an explicit direct-result role. Explicit result
                # routes are handled above so their selection reason remains
                # distinct from this lexical fallback.
                route_records = (
                    _needs_context_objective_evidence_draft(
                        route=route,
                    ).to_record(),
                )
        for record in route_records:
            unit = ExtractedEvidenceDraft.from_mapping(record)
            if not _objective_evidence_has_payload(unit):
                continue
            if unit.evidence_id in seen:
                continue
            seen.add(unit.evidence_id)
            units.append(unit)
            document_state_units.setdefault(
                (unit.objective_id, unit.document_id),
                [],
            ).append(unit)
        if len(units) == route_unit_start:
            # A selected result Source remains a visible unresolved anchor so
            # same-paper context can trigger one bounded reread.  A context or
            # background Source with no extracted fact is inspection metadata,
            # not scientific Evidence; retain it only in the internal ledger.
            inspection_unit = (
                _needs_context_objective_evidence_draft(
                    route=route,
                    selection_reason=(
                        _SELECTED_RESULT_NEEDS_CONTEXT_SELECTION_REASON
                    ),
                )
                if (
                    route.role in _DIRECT_RESULT_ROUTE_ROLES
                    and not _objective_route_is_context_inspection(route)
                )
                else _inspected_objective_source_draft(route=route)
            )
            if (
                route.role not in _DIRECT_RESULT_ROUTE_ROLES
                or _objective_route_is_context_inspection(route)
            ):
                record_analysis_diagnostic(
                    {
                        "trace_type": "objective_source_inspection",
                        "collection_id": collection_id,
                        "objective_id": route.objective_id,
                        "document_id": route.document_id,
                        "source_kind": route.source_kind,
                        "source_ref": route.source_ref,
                        "route_role": route.role,
                        "disposition": "no_source_grounded_fact",
                    }
                )
            if inspection_unit.evidence_id not in seen:
                seen.add(inspection_unit.evidence_id)
                units.append(inspection_unit)
                if route.role in _DIRECT_RESULT_ROUTE_ROLES:
                    document_state_units.setdefault(document_key, []).append(
                        inspection_unit
                    )
        logger.info(
            "Research objective evidence extraction route finished collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s extractions=%s completed_routes=%s remaining_routes=%s",
            collection_id,
            route.source_ref,
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            route_position,
            len(extractable_routes),
            len(units) - route_unit_start,
            route_position,
            max(len(extractable_routes) - route_position, 0),
        )
    if _allow_adaptive_context_expansion:
        # Context discovery is a stateful closure loop. Each round can expose
        # new sample or condition labels that make another same-paper Source
        # discoverable. Only previously unread context Sources are added to the
        # bundle. A selected result Source may receive one bounded re-read after
        # those context facts are grounded, mirroring how a researcher revisits
        # the result after locating its Methods conditions.
        known_routes = list(objective_evidence_routes)
        rechecked_result_keys: set[tuple[str, str, str, str]] = set()
        context_round = 0
        while True:
            context_round += 1
            context_state_before = _objective_context_progress_state(
                units,
                objectives,
            )
            adaptive_context_routes = _build_adaptive_context_routes(
                objectives=objectives,
                source_facts=tuple(units),
                objective_evidence_routes=tuple(known_routes),
                objective_paper_frames=objective_paper_frames,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
                document_trees_by_document_id=document_trees_by_document_id,
            )
            if adaptive_context_routes:
                known_routes.extend(adaptive_context_routes)
                record_analysis_diagnostic(
                    {
                        "trace_type": "objective_context_expansion",
                        "collection_id": collection_id,
                        "route_count": len(adaptive_context_routes),
                        "context_round": context_round,
                        "document_keys": sorted(
                            {
                                f"{route.objective_id}:{route.document_id}"
                                for route in adaptive_context_routes
                            }
                        ),
                        "reason": "partial_result_requires_same_paper_context",
                    }
                )
                expanded_context_units = extract_and_validate_source_facts(
                    collection_id=collection_id,
                    source_extractor=source_extractor,
                    paper_facts_extractor=paper_facts_extractor,
                    objectives=objectives,
                    objective_paper_frames=objective_paper_frames,
                    objective_evidence_routes=adaptive_context_routes,
                    blocks_by_document_id=blocks_by_document_id,
                    tables_by_document_id=tables_by_document_id,
                    figures_by_document_id=figures_by_document_id,
                    document_trees_by_document_id=document_trees_by_document_id,
                    table_cells_by_document_id=table_cells_by_document_id,
                    progress_callback=progress_callback,
                    _document_state_seed=tuple(units),
                    _allow_adaptive_context_expansion=False,
                )
                for unit in expanded_context_units:
                    if unit.evidence_id in seen:
                        continue
                    seen.add(unit.evidence_id)
                    units.append(unit)

                # If a selected result Source returned no result before its
                # same-paper context was available, give that exact Source one
                # bounded re-read with the newly grounded context. Keeping only
                # the unresolved candidate would make the system permanently
                # blind to a recoverable result. Technical failures remain
                # failed drafts and do not upgrade the scientific status.
                result_recovery_routes = _objective_result_recovery_routes(
                    source_facts=tuple(units),
                    routes=tuple(known_routes),
                    attempted_keys=rechecked_result_keys,
                    objectives=objectives,
                )
                if result_recovery_routes:
                    record_analysis_diagnostic(
                        {
                            "trace_type": "objective_result_context_recheck",
                            "collection_id": collection_id,
                            "context_round": context_round,
                            "route_count": len(result_recovery_routes),
                            "source_refs": [
                                {
                                    "document_id": route.document_id,
                                    "source_kind": route.source_kind,
                                    "source_ref": route.source_ref,
                                }
                                for route in result_recovery_routes
                            ],
                            "reason": "same_paper_context_was_grounded",
                        }
                    )
                    rechecked_result_keys.update(
                        _objective_route_identity(route)
                        for route in result_recovery_routes
                    )
                    recovered_result_units = extract_and_validate_source_facts(
                        collection_id=collection_id,
                        source_extractor=source_extractor,
                        paper_facts_extractor=paper_facts_extractor,
                        objectives=objectives,
                        objective_paper_frames=objective_paper_frames,
                        objective_evidence_routes=result_recovery_routes,
                        blocks_by_document_id=blocks_by_document_id,
                        tables_by_document_id=tables_by_document_id,
                        figures_by_document_id=figures_by_document_id,
                        document_trees_by_document_id=document_trees_by_document_id,
                        table_cells_by_document_id=table_cells_by_document_id,
                        progress_callback=progress_callback,
                        _document_state_seed=tuple(units),
                        _allow_adaptive_context_expansion=False,
                    )
                    _merge_recovered_result_units(
                        units=units,
                        document_state_units=document_state_units,
                        recovered_units=recovered_result_units,
                        seen=seen,
                    )

            context_state_after = _objective_context_progress_state(
                units,
                objectives,
            )
            if context_state_after == context_state_before:
                _record_objective_context_scope_gap(
                    collection_id=collection_id,
                    context_round=context_round,
                    units=units,
                    objectives=objectives,
                    reason=(
                        "Same-paper Sources were inspected but did not reduce "
                        "the remaining context gap."
                    ),
                )
                break
            if not adaptive_context_routes:
                break
            if context_round >= _OBJECTIVE_ADAPTIVE_CONTEXT_MAX_ROUNDS:
                _record_objective_context_scope_gap(
                    collection_id=collection_id,
                    context_round=context_round,
                    units=units,
                    objectives=objectives,
                    reason=(
                        "The bounded same-paper review scope was reached "
                        "before all comparison context was source-grounded."
                    ),
                )
                break

    for unit in _build_objective_method_family_test_condition_units(
        objectives=objectives,
        objective_paper_frames=objective_paper_frames,
        objective_evidence_routes=objective_evidence_routes,
        blocks_by_document_id=blocks_by_document_id,
    ):
        if not _objective_evidence_has_payload(unit):
            continue
        if unit.evidence_id in seen:
            continue
        seen.add(unit.evidence_id)
        units.append(unit)
    logger.info(
        "Research objective evidence extraction finished collection_id=%s objective_extractions=%s",
        collection_id,
        len(units),
    )
    return tuple(units)


def _notify_progress(
    progress_callback: ProgressCallback | None,
    **progress_detail: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(progress_detail)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Research objective progress callback failed phase=%s",
            progress_detail.get("phase"),
        )


def _progress_document_metadata(
    *,
    document_trees_by_document_id: dict[str, SourceDocumentTree],
) -> dict[str, dict[str, str | None]]:
    return {
        document_id: {
            "title": str(tree.root.title or "").strip() or None,
            "source_filename": None,
        }
        for document_id, tree in document_trees_by_document_id.items()
    }


def _route_prompt_objective_record(
    objective: ResearchObjective,
) -> dict[str, Any]:
    return {
        "objective_id": objective.objective_id,
        "question": objective.question,
        "material_scope": list(objective.material_scope),
        "variables": list(objective.variables),
        "outcomes": list(objective.outcomes),
        "mechanisms": list(objective.mechanisms),
        "constraints": list(objective.constraints),
        "requested_comparator": objective.requested_comparator,
    }


def _route_prompt_paper_frame_record(
    frame: PaperAnalysisFrame,
) -> dict[str, Any]:
    return {
        "document_id": frame.document_id,
        "objective_id": frame.objective_id,
        "relevance": frame.relevance,
        "paper_role": frame.paper_role,
        "material_match": list(frame.material_match),
        "changed_variables": list(frame.changed_variables),
        "measured_property_scope": list(frame.measured_property_scope),
        "test_environment_scope": list(frame.test_environment_scope),
    }


def _objective_header_matches_any_axis(
    header: str,
    axes: tuple[str, ...],
) -> bool:
    property_name, _unit = _split_property_unit(header)
    normalized_property = property_matching.normalize_property_label(property_name)
    if normalized_property and any(
        property_matching.axis_values_match(normalized_property, axis) for axis in axes
    ):
        return True
    if normalized_property and property_matching.outcome_matches_objective_scope(
        normalized_property,
        axes,
    ):
        return True
    if any(property_matching.axis_values_match(header, axis) for axis in axes):
        return True
    header_key = _objective_column_key(header)
    if not header_key:
        return False
    for axis in axes:
        axis_key = _objective_column_key(axis)
        if not axis_key:
            continue
        if axis_key in header_key or header_key in axis_key:
            return True
    return False


def _failed_objective_evidence_draft(
    *,
    route: EvidenceCandidate,
    error: Exception,
) -> ExtractedEvidenceDraft:
    identity = "|".join(
        (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            "failed",
        )
    )
    reason = f"{error.__class__.__name__}: {str(error) or 'extraction failed'}"
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": (
                f"oev_failed_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
            ),
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "evidence_role": "irrelevant",
            "selection_status": "failed",
            "selection_reason": route.reason,
            "attribution_scope": "not_attributable",
            "source_refs": [
                {
                    "source_kind": route.source_kind,
                    "source_ref": route.source_ref,
                }
            ],
            "resolution_status": "unknown",
            "failure_reason": reason[:1000],
            "confidence": 0.0,
        }
    )


_NEEDS_CONTEXT_SELECTION_REASON = (
    "Target outcome mentioned but needs same-paper context."
)
_SELECTED_RESULT_NEEDS_CONTEXT_SELECTION_REASON = (
    "Selected result Source needs same-paper context."
)
_NEEDS_CONTEXT_SELECTION_REASONS = frozenset(
    {
        _NEEDS_CONTEXT_SELECTION_REASON,
        _SELECTED_RESULT_NEEDS_CONTEXT_SELECTION_REASON,
    }
)
def _needs_context_objective_evidence_draft(
    *,
    route: EvidenceCandidate,
    selection_reason: str = _NEEDS_CONTEXT_SELECTION_REASON,
) -> ExtractedEvidenceDraft:
    identity = "|".join(
        (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            "needs_context",
        )
    )
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": (
                f"oev_context_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
            ),
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "evidence_role": "direct_result",
            "selection_status": "candidate",
            "selection_reason": selection_reason,
            "attribution_scope": "not_attributable",
            "source_refs": [
                {
                    "source_kind": route.source_kind,
                    "source_ref": route.source_ref,
                }
            ],
            "resolution_status": "unresolved",
            "confidence": 0.0,
        }
    )


_INSPECTION_ONLY_SELECTION_REASON = (
    "Source was inspected but no source-grounded scientific fact was extracted."
)


def _inspected_objective_source_draft(
    *,
    route: EvidenceCandidate,
) -> ExtractedEvidenceDraft:
    """Keep an attempted read in the audit ledger without creating Evidence."""

    identity = "|".join(
        (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
            "inspection_only",
        )
    )
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": (
                "oev_inspected_"
                f"{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
            ),
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "evidence_role": "irrelevant",
            # ``rejected`` is a valid transient disposition for a selected
            # Source that yielded no scientific fact. Materialization filters
            # this marker while using it to count the Source as inspected.
            "selection_status": "rejected",
            "selection_reason": (
                f"{_INSPECTION_ONLY_SELECTION_REASON} {route.reason}".strip()
            ),
            "attribution_scope": "not_attributable",
            "source_refs": [
                {
                    "source_kind": route.source_kind,
                    "source_ref": route.source_ref,
                    "role": route.role,
                    "context_fields": list(route.context_fields),
                }
            ],
            "resolution_status": "skipped",
            "confidence": 0.0,
        }
    )


def _objective_route_is_context_inspection(route: EvidenceCandidate) -> bool:
    """Identify routes selected to fill context rather than report a result."""

    if route.role in {
        "process_or_treatment",
        "test_condition",
        "characterization",
    }:
        return True
    reason = " ".join(str(route.reason or "").casefold().split())
    if route.role in _DIRECT_RESULT_ROUTE_ROLES:
        return not any(
            marker in reason
            for marker in (
                _SELECTED_RESULT_NEEDS_CONTEXT_SELECTION_REASON.casefold(),
                "selected direct objective result source",
                "routing model selected this result source",
            )
        ) and ("context" in reason or "inspected" in reason)
    return "context" in reason or "inspected" in reason


def _objective_source_mentions_target_outcome(
    source: Mapping[str, Any],
    *,
    objective: ResearchObjective,
) -> bool:
    """Detect a target outcome in the inspected Source without extracting facts."""
    source_parts: list[str] = []
    for key in (
        "text",
        "caption_text",
        "heading_path",
        "table_markdown",
        "table_visual_text",
        "column_headers",
        "table_matrix",
        "table_cells",
    ):
        value = source.get(key)
        if isinstance(value, (list, tuple)):
            source_parts.extend(str(item) for item in value)
        elif isinstance(value, Mapping):
            source_parts.extend(str(item) for item in value.values())
        elif value not in (None, ""):
            source_parts.append(str(value))
    source_text = " ".join(source_parts)
    if not source_text.strip():
        return False
    target_axes = property_matching.objective_outcomes(objective)
    return any(
        property_matching.axis_label_is_mentioned(source_text, axis)
        for axis in target_axes
    )


def _build_adaptive_context_routes(
    *,
    objectives: tuple[ResearchObjective, ...],
    source_facts: tuple[ExtractedEvidenceDraft, ...],
    objective_evidence_routes: tuple[EvidenceCandidate, ...],
    objective_paper_frames: tuple[PaperAnalysisFrame, ...] = (),
    blocks_by_document_id: dict[str, list[Any]],
    tables_by_document_id: dict[str, list[Any]],
    figures_by_document_id: dict[str, list[Any]] | None = None,
    document_trees_by_document_id: Mapping[str, SourceDocumentTree] | None = None,
) -> tuple[EvidenceCandidate, ...]:
    """Select same-paper Sources needed to complete partial results.

    The first routing pass is intentionally recall-oriented for direct results.
    If extraction shows that a result still lacks material, condition, or
    comparison context, this second pass reads the paper's own Methods,
    specimen, result, figure, and test Sources. Selection is driven by the
    missing field families and source-local terms. A bounded per-paper
    expansion keeps technical recovery from turning into full-document
    extraction; omitted candidates remain an explicit uninspected scope gap
    rather than a scientific absence.
    """

    objective_by_id = {objective.objective_id: objective for objective in objectives}
    anchors_by_key: dict[
        tuple[str, str],
        list[ExtractedEvidenceDraft],
    ] = {}
    context_seed = tuple(
        unit
        for unit in source_facts
        if unit.reported_result is None
        and unit.evidence_role in _OBJECTIVE_CONTEXT_ROLES
    )
    for unit in source_facts:
        objective = objective_by_id.get(unit.objective_id)
        if objective is None or not _objective_fact_needs_context(unit, objective):
            continue
        if _objective_context_bundle_can_bind_result(
            unit,
            context_seed=context_seed,
            objective=objective,
        ):
            continue
        fields = _objective_missing_context_fields(unit, objective)
        if fields:
            anchors_by_key.setdefault(
                (unit.objective_id, unit.document_id),
                [],
            ).append(unit)
    if not anchors_by_key:
        return ()

    existing_source_keys = {
        (
            route.objective_id,
            route.document_id,
            route.source_kind,
            route.source_ref,
        )
        for route in objective_evidence_routes
    }
    adaptive_routes: list[EvidenceCandidate] = []
    figures_by_document_id = figures_by_document_id or {}
    document_trees_by_document_id = document_trees_by_document_id or {}
    for objective_id, document_id in sorted(anchors_by_key):
        objective = objective_by_id[objective_id]
        anchors = tuple(anchors_by_key[(objective_id, document_id)])
        missing_fields = {
            field
            for anchor in anchors
            for field in _objective_missing_context_fields(anchor, objective)
        }
        document_tree = document_trees_by_document_id.get(document_id)
        specific_terms = _objective_context_search_terms(
            objective=objective,
            source_facts=source_facts,
            document_id=document_id,
            objective_id=objective_id,
        )
        specific_term_fields = _objective_context_search_term_fields(
            objective=objective,
            source_facts=source_facts,
            document_id=document_id,
            objective_id=objective_id,
        )
        candidates: list[
            tuple[int, int, str, str, str, tuple[str, ...], int, int]
        ] = []
        candidate_search_text: dict[tuple[str, str], tuple[str, str]] = {}
        frame_candidate_keys: set[tuple[str, str]] = set()

        # Framing is a paper-level reading decision.  When it marked a Source
        # relevant, that decision must survive an over-selective first router;
        # otherwise a researcher would continue reading the Source while the
        # analysis silently stops.  These routes are still ordinary transient
        # routes and must pass the same extraction and grounding path below.
        frame = next(
            (
                paper_frame
                for paper_frame in objective_paper_frames
                if paper_frame.objective_id == objective_id
                and paper_frame.document_id == document_id
            ),
            None,
        )
        if frame is not None:
            frame_sources: list[tuple[str, str]] = []
            for disposition in frame.source_dispositions:
                if not disposition.is_relevant:
                    continue
                source_kind = disposition.source_kind.casefold()
                route_source_kind = (
                    "table"
                    if source_kind == "table"
                    else "figure"
                    if source_kind == "figure"
                    else "text_window"
                    if source_kind in {"section", "block", "text", "text_window"}
                    else ""
                )
                source_ref = disposition.source_ref.strip()
                if not route_source_kind or not source_ref:
                    continue
                if source_kind == "section" and document_tree is not None:
                    section_node = _tree_node_for_route_source(
                        document_tree=document_tree,
                        source_ref_kind="section",
                        source_ref_id=source_ref,
                    )
                    child_refs = (
                        tuple(
                            str(
                                getattr(
                                    document_tree.nodes.get(child_id),
                                    "source_ref_id",
                                    "",
                                )
                                or ""
                            ).strip()
                            for child_id in getattr(
                                section_node,
                                "child_ids",
                                (),
                            )
                            if document_tree.nodes.get(child_id) is not None
                            and document_tree.nodes[child_id].node_type
                            in {"paragraph", "list_item", "caption"}
                        )
                        if section_node is not None
                        else ()
                    )
                    frame_sources.extend(
                        ("text_window", child_ref)
                        for child_ref in child_refs
                        if child_ref
                    )
                    if child_refs:
                        continue
                frame_sources.append((route_source_kind, source_ref))

            record_analysis_diagnostic(
                {
                    "trace_type": "objective_frame_context_candidates",
                    "objective_id": objective_id,
                    "document_id": document_id,
                    "frame_source_disposition_count": len(frame.source_dispositions),
                    "frame_relevant_source_count": sum(
                        1 for item in frame.source_dispositions if item.is_relevant
                    ),
                    "frame_route_candidate_count": len(frame_sources),
                    "frame_route_candidate_refs": [
                        {"source_kind": kind, "source_ref": source_ref}
                        for kind, source_ref in frame_sources[:20]
                    ],
                }
            )
            for route_source_kind, source_ref in frame_sources:
                if document_tree is not None:
                    source_node = document_tree.nodes.get(source_ref)
                    resolved_source_ref = str(
                        getattr(source_node, "source_ref_id", "") or ""
                    ).strip()
                    if resolved_source_ref:
                        source_ref = resolved_source_ref
                source_key = (route_source_kind, source_ref)
                if (
                    (objective_id, document_id, *source_key)
                    in existing_source_keys
                    or source_key in frame_candidate_keys
                ):
                    continue
                frame_route = EvidenceCandidate.from_mapping(
                    {
                        "objective_id": objective_id,
                        "document_id": document_id,
                        "source_kind": route_source_kind,
                        "source_ref": source_ref,
                        "role": "process_or_treatment",
                        "extractable": True,
                        "confidence": 0.8,
                    }
                )
                frame_source = _build_objective_route_source_payload(
                    route=frame_route,
                    blocks=blocks_by_document_id.get(document_id, []),
                    tables=tables_by_document_id.get(document_id, []),
                    figures=figures_by_document_id.get(document_id, []),
                    document_tree=document_tree,
                    table_cells=[],
                )
                if not frame_source:
                    continue
                heading = _adaptive_context_source_heading(
                    heading_path=frame_source.get("heading_path"),
                    document_tree=document_tree,
                    source_ref_kind=(
                        "block" if route_source_kind == "text_window" else route_source_kind
                    ),
                    source_ref=source_ref,
                )
                source_text = " ".join(
                    str(frame_source.get(key) or "")
                    for key in (
                        "text",
                        "caption_text",
                        "heading_path",
                        "table_markdown",
                        "table_visual_text",
                        "column_headers",
                        "table_matrix",
                    )
                )
                matched_fields = _adaptive_context_matched_fields(
                    heading=heading,
                    text=source_text,
                    missing_fields=missing_fields,
                    specific_terms=specific_terms,
                    specific_term_fields=specific_term_fields,
                )
                candidates.append(
                    (
                        -1,
                        -1,
                        route_source_kind,
                        source_ref,
                        _adaptive_context_route_role(heading),
                        matched_fields,
                        _adaptive_context_term_hits(source_text, specific_terms),
                        _adaptive_context_specificity_score(source_text),
                    )
                )
                candidate_search_text[source_key] = (heading, source_text)
                frame_candidate_keys.add(source_key)
                existing_source_keys.add(
                    (objective_id, document_id, *source_key)
                )
        for position, block in enumerate(blocks_by_document_id.get(document_id, ())):
            source_ref = _text(getattr(block, "block_id", ""))
            text = _text(getattr(block, "text", ""))
            heading = _adaptive_context_heading(
                block,
                document_tree=document_tree,
                source_ref_kind="block",
                source_ref=source_ref,
            )
            if not source_ref or not text:
                continue
            source_key = (objective_id, document_id, "text_window", source_ref)
            if source_key in existing_source_keys:
                continue
            role = _adaptive_context_route_role(heading)
            matched_fields = _adaptive_context_matched_fields(
                heading=heading,
                text=text,
                missing_fields=missing_fields,
                specific_terms=specific_terms,
                specific_term_fields=specific_term_fields,
            )
            if not matched_fields:
                continue
            priority = 0 if specific_terms and _contains_any_term(text, specific_terms) else 1
            candidates.append(
                (
                    priority,
                    position,
                    "text_window",
                    source_ref,
                    role,
                    matched_fields,
                    _adaptive_context_term_hits(text, specific_terms),
                    _adaptive_context_specificity_score(text),
                )
            )
            candidate_search_text[("text_window", source_ref)] = (heading, text)

        for position, table in enumerate(tables_by_document_id.get(document_id, ())):
            source_ref = _text(getattr(table, "table_id", ""))
            if not source_ref:
                continue
            heading = " ".join(
                part
                for part in (
                    _adaptive_context_source_heading(
                        heading_path=getattr(table, "heading_path", ""),
                        document_tree=document_tree,
                        source_ref_kind="table",
                        source_ref=source_ref,
                    ),
                    _text(getattr(table, "caption_text", "")),
                    " ".join(
                        _text(value)
                        for value in (getattr(table, "column_headers", ()) or ())
                    ),
                )
                if part
            ).casefold()
            source_key = (objective_id, document_id, "table", source_ref)
            if source_key in existing_source_keys:
                continue
            role = _adaptive_context_route_role(heading)
            table_text = " ".join(
                part
                for part in (
                    heading,
                    " ".join(
                        _text(row)
                        for row in (getattr(table, "table_matrix", ()) or ())
                    ),
                )
                if part
            )
            matched_fields = _adaptive_context_matched_fields(
                heading=heading,
                text=table_text,
                missing_fields=missing_fields,
                specific_terms=specific_terms,
                specific_term_fields=specific_term_fields,
            )
            if not matched_fields:
                continue
            priority = 0 if specific_terms and _contains_any_term(table_text, specific_terms) else 1
            candidates.append(
                (
                    priority,
                    position,
                    "table",
                    source_ref,
                    role,
                    matched_fields,
                    _adaptive_context_term_hits(table_text, specific_terms),
                    _adaptive_context_specificity_score(table_text),
                )
            )
            candidate_search_text[("table", source_ref)] = (heading, table_text)

        for position, figure in enumerate(figures_by_document_id.get(document_id, ())):
            source_ref = _text(getattr(figure, "figure_id", ""))
            caption = _text(getattr(figure, "caption_text", ""))
            if not source_ref or not caption:
                continue
            heading = " ".join(
                part
                for part in (
                    _adaptive_context_source_heading(
                        heading_path=getattr(figure, "heading_path", ""),
                        document_tree=document_tree,
                        source_ref_kind="figure",
                        source_ref=source_ref,
                    ),
                    caption,
                )
                if part
            ).casefold()
            source_key = (objective_id, document_id, "figure", source_ref)
            if source_key in existing_source_keys:
                continue
            matched_fields = _adaptive_context_matched_fields(
                heading=heading,
                text=caption,
                missing_fields=missing_fields,
                specific_terms=specific_terms,
                specific_term_fields=specific_term_fields,
            )
            if not matched_fields:
                continue
            priority = 0 if specific_terms and _contains_any_term(caption, specific_terms) else 1
            candidates.append(
                (
                    priority,
                    position,
                    "figure",
                    source_ref,
                    "characterization",
                    matched_fields,
                    _adaptive_context_term_hits(caption, specific_terms),
                    _adaptive_context_specificity_score(caption),
                )
            )
            candidate_search_text[("figure", source_ref)] = (heading, caption)

        selected_by_key: dict[
            tuple[str, str],
            tuple[
                tuple[int, int, str, str, str, tuple[str, ...], int, int],
                set[str],
                set[str],
            ],
        ] = {}
        anchor_audits: list[dict[str, Any]] = []
        uncovered_fields: set[str] = set()
        anchor_groups_by_key: dict[
            tuple[str, str, str],
            list[ExtractedEvidenceDraft],
        ] = {}
        for anchor in anchors:
            result = anchor.reported_result
            anchor_groups_by_key.setdefault(
                (
                    anchor.source_kind,
                    anchor.source_ref or anchor.evidence_id,
                    property_matching.axis_key(result.outcome) if result else "",
                ),
                [],
            ).append(anchor)
        anchor_groups = tuple(
            tuple(anchor_groups_by_key[key]) for key in sorted(anchor_groups_by_key)
        )
        for anchor_group in anchor_groups:
            anchor = anchor_group[0]
            anchor_missing_fields = {
                field
                for grouped_anchor in anchor_group
                for field in _objective_missing_context_fields(
                    grouped_anchor,
                    objective,
                )
            }
            context_facts = tuple(
                unit
                for unit in source_facts
                if unit.objective_id == objective_id
                and unit.document_id == document_id
                and unit.reported_result is None
                and unit.evidence_role in _OBJECTIVE_CONTEXT_ROLES
            )
            anchor_facts = (*anchor_group, *context_facts)
            anchor_terms = _objective_context_search_terms(
                objective=objective,
                source_facts=anchor_facts,
                document_id=document_id,
                objective_id=objective_id,
            )
            anchor_term_fields = _objective_context_search_term_fields(
                objective=objective,
                source_facts=anchor_facts,
                document_id=document_id,
                objective_id=objective_id,
            )
            anchor_candidates: list[
                tuple[int, int, str, str, str, tuple[str, ...], int, int]
            ] = []
            structural_candidate_count = 0
            for candidate in candidates:
                source_key = (candidate[2], candidate[3])
                heading, source_text = candidate_search_text.get(source_key, ("", ""))
                matched_fields = _adaptive_context_matched_fields(
                    heading=heading,
                    text=source_text,
                    missing_fields=anchor_missing_fields,
                    specific_terms=anchor_terms,
                    specific_term_fields=anchor_term_fields,
                )
                if not matched_fields and source_key not in frame_candidate_keys:
                    continue
                anchor_candidates.append(
                    (
                        candidate[0],
                        candidate[1],
                        candidate[2],
                        candidate[3],
                        candidate[4],
                        matched_fields,
                        _adaptive_context_term_hits(
                            source_text,
                            anchor_terms,
                            term_fields=anchor_term_fields,
                            wanted_fields=anchor_missing_fields,
                        ),
                        _adaptive_context_specificity_score(source_text),
                    )
                )

            # Researchers follow local document structure when a result refers
            # to a terse group label or an abbreviated condition.  Such a
            # neighbouring Source may not contain any objective keyword, so
            # lexical matching alone would silently omit it. Add a small,
            # bounded structural window around text result anchors. These
            # candidates carry no matched field families and therefore cannot
            # claim scientific closure before extraction and validation.
            anchor_block_position = next(
                (
                    position
                    for position, block in enumerate(
                        blocks_by_document_id.get(document_id, ())
                    )
                    if _text(getattr(block, "block_id", ""))
                    == _text(anchor.source_ref)
                ),
                None,
            )
            if anchor_block_position is not None:
                for position, block in enumerate(
                    blocks_by_document_id.get(document_id, ())
                ):
                    source_ref = _text(getattr(block, "block_id", ""))
                    text = _text(getattr(block, "text", ""))
                    if (
                        not source_ref
                        or not text
                        or source_ref == _text(anchor.source_ref)
                        or abs(position - anchor_block_position)
                        > _ADAPTIVE_CONTEXT_NEIGHBOR_RADIUS
                    ):
                        continue
                    source_key = ("text_window", source_ref)
                    if (
                        (objective_id, document_id, *source_key)
                        in existing_source_keys
                        or source_key in candidate_search_text
                    ):
                        continue
                    heading = _adaptive_context_heading(
                        block,
                        document_tree=document_tree,
                        source_ref_kind="block",
                        source_ref=source_ref,
                    )
                    candidate_search_text[source_key] = (heading, text)
                    anchor_candidates.append(
                        (
                            2,
                            abs(position - anchor_block_position),
                            "text_window",
                            source_ref,
                            _adaptive_context_route_role(heading),
                            (),
                            0,
                            _adaptive_context_specificity_score(text),
                        )
                    )
                    structural_candidate_count += 1

            remaining_candidates = list(anchor_candidates)
            anchor_selected: list[
                tuple[int, int, str, str, str, tuple[str, ...], int, int]
            ] = []
            anchor_uncovered = set(anchor_missing_fields)
            while remaining_candidates and anchor_uncovered:
                covering_candidates = [
                    item
                    for item in remaining_candidates
                    if set(item[5]) & anchor_uncovered
                ]
                if not covering_candidates:
                    break
                chosen = max(
                    covering_candidates,
                    key=lambda item: (
                        # When process/test closure is still open, a Methods
                        # or procedure Source is the researcher's next read;
                        # a high-volume Results paragraph cannot substitute for
                        # fixed controls merely because it contains more
                        # objective words or numeric tokens.
                        (
                            2
                            if "process" in anchor_uncovered
                            and item[4] == "process_or_treatment"
                            else 2
                            if "test" in anchor_uncovered
                            and item[4] == "test_condition"
                            else 1
                            if item[4]
                            in {"process_or_treatment", "test_condition"}
                            else 0
                        ),
                        item[6],
                        item[7],
                        len(set(item[5]) & anchor_uncovered),
                        len(item[5]),
                        2 if item[2] == "table" else 1 if item[2] == "figure" else 0,
                        -item[0],
                        -item[1],
                        item[3],
                    ),
                )
                anchor_selected.append(chosen)
                anchor_uncovered.difference_update(chosen[5])
                remaining_candidates.remove(chosen)

            if anchor_uncovered:
                frame_fallbacks = [
                    item
                    for item in remaining_candidates
                    if (item[2], item[3]) in frame_candidate_keys
                ]
                if frame_fallbacks:
                    anchor_selected.append(
                        max(
                            frame_fallbacks,
                            key=lambda item: (
                                item[6],
                                item[7],
                                2 if item[2] == "table" else 1 if item[2] == "figure" else 0,
                                -item[1],
                                item[3],
                            ),
                        )
                    )

            if anchor_uncovered:
                structural_fallbacks = [
                    item
                    for item in remaining_candidates
                    if item[0] == 2 and not item[5]
                ]
                if structural_fallbacks:
                    # Read the nearest structural neighbour even when it does
                    # not advertise a field family. The next extraction pass
                    # decides whether it contains usable context.
                    anchor_selected.append(
                        min(
                            structural_fallbacks,
                            key=lambda item: (
                                item[1],
                                -item[7],
                                item[3],
                            ),
                        )
                    )

            anchor_refs = {
                grouped_anchor.source_ref or grouped_anchor.evidence_id
                for grouped_anchor in anchor_group
            }
            for selected in anchor_selected:
                source_key = (selected[2], selected[3])
                existing = selected_by_key.get(source_key)
                if existing is None:
                    selected_by_key[source_key] = (
                        selected,
                        set(selected[5]),
                        set(anchor_refs),
                    )
                    continue
                existing[1].update(selected[5])
                existing[2].update(anchor_refs)
            uncovered_fields.update(anchor_uncovered)
            anchor_audits.append(
                {
                    "source_kind": anchor.source_kind,
                    "source_ref": anchor.source_ref,
                    "result_count": len(anchor_group),
                    "outcome": (
                        anchor.reported_result.outcome
                        if anchor.reported_result is not None
                        else None
                    ),
                    "missing_fields": sorted(anchor_missing_fields),
                    "candidate_count": len(anchor_candidates),
                    "structural_candidate_count": structural_candidate_count,
                    "selected_count": len(anchor_selected),
                    "uncovered_fields": sorted(anchor_uncovered),
                }
            )

        selected_candidates = tuple(selected_by_key.values())
        record_analysis_diagnostic(
            {
                "trace_type": "objective_context_scope_audit",
                "objective_id": objective_id,
                "document_id": document_id,
                "missing_fields": sorted(missing_fields),
                "result_anchor_count": len(anchors),
                "result_group_count": len(anchor_groups),
                "candidate_count": len(candidates),
                "structural_candidate_count": sum(
                    int(audit.get("structural_candidate_count") or 0)
                    for audit in anchor_audits
                ),
                "selected_count": len(selected_candidates),
                "uncovered_fields": sorted(uncovered_fields),
                "omitted_count": max(len(candidates) - len(selected_candidates), 0),
                "anchor_decisions": anchor_audits[:20],
                # These are lexical candidate matches only.  They are useful
                # for explaining the next read, but they are not
                # source-grounded facts and must never claim scientific
                # closure before extraction and binding run.
                "candidate_coverage_complete": not uncovered_fields,
                "evidence_grounding_complete": False,
                "closure_basis": "candidate_source_match_only",
            }
        )
        for (
            (
                _priority,
                _position,
                source_kind,
                source_ref,
                role,
                _candidate_matched_fields,
                _term_hits,
                _specificity,
            ),
            matched_fields,
            anchor_refs,
        ) in selected_candidates:
            route = EvidenceCandidate.from_mapping(
                {
                    "objective_id": objective_id,
                    "document_id": document_id,
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "role": role,
                    "extractable": True,
                    "reason": (
                        (
                            "Same-paper structural neighbor selected for result "
                            "Source(s): "
                            if not matched_fields
                            else "Same-paper context expansion for result Source(s): "
                        )
                        + f"{', '.join(sorted(anchor_refs))}. Matched Source fields: "
                        f"{', '.join(sorted(matched_fields)) or 'none; requires validation'}."
                    ),
                    "confidence": 0.8,
                    "context_fields": sorted(matched_fields),
                }
            )
            adaptive_routes.append(route)
            existing_source_keys.add(
                (objective_id, document_id, source_kind, source_ref)
            )
    return tuple(adaptive_routes)


_ADAPTIVE_CONTEXT_FIELD_MARKERS: dict[str, tuple[str, ...]] = {
    "material": (
        "material",
        "alloy",
        "powder",
        "feedstock",
        "composition",
        "substrate",
    ),
    "variable": (
        "parameter",
        "process",
        "laser",
        "energy",
        "power",
        "speed",
        "temperature",
        "time",
        "condition",
        "treatment",
        "fabricat",
    ),
    # ``process`` is a separate completeness family from the Objective
    # variable.  A result may name the changed variable but still omit fixed
    # process conditions that a researcher needs to compare papers.
    "process": (
        "laser",
        "energy",
        "power",
        "speed",
        "temperature",
        "thermal",
        "condition",
        "treatment",
        "dose",
        "cooling",
        "preheat",
        "scan",
        "fabricat",
        "manufactur",
    ),
    "comparison": (
        "compar",
        "baseline",
        "control",
        "reference",
        "condition",
        "sample",
        "specimen",
        "result",
    ),
    "outcome": (
        "result",
        "outcome",
        "property",
        "mechanical",
        "microstruct",
        "grain",
        "defect",
        "porosity",
        "density",
    ),
    "sample": (
        "sample",
        "specimen",
        "coupon",
        "geometry",
        "orientation",
    ),
    "test": (
        "test",
        "tensile",
        "hardness",
        "characteriz",
        "measure",
        "microstruct",
        "grain",
    ),
}

_ADAPTIVE_CONTEXT_HEADING_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "design",
        ("comparison", "sample", "variable"),
    ),
    (
        "method",
        ("material", "sample", "variable", "process", "comparison"),
    ),
    (
        "material",
        ("material", "sample"),
    ),
    (
        "process",
        ("variable", "process", "comparison", "sample"),
    ),
    (
        "specimen",
        ("sample", "comparison"),
    ),
    (
        "sample",
        ("sample", "comparison"),
    ),
    (
        "condition",
        ("comparison", "variable"),
    ),
    (
        "test",
        ("test", "outcome"),
    ),
    (
        "measure",
        ("test", "outcome"),
    ),
    (
        "characteriz",
        ("test", "outcome"),
    ),
    (
        "result",
        ("outcome", "comparison"),
    ),
    (
        "analysis",
        ("outcome", "test"),
    ),
)


def _objective_missing_context_fields(
    unit: ExtractedEvidenceDraft,
    objective: ResearchObjective,
) -> frozenset[str]:
    """Return evidence fields still needed before this paper can be compared."""
    missing: set[str] = set()
    result = unit.reported_result
    comparison = unit.comparison
    if result is None:
        missing.add("outcome")
    if not unit.changed_variables or any(
        variable.baseline_value in (None, "")
        or variable.target_value in (None, "")
        for variable in unit.changed_variables
    ):
        missing.add("variable")
    if comparison is None or not comparison.comparable:
        missing.add("comparison")
    if objective.material_scope and not unit.scientific_context.material:
        missing.add("material")
    if not unit.scientific_context.sample and not (
        comparison is not None
        and comparison.comparable
        and str(comparison.baseline_label or "").strip()
        and str(comparison.target_label or "").strip()
    ):
        missing.add("sample")
    # Changed-variable endpoints define the treatment contrast, not the fixed
    # process conditions needed to interpret that contrast.  A researcher
    # still checks the same paper for settings shared by both groups.  Keep the
    # family open until at least one non-varied process fact is source-grounded;
    # a bounded unsuccessful search becomes an explicit scope gap rather than
    # silently upgrading the result to a complete experiment.
    has_fixed_process_context = any(
        _objective_attribute_is_experimental_context(attribute)
        and not any(
            property_matching.axis_values_match(attribute.name, variable.name)
            or property_matching.process_axis_matches_objective_scope(
                attribute.name,
                variable.name,
            )
            for variable in unit.changed_variables
        )
        for attribute in unit.scientific_context.process
    )
    if not has_fixed_process_context:
        missing.add("process")
    if not unit.scientific_context.test:
        missing.add("test")
    return frozenset(missing)


def _objective_attribute_is_experimental_context(attribute: Any) -> bool:
    """Return whether a context value describes the physical experiment.

    Older persisted Evidence has no ``context_scope`` and remains eligible via
    ``unknown``. Explicit simulation or background values stay visible for
    audit, but cannot close the experimental conditions required to interpret a
    measured comparison.
    """

    return str(getattr(attribute, "context_scope", "unknown") or "unknown").strip().casefold() in {
        "experimental",
        "unknown",
    }


def _objective_context_pending_source_keys(
    units: Iterable[ExtractedEvidenceDraft],
    objectives: tuple[ResearchObjective, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    objective_by_id = {objective.objective_id: objective for objective in objectives}
    context_seed = tuple(
        unit
        for unit in units
        if unit.reported_result is None and unit.evidence_role in _OBJECTIVE_CONTEXT_ROLES
    )
    return tuple(
        sorted(
            {
                (
                    unit.objective_id,
                    unit.document_id,
                    unit.source_kind or "",
                    unit.source_ref or "",
                )
                for unit in units
                if (
                    (objective := objective_by_id.get(unit.objective_id)) is not None
                    and _objective_fact_needs_context(unit, objective)
                    and not _objective_context_bundle_can_bind_result(
                        unit,
                        context_seed=context_seed,
                        objective=objective,
                    )
                )
            }
        )
    )


def _objective_route_identity(
    route: EvidenceCandidate,
) -> tuple[str, str, str, str]:
    return (
        route.objective_id,
        route.document_id,
        route.source_kind,
        route.source_ref,
    )


def _objective_result_recovery_routes(
    *,
    source_facts: tuple[ExtractedEvidenceDraft, ...],
    routes: tuple[EvidenceCandidate, ...],
    attempted_keys: set[tuple[str, str, str, str]],
    objectives: tuple[ResearchObjective, ...],
) -> tuple[EvidenceCandidate, ...]:
    """Return direct-result routes whose first read is not yet closed.

    A researcher may find the measured values in Results and then discover the
    variable endpoints, material, or test conditions in Methods.  Context
    expansion therefore rereads the exact result Source both when the first
    pass returned no result and when it returned a partial result.  The route
    identity, rather than a lexical match, is the authority; one reread per
    route bounds additional model work.
    """

    objective_by_id = {objective.objective_id: objective for objective in objectives}
    context_seed = tuple(
        unit
        for unit in source_facts
        if unit.reported_result is None
        and unit.evidence_role in _OBJECTIVE_CONTEXT_ROLES
    )
    pending_keys: set[tuple[str, str, str, str]] = set()
    missing_fields_by_key: dict[tuple[str, str, str, str], set[str]] = {}
    for unit in source_facts:
        if (
            unit.evidence_role not in _DIRECT_RESULT_ROUTE_ROLES
            or unit.selection_status == "failed"
            or unit.resolution_status not in {"unresolved", "partial"}
        ):
            continue
        objective = objective_by_id.get(unit.objective_id)
        if objective is None or not _objective_fact_needs_context(unit, objective):
            continue
        if unit.reported_result is None:
            # An empty direct-result read needs a grounded context Source before
            # it can be revisited.  This preserves the existing bounded retry
            # path without retrying when context discovery made no progress.
            if not any(
                context.objective_id == unit.objective_id
                and context.document_id == unit.document_id
                and context.scientific_context.has_content
                for context in context_seed
            ):
                continue
        else:
            # If comparison labels are already explicit sample/group labels,
            # deterministic reconstruction can bind them without another model
            # call. Revisit only when the context is present but the result
            # still needs a semantic re-read (for example labels are numeric
            # levels while Results names only S1/S2).
            if unit.comparison is None:
                # Results may report the measured values without naming the
                # comparison groups at all. Once Methods supplies explicit
                # sample and process facts, a bounded reread can recover the
                # missing labels and variable endpoints.
                has_grouped_context = any(
                    context.objective_id == unit.objective_id
                    and context.document_id == unit.document_id
                    and context.scientific_context.sample
                    and context.scientific_context.process
                    for context in context_seed
                )
                if not has_grouped_context:
                    continue
            elif not _objective_context_bundle_can_bind_result(
                unit,
                context_seed=context_seed,
                objective=objective,
            ):
                continue
            comparison = unit.comparison
            wanted_labels = (
                {
                    _objective_column_key(comparison.baseline_label),
                    _objective_column_key(comparison.target_label),
                }
                if comparison is not None
                else set()
            )
            explicit_group_labels = {
                _objective_column_key(attribute.value)
                for context in context_seed
                if (
                    context.objective_id == unit.objective_id
                    and context.document_id == unit.document_id
                )
                for attribute in context.scientific_context.sample
                if attribute.value not in (None, "")
            }
            if wanted_labels and wanted_labels <= explicit_group_labels:
                continue
        key = (
            unit.objective_id,
            unit.document_id,
            unit.source_kind or "",
            unit.source_ref or "",
        )
        pending_keys.add(key)
        missing_fields_by_key.setdefault(key, set()).update(
            _objective_missing_context_fields(unit, objective)
        )
    if not pending_keys:
        return ()
    selected: dict[tuple[str, str, str, str], EvidenceCandidate] = {}
    for route in routes:
        key = _objective_route_identity(route)
        if (
            key not in pending_keys
            or key in attempted_keys
            or not route.extractable
            or route.role not in _DIRECT_RESULT_ROUTE_ROLES
        ):
            continue
        route_record = route.to_record()
        route_record["context_fields"] = sorted(
            set(route.context_fields) | missing_fields_by_key.get(key, set())
        )
        selected.setdefault(key, EvidenceCandidate.from_mapping(route_record))
    return tuple(selected.values())


def _merge_recovered_result_units(
    *,
    units: list[ExtractedEvidenceDraft],
    document_state_units: dict[tuple[str, str], list[ExtractedEvidenceDraft]],
    recovered_units: tuple[ExtractedEvidenceDraft, ...],
    seen: set[str],
) -> None:
    """Replace an unresolved direct-result placeholder when reread succeeds."""

    for recovered in recovered_units:
        recovered_key = (
            recovered.objective_id,
            recovered.document_id,
            recovered.source_kind or "",
            recovered.source_ref or "",
        )
        if recovered.reported_result is not None:
            stale_units = [
                unit
                for unit in units
                if (
                    unit.evidence_role in _DIRECT_RESULT_ROUTE_ROLES
                    and unit.selection_status != "failed"
                    and unit.resolution_status in {"unresolved", "partial"}
                    and (
                        unit.objective_id,
                        unit.document_id,
                        unit.source_kind or "",
                        unit.source_ref or "",
                    )
                    == recovered_key
                )
            ]
            for stale in stale_units:
                units.remove(stale)
                seen.discard(stale.evidence_id)
                state_units = document_state_units.get(
                    (stale.objective_id, stale.document_id),
                    [],
                )
                if stale in state_units:
                    state_units.remove(stale)
        if recovered.evidence_id in seen:
            continue
        seen.add(recovered.evidence_id)
        units.append(recovered)
        document_state_units.setdefault(
            (recovered.objective_id, recovered.document_id),
            [],
        ).append(recovered)


def _objective_context_semantic_signature(
    context_seed: Iterable[ExtractedEvidenceDraft],
) -> tuple[tuple[str, ...], ...]:
    """Represent read context by grounded values, ignoring Source identity."""

    signature: set[tuple[str, ...]] = set()
    for unit in context_seed:
        for group in ("material", "sample", "process", "test"):
            for attribute in getattr(unit.scientific_context, group):
                signature.add(
                    (
                        unit.objective_id,
                        unit.document_id,
                        group,
                        _objective_column_key(attribute.name),
                        _objective_column_key(str(attribute.value)),
                        _objective_column_key(attribute.unit or ""),
                    )
                )
    return tuple(sorted(signature))


def _objective_result_semantic_signature(
    units: Iterable[ExtractedEvidenceDraft],
) -> tuple[tuple[str, ...], ...]:
    signature: set[tuple[str, ...]] = set()
    for unit in units:
        result = unit.reported_result
        if result is None:
            continue
        comparison = unit.comparison
        changed_variables = tuple(
            sorted(
                (
                    _objective_column_key(variable.name),
                    _objective_column_key(str(variable.baseline_value)),
                    _objective_column_key(str(variable.target_value)),
                    _objective_column_key(variable.unit or ""),
                )
                for variable in unit.changed_variables
            )
        )
        signature.add(
            (
                unit.objective_id,
                unit.document_id,
                _objective_column_key(result.outcome),
                _objective_column_key(str(result.value)),
                _objective_column_key(str(result.baseline_value)),
                _objective_column_key(str(result.target_value)),
                _objective_column_key(result.unit or ""),
                result.direction,
                result.result_kind,
                _objective_column_key(unit.attribution_scope),
                _objective_column_key(
                    comparison.baseline_label if comparison else ""
                ),
                _objective_column_key(comparison.target_label if comparison else ""),
                str(bool(comparison and comparison.comparable)),
                json.dumps(changed_variables, ensure_ascii=True),
            )
        )
    return tuple(sorted(signature))


def _objective_context_progress_state(
    units: Iterable[ExtractedEvidenceDraft],
    objectives: tuple[ResearchObjective, ...],
) -> tuple[
    tuple[tuple[str, str, str, str], ...],
    tuple[tuple[str, ...], ...],
    tuple[tuple[str, ...], ...],
]:
    units_tuple = tuple(units)
    return (
        _objective_context_pending_source_keys(units_tuple, objectives),
        _objective_context_semantic_signature(
            unit
            for unit in units_tuple
            if unit.reported_result is None and unit.evidence_role in _OBJECTIVE_CONTEXT_ROLES
        ),
        _objective_result_semantic_signature(units_tuple),
    )


def _record_objective_context_scope_gap(
    *,
    collection_id: str,
    context_round: int,
    units: list[ExtractedEvidenceDraft],
    objectives: tuple[ResearchObjective, ...],
    reason: str,
) -> None:
    """Stop an unproductive closure loop while preserving the unresolved fact."""

    objective_by_id = {objective.objective_id: objective for objective in objectives}
    context_seed = tuple(
        unit
        for unit in units
        if unit.reported_result is None and unit.evidence_role in _OBJECTIVE_CONTEXT_ROLES
    )
    pending: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        objective = objective_by_id.get(unit.objective_id)
        if objective is None or not _objective_fact_needs_context(unit, objective):
            continue
        # The extraction draft may still be partial because its result and
        # Methods facts live in separate Sources.  If the inspected same-paper
        # context already binds the comparison labels, the later reconstruction
        # step can close that gap deterministically; do not report it as an
        # unresolved scope gap here.
        if _objective_context_bundle_can_bind_result(
            unit,
            context_seed=context_seed,
            objective=objective,
        ):
            continue
        missing_fields = sorted(_objective_missing_context_fields(unit, objective))
        if not missing_fields:
            continue
        pending.append(
            {
                "objective_id": unit.objective_id,
                "document_id": unit.document_id,
                "source_kind": unit.source_kind,
                "source_ref": unit.source_ref,
                "missing_fields": missing_fields,
            }
        )
        gap_reason = (
            f"Scope gap: {reason} Missing same-paper context: "
            f"{', '.join(missing_fields) or 'unknown'}."
        )
        existing_reason = unit.selection_reason or ""
        if gap_reason not in existing_reason:
            payload = unit.to_record()
            payload["selection_reason"] = (
                f"{existing_reason} {gap_reason}".strip()
            )
            units[index] = ExtractedEvidenceDraft.from_mapping(payload)
    if pending:
        record_analysis_diagnostic(
            {
                "trace_type": "objective_context_scope_gap",
                "collection_id": collection_id,
                "context_round": context_round,
                "reason": reason,
                "pending": pending,
            }
        )


def _objective_context_bundle_can_bind_result(
    unit: ExtractedEvidenceDraft,
    *,
    context_seed: tuple[ExtractedEvidenceDraft, ...],
    objective: ResearchObjective | None = None,
) -> bool:
    """Return whether read same-paper conditions can bind this result.

    Separate Methods rows for the comparison groups are enough for the later
    deterministic paper reconstruction. A generic Methods paragraph without
    explicit group identity is not enough, so the result is revisited with the
    bundle in that case.
    """

    if unit.reported_result is None or unit.comparison is None:
        return False
    comparison = unit.comparison
    wanted = {
        _objective_column_key(comparison.baseline_label),
        _objective_column_key(comparison.target_label),
    }
    if not all(wanted):
        return False
    same_paper_context = tuple(
        context
        for context in context_seed
        if context.document_id == unit.document_id
        and context.objective_id == unit.objective_id
        and context.selection_status != "failed"
        and context.reported_result is None
    )

    # Callers without an Objective use this helper only to ask whether opaque
    # result labels can bind to explicit same-paper condition values.  Keep
    # that narrow behavior while production closure below evaluates every
    # researcher-required field family.
    if objective is None:
        found: set[str] = set()
        for context in same_paper_context:
            if not context.scientific_context.process:
                continue
            context_values = {
                candidate
                for attribute in (
                    attribute
                    for group in ("sample", "process", "test")
                    for attribute in getattr(context.scientific_context, group)
                )
                for candidate in (
                    _objective_column_key(attribute.value),
                    _objective_column_key(
                        f"{attribute.value} {attribute.unit or ''}"
                    ),
                )
                if attribute.value not in (None, "")
            }
            found.update(wanted & context_values)
        return wanted <= found

    missing_fields = set(_objective_missing_context_fields(unit, objective))
    if not missing_fields:
        return True
    if "outcome" in missing_fields or "comparison" in missing_fields:
        return False

    changed_axes = tuple(variable.name for variable in unit.changed_variables)

    def is_changed_axis(name: object) -> bool:
        return any(
            property_matching.axis_values_match(name, axis)
            or property_matching.process_axis_matches_objective_scope(name, axis)
            for axis in changed_axes
        )

    group_identity_keys = {
        "case",
        "condition",
        "condition_no",
        "condition_number",
        "group",
        "sample",
        "sample_id",
        "sample_no",
        "sample_number",
        "specimen",
        "specimen_id",
    }
    document_context: list[ExtractedEvidenceDraft] = []
    group_context: dict[str, list[ExtractedEvidenceDraft]] = {
        label: [] for label in wanted
    }
    all_material_values: list[object] = []
    for context in same_paper_context:
        all_material_values.extend(
            attribute.value
            for attribute in context.scientific_context.material
            if attribute.value not in (None, "")
        )
        labels = {
            _objective_column_key(attribute.value)
            for attribute in context.scientific_context.sample
            if _objective_column_key(attribute.name) in group_identity_keys
            and attribute.value not in (None, "")
        }
        matching_labels = labels & wanted
        if len(labels) == 1 and len(matching_labels) == 1:
            group_context[next(iter(matching_labels))].append(context)
        elif not labels:
            document_context.append(context)

    if "material" in missing_fields and all_material_values:
        if all(
            property_matching.material_values_match_for_scope(left, right)
            for position, left in enumerate(all_material_values)
            for right in all_material_values[position + 1 :]
        ):
            missing_fields.discard("material")

    document_values: dict[
        tuple[str, str],
        set[tuple[str, str]],
    ] = {}
    for context in document_context:
        for section in ("process", "test"):
            for attribute in getattr(context.scientific_context, section):
                if section == "process" and not _objective_attribute_is_experimental_context(
                    attribute
                ):
                    continue
                name = (
                    property_matching.normalize_property_label(attribute.name)
                    or _objective_column_key(attribute.name)
                )
                if not name or (section == "process" and is_changed_axis(attribute.name)):
                    continue
                document_values.setdefault((section, name), set()).add(
                    (
                        _objective_column_key(str(attribute.value)),
                        _objective_column_key(attribute.unit or ""),
                    )
                )
    if "process" in missing_fields and any(
        section == "process" and len(values) == 1
        for (section, _name), values in document_values.items()
    ):
        missing_fields.discard("process")
    if "test" in missing_fields and any(
        section == "test" and len(values) == 1
        for (section, _name), values in document_values.items()
    ):
        missing_fields.discard("test")

    if all(group_context.values()):
        group_values: dict[str, dict[tuple[str, str], set[tuple[str, str]]]] = {}
        for label, contexts in group_context.items():
            values: dict[tuple[str, str], set[tuple[str, str]]] = {}
            for context in contexts:
                for section in ("process", "test"):
                    for attribute in getattr(context.scientific_context, section):
                        if section == "process" and not _objective_attribute_is_experimental_context(
                            attribute
                        ):
                            continue
                        name = (
                            property_matching.normalize_property_label(attribute.name)
                            or _objective_column_key(attribute.name)
                        )
                        if not name:
                            continue
                        values.setdefault((section, name), set()).add(
                            (
                                _objective_column_key(str(attribute.value)),
                                _objective_column_key(attribute.unit or ""),
                            )
                        )
            group_values[label] = values

        baseline_values = group_values[_objective_column_key(comparison.baseline_label)]
        target_values = group_values[_objective_column_key(comparison.target_label)]
        unambiguous_common_keys = {
            key
            for key in set(baseline_values) & set(target_values)
            if len(baseline_values[key]) == 1 and len(target_values[key]) == 1
        }
        if "process" in missing_fields and any(
            section == "process"
            and not is_changed_axis(name)
            and baseline_values[(section, name)] == target_values[(section, name)]
            for section, name in unambiguous_common_keys
        ):
            missing_fields.discard("process")
        if "test" in missing_fields and any(
            section == "test"
            and baseline_values[(section, name)] == target_values[(section, name)]
            for section, name in unambiguous_common_keys
        ):
            missing_fields.discard("test")
        if "variable" in missing_fields:
            shared_process_keys = {
                key
                for key in unambiguous_common_keys
                if key[0] == "process"
            }
            differing_process_keys = {
                key
                for key in shared_process_keys
                if baseline_values[key] != target_values[key]
            }
            if differing_process_keys:
                missing_fields.discard("variable")

    return not missing_fields


def _objective_context_search_terms(
    *,
    objective: ResearchObjective,
    source_facts: tuple[ExtractedEvidenceDraft, ...],
    document_id: str,
    objective_id: str,
) -> tuple[str, ...]:
    terms: list[str] = []
    for value in (
        *objective.material_scope,
        *objective.variables,
        *objective.outcomes,
    ):
        normalized = " ".join(str(value or "").strip().casefold().split())
        if len(normalized) >= 3 and normalized not in terms:
            terms.append(normalized)
    for unit in source_facts:
        if unit.document_id != document_id or unit.objective_id != objective_id:
            continue
        comparison = unit.comparison
        if comparison is not None:
            for value in (
                comparison.baseline_label,
                comparison.target_label,
                *comparison.axis_names,
            ):
                normalized = " ".join(str(value or "").strip().casefold().split())
                if len(normalized) >= 3 and normalized not in terms:
                    terms.append(normalized)
        for context in (
            unit.scientific_context.material,
            unit.scientific_context.sample,
            unit.scientific_context.process,
            unit.scientific_context.test,
        ):
            for attribute in context:
                normalized = " ".join(
                    str(attribute.value or "").strip().casefold().split()
                )
                if len(normalized) >= 3 and normalized not in terms:
                    terms.append(normalized)
    return tuple(terms)


def _objective_context_search_term_fields(
    *,
    objective: ResearchObjective,
    source_facts: tuple[ExtractedEvidenceDraft, ...],
    document_id: str,
    objective_id: str,
) -> dict[str, frozenset[str]]:
    """Map grounded search terms to the context families they can close.

    A term match is only useful when its scientific role is known.  The old
    implementation treated every objective term as evidence for every missing
    field, which made one common word route an entire paper.  This map keeps
    recall for arbitrary material and outcome names without promoting a hit to
    unrelated context families.
    """

    fields_by_term: dict[str, set[str]] = {}

    def add(value: object, *fields: str) -> None:
        normalized = " ".join(str(value or "").strip().casefold().split())
        if len(normalized) < 3:
            return
        fields_by_term.setdefault(normalized, set()).update(fields)

    for value in objective.material_scope:
        add(value, "material")
    for value in objective.variables:
        add(value, "variable", "comparison", "process")
    for value in objective.outcomes:
        # Naming a measured property does not establish how it was measured.
        # Test context requires an explicit method, standard, or test condition.
        add(value, "outcome")

    for unit in source_facts:
        if unit.document_id != document_id or unit.objective_id != objective_id:
            continue
        comparison = unit.comparison
        if comparison is not None:
            for value in (
                comparison.baseline_label,
                comparison.target_label,
                *comparison.axis_names,
            ):
                add(value, "comparison", "variable")
        for group, fields in (
            (unit.scientific_context.material, ("material",)),
            (unit.scientific_context.sample, ("sample", "comparison")),
            (unit.scientific_context.process, ("variable", "comparison")),
            (unit.scientific_context.test, ("test", "outcome")),
        ):
            for attribute in group:
                add(attribute.value, *fields)

    return {term: frozenset(fields) for term, fields in fields_by_term.items()}


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_adaptive_context_term_is_mentioned(text, term) for term in terms)


def _adaptive_context_term_hits(
    text: str,
    terms: tuple[str, ...],
    *,
    term_fields: Mapping[str, frozenset[str]] | None = None,
    wanted_fields: set[str] | frozenset[str] | None = None,
) -> int:
    return sum(
        1
        for term in terms
        if (
            (term_fields is None or wanted_fields is None)
            or bool(term_fields.get(term, frozenset()) & set(wanted_fields))
        )
        and _adaptive_context_term_is_mentioned(text, term)
    )


def _adaptive_context_term_is_mentioned(text: str, term: str) -> bool:
    """Match a grounded search term independent of ordinary word order.

    Scientific prose commonly alternates between noun phrases such as
    ``build platform preheating`` and clauses such as ``preheating the build
    platform``.  Both name the same explicit words; this does not introduce a
    synonym or infer a missing fact.
    """

    return bool(
        str(term or "").strip()
        and property_matching.axis_label_is_mentioned(text, term)
    )


def _adaptive_context_specificity_score(text: str) -> int:
    """Prefer Sources that expose concrete groups or condition values.

    Section headings and repeated objective words are useful for recall but are
    weak evidence that a Source can close a comparison.  Numeric endpoints and
    explicit group labels are a domain-neutral signal that a researcher would
    inspect this Source before generic procedural prose.
    """

    number_count = min(len(_NUMBER_PATTERN.findall(text)), 6)
    group_count = min(len(_GROUP_LABEL_PATTERN.findall(text)), 4)
    return number_count + (2 * group_count)


def _adaptive_context_matched_fields(
    *,
    heading: str,
    text: str,
    missing_fields: set[str] | frozenset[str],
    specific_terms: tuple[str, ...],
    specific_term_fields: Mapping[str, frozenset[str]] | None = None,
) -> tuple[str, ...]:
    searchable = " ".join((heading, text)).casefold()
    matched = {
        field
        for field in missing_fields
        if any(marker in searchable for marker in _ADAPTIVE_CONTEXT_FIELD_MARKERS[field])
    }
    heading_fields = {
        field
        for marker, fields in _ADAPTIVE_CONTEXT_HEADING_FIELDS
        if marker in heading
        for field in fields
    }
    matched.update(heading_fields & set(missing_fields))
    for term in specific_terms:
        if not _adaptive_context_term_is_mentioned(searchable, term):
            continue
        matched.update(
            (specific_term_fields or {}).get(term, frozenset())
            & set(missing_fields)
        )
    return tuple(sorted(matched))


def _objective_fact_needs_context(
    unit: ExtractedEvidenceDraft,
    objective: ResearchObjective,
) -> bool:
    if unit.selection_status == "failed":
        return False
    if (
        unit.selection_status == "candidate"
        and unit.selection_reason in _NEEDS_CONTEXT_SELECTION_REASONS
    ):
        return True
    if unit.reported_result is None:
        return False
    if unit.evidence_role in {
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
    }:
        return False
    # A complete result endpoint is not a complete study record.  Researchers
    # still inspect the paper's Methods, sample, process, and test conditions
    # before accepting a comparison.  Drive expansion from the missing field
    # families instead of treating a model-complete comparison as closure.
    return bool(_objective_missing_context_fields(unit, objective))


def _adaptive_context_source_heading(
    *,
    heading_path: Any,
    document_tree: SourceDocumentTree | None,
    source_ref_kind: str,
    source_ref: str,
) -> str:
    heading = heading_path
    if isinstance(heading, (list, tuple)):
        direct = " ".join(_text(part) for part in heading if _text(part))
    else:
        direct = _text(heading)
    if direct.strip():
        return direct.casefold()
    if document_tree is None or not source_ref:
        return ""
    node = _tree_node_for_route_source(
        document_tree=document_tree,
        source_ref_kind=source_ref_kind,
        source_ref_id=source_ref,
    )
    if node is None:
        return ""
    return " ".join(
        _text(part)
        for part in _tree_node_section_path(document_tree=document_tree, node=node)
        if _text(part)
    ).casefold()


def _adaptive_context_heading(
    block: Any,
    *,
    document_tree: SourceDocumentTree | None = None,
    source_ref_kind: str = "block",
    source_ref: str | None = None,
) -> str:
    return _adaptive_context_source_heading(
        heading_path=getattr(block, "heading_path", ""),
        document_tree=document_tree,
        source_ref_kind=source_ref_kind,
        source_ref=source_ref or _text(getattr(block, "block_id", "")),
    )


def _adaptive_context_is_relevant(heading: str) -> bool:
    return any(marker in heading for marker in _ADAPTIVE_CONTEXT_HEADING_MARKERS)


def _adaptive_context_route_role(heading: str) -> str:
    if any(marker in heading for marker in _ADAPTIVE_CONTEXT_TEST_MARKERS):
        return "test_condition"
    if any(
        marker in heading
        for marker in ("characteriz", "microstruct", "grain", "defect")
    ):
        return "characterization"
    return "process_or_treatment"


def _objective_table_route_should_skip_llm_fallback(
    route: EvidenceCandidate,
) -> bool:
    # A complete table is the preferred input, but deterministic column
    # mapping is not a proof that the table has no objective evidence.  When
    # the matrix parser cannot resolve a result or condition, a bounded
    # source-local semantic extraction must get one chance to read the same
    # Markdown table a researcher would read.  Non-extractable roles never
    # reach this function, so keeping this boundary open cannot promote
    # background tables into Evidence.
    return False


def _repair_objective_table_source_if_needed(
    *,
    collection_id: str,
    route: EvidenceCandidate,
    source: dict[str, Any],
    paper_facts_extractor: PaperFactsExtractor | None,
    unavailable_error: Exception | None = None,
) -> tuple[dict[str, Any], Exception | None]:
    if not _objective_table_source_needs_llm_structural_repair(
        route=route,
        source=source,
    ):
        return source, None
    original_matrix = _normalized_objective_table_matrix(source.get("table_matrix"))
    canonical_matrix = _canonical_objective_table_matrix(
        source=source,
        matrix=original_matrix,
    )
    model_request_count = 0
    model_row_count: int | None = None
    final_row_count: int | None = None
    model_repair_count = 0
    deterministic_rebind_count = 0
    number_sequence_verified: bool | None = None
    warnings: list[str] = []

    def record_trace(status: str, failure_reason: str | None = None) -> None:
        record_analysis_diagnostic(
            {
                "trace_type": "table_matrix_repair",
                "collection_id": collection_id,
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "table_id": route.source_ref,
                "page": source.get("page"),
                "status": status,
                "original_row_count": len(canonical_matrix),
                "model_row_count": model_row_count,
                "final_row_count": final_row_count,
                "model_request_count": model_request_count,
                "model_repair_count": model_repair_count,
                "fragment_row_reduction_count": (
                    max(0, len(canonical_matrix) - final_row_count)
                    if final_row_count is not None
                    else 0
                ),
                "deterministic_rebind_count": deterministic_rebind_count,
                "number_sequence_verified": number_sequence_verified,
                "warnings": list(dict.fromkeys(warnings)),
                "failure_reason": failure_reason,
            }
        )

    if unavailable_error is not None:
        record_trace(
            "provider_failed",
            f"{unavailable_error.__class__.__name__}: {unavailable_error}",
        )
        return source, unavailable_error
    try:
        if paper_facts_extractor is None:
            raise RuntimeError("table repair extractor is unavailable")
        repair_payloads = _build_objective_table_matrix_repair_payloads(
            route=route,
            source=source,
            paper_facts_extractor=paper_facts_extractor,
        )
        parsed_repair_items = []
        for repair_payload in repair_payloads:
            model_request_count += 1
            parsed_repair_items.append(
                (
                    repair_payload,
                    paper_facts_extractor.repair_table_matrix(repair_payload),
                )
            )
        parsed_repairs = tuple(parsed_repair_items)
    except Exception as exc:
        logger.exception(
            "Research objective table matrix repair failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_ref=%s",
            collection_id,
            route.source_ref,
            route.objective_id,
            route.document_id,
            route.source_ref,
        )
        record_trace("provider_failed", f"{exc.__class__.__name__}: {exc}")
        return source, exc

    repair_records = []
    for repair_payload, parsed in parsed_repairs:
        repairs = getattr(parsed, "repairs", None)
        if repairs:
            row_offset = int(
                repair_payload["source"]["table_slice"]["first_source_row_index"]
            )
            for repair_item in repairs:
                repair_record = (
                    repair_item.model_dump()
                    if hasattr(repair_item, "model_dump")
                    else dict(repair_item)
                )
                if repair_record.get("row_index") is not None:
                    repair_record["row_index"] = (
                        int(repair_record["row_index"]) + row_offset - 1
                    )
                repair_records.append(repair_record)
        warnings.extend(
            str(warning)
            for warning in getattr(parsed, "warnings", None) or ()
            if str(warning).strip()
        )
    model_repair_count = len(repair_records)
    repaired_matrix = _merge_objective_table_matrix_repairs(
        source=source,
        canonical_matrix=canonical_matrix,
        parsed_repairs=parsed_repairs,
    )
    model_row_count = len(repaired_matrix)
    if not repaired_matrix:
        reason = "table matrix repair returned no usable matrix"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    repaired_matrix, residual_repairs = (
        _cleanup_objective_repaired_table_matrix_residual_fragments(
            original_matrix=canonical_matrix,
            repaired_matrix=repaired_matrix,
            column_headers=source.get("column_headers", ()),
        )
    )
    repaired_matrix, uncertainty_repairs = (
        _rebind_objective_table_mean_uncertainty_columns(
            original_matrix=canonical_matrix,
            repaired_matrix=repaired_matrix,
            column_headers=source.get("column_headers", ()),
        )
    )
    deterministic_rebind_count = len(uncertainty_repairs)
    final_row_count = len(repaired_matrix)
    if (
        repaired_matrix == canonical_matrix
        and _objective_table_matrix_has_structural_fragments(canonical_matrix)
    ):
        reason = "table matrix repair left the fragmented matrix unchanged"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    if _objective_table_matrix_has_structural_fragments(repaired_matrix):
        reason = "table matrix repair returned a structurally fragmented matrix"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    number_sequence_verified = (
        _objective_table_repair_preserves_result_number_sequences(
            original_matrix=canonical_matrix,
            repaired_matrix=repaired_matrix,
        )
    )
    if not number_sequence_verified:
        reason = "table matrix repair changed or reordered source result numbers"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    if not _objective_table_repair_preserves_source_tokens(
        original_matrix=canonical_matrix,
        repaired_matrix=repaired_matrix,
    ):
        reason = "table matrix repair introduced tokens not present in source"
        record_trace("rejected", reason)
        return source, ValueError(reason)
    repaired_source = dict(source)
    repaired_source["raw_table_matrix"] = source.get("table_matrix", [])
    repaired_source["table_matrix"] = repaired_matrix
    repaired_source["table_matrix_structural_repair_applied"] = True
    repair_records.extend(residual_repairs)
    repair_records.extend(uncertainty_repairs)
    if repair_records:
        repaired_source["table_matrix_repairs"] = repair_records
    if warnings:
        repaired_source["table_matrix_repair_warnings"] = list(
            dict.fromkeys(warnings)
        )
    record_trace("verified")
    return repaired_source, None


def _build_objective_table_matrix_repair_payloads(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    paper_facts_extractor: PaperFactsExtractor,
) -> tuple[dict[str, Any], ...]:
    matrix = _normalized_objective_table_matrix(source.get("table_matrix"))
    canonical_matrix = _canonical_objective_table_matrix(source=source, matrix=matrix)
    if not canonical_matrix:
        return ()
    headers = canonical_matrix[0]
    body_rows = canonical_matrix[1:]

    def payload(start: int, end: int) -> dict[str, Any]:
        return _build_objective_table_matrix_repair_payload(
            route=route,
            source=source,
            headers=headers,
            body_rows=body_rows,
            start=start,
            end=end,
        )

    estimator = getattr(
        paper_facts_extractor,
        "estimate_table_matrix_repair_prompt_tokens",
        None,
    )
    if not callable(estimator):
        return (payload(0, len(body_rows)),)

    bounded: list[dict[str, Any]] = []

    def append_bounded(start: int, end: int) -> None:
        candidate = payload(start, end)
        if (
            int(estimator(candidate)) <= _TABLE_MATRIX_REPAIR_PROMPT_TOKEN_LIMIT
            or end - start <= 1
        ):
            bounded.append(candidate)
            return
        midpoint = start + max(1, (end - start) // 2)
        append_bounded(start, midpoint)
        append_bounded(midpoint, end)

    append_bounded(0, len(body_rows))
    return tuple(bounded)


def _build_objective_table_matrix_repair_payload(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    headers: list[str],
    body_rows: list[list[str]],
    start: int,
    end: int,
) -> dict[str, Any]:
    first_source_row_index = start + 1
    compact_source = {
        "source_kind": source.get("source_kind"),
        "source_ref": source.get("source_ref"),
        "document_id": source.get("document_id"),
        "page": source.get("page"),
        "caption_text": source.get("caption_text"),
        "heading_path": source.get("heading_path"),
        "column_headers": headers,
        "table_markdown": render_markdown_table(
            [headers, *body_rows[start:end]],
            headers,
            header_row_count=1,
        ),
        "table_visual_text": str(source.get("table_visual_text") or "").strip()
        or None,
        "table_slice": {
            "first_source_row_index": first_source_row_index,
            "end_source_row_index": end + 1,
            "total_body_rows": len(body_rows),
        },
    }
    return {
        "table_role": route.role,
        "repair_focus": [
            "repair parser-split cells",
            "preserve table width",
            "preserve numeric result cells exactly",
        ],
        "source": {
            key: value
            for key, value in compact_source.items()
            if value not in (None, "", [], {})
        },
    }


def _canonical_objective_table_matrix(
    *,
    source: dict[str, Any],
    matrix: list[list[str]],
) -> list[list[str]]:
    if not matrix:
        return []
    headers = [str(value).strip() for value in source.get("column_headers", ())]
    if not any(headers):
        headers = list(matrix[0])
    header_row_count = source.get("header_row_count", 1)
    try:
        body_start = max(0, min(int(header_row_count), len(matrix)))
    except (TypeError, ValueError):
        body_start = 1
    return [headers, *matrix[body_start:]]


def _merge_objective_table_matrix_repairs(
    *,
    source: dict[str, Any],
    canonical_matrix: list[list[str]],
    parsed_repairs: tuple[tuple[dict[str, Any], Any], ...],
) -> list[list[str]]:
    if not canonical_matrix or not parsed_repairs:
        return []
    headers = canonical_matrix[0]
    merged = [headers]
    for _repair_payload, parsed in parsed_repairs:
        repaired_slice = _validated_objective_repaired_table_matrix(
            source={**source, "column_headers": headers},
            repaired_table_matrix=getattr(parsed, "repaired_table_matrix", None),
        )
        if not repaired_slice:
            return []
        slice_rows = repaired_slice[1:] if _objective_row_matches_headers(
            tuple(repaired_slice[0]), tuple(headers)
        ) else repaired_slice
        merged.extend(slice_rows)
    # A layout parser may spill more than one logical row (for example when a
    # wrapped specimen label and its uncertainty land on separate grid rows).
    # The repair contract already verifies column width, source-token
    # conservation, and every numeric column sequence below.  Rejecting every
    # row-count reduction except one therefore discarded valid complete tables
    # for no scientific reason.  Keep only the monotonic bound here: a repair
    # may merge parser fragments, but it may never invent additional rows.
    if len(merged) < 2 or len(merged) > len(canonical_matrix):
        return []
    return merged


def _objective_table_repair_preserves_result_number_sequences(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
) -> bool:
    if not original_matrix or not repaired_matrix:
        return False
    expected_width = len(original_matrix[0])
    if expected_width != len(repaired_matrix[0]):
        return False
    if any(len(row) != expected_width for row in original_matrix):
        return False
    if any(len(row) != expected_width for row in repaired_matrix):
        return False
    return all(
        _objective_column_numeric_tokens(original_matrix, column_index)
        == _objective_column_numeric_tokens(repaired_matrix, column_index)
        for column_index in range(1, expected_width)
    )


_OBJECTIVE_TABLE_TOKEN_PATTERN = re.compile(
    r"[^\W_]+(?:[-_][^\W_]+)*",
    re.UNICODE,
)


def _objective_table_repair_preserves_source_tokens(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
) -> bool:
    """Reject repair text that cannot be assembled from the supplied table.

    Structural repair may move a parser-spilled label or join adjacent cells, but
    it must not create a new specimen name, process label, or numeric level. A
    multiset check is deliberately conservative: omission is allowed so the
    existing residual-fragment cleanup can remove a carried prefix, while any
    newly introduced lexical token is left unresolved for a researcher.
    """
    if not original_matrix or not repaired_matrix:
        return False
    original_tokens = Counter(
        token
        for row in original_matrix[1:]
        for cell in row
        for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(
            " ".join(str(cell or "").split()).casefold()
        )
    )
    repaired_tokens = Counter(
        token
        for row in repaired_matrix[1:]
        for cell in row
        for token in _OBJECTIVE_TABLE_TOKEN_PATTERN.findall(
            " ".join(str(cell or "").split()).casefold()
        )
    )
    return all(
        repaired_tokens[token] <= original_tokens[token]
        for token in repaired_tokens
    )


def _objective_column_numeric_tokens(
    matrix: list[list[str]],
    column_index: int,
) -> tuple[str, ...]:
    return tuple(
        match.group(0)
        for row in matrix[1:]
        for match in _NUMBER_PATTERN.finditer(str(row[column_index] or ""))
    )


def _objective_table_has_mergeable_trailing_fragment_row(
    matrix: list[list[str]],
) -> bool:
    if len(matrix) < 3 or len(matrix[-1]) < 2:
        return False
    row = [" ".join(str(cell or "").split()) for cell in matrix[-1]]
    nonempty_result_cells = [cell for cell in row[1:] if cell]
    if len(nonempty_result_cells) != 1:
        return False
    label = row[0]
    return bool(
        re.fullmatch(
            r"\(?\s*[-+]?\d+(?:\.\d+)?\s*/\s*[-+]?\d+(?:\.\d+)?\s*\)?",
            label,
        )
        and _objective_cell_is_uncertainty_fragment(nonempty_result_cells[0])
    )


def _objective_cell_is_uncertainty_fragment(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"\(?\s*(?:±|\+/-|\+-)\s*"
            r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*\)?",
            " ".join(str(value or "").split()),
        )
    )


def _objective_cell_is_mean_uncertainty_value(value: str) -> bool:
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    return bool(
        re.fullmatch(
            rf"\s*{number}\s*\(?\s*(?:±|\+/-|\+-)\s*{number}\s*\)?\s*",
            str(value or ""),
        )
    )


def _rebind_objective_table_mean_uncertainty_columns(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
    column_headers: Any,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    if len(repaired_matrix) < 2 or not original_matrix:
        return repaired_matrix, []
    width = len(repaired_matrix[0])
    if width < 2 or any(len(row) != width for row in repaired_matrix):
        return repaired_matrix, []
    if any(len(row) != width for row in original_matrix):
        return repaired_matrix, []

    body_row_count = len(repaired_matrix) - 1
    headers = [str(value).strip() for value in column_headers or ()]
    rebound_matrix = [list(row) for row in repaired_matrix]
    repairs: list[dict[str, Any]] = []
    for column_index in range(1, width):
        source_cells = [row[column_index] for row in original_matrix[1:]]
        source_tokens = _objective_column_numeric_tokens(
            original_matrix,
            column_index,
        )
        if len(source_tokens) != body_row_count * 2:
            continue
        if not any(
            len(tuple(_NUMBER_PATTERN.finditer(cell))) != 2
            for cell in source_cells
        ):
            continue
        uncertainty_cell_count = sum(
            1
            for cell in source_cells
            if re.search(r"(?:±|\+/-|\+-)", cell)
        )
        if uncertainty_cell_count < max(2, body_row_count // 2):
            continue
        repaired_cells = [row[column_index] for row in repaired_matrix[1:]]
        if not all(
            _objective_cell_is_mean_uncertainty_value(cell)
            for cell in repaired_cells
        ):
            continue

        for body_index, repaired_cell in enumerate(repaired_cells):
            expected_tokens = source_tokens[body_index * 2 : body_index * 2 + 2]
            actual_tokens = tuple(
                match.group(0) for match in _NUMBER_PATTERN.finditer(repaired_cell)
            )
            if actual_tokens == expected_tokens:
                continue
            rebound = f"{expected_tokens[0]} ( ± {expected_tokens[1]})"
            rebound_matrix[body_index + 1][column_index] = rebound
            repairs.append(
                {
                    "row_index": body_index + 1,
                    "column": (
                        headers[column_index]
                        if column_index < len(headers)
                        else str(column_index)
                    ),
                    "before": repaired_cell,
                    "after": rebound,
                    "reason": (
                        "Rebound a parser-split uncertainty using the complete "
                        "top-to-bottom numeric sequence of this result column."
                    ),
                }
            )
    return rebound_matrix, repairs


def _validated_objective_repaired_table_matrix(
    *,
    source: dict[str, Any],
    repaired_table_matrix: Any,
) -> list[list[str]]:
    if not isinstance(repaired_table_matrix, list) or not repaired_table_matrix:
        return []
    headers = [
        str(header).strip()
        for header in source.get("column_headers", ())
        if str(header).strip()
    ]
    expected_width = len(headers)
    repaired_rows: list[list[str]] = []
    for row in repaired_table_matrix:
        if not isinstance(row, (list, tuple)):
            return []
        repaired_row = [str(cell).strip() for cell in row]
        if expected_width and len(repaired_row) != expected_width:
            return []
        repaired_rows.append(repaired_row)
    if expected_width and not _objective_row_matches_headers(
        tuple(repaired_rows[0]),
        tuple(headers),
    ):
        repaired_rows.insert(0, headers)
    return repaired_rows


def _normalized_objective_table_matrix(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [
        [str(cell).strip() for cell in row]
        for row in value
        if isinstance(row, (list, tuple))
    ]


def _cleanup_objective_repaired_table_matrix_residual_fragments(
    *,
    original_matrix: list[list[str]],
    repaired_matrix: list[list[str]],
    column_headers: Any,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    if not original_matrix or not repaired_matrix:
        return repaired_matrix, []
    headers = [str(value).strip() for value in column_headers or ()]
    cleaned_matrix: list[list[str]] = []
    repairs: list[dict[str, Any]] = []
    for row_index, repaired_row in enumerate(repaired_matrix):
        original_row = (
            original_matrix[row_index] if row_index < len(original_matrix) else []
        )
        cleaned_row: list[str] = []
        for col_index, repaired_cell in enumerate(repaired_row):
            original_cell = (
                original_row[col_index] if col_index < len(original_row) else ""
            )
            cleaned_cell = _cleanup_objective_repaired_cell_residual_prefix(
                original_cell=original_cell,
                repaired_cell=repaired_cell,
            )
            cleaned_row.append(cleaned_cell)
            if cleaned_cell != repaired_cell:
                repairs.append(
                    {
                        "row_index": row_index,
                        "column": (
                            headers[col_index]
                            if col_index < len(headers)
                            else str(col_index)
                        ),
                        "before": repaired_cell,
                        "after": cleaned_cell,
                        "reason": (
                            "Removed a leading closing-fragment prefix that "
                            "belonged to the previous parser-split row label."
                        ),
                    }
                )
        cleaned_matrix.append(cleaned_row)
    return cleaned_matrix, repairs


def _cleanup_objective_repaired_cell_residual_prefix(
    *,
    original_cell: str,
    repaired_cell: str,
) -> str:
    original = " ".join(str(original_cell or "").split())
    repaired = " ".join(str(repaired_cell or "").split())
    if not original or not repaired:
        return repaired_cell
    if not _objective_cell_text_looks_structurally_fragmented(original):
        return repaired_cell
    match = re.match(r"^([^\s()[\]{}|]{1,32}\))\s+(.+)$", original)
    if match is None:
        return repaired_cell
    prefix = f"{match.group(1)} "
    original_remainder = match.group(2).strip()
    if not _objective_cell_text_looks_structurally_fragmented(original_remainder):
        return repaired_cell
    if not repaired.startswith(prefix):
        return repaired_cell
    candidate = repaired[len(prefix) :].strip()
    if not candidate:
        return repaired_cell
    if _objective_cell_text_looks_structurally_fragmented(candidate):
        return repaired_cell
    return candidate


def _objective_table_matrix_has_structural_fragments(
    table_matrix: list[list[str]],
) -> bool:
    return any(
        _objective_cell_text_looks_structurally_fragmented(cell)
        for row in table_matrix
        for cell in row
    )


def _objective_table_source_needs_llm_structural_repair(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
) -> bool:
    if route.source_kind != "table":
        return False
    if route.role not in {
        "current_experimental_evidence",
        "process_or_treatment",
        "condition_context",
    }:
        return False
    matrix = source.get("table_matrix")
    if isinstance(matrix, list) and _objective_table_matrix_has_structural_fragments(
        _normalized_objective_table_matrix(matrix)
    ):
        return True
    cells = source.get("table_cells")
    if not isinstance(cells, list):
        return False
    return any(
        _objective_cell_text_looks_structurally_fragmented(
            str(cell.get("cell_text") or "")
        )
        for cell in cells
        if isinstance(cell, dict)
    )


def _objective_cell_text_looks_structurally_fragmented(text: str) -> bool:
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if value.count("(") != value.count(")"):
        return True
    if value.count("[") != value.count("]"):
        return True
    if value.endswith(("/", "(", "[", "{")):
        return True
    if value.startswith((")", "]", "}")):
        return True
    return False


def _objective_merge_table_repair_records(
    *,
    deterministic_records: tuple[dict[str, Any], ...],
    llm_records: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return deterministic_records or llm_records


def _build_objective_method_family_test_condition_units(
    *,
    objectives: tuple[ResearchObjective, ...],
    objective_paper_frames: tuple[PaperAnalysisFrame, ...],
    objective_evidence_routes: tuple[EvidenceCandidate, ...],
    blocks_by_document_id: dict[str, list[Any]],
) -> tuple[ExtractedEvidenceDraft, ...]:
    context_by_objective_id = {context.objective_id: context for context in objectives}
    routed_document_keys = {
        (route.objective_id, route.document_id)
        for route in objective_evidence_routes
        if route.extractable and route.role != "low_value_or_irrelevant"
    }
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for frame in objective_paper_frames:
        if (
            frame.relevance == "irrelevant"
            or (frame.objective_id, frame.document_id) not in routed_document_keys
        ):
            continue
        objective_context = context_by_objective_id.get(frame.objective_id)
        families = property_matching.objective_method_families(objective_context)
        if not families:
            continue
        blocks = blocks_by_document_id.get(frame.document_id, [])
        for family in families:
            key = (frame.objective_id, frame.document_id, family)
            if key in seen:
                continue
            candidate = _objective_method_family_candidate(
                family=family,
                blocks=blocks,
            )
            if candidate is None:
                continue
            block, quote, payload = candidate
            seen.add(key)
            source_ref = str(getattr(block, "block_id", "") or "")
            source_ref_payload = {
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "test_condition",
                "page": getattr(block, "page", None),
            }
            records.append(
                {
                    "evidence_id": _objective_method_family_unit_id(
                        objective_id=frame.objective_id,
                        document_id=frame.document_id,
                        family=family,
                    ),
                    "objective_id": frame.objective_id,
                    "document_id": frame.document_id,
                    "evidence_role": "condition_context",
                    "selection_reason": quote,
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "scientific_context": {
                        "material": [],
                        "sample": [],
                        "process": [],
                        "test": [
                            {"name": "method_family", "value": family},
                            *(
                                {"name": key, "value": value}
                                for key, value in payload.items()
                            ),
                        ],
                    },
                    "source_refs": (
                        {
                            key: value
                            for key, value in source_ref_payload.items()
                            if value not in (None, "", [], {})
                        },
                    ),
                    "resolution_status": "resolved",
                    "confidence": 0.86,
                }
            )
    return tuple(ExtractedEvidenceDraft.from_mapping(record) for record in records)


def _objective_method_family_candidate(
    *,
    family: str,
    blocks: list[Any],
) -> tuple[Any, str, dict[str, Any]] | None:
    best: tuple[int, int, Any, str, dict[str, Any]] | None = None
    for position, block in enumerate(blocks):
        text = str(getattr(block, "text", "") or "").strip()
        if not text:
            continue
        combined_text = " ".join(
            part
            for part in (
                str(getattr(block, "heading_path", "") or "").strip(),
                text,
            )
            if part
        )
        score = _score_objective_method_family_window(
            family=family,
            text=combined_text,
        )
        if score <= 0:
            continue
        quote = _select_objective_method_family_quote(
            text,
            family=family,
        )
        if not quote:
            continue
        payload = _build_objective_method_family_condition_payload(
            family=family,
            text=text,
        )
        if not payload:
            continue
        candidate = (score, -position, block, quote, payload)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    _, _, block, quote, payload = best
    return block, quote, payload


def _score_objective_method_family_window(
    *,
    family: str,
    text: str,
) -> int:
    lowered = text.casefold()
    if family == "tensile_mechanics":
        terms = (
            ("tensile", 4),
            ("stress-strain", 3),
            ("yield strength", 2),
            ("ultimate tensile", 2),
            ("astm e8", 4),
            ("instron", 4),
            ("strain rate", 2),
        )
    elif family == "microhardness":
        terms = (
            ("microhardness", 4),
            ("vickers", 4),
            ("hardness", 2),
            ("wilson", 3),
            ("holding time", 2),
            ("readings", 2),
        )
    elif family == "density_porosity_microstructure":
        terms = (
            ("sem", 3),
            ("imagej", 4),
            ("porosity", 3),
            ("relative density", 3),
            ("microstructure", 2),
            ("magnification", 2),
            ("horizontal", 1),
            ("vertical", 1),
        )
    else:
        return 0
    return sum(weight for term, weight in terms if term in lowered)


def _build_objective_method_family_condition_payload(
    *,
    family: str,
    text: str,
) -> dict[str, Any]:
    if family == "tensile_mechanics":
        payload: dict[str, Any] = {
            "method": "tensile testing",
            "methods": ["tensile testing"],
            "test_method": "tensile testing",
            "standard": _extract_first_pattern(
                text,
                r"\bASTM\s*E8M?\b",
            ),
            "instrument": _extract_first_pattern(
                text,
                r"\bINSTRON\b[^.;,\n]*",
            ),
            "strain_rate_s-1": _extract_first_pattern(
                text,
                r"\b\d+(?:\.\d+)?\s*mm\s*/\s*min\b",
            ),
            "specimen_geometry": (
                "Fig. 2" if re.search(r"\bFig\.\s*2\b", text, re.IGNORECASE) else None
            ),
            "sample_orientation": _extract_orientation_phrase(text),
            "details": _compact_condition_details(text),
        }
    elif family == "microhardness":
        payload = {
            "method": "Vickers microhardness",
            "methods": ["Vickers microhardness"],
            "test_method": "Vickers microhardness",
            "instrument": _extract_first_pattern(
                text,
                r"\b(?:Vickers\s+)?microhardness[^.;\n]*",
            ),
            "load": _extract_first_pattern(text, r"\b\d+(?:\.\d+)?\s*N\b"),
            "holding_time": _extract_first_pattern(
                text,
                r"\b\d+(?:\.\d+)?\s*s\b",
            ),
            "readings_per_sample": _extract_first_pattern(
                text,
                r"\b\d+\s+(?:readings|measurements)\b[^.;\n]*",
            ),
            "sample_orientation": _extract_orientation_phrase(text),
            "details": _compact_condition_details(text),
        }
    else:
        payload = {
            "method": "SEM / ImageJ",
            "methods": _dedupe_preserving_order(
                [
                    method
                    for method in ("SEM", "ImageJ")
                    if method.casefold() in text.casefold()
                ]
            )
            or ["SEM / ImageJ"],
            "test_method": "SEM / ImageJ",
            "instrument": _extract_first_pattern(
                text,
                r"\bFEI[-\s]INSPECT\s*50\s*SEM\b",
            )
            or ("SEM" if re.search(r"\bSEM\b", text, re.IGNORECASE) else None),
            "section_orientation": _extract_section_orientation_phrase(text),
            "surface_state": _extract_surface_preparation_phrase(text),
            "magnification": _extract_first_pattern(
                text,
                r"\b\d+(?:\.\d+)?\s*[xX]\s*(?:-|to)\s*\d+(?:\.\d+)?\s*[xX]\b",
            ),
            "details": _compact_condition_details(text),
        }
    return {
        key: value for key, value in payload.items() if value not in (None, "", [], {})
    }


def _select_objective_method_family_quote(
    text: str,
    *,
    family: str,
) -> str | None:
    terms = {
        "tensile_mechanics": ("tensile", "astm", "instron", "stress-strain"),
        "microhardness": ("microhardness", "vickers", "hardness", "wilson"),
        "density_porosity_microstructure": (
            "sem",
            "imagej",
            "porosity",
            "relative density",
            "microstructure",
        ),
    }.get(family, ())
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", normalized_text):
        if any(term in sentence.casefold() for term in terms):
            return sentence[:900].strip()
    return normalized_text[:900].strip()


def _extract_first_pattern(
    text: str,
    pattern: str,
) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip()


def _extract_orientation_phrase(text: str) -> str | None:
    lowered = text.casefold()
    if "horizontally" in lowered and "substrate" in lowered:
        return "all blocks built horizontally on substrate"
    if "horizontal" in lowered and "vertical" in lowered:
        return "horizontal and vertical sections"
    if "horizontal" in lowered:
        return "horizontal"
    if "vertical" in lowered:
        return "vertical"
    return None


def _extract_section_orientation_phrase(text: str) -> str | None:
    lowered = text.casefold()
    if "horizontal" in lowered and "vertical" in lowered:
        return "horizontal and vertical sections"
    return _extract_orientation_phrase(text)


def _extract_surface_preparation_phrase(text: str) -> str | None:
    parts = []
    grit = _extract_first_pattern(
        text,
        r"\b\d+\s*[-]\s*\d+\s*grit\b",
    )
    if grit:
        parts.append(grit)
    silica = _extract_first_pattern(
        text,
        r"\bcolloidal\s+silica\b[^.;\n]*",
    )
    if silica:
        parts.append(silica)
    return "; ".join(parts) if parts else None


def _compact_condition_details(text: str) -> str | None:
    normalized = " ".join(str(text or "").split())
    return normalized[:1000].strip() or None


def _objective_method_family_unit_id(
    *,
    objective_id: str,
    document_id: str,
    family: str,
) -> str:
    seed = "|".join(("method_family", objective_id, document_id, family))
    return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def _objective_numeric_match_tokens(value: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _NUMBER_PATTERN.finditer(str(value or "").replace(",", "")):
        number_text = match.group(0)
        number = _coerce_number(number_text)
        if number is None:
            continue
        if number.is_integer():
            tokens.append(str(int(number)))
        else:
            tokens.append(("%f" % number).rstrip("0").rstrip("."))
    return tuple(tokens)


def _build_objective_route_source_payload(
    *,
    route: EvidenceCandidate,
    blocks: list[Any],
    tables: list[Any],
    figures: list[Any] | None = None,
    document_tree: SourceDocumentTree | None = None,
    table_cells: list[Any] | None = None,
) -> dict[str, Any]:
    if route.source_kind == "table":
        table = next(
            (
                candidate
                for candidate in tables
                if str(getattr(candidate, "table_id", "") or "") == route.source_ref
            ),
            None,
        )
        if table is None:
            return {}
        header_row_count = int(getattr(table, "header_row_count", 1) or 0)
        table_matrix = [
            [str(cell) for cell in row]
            for row in getattr(table, "table_matrix", ()) or ()
            if isinstance(row, (list, tuple))
        ]
        column_headers = [
            str(value) for value in getattr(table, "column_headers", ()) or ()
        ]
        table_metadata = getattr(table, "metadata", {}) or {}
        table_visual_text = (
            str(table_metadata.get("visual_text") or "").strip()
            if isinstance(table_metadata, Mapping)
            else ""
        )
        cells = tuple(
            cell
            for cell in table_cells or []
            if str(getattr(cell, "table_id", "") or "") == route.source_ref
        )
        return {
            "source_kind": "table",
            "source_ref": route.source_ref,
            "document_id": route.document_id,
            "page": getattr(table, "page", None),
            "caption_text": _objective_table_caption_text(
                table=table,
                blocks=blocks,
            ),
            "heading_path": getattr(table, "heading_path", None),
            "column_headers": column_headers,
            "header_row_count": header_row_count,
            "table_matrix": table_matrix,
            "table_markdown": render_markdown_table(
                table_matrix,
                column_headers,
                header_row_count=header_row_count,
            ),
            "table_visual_text": table_visual_text or None,
            "table_cells": [
                {
                    "row_index": getattr(cell, "row_index", None),
                    "col_index": getattr(cell, "col_index", None),
                    "header_path": getattr(cell, "header_path", None),
                    "cell_text": str(getattr(cell, "cell_text", "") or ""),
                }
                for cell in sorted(
                    cells,
                    key=lambda item: (
                        getattr(item, "row_index", 0),
                        getattr(item, "col_index", 0),
                    ),
                )
            ],
        }
    if route.source_kind == "text_window":
        source_block_id = _route_text_block_id(
            route=route,
            document_tree=document_tree,
        )
        block = next(
            (
                candidate
                for candidate in blocks
                if str(getattr(candidate, "block_id", "") or "") == source_block_id
            ),
            None,
        )
        if block is None:
            return _build_objective_tree_text_source_payload(
                route=route,
                document_tree=document_tree,
            )
        text = str(getattr(block, "text", "") or "").strip()
        return {
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "document_id": route.document_id,
            "page": getattr(block, "page", None),
            "block_type": getattr(block, "block_type", None),
            "heading_path": getattr(block, "heading_path", None),
            "text": text[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
        }
    if route.source_kind == "figure":
        figure = next(
            (
                candidate
                for candidate in figures or []
                if str(getattr(candidate, "figure_id", "") or "") == route.source_ref
            ),
            None,
        )
        if figure is None:
            return {}
        caption = str(getattr(figure, "caption_text", "") or "").strip()
        return {
            "source_kind": "figure",
            "source_ref": route.source_ref,
            "document_id": route.document_id,
            "page": getattr(figure, "page", None),
            "caption_text": caption[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
            "heading_path": getattr(figure, "heading_path", None),
            "text": caption[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
        }
    return {}


def _objective_table_caption_text(*, table: Any, blocks: list[Any]) -> str | None:
    caption = str(getattr(table, "caption_text", "") or "").strip()
    if not re.fullmatch(r"table\s+[A-Za-z0-9.\-]+", caption, flags=re.IGNORECASE):
        return caption or None

    caption_block_id = str(getattr(table, "caption_block_id", "") or "").strip()
    if not caption_block_id:
        return caption
    caption_block = next(
        (
            block
            for block in blocks
            if str(getattr(block, "block_id", "") or "") == caption_block_id
        ),
        None,
    )
    if caption_block is None:
        return caption

    document_id = str(getattr(table, "document_id", "") or "")
    caption_order = int(getattr(caption_block, "block_order", 0) or 0)
    following = sorted(
        (
            block
            for block in blocks
            if str(getattr(block, "document_id", "") or "") == document_id
            and int(getattr(block, "block_order", 0) or 0) > caption_order
        ),
        key=lambda block: int(getattr(block, "block_order", 0) or 0),
    )
    if not following:
        return caption
    description = following[0]
    if (
        int(getattr(description, "block_order", 0) or 0) != caption_order + 1
        or str(getattr(description, "block_type", "") or "").casefold()
        != "paragraph"
        or getattr(description, "page", None) != getattr(table, "page", None)
    ):
        return caption
    description_text = str(getattr(description, "text", "") or "").strip()
    return f"{caption}. {description_text}" if description_text else caption


def _route_text_block_id(
    *,
    route: EvidenceCandidate,
    document_tree: SourceDocumentTree | None,
) -> str:
    if document_tree is None:
        return route.source_ref
    node = _tree_node_for_route_source(
        document_tree=document_tree,
        source_ref_kind="block",
        source_ref_id=route.source_ref,
    )
    if node is None:
        return route.source_ref
    source_ref_id = str(getattr(node, "source_ref_id", "") or "").strip()
    return source_ref_id or route.source_ref


def _build_objective_tree_text_source_payload(
    *,
    route: EvidenceCandidate,
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    if document_tree is None:
        return {}
    node = _tree_node_for_route_source(
        document_tree=document_tree,
        source_ref_kind="block",
        source_ref_id=route.source_ref,
    )
    if node is None or _tree_node_in_reference_branch(document_tree, node):
        return {}
    text = str(getattr(node, "text", "") or "").strip()
    if node.node_type == "section" and not text:
        section_parts: list[str] = []
        for child_id in node.child_ids:
            child = document_tree.nodes.get(child_id)
            if child is None or child.node_type not in {"paragraph", "list_item"}:
                continue
            child_text = str(getattr(child, "text", "") or "").strip()
            if child_text:
                section_parts.append(child_text)
        text = "\n\n".join(section_parts).strip()
        if not text:
            text = str(getattr(node, "title", "") or "").strip()
    if not text:
        return {}
    section_path = _tree_node_section_path(
        document_tree=document_tree,
        node=node,
    )
    return {
        "source_kind": "text_window",
        "source_ref": route.source_ref,
        "document_id": route.document_id,
        "page": getattr(node, "page_start", None),
        "block_type": (
            "section" if node.node_type == "section" else _route_text_node_block_type(node)
        ),
        "heading_path": " > ".join(section_path) if section_path else None,
        "text": text[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
    }


def _objective_table_matrix_evidence_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
) -> tuple[dict[str, Any], ...]:
    if route.source_kind != "table":
        return ()
    headers, data_rows = _objective_table_matrix_rows(source)
    if not headers or not data_rows:
        return ()
    if route.role == "current_experimental_evidence":
        # A result table is also a condition table.  Keeping only the target
        # column loses co-varied factors before the same-paper comparison pass
        # can determine whether an effect is isolated or joint.  Emit the
        # source-local condition rows alongside the measured result rows; the
        # stable row/source locators let reconstruction merge them without
        # inventing values.
        process_records = _objective_process_table_matrix_records(
            route=route,
            source=source,
            objective_context=objective_context,
            headers=headers,
            data_rows=data_rows,
        )
        result_records = _objective_result_table_matrix_records(
            route=route,
            source=source,
            objective_context=objective_context,
            headers=headers,
            data_rows=data_rows,
        )
        return (*process_records, *result_records)
    if route.role in {"process_or_treatment", "condition_context"}:
        multilevel_records = _objective_multilevel_process_table_records(
            route=route,
            source=source,
            objective_context=objective_context,
        )
        if multilevel_records is not None:
            return multilevel_records
        process_records = _objective_process_table_matrix_records(
            route=route,
            source=source,
            objective_context=objective_context,
            headers=headers,
            data_rows=data_rows,
        )
        recover_result_columns = bool(
            _objective_route_result_columns(
                route,
                objective_context=objective_context,
            )
            or (objective_context is not None and objective_context.outcomes)
        )
        result_records = (
            _objective_result_table_matrix_records(
                route=route,
                source=source,
                objective_context=objective_context,
                headers=headers,
                data_rows=data_rows,
            )
            if recover_result_columns
            else ()
        )
        return (*process_records, *result_records)
    return ()


def _objective_multilevel_process_table_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
) -> tuple[dict[str, Any], ...] | None:
    headers = tuple(str(value).strip() for value in source.get("column_headers", ()))
    matrix = tuple(
        tuple(str(cell).strip() for cell in row)
        for row in source.get("table_matrix", ())
        if isinstance(row, (list, tuple))
    )
    if not headers or len(matrix) < 3 or len(set(headers)) == len(headers):
        return None

    first_data_position = 1 if _objective_row_matches_headers(matrix[0], headers) else 0
    if first_data_position >= len(matrix):
        return None
    leaf_headers = matrix[first_data_position]
    columns = _objective_condition_table_columns(
        route=route,
        caption=str(source.get("caption_text") or ""),
        parent_headers=headers,
        leaf_headers=leaf_headers,
    )
    label_columns = [
        index for index, column in columns.items() if column[0] == "condition"
    ]
    process_columns = {
        index: column for index, column in columns.items() if column[0] == "process"
    }
    if len(label_columns) != 1 or not process_columns:
        return None

    label_index = label_columns[0]
    records: list[dict[str, Any]] = []
    for row_index, row in enumerate(
        matrix[first_data_position + 1 :],
        start=first_data_position + 1,
    ):
        label = str(row[label_index] if label_index < len(row) else "").strip()
        if not label or label == "-":
            continue
        process = [
            {"name": name, "value": value, "unit": unit}
            for index, (_kind, name, unit) in process_columns.items()
            if index < len(row)
            and (value := str(row[index]).strip())
            and value != "-"
        ]
        if not process:
            continue
        context = _objective_table_source_scope_attributes(
            source=source,
            objective_context=objective_context,
        )
        records.append(
            {
                "evidence_id": _objective_matrix_unit_id(
                    route=route,
                    row_index=row_index,
                    column="scientific_context",
                ),
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [
                        {"name": name, "value": value}
                        for name, value in context["material"].items()
                    ],
                    "sample": [
                        {"name": "condition", "value": label},
                        *(
                            {"name": name, "value": value}
                            for name, value in context["sample"].items()
                        ),
                    ],
                    "process": [
                        *process,
                        *(
                            {"name": name, "value": value}
                            for name, value in context["process"].items()
                        ),
                    ],
                    "test": [],
                },
                "source_refs": _objective_route_source_refs(
                    route=route,
                    source=source,
                    row_index=row_index,
                    source_excerpt=" | ".join(
                        f"{headers[index]} > {leaf_headers[index]}: {row[index]}"
                        for index in range(
                            min(len(headers), len(leaf_headers), len(row))
                        )
                        if str(row[index]).strip()
                    ),
                ),
                "resolution_status": "resolved",
                "confidence": route.confidence,
            }
        )
    return tuple(records)


def _objective_condition_table_columns(
    *,
    route: EvidenceCandidate,
    caption: str,
    parent_headers: tuple[str, ...],
    leaf_headers: tuple[str, ...],
) -> dict[int, tuple[str, str, str | None]]:
    rate_unit = _objective_condition_rate_unit(caption)
    columns: dict[int, tuple[str, str, str | None]] = {}
    active_stage: str | None = None
    for index, parent in enumerate(parent_headers):
        if index >= len(leaf_headers):
            continue
        leaf = leaf_headers[index]
        parent_key = _objective_column_key(parent)
        leaf_key = _objective_column_key(leaf)
        role = str(route.column_roles.get(parent) or "").casefold()
        if (
            "sample" in role
            or "condition" in role
            or parent_key in {"condition", "nomenclature", "sample", "specimen"}
        ):
            columns[index] = ("condition", "condition", None)
            continue

        property_name, unit = _split_property_unit(leaf)
        parent_stage = property_matching.normalize_property_label(parent) or parent_key
        if leaf_key in {"up", "heating_rate"} or leaf == "↑":
            active_stage = parent_stage
        stage = active_stage or parent_stage
        is_heat_treatment = stage == "heat treatment"
        if property_name == "T":
            columns[index] = (
                "process",
                (
                    "heat treatment temperature"
                    if is_heat_treatment
                    else f"{stage} temperature"
                ),
                _objective_condition_unit(unit),
            )
        elif property_name == "P":
            columns[index] = (
                "process",
                "heat treatment pressure" if is_heat_treatment else f"{stage} pressure",
                _objective_condition_unit(unit),
            )
        elif property_name == "t":
            columns[index] = (
                "process",
                "heat treatment duration" if is_heat_treatment else f"{stage} duration",
                _objective_condition_unit(unit),
            )
        elif (leaf_key in {"up", "heating_rate"} or leaf == "↑") and (
            rate_unit is not None
        ):
            columns[index] = (
                "process",
                "heating rate" if is_heat_treatment else f"{stage} heating rate",
                rate_unit,
            )
        elif (leaf_key in {"down", "cooling_rate"} or leaf == "↓") and (
            rate_unit is not None
        ):
            columns[index] = (
                "process",
                "cooling rate" if is_heat_treatment else f"{stage} cooling rate",
                rate_unit,
            )
    return columns


def _objective_condition_rate_unit(caption: str) -> str | None:
    if not re.search(r"heating\s*/?\s*cooling\s+rates?", caption, re.IGNORECASE):
        return None
    match = re.search(
        r"(?:are\s+)?in\s+([°º]?[A-Za-z]+\s*/\s*(?:min|s|h|hr))",
        caption,
        re.IGNORECASE,
    )
    return _objective_condition_unit(match.group(1)) if match else None


def _objective_condition_unit(value: str | None) -> str | None:
    unit = re.sub(r"\s+", "", str(value or "")).replace("°", "").replace("º", "")
    return unit or None


def _objective_result_table_matrix_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
    headers: tuple[str, ...],
    data_rows: tuple[tuple[int, tuple[str, ...]], ...],
) -> tuple[dict[str, Any], ...]:
    result_columns = _objective_route_result_columns(
        route,
        objective_context=objective_context,
    )
    if objective_context is not None:
        result_columns.update(
            header
            for header in headers
            if not _objective_value_column_is_non_result(header)
            and _objective_result_column_matches_source_target(
                header,
                source=source,
                objective_context=objective_context,
            )
        )
    if not result_columns:
        return ()

    records: list[dict[str, Any]] = []
    for row_index, row in data_rows:
        row_values = _objective_table_row_values(headers=headers, row=row)
        row_attributes = _objective_table_row_attributes(
            route=route,
            source=source,
            row_values=row_values,
            result_columns=result_columns,
            objective_context=objective_context,
        )
        if _objective_result_table_row_is_reference_context(
            route=route,
            row_values=row_values,
            result_columns=result_columns,
        ):
            continue
        row_attributes = _objective_table_row_attributes_with_sample_number(
            row_attributes=row_attributes,
            row_index=row_index,
        )
        for result_column in result_columns:
            raw_value = row_values.get(result_column)
            if raw_value in (None, ""):
                continue
            property_source = _objective_result_column_property_label(
                route=route,
                source=source,
                result_column=result_column,
                objective_context=objective_context,
            )
            _column_property, unit = _split_property_unit(result_column)
            outcome = (
                property_matching.normalize_objective_result_property(
                    property_source,
                    objective_context=objective_context,
                )
                or property_source
            )
            numeric_value = _coerce_result_cell_number(raw_value)
            result_value = (
                numeric_value if numeric_value is not None else str(raw_value).strip()
            )
            records.append(
                {
                    "evidence_id": _objective_matrix_unit_id(
                        route=route,
                        row_index=row_index,
                        column=result_column,
                    ),
                    "objective_id": route.objective_id,
                    "document_id": route.document_id,
                    "evidence_role": "direct_result",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": {
                        "outcome": outcome,
                        "value": result_value,
                        "unit": unit,
                        "direction": "unknown",
                        "result_kind": _objective_result_kind_from_column(
                            result_column
                        ),
                        "result_text": (
                            f"{outcome} = {raw_value}" + (f" {unit}" if unit else "")
                        ),
                    },
                    "attribution_scope": "descriptive_only",
                    "scientific_context": {
                        "material": [
                            item
                            for item in _objective_table_context_attribute_records(
                                attributes=row_attributes["material"],
                                section="material",
                                route=route,
                                source=source,
                                objective_context=objective_context,
                            )
                        ],
                        "sample": [
                            item
                            for item in _objective_table_context_attribute_records(
                                attributes=row_attributes["sample"],
                                section="sample",
                                route=route,
                                source=source,
                                objective_context=objective_context,
                            )
                        ],
                        "process": [
                            item
                            for item in _objective_table_context_attribute_records(
                                attributes=row_attributes["process"],
                                section="process",
                                route=route,
                                source=source,
                                objective_context=objective_context,
                            )
                        ],
                        "test": [
                            item
                            for item in _objective_table_context_attribute_records(
                                attributes=row_attributes["test"],
                                section="test",
                                route=route,
                                source=source,
                                objective_context=objective_context,
                            )
                        ],
                    },
                    "source_refs": _objective_route_source_refs(
                        route=route,
                        source=source,
                        row_index=row_index,
                        col_index=headers.index(result_column),
                        header_path=result_column,
                        source_excerpt=" | ".join(
                            f"{header}: {row_values[header]}"
                            for header in headers
                            if header in row_values
                        ),
                    ),
                    "resolution_status": "resolved",
                    "confidence": route.confidence,
                }
            )
    return tuple(records)


def _objective_process_table_matrix_records(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    objective_context: ResearchObjective | None,
    headers: tuple[str, ...],
    data_rows: tuple[tuple[int, tuple[str, ...]], ...],
) -> tuple[dict[str, Any], ...]:
    result_columns = _objective_route_result_columns(
        route,
        objective_context=objective_context,
    )
    if objective_context is not None:
        result_columns.update(
            header
            for header in headers
            if not _objective_value_column_is_non_result(header)
            and _objective_result_column_matches_source_target(
                header,
                source=source,
                objective_context=objective_context,
            )
        )
    records: list[dict[str, Any]] = []
    for row_index, row in data_rows:
        row_values = _objective_table_row_values(headers=headers, row=row)
        row_attributes = _objective_table_row_attributes(
            route=route,
            source=source,
            row_values=row_values,
            result_columns=result_columns,
            objective_context=objective_context,
        )
        row_attributes = _objective_table_row_attributes_with_sample_number(
            row_attributes=row_attributes,
            row_index=row_index,
        )
        if (
            not row_attributes["material"]
            and not row_attributes["process"]
            and not row_attributes["test"]
        ):
            continue
        records.append(
            {
                "evidence_id": _objective_matrix_unit_id(
                    route=route,
                    row_index=row_index,
                    column="scientific_context",
                ),
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "evidence_role": "condition_context",
                "changed_variables": [],
                "comparison": None,
                "reported_result": None,
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [
                        item
                        for item in _objective_table_context_attribute_records(
                            attributes=row_attributes["material"],
                            section="material",
                            route=route,
                            source=source,
                            objective_context=objective_context,
                        )
                    ],
                    "sample": [
                        item
                        for item in _objective_table_context_attribute_records(
                            attributes=row_attributes["sample"],
                            section="sample",
                            route=route,
                            source=source,
                            objective_context=objective_context,
                        )
                    ],
                    "process": [
                        item
                        for item in _objective_table_context_attribute_records(
                            attributes=row_attributes["process"],
                            section="process",
                            route=route,
                            source=source,
                            objective_context=objective_context,
                        )
                    ],
                    "test": [
                        item
                        for item in _objective_table_context_attribute_records(
                            attributes=row_attributes["test"],
                            section="test",
                            route=route,
                            source=source,
                            objective_context=objective_context,
                        )
                    ],
                },
                "source_refs": _objective_route_source_refs(
                    route=route,
                    source=source,
                    row_index=row_index,
                    source_excerpt=" | ".join(
                        f"{header}: {row_values[header]}"
                        for header in headers
                        if header in row_values
                    ),
                ),
                "resolution_status": "resolved",
                "confidence": route.confidence,
            }
        )
    return tuple(records)




def _objective_table_row_attributes(
    *,
    route: EvidenceCandidate,
    source: Mapping[str, Any],
    row_values: dict[str, str],
    result_columns: set[str],
    objective_context: ResearchObjective | None,
) -> dict[str, dict[str, str]]:
    material_attributes: dict[str, str] = {}
    sample_attributes: dict[str, str] = {}
    process_attributes: dict[str, str] = {}
    test_attributes: dict[str, str] = {}
    for column, value in row_values.items():
        role = str(route.column_roles.get(column) or "").lower()
        column_key = _objective_column_key(column)
        process_attribute_label = _objective_process_attribute_label(
            column=column,
            role=role,
            objective_context=objective_context,
        )
        is_objective_condition_axis = bool(
            objective_context is not None
            and column_key == "condition"
            and process_attribute_label != column
        )
        is_source_symbol_axis = bool(
            property_matching.process_column_axis_keys(column)
        )
        is_objective_symbol_axis = bool(
            objective_context is not None
            and column not in result_columns
            and not _objective_value_column_is_non_result(column)
            and property_matching.process_column_axis_keys(column)
            and _objective_label_matches_variables(
                column,
                objective_context=objective_context,
            )
        )
        compound_label_attributes = _objective_caption_compound_label_attributes(
            column=column,
            value=value,
            role=role,
            caption=str(source.get("caption_text") or ""),
            objective_context=objective_context,
        )
        if compound_label_attributes is not None:
            for context_name, attributes in compound_label_attributes.items():
                {
                    "material": material_attributes,
                    "sample": sample_attributes,
                    "process": process_attributes,
                }[context_name].update(attributes)
        elif is_source_symbol_axis or is_objective_symbol_axis or is_objective_condition_axis:
            process_attributes[process_attribute_label] = value
        elif any(
            term in role for term in ("material", "alloy", "composition")
        ) or column_key in {
            "material",
            "material_system",
            "alloy",
            "alloy_name",
            "alloy_type",
            "composition",
        }:
            material_attributes[column] = value
        elif "sample" in role or _objective_table_column_is_sample_key(column_key):
            sample_attributes[column] = value
        elif column in result_columns or _objective_value_column_is_non_result(column):
            continue
        elif _objective_table_column_is_process_attribute(
            route=route,
            column=column,
            role=role,
            objective_context=objective_context,
        ):
            process_attributes[
                _objective_process_attribute_label(
                    column=column,
                    role=role,
                    objective_context=objective_context,
                )
            ] = value
        elif (
            "test" in role
            or "condition" in role
            or column_key in {"test", "test_no", "test_number"}
        ):
            if route.role == "current_experimental_evidence":
                sample_attributes[column] = value
            test_attributes[column] = value
    source_scope = _objective_table_source_scope_attributes(
        source=source,
        objective_context=objective_context,
    )
    for key, value in source_scope["material"].items():
        material_attributes.setdefault(key, value)
    for key, value in source_scope["sample"].items():
        sample_attributes.setdefault(key, value)
    for key, value in source_scope["process"].items():
        process_attributes.setdefault(key, value)
    return {
        "material": material_attributes,
        "sample": sample_attributes,
        "process": process_attributes,
        "test": test_attributes,
    }


def _objective_table_context_attribute_records(
    *,
    attributes: Mapping[str, Any],
    section: str,
    route: EvidenceCandidate,
    source: Mapping[str, Any],
    objective_context: ResearchObjective | None,
) -> list[dict[str, Any]]:
    """Attach source column units while keeping row values source-local."""

    units_by_key: dict[str, str] = {}
    for header in source.get("column_headers", ()):
        header_text = str(header or "").strip()
        if not header_text:
            continue
        _property_name, unit = _split_property_unit(header_text)
        if not unit:
            continue
        labels = {header_text, _property_name}
        if section == "process":
            labels.add(
                _objective_process_attribute_label(
                    column=header_text,
                    role=str(route.column_roles.get(header_text) or ""),
                    objective_context=objective_context,
                )
            )
        for label in labels:
            key = property_matching.normalize_property_label(label) or property_matching.axis_key(label)
            if key:
                units_by_key.setdefault(key, unit)

    records: list[dict[str, Any]] = []
    for name, value in attributes.items():
        record: dict[str, Any] = {"name": name, "value": value}
        key = property_matching.normalize_property_label(name) or property_matching.axis_key(name)
        unit = units_by_key.get(key)
        if unit:
            record["unit"] = unit
        records.append(record)
    return records


def _objective_table_source_scope_attributes(
    *,
    source: Mapping[str, Any],
    objective_context: ResearchObjective | None,
) -> dict[str, dict[str, str]]:
    source_context = " ".join(
        str(source.get(key) or "").strip()
        for key in ("caption_text", "heading_path")
        if str(source.get(key) or "").strip()
    )
    if not source_context:
        return {"material": {}, "sample": {}, "process": {}}

    material: dict[str, str] = {}
    if objective_context is not None:
        material_matches = tuple(
            value
            for value in objective_context.material_scope
            if property_matching.source_text_mentions_axis(source_context, value)
        )
        if len(material_matches) == 1:
            material["material"] = material_matches[0]

    orientations = tuple(
        value
        for value in ("horizontal", "longitudinal", "transverse", "vertical")
        if re.search(rf"\b{value}\b", source_context, flags=re.IGNORECASE)
    )
    sample = (
        {"build orientation": orientations[0]}
        if len(orientations) == 1
        else {}
    )
    process = (
        {"manufacturing process": "laser powder bed fusion"}
        if re.search(
            r"\b(?:laser\s+powder[-\s]bed\s+fusion|selective\s+laser\s+melting|LPBF|PBF-L|SLM)\b",
            source_context,
            flags=re.IGNORECASE,
        )
        else {}
    )
    return {"material": material, "sample": sample, "process": process}


def _objective_caption_compound_label_attributes(
    *,
    column: str,
    value: str,
    role: str,
    caption: str,
    objective_context: ResearchObjective | None,
) -> dict[str, dict[str, str]] | None:
    if objective_context is None or not caption.strip():
        return None
    column_key = _objective_column_key(column)
    is_material_or_sample_label = (
        any(term in role for term in ("material", "alloy", "sample", "label"))
        or column_key in {
            "alloy",
            "alloy_name",
            "alloy_type",
            "material",
            "material_system",
            "sample",
            "sample_label",
        }
    )
    condition_axes = tuple(
        axis
        for axis in objective_context.variables
        if _objective_column_key(axis).endswith("_condition")
    )
    label_parts = tuple(part.strip() for part in value.split("-") if part.strip())
    if (
        not is_material_or_sample_label
        or len(condition_axes) != 1
        or len(label_parts) < 2
        or any(not re.fullmatch(r"[A-Z]{1,8}", part) for part in label_parts)
    ):
        return None

    definitions = {
        abbreviation.upper(): term
        for term, abbreviation in re.findall(
            r"\b([A-Za-z]+(?:-[A-Za-z]+)*)\s*\(([A-Z]{1,8})\)",
            caption,
        )
    }
    expanded_parts: list[tuple[str, str]] = []
    for part in label_parts:
        expansion = definitions.get(part)
        if expansion is None:
            if re.search(rf"\b{re.escape(part)}\b", caption) is None:
                return None
            expansion = part
        expanded_parts.append((part, expansion))

    orientation_parts = tuple(
        expansion.casefold()
        for _part, expansion in expanded_parts
        if expansion.casefold()
        in {"horizontal", "longitudinal", "transverse", "vertical"}
    )
    process_parts = tuple(
        expansion if expansion.isupper() else expansion.casefold()
        for _part, expansion in expanded_parts
        if expansion.casefold() not in orientation_parts
    )
    if len(orientation_parts) != 1 or not process_parts:
        return None

    material_matches = tuple(
        material
        for material in objective_context.material_scope
        if property_matching.source_text_mentions_axis(caption, material)
    )
    material_attributes = (
        {"material": material_matches[0]}
        if len(material_matches) == 1
        else {}
    )
    return {
        "material": material_attributes,
        "sample": {"build orientation": orientation_parts[0]},
        "process": {condition_axes[0]: " + ".join(process_parts)},
    }


def _objective_process_attribute_label(
    *,
    column: str,
    role: str,
    objective_context: ResearchObjective | None,
) -> str:
    if objective_context is not None:
        condition_axes = tuple(
            axis
            for axis in objective_context.variables
            if _objective_column_key(column) == "condition"
            and _objective_column_key(axis).endswith("_condition")
        )
        if len(condition_axes) == 1:
            return condition_axes[0]
        symbol_axes = property_matching.process_column_axis_keys(column)
        # Some source abbreviations intentionally map to several possible
        # process names (for example ``VED`` can mean volumetric energy
        # density or the broader energy-density family).  Resolve that
        # ambiguity against the confirmed Objective when exactly one axis is
        # supported.  Otherwise retain the specific source-symbol mapping so
        # jointly varied factors remain distinct for comparison.
        matching_objective_axes = tuple(
            axis
            for axis in objective_context.variables
            if any(
                property_matching.process_axis_matches_objective_scope(
                    symbol_axis,
                    axis,
                )
                for symbol_axis in symbol_axes
            )
        )
        if len(matching_objective_axes) == 1 and len(symbol_axes) > 1:
            return matching_objective_axes[0]
        if len(symbol_axes) == 1:
            return next(iter(symbol_axes))
    role_label = property_matching.normalize_property_label(role)
    if (
        role_label
        and property_matching.process_role_is_specific(role_label)
        and (
            objective_context is None
            or _objective_label_matches_variables(
                role_label,
                objective_context=objective_context,
            )
        )
    ):
        return role_label
    return column


def _objective_table_column_is_process_attribute(
    *,
    route: EvidenceCandidate,
    column: str,
    role: str,
    objective_context: ResearchObjective | None,
) -> bool:
    role_text = str(role or "").strip()
    if "process" in role_text or "variable" in role_text:
        return True
    if objective_context is not None:
        for label in (column, role_text):
            if _objective_label_matches_variables(
                label,
                objective_context=objective_context,
            ):
                return True
    return route.role == "process_or_treatment" and objective_context is None


def _objective_label_matches_variables(
    label: Any,
    *,
    objective_context: ResearchObjective,
) -> bool:
    label_text = str(label or "").strip()
    if not label_text:
        return False
    label_axis_keys = property_matching.process_column_axis_keys(label_text)
    label_tokens = property_matching.axis_tokens(property_matching.axis_key(label_text))
    for axis in objective_context.variables:
        axis_text = str(axis or "").strip()
        if not axis_text:
            continue
        if property_matching.variable_matches_objective_scope(label_text, axis_text):
            return True
        axis_key = property_matching.normalize_property_label(axis_text)
        if axis_key and any(
            property_matching.process_axis_matches_objective_scope(
                label_axis_key,
                axis_key,
            )
            for label_axis_key in label_axis_keys
        ):
            return True
        if (
            property_matching.axis_values_match(label_text, axis_text)
            or property_matching.axis_label_is_mentioned(label_text, axis_text)
            or property_matching.axis_label_is_mentioned(axis_text, label_text)
        ):
            return True
        axis_tokens = property_matching.axis_tokens(
            property_matching.axis_key(axis_text)
        )
        if len(label_tokens & axis_tokens) >= 2:
            return True
    return False


def _objective_result_table_row_is_reference_context(
    *,
    route: EvidenceCandidate,
    row_values: dict[str, str],
    result_columns: set[str],
) -> bool:
    if route.role != "current_experimental_evidence":
        return False
    context_values = tuple(
        str(value).strip()
        for column, value in row_values.items()
        if column not in result_columns
        and not _objective_value_column_is_non_result(column)
        and str(value).strip()
    )
    if not context_values:
        return False
    context_text = " ".join(context_values)
    if re.search(r"\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\]", context_text):
        return True
    normalized = context_text.casefold()
    return any(
        marker in normalized
        for marker in (
            "literature",
            "previous study",
            "previous work",
            "reference material",
            "reference sample",
        )
    )


def _objective_table_row_attributes_with_sample_number(
    *,
    row_attributes: dict[str, dict[str, str]],
    row_index: int,
) -> dict[str, dict[str, str]]:
    sample_attributes = dict(row_attributes["sample"])
    if _objective_sample_attributes_have_explicit_number(sample_attributes):
        return row_attributes
    if (
        sample_attributes
        and not _objective_sample_attributes_need_row_number(sample_attributes)
        and _objective_sample_attributes_have_stable_label(sample_attributes)
    ):
        return row_attributes
    if not sample_attributes and not (
        row_attributes["material"]
        or row_attributes["process"]
        or row_attributes["test"]
    ):
        return row_attributes
    sample_attributes["sample_number"] = str(row_index)
    return {
        "material": row_attributes["material"],
        "sample": sample_attributes,
        "process": row_attributes["process"],
        "test": row_attributes["test"],
    }


def _objective_sample_attributes_have_explicit_number(
    sample_attributes: dict[str, Any],
) -> bool:
    for key, value in sample_attributes.items():
        text = str(value).strip()
        if not text:
            continue
        column_key = _objective_column_key(str(key))
        if column_key in {
            "case",
            "condition",
            "condition_no",
            "condition_number",
            "id",
            "no",
            "sample_no",
            "sample_number",
            "specimen",
            "specimen_id",
            "specimens",
        }:
            return True
        if column_key in {"sample", "sample_id"} and (
            re.fullmatch(r"0*\d+", text)
            or re.search(r"\bS0*\d+\b", text, flags=re.IGNORECASE)
            or re.search(r"\bsample\s*#?\s*0*\d+\b", text, flags=re.IGNORECASE)
        ):
            return True
    return False


def _objective_sample_attributes_need_row_number(
    sample_attributes: dict[str, Any],
) -> bool:
    for value in sample_attributes.values():
        tokens = [
            token
            for token in _objective_numeric_match_tokens(value)
            if token not in {"1", "-1"}
        ]
        if len(set(tokens)) >= 2:
            return True
    return False


def _objective_sample_attributes_have_stable_label(
    sample_attributes: dict[str, Any],
) -> bool:
    for key in sample_attributes:
        column_key = _objective_column_key(str(key))
        if column_key in {
            "build_orientation",
            "id",
            "label",
            "material",
            "orientation",
            "printed_316l",
            "sample",
            "sample_id",
            "sample_label",
            "specimen_orientation",
        }:
            return True
        if "sample" in column_key and "condition" not in column_key:
            return True
    return False


def _objective_table_column_is_sample_key(column_key: str) -> bool:
    return column_key in {
        "case",
        "condition",
        "condition_no",
        "condition_number",
        "id",
        "no",
        "printed_316l",
        "sample",
        "sample_id",
        "sample_no",
        "sample_number",
        "specimen",
        "specimen_id",
        "specimens",
    }


def _objective_matrix_unit_id(
    *,
    route: EvidenceCandidate,
    row_index: int,
    column: str,
) -> str:
    seed = "|".join((route.source_ref, str(row_index), column))
    return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"




























def _objective_route_result_columns(
    route: EvidenceCandidate,
    *,
    objective_context: ResearchObjective | None = None,
) -> set[str]:
    result_columns: set[str] = set()
    for column, role in route.column_roles.items():
        column_text = str(column)
        if _objective_value_column_is_non_result(column_text):
            continue
        role_text = str(role or "").strip().lower()
        if any(
            token in role_text
            for token in ("result", "target", "measurement", "property")
        ):
            if _objective_result_column_matches_target(
                column_text,
                objective_context=objective_context,
            ):
                result_columns.add(column_text)
            continue
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and _objective_column_key(role_text) == "current_experimental_evidence"
            and _objective_result_column_is_specific_metric(column_text)
        ):
            result_columns.add(column_text)
            continue
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and _objective_header_matches_any_axis(
                column_text,
                objective_context.outcomes,
            )
        ):
            result_columns.add(column_text)
            continue
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and _objective_column_key(column_text) == "relative_density"
            and any(
                axis in {"densification", "microstructure"}
                for axis in objective_context.outcomes
            )
        ):
            result_columns.add(column_text)
            continue
        role_label = property_matching.normalize_property_label(role_text)
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and role_label
            and property_matching.property_label_matches_target(
                role_label,
                target_axes=property_matching.objective_outcomes(objective_context),
            )
        ):
            result_columns.add(column_text)
    return result_columns


def _objective_result_column_property_label(
    *,
    route: EvidenceCandidate,
    source: Mapping[str, Any],
    result_column: str,
    objective_context: ResearchObjective | None,
) -> str:
    source_defined_property = _objective_source_defined_result_property(
        result_column,
        source=source,
        objective_context=objective_context,
    )
    if source_defined_property is not None:
        return source_defined_property
    role_label = property_matching.normalize_property_label(
        route.column_roles.get(result_column)
    )
    if (
        role_label
        and objective_context is not None
        and property_matching.result_role_is_specific_property(role_label)
        and property_matching.property_label_matches_target(
            role_label,
            target_axes=property_matching.objective_outcomes(objective_context),
        )
    ):
        return role_label
    property_name, _unit = _split_property_unit(result_column)
    return (
        property_matching.normalize_property_label(property_name)
        or str(property_name or result_column).strip()
    )


def _objective_result_column_is_specific_metric(column_text: str) -> bool:
    property_name, _unit = _split_property_unit(column_text)
    tokens = property_matching.axis_tokens(property_name)
    if not tokens:
        return False
    return bool(tokens & {"coefficient", "distance", "index", "score"})


def _objective_result_kind_from_column(column_text: str) -> str:
    """Classify a result column from its source-local header semantics.

    This is deliberately lexical and conservative: a table header can tell us
    whether a value is labelled as a prediction or experiment, but it cannot
    establish that an unlabeled value was measured.  Unlabeled results remain
    ``observed`` and may still be reviewed as source-reported observations.
    """

    normalized = " ".join(
        str(column_text or "")
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )
    if not normalized:
        return "unknown"
    if any(term in normalized for term in _OBJECTIVE_PREDICTED_RESULT_TERMS):
        if "simulat" in normalized:
            return "simulated"
        if "model" in normalized and "predict" not in normalized:
            return "modeled"
        return "predicted"
    if any(term in normalized for term in _OBJECTIVE_MEASURED_RESULT_TERMS):
        return "measured"
    return "observed"


def _objective_result_column_matches_target(
    column_text: str,
    *,
    objective_context: ResearchObjective | None,
) -> bool:
    if objective_context is None or not objective_context.outcomes:
        return True
    property_name, _unit = _split_property_unit(column_text)
    normalized = (
        property_matching.normalize_property_label(property_name) or property_name
    )
    target_axes = property_matching.objective_outcomes(objective_context)
    if property_matching.property_label_matches_target(
        normalized,
        target_axes=target_axes,
    ):
        return True
    if property_matching.outcome_matches_objective_scope(
        normalized,
        objective_context.outcomes,
    ):
        return True
    if property_matching.density_property_matches_structural_target(
        normalized,
        target_axes=target_axes,
    ):
        return True
    if normalized in target_axes:
        return True
    return any(
        property_matching.axis_label_is_mentioned(normalized, axis)
        or property_matching.axis_label_is_mentioned(column_text, axis)
        for axis in target_axes
    )


def _objective_result_column_matches_source_target(
    column_text: str,
    *,
    source: Mapping[str, Any],
    objective_context: ResearchObjective | None,
) -> bool:
    return _objective_result_column_matches_target(
        column_text,
        objective_context=objective_context,
    ) or _objective_source_defined_result_property(
        column_text,
        source=source,
        objective_context=objective_context,
    ) is not None


def _objective_source_defined_result_property(
    column_text: str,
    *,
    source: Mapping[str, Any],
    objective_context: ResearchObjective | None,
) -> str | None:
    if objective_context is None or not objective_context.outcomes:
        return None
    property_name, _unit = _split_property_unit(column_text)
    property_key = _objective_column_key(property_name)
    caption = str(source.get("caption_text") or "")
    if not property_key or not caption:
        return None
    for match in re.finditer(
        r"\b(?P<label>[A-Za-z][A-Za-z0-9._-]{0,15})\s*"
        r"(?:=|means?|denotes?)\s*(?P<definition>[^,;.\n]+)",
        caption,
        flags=re.IGNORECASE,
    ):
        if _objective_column_key(match.group("label")) != property_key:
            continue
        definition = match.group("definition").strip()
        if _objective_result_column_matches_target(
            definition,
            objective_context=objective_context,
        ):
            return property_matching.normalize_property_label(definition) or definition
    return None


def _objective_value_column_is_non_result(value: str) -> bool:
    text = " ".join(
        str(value or "").lower().replace("_", " ").replace("-", " ").split()
    )
    if not text:
        return True
    return any(term in text for term in _OBJECTIVE_NON_RESULT_VALUE_COLUMN_TERMS)






def _coerce_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    scientific_match = re.search(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:[xX\u00d7]\s*10)\s*\^?\s*([-+]?\d+)",
        text,
    )
    if scientific_match is not None:
        return float(scientific_match.group(1)) * (10 ** int(scientific_match.group(2)))
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    return float(match.group(0))


def _coerce_result_cell_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    matches = list(_NUMBER_PATTERN.finditer(text))
    if len(matches) >= 2:
        leading_prefix = text[: matches[0].start()]
        between_first_and_second = text[matches[0].end() : matches[1].start()]
        if "(" in leading_prefix and ")" in between_first_and_second:
            return float(matches[1].group(0))
    return _coerce_number(text)




def _objective_evidence_has_payload(
    unit: ExtractedEvidenceDraft,
) -> bool:
    return bool(
        unit.changed_variables
        or unit.comparison is not None
        or unit.reported_result is not None
        or unit.scientific_context.has_content
        or (
            unit.selection_status in {"candidate", "selected"}
            and unit.selection_reason in _NEEDS_CONTEXT_SELECTION_REASONS
        )
        or (
            unit.evidence_role == "condition_context"
            and unit.selection_status in {"candidate", "selected"}
            and unit.resolution_status == "unresolved"
        )
    )


def _dedupe_preserving_order(
    values: list[str | None],
) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _attach_route_tree_position(
    candidate: dict[str, Any],
    *,
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    tree_position = _route_candidate_tree_position(
        candidate,
        document_tree=document_tree,
    )
    if not tree_position:
        return candidate
    return {
        **candidate,
        "tree_position": tree_position,
    }


def _route_candidate_tree_position(
    candidate: dict[str, Any],
    *,
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    source_kind = str(candidate.get("source_kind") or "")
    source_ref = str(candidate.get("source_ref") or "")
    source_ref_kind = "block" if source_kind == "text_window" else source_kind
    node = (
        _tree_node_for_route_source(
            document_tree=document_tree,
            source_ref_kind=source_ref_kind,
            source_ref_id=source_ref,
        )
        if document_tree is not None and source_ref and source_ref_kind
        else None
    )
    if node is not None:
        return _tree_position_payload(
            document_tree=document_tree,
            node=node,
        )
    heading_path = candidate.get("heading_path")
    return {
        "node_id": None,
        "node_type": source_kind or None,
        "section_path": _heading_path_parts(heading_path),
        "source_ref_kind": source_kind or None,
        "source_ref_id": source_ref or None,
        "order": None,
        "page_start": None,
        "page_end": None,
    }


def _route_tree_position(candidate: dict[str, Any]) -> dict[str, Any]:
    tree_position = candidate.get("tree_position")
    if isinstance(tree_position, dict):
        return dict(tree_position)
    return {
        "node_id": None,
        "node_type": candidate.get("source_kind"),
        "section_path": _heading_path_parts(candidate.get("heading_path")),
        "source_ref_kind": candidate.get("source_kind"),
        "source_ref_id": candidate.get("source_ref"),
        "order": None,
        "page_start": candidate.get("page"),
        "page_end": candidate.get("page"),
    }


def _tree_position_payload(
    *,
    document_tree: SourceDocumentTree,
    node: Any,
) -> dict[str, Any]:
    return {
        "node_id": getattr(node, "node_id", None),
        "node_type": str(getattr(node, "node_type", "") or "") or None,
        "section_path": _tree_node_section_path(
            document_tree=document_tree,
            node=node,
        ),
        "source_ref_kind": getattr(node, "source_ref_kind", None),
        "source_ref_id": getattr(node, "source_ref_id", None),
        "order": getattr(node, "order", None),
        "page_start": getattr(node, "page_start", None),
        "page_end": getattr(node, "page_end", None),
    }


def _tree_node_section_path(
    *,
    document_tree: SourceDocumentTree,
    node: Any,
) -> list[str]:
    heading_path = tuple(getattr(node, "heading_path", ()) or ())
    if heading_path:
        return [str(part) for part in heading_path if str(part).strip()]
    titles: list[str] = []
    parent_id = getattr(node, "parent_id", None)
    while parent_id:
        parent = document_tree.nodes.get(parent_id)
        if parent is None:
            break
        if parent.node_type in {"section", "references_section"}:
            title = str(getattr(parent, "title", "") or "").strip()
            if title:
                titles.append(title)
        parent_id = getattr(parent, "parent_id", None)
    return list(reversed(titles))


def _heading_path_parts(heading_path: Any) -> list[str]:
    if isinstance(heading_path, (list, tuple)):
        return [str(part).strip() for part in heading_path if str(part).strip()]
    return [part.strip() for part in str(heading_path or "").split(">") if part.strip()]


def _tree_node_for_route_source(
    *,
    document_tree: SourceDocumentTree,
    source_ref_kind: str,
    source_ref_id: str,
) -> Any | None:
    node = document_tree.node_for_source_ref(source_ref_kind, source_ref_id)
    if node is not None:
        return node
    return document_tree.nodes.get(source_ref_id)


def _source_candidate_from_route(
    *,
    route: EvidenceCandidate,
    source: dict[str, Any],
    document_tree: SourceDocumentTree | None,
) -> dict[str, Any]:
    candidate = {
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "heading_path": source.get("heading_path"),
        "page": source.get("page"),
    }
    return _attach_route_tree_position(
        candidate,
        document_tree=document_tree,
    )


def _objective_evidence_prompt_route_record(
    route: EvidenceCandidate,
) -> dict[str, Any]:
    return {
        "objective_id": route.objective_id,
        "document_id": route.document_id,
        "source_kind": route.source_kind,
        "source_ref": route.source_ref,
        "role": route.role,
        "extractable": route.extractable,
        "reason": route.reason,
        "column_roles": dict(route.column_roles),
        "join_plan": dict(route.join_plan),
        "confidence": route.confidence,
        "context_fields": list(route.context_fields),
    }


def _objective_evidence_prompt_source(
    source: dict[str, Any],
) -> dict[str, Any]:
    source_kind = str(source.get("source_kind") or "")
    if source_kind == "table":
        table_markdown = str(source.get("table_markdown") or "")
        if not table_markdown:
            table_markdown = str(
                render_markdown_table(
                    _normalized_objective_table_matrix(source.get("table_matrix")),
                    [str(value) for value in source.get("column_headers", ())],
                    header_row_count=int(source.get("header_row_count", 1) or 0),
                )
                or ""
            )
        return {
            "source_kind": "table",
            "source_ref": str(source.get("source_ref") or ""),
            "document_id": source.get("document_id"),
            "page": source.get("page"),
            "caption_text": str(source.get("caption_text") or "")[
                :_ROUTE_PROMPT_TEXT_CHARS
            ],
            "heading_path": source.get("heading_path"),
            "column_headers": [
                str(value)[:_OBJECTIVE_STATE_TEXT_CHARS]
                for value in source.get("column_headers", []) or []
                if str(value).strip()
            ],
            "table_markdown": table_markdown,
            "table_visual_text": str(source.get("table_visual_text") or "")[
                :_OBJECTIVE_EVIDENCE_TEXT_CHARS
            ]
            or None,
        }
    if source_kind == "text_window":
        return {
            "source_kind": "text_window",
            "source_ref": str(source.get("source_ref") or ""),
            "document_id": source.get("document_id"),
            "page": source.get("page"),
            "block_type": source.get("block_type"),
            "heading_path": source.get("heading_path"),
            "text": str(source.get("text") or "")[
                :_OBJECTIVE_EVIDENCE_PROMPT_TEXT_CHARS
            ],
        }
    return dict(source)


def _objective_seed_context_routes(
    *,
    units: Iterable[ExtractedEvidenceDraft],
    route: EvidenceCandidate,
) -> tuple[EvidenceCandidate, ...]:
    """Expose previously inspected same-paper Sources to the next prompt."""

    routes: list[EvidenceCandidate] = []
    seen: set[tuple[str, str]] = set()
    for unit in units:
        if unit.objective_id != route.objective_id or unit.document_id != route.document_id:
            continue
        unit_is_context = (
            unit.reported_result is None
            and unit.evidence_role
            in {
                "condition_context",
                "mechanism_context",
                "baseline_context",
                "comparison_context",
                "background_context",
            }
        )
        context_fields: list[str] = []
        if unit_is_context:
            if unit.scientific_context.material:
                context_fields.append("material")
            if unit.scientific_context.sample:
                context_fields.append("sample")
            if unit.scientific_context.process:
                context_fields.append("variable")
            if unit.scientific_context.test:
                context_fields.append("test")
            if unit.comparison is not None:
                context_fields.append("comparison")
        for source_ref_record in unit.source_refs:
            source_kind = _text(source_ref_record.get("source_kind")).casefold()
            source_ref = _text(source_ref_record.get("source_ref"))
            if source_kind in {"block", "section", "text"}:
                source_kind = "text_window"
            if source_kind not in {"text_window", "table", "figure"} or not source_ref:
                continue
            source_key = (source_kind, source_ref)
            if source_key == (route.source_kind, route.source_ref) or source_key in seen:
                continue
            seen.add(source_key)
            if unit_is_context:
                seed_role = unit.evidence_role or "background_context"
                seed_context_fields = tuple(context_fields)
            else:
                seed_role = (
                    _text(source_ref_record.get("role")) or "background_context"
                )
                seed_context_fields = normalize_objective_terms(
                    source_ref_record.get("context_fields")
                ) or _OBJECTIVE_ROUTE_DEFAULT_CONTEXT_FIELDS.get(
                    seed_role.casefold(),
                    (),
                )
            routes.append(
                EvidenceCandidate.from_mapping(
                    {
                        "objective_id": route.objective_id,
                        "document_id": route.document_id,
                        "source_kind": source_kind,
                        "source_ref": source_ref,
                        "role": seed_role,
                        "extractable": True,
                        "reason": "Previously inspected same-paper Source.",
                        "confidence": 1.0,
                        "context_fields": seed_context_fields,
                    }
                )
            )
    return tuple(routes)


def _build_objective_same_paper_context_bundle(
    *,
    route: EvidenceCandidate,
    routes: tuple[EvidenceCandidate, ...],
    blocks: list[Any],
    tables: list[Any],
    figures: list[Any],
    document_tree: SourceDocumentTree | None,
    table_cells: list[Any],
) -> tuple[dict[str, Any], ...]:
    """Build the bounded context a researcher would read with one Source.

    The bundle is assembled from already routed Sources in the same paper. It
    is deliberately input-only: the current Source remains the authority for
    its reported result, while bundle items can close material, process,
    sample, test, and comparison context. Sources that do not fit the bounded
    request are recorded in diagnostics so omission is distinguishable from a
    scientific absence.
    """

    current_key = (route.source_kind, route.source_ref)
    bundle: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    encoded_chars = 0
    seen: set[tuple[str, str]] = set()
    # Adaptive context routes are appended after the initial result routes. A
    # simple first-N truncation would therefore evict the Methods/test Source
    # that can close a result's missing fields. Keep field-bearing context
    # routes first, then preserve their original document order for ties.
    context_roles = {
        "process_or_treatment",
        "test_condition",
        "characterization",
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
    }
    ordered_candidates = tuple(
        candidate
        for _position, candidate in sorted(
            enumerate(routes),
            key=lambda item: (
                0 if item[1].context_fields else 1,
                -len(item[1].context_fields),
                # Complete tables and figure captions preserve the condition
                # and measurement context that a researcher would inspect
                # before incidental narrative.  Keep this tie-breaker after
                # explicit field coverage so a targeted Methods Source still
                # wins over an unrelated table.
                0
                if item[1].source_kind == "table"
                else 1
                if item[1].source_kind == "figure"
                else 2,
                0 if item[1].role in context_roles else 1,
                item[0],
            ),
        )
    )
    for candidate in ordered_candidates:
        if (
            candidate.objective_id != route.objective_id
            or candidate.document_id != route.document_id
            or not candidate.extractable
            or candidate.role == "low_value_or_irrelevant"
        ):
            continue
        source_key = (candidate.source_kind, candidate.source_ref)
        if source_key == current_key or source_key in seen:
            continue
        if candidate.role == "background_context" and not candidate.context_fields:
            omitted.append(
                {
                    "source_kind": candidate.source_kind,
                    "source_ref": candidate.source_ref,
                    "reason": "unscoped background source excluded from context bundle",
                }
            )
            continue
        # A result Source is an experiment anchor, not context for another
        # result.  Passing independent Results prose in this bundle lets the
        # model combine separate experiments and attribute the wrong
        # conditions or outcome to the current anchor.  A route explicitly
        # carrying context fields is retained because some routing fallbacks
        # use the result role for a Methods/condition Source; complete tables
        # remain eligible as structured context for the anchored result.
        if (
            candidate.role in _DIRECT_RESULT_ROUTE_ROLES
            and not candidate.context_fields
            and candidate.source_kind != "table"
        ):
            omitted.append(
                {
                    "source_kind": candidate.source_kind,
                    "source_ref": candidate.source_ref,
                    "reason": "independent result source excluded from context bundle",
                }
            )
            continue
        seen.add(source_key)
        source = _build_objective_route_source_payload(
            route=candidate,
            blocks=blocks,
            tables=tables,
            figures=figures,
            document_tree=document_tree,
            table_cells=table_cells,
        )
        if not source:
            omitted.append(
                {
                    "source_kind": candidate.source_kind,
                    "source_ref": candidate.source_ref,
                    "reason": "source payload unavailable",
                }
            )
            continue
        item = _objective_evidence_prompt_source(source)
        item["role"] = candidate.role
        item["context_fields"] = list(candidate.context_fields)
        item_size = len(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        )
        if len(bundle) >= _OBJECTIVE_CONTEXT_BUNDLE_MAX_SOURCES:
            omitted.append(
                {
                    "source_kind": candidate.source_kind,
                    "source_ref": candidate.source_ref,
                    "reason": "context bundle source limit reached",
                }
            )
            continue
        if (
            encoded_chars + item_size > _OBJECTIVE_CONTEXT_BUNDLE_MAX_CHARS
            and bundle
        ):
            omitted.append(
                {
                    "source_kind": candidate.source_kind,
                    "source_ref": candidate.source_ref,
                    "reason": "context bundle character limit reached",
                    "estimated_chars": item_size,
                }
            )
            continue
        if item_size > _OBJECTIVE_CONTEXT_BUNDLE_MAX_CHARS:
            omitted.append(
                {
                    "source_kind": candidate.source_kind,
                    "source_ref": candidate.source_ref,
                    "reason": "single context Source exceeds character limit",
                    "estimated_chars": item_size,
                }
            )
            continue
        bundle.append(item)
        encoded_chars += item_size

    if omitted:
        record_analysis_diagnostic(
            {
                "trace_type": "objective_context_bundle_scope",
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "current_source_ref": route.source_ref,
                "included_source_count": len(bundle),
                "included_source_refs": [
                    {
                        "source_kind": item.get("source_kind"),
                        "source_ref": item.get("source_ref"),
                    }
                    for item in bundle
                ],
                "omitted_source_count": len(omitted),
                "omitted_source_refs": omitted,
                "max_sources": _OBJECTIVE_CONTEXT_BUNDLE_MAX_SOURCES,
                "max_chars": _OBJECTIVE_CONTEXT_BUNDLE_MAX_CHARS,
            }
        )
    return tuple(bundle)


def _objective_bundle_grounding_sources(
    bundle: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
    """Turn prompt Bundle items into source/ref pairs for deterministic checks."""

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in bundle:
        source_kind = _text(item.get("source_kind"))
        source_ref = _text(item.get("source_ref"))
        if not source_kind or not source_ref:
            continue
        source = dict(item)
        source.pop("role", None)
        source.pop("context_fields", None)
        pairs.append(
            (
                source,
                {
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "role": item.get("role"),
                    "page": item.get("page"),
                    "heading_path": item.get("heading_path"),
                    "supports": ["bundle_context"],
                },
            )
        )
    return tuple(pairs)


def _objective_bundle_source_refs_for_record(
    item: StructuredEvidenceExtraction,
    bundle_pairs: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
    *,
    existing_grounding_keys: set[tuple[str, str]],
) -> tuple[dict[str, Any], ...]:
    """Keep only bundle locators that support fields in one extracted result.

    The bundle is deliberately broader than one field because the extractor
    must be able to resolve an incomplete result.  Provenance is narrower: a
    Source is attached to the resulting Evidence only when it contains a
    concrete condition, endpoint, label, or context value returned by the
    model.  This prevents every same-paper Source from appearing to support
    every result while preserving the result Source as the authority for
    outcome values and direction.
    """

    if not bundle_pairs:
        return ()
    record = item.model_dump(exclude_unset=True)
    signals: list[tuple[str | None, Any]] = []

    for variable in record.get("changed_variables") or ():
        if not isinstance(variable, Mapping):
            continue
        name = _text(variable.get("name")) or None
        for field in ("baseline_value", "target_value"):
            value = variable.get(field)
            if value not in (None, ""):
                signals.append((name, value))

    comparison = record.get("comparison")
    if isinstance(comparison, Mapping):
        for field in ("baseline_label", "target_label"):
            value = comparison.get(field)
            if value not in (None, ""):
                signals.append((None, value))

    context = record.get("scientific_context")
    if isinstance(context, Mapping):
        for group in ("material", "sample", "process", "test"):
            for attribute in context.get(group) or ():
                if not isinstance(attribute, Mapping):
                    continue
                name = _text(attribute.get("name")) or group
                value = attribute.get("value")
                if value not in (None, ""):
                    signals.append((name, value))

    if not signals:
        return ()

    selected: list[dict[str, Any]] = []
    for source, ref in bundle_pairs:
        source_kind = _text(ref.get("source_kind"))
        source_ref = _text(ref.get("source_ref"))
        if not source_kind or not source_ref:
            continue
        if (source_kind, source_ref) in existing_grounding_keys:
            continue
        source_text = _objective_source_grounding_text(source)
        if not source_text:
            continue
        supports_source = False
        for name, value in signals:
            if name is not None and not _objective_axis_is_source_grounded(
                name,
                source=source,
                source_text=source_text,
            ):
                continue
            if value not in (None, "") and not _objective_value_is_source_grounded(
                value,
                source_text,
            ):
                continue
            supports_source = True
            break
        if supports_source:
            selected.append(dict(ref))
    return tuple(selected)


def _merge_objective_grounding_source_pairs(
    existing: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
    additional: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
    merged: list[tuple[dict[str, Any], dict[str, Any]]] = list(existing)
    seen = {
        (
            _text(ref.get("source_kind")),
            _text(ref.get("source_ref")),
        )
        for _source, ref in existing
    }
    for source, ref in additional:
        key = (_text(ref.get("source_kind")), _text(ref.get("source_ref")))
        if not all(key) or key in seen:
            continue
        merged.append((source, ref))
        seen.add(key)
    return tuple(merged)


def _empty_objective_document_state() -> dict[str, Any]:
    return {
        "schema_version": "objective_document_state.v2",
        "evidence_counts_by_role": {},
        "prior_evidence": [],
        "same_paper_context": [],
    }


def _objective_document_state_payload(
    units: list[ExtractedEvidenceDraft],
) -> dict[str, Any]:
    if not units:
        return _empty_objective_document_state()
    counts_by_role: dict[str, int] = {}
    for unit in units:
        role = unit.evidence_role or "irrelevant"
        counts_by_role[role] = counts_by_role.get(role, 0) + 1
    prior_evidence: list[dict[str, Any]] = []
    same_paper_context: list[dict[str, Any]] = []
    for unit in units[-_OBJECTIVE_STATE_ITEM_LIMIT:]:
        prior_evidence.append(
            {
                "evidence_role": unit.evidence_role,
                "outcome": (
                    unit.reported_result.outcome if unit.reported_result else None
                ),
                "attribution_scope": unit.attribution_scope,
                "resolution_status": unit.resolution_status,
                "source_refs": [dict(ref) for ref in unit.source_refs[:2]],
            }
        )
        context = {
            group: [
                item.to_record()
                for item in getattr(unit.scientific_context, group)[:4]
            ]
            for group in ("material", "sample", "process", "test")
            if getattr(unit.scientific_context, group)
        }
        if context:
            same_paper_context.append(
                {
                    "source_refs": [dict(ref) for ref in unit.source_refs[:2]],
                    "scientific_context": context,
                }
            )
    return {
        "schema_version": "objective_document_state.v2",
        "evidence_counts_by_role": counts_by_role,
        "prior_evidence": prior_evidence,
        "same_paper_context": same_paper_context,
    }


def _objective_document_grounding_sources(
    units: list[ExtractedEvidenceDraft],
    *,
    route: EvidenceCandidate,
    blocks: list[Any],
    tables: list[Any],
    figures: list[Any],
    document_tree: SourceDocumentTree | None,
    table_cells: list[Any],
) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
    """Resolve previously read same-paper Sources for an Evidence Bundle."""

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for unit in units:
        if unit.selection_status == "failed":
            continue
        unit_is_result = unit.reported_result is not None or unit.evidence_role in {
            "direct_result",
            "contradictory_result",
        }
        for ref in unit.source_refs:
            source_kind = str(ref.get("source_kind") or "").strip()
            source_ref = str(ref.get("source_ref") or "").strip()
            if source_kind in {"block", "text"}:
                source_kind = "text_window"
            if not source_ref or not source_kind:
                continue
            if (
                unit_is_result
                and source_kind != "table"
            ):
                # Previously read result prose is another experiment anchor,
                # not context for the current result.  Keeping it here would
                # let a later extraction borrow conditions from an unrelated
                # Results block merely because it came from the same paper.
                continue
            key = (source_kind, source_ref)
            if key == (route.source_kind, route.source_ref) or key in seen:
                continue
            context_route = EvidenceCandidate.from_mapping(
                {
                    "objective_id": route.objective_id,
                    "document_id": route.document_id,
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "role": ref.get("role") or "same_paper_context",
                    "extractable": True,
                    "reason": "Previously read same-paper context Source.",
                    "confidence": 1.0,
                }
            )
            context_source = _build_objective_route_source_payload(
                route=context_route,
                blocks=blocks,
                tables=tables,
                figures=figures,
                document_tree=document_tree,
                table_cells=table_cells,
            )
            if not context_source:
                continue
            context_ref = dict(ref)
            context_ref["source_kind"] = source_kind
            context_ref["source_ref"] = source_ref
            pairs.append((context_source, context_ref))
            seen.add(key)
    return tuple(pairs)


def _route_text_node_block_type(node: Any) -> str:
    node_type = str(getattr(node, "node_type", "") or "")
    if node_type == "caption":
        source_ref_kind = str(getattr(node, "source_ref_kind", "") or "")
        return "figure_caption" if source_ref_kind == "figure" else "paragraph"
    return node_type


def _tree_node_in_reference_branch(
    document_tree: SourceDocumentTree,
    node: Any,
) -> bool:
    current = node
    while current is not None:
        if current.node_type in {"references_section", "reference_entry"}:
            return True
        if getattr(current, "semantic_role", None) == "references":
            return True
        parent_id = getattr(current, "parent_id", None)
        current = document_tree.nodes.get(parent_id) if parent_id else None
    return False
