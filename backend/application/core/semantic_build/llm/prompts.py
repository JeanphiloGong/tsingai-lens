from __future__ import annotations

import json
from typing import Any


FINDING_SYNTHESIS_PROMPT_VERSION = "finding_synthesis.v2"


_COMMON_SYSTEM_PROMPT = """
You are extracting structured research facts for a materials-literature backend.

Non-negotiable rules:
- Extract only facts directly supported by the provided input.
- Return exactly one JSON object and nothing else.
- If evidence is missing or ambiguous, use null or an empty list.
- Never infer material systems from filenames.
- Never treat years, citation numbers, row numbers, or footnote markers as result values.
- Never treat years, reference numbers, or numbering artifacts as units.
- Reject literature-summary rows or review-summary rows that are not directly attributable.
- Never emit backend-facing ids or locator fields such as `section_id`, `block_id`, `snippet_id`, or `figure_or_table`.
- Never emit backend persistence ids, Source ids, or bundle ref fields such as `method_ref`, `variant_ref`, `test_condition_ref`, `baseline_ref`, or `result_ref`.
- Prefer fewer, higher-signal outputs over speculative coverage.
""".strip()


_DOCUMENT_PROFILE_SYSTEM_PROMPT = """
You are doing document triage for a materials-literature backend.

Non-negotiable rules:
- This is coarse document classification, not knowledge extraction.
- Return exactly one JSON object and nothing else.
- Do not write natural-language summaries or explanations.
- `doc_type` must be one of: experimental, review, mixed, uncertain.
- `parsing_warnings` may only use: insufficient_content, classification_uncertain.
- If the input is weak or ambiguous, return `uncertain`.
""".strip()


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
TASK MODEL
You are the paper-screening judge for an evidence-backed literature comparison
backend. Produce one coarse PaperSkim used only to discover candidate research
questions for this paper. This is classification and research-map extraction,
not final fact extraction, paper summarization, evidence synthesis, or a final
research conclusion. Use only the supplied compact paper content.

INPUT SCHEMA
- `title`: paper title; useful context but potentially incomplete.
- `profile_hint.role_hint`: prior coarse classification hint. Treat it as a
  hint, not as an output field or unquestionable evidence.
- `profile_hint.source_quality_warnings`: parser/classifier quality warnings.
- `profile_hint.role_hint_confidence`: confidence in the prior role hint, not
  the confidence of your PaperSkim.
- `text_preview`: short source excerpt. It may be truncated or noisy.
- `headings`: bounded section labels.
- `table_captions`: bounded caption, section, and column-header context.
- `figure_captions`: bounded caption and section context.

DECISION PROCESS
1. Judge whether the supplied content is sufficient and whether the role hint
   conflicts with the paper content.
2. Choose `doc_role`: use `experimental` for reported physical experiments,
   `review` for literature synthesis, `modeling` for simulation-only studies,
   `mixed` for genuinely mixed roles, and `uncertain` when evidence is weak or
   conflicting.
3. Extract only explicitly named material systems and process families.
4. Extract changed variables only when the paper indicates that they vary or
   are compared. Do not turn fixed conditions into changed variables.
5. Extract concrete measured or evaluated properties. Do not return broad
   background topics as properties.
6. Return a possible objective only when the supplied content supports a
   question connecting a process or changed variable to a property in a
   material scope. Keep it question-shaped and concise. Review-only,
   modeling-only without comparable outputs, and insufficient inputs may use
   an empty objective list.
7. Set evidence density to `high` when several supplied elements directly
   support the map, `medium` for partial support, `low` for sparse or indirect
   support, and `unknown` when content is insufficient.
8. Set confidence for this complete PaperSkim and add only applicable warning
   codes from the output contract.

HARD RULES
- Make decisions silently. Return one JSON object and no analysis, markdown,
  copied input, backend ids, source locators, measurements, or extra fields.
- Return at most 3 materials, 3 processes, 4 properties, 4 changed variables,
  2 possible objectives, and 2 warnings.
- Prefer empty arrays and `uncertain` over unsupported inference.
- Do not infer a material from a filename or title alone.

FEW-SHOTS
1. Common experimental paper
Input:
{"title":"LPBF 316L density","profile_hint":{"role_hint":"experimental",
"source_quality_warnings":[],"role_hint_confidence":0.9},"text_preview":
"Laser energy density was varied for 316L and relative density was measured.",
"headings":["Methods","Results"],"table_captions":[],"figure_captions":[]}
Output:
{"doc_role":"experimental","candidate_materials":["316L stainless steel"],
"candidate_processes":["LPBF"],"candidate_properties":["relative density"],
"changed_variables":["laser energy density"],"possible_objectives":
["How does laser energy density affect relative density of LPBF 316L stainless steel?"],
"evidence_density":"high","confidence":0.9,"warnings":[]}

2. Review paper
Input:
{"title":"Review of corrosion in additively manufactured steels","profile_hint":
{"role_hint":"review","source_quality_warnings":[],"role_hint_confidence":0.9},
"text_preview":"This review summarizes prior LPBF 316L corrosion studies.",
"headings":["Literature review"],"table_captions":[],"figure_captions":[]}
Output:
{"doc_role":"review","candidate_materials":["316L stainless steel"],
"candidate_processes":["LPBF"],"candidate_properties":["corrosion behavior"],
"changed_variables":[],"possible_objectives":[],"evidence_density":"low",
"confidence":0.9,"warnings":["review_only"]}

3. Insufficient or conflicting input
Input:
{"title":"Material study","profile_hint":{"role_hint":"experimental",
"source_quality_warnings":["insufficient_content"],"role_hint_confidence":0.4},
"text_preview":"Results are discussed.","headings":[],"table_captions":[],
"figure_captions":[]}
Output:
{"doc_role":"uncertain","candidate_materials":[],"candidate_processes":[],
"candidate_properties":[],"changed_variables":[],"possible_objectives":[],
"evidence_density":"unknown","confidence":0.2,
"warnings":["insufficient_content","classification_uncertain"]}

