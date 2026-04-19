# Backend Docs

This directory is the documentation landing page for backend-wide formal docs.

Use [../README.md](../README.md) for the backend module entry page. Use this
directory when the question is already backend-local and you need the right
authority page, current-state page, or implementation lineage.

## Docs Layout

- `architecture/`
  Backend-wide architecture, ownership-boundary docs, and local ADRs
- `specs/`
  Backend-wide contracts, including the public API contract
- `runbooks/`
  Backend-local operational guidance
- `plans/`
  Backend implementation current-state and plan families organized as
  `backend-wide/`, `source/`, `core/`, `derived/`, and `historical/`; this is
  not the default start surface unless you are already inside backend change
  work

## Start Paths

- Public API contract:
  [`specs/api.md`](specs/api.md)
- Backend architecture and ownership seams:
  [`architecture/overview.md`](architecture/overview.md)
- Local development and operations:
  [`runbooks/backend-ops.md`](runbooks/backend-ops.md)
- Backend plan-family landing page:
  [`plans/README.md`](plans/README.md)
- Current backend migration and execution state:
  [`plans/backend-wide/current-api-surface-migration-checklist.md`](plans/backend-wide/current-api-surface-migration-checklist.md)

## Backend-Wide Authority

- [`specs/api.md`](specs/api.md)
  Authoritative frontend/backend public API contract
- [`architecture/overview.md`](architecture/overview.md)
  Backend module overview, ownership seams, and local navigation
- [`architecture/domain-architecture.md`](architecture/domain-architecture.md)
  Target backend business-domain packaging and controller boundaries
- [`architecture/goal-core-source-layering.md`](architecture/goal-core-source-layering.md)
  Backend-local five-layer research architecture centered on the Core backbone
- [`architecture/application-layer-boundary.md`](architecture/application-layer-boundary.md)
  Backend ADR for HTTP and application ownership separation
- [`runbooks/backend-ops.md`](runbooks/backend-ops.md)
  Local development and operations runbook

## Current State And Plan Families

Start with:

- [`plans/README.md`](plans/README.md)
  Backend-local plans landing page, reading paths, and placement rules
- [`plans/backend-wide/current-api-surface-migration-checklist.md`](plans/backend-wide/current-api-surface-migration-checklist.md)
  Canonical current-state page for backend API migration and local reading
  order

Then move to the owning plan family only when you are already inside that wave:

- [`plans/backend-wide/README.md`](plans/backend-wide/README.md)
  Cross-layer and backend-wide plan family
- [`plans/source/README.md`](plans/source/README.md)
  Source runtime, parser, and retirement plan family
- [`plans/core/README.md`](plans/core/README.md)
  Core backbone, quality, traceback, and domain-semantic plan family
- [`plans/derived/README.md`](plans/derived/README.md)
  Derived-surface and retirement-lineage plan family
- [`plans/historical/README.md`](plans/historical/README.md)
  Historical lineage family for retained non-current pages

## What Does Not Belong Here

- package-local purpose and boundary docs for `application/*`, `infra/*`, and
  `tests/*`
- route-family or package-family docs that belong at a narrower code-owned node
- shared product, system, or cross-module docs that belong in root `docs/`

## Placement Rules

- Keep backend-wide formal docs in this subtree.
- Keep narrower route- or package-local docs near the owning code node.
- Use `plans/` for backend implementation current-state and retained lineage.
- Put multi-family waves under `plans/backend-wide/`.
- Put business-layer-local waves under `plans/source/`, `plans/core/`, or
  `plans/derived/`.
- Move superseded or origin-only lineage pages under `plans/historical/`.
- Keep shared product, system, and cross-module docs in root `docs/`.
