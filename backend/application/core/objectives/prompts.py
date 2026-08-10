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
        "Extract a bounded structured research map from one paper. This is coarse "
        "study-design mapping for later cross-paper objective discovery, not final "
        "measurement extraction or evidence synthesis.\n\n"
        "INPUT\n"
        "The input contains one document id and title, a bounded text preview, a "
        "coarse document profile, headings, and bounded table/figure captions. These "
        "are incomplete views; absence from the preview is not evidence of absence.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Classify the paper role from explicit study-design signals.\n"
        "2. Record only explicitly supported material and process families.\n"
        "3. `changed_variables` contains factors explicitly varied or compared; do "
        "not place fixed context or measured responses there.\n"
        "4. `candidate_properties` contains measured outcomes, not process settings, "
        "mechanisms, or generic claims.\n"
        "5. Create a `possible_objectives` question only when at least one changed "
        "variable and one measured outcome are supported by this paper.\n"
        "6. Use evidence density, confidence, and warnings to expose incomplete or "
        "ambiguous input rather than filling gaps.\n\n"
        "HARD RULES\n"
        "- Return only the schema object. Rank every list from most central and "
        "explicitly supported to least central so bounded consumers retain the "
        "strongest values.\n"
        "- Do not extract final measurements, sample-level results, or source ids.\n"
        "- Do not infer scientific content from filenames or generic section names.\n"
        "- Return empty arrays rather than guessing unsupported axes or objectives.\n\n"
        "OUTPUT CONTRACT\n"
        "- Return up to 8 `candidate_materials`, each at most 80 characters.\n"
        "- Return up to 4 `candidate_processes`, each at most 80 characters.\n"
        "- Return up to 8 `candidate_properties`, each at most 80 characters.\n"
        "- Return up to 8 `changed_variables`, each at most 80 characters.\n"
        "- Return up to 3 `possible_objectives`, each at most 320 characters.\n"
        "- Return up to 2 `warnings`, each at most 240 characters.\n"
        "- Keep each value concise; do not combine distinct list values into one item."
    )
    return _RESEARCH_OBJECTIVE_SYSTEM_PROMPT, user_prompt


def build_research_objective_discovery_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Create a small set of collection-level variable-to-outcome comparison "
        "objectives from bounded per-paper structured research maps. This is "
        "cross-paper candidate grouping and ranking, not evidence extraction, final "
        "fact synthesis, or question selection from one paper.\n\n"
        "INPUT SCHEMA\n"
        "- `collection_id` identifies the collection and must never be copied to output.\n"
        "- `paper_skims` is the list of bounded per-paper research maps.\n"
        "- `document_id` is the exact Source document identity.\n"
        "- `doc_role` separates experimental, modeling, review, and uncertain work.\n"
        "- `candidate_materials` identifies material systems; "
        "`candidate_processes` provides bounded process-scope hints.\n"
        "- `changed_variables` are candidate comparison factors explicitly varied or "
        "compared in that paper.\n"
        "- `candidate_properties` are candidate measured outcomes.\n"
        "- Treat `possible_objectives` as a noisy hint, never as the sole authority.\n"
        "- `evidence_density`, `confidence`, and `warnings` describe skim quality, not "
        "scientific result strength.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "DECISION PROCESS\n"
        "1. Build candidate variable-outcome pairs only from structured skim axes.\n"
        "2. Group compatible skims by aligned variable and outcome axes while keeping "
        "different material systems or incompatible study designs visible.\n"
        "3. Prefer candidates supported by at least two experimental skims. Retain a "
        "single-paper candidate only when it is high-confidence and no stronger "
        "cross-paper candidate displaces it.\n"
        "4. Choose exact variable and outcome labels present in at least one seed skim, "
        "then construct one question with separate exact role regions. Put a material "
        "shared by every seed in `material_scope`.\n"
        "5. Add a seed document only when that skim supports every returned variable, "
        "outcome, and material. Reviews and background mentions are not direct seeds.\n"
        "6. Rank by direct document coverage, axis specificity, evidence density, and "
        "skim confidence. Reject ambiguous or unsupported combinations.\n\n"
        "HARD RULES\n"
        "- The top-level object must contain exactly one key: `objectives`. Never echo "
        "`collection_id` or any other input metadata. Return at most six objectives. "
        "Rank across all skims and keep only the six highest-signal objectives total; "
        "never emit a seventh objective. Return fewer than six when another candidate cannot align "
        "its question, variables, and outcomes exactly; skip that candidate instead "
        "of weakening, broadening, or hiding a field label.\n"
        "- Every variable must be supported by `changed_variables`, and every outcome "
        "must be supported by `candidate_properties`, in each declared seed skim. "
        "Never invent an axis found only in another field. Prefer 'How does/do "
        "<variables joined with and> affect <outcomes joined with and>?'.\n"
        "- Supported question forms have separate exact role regions: in '<variables> "
        "affect/influence/impact <outcomes>', variables precede the active relation "
        "and outcomes follow it; in 'effects of <variables> on <outcomes>', variables "
        "occur between `of` and `on` and outcomes follow `on`; in 'relationship "
        "between <variables> and <outcomes>', use one separating `and` such that all "
        "declared variables occur before it and all declared outcomes follow it. "
        "Passive forms are invalid. Every selected label must occur verbatim in its "
        "assigned role region.\n"
        "- Group semantically aligned axes across papers, but never combine unrelated "
        "variables or outcomes merely to increase document count. Keep only tightly "
        "related outcomes.\n"
        "- Do not repeat the same variable-outcome combination. Keep distinct "
        "variable-outcome families separate.\n"
        "- Put common material identities in `material_scope`, using exact labels "
        "from the seed skims. Every seed must support every returned material. When "
        "materials conflict, split the objective or reduce its seeds; never silently "
        "mix material systems.\n"
        "- Put only supported explanatory intermediate concepts in `mechanisms`. Do "
        "not put another measured property in `mechanisms`.\n"
        "- Put fixed process, sample, and test scope in `constraints`. Every "
        "`seed_document_ids` value must identify a skim that supports the complete "
        "returned axes. Use exact document_id values for seed/excluded ids. Do not "
        "append scope wording to a variable or outcome label in `question`.\n\n"
        "BOUNDARY EXAMPLES\n"
        "Compatible input: paper-a and paper-b are experimental, both have "
        "candidate_materials=['316L stainless steel'], "
        "changed_variables=['laser power'], and "
        "candidate_properties=['relative density'].\n"
        "Expected output item: {\"question\":\"How does laser power affect relative "
        "density?\",\"material_scope\":[\"316L stainless steel\"],"
        "\"variables\":[\"laser power\"],\"outcomes\":[\"relative "
        "density\"],\"seed_document_ids\":[\"paper-a\",\"paper-b\"]}.\n"
        "Non-seed input: a review mentions laser power but has no changed variable or "
        "measured property. It may inform scope but cannot be a seed.\n"
        "Reject input: paper-a varies heat treatment for yield strength while paper-b "
        "varies scan speed for porosity. Do not manufacture a broader process "
        "parameter objective; if these are the only skims, return "
        "{\"objectives\":[]}.\n\n"
        "ROLE ALIGNMENT EXAMPLE\n"
        "Valid: question='How does factor alpha affect response beta?', "
        "variables=['factor alpha'], outcomes=['response beta'].\n"
        "Invalid: that same question with variables=['factor alpha value'] or "
        "outcomes=['response']; those labels are not verbatim in their roles.\n"
        "If the variable label is 'factor alpha value', the question must contain "
        "that full label rather than shortening it to 'factor alpha'. If the outcome "
        "label is 'response beta', do not replace it with a broader phrase such as "
        "'response behavior'.\n\n"
        "OUTPUT\n"
        "Return compact JSON without indentation. Omit optional fields whose value "
        "would be null, empty, or the schema default. Do not output reasoning, "
        "commentary, or field-assignment explanations. When no defensible candidate "
        "exists, return exactly `{\"objectives\":[]}`."
    )
    system_prompt = (
        "Build concise research-objective questions for literature comparison using "
        "only the supplied skims. Return one compact JSON object immediately. Do not "
        "output reasoning or commentary."
    )
    return system_prompt, user_prompt


