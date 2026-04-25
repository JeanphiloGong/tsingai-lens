# Index-To-Build Contract Cutover Plan

## Summary

This plan records one backend-wide contract cleanup wave:

replace the remaining product-facing `index` vocabulary with `build`
vocabulary, then align frontend/backend task and workspace contracts to the
real collection-processing flow.

This wave exists because the current Lens v1 collection task is no longer "just
indexing":

- Source builds structure-first source artifacts
- Core builds document profiles
- Core builds paper facts and evidence views
- Core builds comparison rows
- protocol remains a conditional downstream build branch

The current public contract still says `index`, while the frontend also still
contains older drift such as `graphrag_index_*`, `sections_ready`, and
`graphml_ready`.

This plan defines one coordinated hard cut for backend and frontend. It does
not allow a long-lived compatibility route family.

Read this plan with:

- [`frontend-facing-contract-cleanup-plan.md`](../frontend-facing-contract-cleanup/implementation-plan.md)
- [`current-api-surface-migration-checklist.md`](../api-surface-migration/current-state.md)
- [`../../specs/api.md`](../../../specs/api.md)
- [`../../../../frontend/docs/frontend-plan.md`](../../../../../frontend/docs/frontend-plan.md)

## Why This Wave Is Needed

### 1. `index` no longer describes the real product task

The active collection task does much more than Source-only indexing.

Current backend flow:

1. register files
2. build Source artifacts
3. build document profiles
4. build paper facts and evidence-card views
5. build comparison rows
6. optionally build protocol artifacts

That means:

- `POST /api/v1/collections/{collection_id}/tasks/index` is semantically too
  narrow
- `task_type="index"` is misleading in frontend state and logs
- `source_index_started` and `source_index_completed` still overfit an older
  indexing-era mental model

### 2. Frontend is already out of sync with the current backend

Current frontend code still expects outdated contract pieces:

- [`../../../../frontend/src/routes/_shared/tasks.ts`](../../../../../frontend/src/routes/_shared/tasks.ts)
  still types `graphrag_index_started` and `graphrag_index_completed`
- the same file still calls
  `POST /api/v1/collections/{collection_id}/tasks/index`
- [`../../../../frontend/src/routes/_shared/workspace.ts`](../../../../../frontend/src/routes/_shared/workspace.ts)
  still expects `sections_ready` and `graphml_ready`
- [`../../../../frontend/src/routes/collections/[id]/+layout.svelte`](../../../../../frontend/src/routes/collections/[id]/+layout.svelte)
  still treats `graphml_ready` as a graph visibility signal
- [`../../../../frontend/src/routes/_shared/i18n.ts`](../../../../../frontend/src/routes/_shared/i18n.ts)
  still renders GraphRAG-era stage labels

This means the next vocabulary cleanup should not be treated as a backend-only
rename. The frontend contract needs one explicit synchronized cut.

## Scope

This plan covers:

- renaming the public collection task from `index` to `build`
- replacing task-stage names that still imply indexing-engine ownership
- freezing the frontend-consumed task/workspace contract around current
  build/backbone semantics
- removing frontend dependence on stale readiness keys such as
  `sections_ready` and `graphml_ready`
- renaming backend application/runtime entrypoints whose names leak the old
  product mental model

This plan does not cover:

- redesign of Goal intake or collection creation
- protocol branch redesign
- graph/report route-family renaming
- parser or extraction algorithm changes
- adding compatibility routes, aliases, wrappers, or dual-path payload fields

## Contract Decision

### Rule 1: Product-facing collection processing is a build task

Frontend and backend should both describe the collection-processing action as
`build`, not `index`.

That applies to:

- route naming
- task type
- button and status copy
- internal app-layer orchestration names that are still visible in controller
  or service seams

### Rule 2: Task stages should describe build phases, not engine history

Frontend should consume stage names that describe what is being produced, not
what historical engine once owned the phase.

That means:

- remove `graphrag_index_*` entirely
- stop using `source_index_*`
- stop using `evidence_cards_started` as the name of the larger paper-facts
  extraction phase

### Rule 3: Frontend should use capabilities and workflow, not stale artifact flags

For primary UI decisions, frontend should prefer:

- `workspace.workflow`
- `workspace.capabilities`
- `workspace.warnings`
- `latest_task.status`
- `latest_task.current_stage`

Frontend must not use these as long-term primary contract signals:

- `sections_ready`
- `graphml_ready`
- other Source-internal substrate flags that do not express a stable user
  capability

GraphML export availability should come from:

- `capabilities.can_download_graphml`
- with `artifacts.graph_ready` as the structural backend precondition

### Rule 4: This cut is a coordinated hard cut

Because frontend is adjusting in the same wave, this plan explicitly chooses:

- no `/tasks/index` and `/tasks/build` dual route support
- no dual `task_type=index|build` compatibility field handling
- no stage alias normalization for old frontend values

Backend and frontend should be merged and released together for this wave.

## Target Public Contract

### 1. Build Task Create

Current public route:

- `POST /api/v1/collections/{collection_id}/tasks/index`