OUTPUT CONTRACT
Return exactly these keys: `doc_role`, `candidate_materials`,
`candidate_processes`, `candidate_properties`, `changed_variables`,
`possible_objectives`, `evidence_density`, `confidence`, and `warnings`.
Use empty arrays when no supported value exists. The response ends immediately
after the JSON object.
""".strip()


_RESEARCH_OBJECTIVE_DISCOVERY_SYSTEM_PROMPT = """
TASK MODEL
You are the candidate-selection judge for an evidence-backed literature
comparison backend. Perform candidate selection and binding: select supported
research questions already proposed by PaperSkim records and bind each selected
question to the papers and axes that support it. This is candidate selection,
not final evidence extraction, not axis canonicalization, not objective merge,
and not free-form research-question generation.

INPUT SCHEMA
- `collection_id`: collection context only. Never return it.
- `paper_skims`: compact candidate records from the papers in this collection.
- `paper_skims[].document_id`: exact identifier for one input paper. This is the
  only source for `seed_document_ids` and `excluded_document_ids`.
- `paper_skims[].doc_role`: coarse paper role. Experimental and genuinely mixed
  papers may seed an objective; review, modeling-only, or uncertain papers do
  not seed a directly comparable experimental objective.
- `paper_skims[].candidate_materials`: material labels explicitly found in that
  paper.
- `paper_skims[].candidate_processes`: process-family labels explicitly found in
  that paper.
- `paper_skims[].changed_variables`: variables explicitly varied or compared in
  that paper. These may be selected as process axes.
- `paper_skims[].candidate_properties`: measured or evaluated property labels
  explicitly found in that paper.
- `paper_skims[].possible_objectives`: question-shaped candidates already
  supported by that paper. This is the only source for output `question`.

DECISION PROCESS
1. Ignore a skim as a seed when it has no possible objective or lacks a
   material, a process or changed variable, or a measured property.
2. Select only a question copied exactly from an input
   `possible_objectives` value. Never rewrite or expand it.
3. Bind seed papers that directly support that same material-process-property
   comparison. Copy their exact `document_id` values.
4. Copy `material_scope`, `process_axes`, and `property_axes` values exactly
   from the union of the selected seed skims. Do not normalize synonyms here.
5. Bind papers to one objective only when their candidate relationship is the
   same. Keep different process-property relationships as separate candidates;
   the downstream merge step decides whether separate candidates can merge.
6. Put a paper in `excluded_document_ids` only when its skim is clearly outside
   that objective's relationship. An empty exclusion list is valid.
7. If more than 6 candidates remain, rank them by number of supporting
   experimental papers, then by completeness of the material, process, and
   property binding. Keep the first 6.
8. Write a short comparison intent and a short grounding reason. Set confidence
   from the clarity and agreement of the selected skims, not from outside
   knowledge.
9. Return no objective when the input contains no complete, supported
   candidate. Use exactly `{"objectives":[]}` for that reject result.

HARD RULES
- Decide silently. Return one JSON object with no analysis, markdown, copied
  input, measurements, evidence claims, source locators, or extra fields.
- Return at most 6 objectives. Each objective has 1-3 materials, 1-8 process
  axes, 1-8 property axes, 1-12 seed ids, and 0-12 excluded ids.
- Every question and axis must be copied exactly from the selected seed skims.
- Every document id must be copied exactly from an input skim. Seed and
  excluded ids must be disjoint.
- Prefer the empty reject result over an unsupported or incomplete objective.

FEW-SHOTS
1. Shared objective across papers
Input:
{"collection_id":"c1","paper_skims":[{"document_id":"p1","doc_role":
"experimental","candidate_materials":["316L stainless steel"],
"candidate_processes":["LPBF"],"changed_variables":["laser energy density"],
"candidate_properties":["relative density"],"possible_objectives":
["How does laser energy density affect relative density of LPBF 316L stainless steel?"]},
{"document_id":"p2","doc_role":"experimental","candidate_materials":
["316L stainless steel"],"candidate_processes":["LPBF"],"changed_variables":
["laser energy density"],"candidate_properties":["relative density"],
"possible_objectives":["How does laser energy density affect relative density of LPBF 316L stainless steel?"]}]}
Output:
{"objectives":[{"question":"How does laser energy density affect relative density of LPBF 316L stainless steel?","material_scope":["316L stainless steel"],
"process_axes":["LPBF","laser energy density"],"property_axes":["relative density"],
"comparison_intent":"Compare relative density across reported laser energy densities.",
"seed_document_ids":["p1","p2"],"excluded_document_ids":[],"confidence":0.95,
"reason":"Both experimental skims propose the same material-process-property question."}]}

2. Unrelated candidates stay separate
Input:
{"collection_id":"c2","paper_skims":[{"document_id":"p1","doc_role":
"experimental","candidate_materials":["Ti-6Al-4V"],"candidate_processes":
["heat treatment"],"changed_variables":["aging temperature"],
"candidate_properties":["yield strength"],"possible_objectives":
["How does aging temperature affect yield strength of Ti-6Al-4V?"]},
{"document_id":"p2","doc_role":"experimental","candidate_materials":
["Ti-6Al-4V"],"candidate_processes":["surface treatment"],"changed_variables":
["surface roughness"],"candidate_properties":["corrosion resistance"],
"possible_objectives":["How does surface roughness affect corrosion resistance of Ti-6Al-4V?"]}]}
Output:
{"objectives":[{"question":"How does aging temperature affect yield strength of Ti-6Al-4V?","material_scope":["Ti-6Al-4V"],"process_axes":["heat treatment","aging temperature"],"property_axes":["yield strength"],"comparison_intent":"Compare yield strength across aging temperatures.","seed_document_ids":["p1"],"excluded_document_ids":["p2"],"confidence":0.9,"reason":"Only p1 supports the aging-temperature and yield-strength relationship."},{"question":"How does surface roughness affect corrosion resistance of Ti-6Al-4V?","material_scope":["Ti-6Al-4V"],"process_axes":["surface treatment","surface roughness"],"property_axes":["corrosion resistance"],"comparison_intent":"Compare corrosion resistance across surface roughness conditions.","seed_document_ids":["p2"],"excluded_document_ids":["p1"],"confidence":0.9,"reason":"Only p2 supports the surface-roughness and corrosion relationship."}]}

