# Backend Goal/Core/Source Implementation Plan

## Summary

This document records the backend-local parent implementation plan for turning
the Goal/Core/Source layering proposal into executable backend waves.

The plan keeps one requirement fixed:

all research-facing outputs must continue to converge on one collection-backed
evidence/comparison backbone.

This is the broader multi-wave roadmap above the current Core stabilization
work. It is not the near-term execution entry point for the current backend
slice.

## Context

The layering proposal in
[`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
defines three layers:

- Goal Layer
- Research Intelligence Core
- Source / Acquisition Layer

Current backend-local work has already moved part of the Core forward:

- `document_profiles` is a real artifact
- `application/evidence/` and `application/comparisons/` now exist as real
  backend packages in the local codebase
- indexing orchestration already runs Core stages before the protocol branch
- workspace and artifact registry are already growing Core-specific readiness
  states

The near-term execution reference for this in-flight Core work is
[`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md).
This parent plan should be used when deciding what follows after that child
plan is complete.

The main implementation gaps are now narrower:

- Core parsing helpers still live under `application/protocol/`
- protocol remains too close to the shared parsing seam
- Goal Layer does not exist yet as a first-class backend surface
- Source / Acquisition is still mostly upload plus PDF extraction
- route and artifact contracts need to be stabilized around the new Core

This plan therefore does not restart the evidence-first work. It takes the
current Core rollout as the baseline and defines how to harden it, decouple it,
and then add Goal and Source layers on top.

## Scope

This plan covers backend-owned implementation waves for:

- Core artifact completion
- Core versus Protocol boundary repair
- indexing and readiness orchestration
- minimal Goal Layer contracts
- Source / Acquisition expansion seams

This plan does not cover:

- frontend IA or page design
- provider or vendor selection for external search
- crawler-specific infrastructure decisions
- root product positioning changes

## Proposed Change

### Execution Rules

- keep one collection-backed artifact model for paper-first and goal-first
  entry
- do not allow Goal Layer logic to generate research judgments without Core
  artifacts
- do not allow Source adapters to bypass collection creation or Core pipelines
- keep protocol behind Core suitability and Core readiness
- prefer boundary refactors that preserve current behavior before adding new
  product entrypoints

### Wave 1: Complete And Stabilize The Current Core Rollout

Goal:

- finish the current in-flight rollout of `document_profiles`,
  `evidence_cards`, and `comparison_rows` for real collections

Primary changes:

- finish real collection support for `/documents/profiles`,
  `/evidence/cards`, and `/comparisons`
- stabilize collection-scoped artifact persistence for
  `document_profiles.parquet`, `evidence_cards.parquet`, and
  `comparison_rows.parquet`
- make workspace readiness and warnings depend on Core artifact flags rather
  than on protocol by default
- ensure artifact registry tracks `document_profiles_ready`,
  `evidence_cards_ready`, and `comparison_rows_ready`

Exit criteria:

- non-mock collections can serve all three Core resources
- workspace treats comparison readiness as the primary ready state
- protocol can be absent without making the collection look broken

### Wave 2: Extract A Core-Owned Parsing Seam

Goal:

- remove the current reverse dependency where Core services import protocol-
  owned parsing helpers

Primary changes:

- move shared helpers such as document-record assembly, text-unit joining, and
  section derivation out of `application/protocol/`
- place those helpers under a Core-owned seam, preferably under
  `application/documents/` or a narrowly scoped Core parsing package owned by
  the same collection-analysis path
- make `documents`, `evidence`, `comparisons`, and `protocol` all depend on
  that shared seam rather than on protocol packages

Boundary result:

- document parsing becomes upstream Core infrastructure
- protocol becomes a downstream consumer rather than the owner of shared corpus
  parsing

Exit criteria:

- `application/documents/` and `application/evidence/` no longer import shared
  parsing helpers from `application/protocol/`
- protocol helpers can be changed without changing Core dependency direction

### Wave 3: Harden The Core Pipeline And Protocol Branch

Goal:

- make the index-time sequence and readiness semantics explicit and stable

Primary changes:

