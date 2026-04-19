# Five-Layer Contract Follow-up Plan

This document keeps its historical path for continuity, but it now records the
contract-freeze follow-up for the five-layer architecture.

## Purpose

This child plan freezes the contracts and boundaries between:

- Goal Brief / Intake
- Source & Collection Builder
- Research Intelligence Core
- Goal Consumer / Decision Layer
- Derived Views / Downstream

Its job is not to add feature breadth first. Its job is to prevent boundary
drift while the new goal-related surfaces are still young.

## Why This Follow-up Exists

Core stabilization work has already moved key semantics into a safer baseline:

- Core parsing seam extraction is in place
- `*_generated` versus `*_ready` semantics are explicit
- protocol branch behavior is aligned with Core-first artifact readiness

The next architecture risk is semantic confusion:

- Goal Brief / Intake can be mistaken for the full Goal layer
- Source & Collection Builder can start writing Core semantics directly
- Goal Consumer can emerge later as a second fact model if its boundary is not
  frozen early
- derived views can drift back into semantic ownership if Core dependency rules
  are not kept explicit

## Scope

This follow-up covers:

- five-layer ownership and dependency-direction contract freeze
- Goal Brief / Intake contract clarification
- Source & Collection Builder handoff contract
- Goal Consumer input/output constraints over Core artifacts
- Derived View dependency rules
- verification matrix for cross-layer contract enforcement

This follow-up does not cover:

- graph semantic cutover details (`/graph`, `/graphml`)
- crawler ranking or external provider selection
- protocol extraction algorithm upgrades
- frontend IA redesign

## Contract Decisions

### Goal Brief / Intake Contract

Goal Brief / Intake defines the problem and optionally initiates collection
building.

Current public contract:

- `research_brief`
- `coverage_assessment`
- `seed_collection`
- `entry_recommendation`

Boundary rules:

- this surface does not emit Core artifacts
- `seed_collection` is a collection-builder handoff object, not a Core fact
  object
- current `coverage_assessment` on `goals/intake` is a coarse intake-side hint
  for collection building and should not be treated as the final Goal Consumer
  coverage assessment

### Source & Collection Builder Contract

Source & Collection Builder owns document gathering, normalization, and
collection assembly.

Target handoff shape:

- `documents`
- `text_units`
- `source_metadata`

Boundary rules:

- this layer may create or enrich collections
- it must not emit `document_profiles`, `evidence_cards`, or
  `comparison_rows`
- it must not set Core or downstream readiness fields directly

### Research Intelligence Core Contract