def build_research_axis_canonicalization_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Canonicalize axis labels used by already-discovered research objectives.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with an `axis_groups` array.\n"
        "This is axis-label canonicalization, not objective discovery or objective "
        "merge.\n"
        "Hard constraints:\n"
        "- Use only labels from `axis_candidates`. Do not invent new axis labels.\n"
        "- `canonical` must be copied exactly from one of the group's `aliases`.\n"
        "- Every candidate axis label must appear exactly once in `aliases` for "
        "its own axis_type.\n"
        "- Do not mix axis types. Material, variable, outcome, mechanism, and "
        "constraint aliases may only group within their own type.\n"
        "- Group aliases only when they clearly refer to the same axis in this "
        "collection context, such as spelling, acronym, singular/plural, or "
        "wording variants.\n"
        "- Do not group broad concepts with specific endpoints unless the labels "
        "are genuinely the same axis. For example, a general performance category "
        "should not absorb several distinct measured endpoints.\n"
        "- If uncertain, keep the label as a single-alias group.\n"
        "For each group, provide a short reason grounded in the labels and paper "
        "skim context.\n"
    )
    return _RESEARCH_OBJECTIVE_SYSTEM_PROMPT, user_prompt


def build_research_objective_merge_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Decide whether already-discovered research objectives should be kept "
        "separate or merged before persistence.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with a `merged_objectives` array.\n"
        "This is a merge decision step, not new objective discovery.\n"
        "Hard constraints:\n"
        "- Use only the provided `candidate_objectives` and `paper_skims`.\n"
        "- Every candidate objective id must appear exactly once in "
        "`source_objective_ids` across the whole response.\n"
        "- Do not invent new source ids, material_scope, variables, outcomes, "
        "mechanisms, or constraints. Merged values must come from candidate "
        "objectives.\n"
        "- If an objective should not be merged, return a group with only that "
        "single source id.\n"
        "- Merge objectives only when they are the same research question split "
        "by a variable axis or by a subset of closely related property endpoints.\n"
        "- Do not merge objectives whose `outcomes` are disjoint. Disjoint "
        "property axes usually mean different research directions.\n"
        "- Do not merge different research directions. For example, keep "
        "densification/microstructure separate from mechanical properties unless "
        "the candidate objectives explicitly frame them as one comparison.\n"
        "- Keep composition/background/literature-comparison objectives separate "
        "from current-work performance objectives.\n"
        "- If uncertain, keep objectives separate.\n"
        "- Every output question must preserve its variables on the source side and "
        "its outcomes on the result side of a supported active question form.\n"
        "For each output group, preserve the complete scientific-intent fields, "
        "write a question-shaped `question`, and explain why the sources were "
        "merged or kept separate. `requested_comparator` remains optional.\n"
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