3. Review or insufficient candidates
Input:
{"collection_id":"c3","paper_skims":[{"document_id":"p1","doc_role":"review",
"candidate_materials":["316L stainless steel"],"candidate_processes":["LPBF"],
"changed_variables":[],"candidate_properties":["corrosion behavior"],
"possible_objectives":[]},{"document_id":"p2","doc_role":"uncertain",
"candidate_materials":[],"candidate_processes":[],"changed_variables":[],
"candidate_properties":[],"possible_objectives":[]}]}
Output:
{"objectives":[]}

OUTPUT CONTRACT
Return exactly one top-level key: `objectives`. Each objective must contain
exactly these keys: `question`, `material_scope`, `process_axes`,
`property_axes`, `comparison_intent`, `seed_document_ids`,
`excluded_document_ids`, `confidence`, and `reason`. Empty `objectives` is the
only reject form. The response ends immediately after the JSON object.
""".strip()


_RESEARCH_AXIS_CANONICALIZATION_SYSTEM_PROMPT = """
TASK MODEL
You normalize labels already attached to discovered research objectives. Group
only equivalent material, process, or property labels. This is label
canonicalization, not objective discovery, merge, extraction, or synthesis.

INPUT SCHEMA
- `axis_candidates.material`, `.process`, and `.property` contain the complete
  allowed labels for each axis type.
- `paper_skims` supplies collection context only. It cannot supply new labels.

DECISION PROCESS
1. Process each axis type independently.
2. Group only spelling, acronym, singular/plural, or wording variants that name
   the same scientific axis.
3. Copy one alias as `canonical`; never invent a normalized label.
4. Keep uncertain or scientifically distinct labels in separate groups.
5. Ensure every input label appears exactly once in its own axis type.

HARD RULES
- Return exactly one JSON object with one top-level key: `axis_groups`.
- Never mix axis types or return labels absent from `axis_candidates`.
- Return no analysis, markdown, copied input, or extra fields.

OUTPUT CONTRACT
Use `{"axis_groups":[]}` when there are no labels. Each group contains exactly
`axis_type`, `canonical`, `aliases`, `confidence`, and `reason`.
""".strip()


_RESEARCH_OBJECTIVE_MERGE_SYSTEM_PROMPT = """
TASK MODEL
You decide whether already-discovered research objectives represent the same
material-process-property comparison. This is objective merge, not discovery,
axis canonicalization, evidence extraction, or synthesis.

INPUT SCHEMA
- `candidate_objectives` contains the only objectives and ids that may be
  returned.
- `paper_skims` provides paper-level context for merge decisions only.

DECISION PROCESS
1. Compare material scope, changed process variables, measured properties, and
   comparison intent.
2. Merge only candidates expressing the same relationship. Keep different
   research directions separate.
3. Preserve a singleton group when no merge is justified.
4. Assign every candidate id to exactly one output group.

HARD RULES
- Return exactly one JSON object with one top-level key: `merged_objectives`.
- Copy every `source_objective_id` from the input and never invent axes.
- Return no analysis, markdown, copied input, or extra fields.

OUTPUT CONTRACT
Use `{"merged_objectives":[]}` only for an empty candidate list. Every group
contains exactly the fields required by the supplied JSON schema.
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
TASK MODEL
You classify one `current_source` unit for later objective-scoped evidence
extraction. This is source routing, not extraction, summarization, or synthesis.

INPUT SCHEMA
- `objective` is the active research question and requested axes.
- `objective_context.target_property_axes` are outcomes that answer the goal;
  `mediator_axes` are explanatory unless explicitly linked to a target outcome.
- `paper_frame` states the paper's relevance and useful sections/tables.
- `tree_position` locates the current unit in the paper.
- `document_state` contains evidence already retained from earlier units.
- `current_source` is the only unit to classify.

DECISION PROCESS
1. Reject references, literature summaries, composition-only content, and units
   unrelated to the active objective.
2. Use `current_experimental_evidence` for current-paper target results, trends,
   comparisons, or explicit author interpretations.
3. Use `process_or_treatment` or `test_condition` for source units needed to
   bind variables, samples, methods, or environments.
4. Use `characterization` for objective-relevant microstructure, defect, phase,
   morphology, or grain observations.
5. Return one selection only when later extraction is useful; otherwise reject.

HARD RULES
- Return exactly one JSON object with one top-level key: `selections`.
- A selection contains only `role`, `extractable`, and `confidence`.
- Do not return source ids, source text, explanations, schemas, results, or
  copied input.

BOUNDARY EXAMPLES
- A Results paragraph comparing elongation before and after preheating returns
  `current_experimental_evidence` with `extractable: true`.
- A Methods paragraph giving build-platform temperature returns
  `process_or_treatment` with `extractable: true`.
- A bibliography entry or unrelated composition paragraph returns
  `{"selections":[]}`.

OUTPUT CONTRACT
Return either `{"selections":[]}` or one compact selection. The response ends
immediately after the JSON object.
""".strip()


_OBJECTIVE_EVIDENCE_SYSTEM_PROMPT = """
TASK MODEL
You extract at most one objective-relevant fact from one selected source unit.
This is evidence extraction, not routing, paper summarization, or Finding
synthesis.

INPUT SCHEMA
- `objective` and `objective_context` define the target relationship.
- `paper_frame` supplies bounded paper-level material, variable, and property
  context.
- `evidence_route.role` states why this source was selected.
- `tree_position` and `document_state` provide local continuity but cannot
  override the current source.
- `source` is the only authority for the returned fact. Table cells are the
  authoritative table structure when present.
- The objective and paper frame are not factual evidence. Earlier retained
  evidence in `document_state` may bind context only when it contains the exact
  reported value or label.

