# Backend Module Overview

## Purpose

The backend turns uploaded collection files into document profile, evidence,
comparison, retained graph/report, and conditional protocol artifacts and
exposes those results through the public HTTP contract.

The backend implements the shared Lens v1 evidence-first architecture defined
in root docs. This document describes backend ownership seams and local
navigation rather than redefining shared product or architecture decisions.

## Current Ownership Seams

- `controllers/`
  Current HTTP route surface for collections, tasks, workspace, graph,
  protocol, query, and reports.
- `application/`
  Use-case orchestration layer with active domain packages plus some remaining
  legacy flat services.
- `domain/`
  Domain models and port definitions.
- `infra/persistence/`
  Repository and persistence backends.
- `retrieval/`
  Index and query engine package.

## Current Architectural Shape

The backend is in a transition state:

- all public HTTP flows currently enter through `controllers/`
- `application/` already contains domain packages for collections, indexing,
  workspace, documents, evidence, comparisons, and protocol
- some legacy flat orchestration seams still remain and should not be deepened
- the Lens v1 collection backbone is now
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`
- `retrieval/` remains the largest engine surface and should be reached
  through clearer application or infrastructure boundaries over time

The target direction is a business-domain-oriented backend shape rather than a
larger flat service bag.

## Key Runtime Flows

- collection creation and file upload
- indexing task orchestration
- artifact readiness tracking
- document profile, evidence, and comparison artifact generation
- graph export and report browsing
- protocol step listing, search, and SOP draft generation for suitable corpora

## Local Navigation

Start with:

- [`../specs/api.md`](../specs/api.md)
  Authoritative frontend/backend API contract
- [`../plans/current-api-surface-migration-checklist.md`](../plans/current-api-surface-migration-checklist.md)
  Canonical current-state page for the active backend migration

Active execution plans:

- [`../plans/core-stabilization-and-seam-extraction-plan.md`](../plans/core-stabilization-and-seam-extraction-plan.md)
  Active near-term child plan for Core stabilization and parsing seam
  extraction
- [`../plans/goal-core-source-implementation-plan.md`](../plans/goal-core-source-implementation-plan.md)
  Broader parent roadmap for later Core, Goal, and Source waves
- [`../plans/goal-core-source-contract-follow-up-plan.md`](../plans/goal-core-source-contract-follow-up-plan.md)
  Active child plan for freezing Goal/Core/Source contracts before layer growth
- [`../plans/graph-surface-plan.md`](../plans/graph-surface-plan.md)
  Active retained-secondary-surface plan for graph hardening

Architecture background:

- [`domain-architecture.md`](domain-architecture.md)
  Target backend-local domain seams and packaging direction
- [`goal-core-source-layering.md`](goal-core-source-layering.md)
  Backend-local proposal for goal-driven entry, collection intelligence core,
  and source acquisition seams
- [`application-layer-boundary.md`](application-layer-boundary.md)
  Boundary ADR

Historical background:

- [`../plans/evidence-first-parsing-plan.md`](../plans/evidence-first-parsing-plan.md)
  Origin plan for the evidence-first parsing transition
- [`../plans/v1-api-migration-notes.md`](../plans/v1-api-migration-notes.md)
  Historical bridge note behind the current API migration checklist

Code-owned neighbors:

- [`../runbooks/backend-ops.md`](../runbooks/backend-ops.md)
  Local development and operations runbook
- [`../../application/README.md`](../../application/README.md)
  Use-case orchestration boundary
- [`../../retrieval/README.md`](../../retrieval/README.md)
  Retrieval engine boundary
- [`../../infra/persistence/README.md`](../../infra/persistence/README.md)
  Persistence adapter boundary
