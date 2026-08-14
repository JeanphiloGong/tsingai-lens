from __future__ import annotations

import json
from typing import Any

FINDING_SYNTHESIS_PROMPT_VERSION = "finding_synthesis.v8"

_RESEARCH_OBJECTIVE_SYSTEM_PROMPT = """
You are building research-objective records for an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is research-map extraction, not final fact extraction.
- Return exactly one JSON object and nothing else.
- Do not emit measurement results, sample variants, evidence anchors, backend ids, or source locators.
- Do not infer material systems from filenames.
- Prefer fewer, higher-signal outputs over speculative coverage.
- Research objectives must be question-shaped. Do not return a plain material list.
""".strip()


_PAPER_SKIM_SYSTEM_PROMPT = """
You are screening one bounded Source window for a traceable literature map.

Non-negotiable rules:
- This is high-recall study-design screening, not final fact extraction or synthesis.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied `source_unit_id` values; never invent or rewrite an id.
- Do not infer material systems from filenames or section names.
""".strip()


_PAPER_SIGNAL_RECONCILIATION_SYSTEM_PROMPT = """
You are reconciling source-linked variable and outcome signals within one paper.

Non-negotiable rules:
- This is paper-level reconciliation, not cross-paper grouping or final synthesis.
- Return exactly one JSON object and nothing else.
- Link signals only when their supplied excerpts and contexts support one study design.
- Copy only supplied `signal_id` values; never invent scientific labels or ids.
- Preserve ambiguity by returning an unresolved signal instead of guessing a link.
""".strip()


_OBJECTIVE_PAPER_FRAME_SYSTEM_PROMPT = """
You are framing one paper against one research objective for an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is coarse objective-paper routing, not final fact extraction.
- Return exactly one JSON object and nothing else.
- Do not emit measurement results, sample variants, evidence anchors, or backend persistence ids.
- You may return table ids only by copying ids from `table_summaries`.
- You may return section labels only by copying headings from `section_snippets`.
- Do not infer material systems from filenames.
- Prefer a conservative frame: mark unrelated or review-only papers as low, irrelevant, review, or supporting_background.
""".strip()


_OBJECTIVE_EVIDENCE_ROUTE_SYSTEM_PROMPT = """
You are routing source units for one research objective in an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is routing only, not final fact extraction.
- Return exactly one JSON object and nothing else.
- Decide only the `current_source` unit and return at most one route.
- Do not return source identity fields; the backend binds the route to the
  current source unit.
- Do not emit measurement results, sample variants, evidence anchors, or backend persistence ids.
- Do not output table schemas, column roles, join keys, join plans, source text, sample rows, explanations, or copied input JSON.
- For low-value, review, literature-comparison, composition-only, or unrelated
  units, return an empty `routes` array instead of writing a low-value route
  unless the source is explicitly frame-excluded.
- Prefer fewer, higher-confidence extractable routes over speculative coverage.
""".strip()


