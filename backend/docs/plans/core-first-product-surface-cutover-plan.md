# Core-First Product Surface Cutover Plan

## Summary

This document records the backend-local closure plan for the current
Core-first cutover wave.

The main implementation shift is already underway in code:

- product graph semantics now consume Core artifacts
- report semantics now consume Core artifacts
- workspace graph readiness now tracks Core graph inputs
- public task-stage vocabulary no longer exposes `graphrag_*`
- application query calls now cross a Source-owned runtime facade

The remaining job is not another semantic redesign.
It is to freeze the contract, align the docs, and prevent legacy GraphRAG
product semantics from leaking back out of Source.

## Purpose

This plan exists to answer one narrow backend question:

after the hard Core-first cutover, what is now frozen, what still needs
cleanup, and what must remain internal to Source only.

It should be read as the current closure plan for:

- graph
- reports
- workspace readiness
- task-stage vocabulary
- query/runtime boundary wording

## Context

The five-layer backend architecture already states that:

- Core is the only producer of stable research facts
- graph, reports, and protocol are downstream or derived surfaces
- Source may gather or index material, but it must not define product-facing
  research facts

That architecture now has concrete code movement behind it:

- [`application/graph/service.py`](../../application/graph/service.py) reads
  only `document_profiles.parquet`, `evidence_cards.parquet`, and
  `comparison_rows.parquet`
- [`application/reports/service.py`](../../application/reports/service.py)
  derives pattern-group style report payloads from Core artifacts
- [`application/workspace/artifact_registry_service.py`](../../application/workspace/artifact_registry_service.py)
  computes `graph_generated` and `graph_ready` from Core graph inputs rather
  than GraphRAG entity artifacts
- [`application/indexing/task_service.py`](../../application/indexing/task_service.py)
  and [`controllers/schemas/task.py`](../../controllers/schemas/task.py)
  expose `source_index_*` stage names
- [`application/query/service.py`](../../application/query/service.py) no
  longer imports `infra.graphrag` directly, and now crosses
  [`application/source/query_runtime_service.py`](../../application/source/query_runtime_service.py)
- GraphML rendering for the product graph surface now lives under
  [`infra/graph/graphml.py`](../../infra/graph/graphml.py)

The architecture risk has therefore changed.

The main risk is no longer "can we build a Core-derived graph path".
The main risk is "can we keep product semantics Core-first while GraphRAG
runtime logic retreats behind Source-only ownership".

## Scope

This closure plan covers:

- Core-first contract freeze for graph and reports
- Core-based readiness semantics for workspace and task payloads
- Source-only boundary rules for GraphRAG and retrieval runtime usage
- public vocabulary cleanup for task stages and graph/report semantics
- documentation and regression-guard work needed after the code cutover

This closure plan does not cover:

- Goal Consumer / Decision-layer implementation
- new Core artifact types
- query algorithm redesign
- frontend IA redesign
- immediate retirement of all Source-internal GraphRAG artifacts

## Current Implemented State

The current backend state should be read as follows.

### Graph

- `GET /api/v1/collections/{collection_id}/graph` is now a Core-derived graph
  route
- `GET /api/v1/collections/{collection_id}/graphml` exports the same Core
  projection
- legacy `community_id` filtering is no longer supported on the product graph
  route and should return a stable application error

### Reports

- report routes remain available, but their semantic source is now Core
- the report service should be interpreted as Core-derived pattern grouping,
  not as GraphRAG community summarization
- route-path compatibility may remain temporarily even if the underlying
  semantics have changed

### Workspace And Tasks

- `graph_generated` and `graph_ready` now mean "Core graph inputs exist and are
  consumable", not "GraphRAG entities/relationships exist"
- public task-stage language now uses `source_index_started` and
  `source_index_completed`
- older persisted `graphrag_*` task stages may still be normalized at the
  service edge for compatibility, but they are no longer part of the public
  contract

### Query Runtime Boundary

- the application query service now depends on a Source-owned runtime facade
- Source runtime may still use GraphRAG/retrieval tables internally
- product-facing application code should not directly import
  `infra.graphrag` anymore outside Source-owned seams

## Frozen Contract Checklist

### 1. Core Fact Ownership