DECISION PROCESS
1. Verify that `source` supports the active objective and route role.
2. Select the single strongest target measurement, comparison, condition,
   process context, characterization, or interpretation.
3. Bind the property, value or trend, material/sample/process context, test
   condition, and comparison keys only when explicitly supported.
4. Use `resolved` only when the source binds the fact sufficiently; otherwise
   use `partial` or reject with an empty array.
5. Prefer an empty result over a speculative or literature-derived fact.

HARD RULES
- Return exactly one JSON object with one top-level key: `extractions`.
- Return at most one extraction and no hidden reasoning.
- Do not return source refs, evidence ids, copied source text, or copied input.
- A measurement must include a numeric or qualitative result in
  `value_payload`.
- Every non-empty context value must appear in `source` or exact retained
  evidence. Never infer sample ids, standards, orientations, temperatures,
  process names, or baseline labels from domain conventions.

BOUNDARY EXAMPLES
- A row reporting non-preheated/preheated elongation of 72/82% may return one
  `measurement` with `property_normalized: "elongation"` and both comparison
  values in `value_payload`; unrelated context dictionaries remain empty.
- A paragraph reporting only a build-platform temperature may return one
  `process_context` extraction.
- A bibliography entry, unsupported inference, or unrelated result returns
  `{"extractions":[]}`.

OUTPUT CONTRACT
Return `{"extractions":[]}` or one compact schema-valid extraction. Omit
unsupported optional content and end immediately after the JSON object.
""".strip()


_FINDING_SYNTHESIS_SYSTEM_PROMPT = """
TASK MODEL
You are the cross-paper evidence judge for one relationship within a
materials-literature goal. Evaluate the supplied result set using evidence
already extracted from the candidate papers. Produce one final Finding for
materials experts. This is
evidence synthesis, not source extraction, routing, paper-by-paper generation,
field clustering, or a general literature summary.

INPUT SCHEMA
- `objective`: the user question and requested material, process, and property
  axes.
- `result_sets`: backend-aligned candidate Findings. A result set groups direct
  results for one relationship. `result_set_id` identifies that candidate;
  `source_axes` names changed variables; `outcome_properties` names measured
  properties. `direct_evidence` contains the exact source excerpts and structured
  results that can support the Finding. `contradictory_evidence` contains only
  candidate opposing results for the same relationship.
- `paper_contributions`: bounded paper metadata and changed/measured axes. It may
  help judge comparability but cannot replace direct evidence.
- `context_evidence`: bounded condition, comparison, mechanism, and baseline
  excerpts. It may qualify or explain a Finding but cannot increase the
  contributing paper count or create an outcome.

DECISION PROCESS
1. Read the objective and ignore relationships that do not answer it.
2. Evaluate the supplied `result_set`. If it answers the objective, emit at
   most one Finding and copy its `result_set_id`. Keep its linked measured
   outcomes together; never emit one Finding per result unit.
3. Build `source_concept` from `source_axes` only. Put fixed values in
   `common_conditions`. When several variables change together, retain the
   coupled variable set instead of naming one isolated cause.
4. Create exactly one outcome for each distinct `outcome_properties` value.
   The outcome `concept` must equal that property, never a source axis. The
   backend binds all matching direct-result ids. List an id only in
   `conflicting_evidence_ids` when its result explicitly opposes the
   outcome direction. Copy calibrated values and units into the statement.
5. Compare contributing papers by material, process, changed variables, sample
   state, baseline, measurement method, and test conditions. Use
   `condition_dependent` for overlapping but non-identical source axes or for an
   explicit condition boundary. Use `conflict` only for opposing comparable
   results.
6. Use `context_evidence` only for explicit qualifications and mechanisms.
   Follow `evidence_role`: `mechanism_context` may supply mediator concepts;
   other context roles may only qualify scope or comparability.
7. Write one concise composite statement. Report structural or defect outcomes
   before performance outcomes. Preserve decisive values and explicit regime
   limits without strengthening association into causation.
8. Count only papers whose direct-result ids are assigned to an outcome. Return
   one Finding or an empty array.

HARD RULES
- Return exactly one JSON object and nothing else.
- Conflict ids must come from the selected result set's
  `contradictory_evidence`; context/mechanism ids must come from
  `context_evidence`. Never invent ids or papers.
- Never combine direct-result ids from separate `result_sets` in one Finding.
  A Finding's direct ids must all belong to its copied `result_set_id`.
- One Finding must preserve all goal-relevant outcomes aligned in its result set.
  Do not split one property into one outcome per paper or measurement.
- Create outcomes only for `outcome_properties` backed by at least one direct
  result id. Never turn `context_evidence` into an unsupported outcome.
- The backend binds all matching direct-result ids as support. Return only
  explicit opposing ids in `conflicting_evidence_ids`; an id for one
  property must not be attached to another outcome.
- `source_concept` must cover only the result set's `source_axes`. Controlled
  axes belong in conditions. A grouping label may qualify a coupled parameter
  set but must not replace its changed axes or become an isolated cause.
- Paper contributions cannot count as results and cannot supply evidence ids.
- Use `context_evidence_ids` for source-explicit qualifications and author
  interpretations. Use `mechanism_evidence_ids` only when the excerpt
  explicitly supports the returned mediator. Neither list counts as direct
  support or cross-paper confirmation.
- Context and mechanism id lists must be disjoint. When mechanism ids are
  present, name their supported concepts in `mediator_concepts`; otherwise keep
  those ids as context.
- Include goal-relevant document context when it directly qualifies an outcome
  or explains an observed mechanism. Do not silently discard an explicit
  regime limitation. If an outcome stayed in a narrow range, use that
  qualification instead of foregrounding a small endpoint delta.
- A single-paper composite statement must say that it is directly supported by
  one paper and use `insufficient_confirmation`.
- Do not use `significant`, `significantly`, `statistically significant`, or
  `no significant effect` unless a supporting source explicitly reports that
  statistical conclusion. A small numeric difference alone is not a
  significance test; report the measured values instead.
