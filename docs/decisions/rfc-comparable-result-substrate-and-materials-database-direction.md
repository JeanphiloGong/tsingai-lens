# RFC Comparable-Result Substrate and Materials Database Direction

## Summary

This RFC records a project-level architecture direction for Lens after the
paper-facts and comparable-result decisions.

The core judgment is:

- Lens v1 should remain a collection-first, evidence-first comparison product
- the semantic backbone that powers that product should not be understood as a
  collection-local row system
- the same backbone should be able to grow naturally into a reusable,
  literature-backed materials facts substrate
- that substrate should support later expansion directions beyond the current
  comparison workspace

In practical terms, the intended long-term interpretation is:

`paper facts -> comparable results -> collection-scoped assessment -> projection/cache`

This RFC is about shared direction. It does not replace backend-owned rollout
plans.

## Relationship To Current Docs

This RFC should be read with:

- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)

The backend-owned implementation companions are:

- [`../../backend/docs/architecture/core-comparison/decision.md`](../../backend/docs/architecture/core-comparison/decision.md)
- [`../../backend/docs/plans/historical/comparable-result/core-comparable-result-evolution-roadmap-plan.md`](../../backend/docs/plans/historical/comparable-result/core-comparable-result-evolution-roadmap-plan.md)

This RFC should not be treated as a backend implementation plan or as an
immediate API contract update.

## Context

Lens v1 is correctly positioned as a comparison-first and evidence-first
literature intelligence system for research collections.

That product boundary is still right.

At the same time, the repository has already moved toward a stronger semantic
backbone:

- durable paper facts matter more than fluent summaries
- comparison assembly depends on normalized result and context semantics rather
  than on row shells alone
- collection-facing rows, graph views, and report views behave more like
  projections over a stronger substrate than like first-pass semantic objects

The remaining gap is shared project language.

Without a project-level statement, the repository can keep slipping into one of
two mistaken interpretations:

- the current comparison workspace is the whole architecture
- or the only future beyond the workspace is a generic paper chat or agent
  shell

Neither is the right long-term direction.

## Problem Statement

If Lens continues to describe its architecture mainly through collection-local
comparison rows, three problems follow.

### 1. The Semantic Center Looks Too Local

The system will keep treating collection scope as if it owns the semantics
rather than understanding collection as one working boundary over reusable
research facts.

### 2. The Materials Direction Looks Like A One-Off Workflow

The materials vertical can look like a temporary workflow specialization
instead of the first proving ground for a broader evidence-backed literature
facts substrate.

### 3. Future Expansion Paths Stay Implicit

The repository will struggle to explain how current work relates to later
directions such as:

- literature-backed materials database behavior
- cross-collection reuse
- corpus-level retrieval
- benchmark or landscape views
- agent-readable structured research memory

If those paths stay implicit, later product and architecture work will keep
reopening already-settled semantic questions.

## Proposed Direction

### 1. Keep Lens V1 Collection-First At The Product Surface

The primary Lens v1 acceptance surface should remain the collection comparison
workspace and its evidence-backed review flows.

This RFC does not change the current product center into:

- a generic paper chat tool
- a standalone database browser
- an autonomous research agent

The collection-facing comparison workflow remains the first proving surface.

### 2. Treat The Core Backbone As A Reusable Semantic Substrate

The architecture should be understood in four layers:

1. `paper facts`
   one-document research semantics such as samples, methods, conditions,
   baselines, results, and anchors
2. `comparable results`
   reusable normalized comparison-semantic units derived from paper facts
3. `collection-scoped assessment`
   inclusion, ordering, and comparability judgment inside one working scope
4. `projection/cache`
   rows, evidence views, graph views, report payloads, and exports

This layered interpretation matters because it lets the repository preserve the
current collection workflow without making collection-local projections the
source of truth.

### 3. Treat `collection` As Working Scope Rather Than Semantic Ownership

`collection` should remain the primary user-facing working boundary in Lens v1.

But architecturally it should be understood as:

