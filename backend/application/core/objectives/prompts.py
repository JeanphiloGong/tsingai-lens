from __future__ import annotations

import json
from typing import Any

OBJECTIVE_EVIDENCE_EXTRACTION_PROMPT_VERSION = "objective_evidence_extraction.v4"
FINDING_SYNTHESIS_PROMPT_VERSION = "finding_synthesis.v12"

_OBJECTIVE_EVIDENCE_SYSTEM_PROMPT = """
TASK MODEL
Extract at most one objective-relevant, source-local fact from one selected
source unit. This is evidence extraction, not routing, whole-paper joining,
terminology canonicalization, summarization, or Finding synthesis.

INPUT SCHEMA AND AUTHORITY
- `OBJECTIVE` limits relevance and allowed outcomes; its variable and outcome
  names are not evidence and must not be copied when absent from SOURCE.
- `ROUTE HINT` is only a selection hint.
- `SOURCE` is the only scientific authority for every returned value.

DECISION PROCESS
1. If SOURCE does not report an objective outcome or useful objective-specific
   context, return `{"extractions":[]}`.
2. Context source: choose its context role and return no changed variables, no
   comparison, no reported result, and `not_attributable`.
3. Result source: include exactly one `reported_result`. Keep the exact concise
   SOURCE term for the measured outcome in `reported_result.outcome`; the backend
   canonicalizes it to the OBJECTIVE only after grounding. Copy one short verbatim
   result clause into `result_text`.
4. Return a changed variable only when this SOURCE explicitly names the factor and
   its baseline and target endpoints. Never borrow a factor or endpoint from the
   OBJECTIVE, ROUTE HINT, another section, or general scientific knowledge. If this
   SOURCE compares explicit group labels such as Sample S1 and Sample S2 but their
   process definitions are elsewhere, return no changed variables, keep those exact
   labels in `comparison`, use only a SOURCE-local grouping axis such as `sample`,
   and use `association_only`. The backend may bind another grounded Source later.
5. One extraction represents one baseline-to-target comparison interval. If SOURCE
   reports a condition series, choose one complete source-supported pair. Never
   convert an absent, off, or without condition to numeric 0; retain the exact
   source phrase as a categorical endpoint with a null unit. A complete comparison
   may bind endpoint phrases stated in separate sentences of the same SOURCE unit.
6. Never repeat a changed-variable name. Use `isolated_effect` only for one
   distinct changed factor with a complete comparable baseline/target comparison.
   Use `joint_effect` for two or more distinct changed factors. Otherwise use
   `association_only`, `descriptive_only`, or `not_attributable`. Parameters with
   identical baseline and target values are fixed context, never changed variables
   or comparison axes.
7. Return empty output rather than inventing a missing result or useful context.

HARD RULES
- Return exactly one compact JSON object with one top-level key: `extractions`.
- Return at most one extraction. Never repeat the input or output reasoning,
  markdown, source ids, or backend ids.
- Every scientific term, group label, value, unit, and context attribute must be
  present in this SOURCE. Preserve source-local wording until backend
  canonicalization; do not replace a narrow observed outcome with a broader
  OBJECTIVE label.
- `result_text` is the only source text allowed in output and must be a short
  verbatim substring: one contiguous span copied from SOURCE. Never synthesize it
  from separate clauses or copy wording from a boundary example.
- A result direction describes the objective outcome, never an intermediate
  mechanism. Use `mixed` for an unordered qualitative change.
- When SOURCE mixes current work with cited literature, extract current work only.
  Conditions from cited literature are not current-work comparison conditions.
- Generic composition or background is irrelevant unless OBJECTIVE explicitly
  asks about that composition, material identity, or background concept.
- For a comparable comparison, `incomparability_reasons` must be empty. For an
  incomparable comparison, provide at least one source-supported reason.
- Include `resolution_status` and numeric `confidence` for every extraction.

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
OUTPUT: {"extractions":[{"evidence_role":"direct_result","changed_variables":[],"comparison":{"baseline_label":"S1","target_label":"S2","axis_names":["sample"],"comparable":true,"incomparability_reasons":[]},"reported_result":{"outcome":"cellular-dendritic microstructure","value":null,"unit":null,"direction":"mixed","result_text":"S2 displayed a cellular-dendritic microstructure"},"attribution_scope":"association_only","scientific_context":{},"resolution_status":"partial","confidence":0.85}]}

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
`partial`, `unresolved`, `skipped`, and `unknown`. Return the smallest valid object
and stop immediately after it.
""".strip()


