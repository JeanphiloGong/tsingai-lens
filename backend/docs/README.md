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

Start here:

- [`specs/api.md`](specs/api.md)
  Authoritative frontend/backend public API contract
- [`architecture/overview.md`](architecture/overview.md)
  Backend ownership seams and local navigation

Current state and active plans:

- [`plans/current-api-surface-migration-checklist.md`](plans/current-api-surface-migration-checklist.md)
  Canonical current-state page for backend API migration and reading order
- [`plans/core-parsing-quality-hardening-plan.md`](plans/core-parsing-quality-hardening-plan.md)
  Current near-term child plan for improving Core parsing, evidence, and
  comparison quality before new adapters or Goal Consumer work
- [`plans/core-stabilization-and-seam-extraction-plan.md`](plans/core-stabilization-and-seam-extraction-plan.md)
  Earlier child plan for Core stabilization and parsing seam extraction
- [`plans/goal-core-source-implementation-plan.md`](plans/goal-core-source-implementation-plan.md)
  Broader parent roadmap for the five-layer backend rollout
- [`plans/goal-core-source-contract-follow-up-plan.md`](plans/goal-core-source-contract-follow-up-plan.md)
  Active contract-freeze child plan for Goal Brief, Source Builder, Core,
  Goal Consumer, and downstream boundary guardrails
- [`plans/source-collection-builder-normalization-plan.md`](plans/source-collection-builder-normalization-plan.md)
  Active child plan for standardizing Source & Collection Builder handoff
  before Core execution
- [`plans/core-derived-graph-follow-up-plan.md`](plans/core-derived-graph-follow-up-plan.md)
  Follow-up migration plan for moving graph semantics to Core-derived
  claim/evidence/condition/comparability projections
- [`plans/graph-surface-plan.md`](plans/graph-surface-plan.md)
  Active retained-secondary-surface plan for graph hardening

Architecture background:

- [`architecture/domain-architecture.md`](architecture/domain-architecture.md)
  Target backend business-domain packaging and controller boundaries
- [`architecture/goal-core-source-layering.md`](architecture/goal-core-source-layering.md)
  Backend-local five-layer research architecture centered on the Core backbone
- [`architecture/application-layer-boundary.md`](architecture/application-layer-boundary.md)
  Backend ADR for HTTP/application ownership separation

Historical background:

- [`plans/evidence-first-parsing-plan.md`](plans/evidence-first-parsing-plan.md)
  Origin plan for the evidence-first parsing transition, kept for lineage
- [`plans/v1-api-migration-notes.md`](plans/v1-api-migration-notes.md)
  Historical bridge note behind the current API migration checklist

Operations:

- [`runbooks/backend-ops.md`](runbooks/backend-ops.md)
  Local development and operations runbook

## Placement Rule

- keep backend-wide formal docs in this subtree
- keep route- or package-local docs near the owning code node when the
  knowledge is narrower than the backend module
- keep shared product, system, and cross-module docs in the root `docs/`
  tree