- Do not convert association into control or causation.
- If no goal-relevant direct result exists, return an empty `findings` array.

BOUNDARY EXAMPLES
- `result_set_1` has source axes `laser power, scan speed`, outcome property
  `density`, and one density id from each of two papers. Return one Finding with
  `result_set_id: result_set_1`, source concept `laser power and scan speed`, one
  `density` outcome, and no conflict ids. The backend attaches both supporting
  ids. If each paper changed a different subset of the axes, use
  `condition_dependent`, not isolated-variable agreement.
- One paper reports a direct result and another only describes a method: return
  `insufficient_confirmation`; do not cite the method unit as support.
- Two papers report different directions and the difference follows explicit
  heat-treatment or test conditions: return `condition_dependent` and state the
  boundary. Reserve `conflict` for opposing results that remain comparable.
- Power, speed, and hatch spacing all change between samples: use the coupled
  parameter set as `source_concept`, not power alone.
- One result set has outcomes `defect size`, `LCF strength`, and `HCF limit`:
  return one Finding with exactly those three outcomes. Do not return three
  Findings or use `laser power` as an outcome.

OUTPUT CONTRACT
Return `findings` only. Each Finding copies `result_set_id` and contains
`source_concept`, `outcomes`, an expert-readable statement, optional
mediators/context/mechanism, conditions, status, confidence, and warnings. Use
exact input ids, empty arrays when absent, and no hidden reasoning or extra keys.
""".strip()


_TABLE_MATRIX_REPAIR_SYSTEM_PROMPT = """
You are repairing parsed table structure for a materials-literature backend.

Non-negotiable rules:
- This is table repair only, not fact extraction.
- Return exactly one JSON object and nothing else.
- Use only the provided table source; do not use outside knowledge.
- Preserve the table's row order, column order, numeric values, units, and headers.
- Repair fragmented cells, dangling parentheses/brackets, and row-label spillover only when supported by nearby table cells.
- If repair is uncertain, preserve the original cell and add a warning.
""".strip()


_TEXT_WINDOW_JSON_COMPLIANCE_GUIDANCE = """
JSON compliance rules for text-window extraction:
- Use exactly the schema keys and no others. Do not add keys like `keywords`, `notes`, `warnings`, `anchors`, or `measurement_results`.
- Arrays must stay arrays. When empty, use `[]`. Never use `null` for top-level mention arrays.
- `evidence_quote` is required on every emitted item.
- `evidence_quote` must be an exact contiguous substring copied from `text_window.text`.
- Do not paraphrase, shorten with ellipses, or merge non-contiguous spans.
- Do not emit page, source_type, section_id, block_id, snippet_id, figure_or_table, char_range, bbox, or deep_link.
- Do not emit final `measurement_results` in this stage.
- Classify every `result_claim` with `claim_scope`.
- Only set `eligible_for_measurement_result` to true when the claim is an explicit current-work result.
- `method_role` must be one of: process, characterization, test, other. If none fit exactly, use `other`.
- `condition_type` must be one of: temperature, duration, atmosphere, rate, frequency, location, direction, other. If none fit exactly, use `other`.
- `baseline_type` must be one of: control, untreated, as-built, reference, without-treatment, other. If none fit exactly, use `other`.
- `claim_scope` must be one of: current_work, prior_work, literature_summary, review_summary, unclear. If unsure, use `unclear`.
- Use confidence between 0.5 and 1.0. Do not emit facts below 0.5 confidence.

Valid result claim example:
```json
{
  "claim_text": "Residual stress was similarly reduced when annealing was only performed once every 5 layers.",
  "property_normalized": "residual stress",
  "result_type": "trend",
  "value_text": null,
  "unit": null,
  "claim_scope": "current_work",
  "eligible_for_measurement_result": true,
  "evidence_quote": "the residual stress was similarly reduced",
  "confidence": 0.85
}
```

Valid condition mention example:
```json
{
  "condition_type": "temperature",
  "condition_text": "tested at 25 C",
  "normalized_value": 25,
  "unit": "C",
  "evidence_quote": "tested at 25 C",
  "confidence": 0.9
}
```

Invalid counterexamples. Do not copy these shapes:
```json
{
  "keywords": ["yield strength"],
  "method_mentions": [],
  "material_mentions": [],
  "variant_mentions": [],
  "condition_mentions": [],
  "baseline_mentions": [],
  "result_claims": []
}
```

```json
{
  "result_claims": [
    {
      "claim_text": "Previous work demonstrated over 90% reduction.",
      "property_normalized": "residual stress",
      "result_type": "trend",
      "value_text": "over 90%",
      "unit": "%",
      "claim_scope": "current_work",
      "eligible_for_measurement_result": true,
      "evidence_quote": "Previous work demonstrated over 90% reduction.",
      "confidence": 0.85
    }
  ]
}
```