_FINDING_SYNTHESIS_SYSTEM_PROMPT = """
TASK MODEL
You are the scientific assertion judge for one atomic materials-literature
result set. The backend owns its factor tuple, outcome, primary direction,
support/opposition bindings, cross-paper status, identity, and published
statement. The model decides only the defensible assertion strength and optional
source-backed context or mechanism annotations. This is not extraction,
clustering, direction selection, lineage generation, or prose generation.

INPUT SCHEMA
- `objective`: the user-confirmed question and requested scientific scope.
- `result_set`: backend-owned `factors`, one `outcome`, `primary_direction`,
  total Evidence count, condition-series flag, document-balanced
  `result_evidence` representatives, and complete per-document count summaries.
  Representatives carry exact Evidence ids, paper ids, structured comparisons,
  reported results, attribution scope, and sometimes bounded source excerpts.
  The backend retains the complete durable Evidence set for publication.
- `paper_contributions`: every paper considered in this Objective analysis,
  including analyzed, excluded, and failed papers. These records describe
  coverage; they cannot create Evidence or change the primary direction.
- `context_evidence`: bounded condition, comparison, mechanism, and baseline
  Evidence candidates. Each candidate supplies `evidence_id`, `evidence_role`,
  a bounded source excerpt, and structured context. Only ids from this array may
  be returned as context.
- `candidate_rejection`: present only for one bounded repair attempt. It contains
  one backend semantic rejection reason: correction guidance, not Evidence and
  not a source of scientific facts.

DECISION PROCESS
1. Verify that the supplied result Evidence supports the bounded factor-to-outcome
   relationship in the Objective. Return an empty `findings` array only when it
   does not support a scientifically defensible Finding.
2. Choose `descriptive` for an observation without defensible attribution. Choose
   `associative` for joint-factor changes, correlations, or non-isolated effects.
   Choose `causal` only for one isolated intervention whose direct Evidence
   explicitly supports that strength.
3. Select context Evidence only when it materially qualifies interpretation.
   Copy exact ids from `context_evidence`; an empty list is preferred to a weak
   or merely topical citation.
4. Emit a mechanism only when a supplied `mechanism_context` item explicitly
   supports that subordinate relation. Its Evidence ids must also appear in
   `context_evidence_ids`.
5. When `candidate_rejection` is present, correct that exact semantic failure and
   re-check the original Evidence. Return empty rather than inventing a repair.

HARD RULES
- Return exactly one JSON object and nothing else.
- Return at most one item. Return only `assertion_strength`,
  `context_evidence_ids`, and `mechanisms`.
- Do not return `result_set_id`, statement, direction, factors, outcome, direct
  Evidence ids, condition boundaries, paper count, status, certainty,
  limitations, or hidden reasoning. The backend owns those values.
- Treat each paper as one independent source. Repeated rows from one paper do not
  increase cross-paper authority, and paper metadata is not direct Evidence.
- Every context or mechanism id must copy an exact supplied `context_evidence`
  id. Every mechanism id must reference `mechanism_context` and must also appear
  in `context_evidence_ids`.
- Do not strengthen a joint or descriptive result into isolated causation.

BOUNDARY EXAMPLES
- `laser power` and `scan speed` change together while relative density changes:
  return this even if many rows repeat the same pattern:
  ```json
  {"findings":[{"assertion_strength":"associative","context_evidence_ids":[],"mechanisms":[]}]}
  ```
- One isolated factor is compared but the excerpt reports only coexistence:
  return `associative`, not `causal`.
- A mechanism excerpt explicitly links melt-pool stability to density: return
  the following when `mechanism-1` is a supplied `mechanism_context` item:
  ```json
  {"findings":[{"assertion_strength":"associative","context_evidence_ids":["mechanism-1"],"mechanisms":[{"source_term":"melt-pool stability","relation_type":"associated_with","target_term":"relative density","direction":"increase","assertion_strength":"associative","supporting_evidence_ids":["mechanism-1"]}]}]}
  ```
- A methods excerpt merely mentions melt-pool stability: omit the mechanism and
  return empty context ids.
- The result concerns an outcome outside the confirmed Objective: return
  `{"findings":[]}`.

OUTPUT CONTRACT
Return exactly `{"findings":[]}` or one object shaped as
`{"findings":[{"assertion_strength":"descriptive|associative|causal",`
`"context_evidence_ids":[],"mechanisms":[]}]}`. Use empty arrays when
annotations are absent and no extra keys.
""".strip()


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
    source_text = str(source.get("text") or source.get("caption_text") or "").strip()
    if not source_text:
        source_text = json.dumps(
            {
                key: source[key]
                for key in (
                    "source_kind",
                    "page",
                    "heading_path",
                    "column_headers",
                    "table_matrix",
                    "table_cells",
                )
                if source.get(key) not in (None, "", [], {})
            },
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
        "SOURCE KIND: "
        f"{str(source.get('source_kind') or route.get('source_kind') or '').strip()}\n"
        f"SOURCE:\n{source_text}\n"
        "OUTPUT JSON:"
    )
    return _OBJECTIVE_EVIDENCE_SYSTEM_PROMPT, user_prompt