Only the Research Intelligence Core may produce stable research fact objects:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`

No Goal, Source, graph, report, or query surface may create a parallel fact
model that competes with these artifacts.

### 2. Graph Contract

The product graph surface is now Core-first.

Frozen rules:

- `/graph` and `/graphml` consume only:
  - `document_profiles.parquet`
  - `evidence_cards.parquet`
  - `comparison_rows.parquet`
- `community_id` is no longer a supported product-graph semantic filter
- if `community_id` is provided, the route should fail with a stable
  application-level `400`
- missing Core graph inputs should fail with a stable `409`

Explicit non-contract:

- `entities.parquet`
- `relationships.parquet`
- `communities.parquet`

These files are no longer product-facing graph prerequisites.

### 3. Report Contract

The report surface must be interpreted as a Core-derived secondary view.

Frozen rules:

- report payloads must be assembled from Core artifacts
- report detail and summary objects must remain traceable to Core document,
  evidence, and comparison ids
- report semantics must not depend on GraphRAG communities, community reports,
  entities, or relationships

Compatibility note:

- route paths such as `/reports/communities` may remain temporarily for
  compatibility
- route names do not override the semantic rule that the backing model is now
  Core-derived pattern grouping

### 4. Workspace Readiness Contract

Workspace artifact flags must remain Core-first.

Frozen rules:

- `graph_generated` means the three Core graph input files exist
- `graph_ready` means those Core graph inputs are present and at least one of
  them is non-empty enough for graph projection use
- `graphml_generated` and `graphml_ready` continue to describe the GraphML
  export file only

Workspace readiness must not regress to entity-graph file presence.

### 5. Task Vocabulary Contract

Public task payloads must use Source/Core language rather than engine names.

Frozen rules:

- public stages use `source_index_started`
- public stages use `source_index_completed`
- public contracts must not expose `graphrag_index_started`
- public contracts must not expose `graphrag_index_completed`

Compatibility aliasing may exist inside service logic for old records, but it
must not redefine the public API vocabulary.

### 6. Query Boundary Contract

Query remains a retained secondary surface, but its dependency direction is
now explicit.

Frozen rules:

- `application/query/` must cross a Source-owned facade
- GraphRAG and retrieval runtime details belong under Source-owned seams only
- controller- or application-level product semantics must not depend directly
  on `infra.graphrag`

Deferred question:

- query request vocabulary still carries community-oriented knobs today; that
  vocabulary should be treated as Source-runtime-facing, not as a Core fact
  contract

### 7. Source Privacy Contract

GraphRAG is now a Source-internal implementation concern.

Frozen rules:

- GraphRAG may remain inside Source/runtime/infrastructure code when needed
- GraphRAG must not define product graph semantics
- GraphRAG must not define product report semantics
- GraphRAG must not define workspace graph readiness
- GraphRAG engine names must not leak into public task-stage vocabulary

### 8. Legacy Artifact Retirement Contract

Legacy GraphRAG artifacts may still exist for Source-internal runtime reasons,
but they no longer carry product authority.

Examples:

- `entities.parquet`
- `relationships.parquet`
- `communities.parquet`
- `community_reports.parquet`

Frozen rule:

these artifacts are optional internal byproducts only.
They are not product-facing readiness prerequisites and not product-facing
semantic sources.

### 9. Documentation Authority Contract

Backend docs must match the Core-first code path.

At minimum, backend docs must no longer describe:

- graph as a community/entity graph surface
- reports as GraphRAG community reports
- graph readiness as entity/relationship readiness
- public task stages as `graphrag_*`

## Remaining Closure Waves

### Wave A: Freeze The Current Core-First Language

Goal:

- align architecture, plan, and API wording with the new implemented boundary

Primary changes:

- update graph/report/task wording in
  [`../specs/api.md`](../specs/api.md)
- update retained plan docs whose old text still assumes dual-path or
  GraphRAG-first product semantics
- keep five-layer wording consistent with current code

Exit criteria:

- no backend authority page describes GraphRAG as the product semantic source
  for graph or reports

### Wave B: Add Contract Guard Tests

Goal:

- keep the cutover from silently regressing

Primary changes:

- assert `/graph` no longer accepts legacy community semantics
- assert report service works without GraphRAG community artifacts
- assert workspace graph readiness depends on Core inputs
- assert public task-stage payloads expose `source_index_*`
- assert product-facing application code does not reintroduce direct
  `infra.graphrag` imports outside Source-owned seams

Exit criteria:

- test failures catch boundary drift before it reaches product behavior

### Wave C: Decide Source Pipeline Cleanup

Goal:

- decide how much GraphRAG output generation remains necessary inside Source

Primary changes:

- identify which Source runtime paths still require legacy GraphRAG artifacts
- decide whether those artifacts remain generated, become lazy, or are retired
- keep this decision explicitly internal to Source rather than product-facing

Exit criteria:

- legacy artifact generation has an explicit owner and justification
- product contracts remain unaffected regardless of the Source-internal choice

## Verification Matrix

- graph success path works from Core artifacts only
- graph route returns `400` for unsupported `community_id`
- graph route returns `409` when Core graph inputs are missing
- report routes succeed when legacy GraphRAG report files are absent
- workspace `graph_generated` and `graph_ready` track Core graph inputs
- public task payloads show `source_index_*`
- product-facing docs no longer instruct readers to depend on entity/community
  graph artifacts
- GraphRAG runtime details remain reachable only through Source-owned seams

## Risks

- route-path compatibility can hide semantic changes if docs are not updated at
  the same time
- report schema names such as `community_*` can preserve legacy vocabulary even
  after the data model has changed
- query parameters still expose some community-oriented runtime language, which
  can confuse readers if Source/runtime ownership is not stated clearly
- Source-internal legacy artifact generation can drift back into product
  dependency if readiness and docs are not guarded

## Recommended Reading Order

1. [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
2. [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)
3. [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
4. [`core-derived-graph-cutover-implementation-plan.md`](core-derived-graph-cutover-implementation-plan.md)
5. this cutover-closure plan

## Related Docs

- [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)
- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
- [`core-derived-graph-cutover-implementation-plan.md`](core-derived-graph-cutover-implementation-plan.md)
- [`graph-surface-plan.md`](graph-surface-plan.md)
- [`../specs/api.md`](../specs/api.md)
