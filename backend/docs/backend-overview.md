# Backend Module Overview

## Purpose

The backend turns uploaded collection files into queryable graph, report, and
protocol artifacts and exposes those results through the public HTTP contract.

The backend implements the shared Lens v1 evidence-first architecture defined
in root docs. This document describes backend ownership seams and local
navigation rather than redefining shared product or architecture decisions.

## Current Ownership Seams

- `api/`
  Public HTTP route boundary for query and reports.
- `controllers/`
  App-layer HTTP routes for collections, tasks, graph, protocol, and workspace.
- `application/`
  Query and report orchestration layer.
- `services/`
  Collection, task, protocol, and workspace services used by the app layer.
- `domain/`
  Domain models and port definitions.
- `infra/persistence/`
  Repository and persistence backends.
- `retrieval/`
  Index and query engine package.

## Current Architectural Shape

The backend is in a transition state:

- public query and report flows already have an `api -> application` shape
- collection, task, workspace, graph, and protocol flows still route through
  `controllers/` and `services/`
- `retrieval/` remains the largest engine surface and should be reached
  through clearer application or infrastructure boundaries over time

## Key Runtime Flows

- collection creation and file upload
- indexing task orchestration
- artifact readiness tracking
- graph export and report browsing
- evidence and comparison artifact generation
- protocol step listing, search, and SOP draft generation for suitable corpora

## Local Navigation

- [`api.md`](api.md)
  Public route boundary and HTTP contract
- [`backend-application-layer-boundary.md`](backend-application-layer-boundary.md)
  Boundary ADR
- [`backend-evidence-first-parsing-plan.md`](backend-evidence-first-parsing-plan.md)
  Draft backend-local implementation plan for Lens v1 evidence-first parsing
- [`backend-ops.md`](backend-ops.md)
  Local development and operations runbook
- [`../application/README.md`](../application/README.md)
  Use-case orchestration boundary
- [`../retrieval/README.md`](../retrieval/README.md)
  Retrieval engine boundary
- [`../infra/persistence/README.md`](../infra/persistence/README.md)
  Persistence adapter boundary
