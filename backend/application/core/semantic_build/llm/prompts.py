from __future__ import annotations

import json
from typing import Any


RESEARCH_UNDERSTANDING_RELATION_PROMPT_VERSION = (
    "research_understanding_relation.v1"
)


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


_OBJECTIVE_EVIDENCE_UNIT_SYSTEM_PROMPT = """
You are extracting objective-scoped evidence units for an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is final evidence-unit extraction for one research objective and one routed source.
- Return exactly one JSON object and nothing else.
- Extract only facts directly supported by `source`; do not use outside knowledge.
- Use the `objective`, `objective_context`, and `evidence_route` as the research lens.
- Do not emit backend persistence ids.
- The backend binds `source_refs` from the active route/source.
- Do not output `source_refs`, `evidence_anchor_ids`, backend ids, copied source text, or copied input JSON.
- Prefer fewer, traceable units over broad speculative coverage.
- Return at most one evidence unit for the current source.
""".strip()


_RESEARCH_UNDERSTANDING_RELATION_SYSTEM_PROMPT = """
You are extracting expert-readable research understanding relations for a materials-literature backend.

Non-negotiable rules:
- Return exactly one JSON object and nothing else.
- Extract only relations supported by the provided claims and evidence units.
- Relation endpoints must be scientific concepts, not sample numbers, row ids,
  backend ids, table cell ids, or copied JSON field names.
- Prefer fewer, higher-signal relations over enumerating table rows.
- A relation should help an expert understand why a claim may hold, such as
  process parameter -> defect/microstructure -> property response.
- If the evidence only supports a low-level sample comparison and no scientific
  relation can be stated, return an empty `relations` array.
- Every relation must cite one or more `evidence_unit_ids` from the input.
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
        "- If `objective_context.objective_evidence_lens` is present, treat "
        "`target_outcome_axes` as the outcomes that answer the objective, "
        "`mediator_axes` as explanatory intermediate concepts, `context_axes` "
        "as binding scope, and `excluded_axes` as out-of-lens properties.\n"
        "- Prefer facts that connect `objective_context.variable_process_axes` to "
        "`objective_context.target_property_axes` for that lens.\n"
        "- Do not treat a mediator or context-only observation as a target result "
        "unless the source explicitly links it to a target outcome.\n"
        "- If `objective_context.material_scope` identifies one clear material "
        "system, populate emitted evidence units' `material_system.family` with "
        "that material unless the source explicitly states a different material.\n"
        "- Treat `objective_context.process_context_axes` as process context, not "
        "as changed variables unless the input explicitly compares them.\n"
        "- Do not emit result claims for `objective_context.excluded_property_axes` "
        "or for unrelated properties outside the current lens.\n"
        f"{route_guidance}\n"
    )


def build_paper_skim_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "Skim this one paper for collection-level research-objective discovery.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with these fields: doc_role, "
        "candidate_materials, candidate_processes, candidate_properties, "
        "changed_variables, possible_objectives, evidence_density, confidence, "
        "and warnings.\n"
        "Do not extract final measurement facts or comparison rows.\n"
        "Do not output a material as a research objective unless it is phrased as "
        "a question or comparison intent.\n"
        "Make the skim useful for later comparison planning:\n"
        "- `candidate_processes` should include both the process family and the "
        "main variable axes when visible. For PBF/SLM/LPBF papers, include axes "
        "such as energy density, scan strategy, scanning speed, laser power, "
        "hatch spacing, layer thickness, build orientation, heat treatment, or "
        "porosity when they are part of the study.\n"
        "- `candidate_properties` should prefer concrete observable endpoints "
        "from title, headings, captions, and table headers. Do not stop at "
        "`mechanical properties` when specific endpoints such as yield strength, "
        "ultimate tensile strength, elongation, hardness, or microhardness are "
        "visible. Do not stop at `corrosion properties` when corrosion potential, "
        "pitting potential, current density, EIS, or passivation metrics are "
        "visible.\n"
        "- `possible_objectives` should combine material + process variable axes "
        "+ concrete property axes. Avoid overly broad questions that only say "
        "`processing affects properties`.\n"
        "- Emit at most 3 high-signal `possible_objectives` for one paper. Group "
        "related endpoints into one objective instead of creating one question "
        "per metric. For example, yield strength, ultimate tensile strength, "
        "elongation, and microhardness usually belong in one mechanical-properties "
        "objective with specific endpoints listed in `candidate_properties`.\n"
        "- Preserve paper-level outcomes visible in the title or abstract, such "
        "as densification/relative density and microstructure, even when tables "
        "also expose many mechanical endpoints.\n"
    )
    return _RESEARCH_OBJECTIVE_SYSTEM_PROMPT, user_prompt


def build_research_objective_discovery_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Discover research objectives supported by this collection of paper skims.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with an `objectives` array.\n"
        "Each objective must have a question, material_scope, process_axes, "
        "property_axes, comparison_intent, seed_document_ids, "
        "excluded_document_ids, confidence, and reason.\n"
        "Do not return a list of materials. Return question-shaped objectives "
        "that define what should be compared.\n"
        "`comparison_intent` is required and must be a non-empty operational "
        "sentence that says which process/material groups or variable axes should "
        "be compared against which property endpoints. Do not return null.\n"
        "`process_axes` should include the studied variable axes, not only the "
        "manufacturing method. For example, prefer `Selective Laser Melting`, "
        "`energy density`, `scan strategy`, and `scanning speed` together when "
        "the paper studies those axes.\n"
        "`property_axes` should preserve specific endpoints when they are visible "
        "in the skims. For example, expand broad `mechanical properties` into "
        "yield strength, ultimate tensile strength, elongation, hardness, or "
        "microhardness when those endpoints are present.\n"
        "Prefer a small set of high-signal objectives. Do not split one coherent "
        "mechanical-properties comparison into many tiny objectives unless the "
        "paper clearly treats them as separate research questions.\n"
        "Do not create one objective per mechanical endpoint. Group related "
        "mechanical endpoints into one objective and list the specific endpoints "
        "inside `property_axes`.\n"
        "Do not collapse distinct `possible_objectives` from a paper skim when "
        "they cover different property axes. Keep an objective about "
        "densification/microstructure separate from one about mechanical "
        "properties unless the skim only provides one explicitly integrated "
        "research question.\n"
        "For PBF/SLM parameter papers, a good objective set often separates: "
        "densification/relative density, microstructure, and grouped mechanical "
        "properties, instead of four separate tensile/hardness questions.\n"
    )
    return _RESEARCH_OBJECTIVE_SYSTEM_PROMPT, user_prompt


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
        "When `objective_context.objective_evidence_lens` is present, first "
        "decide whether `current_source` is direct target-outcome evidence, "
        "mediator/context evidence, or irrelevant. Treat `target_outcome_axes` "
        "as the only outcome axes that answer the objective. Treat "
        "`mediator_axes` as explanatory context unless the source explicitly "
        "links them to a target outcome.\n"
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


def build_objective_evidence_unit_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Extract objective-scoped evidence units from this one routed source.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with an `evidence_units` array.\n"
        "Return at most one high-confidence evidence unit. If the source "
        "contains many possible facts, choose the ones most directly tied to "
        "the active objective and route role.\n"
        "The backend binds `source_refs` from the active route. Do not output "
        "`source_refs`, `evidence_anchor_ids`, backend ids, copied source text, "
        "or copied input JSON.\n"
        "`unit_kind` must be one of: measurement, test_condition, sample_context, "
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
        "For text routes, return at most one evidence unit: the strongest "
        "objective-relevant measurement, process/test context, characterization, "
        "comparison, or interpretation. Do not enumerate every possible number "
        "or secondary observation in the paragraph.\n"
        "Good text example: `1.43x10^6 C/s for P150, and 1.65x10^6 C/s for NP` "
        "should produce only the most objective-relevant one of those bindings "
        "for this route, not two separate evidence units.\n"
        "Bad text example: returning separate evidence units for every numeric "
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
        "Do not emit an evidence unit if its property, context, value, and "
        "interpretation fields would all be empty.\n"
        "`resolution_status` should be resolved only when source, sample/process "
        "context, and value or condition are sufficiently bound; otherwise use "
        "partial or unresolved."
    )
    return _OBJECTIVE_EVIDENCE_UNIT_SYSTEM_PROMPT, user_prompt


def build_research_understanding_relation_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "Extract expert-readable relations for this research understanding workspace.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with a `relations` array.\n"
        "Return at most 8 relations.\n"
        "`relation_type` must be one of: causal, correlational, mechanistic, "
        "conditional, conflicting, comparative.\n"
        "`direction` must be one of: increases, decreases, improves, reduces, "
        "changes, mixed, conditional, unknown.\n"
        "`source_concept` and `target_concept` must be concise scientific terms "
        "such as laser power, scan speed, porosity, density, microstructure, "
        "ductility, pitting corrosion, heat treatment, or residual stress.\n"
        "Do not use None, null, unknown, n/a, true/false, JSON fragments, backend "
        "field names, sample ids, or condition ids as source, target, or mediator "
        "concepts; return no relation instead.\n"
        "Use `mediator_concepts` only for explicit or strongly supported middle "
        "concepts, for example porosity or microstructure evolution.\n"
        "`statement` should be a short expert-readable sentence grounded in the "
        "provided claims/evidence. Do not include backend ids, sample_number, "
        "condition_number, row labels, or copied JSON.\n"
        "Use `conditions` for material, process, test, and scope constraints.\n"
        "Use `warnings` for limited evidence, conflicting evidence, or overclaim "
        "risk. If no expert relation is supported, return `{\"relations\": []}`."
    )
    return _RESEARCH_UNDERSTANDING_RELATION_SYSTEM_PROMPT, user_prompt
