# Frontend-Facing Contract Cleanup Plan

## Summary

This plan records one narrow contract-cleanup decision for frontend/backend
integration:

frontend should consume product semantics, not indexing-engine semantics.

In the current backend surface, `standard`, `fast`, and `is_update_run` are
still exposed through collection and task contracts. Those values describe
retrieval/indexing execution strategy. They do not describe stable Lens
product behavior and should not be treated as frontend-facing user choices.

The target frontend contract should instead revolve around:

- collection lifecycle
- workspace readiness
- capabilities
- goal-driven entry recommendation such as `comparison` or `exploratory`
- Core-backed document, evidence, comparison, protocol, graph, and report
  surfaces

## Purpose

This plan exists to answer one backend-local question:

how should the public API be cleaned up so frontend integration does not bind
itself to internal Source/indexing engine modes.

It is a child plan under the five-layer architecture and current API migration
work. It does not redefine the architecture itself.

## Why This Cleanup Is Needed

The current API still leaks internal execution choices into public contracts.

Current leakage points include:

- [`../../../controllers/schemas/source/collection.py`](../../../controllers/schemas/source/collection.py)
  exposes `default_method`
- [`../../../controllers/schemas/source/task.py`](../../../controllers/schemas/source/task.py)
  exposes `method` and `is_update_run`
- [`../../../application/source/collection_service.py`](../../../application/source/collection_service.py)
  persists `default_method` as collection metadata
- [`../../../application/source/collection_build_task_runner.py`](../../../application/source/collection_build_task_runner.py)
  accepts a caller-provided indexing method
- [`../../../infra/source/config/pipeline_mode.py`](../../../infra/source/config/pipeline_mode.py)
  defines `IndexingMethod.Standard` and `IndexingMethod.Fast` as engine-level
  execution options

These values are not part of the stable product model.

From the five-layer perspective:

- Goal Brief may recommend `comparison` or `exploratory`
- Source & Collection Builder may choose how to ingest and index
- Research Intelligence Core produces the stable fact artifacts
- Derived Views consume Core outputs

`standard` and `fast` belong to Source/indexing execution strategy.
They should not be presented as first-class product controls to frontend.

## Scope

This cleanup covers:

- frontend-facing collection creation contract
- frontend-facing task creation contract
- frontend-facing collection/task response payload cleanup
- service-side defaulting and internal execution-mode ownership
- compatibility migration for existing frontend callers

This cleanup does not cover:

- redesign of Goal Brief or Goal Consumer payloads
- graph/report semantic cutover
- query runtime redesign
- evidence id stabilization
- frontend page IA redesign

## Contract Decision

### Rule 1: Frontend Must Not Choose Internal Indexing Mode

Frontend should not choose between:

- `standard`
- `fast`
- `standard-update`
- `fast-update`

These are Source/indexing implementation choices and should remain backend
owned.

### Rule 2: Frontend May Consume Product Entry Semantics

Frontend may continue to consume product-facing entry semantics such as:

- Goal `intent`
- Goal `recommended_mode`
- workspace `workflow`
- workspace `capabilities`
- workspace `warnings`

These are stable product semantics because they describe what the user is
trying to do and what the collection can currently support.

### Rule 3: Update Versus Rebuild Is Backend-Owned

Frontend should not decide `is_update_run` on the main product path.

The backend should infer or choose rebuild versus update based on:

- collection state
- artifact baseline availability
- vector-store baseline availability
- internal policy

### Rule 4: Collection Metadata Should Stay Product-Level

Collection metadata returned to frontend should describe:

- identity
- name
- description
- status
- paper_count
- timestamps

It should not expose retrieval-engine mode as a stable collection property.

## Target Public Contract

### 1. Collection Create

Current public request shape:

- `name`
- `description`
- `default_method`

Target public request shape:

- `name`
- `description`

Target behavior:

- backend creates the collection
- backend stores internal indexing policy separately if needed
- frontend does not send or display `default_method`

### 2. Collection Response

Current public response includes:

- `default_method`

Target public response excludes:

- `default_method`

Frontend should treat collection detail as product metadata only.

### 3. Index Task Create

Current public request shape includes:

- `method`
- `is_update_run`
- `verbose`
- `additional_context`

Target primary frontend request shape:

- optional `additional_context`

Backend-owned behavior:

- choose internal indexing profile
- choose update versus rebuild
- keep debug or verbose knobs internal or admin-only

Compatibility note:

- `verbose` may remain temporarily available for local development or internal
  tooling, but it should not be treated as part of the primary frontend flow

### 4. Task Response

Task response should remain focused on:

- task id
- status
- current stage
- progress
- warnings
- errors
- timestamps

Task responses should not gain engine-mode echo fields.

### 5. Workspace As Frontend Primary Read Model

Frontend should drive most UI state from:

- [`../../../controllers/schemas/core/workspace.py`](../../../controllers/schemas/core/workspace.py)

