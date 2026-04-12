# Backend Goal/Core/Source Layering

## Summary

This document records a backend-local proposal for expressing Lens as a
goal-driven research system with a collection intelligence core.

The backend should distinguish three layers:

- Goal Layer
- Research Intelligence Core
- Source / Acquisition Layer

This layering view complements the existing business-domain packaging. Its job
is to clarify entry modes, protect the evidence/comparison backbone, and keep
search, crawler, and connector work outside research-judgment logic.

## Context

Current backend docs already establish that:

- `workspace` is the primary collection-facing entry surface
- `document_profiles`, `evidence_cards`, and `comparison_rows` are the intended
  parsing backbone
- `protocol/*` remains a conditional downstream branch rather than the default
  center of the workflow

Current backend code fits that direction only partially:

- collections and ingestion already accept uploaded files and create a
  collection-scoped working set
- indexing already produces GraphRAG outputs and `document_profiles`
- workspace already exposes collection-facing readiness, warnings, and links
- real `evidence_cards` and `comparison_rows` are not yet implemented for
  non-mock collections
- document profiling still depends on protocol-owned helpers, which shows that
  the Core versus Protocol boundary is not yet clean

The main architecture question is therefore not whether Lens should keep a
collection intelligence layer. It is how to add a goal-driven entry layer
without weakening the shared evidence/comparison backbone.

## Scope

This proposal covers backend-local layering and dependency direction.

It does not:

- redefine shared product positioning
- choose external search providers or crawler vendors
- define frontend copy or page design
- replace the existing business-domain package map

## Proposed Change

### Product-Facing Entry Model

The backend should support two entry modes that converge on one Core:

1. Start from papers:
   upload or import files, form a collection, then enter the Core
2. Start from research goal:
   build a research brief, seed a collection, then enter the same Core

Both paths must resolve to the same collection-backed artifact model and the
same workspace navigation. The system should not allow separate fact models for
goal-first versus paper-first flows.

### Goal Layer

The Goal Layer owns purpose-driven entry and collection seeding.

Responsibilities:

- accept research intent, target material or property, and explicit constraints
- build a `research_brief`
- assess whether evidence coverage is direct, indirect, sparse, or absent
- produce retrieval or seeding recommendations
- create or update a `seed_collection`
- recommend whether the user should enter comparison mode or exploratory mode

Non-goals:

- it must not generate `comparison_rows`, protocol steps, or final research
  judgments on its own
- it must not bypass the Core artifact path

Primary contract objects:

- `research_brief`
- `coverage_assessment`
- `seed_collection`
- `entry_recommendation`

### Research Intelligence Core

This is the backend's semantic center. It should not be described as a generic
data layer.

Responsibilities:

- convert a collection into research artifacts
- own document profiling, evidence extraction, comparison assembly, traceback,
  warnings, and protocol gating
- provide the stable collection-facing workspace and artifact navigation
- allow protocol only as a downstream branch after Core-owned suitability and
  readiness checks

Primary artifacts:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`
- optional `protocol_candidates`
- optional `protocol_steps`

Boundary rule:

Only the Core may turn a collection into evidence-backed research judgments or
comparison views.

### Source / Acquisition Layer

The Source / Acquisition Layer owns how external material enters the system.

Responsibilities:

- file upload and local ingestion
- PDF or text normalization
- external search adapters
- crawler and connector integrations
- source metadata capture and raw document import

Boundary rule:

This layer may bring material into the system, but it must not define research
semantics, comparison logic, or protocol suitability.

### Collections And Indexing As Handoff Seams

The collection object is the shared handoff unit between entry modes and the
Core. It should not be treated as Goal-only or Source-only state.

Indexing is a pipeline orchestrator, not a user-facing product layer. Its role
is to coordinate artifact build from collection inputs into Core outputs and an
optional protocol branch.

## Current Backend Mapping

### Already Aligned With The Core

- `workspace` already acts as the primary collection-facing navigation surface
- `document_profiles` is already a real backend artifact
- protocol generation is already gated by document suitability
- collection-level warnings and readiness states already reflect comparison-
  first semantics

### Still Missing Or Blurred

- `evidence_cards` and `comparison_rows` are still mock-only for real
  collections
- document profiling still imports protocol-owned helpers, which keeps protocol
  too close to the main parsing backbone
- a first-class Goal Layer does not exist yet
- the Source Layer currently covers upload and PDF extraction only; external
  acquisition seams remain thin

## Package Direction

This layering view complements the existing backend domain map rather than
replacing it.

Near-term implications:

- add a dedicated `application/goals/` package only when goal-driven entry is
  implemented
- keep `application/documents/`, `application/evidence/`,
  `application/comparisons/`, and `application/workspace/` as the Core-owned
  artifact path
- keep `application/protocol/` as a downstream branch that depends on Core
  outputs or Core-owned suitability decisions
- expand `infra/ingestion/` for search adapters, connectors, and crawler-style
  acquisition
- treat `application/collections/` as the collection handoff boundary shared by
  Goal and Source concerns
- move shared parsing helpers that are currently under `application/protocol/`
  into a Core-owned seam before deepening evidence or comparison work

Controller implications:

- a future goal-driven entry surface should live under its own goal-oriented
  route package rather than being hidden behind protocol or query routes
- the collection-facing artifact routes should continue to converge on
  `/workspace`, `/documents/profiles`, `/evidence/cards`, and `/comparisons`
- `protocol/*` must remain a dependent branch rather than a parallel research
  fact model

## File Change Plan

1. Complete real `evidence_cards` and `comparison_rows` services and endpoints
   for non-mock collections.
2. Refactor shared parsing helpers out of protocol-owned modules so document,
   evidence, and comparison services do not depend on protocol packages.
3. Update indexing orchestration so the post-index sequence is
   `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`,
   with protocol gated by Core outputs.
4. When goal-driven entry is implemented, add a Goal Layer surface that owns
   briefing, coverage assessment, and collection seeding only.
5. Expand acquisition adapters under infrastructure boundaries without allowing
   them to bypass collection creation or Core artifact generation.

## Verification

- paper-first and goal-first entry paths both produce a collection that lands
  in the same workspace and artifact URLs
- non-mock collections can return `document_profiles`, `evidence_cards`, and
  `comparison_rows` without protocol dependence
- protocol remains unavailable or limited when the Core marks collections as
  unsuitable
- acquisition adapters can only feed collections; they do not produce
  evidence or comparison artifacts directly
- workspace continues to expose comparison-first readiness and warnings

## Risks

- the word `layer` may be confused with the business-domain package map unless
  docs keep those views separate
- collections sit at the handoff between layers and can accumulate mixed
  responsibilities if boundaries stay implicit
- a future goal-driven agent could bypass the Core and weaken traceability
- refactoring protocol-owned helpers into Core-owned seams may create temporary
  duplication during migration

## Related Docs

- [`../plans/goal-core-source-implementation-plan.md`](../plans/goal-core-source-implementation-plan.md)
- [`overview.md`](overview.md)
- [`domain-architecture.md`](domain-architecture.md)
- [`../plans/v1-api-migration-notes.md`](../plans/v1-api-migration-notes.md)
- [`../plans/evidence-first-parsing-plan.md`](../plans/evidence-first-parsing-plan.md)
- [`../specs/api.md`](../specs/api.md)
