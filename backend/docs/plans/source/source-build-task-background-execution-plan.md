# Source Build Task Background Execution Plan

## Summary

This document records the minimal Source-layer execution plan for collection
builds:

keep file upload synchronous and narrow, create a build task that returns
immediately, run the real build flow outside the main request loop, and let
clients poll task status by `task_id`.

This is a Source-owned execution plan because it is primarily about collection
construction, task progression, and Source-to-Core handoff behavior. It does
not change the public API contract defined in
[`../../specs/api.md`](../../specs/api.md).

## Context

The current frontend-facing contract already points clients to this flow:

1. `POST /api/v1/collections`
2. `POST /api/v1/collections/{collection_id}/files`
3. `POST /api/v1/collections/{collection_id}/tasks/build`
4. poll `GET /api/v1/tasks/{task_id}`

That contract shape is correct for Lens v1. The operational failure comes from
how the build work executes after task creation.

Current backend facts:

- `controllers/source/tasks.py` creates a build task and schedules the real
  work through `CollectionBuildTaskRunner`
- `application/source/collection_build_task_runner.py` runs a long chain that
  includes Source artifact generation, document profiles, paper facts,
  comparison rows, and conditional protocol work
- several steps in that chain are synchronous heavy work even when they are
  called from an `async` route or wrapper
- synchronous LLM calls or CPU-heavy dataframe work inside the main request
  event loop can still block unrelated API traffic on a single-worker process

The key rule is simple:

- `async` route shape alone does not guarantee non-blocking behavior
- long-running build execution must be isolated from the main request loop

## Scope

This plan covers:

- the minimal execution model for collection builds
- the required split between upload, task creation, background build
  execution, and task-status reads
- the minimum task lifecycle fields needed for frontend polling
- the smallest acceptable isolation rule for single-node backend deployment

This plan does not cover:

- introducing Celery, Redis, RabbitMQ, or another distributed task system
- task cancellation, retries, or priority queues
- multi-instance task coordination
- changing the public request or response shapes for the existing build-task
  routes
- changing the Core semantic build order

## Proposed Change

### Design Rule

Collection build is a background task model, not a request-response model.

That means:

- upload requests store files and return
- build-task requests create task records and return
- background execution owns the long-running build chain
- task detail routes expose progress and terminal status

### Minimal Runtime Shape

#### 1. File upload stays narrow

`POST /api/v1/collections/{collection_id}/files` should only do collection
file registration and storage.

It should not start the full semantic build as part of the upload request.

#### 2. Build task creation returns immediately

`POST /api/v1/collections/{collection_id}/tasks/build` should do only these
steps:

- validate that the collection exists
- validate that at least one file is present
- create a task record
- schedule background execution
- return the created `task_id`

The request should not wait for:

- Source artifact generation
- document profile extraction
- paper facts extraction
- comparison row assembly
- protocol artifact generation

#### 3. Background execution must leave the request loop

The real build chain must run outside the main request event loop.

The minimum acceptable implementation for the current single-node backend is:

- schedule a synchronous background entrypoint
- run the full build chain in a worker thread or equivalent isolated executor
- keep task-state updates in `TaskService` as the observable progress contract

This plan intentionally chooses the smallest isolated runtime that fits the
current repository:

- no new queue infrastructure
- no new deployment dependency
- no compatibility layer between the route and the real runner

#### 4. Task status polling stays the primary progress surface

`GET /api/v1/tasks/{task_id}` remains the primary polling route.

At minimum, clients need:

- `task_id`
- `task_type`
- `status`
- `current_stage`
- `progress_percent`
- `warnings`
- `errors`

`GET /api/v1/collections/{collection_id}/tasks` remains the history surface
for collection-scoped task lists.

#### 5. Frontend flow remains poll-driven

The frontend should continue to:

1. upload files
2. create a build task
3. poll `GET /api/v1/tasks/{task_id}`
4. open workspace and downstream resources only after terminal task state or
   sufficient readiness

This keeps the browser contract simple and aligned with the current public API
surface.

## Why This Is The Minimal Fix

The backend does not need a larger task platform to solve the immediate
blocking problem.

The immediate problem is not the absence of a status route. The status route
already exists. The immediate problem is that long-running build work can
still execute on the same main request loop as unrelated API traffic.

The smallest correct fix is therefore:

- keep the current build-task API contract
- keep the current task registry model
- move the long-running execution off the main request loop

Anything larger should be deferred until the repository actually needs:

- cross-process queue durability
- retries after worker restart
- distributed scheduling
- explicit cancellation controls

## Implementation Slice

### Phase 1: Preserve The Existing HTTP Contract

Keep these routes as the stable frontend contract:

- `POST /api/v1/collections/{collection_id}/tasks/build`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`

No new compatibility route should be added in this wave.

### Phase 2: Offload The Real Build Chain

Keep `CollectionBuildTaskRunner` as the owning application-layer runner, but
ensure the route schedules an entrypoint that executes outside the main
request loop.

The execution rule is:

- task creation and scheduling happen in the request path
- task progression and artifact generation happen in the isolated background
  path

### Phase 3: Keep Task Progress Observable

Every stage transition should continue to write task state that can be read by
polling clients.

The minimum externally meaningful sequence is:

- `queued`
- `files_registered`
- `source_artifacts_started`
- `source_artifacts_completed`
- `document_profiles_started`
- `paper_facts_started`
- `comparison_rows_started`
- `protocol_artifacts_started`
- `artifacts_ready`
- `failed`

Terminal `status` remains:

- `completed`
- `partial_success`
- `failed`

## Verification

This plan is working when these checks hold:

1. `POST /api/v1/collections/{collection_id}/tasks/build` returns a `task_id`
   without waiting for artifact generation to finish.
2. While a build is running, unrelated routes such as
   `GET /api/v1/tasks/{task_id}`, `GET /api/v1/collections`, or read-only
   collection routes remain responsive on the same backend instance.
3. Task polling shows stage progression through the existing task payload.
4. Completion and failure are visible through task status without requiring the
   build request to stay open.

## Follow-Up Boundary

If the repository later needs durable multi-process execution, retries, or
cross-instance scheduling, record that as a new Source or backend-wide plan.

That future wave should replace the same execution seam directly. It should
not introduce a temporary compatibility layer that keeps both in-process and
distributed task models alive by default.
