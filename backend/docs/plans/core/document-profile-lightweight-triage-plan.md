# Document Profile Lightweight Triage Plan

## Summary

This document records the current narrowed Core child plan for
`document_profiles`.

The immediate change is:

turn `document_profile` generation into lightweight document triage rather than
a broad semantic extraction step.

This remains a narrow Core child plan inside the current backend Core wave.

It does not decide the downstream primary object model for paper facts,
evidence views, or comparison projections.

It does not justify expanding scope into `evidence_cards`, comparison
assembly, Source restructuring, or API-wide contract cleanup.

For the broader backend roadmap, read
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md).
For the shared domain-model correction, read
[`../../../../docs/decisions/rfc-paper-facts-primary-domain-model.md`](../../../../docs/decisions/rfc-paper-facts-primary-domain-model.md).
For the parent Core quality wave, read
[`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md).
For the broader Core LLM cutover plan, read
[`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md).

## Why This Child Plan Exists

The current `document_profile` slice is doing the wrong job.

Today it accepts a broad payload, asks the model for structured output, and
then relies on a loose schema plus post-hoc normalization. In practice, that
has allowed invalid values such as free-text summaries or off-enum document
types to land in fields that downstream code expects to be stable enums.

That creates two problems:

- `document_profile` is acting like a weak semantic extractor instead of a
  routing layer
- downstream Core logic receives unstable values for `doc_type` and
  `protocol_extractable`

The narrower design principle is simple:

- `document_profile` should only answer coarse document-level triage questions
- deeper research semantics belong in later Core extraction and fact
  materialization stages
- this wave should not introduce `has_*` feature payloads or another ruleset
  surface unless they are explicitly needed later

## Decision

Core should simplify `document_profile` to a lightweight triage step.

The new shape is:

- keep existing output field names for compatibility
- narrow the LLM input to title/front-matter style context only
- allow only enum outputs plus a small fixed warning set
- keep `protocol_extractability_signals` present but empty in this wave
- treat invalid or uncertain outputs as `uncertain`, not as material for
  hidden semantic backfill

This plan explicitly rejects:

- adding adapter, wrapper, shim, facade, or compatibility-layer code
- broadening the task into `evidence_cards` or `comparison_rows`
- adding `has_methods_heading`, `has_table_marker`, or similar signal families
  to the contract in this wave
- keeping the old "signals drive semantic inference" behavior in
  `DocumentProfile`

## Scope

This child plan covers:

- narrowing `document_profile` input payload construction
- tightening the `StructuredDocumentProfile` response schema
- rewriting the document-profile prompt as triage-only
- simplifying `DocumentProfile` normalization so invalid values collapse to
  stable enums
- updating the fake extractor and unit tests for the new contract

This child plan does not cover:

- Source chunking or section/table generation strategy
- `evidence_cards`, `sample_variants`, `measurement_results`, or comparison
  extraction changes
- public API field renames
- new persistent signal families
- collection-wide routing redesign outside `document_profile`

## Target Contract

### Input Payload

The `document_profile` extraction input should shrink to:

```json
{
  "title": "string | null",
  "source_filename": "string | null",
  "abstract_or_lead_text": "string | null",
  "headings": ["string"]
}
```

Construction rules:

- use `abstract` or similar front-matter text when available
- otherwise use the first small lead slice from the document body
- pass only the first few headings
- do not send the full section list or long representative text blocks

### Output Payload

The response should keep the current field names but constrain their meaning:

```json
{
  "doc_type": "experimental | review | mixed | uncertain",
  "protocol_extractable": "yes | partial | no | uncertain",
  "protocol_extractability_signals": [],
  "parsing_warnings": [
    "insufficient_content | classification_uncertain"
  ],
  "confidence": 0.0
}
```

Field semantics:

- `doc_type` is a coarse document-level class, not a paper summary
- `protocol_extractable` is a coarse "worth deeper extraction?" signal
- `protocol_extractability_signals` stays empty in this wave
- `parsing_warnings` may only contain fixed warning enums
- `confidence` reflects triage confidence only

## Triage Rules

The runtime should stay simple.

1. Build the minimal payload from `title`, `source_filename`,
   `abstract_or_lead_text`, and `headings`.
2. If content is obviously insufficient, short-circuit to:
   - `doc_type = uncertain`
   - `protocol_extractable = uncertain`
   - `parsing_warnings = ["insufficient_content"]`
3. Otherwise call the LLM with the narrowed payload.
4. If the model is unsure or returns invalid values, normalize to:
   - `doc_type = uncertain`
   - `protocol_extractable = uncertain`
   - `parsing_warnings = ["classification_uncertain"]` when appropriate

This wave does not add a separate feature-extraction stage.

## Prompt And Schema Rules

The document-profile prompt should say explicitly:

- you are doing document triage, not knowledge extraction
- return enums only
- do not return natural-language summaries or explanations
- if uncertain, return `uncertain`
- `protocol_extractability_signals` must be empty
- `parsing_warnings` may only use the fixed warning enum set

The Pydantic response model should enforce:

- `doc_type = Literal["experimental", "review", "mixed", "uncertain"]`
- `protocol_extractable = Literal["yes", "partial", "no", "uncertain"]`
- `protocol_extractability_signals = list[Literal[...]]` is not needed here;
  keep it as an empty list default
- `parsing_warnings` is limited to
  `["insufficient_content", "classification_uncertain"]`

## Implementation Plan

### Primary Code Areas

- `backend/application/core/document_profile_service.py`
- `backend/application/core/llm_extraction_models.py`
- `backend/application/core/llm_extraction_prompts.py`
- `backend/domain/core/document_profile.py`
- `backend/tests/support/fake_core_llm_extractor.py`
- `backend/tests/unit/services/test_document_profile_service.py`

### Planned Changes

- tighten `StructuredDocumentProfile` so invalid free-text values are rejected
- change `_profile_document_row()` to build a minimal triage payload
- add a small insufficient-content short-circuit before LLM invocation
- remove hidden semantics that currently derive `doc_type` and
  `protocol_extractable` from signal lists
- update tests so `document_profile` no longer depends on `has_*` signal
  semantics

### Execution Order

1. Tighten the response schema.
2. Rewrite the prompt for triage-only behavior.
3. Narrow `document_profile_service` payload construction.
4. Simplify `DocumentProfile` normalization.
5. Update the fake extractor and unit tests.
6. Run targeted backend verification.

## Verification

Primary verification should be:

- `pytest backend/tests/unit/services/test_document_profile_service.py`

The checks should confirm:

- `doc_type` and `protocol_extractable` stay inside the enum contract
- no free-text summaries appear in enum fields
- `protocol_extractability_signals` is empty in this wave
- content-poor documents fall back to `uncertain`

## Risks And Guardrails

- do not rename public fields in this wave; keep the output contract shape
  stable
- do not touch `paper_facts_service` unless a concrete dependency is proven
- do not reintroduce signal-driven semantic inference through normalization
- do not expand this plan into a broader Core data-model redesign

If a later wave wants richer routing signals or field renames, that should be a
separate change with its own contract review.