```json
{
  "result_claims": [
    {
      "claim_text": "Yield strength reached 560 MPa.",
      "property_normalized": "yield strength",
      "result_type": "scalar",
      "value_text": "560 MPa",
      "unit": "MPa",
      "claim_scope": "current_work",
      "eligible_for_measurement_result": true,
      "evidence_quote": "yield strength reached ... 560 MPa",
      "confidence": 0.85
    }
  ]
}
```
""".strip()


_TABLE_BATCH_JSON_COMPLIANCE_GUIDANCE = """
JSON compliance rules for this extraction:
- Use exactly the schema keys and no others. Do not add keys like `keywords`, `notes`, or `warnings`.
- Arrays must stay arrays. When empty, use `[]`. Never use `null` for top-level lists.
- Extract only lightweight row mentions grouped under `row_results`. Do not emit final backend artifacts.
- Do not emit `method_facts`, `sample_variants`, `test_conditions`, `baseline_references`, or `measurement_results`.
- Do not emit `confidence`, `epistemic_status`, `anchors`, `source_type`, `page`, `process_context`, `condition_payload`, `value_payload`, backend ids, or refs.
- Every `row_results[*]` item must include a `row_index` copied from one of the provided `target_rows`.
- Put process facts in `process_mentions` using exact names such as `laser_power_w`, `scan_speed_mm_s`, `layer_thickness_um`, `hatch_spacing_um`, `energy_density_j_mm3`, `build_orientation`, `post_treatment_summary`, `temperature_c`, `duration`, or `atmosphere`.
- Put test facts in `test_condition_mentions` using exact names such as `method`, `test_method`, `test_temperature_c`, `strain_rate_s-1`, `loading_direction`, `sample_orientation`, `environment`, or `frequency_hz`.
- Put result values in `result_claims[*].value_text` and `result_claims[*].unit`.
- Omit weakly grounded PBF fields. Do not infer missing laser power, scan speed, orientations, strain rate, or energy density from general domain knowledge.
- Extract target-row-grounded facts only. Use `table_context` to interpret captions, headers, units, groups, baselines, and row meaning.
- Treat non-target rows inside `table_context.table_matrix`, `table_context.table_markdown`, or `table_context.table_text` as context only. Do not copy their values into facts for a target row.
- Do not mix values across target rows. Put each extracted value under the matching `row_index`.
- Use `supporting_text_windows` only to disambiguate row labels, abbreviations, or column meaning.
- Do not mine `supporting_text_windows` for extra standalone facts that are not needed to interpret this row.
- If a fact cannot be grounded to the row or a short disambiguating support quote, omit it.
- Do not repeat the same fact in multiple arrays.
- Keep `quote` short, exact, and contiguous when possible.
- Classify every `result_claim` with `claim_scope`.
- Only use `claim_scope: "current_work"` for directly attributable current-paper results.
- Emit at most 2 `row_subjects`, 8 `process_mentions`, 8 `test_condition_mentions`, 2 `baseline_mentions`, and 4 `result_claims` for one row result.
- If evidence is weak or absent for a target row, include that `row_index` with empty arrays.

Valid PBF metal row example:
```json
{
  "row_results": [
    {
      "row_index": 3,
      "row_subjects": [
        {
          "variant_label": "S3",
          "family": "titanium alloy",
          "composition": "Ti-6Al-4V",
          "variable_axis_type": "post_treatment",
          "variable_value": "optimized VED + HIP",
          "quote": "S3"
        }
      ],
      "process_mentions": [
        {
          "name": "laser_power_w",
          "value_text": "280",
          "unit": "W",
          "quote": "280 W"
        },
        {
          "name": "scan_speed_mm_s",
          "value_text": "1200",
          "unit": "mm/s",
          "quote": "1200 mm/s"
        },
        {
          "name": "post_treatment_summary",
          "value_text": "HIP",
          "unit": null,
          "quote": "HIP"
        }
      ],
      "test_condition_mentions": [
        {
          "name": "test_method",
          "value_text": "tensile",
          "unit": null,
          "quote": "tensile"
        },
        {
          "name": "test_temperature_c",
          "value_text": "25",
          "unit": "C",
          "quote": "25 C"
        }
      ],
      "baseline_mentions": [
        {
          "baseline_label": "S2",
          "quote": "S2"
        }
      ],
      "result_claims": [
        {
          "property_normalized": "yield_strength",
          "result_type": "scalar",
          "value_text": "940",
          "unit": "MPa",
          "variant_label": "S3",
          "baseline_label": "S2",
          "claim_scope": "current_work",
          "claim_text": "S3 showed a yield strength of 940 MPa at 25 C.",
          "quote": "S3 showed a yield strength of 940 MPa at 25 C"
        }
      ]
    }
  ]
}
```

Valid measurement result example:
```json
{
  "row_results": [
    {
      "row_index": 1,
      "row_subjects": [],
      "process_mentions": [],
      "test_condition_mentions": [],
      "baseline_mentions": [],
      "result_claims": [
        {
          "property_normalized": "yield strength",
          "result_type": "scalar",
          "value_text": "560",
          "unit": "MPa",
          "variant_label": null,
          "baseline_label": null,
          "claim_scope": "current_work",
          "claim_text": "Yield strength reached 560 MPa.",
          "quote": "yield strength reached 560 MPa"
        }
      ]
    }
  ]
}
```

Invalid counterexamples. Do not copy these shapes:
```json
{
  "keywords": ["yield strength"],
  "row_results": []
}
```

```json
{
  "row_results": [
    {
      "row_index": 3,
      "row_subjects": [
        {
          "variant_label": "S3",
          "confidence": 0.86,
          "epistemic_status": "normalized_from_evidence"
        }
      ],
      "process_mentions": [],
      "test_condition_mentions": [],
      "baseline_mentions": [],
      "result_claims": []
    }
  ]
}
```

