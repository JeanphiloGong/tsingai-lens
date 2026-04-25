# Core Semantic Build Packaging Alignment Plan

## Summary

This document records a focused Core child plan for packaging and ownership
cleanup around the current semantic build path.

The target is not to introduce a new backend layer. The target is to make the
existing Source-to-Core handoff and Core semantic build path easier to reason
about, easier to benchmark, and easier to change without spreading one
semantic-extraction concern across unrelated `application/core/*` files.

This plan sits under the existing Core structured-extraction cutover wave:

- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)

It is intentionally narrower than that parent wave. The parent wave decides
that Core semantic extraction should hard-cut to schema-bound LLM parsing.
This child plan decides how that semantic build path should be packaged inside
the backend so the ownership seam stays explicit.

## Why This Child Plan Exists

The current high-level dependency direction is already right:

- Source produces structural handoff artifacts such as `documents`, `blocks`,
  `table_rows`, and `table_cells`
- Core consumes those artifacts to build `document_profiles`, paper facts, and
  deterministic Core-derived views
- downstream surfaces consume Core outputs

The problem is not a missing layer.

The problem is that one concrete Core responsibility, semantic build from
Source artifacts, is currently scattered across flat files under
`application/core/`:

- `document_profile_service.py`
- `paper_facts_service.py`
- `llm_extraction_models.py`
- `llm_extraction_prompts.py`
- `llm_structured_extractor.py`
- `core_semantic_version.py`

That shape creates three practical problems:

- the semantic-build path is mixed together with downstream Core consumers such
  as comparison and workspace services
- the business-owned LLM extraction contract and the infra-owned transport seam
  are close enough to be confused but not close enough to read as one coherent
  slice
- benchmarking, latency diagnostics, and extraction-path refactors require
  readers to bounce between service, prompt, schema, and extractor files
  without one obvious package boundary

## Decision

Keep the existing layering, but package the Core semantic build path as one
explicit submodule under `application/core/`.

The intended interpretation should become:

- Source owns structural artifact production
- Core semantic build owns Source-artifact consumption and schema-bound
  semantic extraction
- other Core services consume semantic-build artifacts rather than owning the
  extraction path themselves

This plan explicitly rejects:

- moving the semantic build path into Source
- introducing a new compatibility layer, wrapper, or facade just to preserve
  the current flat file layout
- moving OpenAI transport code into `application/`
- creating a generic `clients/`, `common/`, or `utils/` bucket under
  `application/core/`

## Scope

This plan covers:

- packaging `document_profiles` and paper-facts semantic build as one
  code-owned Core submodule
- grouping prompt, schema, and extraction orchestration files with the owning
  semantic-build path
- preserving the current `Source -> Core -> derived` ownership direction while
  making the Source-to-Core handoff seam more legible
- keeping the OpenAI-compatible transport implementation inside the owning Core
  extractor path unless a later wave explicitly re-separates that seam

This plan does not cover:

- changing Source artifact semantics
- redesigning comparison, evidence-card, workspace, graph, report, or protocol
  behavior
- changing public HTTP contracts
- solving LLM latency by packaging changes alone
- introducing fallback extraction paths or temporary package bridges

## Proposed Package Shape

### Current Shape

Today the relevant files are flat under `application/core/`:

- `document_profile_service.py`
- `paper_facts_service.py`
- `llm_extraction_models.py`
- `llm_extraction_prompts.py`
- `llm_structured_extractor.py`
- `core_semantic_version.py`
- `comparison_service.py`
- `workspace_overview_service.py`

That flat shape makes one semantic-build slice and two consumer slices appear
to be peer concerns at the same abstraction level.

### Target Shape

The Core semantic build path should move under one explicit subpackage such as:

```text
backend/application/core/
  semantic_build/
    __init__.py
    README.md
    document_profile_service.py
    paper_facts_service.py
    core_semantic_version.py
    llm/
      __init__.py
      schemas.py
      prompts.py
      extractor.py
```

The rest of `application/core/` should continue to host consumers and
collection-facing aggregators such as:

- `comparison_service.py`
- `workspace_overview_service.py`

### Why `semantic_build/llm/` Instead Of `clients/`

`clients/` would blur two different ownership concerns:

- business-owned extraction contracts, prompt design, and response schema
- infra-owned transport details

The extraction contract belongs to Core semantic build, not to infra and not
to a generic application client bag. The current transport implementation now
lives directly in the owning Core extractor path:

- [`../../../application/core/semantic_build/llm/extractor.py`](../../../application/core/semantic_build/llm/extractor.py)

Therefore:

- Core keeps `llm/prompts.py`, `llm/schemas.py`, and `llm/extractor.py`
- Core currently also owns the concrete OpenAI-compatible transport call path

## Ownership Boundary After Refactor

### Source

Source should continue to own:

- collection build orchestration
- artifact loading helpers
- structural handoff artifacts

Source should not become the owner of Core semantic extraction packaging.

### Core Semantic Build

`semantic_build/` should own:

- semantic build entrypoints for `document_profiles` and paper facts
- Core semantic artifact version invalidation
- the semantic-build prompt and schema contract
- bounded extraction units such as text windows and table rows

### Other Core Consumers

Other Core services should continue to consume semantic-build outputs rather
than co-owning extraction internals:

- comparison assembly
- workspace summary assembly

### Infra

`infra/llm/` should continue to own only the external-transport seam.

It should not absorb:

- Core prompt text
- Core extraction schema definitions
- Core semantic build orchestration

## Direct Move Plan

### Phase 1: Create The Owning Subpackage

- add `application/core/semantic_build/`
- add a narrow `README.md` that states this package consumes Source artifacts
  and produces Core semantic artifacts
- move `document_profile_service.py`, `paper_facts_service.py`, and
  `core_semantic_version.py` into the new package

### Phase 2: Group The Core-Owned LLM Contract

- move `llm_extraction_models.py` to `semantic_build/llm/schemas.py`
- move `llm_extraction_prompts.py` to `semantic_build/llm/prompts.py`
- move `llm_structured_extractor.py` to `semantic_build/llm/extractor.py`
- update imports directly at call sites instead of retaining forwarding files

### Phase 3: Repoint Core Consumers

- update `comparison_service.py`
- update `workspace_overview_service.py`
- update `collection_build_task_runner.py`
- update tests that import the moved services

### Phase 4: Reconfirm Documentation Boundaries

- update `application/core/README.md` so the semantic-build slice is explicit
- keep backend-wide architecture docs stable unless the package move changes an
  architecture claim rather than only local code placement

## Verification

### Behavioral Verification

- `document_profiles` behavior remains unchanged after package relocation
- paper-facts generation remains unchanged after package relocation
- comparison and workspace consumers continue to read the same Core artifacts
- no compatibility bridge or fallback package remains

### Verification Commands

- targeted backend unit tests for document profile and paper-facts services
- targeted backend unit tests for comparison and workspace consumers
- one production-like benchmark run through the real structured-parse path
  before and after the move to confirm packaging changes do not masquerade as
  latency fixes

## Risks

- if this move is done with forwarding files, the package shape will look
  cleaner while preserving the same ownership ambiguity
- if `semantic_build/` grows into another generic dumping ground, the refactor
  will only move the clutter rather than reducing it
- if the move is sold as a latency fix, it will create the wrong expectation;
  this plan is an ownership and maintainability cleanup first

## Related Docs

- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../../architecture/overview.md`](../../architecture/overview.md)
- [`../../../application/core/README.md`](../../../application/core/README.md)
- [`../../../application/source/README.md`](../../../application/source/README.md)
