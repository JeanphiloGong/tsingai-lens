from __future__ import annotations

import json
from typing import Any


_COMMON_SYSTEM_PROMPT = """
You are extracting structured research facts for a materials-literature backend.

Non-negotiable rules:
- Extract only facts directly supported by the provided input.
- If evidence is missing or ambiguous, use null or an empty list.
- Never infer material systems from filenames.
- Never treat years, citation numbers, row numbers, or footnote markers as result values.
- Never treat years, reference numbers, or numbering artifacts as units.
- Reject literature-summary rows or review-summary rows that are not directly attributable.
- Preserve anchors needed for downstream traceback using quoted evidence only.
- Never emit backend-facing ids or locator fields such as `section_id`, `block_id`, `snippet_id`, or `figure_or_table`.
- Never emit bundle ref fields such as `method_ref`, `variant_ref`, `test_condition_ref`, `baseline_ref`, or `result_ref`.
- If a result needs to point to a variant or baseline, repeat the human-readable label instead.
- Prefer fewer, higher-signal outputs over speculative coverage.
""".strip()


_DOCUMENT_PROFILE_SYSTEM_PROMPT = """
You are doing document triage for a materials-literature backend.

Non-negotiable rules:
- This is coarse document classification, not knowledge extraction.
- Return schema-valid structured data only.
- Do not write natural-language summaries or explanations.
- `doc_type` must be one of: experimental, review, mixed, uncertain.
- `protocol_extractable` must be one of: yes, partial, no, uncertain.
- `protocol_extractability_signals` must always be an empty list.
- `parsing_warnings` may only use: insufficient_content, classification_uncertain.
- If the input is weak or ambiguous, return `uncertain`.
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
        "Extract text-window-grounded research facts from this one bounded document window.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "You may emit method facts, sample variants, test conditions, baseline "
        "references, and measurement results only if they are directly grounded in "
        "this text window. Anchors may include quote, source_type, and page only. "
        "Do not emit backend locators, ids, or bundle refs. Use human-readable labels "
        "instead of refs when a result must identify a variant or baseline. Do not emit "
        "reader-facing summaries or cards."
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
        "identify a variant or baseline. Return facts only, not reader-facing cards."
    )
    return _COMMON_SYSTEM_PROMPT, user_prompt