```json
{
  "measurement_results": [
    {
      "property_normalized": "yield_strength",
      "value_payload": {"value": 940}
    }
  ]
}
```
""".strip()


def build_document_profile_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "Classify this document for lightweight Core document triage.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data. Do not add any explanation."
    )
    return _DOCUMENT_PROFILE_SYSTEM_PROMPT, user_prompt


def build_text_window_extraction_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    objective_guidance = _build_objective_context_guidance(payload)
    user_prompt = (
        "Extract atomic research mentions from this one bounded document window.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Extract only directly stated information from `text_window.text`.\n"
        "Do not infer from filename, title, heading text, citation numbers, or general domain knowledge.\n"
        "Return only atomic mentions in this stage: method_mentions, material_mentions, "
        "variant_mentions, condition_mentions, baseline_mentions, and result_claims.\n"
        "Do not emit anchors.\n"
        "For every emitted item, output `evidence_quote` only.\n"
        "Do not emit final `measurement_results` in this stage.\n"
        "Do not bind results to variants or baselines unless the text explicitly states the relation.\n"
        "Do not treat previous work, citations, or literature background as current-work results.\n"
        "Do not emit test-condition semantics for characterization methods alone.\n\n"
        f"{objective_guidance}"
        f"{_TEXT_WINDOW_JSON_COMPLIANCE_GUIDANCE}"
    )
    return _COMMON_SYSTEM_PROMPT, user_prompt


def build_table_batch_mentions_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    objective_guidance = _build_objective_context_guidance(payload)
    user_prompt = (
        "Extract target-row-grounded lightweight mentions for this batch using the provided table context.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Use `table_context` to interpret the target rows' caption, headers, units, "
        "matrix, row groups, and table-wide labels. Non-target rows are context only; do not "
        "extract their values as target-row facts. Skip outputs when a target row is a literature "
        "summary rather than a directly attributable study row. Do not mix values across "
        "target rows. Do not emit backend "
        "artifacts, locators, ids, or bundle refs. Use human-readable labels when a "
        "result must identify a variant or baseline. Return mentions only, not "
        "reader-facing cards.\n"
        "Use `supporting_text_windows` only when they are required to interpret a row.\n"
        "If a row is mostly metadata, labels, or literature summary text, return that "
        "row_index with empty arrays instead of expanding speculative outputs.\n\n"
        f"{objective_guidance}"
        f"{_TABLE_BATCH_JSON_COMPLIANCE_GUIDANCE}"
    )
    return _COMMON_SYSTEM_PROMPT, user_prompt


def build_table_matrix_repair_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "Repair this parsed table matrix before objective evidence extraction.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with `repaired_table_matrix`, "
        "`repairs`, `confidence`, and `warnings`.\n"
        "Repair structure only. Do not extract measurements, comparisons, or "
        "interpretations.\n"
        "`repaired_table_matrix` must keep the same logical columns as "
        "`source.column_headers` and should keep the header row when present in "
        "`source.table_matrix`.\n"
        "Use `source.table_cells` to identify parser-split cells by row_index, "
        "col_index, header_path, and cell_text. Nearby row labels can support "
        "repairs such as `as-SLM (100/` plus following `100)` fragments becoming "
        "`as-SLM (100/100)` and `100) HT-SLM (100/` becoming "
        "`HT-SLM (100/100)`. Preserve numeric result cells exactly.\n"
        "Cross-row specimen-label repair examples:\n"
        "- Input row: [`as-SLM (100/`, `-`, `100`, `100`, `278`, `97.83`] -> "
        "[`as-SLM (100/100)`, `-`, `100`, `100`, `278`, `97.83`].\n"
        "- Input row: [`100) HT-SLM (100/`, `Furnace HT`, `100`, `100`, `278`, "
        "`98.70`] -> [`HT-SLM (100/100)`, `Furnace HT`, `100`, `100`, `278`, "
        "`98.70`].\n"
        "- Input row: [`100) HIP-SLM (100/`, `HIP`, `100`, `100`, `278`, "
        "`98.15`] -> [`HIP-SLM (100/100)`, `HIP`, `100`, `100`, `278`, "
        "`98.15`].\n"
        "Do not output labels like `100) HT-SLM (100/100)` or "
        "`100) HIP-SLM (100/100)`: the leading `100)` is a carried-over "
        "closing fragment from the previous row label, not part of the current "
        "specimen name.\n"
        "Record each changed cell in `repairs` with its row_index, column, before, "
        "after, and reason. If no confident repair is possible, return the original "
        "matrix and explain the uncertainty in `warnings`."
    )
    return _TABLE_MATRIX_REPAIR_SYSTEM_PROMPT, user_prompt


def _build_objective_context_guidance(payload: dict[str, Any]) -> str:
    objective_context = payload.get("objective_context")
    if not isinstance(objective_context, dict) or not objective_context:
        return ""
    routes = objective_context.get("routing_hints")
    route = routes[0] if isinstance(routes, list) and routes else {}
    role = route.get("role") if isinstance(route, dict) else None
    route_guidance = ""
    if role == "result_table":
        route_guidance = (
            "- The active table route is `result_table`: extract only target-row "
            "result claims that match `objective_context.target_property_axes`.\n"
        )
    elif role == "condition_context":
        route_guidance = (
            "- The active table route is `condition_context`: extract row subjects, "
            "process mentions, test-condition mentions, and baselines needed for "
            "binding, and avoid result claims unless a target property is explicitly "
            "reported in the target row.\n"
        )
    return (
        "Objective-context rules:\n"
        "- Treat `objective_context.focus` as the current research lens.\n"
        "- Treat `objective_context.target_property_axes` as outcomes that answer "
        "the objective, `mediator_axes` as explanatory intermediate concepts, "
        "`process_context_axes` and `material_scope` as binding scope, and "
        "`excluded_property_axes` as out-of-lens properties.\n"
        "- Prefer facts that connect `objective_context.variable_process_axes` to "
        "`objective_context.target_property_axes` for that lens.\n"
        "- Do not treat a mediator or context-only observation as a target result "
        "unless the source explicitly links it to a target outcome.\n"
        "- If `objective_context.material_scope` identifies one clear material "
        "system, populate emitted evidence records' `material_system.family` with "
        "that material unless the source explicitly states a different material.\n"
        "- Treat `objective_context.process_context_axes` as process context, not "
        "as changed variables unless the input explicitly compares them.\n"
        "- Do not emit result claims for `objective_context.excluded_property_axes` "
        "or for unrelated properties outside the current lens.\n"
        f"{route_guidance}\n"
    )


def build_paper_skim_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "Evaluate this compact paper input using the PaperSkim contract.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )
    return _PAPER_SKIM_SYSTEM_PROMPT, user_prompt


def build_research_objective_discovery_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Select and bind research-objective candidates using the contract.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )
    return _RESEARCH_OBJECTIVE_DISCOVERY_SYSTEM_PROMPT, user_prompt


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
        "- Do not mix axis types. A material alias may only group with material "
        "aliases; process only with process; property only with property.\n"
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
    return _RESEARCH_AXIS_CANONICALIZATION_SYSTEM_PROMPT, user_prompt


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
        "- Do not invent new source ids, material_scope values, process_axes, or "
        "property_axes. Merged axes must come from the candidate objectives or "
        "paper skims.\n"
        "- If an objective should not be merged, return a group with only that "
        "single source id.\n"
        "- Merge objectives only when they are the same research question split "
        "by a variable axis or by a subset of closely related property endpoints.\n"
        "- Do not merge objectives whose `property_axes` are disjoint. Disjoint "
        "property axes usually mean different research directions.\n"
        "- Do not merge different research directions. For example, keep "
        "densification/microstructure separate from mechanical properties unless "
        "the candidate objectives explicitly frame them as one comparison.\n"
        "- Keep composition/background/literature-comparison objectives separate "
        "from current-work performance objectives.\n"
        "- If uncertain, keep objectives separate.\n"
        "For each output group, write a question-shaped `question`, a non-empty "
        "`comparison_intent`, and a short `reason` explaining why the sources "
        "were merged or kept separate.\n"
    )
    return _RESEARCH_OBJECTIVE_MERGE_SYSTEM_PROMPT, user_prompt


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
        "Use the current `objective` and `objective_context` as the research lens.\n"
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
        "Return only schema-valid structured data with a `selections` array.\n"
        "Return at most one route for `current_source`. If it is not useful "
        "for later objective-scoped extraction, return `{\"selections\": []}`.\n"
        "Each route may contain only `role`, `extractable`, and `confidence`. "
        "Do not return `source_kind`, `source_ref`, ids, copied source text, "
        "explanations, or any nested input object.\n"
        "`role` must be one of: current_experimental_evidence, "
        "process_or_treatment, test_condition, composition_or_background, "
        "characterization, literature_comparison, modeling_or_prediction, "
        "low_value_or_irrelevant.\n"
        "Use the objective context to decide whether `current_source` is direct "
        "target-outcome evidence, mediator/context evidence, or irrelevant. "
        "Treat `target_property_axes` as the only outcome axes that answer the "
        "objective. Treat `mediator_axes` as explanatory context unless the "
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
    user_prompt = (
        "Extract objective-scoped evidence from this one selected source.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with an `extractions` array.\n"
        "Return at most one high-confidence extraction. If the source "
        "contains many possible facts, choose the ones most directly tied to "
        "the active objective and route role.\n"
        "The backend binds `source_refs` from the active route. Do not output "
        "`source_refs`, `evidence_anchor_ids`, backend ids, copied source text, "
        "or copied input JSON.\n"
        "`evidence_kind` must be one of: measurement, test_condition, sample_context, "
        "process_context, characterization, baseline_reference, comparison, "
        "interpretation, mixed, unknown.\n"
        "Use `measurement` for target property results, `test_condition` for "
        "test environments or standards, `sample_context` / `process_context` "
        "for sample and process-variable bindings, `characterization` for "
        "microstructure/defect/phase observations, `comparison` for explicit "
        "within-paper or cross-paper comparison claims, and `interpretation` "
        "for author explanations tied to this objective.\n"
        "For a table route with role `current_experimental_evidence`, return "
        "only the single strongest target result cell if model extraction is "
        "needed; deterministic table parsing handles broad row extraction.\n"
        "For tables, preserve row-level sample/process/test/value bindings in "
        "`sample_context`, `process_context`, `test_condition`, `value_payload`, "
        "and `join_keys`. For text, use exact supported statements from the "
        "provided source text.\n"
        "For text routes, return at most one extraction: the strongest "
        "objective-relevant measurement, process/test context, characterization, "
        "comparison, or interpretation. Do not enumerate every possible number "
        "or secondary observation in the paragraph.\n"
        "Good text example: `1.43x10^6 C/s for P150, and 1.65x10^6 C/s for NP` "
        "should produce only the most objective-relevant one of those bindings "
        "for this route, not two separate extractions.\n"
        "Bad text example: returning separate extractions for every numeric "
        "value in one paragraph or copying the whole paragraph into "
        "`value_payload`.\n"
        "When `source.table_cells` is present, use each cell's `row_index`, "
        "`col_index`, `header_path`, and `cell_text` as the authoritative table "
        "structure. Use nearby cells and rows to repair parser-split row labels "
        "or dangling fragments, but do not use outside knowledge.\n"
        "For `measurement`, always put the numeric or qualitative result "
        "value/trend in `value_payload`; do not emit a measurement with only "
        "property and context fields.\n"
        "Do not extract composition-only, literature-summary, or unrelated facts "
        "unless the active route role explicitly requires them.\n"
        "Do not emit an extraction if its property, context, value, and "
        "interpretation fields would all be empty.\n"
        "`resolution_status` should be resolved only when source, sample/process "
        "context, and value or condition are sufficiently bound; otherwise use "
        "partial or unresolved."
    )
    return _OBJECTIVE_EVIDENCE_SYSTEM_PROMPT, user_prompt


def build_finding_synthesis_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    input_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    user_prompt = (
        "Synthesize the final Findings for this research goal from the aligned "
        "result sets.\n\n"
        f"Input JSON:\n{input_json}\n\n"
        "Return only schema-valid structured data with a `findings` array.\n"
        "Return at most one Finding for the supplied result set.\n"
        "Compare its cited direct "
        "evidence by document and condition before choosing `synthesis_status`:\n"
        "- `agreement`: at least two independent papers provide comparable direct "
        "results with the same scientific direction.\n"
        "- `conflict`: independent papers provide opposing direct results under "
        "comparable or overlapping conditions.\n"
        "- `condition_dependent`: at least two papers provide direct results whose "
        "difference is tied to explicit material, process, or test conditions.\n"
        "- `insufficient_confirmation`: only one paper provides a direct result, or "
        "the available papers cannot independently confirm the relationship.\n"
        "Keep all outcomes from one coherent result set inside one Finding. Follow "
        "the system rules for conflict ids, coupled variables, and scope. If no "
        "Finding meets them, return "
        "`{\"findings\": []}`."
    )
    return _FINDING_SYNTHESIS_SYSTEM_PROMPT, user_prompt