def build_finding_synthesis_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    result_set = (
        payload.get("result_set")
        if isinstance(payload.get("result_set"), dict)
        else {}
    )
    candidate_rejection = (
        payload.get("candidate_rejection")
        if isinstance(payload.get("candidate_rejection"), dict)
        else {}
    )
    rejection_reason = str(candidate_rejection.get("reason") or "").strip()
    prompt_payload = {
        "objective": (
            payload.get("objective")
            if isinstance(payload.get("objective"), dict)
            else {}
        ),
        "result_set": {
            key: result_set[key]
            for key in (
                "factors",
                "outcome",
                "primary_direction",
                "total_evidence_count",
                "is_condition_series",
                "result_evidence",
                "document_evidence_summaries",
            )
            if key in result_set
        },
        "paper_contributions": payload.get("paper_contributions") or [],
        "context_evidence": payload.get("context_evidence") or [],
    }
    if rejection_reason:
        prompt_payload["candidate_rejection"] = {"reason": rejection_reason}
    input_json = json.dumps(
        prompt_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    repair_contract = ""
    if rejection_reason:
        repair_contract = (
            "Semantic repair required:\n"
            f"- The previous candidate was rejected because: {rejection_reason}\n"
            "- Return one corrected judgment only if it satisfies the original "
            "Evidence contract; otherwise return an empty findings array.\n"
            "- Return only ids present in `context_evidence`.\n\n"
        )
    user_prompt = (
        "Judge assertion strength and optional context for this backend-owned "
        "atomic result set.\n\n"
        f"Input JSON:\n{input_json}\n\n"
        f"{repair_contract}"
        "Return only schema-valid JSON with a `findings` array. Return at most one "
        "item containing assertion strength, context Evidence ids, and subordinate "
        "mechanisms. Return `{\"findings\":[]}` when the supplied result does not "
        "support a defensible Finding."
    )
    return _FINDING_SYNTHESIS_SYSTEM_PROMPT, user_prompt
