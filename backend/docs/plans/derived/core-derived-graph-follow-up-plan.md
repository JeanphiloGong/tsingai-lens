# Core-Derived Graph Follow-up Plan

## Purpose

This document records the follow-up execution plan for evolving the collection
graph from a retained GraphRAG artifact browser into a Core-derived research
projection that consumes Lens research objects:

- `claim`
- `evidence`
- `condition_context`
- `comparability`

The plan is a child follow-up of
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
and should be executed after current Core stabilization waves are in a usable
state.

## Why This Follow-up Exists

Current graph behavior is stable as a retained secondary surface, but its
semantic center is still GraphRAG entity/relationship artifacts.

That means:

- graph is useful for relation browsing
- graph is weak for research judgment
- graph cannot directly express Core-first review questions such as:
  - which claims are evidence-grounded
  - which comparisons are blocked by missing baseline/test context
  - which conditions constrain apparent support/conflict

## Scope

This follow-up covers:

- backend graph semantic source-of-truth migration
- graph payload assembly from Core artifacts
- migration and cutover order for `/graph` and `/graphml`
- downgrade strategy for GraphRAG graph semantics into pipeline-only ownership

This follow-up does not cover:

- frontend graph framework replacement
- final graph interaction design language
- source acquisition provider selection

## Decision

The backend should adopt this sequence:

1. keep Source/Acquisition and Core extraction seams decoupled
2. introduce a Core-derived graph projection that reads Core artifacts
3. keep GraphRAG graph logic available during transition
4. cut over product graph semantics to Core-derived objects
5. degrade GraphRAG graph semantics to pipeline/system support only

This is a migration, not an immediate hard switch.

Current child execution entrypoint:

- [`core-derived-graph-cutover-implementation-plan.md`](core-derived-graph-cutover-implementation-plan.md)
- [`core-derived-graph-structure-and-drilldown-plan.md`](core-derived-graph-structure-and-drilldown-plan.md)
- [`core-derived-graph-semantic-expansion-plan.md`](core-derived-graph-semantic-expansion-plan.md)
- [`core-first-product-surface-cutover-plan.md`](../backend-wide/core-first-product-surface-cutover-plan.md)

## Target Semantic Model

The target graph semantics should be Core-owned and traceable:

- node kinds should be explicit (for example `claim`, `evidence`, `condition`,
  `comparison_row`, `document`)
- edge kinds should express research meaning (for example
  `supported_by`, `conditioned_by`, `compares_with`, `conflicts_with`,
  `derived_from`)
- node/edge fields should preserve source traceback and comparability signals

The projection should treat `document_profiles`, `evidence_cards`, and
`comparison_rows` as semantic inputs; GraphRAG entity edges should no longer be
the primary product-facing graph meaning.

## Execution Waves

### Wave A: Core Seam Prerequisites

Goal:

- finish Source/Core seam extraction so graph projection does not depend on
  protocol-owned parsing helpers.

Exit criteria:

- shared parsing helpers are Core-owned
- documents/evidence/comparisons do not depend on protocol-owned parsing seams

### Wave B: Core Projection Assembly

Goal:

- add backend graph projection assembly from Core artifacts.

Primary changes:

- add a Core graph assembly service under `application/graph/`
- derive graph nodes/edges from:
  - `document_profiles.parquet`
  - `evidence_cards.parquet`
  - `comparison_rows.parquet`
- preserve traceback pointers needed by frontend detail panels

Exit criteria:

- a collection can produce a Core-derived graph payload without reading
  GraphRAG `entities/relationships` as semantic source

### Wave C: Dual Path And Compatibility

Goal:

- run Core-derived and retained GraphRAG graph paths in parallel during
  migration.

Primary changes:

- keep current `/graph` contract stable while introducing an internal mode
  switch
- support side-by-side verification on node/edge counts, traceback coverage,
  and error behavior
- keep GraphML export available during dual-path period

Exit criteria:

- Core-derived graph path is stable on real collections
- no frontend-breaking payload regressions in normal graph usage

### Wave D: Semantic Cutover

Goal:

- make Core-derived graph the default product-facing graph semantics.

Primary changes:

- switch `/graph` default payload assembly to Core-derived projection
- update readiness semantics to align with Core artifact readiness
- keep GraphRAG graph generation as non-primary internal capability

Exit criteria:

- graph semantics are Core-first by default
- graph readiness aligns with Core backbone availability

### Wave E: GraphRAG Semantic Downgrade

Goal:

- retain GraphRAG logic only for pipeline/system needs, not product graph
  semantics.

Primary changes:

- remove GraphRAG entities/relationships as product-facing semantic dependency
  for graph route behavior
- keep GraphRAG internals only where pipeline and retrieval infrastructure
  still need them
- document final ownership boundary clearly

Exit criteria:

- product graph no longer depends on GraphRAG entity graph semantics
- GraphRAG graph extraction remains optional/internal pipeline capability

## API And Contract Guardrails

- preserve route stability during migration (`/graph`, `/graphml`)
- preserve stable structured errors during migration
- do not force frontend to migrate via breaking schema jumps in one release
- use additive compatibility fields where transition is needed

## Risks

- if cutover happens before Core artifact quality stabilizes, graph quality
  will not improve in practice
- if GraphRAG semantics are removed too early, operational troubleshooting
  surfaces may regress
- if compatibility period is too long, dual semantics can create confusion

## Recommended Reading Order

1. [`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
2. [`core-stabilization-and-seam-extraction-plan.md`](../core/core-stabilization-and-seam-extraction-plan.md)
3. [`graph-surface-plan.md`](graph-surface-plan.md)
4. this follow-up plan

## Related Docs

- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
- [`core-stabilization-and-seam-extraction-plan.md`](../core/core-stabilization-and-seam-extraction-plan.md)
- [`graph-surface-plan.md`](graph-surface-plan.md)
- [`core-derived-graph-structure-and-drilldown-plan.md`](core-derived-graph-structure-and-drilldown-plan.md)
- [`core-derived-graph-semantic-expansion-plan.md`](core-derived-graph-semantic-expansion-plan.md)
- [`../../../docs/architecture/graph-surface-current-state.md`](../../../../docs/architecture/graph-surface-current-state.md)
- [`../../../docs/architecture/lens-v1-architecture-boundary.md`](../../../../docs/architecture/lens-v1-architecture-boundary.md)
