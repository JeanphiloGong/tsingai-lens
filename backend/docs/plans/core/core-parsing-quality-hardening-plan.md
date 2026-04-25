# Backend Core Parsing Quality Hardening Plan

## Summary

This document records the current backend child execution plan after the
five-layer contract freeze and Source & Collection Builder seam hardening.

The immediate decision is:

pause first-real-adapter expansion and pause Goal Consumer implementation until
the current Research Intelligence Core produces materially better parsing,
evidence, and comparison outputs on real collections.

This remains a backend-wide child plan under `docs/plans/`. It does not
justify a deeper documentation subtree yet because the work spans the current
Core-owned path across `application/documents/`, `application/evidence/`, and
`application/comparisons/`.

For the broader roadmap, read
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md).
For the earlier Core seam work, read
[`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md).
For the narrow PBF-metal validation wave under this quality plan, read
[`pbf-metal-extraction-and-comparison-validation/README.md`](pbf-metal-extraction-and-comparison-validation/README.md).
For the LLM hard-cutover child execution plan under this wave, read
[`../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md).
For the traceback/document-viewer vertical slice under this plan, read
[`claim-traceback-navigation-implementation-plan.md`](claim-traceback-navigation-implementation-plan.md).

## Decision

The backend should not spend the next wave on:

- a first real search or crawler adapter
- Goal Consumer / Decision-layer implementation

The backend should spend the next wave on:

- Core parsing quality
- evidence extraction quality
- comparison assembly quality
- evaluation and regression guardrails for those Core stages

## Why This Priority Changed

The current architecture is now shaped correctly enough:

- Goal Brief is thin and pre-Core
- Source & Collection Builder has a normalized handoff seam
- collection-side handoffs and import provenance are explicit
- Core remains the only stable fact producer

The remaining bottleneck is output quality, not missing layers.

Current risk:

- if document parsing is weak, Goal Consumer will only reorganize weak facts
- if evidence extraction is weak, a first real adapter will only bring in more
  low-quality inputs
- if comparison rows are noisy or under-grounded, downstream protocol, graph,
  and decision views will all inherit that weakness

So the next execution priority should be:

make the Core more trustworthy before adding more sources or more consumers.

## Scope

This child plan covers:

- document input parsing quality under the current Core path
- title, source filename, and section fidelity needed by document profiles
- paper-facts extraction quality, evidence-view quality, and traceback quality
- comparison row quality, comparability gating, and low-value-row suppression
- a small benchmark corpus and regression checks for the Core path

This child plan does not cover:

- search provider or crawler implementation
- first real source adapter implementation
- Goal Consumer / Decision-layer feature work
- graph semantic redesign
- protocol algorithm expansion beyond the minimum Core dependency contract

## Proposed Change

### Execution Goal

Improve the quality of the existing Core backbone:

`document_profiles -> paper facts family -> evidence_cards plus
comparable-result substrate -> row projection`

without changing the five-layer architecture or introducing new product-facing
layers first.

### Workstream 1: Improve Collection Input And Document Parsing Fidelity

Goal:

- make the current Core parsing path produce better document identity and text
  structure before evidence extraction starts

Primary changes:

- improve title versus source-filename resolution rules
- improve section derivation and text-unit joining behavior
- reduce cases where stored filenames leak into title-like fields
- reduce empty or low-signal text inputs reaching profile and evidence stages

Focus symptoms:

- titles falling back poorly
- source filename mismatches
- sections too coarse or missing
- text-unit joins dropping important context or duplicating context

Exit criteria:

- document profile outputs on representative collections show materially better
  title/source fidelity
- section and text-unit behavior no longer blocks downstream evidence parsing

### Workstream 2: Improve Paper-Facts And Evidence-View Quality

Goal:

- improve sample, method, condition, baseline, result, and traceback quality
  so evidence views stop carrying primary-fact responsibilities they should not
  own

Primary changes:

- improve sample, method, result, condition, and baseline extraction
- tighten traceback requirements for the fact layer and for evidence cards
- improve how evidence cards are projected from stronger underlying facts
- reduce weak cards that do not support collection-facing review

