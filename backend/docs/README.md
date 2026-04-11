# Backend Docs Index

This directory is the secondary index for backend-owned formal docs.

Use [../README.md](../README.md) for the backend module entry page. Use this
directory when you already know the question is backend-local and need the
right architecture, spec, plan, or runbook document.

## Layout

- `architecture/`
  Backend-local architecture and ownership-boundary docs
- `specs/`
  Backend-local formal contracts, including the authoritative public API spec
- `plans/`
  Backend-local migration and implementation plans
- `runbooks/`
  Backend-local operational guidance

## Key Docs

- [`specs/api.md`](specs/api.md)
  Authoritative frontend/backend public API contract
- [`architecture/overview.md`](architecture/overview.md)
  Backend ownership seams and local navigation
- [`architecture/domain-architecture.md`](architecture/domain-architecture.md)
  Target backend business-domain packaging and controller boundaries
- [`architecture/application-layer-boundary.md`](architecture/application-layer-boundary.md)
  Backend ADR for HTTP/application ownership separation
- [`plans/evidence-first-parsing-plan.md`](plans/evidence-first-parsing-plan.md)
  Execution plan for the evidence-first parsing backbone
- [`plans/goal-core-source-implementation-plan.md`](plans/goal-core-source-implementation-plan.md)
  Execution plan for the Goal/Core/Source layering direction
- [`plans/v1-api-migration-notes.md`](plans/v1-api-migration-notes.md)
  Backend-local migration notes behind the agreed public API contract
- [`plans/current-api-surface-migration-checklist.md`](plans/current-api-surface-migration-checklist.md)
  Current backend migration state and next execution order for API surfaces
- [`runbooks/backend-ops.md`](runbooks/backend-ops.md)
  Local development and operations runbook

## Placement Rule

- keep backend-wide formal docs in this subtree
- keep route- or package-local docs near the owning code node when the
  knowledge is narrower than the backend module
- keep shared product, system, and cross-module docs in the root `docs/`
  tree
