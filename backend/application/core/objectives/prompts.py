from __future__ import annotations

import json
from typing import Any

PAPER_SKIM_PROMPT_VERSION = "paper_skim.v1"
PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION = "paper_signal_reconciliation.v2"
RESEARCH_AXIS_CANONICALIZATION_PROMPT_VERSION = "research_axis_canonicalization.v1"
OBJECTIVE_PAPER_FRAME_PROMPT_VERSION = "objective_paper_frame.v2"
OBJECTIVE_EVIDENCE_ROUTE_PROMPT_VERSION = "objective_evidence_route.v1"
OBJECTIVE_EVIDENCE_EXTRACTION_PROMPT_VERSION = "objective_evidence_extraction.v2"
FINDING_SYNTHESIS_PROMPT_VERSION = "finding_synthesis.v12"

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
You are adjudicating one bounded candidate neighborhood within one paper.

Non-negotiable rules:
- This batch has exactly one outcome anchor and candidate variable signals selected by the backend.
- This is paper-level membership adjudication, not cross-paper grouping or final synthesis.
- Return exactly one JSON object and nothing else.
- Link signals only when their supplied excerpts and contexts support one study design.
- Copy only supplied `signal_id` values; never invent scientific labels or ids.
- Preserve ambiguity by returning an unresolved signal instead of guessing a link.
- Account only for the current batch; the backend derives final whole-paper accounting.
""".strip()


_OBJECTIVE_PAPER_FRAME_SYSTEM_PROMPT = """
You are the source-relevance judge for one bounded neighborhood of a paper under one confirmed research objective.

