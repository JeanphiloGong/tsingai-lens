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
  Backend implementation current-state, active delivery waves, and retained
  lineage; this is not the default start surface unless you are already inside
  backend change work

## Start Paths

- Public API contract:
  [`specs/api.md`](specs/api.md)
- Backend architecture and ownership seams:
  [`architecture/overview.md`](architecture/overview.md)
- Local development and operations:
  [`runbooks/backend-ops.md`](runbooks/backend-ops.md)
- Current backend migration and execution state:
  [`plans/current-api-surface-migration-checklist.md`](plans/current-api-surface-migration-checklist.md)

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

- [`plans/current-api-surface-migration-checklist.md`](plans/current-api-surface-migration-checklist.md)
  Canonical current-state page for backend API migration and local reading
  order

Then move to the owning plan family only when you are already inside that wave:

- Core quality:
  [`plans/core-parsing-quality-hardening-plan.md`](plans/core-parsing-quality-hardening-plan.md)
- Core stabilization and parsing seam extraction:
  [`plans/core-stabilization-and-seam-extraction-plan.md`](plans/core-stabilization-and-seam-extraction-plan.md)
- Five-layer rollout and contract freeze:
  [`plans/goal-core-source-implementation-plan.md`](plans/goal-core-source-implementation-plan.md),
  [`plans/goal-core-source-contract-follow-up-plan.md`](plans/goal-core-source-contract-follow-up-plan.md)
- Source and collection-builder normalization:
  [`plans/source-collection-builder-normalization-plan.md`](plans/source-collection-builder-normalization-plan.md)
- Graph retained surface and Core-derived cutover:
  [`plans/graph-surface-plan.md`](plans/graph-surface-plan.md),
  [`plans/core-derived-graph-follow-up-plan.md`](plans/core-derived-graph-follow-up-plan.md),
  [`plans/core-derived-graph-cutover-implementation-plan.md`](plans/core-derived-graph-cutover-implementation-plan.md)

Historical lineage:

- [`plans/evidence-first-parsing-plan.md`](plans/evidence-first-parsing-plan.md)
  Origin plan for the evidence-first parsing transition
- [`plans/v1-api-migration-notes.md`](plans/v1-api-migration-notes.md)
  Historical bridge note behind the current API migration checklist

## What Does Not Belong Here

- package-local purpose and boundary docs for `application/*`, `retrieval/*`,
  `infra/*`, and `tests/*`
- route-family or package-family docs that belong at a narrower code-owned node
- shared product, system, or cross-module docs that belong in root `docs/`

## Placement Rules

- Keep backend-wide formal docs in this subtree.
- Keep narrower route- or package-local docs near the owning code node.
- Use `plans/` for backend implementation current-state and retained lineage,
  not as the primary reader start page.
- Keep shared product, system, and cross-module docs in root `docs/`.
