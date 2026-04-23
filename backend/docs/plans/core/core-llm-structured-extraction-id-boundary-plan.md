# Core LLM Structured Extraction ID Boundary Plan

## Summary

This document records a focused Core child implementation plan for removing
backend-internal identifiers from the Core semantic-build LLM contract.

The target is not to redesign the public API, replace the provider, or claim a
latency fix from prompt cleanup alone. The target is narrower:

- stop passing backend and Source artifact identifiers into Core semantic
  extraction prompts
- stop expecting the model to return backend-facing locator identifiers
- move identity generation, anchor alignment, and relation resolution back into
  deterministic backend materialization

This plan sits under the existing Core structured-extraction cutover wave and
works with the new semantic-build package boundary:

- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
- [`core-semantic-build-packaging-alignment-plan.md`](core-semantic-build-packaging-alignment-plan.md)

## Why This Child Plan Exists

The new `application/core/semantic_build/llm/` package made the Core-owned LLM
contract easier to read, but it also made one remaining boundary problem more
obvious:

the current `paper_facts` LLM contract still leaks backend-internal identity
and locator fields into the model boundary.

Today that leak happens in both directions:

- input payloads still pass fields such as `document_id`, `window_id`,
  `text_unit_ids`, `block_ids`, `table_id`, and `row_index`
- output schemas still allow model-produced locator fields such as
  `section_id`, `block_id`, `snippet_id`, and `figure_or_table`
- output schemas also still ask the model to coordinate intra-bundle linkage
  through temporary refs such as `method_ref`, `variant_ref`,
  `test_condition_ref`, `baseline_ref`, and `result_ref`

That shape creates four practical problems:

- it couples the model contract to current backend artifact structure instead
  of to research semantics
- it bloats prompt payloads and response schemas with data the backend already
  owns deterministically
- it makes portability and provider changes harder because the model is
  learning backend plumbing rather than only extraction work
- it leaves backend identity and relation logic partly delegated to the model
  instead of to deterministic Core code

## Decision

The Core semantic-build LLM boundary should become id-free.

That means:

- model input should contain semantic text and human-readable context only
- model output should contain semantic facts and quoted evidence only
- backend code should own all UUID generation, locator recovery, quote-to-scope
  alignment, deduplication, and entity linking

This plan makes one important distinction explicit:

- persistent stored ids already belong to the backend and should stay there
- temporary model-facing refs and locators should also move out of the model
  boundary unless there is a tightly bounded short-term migration reason

This plan explicitly rejects:

- letting the model emit backend persistence ids
- preserving current id-heavy prompt shapes for convenience
- adding compatibility wrappers or dual-schema parse paths
- treating Source artifact ids as a stable semantic contract

## Current State

### Document Profile Slice

`document_profile` is already close to the desired boundary:

- its prompt payload is limited to `title`, `source_filename`,
  `abstract_or_lead_text`, and `headings`
- it does not pass `document_id` into the model
- its response schema contains classification results only, not ids

That slice does not need the same boundary cleanup.

### Paper Facts Slice

`paper_facts` is the active problem area.

Current prompt payloads still include backend or Source identity data:

- `document_id`
- `text_window.window_id`
- `text_window.text_unit_ids`
- `text_window.block_ids`
- `table_row.table_id`
- `table_row.row_index`
- `supporting_text_windows[].window_id`
- `supporting_text_windows[].text_unit_ids`
- `supporting_text_windows[].block_ids`

Current response schemas still allow backend-facing locator output:

- `section_id`
- `block_id`
- `snippet_id`
- `figure_or_table`

Current response schemas also still ask the model to manage bundle-local
linkage through temporary refs:

- `method_ref`
- `variant_ref`
- `test_condition_ref`
- `baseline_ref`
- `result_ref`

At the same time, the materialization path already proves the backend is the
right owner for persistent ids:

- evidence anchors, methods, variants, test conditions, baselines, and
  measurement results are all assigned locally generated ids during
  materialization

## Scope

This plan covers:

- prompt payload cleanup for `paper_facts` text-window and table-row extraction
- response-schema cleanup for anchor locators and model-managed refs
- backend-local anchor recovery from current scope and quote matching
- deterministic backend relation resolution after model parse
- targeted test and fake-extractor updates for the new contract

This plan does not cover:

- public HTTP contract changes
- collection artifact filename changes
- Source structural artifact redesign
- provider replacement
- packaging changes already recorded in the semantic-build packaging plan
- latency optimization claims from id cleanup alone

## Target Contract Shape

### Input Boundary

Allowed model input should be semantic and human-readable:

- document title
- document profile coarse classification when useful
- bounded text-window text
- heading and heading-path text
- row summary and row cell text
- nearby or supporting text excerpts

Disallowed model input should include all backend or Source identifiers:

- `document_id`
- `window_id`
- `text_unit_ids`
- `block_ids`
- `table_id`
- `row_index`
- any future storage primary key or artifact-local identity field