Non-negotiable rules:
- This is bounded source-candidate classification, not whole-paper summarization or final fact extraction.
- Return exactly one JSON object and nothing else.
- Copy every supplied `source_unit_id` exactly once into either `relevant_source_unit_ids` or `excluded_source_unit_ids`.
- Never invent, rewrite, omit, or duplicate a source-unit id.
- Treat uncertain candidates as relevant so the downstream evidence router can inspect them.
- Do not emit measurement results, sample variants, evidence anchors, source text, or persistence ids.
- Do not infer material systems from filenames.
- Judge only the supplied neighborhood; omitted paper sources are outside this batch.
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
   `association_only`, `descriptive_only`, or `not_attributable`. Parameters with
   identical baseline and target values are fixed context, never changed variables
   or comparison axes.
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
        "Decide whether the candidate variables in one bounded candidate neighborhood "
        "belong to the same experiment or model as its exactly one outcome anchor. "
        "This is membership adjudication, not scientific-field generation or "
        "whole-paper discovery.\n\n"
        "INPUT SCHEMA\n"
        "- `document_id` identifies the one paper.\n"
        "- `signals` contains exactly one outcome anchor and one or more candidate "
        "variables. Each has a backend-owned `signal_id`, exact label, known scientific "
        "context, and bounded Source excerpts with stable Source-unit positions.\n"
        "- Signals omitted from this request are outside the current batch; omitted "
        "paper signals are outside this batch, not negative evidence.\n"
        "- Source excerpts are the only authority for deciding whether signals belong "
        "to the same experiment or model.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "DECISION PROCESS\n"
        "1. Identify the single outcome anchor and evaluate each candidate variable "
        "against it.\n"
        "2. Compare their material, process, condition, experiment, sample, and "
        "section evidence. Do not link signals merely because they occur in the same paper.\n"
        "3. Form a relationship only when the excerpts support the variable as varied, "
        "compared, or modeled and the outcome as the response for that same study design.\n"
        "4. Return at most one study for this neighborhood. Relationships may share the "
        "outcome anchor only when the Source explicitly supports that membership.\n"
        "5. Do not reason about omitted signals or attempt to reconstruct the whole paper.\n"
        "6. Include a rejected candidate once in `unresolved_signals` when a concise "
        "scientific reason is visible. The backend treats every omitted input signal "
        "as unresolved, so never invent a reason merely to repeat an ID.\n\n"
        "HARD RULES\n"
        "- In every relationship, copy only input `signal_id` values and include at "
        "least one variable signal and one outcome signal.\n"
        "- Never combine incompatible materials, processes, samples, tests, or "
        "experiments. Ambiguous proximity is not a link.\n"
        "- Do not output labels, contexts, Source locators, questions, or new scientific "
        "fields; the backend derives them from selected signals.\n"
        "- Do not mark a signal unresolved if it appears in a relationship. Backend "
        "relationship acceptance is authoritative when the response repeats an ID.\n\n"
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
        "Return exactly `studies` and `unresolved_signals`. Return at most one study, "
        "up to 11 relationships, and up to 12 unresolved signals. Each relationship "
        "contains only `signal_ids` and `confidence`; each unresolved item has one "
        "`signal_id` and a concise `reason`. The backend derives final whole-paper "
        "accounting after all candidate batches finish. Return empty arrays when appropriate."
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
        "TASK MODEL\n"
        "Perform bounded source-candidate classification for downstream objective-scoped evidence routing. "
        "This request contains one partial neighborhood, not the whole paper.\n\n"
        "INPUT SCHEMA\n"
        "- `collection_id`: backend scope identity; it is not scientific evidence and must not be returned.\n"
        "- `objective`: the confirmed comparison question and scientific axes.\n"
        "- `document`: backend metadata; the filename is not scientific evidence.\n"
        "- `document_profile`: backend document-type metadata; it is a routing hint, not authority over visible source text.\n"
        "- `paper_prior`: compact PaperSkim study context linked to the objective; it is a hint, not authority over visible source text.\n"
        "- `source_units`: current section chunks and table-row chunks. Each has a backend-owned `source_unit_id`, kind, stable source reference, and visible scientific content.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Read the objective variables, outcomes, material scope, constraints, and comparator.\n"
        "2. For each source unit independently, decide whether it may contain direct results, changed-variable context, material/sample/test context, mechanism context, or a useful table for that objective.\n"
        "3. Put useful or uncertain candidates in `relevant_source_unit_ids`; put only clearly unrelated, review-only, composition-only, or generic background candidates in `excluded_source_unit_ids`.\n"
        "4. Summarize only scientific scope supported by the current relevant candidates.\n"
        "5. Set batch `relevance` and `paper_role` from current evidence and `paper_prior`. Do not infer whole-paper irrelevance from facts absent in this partial neighborhood.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- A Methods section defining the objective variable but not reporting the outcome is relevant.\n"
        "- A Results table using a symbol or abbreviation for an objective axis is relevant when headers, caption, or cells establish that meaning.\n"
        "- A literature-comparison table without current-work results is excluded unless the objective explicitly asks for literature comparison.\n"
        "- Shared material alone does not make generic composition or background text relevant.\n\n"
        "SAME-SCHEMA EXAMPLE\n"
        "Example input: "
        '{"collection_id":"col-example","objective":{"variables":["laser power"],"outcomes":["relative density"]},"document":{"document_id":"paper-example"},"document_profile":{"doc_type":"experimental"},"paper_prior":{"doc_role":"experimental"},"source_units":[{"source_unit_id":"unit-methods","source_kind":"section","text":"Laser power was varied."},{"source_unit_id":"unit-composition","source_kind":"table","caption_text":"Nominal composition."}]}\n'
        "Example output: "
        '{"relevance":"medium","paper_role":"primary_experiment","background":"The current batch defines the changed process variable.","material_match":[],"changed_variables":["laser power"],"measured_property_scope":[],"test_environment_scope":[],"relevant_source_unit_ids":["unit-methods"],"excluded_source_unit_ids":["unit-composition"]}\n\n'
        "OUTPUT CONTRACT\n"
        "Return only schema-valid structured data. Every input `source_unit_id` must appear exactly once across `relevant_source_unit_ids` and `excluded_source_unit_ids`. "
        "Keep `background` concise and return no source text or reasoning transcript."
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
