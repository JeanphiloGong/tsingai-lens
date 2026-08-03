from __future__ import annotations

import json
from typing import Any


FINDING_SYNTHESIS_PROMPT_VERSION = "finding_synthesis.v4"


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
You are extracting objective-scoped evidence for an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is final evidence extraction for one research objective and one selected source.
- Return exactly one JSON object and nothing else.
- Extract only facts directly supported by `source`; do not use outside knowledge.
- Use the `objective` and `evidence_route` as the research scope.
- Do not emit backend persistence ids.
- The backend binds the exact source excerpt and Source locators from the active route/source.
- Do not output source refs, evidence anchor ids, backend ids, source excerpts, or copied input JSON.
- `document_state` is coverage metadata only. It is not scientific source text;
  never copy prior values or context into the current extraction.
- Classify the final evidence role from the active source; the route role is only a selection hint.
- Preserve every factor that changes between compared groups. Never choose one
  convenient variable when scan speed, hatch spacing, energy density, treatment,
  sample state, or test regime change together.
- Keep fixed material, sample, process, and test conditions in scientific_context;
  fixed conditions are not changed variables.
- A direct or contradictory result must bind exactly one objective outcome to one
  reported result from this source.
- Every changed variable should include a source-reported baseline or target value.
  For categorical comparisons, use the exact source group labels as endpoints when
  numeric values are absent. Omit a variable when no endpoint is present in source.
- `isolated_effect` and `joint_effect` require a comparable `comparison` whose
  axis names exactly match the changed variables and whose baseline and target
  values are both present.
- Context roles must return `reported_result: null`, empty changed variables,
  and `not_attributable`; use a result role when the source reports a result.
- Use isolated_effect only for one changed variable in a comparable experiment.
  Use joint_effect for two or more jointly varied factors, association_only for
  non-isolating associations, descriptive_only without an effect comparison, and
  not_attributable when groups are scientifically incomparable.
- Prefer fewer, traceable extractions over broad speculative coverage.
- Return at most one extraction for the current source.
- Always include a numeric `confidence` after `resolution_status` for every extraction.
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
  `outcome`, and `result_evidence`. Every result Evidence has the exact source
  excerpt, explicit changed variables, comparison, reported result,
  attribution scope, scientific context, and paper id.
- `paper_contributions`: every paper considered in this Objective analysis,
  including analyzed papers without a direct result and excluded or failed
  papers. Paper metadata can qualify judgment but cannot become Evidence.
- `context_evidence`: bounded condition, comparison, mechanism, and baseline
  excerpts from papers in this result set. Context cannot create factors,
  outcomes, directions, or supporting papers.

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
5. Use context Evidence only for explicit limitations and mechanisms. Every
   mechanism must be a subordinate relation backed by `mechanism_context`
   Evidence and those ids must also appear in `context_evidence_ids`.
6. Write one concise statement containing every factor and the one outcome.
   Do not mention any Objective variable absent from `result_set.factors`.
   Preserve decisive values and limits, distinguish support from contradiction,
   and do not strengthen association into single-variable causation. Every
   numeric endpoint in the statement must come from one complete supporting
   Evidence comparison; never combine endpoints from different Evidence rows.

HARD RULES
- Return exactly one JSON object and nothing else.
- Return at most one Finding and copy `result_set_id` exactly.
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
subordinate `mechanisms`, and `limitations`. Use exact input ids for context and
boundaries, empty arrays when absent, and no extra keys.
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
    objective_guidance = _build_objective_guidance(payload)
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
    objective_guidance = _build_objective_guidance(payload)
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


def _build_objective_guidance(payload: dict[str, Any]) -> str:
    objective = payload.get("objective")
    if not isinstance(objective, dict) or not objective:
        return ""
    return (
        "Objective rules:\n"
        "- Treat `objective.outcomes` as the only outcomes that answer the "
        "objective, `objective.mechanisms` as explanatory intermediate concepts, "
        "and `objective.constraints` plus `objective.material_scope` as binding scope.\n"
        "- Prefer facts that connect `objective.variables` to `objective.outcomes`.\n"
        "- Do not treat a mechanism or context-only observation as a target result "
        "unless the source explicitly links it to a target outcome.\n"
        "- If `objective.material_scope` identifies one clear material system, "
        "populate emitted evidence records material family with that material unless "
        "the source explicitly states a different material.\n"
        "- Treat `objective.constraints` as fixed scope, not as changed variables "
        "unless the input explicitly compares them.\n"
        "- Do not emit result claims for properties outside `objective.outcomes`.\n"
    )


def build_paper_skim_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "Extract a compact research map from this one paper.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only the schema object. Use at most a few high-signal values. "
        "Do not extract final measurements. Include process family plus changed "
        "axes, concrete measured properties, and question-shaped objectives."
    )
    return _RESEARCH_OBJECTIVE_SYSTEM_PROMPT, user_prompt