- keep the post-index sequence as
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`
- ensure task stages and readiness fields mirror that order
- make protocol execution depend on Core suitability and Core completion rather
  than on raw document presence alone
- introduce `protocol_candidates` when protocol filtering needs a separate
  intermediate artifact
- make SOP generation depend on filtered protocol outputs, not on raw protocol-
  like text hits

Exit criteria:

- task history clearly shows Core stages before protocol stages
- protocol-limited collections still complete indexing successfully
- protocol branch failures do not redefine the Core contract

### Wave 4: Add The Minimal Goal Layer Contract

Goal:

- add a first-class goal-driven entry surface without creating a second fact
  model

Current child execution entrypoint:

- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)

Primary changes:

- add `application/goals/` for backend-local goal orchestration
- define the smallest durable objects:
  `research_brief`, `coverage_assessment`, `seed_collection`, and
  `entry_recommendation`
- add a goal-facing controller surface only after the contract is clear
- make the Goal Layer call collection and acquisition services to produce or
  enrich a collection, then hand off to the Core

Non-goals:

- no direct comparison generation inside the Goal Layer
- no direct SOP generation from the Goal Layer
- no monolithic goal agent that bypasses traceability

Exit criteria:

- a goal-first path results in a collection that lands in the same workspace
  and Core artifact endpoints as a paper-first path
- Goal responses can recommend next steps without claiming final research
  judgments

### Wave 5: Expand The Source / Acquisition Layer

Goal:

- support more ways to form or enrich collections without leaking acquisition
  logic into research semantics

Primary changes:

- expand `infra/ingestion/` with search adapters, connectors, and crawler-style
  acquisition seams
- keep source normalization, metadata capture, and import mechanics in
  infrastructure-owned packages
- let acquisition flows populate collections or collection drafts, but not Core
  artifacts directly

Exit criteria:

- upload, external search, and connector-driven inputs all end at collection
  boundaries
- acquisition adapters remain replaceable without changing Core contracts

## File Change Plan

### Core Rollout And Stabilization

- `application/documents/service.py`
- `application/evidence/service.py`
- `application/comparisons/service.py`
- `controllers/documents.py`
- `controllers/evidence.py`
- `controllers/comparisons.py`
- `application/workspace/service.py`
- `application/workspace/artifact_registry_service.py`
- `controllers/schemas/workspace.py`
- `controllers/schemas/task.py`

### Core Parsing Seam Extraction

- shared helpers currently under `application/protocol/source_service.py`
- shared helpers currently under `application/protocol/section_service.py`
- new Core-owned parsing location under `application/documents/` or a nearby
  Core package
- import sites in `application/documents/service.py`
- import sites in `application/evidence/service.py`
- import sites in `application/comparisons/service.py`
- import sites in `application/protocol/*`

### Pipeline And Protocol Branch Hardening

- `application/indexing/index_task_runner.py`
- `application/protocol/pipeline_service.py`
- `application/protocol/extract_service.py`
- `application/protocol/search_service.py`
- `application/protocol/sop_service.py`

### Goal Layer Introduction

- new `application/goals/`
- future `controllers/goals.py` or equivalent goal-facing route package
- collection handoff integration in `application/collections/`

### Source / Acquisition Expansion

- `infra/ingestion/`
- future adapter-specific subpackages under `infra/ingestion/`
- collection seeding handoff into `application/collections/`

## Verification

### Regression Verification

- collection upload, indexing kickoff, graph, reports, and query flows remain
  available while Core refactors land
- protocol-capable fixtures still produce usable protocol outputs after Core
  seam extraction
- current workspace consumers continue to receive stable readiness payloads

### New Behavior Verification

- real collections can serve `document_profiles`, `evidence_cards`, and
  `comparison_rows`
- document, evidence, and comparison services no longer import shared parsing
  helpers from protocol-owned modules
- task stages reflect the Core-first sequence before protocol
- goal-first collection seeding lands in the same workspace and URLs as
  paper-first entry
- source adapters can seed collections but cannot write Core artifacts directly

### Test Slices

- unit tests for shared Core parsing helpers after extraction
- unit tests for evidence extraction and comparison normalization
- integration tests for real collection document, evidence, and comparison
  endpoints
- integration tests for task-stage progression across Core and protocol phases
- app-layer tests for Goal Layer contract objects once introduced

## Risks

- in-flight Core rollout work may still be changing locally, so this plan must
  absorb current implementation rather than fight it
- extracting shared parsing helpers can temporarily duplicate logic across Core
  and protocol modules
- readiness fields can churn unless task, workspace, and controller schemas
  move together
- Goal Layer scope can sprawl into agent behavior if its contract is not kept
  intentionally small
- Source expansion can become a crawler project unless collection handoff stays
  the explicit boundary

## Related Docs

- [`current-api-surface-migration-checklist.md`](current-api-surface-migration-checklist.md)
- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)
- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
- [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`evidence-first-parsing-plan.md`](evidence-first-parsing-plan.md)
- [`v1-api-migration-notes.md`](v1-api-migration-notes.md)