Focus symptoms:

- cards with vague claim text
- weak or missing sample/result linkage
- weak or missing condition capture
- poor linkage back to source text
- too many cards that add little review value

Exit criteria:

- paper facts are grounded enough to inspect one paper coherently
- evidence cards are more grounded and collection-reviewable
- traceback quality is good enough for comparison assembly to trust

### Workstream 3: Improve Comparison Row Quality

Goal:

- make comparison rows more useful as the primary collection-facing judgment
  surface

Primary changes:

- tighten comparison inclusion rules
- improve comparability gating
- improve result-to-sample, condition, and baseline linkage before row
  projection
- suppress rows that are traceability-poor or structurally low value

Focus symptoms:

- noisy or repetitive comparison rows
- rows that compare weakly related evidence
- missing or inconsistent condition normalization
- rows that look structured but do not support real comparison

Exit criteria:

- comparison rows become a higher-signal review surface
- limited or not-comparable rows are still visible when useful, but no longer
  dominate the collection output

### Workstream 4: Add Core Quality Benchmarks And Regression Guards

Goal:

- stop tuning parsing quality purely by anecdote

Primary changes:

- define a small representative benchmark corpus
- add expectation-oriented tests for document profiles, paper facts, evidence
  cards, and comparison rows
- add regression assertions around known failure modes
- track a short failure taxonomy to guide iteration order

Initial failure taxonomy should at least cover:

- title/source identity errors
- section boundary errors
- fact grounding and anchor errors
- missing or weak condition capture
- noisy comparison assembly

Exit criteria:

- Core quality changes can be evaluated against repeatable examples
- regressions fail in tests rather than being rediscovered manually

## Execution Order

1. Build a small benchmark corpus and failure taxonomy.
2. Fix document parsing and identity fidelity first.
3. Improve paper-facts extraction over the cleaner parsing output.
4. Improve evidence-view projection and comparison assembly over the stronger
   fact output.
5. Lock in regression checks before resuming adapter or Goal Consumer work.

## File Change Plan

### Primary Code Areas

- `application/documents/service.py`
- `application/documents/source_service.py`
- `application/documents/section_service.py`
- `application/evidence/service.py`
- `application/comparisons/service.py`
- `application/workspace/service.py` only if summary semantics need to reflect
  improved Core quality signals

### Primary Test Areas

- `tests/unit/services/test_document_profile_service.py`
- `tests/unit/services/test_evidence_backbone_services.py`
- `tests/unit/services/test_collection_service.py` only when input assumptions
  change
- `tests/unit/services/test_workspace_service.py`
- `tests/integration/services/test_task_runner.py`
- `tests/integration/test_app_layer_api.py`

### Possible New Fixtures

- a small benchmark fixture corpus under `tests/fixtures/` or a nearby
  backend-local test location
- expectation files for profile, evidence, and comparison quality checks

## Verification

### Quality Verification

- representative collections produce better document profile identity fields
- evidence cards improve in grounding and traceback usefulness
- comparison rows improve in signal-to-noise ratio and comparability semantics

### Regression Verification

- current upload, indexing, workspace, and protocol-capable flows remain intact
- Core quality work does not bypass current artifact ownership boundaries
- Source & Collection Builder still terminates at collection boundaries only

### Deferral Verification

- no new real adapter is required to validate this wave
- no Goal Consumer route or service is introduced in this wave

## Risks And Guardrails

- quality work can sprawl into architecture churn if boundaries are not held
  fixed
- evidence tuning before parsing cleanup can create brittle heuristics
- comparison tuning before evidence cleanup can optimize noise
- benchmark scope can grow too large; start with a small but representative set

## Related Docs

- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md)
- [`goal-core-source-contract-follow-up-plan.md`](../backend-wide/goal-source-core-layering/contract-follow-up.md)
- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
- [`claim-traceback-navigation-implementation-plan.md`](claim-traceback-navigation-implementation-plan.md)
- [`source-collection-builder-normalization-plan.md`](../source/source-collection-builder-normalization-plan.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