_OBJECTIVE_EVIDENCE_SYSTEM_PROMPT = """
TASK MODEL
Extract at most one objective-relevant fact from one selected source unit. This
is evidence extraction, not routing, summarization, or Finding synthesis.

INPUT SCHEMA AND AUTHORITY
- `OBJECTIVE` limits relevance and allowed outcomes; it is not evidence.
- `ROUTE HINT` is only a selection hint.
- `SOURCE` is the only scientific authority for every returned value.

DECISION PROCESS
1. If SOURCE does not report an objective outcome or useful objective-specific
   context, return `{"extractions":[]}`.
2. Context source: choose its context role and return no changed variables, no
   comparison, no reported result, and `not_attributable`.
3. Result source: include exactly one `reported_result`. One extraction represents
   one baseline-to-target comparison interval. Identify every changed factor and
   use exact source group labels or values as endpoints. If SOURCE reports a
   condition series, choose one complete source-supported pair. Never convert an
   absent, off, or without condition to numeric 0; retain the exact source phrase
   as a categorical endpoint with a null unit. The canonical OBJECTIVE outcome may
   appear under inflected, narrower, or synonymous SOURCE wording; keep the
   canonical name in `reported_result.outcome` but copy the exact source-local
   result clause into `result_text`. A complete comparison may bind endpoint
   phrases stated in separate sentences of the same SOURCE unit.
4. Never repeat a changed-variable name. Use `isolated_effect` only for one
   distinct changed factor with a complete comparable baseline/target comparison.
   Use `joint_effect` for two or more distinct changed factors. Otherwise use
   `association_only`, `descriptive_only`, or `not_attributable`.
5. Return empty output rather than inventing a missing binding.

HARD RULES
- Return exactly one compact JSON object with one top-level key: `extractions`.
- Return at most one extraction. Never repeat the input or output reasoning,
  markdown, source ids, or backend ids.
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
OUTPUT: {"extractions":[{"evidence_role":"direct_result","changed_variables":[{"name":"preheating","baseline_value":"without preheating","target_value":"preheating at 400 C","unit":null}],"comparison":{"baseline_label":"without preheating","target_label":"preheating at 400 C","axis_names":["preheating"],"comparable":true,"incomparability_reasons":[]},"reported_result":{"outcome":"crack formation","value":null,"unit":null,"direction":"decrease","result_text":"Application of preheating largely reduces this cracking behavior"},"attribution_scope":"isolated_effect","scientific_context":{"material":[],"sample":[],"process":[],"test":[]},"resolution_status":"resolved","confidence":0.9}]}

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
You are the evidence judge for one atomic materials-literature result set. The
backend has already grouped exact changed factors, one comparison interval,
and exactly one reported outcome across every candidate paper. Decide which
direct results support or contradict one bounded Finding.
This is not extraction, paper-by-paper generation, clustering, or summary.

INPUT SCHEMA
- `objective`: the user question and requested scientific scope.
- `result_set`: one backend-owned `result_set_id`, complete `factors`, one
  `outcome`, and `result_evidence`. A single comparison carries its source
  excerpt, explicit changed variables, comparison, reported result,
  attribution scope, scientific context, and paper id. A multi-interval
  condition series carries every Evidence id and paper id, every factor
  endpoint, structured result value/direction, and attribution scope while
  omitting repeated excerpts and context. The backend retains the complete
  persisted Evidence for final validation and traceback.
- `paper_contributions`: every paper considered in this Objective analysis,
  including analyzed papers without a direct result and excluded or failed
  papers. Paper metadata can qualify judgment but cannot become Evidence.
- `context_evidence`: bounded condition, comparison, mechanism, and baseline
  excerpts from papers in this result set. Context cannot create factors,
  outcomes, directions, or supporting papers.
- `candidate_rejection`: present only for one bounded repair attempt. It contains
  one backend semantic rejection reason: correction guidance, not Evidence and
  not a source of scientific facts.

DECISION PROCESS
1. Confirm that the factor tuple and outcome answer the Objective. Otherwise
   return an empty `findings` array.
2. Choose one defensible direction. The backend assigns result Evidence with
   that exact reported direction as support and explicit opposing directions as
   contradiction; do not output support or contradiction ids.
3. Return an empty `condition_boundary_evidence_ids` array. The backend derives
   condition dependence only when opposing direct results from different papers
   contain the same context attribute with disjoint values.
4. Choose `causal` only when one factor was isolated by every supporting
   comparison and the source explicitly supports intervention language. Use
   `associative` for joint changes or associations and `descriptive` for a
   bounded observation.
5. Use context Evidence only for explicit mechanisms. Every
   mechanism must be a subordinate relation backed by `mechanism_context`
   Evidence and those ids must also appear in `context_evidence_ids`.
6. Write one concise statement containing every factor and the one outcome.
   Do not mention any Objective variable absent from `result_set.factors`.
   Preserve decisive values and limits, distinguish support from contradiction,
   and do not strengthen association into single-variable causation. Every
   numeric endpoint in the statement must come from one complete supporting
   Evidence comparison; never combine endpoints from different Evidence rows.
   Numeric values may come only from `changed_variables` baseline/target values
   and `reported_result.value` or `reported_result.result_text` within that one
   Evidence record. Numbers present only in `source_excerpt` are not allowed.
   When result Evidence contains opposing directions, explicitly foreground
   heterogeneous or opposing responses across the reported conditions instead
   of presenting the selected direction as uniform.
7. When `candidate_rejection` is present, correct that exact failure and then
   re-check every rule against the original result Evidence. Do not repeat the
   rejected candidate or weaken its scientific claim to evade validation.

HARD RULES
- Return exactly one JSON object and nothing else.
- Do not output limitations. The backend derives analysis boundaries from
  validated Evidence coverage, attribution, and contradiction state.
- Return at most one Finding and copy `result_set_id` exactly.
- Treat `result_set_id` as backend-owned identity and copy it exactly from
  `result_set`.
- Do not output factors, outcome, paper count, Finding level, synthesis status,
  attribution scope, certainty, common context, or hidden reasoning. The backend
  owns and derives them from Evidence.
- Every `result_evidence` direction must be either the returned direction or an
  explicit opposition to it. Otherwise return an empty Finding array.
- Context ids must come from `context_evidence`. Always return an empty
  `condition_boundary_evidence_ids` array; condition boundaries are
  backend-derived from direct Evidence.
- Paper contributions cannot supply evidence ids or increase support scope.
- Joint factors must remain the complete factor set in the statement. Never
  select one convenient factor or rename the tuple as energy density.
- One Finding has one outcome. Never introduce another measured property into
  the statement or mechanisms.
- Do not combine a baseline from one result Evidence with a target from another.
  If you include numeric values, copy one complete supporting comparison.
- Mechanisms explain the main Finding and cannot replace its factors, outcome,
  direction, or support Evidence. Every mechanism Evidence id must come from a
  `mechanism_context` input and must also appear in `context_evidence_ids`; omit
  the mechanism when that exact Evidence id is unavailable.
- Do not convert association into control or causation. If no defensible
  Finding exists, return an empty `findings` array.

BOUNDARY EXAMPLES
- Factors are `laser power, scan speed`, outcome is `relative density`, and two
  papers report the same direction. Choose that direction and write both factors
  in the statement; do not call this an isolated energy-density effect.
- One paper reports a direct result and five papers only describe methods. Use
  the direct result's direction; do not use method papers as confirmation. The
  backend will derive insufficient confirmation.
- Two papers report opposing directions under otherwise comparable conditions.
  Choose one direction for the statement; the backend will bind the opposing
  result as contradiction. Do not cite a condition boundary without source
  Evidence.
- Opposing direct results from different papers report explicitly different
  heat-treatment values. Leave `condition_boundary_evidence_ids` empty; the
  backend will verify the disjoint context and derive condition dependence.

OUTPUT CONTRACT
Return `findings` only. Each item contains `result_set_id`, `statement`,
`direction`, `assertion_strength`, condition-boundary/context Evidence ids,
subordinate `mechanisms`. Use exact input ids for context and
boundaries, empty arrays when absent, and no extra keys.
""".strip()

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
        "7. Copy every Source-unit id that supports each relationship.\n"
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
        "directly support it. Do not return an id absent from `source_units`.\n"
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
    return _PAPER_SKIM_SYSTEM_PROMPT, user_prompt