Core remains the only place that turns collection material into stable research
objects:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`
- optional downstream `protocol_candidates`
- optional downstream `protocol_steps`

Core lifecycle semantics remain authoritative:

- `*_generated` answers whether a stage completed generation attempt
- `*_ready` answers whether the artifact is consumable by primary collection
  surfaces

### Goal Consumer / Decision Contract

Goal Consumer reads Core artifacts and organizes them around a user goal.

Allowed outputs:

- grounded coverage assessment
- goal-oriented filtered slices
- gap detection
- clue ranking
- next-step decision support

Boundary rules:

- it must consume Core artifacts rather than replace them
- it must preserve Core traceback and comparability semantics
- it must not create an alternate fact model parallel to the Core

### Derived Views / Downstream Contract

Derived Views must consume or derive from Core outputs.

Examples:

- protocol
- graph
- reports
- export

Boundary rules:

- they remain downstream of Core readiness and Core suitability
- they do not become the primary system fact model

## Execution Waves

### Wave A: Freeze The Five-Layer Contract Language

Goal:

- make the five-layer model explicit everywhere that currently implies the old
  three-layer shorthand

Primary changes:

- update architecture and plan docs to distinguish Goal Brief from Goal
  Consumer
- document collection-builder handoff semantics clearly
- document derived-view dependency rules clearly

Exit criteria:

- one unambiguous contract language exists across architecture, plan, and API
  docs

### Wave B: Clarify The Current Goal Brief / Intake Surface

Goal:

- keep the current `goals/intake` surface small and correctly placed

Primary changes:

- document current `goals/intake` as Goal Brief / Intake only
- preserve current response contract while explicitly labeling
  `coverage_assessment` as intake-side and provisional
- keep collection handoff explicit through `seed_collection`

Exit criteria:

- backend readers no longer mistake `goals/intake` for the full Goal Consumer
  layer

### Wave C: Harden Source & Collection Builder

Goal:

- standardize import outputs from upload and future adapters

Current child execution entrypoint:

- [`source-collection-builder-normalization-plan.md`](../source/source-collection-builder-normalization-plan.md)

Primary changes:

- define one normalized handoff seam under collection-builder or ingestion-owned
  code
- align upload path and adapter path to emit the same normalized import shape
- keep adapter implementation replaceable behind the same handoff contract

Exit criteria:

- upload and adapter ingestion both terminate at collection boundaries
- Core receives consistent normalized inputs regardless of source channel

### Wave D: Add Goal Consumer / Decision Contract

Goal:

- define the post-Core goal-oriented consumer without weakening Core ownership

Primary changes:

- specify Goal Consumer inputs as Core artifacts
- specify allowed outputs such as grounded coverage, gap, ranking, and
  next-step support
- prohibit alternate fact production explicitly

Exit criteria:

- Goal Consumer is documented as a Core consumer, not a Core replacement

### Wave E: Align Derived Views / Downstream

Goal:

- make downstream dependency on Core semantics explicit

Current child execution entrypoint:

- [`core-first-product-surface-cutover-plan.md`](core-first-product-surface-cutover-plan.md)

Primary changes:

- align protocol, graph, and report positioning language around Core
  dependency
- keep protocol conditional and graph/report secondary

Exit criteria:

- downstream surfaces are documented as consumers or projections of Core
  outputs

### Wave F: Cross-Layer Contract Guard Tests

Goal:

- enforce contracts through tests rather than conventions

Primary changes:

- add app-layer tests for Goal Brief to collection convergence
- add contract tests that Source & Collection Builder cannot emit Core
  artifacts
- add future Goal Consumer tests that require Core-backed inputs
- add readiness matrix assertions for `generated` versus `ready` semantics at
  route boundaries

Exit criteria:

- contract invariants fail fast in tests when boundaries are violated

## File Change Plan

### Docs And Contracts

- `docs/specs/api.md`
- `docs/architecture/goal-core-source-layering.md`
- this follow-up plan

### Goal Brief / Intake

- `application/goals/`
- `controllers/goals.py`
- `controllers/schemas/goals.py`

### Source & Collection Builder

- `application/collections/`
- `infra/ingestion/`
- upload path and future adapter path integration

### Goal Consumer / Decision Layer

- future goal-consumer logic under `application/goals/` or a nearby
  goal-oriented package
- future route or workspace surfaces that consume Core outputs

### Verification

- `tests/application/` slices for Goal Brief and collection handoff
- `tests/controllers/` slices for Goal Brief route semantics
- `tests/integration/` slices for goal-first versus paper-first convergence
- future Goal Consumer slices over Core outputs

## Acceptance Matrix

- Goal Brief routes return brief-and-handoff objects only, not Core artifacts.
- `seed_collection` always identifies a collection handoff, not a research fact
  object.
- Source & Collection Builder feeds collections with normalized import units
  only.
- Core remains the only producer of evidence/comparison artifacts.
- Goal Consumer outputs remain downstream of Core artifacts.
- protocol, graph, and reports remain downstream of Core.
- readiness semantics remain stable with `generated` and `ready` split.

## Risks

- current field names such as `coverage_assessment` can be overread as final
  decision-layer semantics unless the docs keep stressing the intake-side
  limitation
- Source & Collection Builder hardening can regress upload behavior if
  normalization contracts are not tested against current fixtures
- Goal Consumer can sprawl into a second fact model if it is not kept strictly
  Core-backed

## Recommended Reading Order

1. [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
2. [`core-stabilization-and-seam-extraction-plan.md`](../core/core-stabilization-and-seam-extraction-plan.md)
3. [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
4. this follow-up plan
5. [`core-derived-graph-follow-up-plan.md`](../derived/core-derived-graph-follow-up-plan.md)

## Related Docs

- [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
- [`core-stabilization-and-seam-extraction-plan.md`](../core/core-stabilization-and-seam-extraction-plan.md)
- [`core-derived-graph-follow-up-plan.md`](../derived/core-derived-graph-follow-up-plan.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../specs/api.md`](../../specs/api.md)
