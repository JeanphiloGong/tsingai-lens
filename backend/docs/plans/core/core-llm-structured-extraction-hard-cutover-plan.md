# Core LLM Structured Extraction Hard Cutover Plan

## Summary

This document records the backend-owned child execution plan for hard-cutting
the current Core parsing and evidence backbone away from heuristic extraction
and onto LLM structured extraction.

This is not a new architecture layer and not a Source-owned parser expansion.
It is a Core child plan inside the corrected Lens v1 Core flow:

`document_profiles -> paper facts family -> comparison_rows / evidence_cards`

Read this plan with the accepted paper-facts RFC:

- [`../../../../docs/decisions/rfc-paper-facts-primary-domain-model.md`](../../../../docs/decisions/rfc-paper-facts-primary-domain-model.md)

The purpose of this cutover is straightforward:

- stop treating noisy heuristic inference as the primary semantic extractor
- move Core fact extraction onto schema-bound LLM parsing
- keep `comparison_rows` and `evidence_cards` as deterministic Core-derived
  surfaces rather than opaque model-generated final artifacts

For the broader backend roadmap, read
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md).
For the immediate parent quality wave, read
[`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md).
For the layering rule that keeps stable research facts in Core rather than in
Source, read
[`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md).

## Why This Child Plan Exists

The current backend already has the right high-level layering:

- Source hands off structural artifacts such as `documents`, `text_units`,
  `blocks`, `table_rows`, and `table_cells`
- Core owns stable research-fact extraction and collection-facing review
  artifacts
- derived and downstream surfaces consume Core outputs rather than defining the
  facts themselves

The problem is not missing layers. The problem is that the current Core
semantic extraction is still dominated by heuristics:

- keyword scoring for `document_profiles`
- regex and section heuristics for `evidence_cards`
- table-row guessing for `sample_variants`
- value and unit guessing for `measurement_results`
- condition and baseline inference from weak context fragments

That rule-heavy path is now producing visibly bad collection-facing outputs on
real documents:

- filenames leaking into material-system fields
- review papers producing fake comparison candidates
- years, numbering, or citation artifacts being treated as result values or
  units
- document-level process context being over-merged into row-level comparison
  displays

At this point, further heuristic tuning would only create a larger brittle
ruleset around the wrong primary extraction strategy.

## Decision

The backend should hard-cut Core extraction to LLM structured parsing.

That means:

- Source remains a structural handoff layer
- Core becomes an LLM-first semantic extraction layer
- primary paper facts are extracted before views are assembled
- `comparison_rows` and `evidence_cards` stay deterministic and assembled from
  Core backbone artifacts
- the old heuristic extraction path is removed rather than retained as a
  fallback

This plan explicitly rejects:

- dual-path extraction
- compatibility shims between old heuristic artifacts and new LLM artifacts
- partial roll-forward where one artifact stays heuristic only because it is
  already working "well enough"
- letting Source emit stable Core research facts directly

## Place In The System

### Five-Layer Position

This cutover belongs to Layer 3, the Research Intelligence Core.

It is not:

- Goal Brief / Intake work
- Source runtime parser ownership expansion
- Goal Consumer / Decision-layer work
- a derived-surface graph or report redesign

### Ownership Boundary

The dependency direction after cutover should remain:

- Source owns structural raw material
- Core owns stable research-fact extraction
- downstream views consume Core artifacts

Source may still use rules to split text and tables, but it must not become the
owner of stable semantic artifacts such as sample variants, methods,
measurement results, or comparison judgments.

## Scope

This hard-cutover plan covers:

- replacing heuristic `document_profiles` classification with LLM structured
  extraction
- replacing heuristic paper-facts extraction and evidence-view projection with
  LLM-grounded structured extraction plus deterministic projection
- removing `section` as a Core extraction contract or Source-to-Core semantic
  handoff requirement
- preserving deterministic Core assembly for `comparison_rows`
- invalidating old heuristic-produced Core artifacts rather than supporting
  mixed reads
- adding benchmark and regression coverage for known collection-facing failure
  modes

This plan does not cover:

- redesigning Source document loading or chunking ownership
- moving stable Core facts into Source artifacts
- letting LLMs directly emit final `comparison_rows`
- graph or protocol surface redesign
- adapter, wrapper, facade, or compatibility-layer work

## Hard-Cutover Shape

### What Source Still Produces

Source should continue to produce only structural handoff artifacts:

- `documents`
- `text_units`
- `blocks`
- `table_rows`
- `table_cells`

Those are the inputs Core will consume for semantic extraction.

This plan now makes one narrower boundary explicit:

