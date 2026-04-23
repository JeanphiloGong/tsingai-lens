# Backend Five-Layer Research Architecture

This document supersedes the earlier three-layer shorthand retained in this
file path for continuity.

## Summary

Lens backend should be described as a five-layer research system:

- Goal Brief Layer
- Source & Collection Builder
- Research Intelligence Core
- Goal Consumer / Decision Layer
- Derived Views / Downstream

The system may accept a goal-first or paper-first entry, but it must not let
goal logic produce research facts directly. All stable research facts must be
produced by one collection-backed Core backbone.

## Context

Current backend docs already establish that:

- `workspace` is the primary collection-facing entry surface
- `document_profiles`, the paper-facts family, `evidence_cards`, and the
  comparable-result substrate are the intended backbone
- `protocol/*` is a conditional downstream branch rather than the default
  center of the workflow

The main architecture correction is therefore not to weaken the Core. It is to
place Goal semantics on both sides of the Core correctly:

- before the Core, Goal Brief defines the problem
- after the Core, Goal Consumer organizes judgment support around that problem

This avoids the unstable shape where goal-first entry, retrieval, or chat
logic attempts to define system facts directly.

## Scope

This proposal covers backend-local layering, dependency direction, and
collection handoff semantics.

It does not:

- redefine shared product positioning
- choose external search providers or crawler vendors
- define frontend page design
- replace the existing business-domain package map

## Proposed Change

### Core Logic In One Sentence

Users arrive with a goal, but the system must not jump from goal to answer.
It must first turn collection material into traceable, comparable research
objects, then let goal-oriented consumers interpret those objects.

### Layer 1: Goal Brief Layer

Goal Brief owns problem definition only.

Responsibilities:

- capture the target material or system
- capture target property or research question
- capture intent such as `explore`, `compare`, `design`, or `verify`
- capture constraints such as temperature, process route, or application
  context
- capture evidence expectation when supported by the public contract

Boundary rules:

- it defines the question but does not produce research facts
- it may seed collection-building work but must not claim evidence-backed
  conclusions

Current backend note:

- the current `POST /goals/intake` surface should be interpreted as a thin
  Goal Brief / Intake endpoint
- it is not the full Goal Consumer / Decision Layer

### Layer 2: Source & Collection Builder

This layer owns how material is gathered and assembled into a collection.

Responsibilities:

- file upload and local ingestion
- search adapters, connectors, and crawler-style acquisition
- deduplication and metadata normalization
- collection creation and collection enrichment
- collection seeding for goal-first entry

Boundary rules:

- it answers which documents belong in scope for a research task
- it may normalize and import material, but it must not emit research facts
- it must terminate at collection boundaries, not at Core artifact boundaries

### Layer 3: Research Intelligence Core

This is the semantic center of the system.

Responsibilities:

- turn a collection into research objects
- own document profiling, evidence extraction, comparison assembly,
  traceback, warnings, and protocol gating
- provide the stable collection-facing workspace and artifact navigation

Primary artifacts:

- `document_profiles`
- paper-facts family
- `evidence_cards`
- `comparable_results`
- `collection_comparable_results`
- downstream `comparison_rows` projection
- optional downstream `protocol_candidates`
- optional downstream `protocol_steps`

Boundary rule:

Only the Core may produce the stable research fact objects used by the rest of
the system.

### Layer 4: Goal Consumer / Decision Layer

This layer consumes Core outputs in the context of a user goal.

Responsibilities:

- goal-oriented filtering over Core artifacts
- coverage assessment grounded in Core artifacts
- gap detection over baselines, test conditions, and variable coverage
- clue ranking and next-step guidance
- decision support views built from Core facts without replacing them

Boundary rules:

- it may reorganize, filter, rank, and assess Core outputs
- it must not create a second fact model parallel to the Core
- it must not bypass Core traceback and comparability semantics

### Layer 5: Derived Views / Downstream

These are views or downstream capabilities derived from the Core.

Examples:

- protocol
- graph
- reports
- export
- future SOP drafts

Boundary rules:

- these surfaces consume or derive from Core artifacts
- they must not redefine the primary system facts
- protocol remains conditional rather than becoming the default backbone

### Collections And Indexing As Handoff Seams

The collection object is the shared handoff unit between Goal Brief, Source &
Collection Builder, and the Core.

Indexing is a pipeline orchestrator, not a product-facing layer. Its role is to
coordinate artifact build from collection inputs into Core outputs and optional
downstream branches.

### Frozen Contract Surface

Current contract-freeze target for the five-layer model:

- Goal Brief / Intake currently returns:
  `research_brief`, `coverage_assessment`, `seed_collection`,
  `entry_recommendation`
- the current `coverage_assessment` field on `goals/intake` is only a coarse
  intake-side hint for collection building, not the final Goal Consumer
  coverage assessment