- a working set
- a review scope
- a saved comparison context

It should not be understood as:

- the permanent owner of semantic research facts
- the only identity boundary for reusable comparison units
- the long-term ceiling of the architecture

### 4. Treat `ComparableResult` As The Bridge Object

The key bridge from the current product to the longer-term substrate is the
comparable-result layer.

That layer matters because it is the first place where:

- one document result becomes reusable outside one UI row
- normalized comparison identity becomes stable
- collection-local assessment can be separated from reusable semantics

In other words, `ComparableResult` is not only a backend cleanup detail. It is
the semantic bridge between:

- today's collection comparison product
- tomorrow's reusable literature-backed facts substrate

## Long-Term Architecture Direction

### Materials Database Direction

For the first vertical, the natural long-term direction is a
literature-backed materials database.

That does not mean Lens should immediately reposition itself as a traditional
database product.

It means the current evidence-backed comparison backbone should be able to
evolve into a substrate where users and agents can reliably ask questions such
as:

- what comparable conductivity results exist for this material family
- which process routes or baselines recur across papers
- what evidence-backed result patterns appear across collections
- which claims remain weak because condition or baseline context is missing

The database-like value comes from structured, traceable literature facts, not
from abandoning the comparison-first product discipline.

### Additional Expansion Directions

If the substrate is kept clean, the same architecture can later support more
than one future surface.

Examples include:

- document-first semantic inspection over one paper's facts and results
- cross-collection reuse of the same comparable-result identity
- corpus-level retrieval over normalized results and context
- benchmark, leaderboard, and trend views derived from reusable facts
- contradiction, gap, and evidence-density analysis
- agent-readable structured literature memory for planning and review workflows

These are not separate architecture bets.

They are natural projections or retrieval modes over the same substrate.

## Why This Direction Fits Lens

This direction preserves the core Lens philosophy:

- evidence before fluent generation
- comparison before isolated summary
- traceability before opaque convenience

It also reduces a common future risk:

the repository does not need to choose between being a trustworthy comparison
system and being a reusable literature-facts substrate.

The comparison product is how Lens proves value first.
The substrate direction is how Lens compounds that value later.

## Guardrails

This direction should be interpreted with four guardrails.

### 1. Do Not Replace The Lens V1 Acceptance Surface Prematurely

The collection comparison workspace remains the primary Lens v1 proving
surface.

### 2. Do Not Let Projection Records Become Semantic Source Of Truth

Rows, cards, graphs, reports, and exports remain downstream projections.

### 3. Do Not Drop Evidence And Traceability For Database-Like Convenience

The future materials-database direction only makes sense if the reusable
substrate remains evidence-backed and inspectable.

### 4. Do Not Collapse Everything Into Materials-Only Product Language

Materials science is the first vertical, not the permanent ceiling of Lens.

## Shared Implications

### Shared Docs

Shared docs should describe the long-term direction as:

- collection-first at the current product surface
- substrate-oriented underneath
- capable of growing into literature-backed database and retrieval directions

### Contracts

Current shared contracts should continue to describe the current accepted Lens
surface until implementation cutovers are actually accepted.

This RFC should not be used to silently rewrite current public contracts ahead
of real cutover work.

### Backend Plans

Backend plans remain the authority for:

- artifact rollout
- storage split
- read-path cutover
- service-boundary changes

This RFC only provides the shared project-level direction that explains why
that backend work matters beyond the local implementation slice.

## Acceptance Signals

This RFC is working if later repository changes can be explained without
reopening the same question every time.

Examples:

- a new document-first facts surface is described as another read path over the
  same substrate
- a future materials benchmark view is described as a projection over reusable
  comparable results and traceable facts
- agent workflows consume structured facts and comparable results rather than
  bypassing the evidence backbone

## Related Docs

- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)
- [System Overview](../overview/system-overview.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Paper Facts And Comparison Current State](../architecture/paper-facts-and-comparison-current-state.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](rfc-paper-facts-primary-domain-model.md)