def build_paper_signal_reconciliation_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Assign explicit, source-linked variable and outcome signals to paper-local "
        "studies and relationships when their excerpts prove shared experiment "
        "identity. This is membership adjudication, not scientific-field generation.\n\n"
        "INPUT SCHEMA\n"
        "- `document_id` identifies the one paper.\n"
        "- `signals` contains a backend-owned `signal_id`, `signal_type` (variable or "
        "outcome), exact label, material/process context, and one or more Source "
        "records with stable locator, section path, and bounded excerpt, plus any "
        "known experiment/design/material/process/sample/test/comparator context.\n"
        "- Source excerpts are the only authority for deciding whether signals belong "
        "to the same experiment or model.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "DECISION PROCESS\n"
        "1. Separate variable and outcome signals.\n"
        "2. Compare their material, process, condition, experiment, sample, and "
        "section evidence. Do not link signals merely because they occur in the same paper.\n"
        "3. Form a relationship only when the excerpts support the variable as varied, "
        "compared, or modeled and the outcome as the response for that same study design.\n"
        "4. Put relationships from the same explicit experiment in one study item; "
        "keep different experiments as different study items.\n"
        "5. A signal may support multiple relationships only when the Source explicitly "
        "reports that shared factor or response across those relationships.\n"
        "6. Every input signal must be accounted for: include it in at least one valid "
        "relationship, or return it once in `unresolved_signals` with a concrete reason.\n\n"
        "HARD RULES\n"
        "- In every relationship, copy only input `signal_id` values and include at "
        "least one variable signal and one outcome signal.\n"
        "- Never combine incompatible materials, processes, samples, tests, or "
        "experiments. Ambiguous proximity is not a link.\n"
        "- Do not output labels, contexts, Source locators, questions, or new scientific "
        "fields; the backend derives them from selected signals.\n"
        "- Do not mark a signal unresolved if it appears in a relationship.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Methods variable and Results outcome: Methods says laser power was varied "
        "for LPBF 316L specimens; Results says relative density was measured for those "
        "power conditions. Link both signal ids into one relationship.\n"
        "- Different experiments: Methods describes heat-treatment temperature for "
        "tensile coupons, while Results reports corrosion potential for as-built "
        "electrochemical specimens. Return both signals unresolved; do not link them.\n"
        "- Ambiguous result: Results lists hardness without identifying which of two "
        "independent process studies it belongs to. Keep the hardness signal unresolved.\n\n"
        "OUTPUT CONTRACT\n"
        "Return exactly `studies` and `unresolved_signals`. Each study contains one or "
        "more relationships with only `signal_ids` and `confidence`. An unresolved item has one "
        "`signal_id` and a concise `reason`. Return empty arrays when appropriate."
    )
    return _PAPER_SIGNAL_RECONCILIATION_SYSTEM_PROMPT, user_prompt