- Core must not depend on `sections.parquet` as an owned semantic handoff
- Core may build transient text windows over ordered `blocks`
- those text windows are batching units only, not durable Source or Core
  domain artifacts

### What Core Must Extract With LLM Structured Parsing

Core should switch these artifacts to LLM structured extraction:

- `document_profiles`
- `sample_variants`
- `method_facts`
- `measurement_results`
- `test_conditions`
- `baseline_references`
- `characterization_observations`
- `evidence_anchors`

Core may continue to derive:

- `evidence_cards`
- `comparison_rows`
- `structure_features`

from stronger LLM-grounded fact outputs when deterministic extraction still
adds value.

### What Must Stay Deterministic

`comparison_rows` and `evidence_cards` should remain deterministic and
assembled from the backbone artifacts above.

The backend should keep model output away from the final comparison surface for
three reasons:

- deterministic comparability judgment remains auditable
- API behavior stays easier to reason about and test
- collection-facing review does not become hostage to one opaque prompt output

## New Extraction Architecture

The cutover should introduce one minimal permanent OpenAI structured-calling
seam in backend infrastructure, three Core fact-extraction slices, and one
derived-view projection slice above it.

### Slice 1: Document Profile Extraction

The current narrowed execution plan for this slice is recorded in
[`document-profile-lightweight-triage-plan.md`](document-profile-lightweight-triage-plan.md).

Input:

- document title candidates
- source filename
- section summaries
- representative document text

Output:

- `doc_type`
- `protocol_extractable`
- `protocol_extractability_signals`
- `parsing_warnings`
- confidence and contamination markers

### Slice 2: Text-Window Fact Extraction

Input:

- one Core-built text window over ordered `blocks`
- document title and document-level identity
- local `heading_path`, `block_ids`, and source anchor context

Output:

- `method_facts`
- text-grounded `sample_variants`, `test_conditions`, `baseline_references`,
  and `measurement_results` when the window directly supports them
- `characterization_observations` when the evidence is explicit enough
- traceability-ready anchors

This slice replaces the old `extract_section_bundle` idea.

The batching unit may still align with a heading boundary when that makes the
window more coherent, but the contract should be "bounded text window over
blocks", not "section object with `section_type` semantics".

### Slice 3: Table Row Fact Extraction

Input:

- document title
- table title if available
- header path values
- one row's cells
- supporting text windows selected from nearby or anchor-related `blocks`

Output:

- `sample_variants`
- `measurement_results`
- `test_conditions`
- `baseline_references`
- row-grounded anchors

The extraction unit should be one table row, not the whole paper, so the model
is forced to reason over bounded local evidence instead of mixing unrelated
studies in review-heavy documents.

The contextual contract for this slice should no longer be:

- first `methods` section text
- first `characterization` section text

Instead it should be:

- row-local structure
- nearby supporting text windows
- optional caption or block-linked support text

This keeps Core from smuggling `section_type` semantics back into the row path.

### Slice 4: Evidence View Projection

Input:

- extracted paper facts
- extracted evidence anchors
- document-level routing context when needed

Output:

- `evidence_cards`

This slice exists so the system can keep cards as a deterministic projection
layer rather than asking the model to treat them as the only primary research
objects.

## Structured Calling Contract

The implementation should use schema-bound structured extraction rather than
free-text parsing repair.

The intended call shape is:

- one minimal OpenAI-compatible client
- `beta.chat.completions.parse`
- Pydantic response models for each extraction slice

The design goal is:

- model freedom inside the prompt
- schema certainty at the boundary
- no post-hoc regex salvage as the primary correctness mechanism

## Prompt Rules

Every extraction prompt should enforce the same non-negotiables:

- extract only facts supported by the provided text window or table row
- when evidence is missing or ambiguous, return `null` or an empty list
- do not infer missing material systems from filenames
- do not treat years, citation numbers, row numbers, or footnote markers as
  result values
- do not treat years, reference numbers, or numbering artifacts as units
- do not emit comparison-ready results from literature-summary rows unless the
  row is directly grounded and locally attributable
- mark review contamination explicitly
- preserve provenance needed for traceback and downstream rejection decisions

The prompts should be domain-aware rather than generic. The model must be told
what a usable research result looks like and what common failure modes must be
suppressed.

## Artifact Versioning And Cache Invalidation

This cutover should invalidate the old heuristic Core artifacts rather than
trying to read them forever.

Required behavior:

- introduce a Core extraction version such as `llm_v1`
- treat old heuristic-produced artifacts as stale for Core semantic reads
- force rebuild of Core artifacts when a collection only has the old version
- do not keep dual readers for heuristic and LLM artifact shapes