Primary frontend decisions should come from:

- `workflow`
- `capabilities`
- `warnings`
- `links`
- artifact readiness

This keeps the frontend anchored on collection/Core state rather than on
engine configuration.

### 6. Goal Intake As Product Entry Recommendation

Frontend may continue consuming:

- [`../../../controllers/schemas/goal/intake.py`](../../../controllers/schemas/goal/intake.py)

In particular:

- `research_brief`
- `coverage_assessment`
- `seed_collection`
- `entry_recommendation.recommended_mode`

`comparison` and `exploratory` are acceptable frontend-facing semantics
because they describe user workflow entry, not internal engine implementation.

## Backend Ownership After Cleanup

After cleanup, backend should own the following internal decisions:

### Internal Execution Profile

Backend chooses whether current indexing runs use:

- standard indexing
- fast indexing
- any future replacement strategy

This policy should remain hidden behind Source application and Source runtime
seams.

### Update Policy

Backend decides whether to:

- run a full rebuild
- attempt update mode
- downgrade update mode to rebuild

The current mode-selection and downgrade policy now lives across:

- [`../../../application/source/collection_build_task_runner.py`](../../../application/source/collection_build_task_runner.py)
- [`../../../infra/source/config/pipeline_mode.py`](../../../infra/source/config/pipeline_mode.py)

That logic should remain backend-owned rather than frontend-owned.

### Future Product Choice Mapping

If a future product requirement truly needs a user-visible depth/speed choice,
frontend still should not receive raw engine names.

Instead, frontend should receive product-level choices such as:

- `preview`
- `full`

The backend would then map those labels to the underlying execution strategy.

This mapping is deferred and should not block the current cleanup.

## Migration Plan

### Phase 1: Hide Engine Semantics From Primary Frontend Contract

Backend changes:

- remove `default_method` from public collection request/response schemas
- remove `method` and `is_update_run` from the primary task creation schema
- keep server-side defaults in application services

Compatibility behavior:

- backend may still accept legacy fields for one transition period
- backend should ignore or normalize legacy mode fields rather than letting
  them redefine runtime behavior

Exit criteria:

- frontend can create collections and start index runs without sending engine
  mode fields

### Phase 2: Move Frontend To Workspace-Driven State

Frontend changes:

- remove mode selectors and related state
- rely on workspace readiness and capabilities
- use goal `recommended_mode` only for entry routing

Exit criteria:

- primary collection flow no longer references `standard` or `fast`

### Phase 3: Remove Compatibility Path

Backend changes:

- remove compatibility handling for `default_method`, `method`, and
  `is_update_run` from primary public routes
- retain any needed internal or admin-only execution knobs outside the primary
  frontend contract

Exit criteria:

- public API no longer leaks indexing-engine terminology

## Frontend Integration Checklist

Frontend should integrate against the following stable flow:

1. Create collection with `name` and `description`
2. Upload files into the collection
3. Start index task without engine-mode parameters
4. Poll task status by `task_id`
5. Open workspace and branch UI using `workflow`, `capabilities`, and `links`
6. Open `documents/profiles`, `evidence/cards`, and `comparisons` as the Core
   backbone surfaces
7. Treat protocol, graph, and reports as derived surfaces gated by readiness
   and capability flags

Frontend should not:

- cache assumptions about `standard` versus `fast`
- display engine-mode labels in collection or task views
- bind UI state to update-mode decisions

## Verification

Backend verification should cover:

- collection create works without `default_method`
- collection read/list no longer require `default_method`
- task create works without `method`
- task create works without `is_update_run`
- backend ignores or safely normalizes legacy frontend payloads during the
  transition window
- workspace remains sufficient as the frontend state aggregator
- goal intake still exposes `recommended_mode`

## Risks And Follow-ups

### Risk 1: Hidden Engine Choice Can Still Leak Through Old Metadata

If `default_method` remains persisted internally for backward compatibility,
care is needed to ensure it does not reappear in public serializers.

### Risk 2: Frontend May Still Depend On Existing Fields

Before removing fields entirely, confirm whether any active frontend code still
expects them.

### Risk 3: Engine Names Can Leak Back Through Logs Or Admin Endpoints

This plan cleans the primary frontend contract only.
Admin, debug, or internal tooling routes should be reviewed separately if they
become frontend-reachable later.

### Follow-up: Stabilize Evidence Deep Links

This contract cleanup is independent from evidence traceback stability.

Current evidence ids are still generated with random `uuid4()`-style values in
the evidence service, so frontend should not treat traceback deep links as
stable across rebuilds until evidence ids become deterministic.

## Related Docs

- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)
- [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
- [`current-api-surface-migration-checklist.md`](current-api-surface-migration-checklist.md)
- [`core-first-product-surface-cutover-plan.md`](core-first-product-surface-cutover-plan.md)