def build_research_axis_canonicalization_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Classify whether each candidate label pair names exactly the same neutral "
        "scientific axis before collection objective grouping. This is pair "
        "classification, not "
        "property-family clustering, causal interpretation, objective discovery, or "
        "evidence synthesis.\n\n"
        "INPUT SCHEMA\n"
        "- `collection_id` identifies the request and must not appear in output.\n"
        "- `axis_pairs` contains backend-selected possible aliases. Each item has an "
        "opaque `pair_id`, one `axis_type`, and exact `left` and `right` labels.\n"
        "- `material` pairs are material identities; `variable` pairs are changed "
        "factors; `outcome` pairs are measured or predicted responses.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Judge every pair independently within its supplied axis_type.\n"
        "2. Set `equivalent=true` only when substituting one label for the other preserves "
        "the exact scientific question. Acronyms, spelling variants, and grammatical "
        "variants can qualify.\n"
        "3. Set `equivalent=false` when the labels are merely related, inverse, causal, "
        "broad/narrow, jointly reported, different material grades, or different "
        "process parameters.\n"
        "4. Set `equivalent=false` when uncertain. This keeps both source labels.\n\n"
        "HARD RULES\n"
        "- Return one decision for every input pair, in input order.\n"
        "- Copy each input `pair_id` exactly once; do not omit, repeat, or invent IDs.\n"
        "- Each decision contains only `pair_id` and boolean `equivalent`.\n"
        "- Do not return labels, canonical names, groups, explanations, or confidence.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- VED and volumetric energy density: select; they are the same variable.\n"
        "- SS316L and 316L stainless steel: select; they are the same material grade.\n"
        "- SS316 and 316L stainless steel are different grades: reject.\n"
        "- scan speed and laser scanning speed: select when both denote the scan-speed "
        "factor; laser power and energy density: reject.\n"
        "- porosity and relative density are scientifically related but distinct "
        "measured outcomes: reject.\n"
        "- mechanical properties is a broad property family, not an alias for yield "
        "strength, elongation, hardness, fatigue, corrosion, or microstructure: reject.\n"
        "- microstructure and grain size, or porosity and defect size: reject; one is "
        "broader than the other.\n"
        "- tensile strength and ultimate tensile strength: reject without source "
        "context explicitly defining them as the same measurement.\n"
        "- surface hardness and hardness: reject; surface scope is meaningful.\n"
        "\n"
        "OUTPUT CONTRACT\n"
        "Return only schema-valid structured data with one `decisions` array. "
        "The array must account for every input pair even when all decisions are false.\n"
    )
    return _RESEARCH_OBJECTIVE_SYSTEM_PROMPT, user_prompt


def build_objective_paper_frame_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Frame this one paper for this one research objective.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with these fields: relevance, "
        "paper_role, background, material_match, changed_variables, "
        "measured_property_scope, test_environment_scope, relevant_sections, "
        "relevant_tables, and excluded_tables.\n"
        "Use the current `objective` as the research scope.\n"
        "`relevance` should be high only when the paper directly supports the "
        "objective's material/process/property comparison. Use medium or low for "
        "partial support, and irrelevant when the paper does not serve the lens.\n"
        "`paper_role` should distinguish current experiments from background, "
        "review, modeling-only, mixed, or irrelevant papers.\n"
        "`relevant_tables` should include only tables likely useful for later "
        "objective-scoped extraction. Exclude composition-only, generic parameter, "
        "review/literature-comparison, or unrelated tables unless they directly "
        "support this objective.\n"
        "`excluded_tables` should list visible tables that should not be extracted "
        "for this objective.\n"
        "Do not invent table ids or section labels. If uncertain, leave arrays empty."
    )
    return _OBJECTIVE_PAPER_FRAME_SYSTEM_PROMPT, user_prompt