Target public route:

- `POST /api/v1/collections/{collection_id}/tasks/build`

Target request shape for the main frontend path:

```json
{
  "additional_context": {
    "optional": "debug or caller context"
  }
}
```

Notes:

- the frontend main flow should call only `/tasks/build`
- this plan does not require frontend to send `verbose`
- if `verbose` remains temporarily available in backend schema for local
  debugging, frontend should still ignore it

### 2. Task Response

Current response shape stays structurally similar, but task identity changes:

```json
{
  "task_id": "task_123",
  "collection_id": "col_123",
  "task_type": "build",
  "status": "queued",
  "current_stage": "queued",
  "progress_percent": 0,
  "output_path": null,
  "errors": [],
  "warnings": [],
  "created_at": "...",
  "updated_at": "...",
  "started_at": null,
  "finished_at": null
}
```

The target contract is:

- `task_type` is always `build` for this collection-processing task family
- frontend should stop defaulting missing `task_type` to `index`

### 3. Task Stage Enum

Current-to-target public stage mapping:

| Current stage | Target stage | Reason |
| --- | --- | --- |
| `queued` | `queued` | keep |
| `files_registered` | `files_registered` | keep |
| `source_index_started` | `source_artifacts_started` | phase builds Source artifacts, not generic indexing |
| `source_index_completed` | `source_artifacts_completed` | same reason |
| `document_profiles_started` | `document_profiles_started` | keep |
| `evidence_cards_started` | `paper_facts_started` | phase builds paper facts first, evidence cards are only one derived view |
| `comparison_rows_started` | `comparison_rows_started` | keep |
| `protocol_artifacts_started` | `protocol_artifacts_started` | keep |
| `artifacts_ready` | `artifacts_ready` | keep |
| `failed` | `failed` | keep |

Explicit removals:

- `graphrag_index_started`
- `graphrag_index_completed`
- `source_index_started`
- `source_index_completed`
- `evidence_cards_started`

### 4. Task Artifacts Response

The task-artifacts route remains:

- `GET /api/v1/tasks/{task_id}/artifacts`

But the frontend-consumed contract should stop depending on stale fields.

Frontend-stable fields:

- `documents_ready`
- `document_profiles_ready`
- `evidence_cards_ready`
- `comparison_rows_ready`
- `graph_ready`
- `protocol_steps_ready`
- `updated_at`

Backend may still expose additional structural readiness fields for local
debugging, but frontend should not model these as primary stable page-state
inputs:

- `blocks_ready`
- `table_rows_ready`
- `table_cells_ready`
- `procedure_blocks_ready`

Removed from frontend contract:

- `sections_ready`
- `graphml_ready`

### 5. Workspace Contract

The workspace route stays:

- `GET /api/v1/collections/{collection_id}/workspace`

Target frontend contract rules:

- graph-tab visibility should use
  `capabilities.can_view_graph || capabilities.can_download_graphml || artifacts.graph_ready`
- frontend should not read `graphml_ready`
- frontend should not read `sections_ready`
- frontend should continue treating `workflow` as the primary collection-state
  model

## Backend Change Plan

### Wave A: Public Route And Schema Hard Cut

Primary backend changes:

- rename the route in
  [`../../../controllers/source/tasks.py`](../../../../controllers/source/tasks.py)
  from `/tasks/index` to `/tasks/build`
- rename request/handler symbols from `IndexTask*` / `create_index_task` to
  `BuildTask*` / `create_build_task`
- change task creation in
  [`../../../application/source/task_service.py`](../../../../application/source/task_service.py)
  from `task_type="index"` to `task_type="build"`
- update
  [`../../../controllers/schemas/source/task.py`](../../../../controllers/schemas/source/task.py)
  to the new task-stage enum
- update [`../../specs/api.md`](../../../specs/api.md) to the new route and stage
  vocabulary

Exit criteria:

- public backend no longer exposes `/tasks/index`
- public task payload no longer emits `task_type="index"`
- public task payload no longer emits the removed stage values

### Wave B: App-Layer Build Vocabulary Cleanup

Primary backend changes:

- rename
  [`../../../application/source/collection_build_task_runner.py`](../../../../application/source/collection_build_task_runner.py)
  to a build-oriented name such as `collection_build_task_runner.py`
- rename `IndexTaskRunner` to `CollectionBuildTaskRunner`
- rename `run_index_task()` to `run_build_task()`
- update logs to say `build task` instead of `index task`
- update any tests that still assert `index` naming

Recommended stage changes inside the runner:

- `source_index_started` -> `source_artifacts_started`
- `source_index_completed` -> `source_artifacts_completed`
- `evidence_cards_started` -> `paper_facts_started`

Exit criteria:

- backend application orchestration no longer uses `index task` as the primary
  product-facing orchestration name
- task-stage updates match the new public enum

### Wave C: Source Runtime Internal Cleanup

This wave is internal and does not change frontend contracts, but it completes
the naming correction.

Primary backend changes:

- rename [`../../../infra/source/runtime/build_source_artifacts.py`](../../../../infra/source/runtime/build_source_artifacts.py)
  to a build-oriented runtime entry such as `build_source_artifacts.py` or
  `run_source_pipeline.py`
- rename `build_index()` to a name that describes the current runtime job
- evaluate whether `IndexingMethod` should also be renamed to a Source-runtime
  pipeline/profile name now that frontend no longer sees it

Exit criteria:

- Source runtime entry naming no longer suggests that the whole job is generic
  indexing

## Frontend Change Plan

### Frontend Contract Files

Frontend files that need direct contract updates:

- [`../../../../frontend/src/routes/_shared/tasks.ts`](../../../../../frontend/src/routes/_shared/tasks.ts)
- [`../../../../frontend/src/routes/_shared/workspace.ts`](../../../../../frontend/src/routes/_shared/workspace.ts)
- [`../../../../frontend/src/routes/_shared/i18n.ts`](../../../../../frontend/src/routes/_shared/i18n.ts)
- [`../../../../frontend/src/routes/+page.svelte`](../../../../../frontend/src/routes/+page.svelte)
- [`../../../../frontend/src/routes/collections/[id]/+page.svelte`](../../../../../frontend/src/routes/collections/[id]/+page.svelte)
- [`../../../../frontend/src/routes/collections/[id]/+layout.svelte`](../../../../../frontend/src/routes/collections/[id]/+layout.svelte)
- [`../../../../frontend/src/routes/collections/lens-v1-interface-spec.md`](../../../../../frontend/src/routes/collections/lens-v1-interface-spec.md)
- [`../../../../frontend/docs/frontend-plan.md`](../../../../../frontend/docs/frontend-plan.md)

### Frontend Required Changes

1. Replace `createIndexTask()` with `createBuildTask()`.
2. Call `POST /api/v1/collections/{collection_id}/tasks/build`.
3. Replace the frontend `TaskStage` union with the target enum from this plan.
4. Stop typing `task_type` with an `index` default.
5. Remove `sections_ready` and `graphml_ready` from frontend task/workspace
   models.
6. Use `capabilities.can_download_graphml` for GraphML UI enablement.
7. Update i18n labels from GraphRAG/indexing wording to build/backbone wording.
8. Update collection-page action copy so the user starts a `build`, not an
   `index`.

### Frontend Non-Goals In This Wave

Frontend does not need to:

- redesign collection IA again
- rename graph or protocol route families
- add a temporary compatibility adapter for `/tasks/index`

## Execution Shape

Recommended order:

1. freeze this contract in docs
2. update backend route/schema/task-stage implementation
3. update frontend API helpers/types/i18n/UI in the same branch or release wave
4. run backend route tests and frontend type/UI checks
5. update stable backend and frontend docs after the code cut lands

Because this repository contains both backend and frontend, the preferred
delivery shape is one coordinated implementation wave rather than staggered
deployment with compatibility baggage.

## Verification

### Backend Verification

- task creation route works only at `/tasks/build`
- `GET /api/v1/tasks/{task_id}` returns `task_type="build"`
- task stage progression matches the target enum
- workspace still reports graph export availability through
  `capabilities.can_download_graphml`
- app-layer and router tests are updated to the new route and stage vocabulary

### Frontend Verification

- no frontend code calls `/tasks/index`
- no frontend type union still includes `graphrag_index_*`
- no frontend code reads `sections_ready`
- no frontend code reads `graphml_ready`
- collection pages still poll tasks and render stage/status correctly
- graph visibility/export controls still work through
  `can_view_graph`, `can_download_graphml`, and `graph_ready`

### Joint Verification

- create collection
- upload file
- start build
- poll task
- open workspace
- verify document/evidence/comparison surfaces
- verify graph export remains available when the Core graph is ready

## Risks

- a backend-only route rename would immediately break the current frontend
- a frontend-only adjustment would fail until the backend build route exists
- if the stage rename stops at `build` but not at `paper_facts_started`, task
  status would still overfit old evidence-card vocabulary
- if frontend keeps typing debug-only readiness fields as stable contract,
  future Source cleanup waves will keep breaking UI assumptions

## Acceptance Bar

This plan is complete when:

- the collection-processing action is called `build` across backend and
  frontend public surfaces
- frontend task polling no longer contains GraphRAG/indexing-era stage names
- frontend no longer depends on `sections_ready` or `graphml_ready`
- backend and frontend both describe the task as the current backbone build
  flow rather than as generic indexing

## Related Docs

- [`frontend-facing-contract-cleanup-plan.md`](../frontend-facing-contract-cleanup/implementation-plan.md)
- [`current-api-surface-migration-checklist.md`](../api-surface-migration/current-state.md)
- [`../../specs/api.md`](../../../specs/api.md)
- [`../../../../frontend/docs/frontend-plan.md`](../../../../../frontend/docs/frontend-plan.md)
- [`../../../../frontend/src/routes/collections/lens-v1-interface-spec.md`](../../../../../frontend/src/routes/collections/lens-v1-interface-spec.md)