- Source & Collection Builder handoff should converge on normalized import
  units such as `documents`, `text_units`, and `source_metadata`
- Core remains the only layer that may emit:
  `document_profiles`, paper facts, `evidence_cards`,
  `comparable_results`, `collection_comparable_results`, downstream
  `comparison_rows` projection, and downstream protocol artifacts
- Goal Consumer may read Core outputs and emit filtered, ranked, gap, and
  next-step views only
- Derived Views must consume or derive from Core outputs rather than inventing
  alternate product semantics

Readiness semantics remain Core-owned:

- `*_generated`: stage generation attempt completed and artifact file exists
- `*_ready`: artifact is consumable by collection-facing primary surfaces

The active child execution plan for this freeze is:

- [`../plans/goal-core-source-contract-follow-up-plan.md`](../plans/backend-wide/goal-core-source-contract-follow-up-plan.md)

## Current Backend Mapping

### Already Aligned

- `application/collections/` already owns collection lifecycle
- upload already terminates at collection boundaries
- `workspace` already acts as the primary collection-facing navigation surface
- `document_profiles` is already a real backend artifact
- indexing already runs Core stages before the protocol branch
- protocol generation is already gated by document suitability
- `application/goals/` now exists as a thin Goal Brief / Intake surface

### Still Missing Or Blurred

- Source & Collection Builder does not yet expose one explicit normalized
  handoff seam across upload, search, crawler, and goal-seeding paths
- the current `goals/intake` surface is easy to misread as the full Goal
  layer, even though it is only the briefing side
- a true Goal Consumer / Decision Layer over Core outputs does not exist yet
- graph, reports, and protocol are not yet documented everywhere as derived
  Core consumers consistently enough

## Package Direction

This layering view complements the existing backend domain map rather than
replacing it.

Near-term implications:

- treat `application/goals/` as the place for Goal Brief / Intake today, and
  make any future Goal Consumer logic explicit there rather than blending the
  two concerns invisibly
- keep `application/collections/` and `infra/ingestion/` as the Source &
  Collection Builder path
- keep `application/documents/`, `application/evidence/`,
  `application/comparisons/`, and `application/workspace/` as the Core-owned
  artifact path
- keep `application/protocol/`, `application/graph/`, and
  `application/reports/` as derived or downstream consumers rather than
  alternate fact sources
- keep shared parsing helpers under a Core-owned seam, not under protocol-owned
  modules

Controller implications:

- `goals/*` should currently be read as Goal Brief / Intake only
- collection-facing primary review routes should continue to converge on
  `/workspace`, `/documents/profiles`, `/evidence/cards`, and `/comparisons`
- any future Goal Consumer routes must consume Core outputs rather than
  replacing the collection-backed artifact URLs
- `protocol/*` remains a downstream branch, not a parallel research fact model

## File Change Plan

1. Keep hardening the Core backbone so real collections reliably emit
   `document_profiles`, `evidence_cards`, and the comparable-result substrate
   with row projection downstream.
2. Harden the Source & Collection Builder seam so upload, search, crawler, and
   goal seeding converge on one collection handoff shape.
3. Keep Goal Brief / Intake intentionally thin and explicit.
4. Add a true Goal Consumer / Decision layer over Core outputs.
5. Keep protocol, graph, and report semantics downstream of the Core.

## Verification

- goal-first and paper-first entry paths both converge on the same collection
  and Core artifact URLs
- Source & Collection Builder does not emit evidence or comparison artifacts
  directly
- Core remains the only producer of stable research fact objects
- Goal Consumer outputs remain traceable back to Core artifacts
- protocol, graph, and reports behave as derived or downstream views rather
  than as primary fact definitions

## Risks

- keeping the old file path can mislead readers unless the five-layer framing
  is explicit in the document body
- the current `coverage_assessment` field can be over-read as a final decision
  signal unless docs clearly mark it as intake-side and provisional
- Goal Consumer can drift into a second fact model if it does more than filter,
  assess, and organize Core outputs
- Derived Views can reclaim semantic ownership if Core-derived dependency rules
  are not kept explicit

## Related Docs

- [`../plans/goal-core-source-implementation-plan.md`](../plans/backend-wide/goal-core-source-implementation-plan.md)
- [`../plans/goal-core-source-contract-follow-up-plan.md`](../plans/backend-wide/goal-core-source-contract-follow-up-plan.md)
- [`overview.md`](overview.md)
- [`domain-architecture.md`](domain-architecture.md)
- [`core-comparison/README.md`](core-comparison/README.md)
- [`../plans/v1-api-migration-notes.md`](../plans/historical/v1-api-migration-notes.md)
- [`../plans/evidence-first-parsing-plan.md`](../plans/historical/evidence-first-parsing-plan.md)
- [`../specs/api.md`](../specs/api.md)