### Output Boundary

Allowed model output should contain:

- semantic method, sample, condition, baseline, and measurement facts
- quoted evidence anchors
- human-meaningful labels and normalized property names
- optional page numbers when the page itself is a reader-facing evidence clue

Disallowed model output should include:

- backend persistence ids
- Source artifact ids
- backend locator fields such as `section_id`, `block_id`, `snippet_id`, and
  `figure_or_table`
- model-managed relationship ids once the second wave lands

## Execution Waves

### Wave 1: Remove Internal Locator IDs From The LLM Boundary

Objective:

remove backend and Source locator ids from prompt payloads and stop asking the
model to return locator ids.

Actions:

- update `paper_facts_service.py` payload builders so prompt payloads no longer
  include `document_id`, `window_id`, `text_unit_ids`, `block_ids`, `table_id`,
  or `row_index`
- narrow `EvidenceAnchorPayload` so it keeps only semantic evidence fields such
  as `quote`, `source_type`, and optional `page`
- update prompt text to explicitly forbid backend-facing locator output
- rewrite local anchor materialization so locator recovery is derived from the
  current text-window or table-row scope instead of from model-returned ids
- keep temporary `*_ref` fields for one intermediate wave only, so relation
  breakage risk stays bounded while locator cleanup lands first

Acceptance:

- serialized LLM prompt payloads no longer contain backend or Source ids
- `EvidenceAnchorPayload` no longer contains locator id fields
- traceback-ready anchors are still materialized locally from quote and scope
- existing evidence and traceback surfaces continue to work without model
  locator ids

### Wave 2: Remove Model-Owned Bundle Ref Linking

Objective:

stop using model-owned temporary refs as the primary mechanism for linking
variants, test conditions, baselines, and results within one extraction unit.

Actions:

- redesign the structured extraction schema so linked semantics are nested or
  result-centered rather than coordinated through `*_ref` tokens
- remove `method_ref`, `variant_ref`, `test_condition_ref`, `baseline_ref`,
  and `result_ref` from the Core LLM schema
- change backend materialization so relation resolution is derived from nested
  semantic payloads and deterministic local matching
- keep deduplication keyed on backend-owned semantic signatures rather than on
  model-managed reference strings

Acceptance:

- the LLM schema no longer contains temporary inter-object refs
- relation resolution stays entirely backend-owned after parse
- multi-entity extraction units still materialize stable variant/condition/
  baseline/result links without model-generated ids

## Local Runtime Design Rules

### Anchor Recovery

After Wave 1, anchor recovery should follow backend-local rules:

- the current extraction scope is authoritative
- for text-window extraction, the backend should first try to match quote text
  inside the current bounded text window and its local block/text-unit context
- for table-row extraction, the backend should default to current row scope and
  nearby supporting text context
- if exact quote matching fails, the backend may still emit a weak locator
  anchored to current scope with explicit low-confidence semantics

### Identity Generation

Backend-owned identity remains local:

- `anchor_id`
- `method_id`
- `variant_id`
- `test_condition_id`
- `baseline_id`
- `result_id`

No part of that identity generation should cross the LLM boundary.

### No Compatibility Layer Rule

This cleanup should be a direct contract replacement:

- update the real prompt and schema owners directly
- update tests and fake extractors directly
- do not retain old LLM schema shapes behind wrappers, forwarders, or
  dual-parse bridges

## File Change Surface

Primary runtime files:

- `backend/application/core/semantic_build/paper_facts_service.py`
- `backend/application/core/semantic_build/llm/schemas.py`
- `backend/application/core/semantic_build/llm/prompts.py`
- `backend/application/core/semantic_build/llm/extractor.py`

Primary verification files:

- `backend/tests/support/fake_core_llm_extractor.py`
- `backend/tests/unit/services/test_paper_facts_services.py`
- any focused integration coverage that asserts prompt shape or traceback
  stability

## Verification

Required verification slices:

- add a targeted unit test that serialized prompt payloads do not include
  internal ids
- add or update a targeted unit test that quote-based anchor recovery still
  reconstructs local traceback anchors without model locator ids
- keep existing `paper_facts` and traceback tests passing after Wave 1
- add or update coverage for multi-entity extraction units before removing
  `*_ref` fields in Wave 2

Suggested verification commands:

- targeted backend unit tests for `paper_facts_service`
- targeted backend unit tests for traceback-ready evidence views
- docs governance after recording this child plan

## Risks

- removing locator ids before local quote matching is strong enough could
  weaken traceback precision
- some current test fixtures and fake extractors still assume id-bearing prompt
  or schema shapes and must move in the same wave
- removing `*_ref` fields too early could break relation materialization in
  windows that emit multiple variants or conditions at once
- this cleanup improves ownership and contract quality, but should not be sold
  as a guaranteed latency fix by itself

## Related Docs

- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
- [`core-semantic-build-packaging-alignment-plan.md`](core-semantic-build-packaging-alignment-plan.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
