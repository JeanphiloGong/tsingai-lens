# Query Retirement And GraphRAG Query Decoupling Plan

## Summary

This document records the backend-local plan to retire the retained query
surface and remove the remaining GraphRAG query dependency chain from the
backend.

The target is narrower than "remove all GraphRAG from backend".

This plan only covers the query side:

- remove the public `POST /api/v1/query` surface
- remove the application-layer query package and Source query runtime bridge
- remove the retrieval query engine, query CLI, and query prompt family
- stop exposing query-specific GraphRAG vocabulary in backend contracts

It does not yet remove GraphRAG from indexing, collection config bootstrapping,
or other Source-internal generation paths.

Status as of 2026-04-19:

- the public query surface is already removed from runtime
- the historical `application/query/*` package and query-runtime bridge are
  already gone
- this page now remains as retained derived-surface retirement lineage

## Purpose

This plan exists to answer one backend question:

if query is no longer a wanted backend product surface, what exact code,
runtime, test, and documentation slices must be removed so GraphRAG stops
leaking through the query path entirely.

It should be read as the follow-up execution plan after the Core-first product
surface cutover.

## Context

The current backend state already treats query as a retained secondary surface
rather than part of the Core-backed product backbone.

Historically, query was the largest surviving GraphRAG-shaped hole in the
backend boundary:

- historical `application/query/service.py` owned a public app-layer query use
  case
- historical `application/source/query_runtime_service.py` translated app query
  calls into GraphRAG table reads such as `entities`, `communities`,
  `community_reports`, and `relationships`
- historical `backend/retrieval/api/query.py`, `backend/retrieval/query/`, and
  query-oriented CLI paths provided the actual query engine
- public docs previously described `/api/v1/query` as a retained secondary
  route

That shape conflicts with the desired backend layering:

- Goal defines and consumes
- Source gathers and normalizes
- Core produces stable research facts
- downstream product views consume Core

Query no longer fits as a stable product-facing surface under that model, and
its retained presence keeps GraphRAG-specific vocabulary alive in backend code
and docs.

## Scope

This plan covers:

- retirement of the public backend `/query` route
- removal of query request/response schemas
- removal of the application query package and compatibility shim
- removal of the Source query runtime adapter
- removal of retrieval query API, query engine package, query CLI, and query
  prompt family
- update of tests and docs that still assume query exists

This plan does not cover:

- GraphRAG indexing retirement
- removal of `infra/graphrag/collection_store.py`
- removal of entity/community artifact generation during indexing
- replacement of query with a new Core-backed search surface
- frontend redesign beyond removing references to the retired route

## Target End State

After this plan is completed:

- `POST /api/v1/query` no longer exists
- `backend/application/` no longer contains a query use-case package
- `backend/application/source/` no longer contains a query runtime bridge
- `backend/retrieval/` no longer contains query API, query engine, query CLI,
  or query prompt assets
- backend docs no longer present query as a retained product surface
- GraphRAG no longer leaks into the backend through the query path

The remaining GraphRAG footprint, if any, is then isolated to Source/indexing
generation paths and can be handled by a separate retirement wave.

## Removal Waves

### Wave A: Remove Public Query Surface

Goal:

- remove query from the backend HTTP contract

Primary changes:

- delete `controllers/query.py`
- delete `controllers/schemas/query.py`
- remove `QueryRequest` and `QueryResponse` exports from
  [`controllers/schemas/__init__.py`](../../../controllers/schemas/__init__.py)
- remove query router registration from [`main.py`](../../../main.py)

Exit criteria:

- OpenAPI no longer exposes `/api/v1/query`
- controller and schema imports compile without query references

### Wave B: Remove Application And Source Query Runtime

Goal:

- remove the retained app-layer query use case and the Source bridge that still
  knows GraphRAG table names

Primary changes:

- delete `application/query/service.py`
- delete `application/query/__init__.py`
- delete `application/query_service.py`
- delete `application/source/query_runtime_service.py`

Exit criteria:

- no application-layer runtime path still imports retrieval query runtime
- `application/source/` no longer exposes query-only logic

### Wave C: Remove Retrieval Query Engine

Goal:

- remove the internal query engine that anchors GraphRAG query semantics in the
  backend

Primary changes:

- delete `backend/retrieval/api/query.py`
- remove query exports from `backend/retrieval/api/__init__.py`
- delete `backend/retrieval/query/`
- delete `backend/retrieval/cli/query.py`
- remove the `query` command from `backend/retrieval/cli/main.py`
- remove `SearchMethod` from `backend/retrieval/config/enums.py`
- delete `backend/retrieval/prompts/query/`

Exit criteria:

- retrieval no longer offers query runtime entry points
- no runtime code depends on `SearchMethod`

### Wave D: Clean Tests And Docs

Goal:

- remove stale query expectations from verification and backend docs

Primary changes:

- remove `/query` assertions and stubs from
  [`tests/integration/test_app_layer_api.py`](../../../tests/integration/test_app_layer_api.py)
- remove `/query` OpenAPI expectations from
  [`tests/integration/routers/test_protocol_api.py`](../../../tests/integration/routers/test_protocol_api.py)
- update [`../specs/api.md`](../../specs/api.md)
- update [`current-api-surface-migration-checklist.md`](../backend-wide/api-surface-migration/current-state.md)
- update [`core-first-product-surface-cutover-plan.md`](../backend-wide/core-first-product-surface/implementation-plan.md)
- update [`../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
- update
  [`../../../docs/overview/system-overview.md`](../../../../docs/overview/system-overview.md)

Exit criteria:

- docs no longer describe query as a retained backend surface
- tests no longer require `/query` or query schemas

## Verification Matrix

- `rg "/query\\b|QueryRequest|QueryResponse" backend/controllers backend/application`
  returns no runtime references
- `rg "query_runtime_service|retrieval.api.query|SearchMethod" backend`
  returns no runtime references tied to the retired query path
- OpenAPI generation no longer includes `/api/v1/query`
- backend integration tests no longer stub or expect query
- graph, reports, workspace, tasks, protocol, and Core artifact routes still
  pass their current regression suite

## Risks

- deleting `SearchMethod` can produce a long tail of compile failures if query
  references are removed in the wrong order
- CLI users may still rely on `retrieval query`; this plan retires that path
  rather than preserving it as a hidden compatibility layer
- docs can drift if the route is removed in code before the retained-surface
  wording is cleaned up
- this plan can be mistaken for full GraphRAG retirement; it is only query-path
  retirement

## Recommended Execution Order

1. Remove the public query route and schemas.
2. Remove the application and Source query runtime bridge.
3. Remove retrieval query engine, query CLI, and query prompts.
4. Clean tests, docs, and remaining references.
5. Run regression focused on non-query product surfaces.

## Follow-Up After This Plan

If this plan succeeds, the next GraphRAG retirement question becomes narrower:

- keep or replace GraphRAG-based indexing generation inside Source
- decide whether entity/community artifacts remain temporary internal outputs
  or are retired entirely
- move collection config bootstrapping out of `infra/graphrag` if Source no
  longer wants GraphRAG-specific ownership there

That should be tracked as a separate Source/indexing retirement plan rather
than folded into this query retirement wave.

## Related Docs

- [`core-first-product-surface-cutover-plan.md`](../backend-wide/core-first-product-surface/implementation-plan.md)
- [`current-api-surface-migration-checklist.md`](../backend-wide/api-surface-migration/current-state.md)
- [`../specs/api.md`](../../specs/api.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