The backend may still reuse the same artifact filenames if the shape remains
compatible, but the read path must reject stale semantic versions instead of
quietly trusting them.

## File Change Plan

### Primary Runtime Areas

- `backend/application/core/document_profile_service.py`
- `backend/application/core/evidence_card_service.py`
- `backend/application/core/comparison_service.py`
- `backend/application/core/llm_structured_extractor.py`
- `backend/application/source/index_task_runner.py`
- `backend/infra/`
  new minimal OpenAI structured-calling seam
- `backend/tests/support/fake_core_llm_extractor.py`

### Suggested New Backend Files

- `backend/infra/llm/openai_structured_client.py`
- `backend/application/core/llm_extraction_models.py`
- `backend/application/core/llm_extraction_prompts.py`

These files should be permanent owning seams, not transitional wrappers.

### Code Removal Requirement

Delete the current heuristic extraction chain after cutover, including:

- profile keyword-scoring as the primary semantic classifier
- table-row variant guessing as the primary variant extractor
- scalar value and unit regex guessing as the primary measurement extractor
- Core-internal section projection as the primary text extraction contract
- Source `sections` workflow remnants once no Core read path still depends on
  them
- baseline and test-condition inference fallbacks that survive only because the
  LLM extractor was uncertain

Small deterministic validators are still acceptable after cutover, but they may
not become a second semantic extraction path.

## Execution Order

1. Add the minimal OpenAI structured client and extraction models.
2. Hard-cut Core text extraction from `section` payloads to text-window
   payloads over `blocks`.
3. Hard-cut table-row extraction to consume row-local structure plus supporting
   text windows.
4. Move characterization support to first-class extracted facts or
   anchor-linked deterministic derivation only.
5. Hard-cut document-profile classification to LLM structured parsing.
6. Rebuild deterministic evidence-card projection over the extracted fact
   layer.
7. Rebuild Core artifact versioning and stale-artifact invalidation.
8. Remove the old heuristic extraction implementation and remaining `sections`
   dependency chain.
9. Lock in regression coverage on a representative benchmark corpus.

This order keeps the highest-noise extraction surface first while preserving
deterministic comparison assembly until the backbone artifacts improve.

## Verification

### Output Quality Verification

- review-heavy collections no longer leak filenames into
  `material_system_normalized`
- year-like values no longer appear as `unit`
- numbering artifacts no longer appear as variant axes or variant labels
- table-row extraction rejects literature-summary rows that are not
  comparison-worthy
- `comparison_rows` become fewer but materially higher signal
- Core no longer requires `sections.parquet` or `section_type` to extract paper
  facts

### Contract Verification

- Source still terminates at structural artifacts only
- Core remains the only stable fact producer
- Core consumes `blocks` and `table_rows` rather than `sections`
- comparison APIs continue to serve deterministic collection-facing rows

### Regression Verification

- add benchmark fixtures covering experimental, mixed, and review-heavy papers
- add regression assertions for known false positives:
  - filename-as-material-system
  - year-as-unit
  - number-as-variant-axis
  - document-level process over-merge
- run targeted backend tests for profiles, evidence, comparison assembly, and
  task-runner indexing flow

## Risks And Guardrails

- prompt design can quietly overfit to a few fixture papers unless the
  benchmark set is deliberately mixed
- schema-bound parsing reduces shape drift, but bad prompt scope can still
  create semantically wrong null-versus-value decisions
- if old heuristic code is not deleted, the system will regress into
  dual-semantic ownership
- if LLM extraction is placed in Source instead of Core, the layering boundary
  will become weaker rather than stronger
- if Core keeps using `section_type` as a hidden routing primitive, the system
  will still be Source-shaped even after the LLM cutover

Guardrails:

- no fallback to the old heuristic extractor
- no adapter or compatibility layer between heuristic and LLM semantic outputs
- no direct LLM emission of final `comparison_rows`
- no Source-owned stable fact artifacts
- no new permanent Core contract that rebrands `section` without actually
  removing section semantics

## Parent, Child, And Companion Relationships

### Parent Docs

- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
  is the immediate parent execution plan. This page is the detailed child plan
  for the hard cutover decision inside that quality wave.
- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
  remains the broader backend roadmap.

### Companion Docs

- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
  remains the companion plan for moving stable Core semantics into explicit
  domain ownership.
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
  remains the boundary authority for keeping stable research facts in Core.

### Later Follow-Up Scope

If later work adds benchmark operations, prompt-evaluation tooling, or a second
wave of deterministic post-validation, record those as later child docs rather
than expanding this page into an open-ended parser program.

## Related Docs

- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../backend-wide/goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
