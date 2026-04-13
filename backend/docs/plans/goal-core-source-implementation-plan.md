# Backend Five-Layer Research Flow Implementation Plan

This document keeps its historical path for continuity, but the plan now
tracks the five-layer architecture rather than the earlier three-layer
shorthand.

## Summary

This is the backend-local parent roadmap for executing the five-layer Lens
research flow:

- Goal Brief Layer
- Source & Collection Builder
- Research Intelligence Core
- Goal Consumer / Decision Layer
- Derived Views / Downstream

One requirement stays fixed across all waves:

all research-facing outputs must continue to converge on one collection-backed
Core backbone.

## Context

The architecture proposal in
[`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
now defines five layers rather than a single pre-Core Goal layer.

The most important correction is:

- Goal Brief defines the problem
- Core produces the facts
- Goal Consumer interprets those facts

Current backend-local work has already moved part of the Core forward:

- `document_profiles` is a real artifact
- `application/evidence/` and `application/comparisons/` exist as real backend
  packages
- indexing already runs Core stages before the protocol branch
- workspace and artifact registry already expose Core-oriented readiness states
- `application/goals/` exists, but should currently be interpreted as Goal
  Brief / Intake only

The main implementation gaps are now clearer:

- Source & Collection Builder does not yet expose one explicit normalized
  import seam
- Goal Brief / Intake exists but can be mistaken for the full Goal layer
- Goal Consumer / Decision logic over Core outputs does not exist yet
- derived surfaces such as protocol, graph, and reports still need clearer
  dependency language in some places

## Scope

This plan covers backend-owned implementation waves for:

- Core artifact completion
- Core versus Protocol boundary repair
- Goal Brief / Intake contract clarification
- Source & Collection Builder expansion seams
- Goal Consumer / Decision-layer introduction
- downstream derived-view alignment

This plan does not cover:

- frontend IA or page design
- provider or vendor selection for external search
- crawler-specific infrastructure decisions
- root product positioning changes

## Proposed Change

### Execution Rules

- keep one collection-backed Core artifact model for paper-first and goal-first
  entry
- do not allow Goal Brief logic to generate research judgments
- do not allow Source & Collection Builder logic to bypass collection creation
  or Core pipelines
- do not allow Goal Consumer logic to create a second fact model parallel to
  the Core
- keep protocol, graph, and reports downstream of Core artifacts
- prefer boundary refactors that preserve current behavior before adding richer
  decision surfaces

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

- remove the reverse dependency where Core services import protocol-owned
  parsing helpers

Primary changes:

- move shared helpers such as document-record assembly, text-unit joining, and
  section derivation out of `application/protocol/`
- place those helpers under a Core-owned seam, preferably under
  `application/documents/` or a narrowly scoped Core parsing package
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
- make SOP generation depend on filtered protocol outputs, not on raw
  protocol-like text hits

Exit criteria:

- task history clearly shows Core stages before protocol stages
- protocol-limited collections still complete indexing successfully
- protocol branch failures do not redefine the Core contract

### Wave 4: Normalize Goal Brief / Intake

Goal:

- keep the current goal-first entry surface thin, explicit, and correctly
  placed before the Core

Current child execution entrypoint:

- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)

Primary changes:

- treat `application/goals/` and `controllers/goals.py` as Goal Brief / Intake
  rather than as the full Goal layer
- keep the current durable intake objects intentionally narrow:
  `research_brief`, `coverage_assessment`, `seed_collection`,
  `entry_recommendation`
- document that current `coverage_assessment` is intake-side and provisional,
  not the final Goal Consumer coverage view
- keep goal-first entry converging on a collection handoff into the Core

Non-goals:

- no direct comparison generation inside Goal Brief / Intake
- no direct SOP generation from Goal Brief / Intake
- no monolithic goal agent that bypasses traceability

Exit criteria:

- a goal-first path results in a collection that lands in the same workspace
  and Core artifact endpoints as a paper-first path
- current goal responses are understood as brief-and-handoff responses, not as
  research conclusions

### Wave 5: Harden Source & Collection Builder

Goal:

- support more ways to form or enrich collections without leaking acquisition
  logic into research semantics

Current child execution entrypoint:

- [`source-collection-builder-normalization-plan.md`](source-collection-builder-normalization-plan.md)

Primary changes:

- expand `infra/ingestion/` with search adapters, connectors, and crawler-style
  acquisition seams
- keep source normalization, metadata capture, and import mechanics in
  infrastructure-owned or collection-builder-owned packages
- align upload, search, crawler, and goal-seeding flows around one normalized
  handoff shape
- let acquisition flows populate collections or collection drafts, but not Core
  artifacts directly

Exit criteria:

- upload, external search, and connector-driven inputs all end at collection
  boundaries
- Source & Collection Builder adapters remain replaceable without changing Core
  contracts

### Wave 6: Add Goal Consumer / Decision Layer

Goal:

- add a post-Core goal-oriented consumer that organizes judgment support around
  user intent

Primary changes:

- add Goal Consumer services that read `document_profiles`, `evidence_cards`,
  and `comparison_rows`
- define consumer-owned outputs such as grounded coverage assessment, gap
  detection, ranked clues, and next-step support
- keep those outputs traceable to Core artifacts and compatible with workspace
  navigation

Non-goals:

- no alternate fact model beside the Core
- no goal-only evidence objects with no Core traceback

Exit criteria:

- goal-oriented views consume Core outputs rather than replacing them
- coverage and recommendation semantics are grounded in Core artifacts

### Wave 7: Align Derived Views / Downstream

Goal:

- keep downstream surfaces explicitly dependent on the Core rather than on
  independent semantic pipelines

Primary changes:

- document and harden protocol as a Core-gated downstream branch
- continue the graph transition toward Core-derived semantics
- keep report and export surfaces positioned as downstream consumers

Exit criteria:

- downstream routes are documented and implemented as derived surfaces
- no derived view reclaims ownership of primary research facts

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

### Goal Brief / Intake

- `application/goals/`
- `controllers/goals.py`
- `controllers/schemas/goals.py`
- contract references in `docs/specs/api.md`

### Source & Collection Builder

- `application/collections/`
- `infra/ingestion/`
- future adapter-specific subpackages under `infra/ingestion/`
- collection-builder handoff integration into `application/collections/`

### Goal Consumer / Decision Layer

- future consumer logic under `application/goals/` or a closely related
  goal-oriented package
- future goal-oriented read models or route surfaces that consume Core outputs

### Derived Views / Downstream

- `application/protocol/`
- `application/graph/`
- `application/reports/`

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
- Goal Brief / Intake converges on collection handoff rather than bypassing
  the Core
- Source & Collection Builder adapters can seed collections but cannot write
  Core artifacts directly
- Goal Consumer views read Core outputs instead of inventing parallel facts
- derived routes remain downstream of Core readiness and Core suitability

### Test Slices

- unit tests for shared Core parsing helpers after extraction
- unit tests for evidence extraction and comparison normalization
- integration tests for real collection document, evidence, and comparison
  endpoints
- app-layer tests for Goal Brief / Intake contract objects
- contract tests for Source & Collection Builder non-bypass rules
- future tests for Goal Consumer views over Core artifacts

## Risks

- the old file path and historical plan names can cause readers to project the
  earlier three-layer shorthand onto the newer five-layer model
- Goal Brief / Intake can sprawl if it is allowed to act like Goal Consumer
- Source & Collection Builder expansion can become a crawler project unless
  collection handoff stays explicit
- Goal Consumer can create semantic duplication if it is not kept strictly
  downstream of the Core

## Related Docs

- [`current-api-surface-migration-checklist.md`](current-api-surface-migration-checklist.md)
- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)
- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
- [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`evidence-first-parsing-plan.md`](evidence-first-parsing-plan.md)
- [`v1-api-migration-notes.md`](v1-api-migration-notes.md)