def build_objective_evidence_route_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Route the current source unit for this one research objective.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with a `routes` array.\n"
        "Return at most one route for `current_source`. If it is not useful "
        "for later objective-scoped extraction, return `{\"routes\": []}`.\n"
        "Each route may contain only `role`, `extractable`, and `confidence`. "
        "Do not return `source_kind`, `source_ref`, ids, copied source text, "
        "explanations, or any nested input object.\n"
        "`role` must be one of: current_experimental_evidence, "
        "process_or_treatment, test_condition, composition_or_background, "
        "characterization, literature_comparison, modeling_or_prediction, "
        "low_value_or_irrelevant.\n"
        "Use the objective to decide whether `current_source` is direct "
        "target-outcome evidence, mediator/context evidence, or irrelevant. "
        "Treat `objective.outcomes` as the only outcomes that answer the "
        "objective. Treat `objective.mechanisms` as explanatory context unless the "
        "source explicitly links them to a target outcome.\n"
        "Use `current_experimental_evidence` only when the source unit likely "
        "contains current-work target results for the active objective.\n"
        "Use `process_or_treatment` or `test_condition` when a unit is mainly "
        "needed to bind samples, process variables, or test environments.\n"
        "Use `characterization` for microstructure, defect, phase, morphology, "
        "or grain observations tied to the active objective. Use "
        "`current_experimental_evidence` for explicit trends, best/worst "
        "conditions, or author explanations tied to target results.\n"
        "Use `low_value_or_irrelevant` with `extractable: false` only for "
        "frame-excluded tables that are passed as `current_source`."
    )
    return _OBJECTIVE_EVIDENCE_ROUTE_SYSTEM_PROMPT, user_prompt


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
    factors = [
        str(value).strip()
        for value in result_set.get("factors", ())
        if str(value).strip()
    ]
    outcome = str(result_set.get("outcome") or "").strip()
    required_terms = ", ".join(f"`{factor}`" for factor in factors)
    result_evidence = [
        item
        for item in result_set.get("result_evidence", ())
        if isinstance(item, dict)
    ]
    representative_evidence = result_evidence[0] if result_evidence else {}
    interval_signatures = {
        tuple(
            sorted(
                (
                    str(variable.get("name") or "").strip().casefold(),
                    str(
                        variable.get("baseline_value")
                        if variable.get("baseline_value") is not None
                        else ""
                    ).strip(),
                    str(
                        variable.get("target_value")
                        if variable.get("target_value") is not None
                        else ""
                    ).strip(),
                    str(variable.get("unit") or "").strip().casefold(),
                )
                for variable in item.get("changed_variables", ())
                if isinstance(variable, dict)
            )
        )
        for item in result_evidence
    }
    is_condition_series = len(interval_signatures) > 1
    reported_directions = {
        str(reported_result.get("direction") or "").strip()
        for item in result_evidence
        if isinstance(item.get("reported_result"), dict)
        and (reported_result := item["reported_result"])
    }
    has_opposing_directions = len(reported_directions) > 1
    factor_phrase = (
        ""
        if not factors
        else factors[0]
        if len(factors) == 1
        else f"{factors[0]} and {factors[1]}"
        if len(factors) == 2
        else f"{', '.join(factors[:-1])}, and {factors[-1]}"
    )
    comparison_details = [
        (
            f"`{str(item.get('name') or '').strip()}: "
            f"{str(item.get('baseline_value') if item.get('baseline_value') is not None else '').strip()} -> "
            f"{str(item.get('target_value') if item.get('target_value') is not None else '').strip()}`"
        )
        for item in representative_evidence.get("changed_variables", ())
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and str(
            item.get("baseline_value")
            if item.get("baseline_value") is not None
            else ""
        ).strip()
        and str(
            item.get("target_value")
            if item.get("target_value") is not None
            else ""
        ).strip()
    ]
    reported_result = (
        representative_evidence.get("reported_result")
        if isinstance(representative_evidence.get("reported_result"), dict)
        else {}
    )
    result_value = str(
        reported_result.get("value")
        if reported_result.get("value") is not None
        else ""
    ).strip()
    result_direction = str(reported_result.get("direction") or "").strip()
    candidate_rejection = (
        payload.get("candidate_rejection")
        if isinstance(payload.get("candidate_rejection"), dict)
        else {}
    )
    rejection_reason = str(candidate_rejection.get("reason") or "").strip()
    prompt_payload = dict(payload)
    if rejection_reason:
        prompt_payload["candidate_rejection"] = {"reason": rejection_reason}
    if rejection_reason == (
        "candidate statement combines numeric values not bound to one "
        "supporting Evidence record"
    ):
        prompt_payload["result_set"] = {
            **result_set,
            "result_evidence": [
                {
                    key: value
                    for key, value in evidence.items()
                    if key != "source_excerpt"
                }
                for evidence in result_evidence
            ],
        }
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
            "- Return one corrected replacement only if it satisfies every original "
            "Evidence and Finding rule; otherwise return an empty findings array.\n"
            "- Re-read result_evidence for its exact direction, complete factor "
            "tuple, one outcome, comparison values, and attribution scope.\n\n"
            "- When correcting numeric binding, remove every number available "
            "only in `source_excerpt`; keep numbers only from one Evidence "
            "record's `changed_variables` endpoints and "
            "`reported_result.value` or `reported_result.result_text`.\n\n"
        )
    comparison_contract = ""
    if is_condition_series:
        comparison_contract += (
            "- Treat the supplied comparisons as one reported condition series, "
            "not as independent Findings.\n"
            "- Start the statement with `Across the reported condition series, "
            f"{factor_phrase} showed heterogeneous or opposing responses in "
            f"{outcome}` and then summarize the response pattern.\n"
            "- Do not include numeric values in the statement; keep every endpoint "
            "bound to its individual Evidence record.\n"
        )
    else:
        if comparison_details:
            comparison_contract += (
                "- The statement must identify this complete source comparison: "
                f"{', '.join(comparison_details)}.\n"
            )
        if result_value:
            comparison_contract += (
                "- The statement must state the source-reported result detail "
                f"`{result_value}`.\n"
            )
        comparison_contract += (
            "- Never return a generic restatement such as `factor affects outcome`; "
            "state what differed between the compared groups.\n"
        )
    if has_opposing_directions:
        comparison_contract += (
            "- The statement must explicitly describe the responses as heterogeneous "
            "or opposing across conditions; the selected direction is not uniform.\n"
        )
    if len(factors) > 1:
        joint_statement_contract = (
            ""
            if is_condition_series
            else f"- Start the statement with `Joint changes in {factor_phrase} "
            "were associated with` and then state the direction and outcome.\n"
        )
        exact_contract = (
            "Exact contract for this result set:\n"
            f"- The statement must contain every factor verbatim: {required_terms}.\n"
            f"- The statement must contain the outcome verbatim: `{outcome}`.\n"
            "- `assertion_strength` must be `associative`; this is a joint-factor "
            "comparison, never a single-factor causal effect.\n"
            f"{joint_statement_contract}"
            "- Omit numbers unless all numeric endpoints come from one complete "
            "supporting Evidence comparison.\n"
            f"{comparison_contract}\n"
        )
    else:
        mixed_result_contract = ""
        if result_direction == "mixed" and comparison_details:
            first_variable = representative_evidence["changed_variables"][0]
            baseline = str(
                first_variable.get("baseline_value")
                if first_variable.get("baseline_value") is not None
                else ""
            ).strip()
            target = str(
                first_variable.get("target_value")
                if first_variable.get("target_value") is not None
                else ""
            ).strip()
            mixed_result_contract = (
                f"- Start the statement with `For {factors[0]}, {baseline} versus "
                f"{target} showed a difference in {outcome}:` and then state the "
                "observed result without implying increase, decrease, or causation.\n"
            )
        exact_contract = (
            "Exact contract for this result set:\n"
            f"- The statement must contain the factor verbatim: {required_terms}.\n"
            f"- The statement must contain the outcome verbatim: `{outcome}`.\n"
            f"{mixed_result_contract}"
            f"{comparison_contract}\n"
        )
    user_prompt = (
        "Judge one atomic factor-to-outcome result set for this research "
        "objective.\n\n"
        f"Input JSON:\n{input_json}\n\n"
        f"{repair_contract}"
        f"{exact_contract}"
        "Return only schema-valid structured data with a `findings` array.\n"
        "Return at most one Finding. Choose one direction that accounts for every "
        "result Evidence direction and leave `condition_boundary_evidence_ids` "
        "empty because the backend derives boundaries. Keep mechanisms subordinate. "
        "Do not return "
        "backend-derived status, scope, "
        "certainty, paper count, factors, or outcome. If no Finding meets the "
        "contract, return "
        "`{\"findings\": []}`."
    )
    return _FINDING_SYNTHESIS_SYSTEM_PROMPT, user_prompt
