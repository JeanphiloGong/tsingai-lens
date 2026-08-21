from __future__ import annotations

import json
from typing import Any

PAPER_FACT_TEXT_WINDOW_PROMPT_VERSION = "paper_fact_text_window.v1"
PAPER_FACT_TABLE_BATCH_PROMPT_VERSION = "paper_fact_table_batch.v1"
PAPER_FACT_TABLE_MATRIX_REPAIR_PROMPT_VERSION = "paper_fact_table_matrix_repair.v2"

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
- Never emit backend-owned Source references or persistence IDs.
- Never emit backend persistence ids, Source ids, or bundle ref fields such as `method_ref`, `variant_ref`, `test_condition_ref`, `baseline_ref`, or `result_ref`.
- Prefer fewer, higher-signal outputs over speculative coverage.
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
- Do not emit page, source type, Source references, or deep links.
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
        "Read the complete continuous table or table slice from "
        "`source.table_markdown`. Its first row is the canonical flattened header "
        "from `source.column_headers`; caption and heading context apply to every "
        "row in the slice.\n"
        "`repaired_table_matrix` must contain that header followed by every data "
        "row in the Markdown, in the same order and with the same logical columns. "
        "Do not add, remove, reorder, summarize, or truncate rows.\n"
        "Nearby complete rows can support "
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
        "Record each changed cell in `repairs` with its Markdown-local row_index "
        "(header is row 0), column, before, after, and reason. If no confident "
        "repair is possible, return the Markdown matrix unchanged and explain the "
        "uncertainty in `warnings`."
    )
    return _TABLE_MATRIX_REPAIR_SYSTEM_PROMPT, user_prompt