def build_research_objective_discovery_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Create a small set of comparison questions from these compact paper skims.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Return only the schema object with at most six objectives. Keep each "
        "objective question-shaped and focused: name all jointly changed variables "
        "needed for the comparison and only tightly related outcomes. Keep distinct "
        "variable-outcome families separate. Put only explanatory intermediate "
        "concepts explicitly supported by a skim in `mechanisms`; otherwise use an "
        "empty list. Do not put another measured property in `mechanisms`. Put fixed "
        "material, process, sample, and test scope in `constraints`, and an explicitly "
        "requested comparison target in optional `requested_comparator`. Do not copy "
        "every process or property from a paper skim into an objective. Use exact "
        "document_id values for seed/excluded ids. Set `reason` to null unless one "
        "short clause is needed; never explain the field assignment."
    )
    system_prompt = (
        "Build concise research-objective questions for literature comparison. "
        "Use only the supplied skims. Return one JSON object, no commentary."
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
    user_prompt = (
        "Extract objective-scoped evidence from this one selected source.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with an `extractions` array.\n"
        "Return at most one high-confidence extraction. If the source "
        "contains many possible facts, choose the ones most directly tied to "
        "the active objective and route role.\n"
        "The backend binds the exact source excerpt and Source locators from the "
        "active route. Do not output "
        "`source_refs`, `evidence_anchor_ids`, backend ids, copied source text, "
        "or copied input JSON.\n"
        "Treat `document_state` only as a map of prior coverage and Source positions. "
        "Do not extract or copy scientific values from it; every output field must be "
        "supported by the active `source`.\n"
        "Set `evidence_role` from this source's actual content: direct_result, "
        "contradictory_result, mechanism_context, condition_context, baseline_context, "
        "comparison_context, background_context, or irrelevant.\n"
        "For direct_result or contradictory_result, populate exactly one "
        "`reported_result` whose outcome answers `objective.outcomes`. Preserve its "
        "reported value and unit. Set `result_text` to one short verbatim substring "
        "from the active source, not a paraphrase. The direction must describe that "
        "outcome, never an intermediate mechanism; use `mixed` for a qualitative "
        "morphology change with no ordered increase, decrease, improvement, or "
        "worsening.\n"
        "A qualitative observation that directly compares the objective outcome "
        "between source groups is still a direct_result when no scalar is reported: "
        "set reported_result.value and unit to null and preserve the observed outcome "
        "difference in result_text. Do not demote an observed outcome to "
        "mechanism_context.\n"
        "Populate `changed_variables` with every factor that differs between baseline "
        "and target, including each factor's reported baseline/target values and unit. "
        "For a categorical factor without numeric endpoints, copy the exact baseline "
        "and target group labels from source as the variable values. "
        "Do not infer a missing factor from the objective or paper frame.\n"
        "Populate `comparison` only when the source identifies baseline and target "
        "groups. Its axis_names must contain every changed-variable name. Mark "
        "as-SLM/HIP-SLM, different materials, or different test regimes incomparable "
        "when those differences prevent direct attribution, and state why. When "
        "`comparable` is true, `incomparability_reasons` must be empty. Set "
        "`comparable` false only when the active source explicitly reports a "
        "confounding difference between the current baseline and target groups; "
        "conditions from cited literature and unreported fixed conditions are not "
        "incomparability reasons for the current groups.\n"
        "Set attribution_scope to isolated_effect only for one comparable changed "
        "variable; joint_effect for multiple comparable changed variables; "
        "association_only for non-isolating associations; descriptive_only when no "
        "effect comparison is reported; not_attributable for incomparable/context evidence.\n"
        "Store only fixed material, sample, process, and test conditions in "
        "scientific_context as name/value/unit entries.\n"
        "For a table route with role `current_experimental_evidence`, return "
        "only the single strongest target result cell if model extraction is "
        "needed; deterministic table parsing handles broad row extraction.\n"
        "For tables, keep result, baseline, target, changed-variable values, and fixed "
        "context aligned to the same row/column binding. For text, use only statements "
        "supported by the provided source text.\n"
        "For text routes, return at most one extraction: the strongest "
        "objective-relevant result, condition, mechanism, comparison, or background "
        "record. Do not enumerate every possible number "
        "or secondary observation in the paragraph.\n"
        "When one paragraph mixes the authors' current result with cited literature, "
        "extract only the current result and ignore the cited comparison claims.\n"
        "Good text example: `1.43x10^6 C/s for P150, and 1.65x10^6 C/s for NP` "
        "should produce only the most objective-relevant one of those bindings "
        "for this route, not two separate extractions.\n"
        "Bad text example: returning separate extractions for every numeric "
        "value in one paragraph or copying the whole paragraph into "
        "`result_text`.\n"
        "Qualitative result example: a source comparing cellular microstructure in "
        "P150 with NP is direct_result for a microstructure outcome, with categorical "
        "endpoints P150 and NP and a null scalar value; it is not mechanism_context.\n"
        "When `source.table_cells` is present, use each cell's `row_index`, "
        "`col_index`, `header_path`, and `cell_text` as the authoritative table "
        "structure. Use nearby cells and rows to repair parser-split row labels "
        "or dangling fragments, but do not use outside knowledge.\n"
        "Do not extract composition-only, literature-summary, or unrelated facts "
        "unless the active route role explicitly requires them.\n"
        "Do not emit an extraction when reported_result and scientific_context are both empty.\n"
        "`resolution_status` should be resolved only when source, sample/process "
        "context, and value or condition are sufficiently bound; otherwise use "
        "partial or unresolved."
    )
    return _OBJECTIVE_EVIDENCE_SYSTEM_PROMPT, user_prompt


def build_finding_synthesis_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    input_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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
    comparison_contract = ""
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
    if len(factors) > 1:
        factor_phrase = (
            f"{factors[0]} and {factors[1]}"
            if len(factors) == 2
            else f"{', '.join(factors[:-1])}, and {factors[-1]}"
        )
        exact_contract = (
            "Exact contract for this result set:\n"
            f"- The statement must contain every factor verbatim: {required_terms}.\n"
            f"- The statement must contain the outcome verbatim: `{outcome}`.\n"
            "- `assertion_strength` must be `associative`; this is a joint-factor "
            "comparison, never a single-factor causal effect.\n"
            f"- Start the statement with `Joint changes in {factor_phrase} were "
            "associated with` and then state the direction and outcome.\n"
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
