from __future__ import annotations

import json
from typing import Any


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
- `protocol_extractable` must be one of: yes, partial, no, uncertain.
- `protocol_extractability_signals` must always be an empty list.
- `parsing_warnings` may only use: insufficient_content, classification_uncertain.
- If the input is weak or ambiguous, return `uncertain`.
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


_TABLE_ROW_JSON_COMPLIANCE_GUIDANCE = """
JSON compliance rules for this extraction:
- Use exactly the schema keys and no others. Do not add keys like `keywords`, `notes`, or `warnings`.
- Arrays must stay arrays. When empty, use `[]`. Never use `null` for arrays such as `temperatures_c`, `durations`, `methods`, or any top-level list.
- Required nested objects must stay objects. Never use `null` for `method_payload`, `process_context`, `condition_payload`, or `value_payload`.
- Put nullable scalars inside those required objects instead of nulling the whole object.
- `unit` belongs at `measurement_results[*].unit`, never inside `value_payload`.
- `host_material_system` may be `null`, but `process_context` may not be `null`.
- For PBF metal rows, put laser/process/sample-state facts in `process_context`; do not put test temperature or strain rate there.
- Put mechanical test facts in `condition_payload`: `test_method`, `test_temperature_c`, `strain_rate_s-1`, `loading_direction`, and `sample_orientation`.
- Put value provenance in `value_payload`: `value_origin`, `source_value_text`, `source_unit_text`, `derivation_formula`, and `derivation_inputs`.
- Use `value_origin: "reported"` only for directly reported values, `derived` only when the row gives enough inputs and a formula, and `estimated` only when the row itself marks the value as approximate.
- Omit weakly grounded PBF fields. Do not infer missing laser power, scan speed, orientations, strain rate, or energy density from general domain knowledge.
- Extract row-grounded facts only. Use `supporting_text_windows` only to disambiguate row labels, abbreviations, or column meaning.
- Do not mine `supporting_text_windows` for extra standalone facts that are not needed to interpret this row.
- If a fact cannot be grounded to the row or a short disambiguating support quote, omit it.
- Do not repeat the same fact in multiple arrays.
- Keep `anchors[*].quote` short, exact, and contiguous.
- Emit at most 2 `method_facts`, 2 `sample_variants`, 2 `test_conditions`, 2 `baseline_references`, and 4 `measurement_results` for one row.
- If evidence is weak or absent, return the valid empty-shape object with empty lists and null scalar leaves.

Valid nested object example:
```json
{
  "method_payload": {
    "temperatures_c": [],
    "durations": [],
    "atmosphere": null,
    "methods": [],
    "details": null
  },
  "process_context": {
    "temperatures_c": [],
    "durations": [],
    "atmosphere": null,
    "laser_power_w": null,
    "scan_speed_mm_s": null,
    "layer_thickness_um": null,
    "hatch_spacing_um": null,
    "spot_size_um": null,
    "energy_density_j_mm3": null,
    "energy_density_origin": null,
    "scan_strategy": null,
    "build_orientation": null,
    "preheat_temperature_c": null,
    "shielding_gas": null,
    "oxygen_level_ppm": null,
    "powder_size_distribution_um": null,
    "post_treatment_summary": null
  },
  "condition_payload": {
    "method": null,
    "methods": [],
    "temperatures_c": [],
    "durations": [],
    "atmosphere": null,
    "test_method": null,
    "test_temperature_c": null,
    "strain_rate_s-1": null,
    "loading_direction": null,
    "sample_orientation": null,
    "environment": null,
    "frequency_hz": null,
    "specimen_geometry": null,
    "surface_state": null
  },
  "value_payload": {
    "value": null,
    "min": null,
    "max": null,
    "retention_percent": null,
    "direction": null,
    "statement": null,
    "value_origin": null,
    "source_value_text": null,
    "source_unit_text": null,
    "derivation_formula": null,
    "derivation_inputs": null
  }
}
```

Valid PBF metal row example:
```json
{
  "method_facts": [],
  "sample_variants": [
    {
      "variant_label": "S3",
      "host_material_system": {
        "family": "titanium alloy",
        "composition": "Ti-6Al-4V"
      },
      "composition": "Ti-6Al-4V",
      "variable_axis_type": "post_treatment",
      "variable_value": "optimized VED + HIP",
      "process_context": {
        "temperatures_c": [],
        "durations": [],
        "atmosphere": null,
        "laser_power_w": 280,
        "scan_speed_mm_s": 1200,
        "layer_thickness_um": 30,
        "hatch_spacing_um": 100,
        "energy_density_j_mm3": 78,
        "energy_density_origin": "reported",
        "build_orientation": "vertical",
        "post_treatment_summary": "HIP"
      },
      "confidence": 0.86,
      "epistemic_status": "normalized_from_evidence",
      "source_kind": "table_row"
    }
  ],
  "test_conditions": [
    {
      "property_type": "yield_strength",
      "condition_payload": {
        "method": "tensile",
        "methods": ["tensile"],
        "temperatures_c": [],
        "durations": [],
        "atmosphere": null,
        "test_method": "tensile",
        "test_temperature_c": 25,
        "strain_rate_s-1": 0.001,
        "loading_direction": "vertical",
        "sample_orientation": "vertical"
      },
      "confidence": 0.86,
      "epistemic_status": "normalized_from_evidence"
    }
  ],
  "baseline_references": [
    {
      "baseline_label": "S2",
      "confidence": 0.86,
      "epistemic_status": "normalized_from_evidence"
    }
  ],
  "measurement_results": [
    {
      "claim_text": "S3 showed a yield strength of 940 MPa at 25 C.",
      "property_normalized": "yield_strength",
      "result_type": "scalar",
      "value_payload": {
        "value": 940,
        "statement": "S3 showed a yield strength of 940 MPa at 25 C.",
        "value_origin": "reported",
        "source_value_text": "940",
        "source_unit_text": "MPa"
      },
      "unit": "MPa",
      "variant_label": "S3",
      "baseline_label": "S2",
      "anchors": [
        {
          "quote": "S3 showed a yield strength of 940 MPa at 25 C",
          "source_type": "table",
          "page": 5
        }
      ],
      "claim_scope": "current_work",
      "confidence": 0.86
    }
  ]
}
```

Valid measurement result example:
```json
{
  "claim_text": "Yield strength reached 560 MPa.",
  "property_normalized": "yield strength",
  "result_type": "scalar",
  "value_payload": {
    "value": 560,
    "min": null,
    "max": null,
    "retention_percent": null,
    "direction": null,
    "statement": null,
    "value_origin": "reported",
    "source_value_text": "560",
    "source_unit_text": "MPa",
    "derivation_formula": null,
    "derivation_inputs": null
  },
  "unit": "MPa",
  "variant_label": null,
  "baseline_label": null,
  "anchors": [
    {
      "quote": "yield strength reached 560 MPa",
      "source_type": "table",
      "page": 5
    }
  ],
  "confidence": 0.85
}
```

Invalid counterexamples. Do not copy these shapes:
```json
{
  "keywords": ["yield strength"],
  "method_facts": [],
  "sample_variants": [],
  "test_conditions": [],
  "baseline_references": [],
  "measurement_results": []
}
```

```json
{
  "method_payload": {
    "temperatures_c": null,
    "durations": null
  },
  "process_context": null,
  "condition_payload": {
    "methods": null
  },
  "value_payload": null
}
```

```json
{
  "value_payload": {
    "value": 560,
    "unit": "MPa"
  }
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
        f"{_TEXT_WINDOW_JSON_COMPLIANCE_GUIDANCE}"
    )
    return _COMMON_SYSTEM_PROMPT, user_prompt


def build_table_row_extraction_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    user_prompt = (
        "Extract row-grounded research facts from this one table row.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Use the row and header context only. Skip outputs when the row is a literature "
        "summary rather than a directly attributable study row. Anchors may include "
        "quote, source_type, and page only. Do not emit backend locators, ids, or "
        "bundle refs. Use human-readable labels instead of refs when a result must "
        "identify a variant or baseline. Return facts only, not reader-facing cards.\n"
        "Use `supporting_text_windows` only when they are required to interpret the row.\n"
        "If the row is mostly metadata, labels, or literature summary text, return the "
        "smallest valid object instead of expanding speculative outputs.\n\n"
        f"{_TABLE_ROW_JSON_COMPLIANCE_GUIDANCE}"
    )
    return _COMMON_SYSTEM_PROMPT, user_prompt
