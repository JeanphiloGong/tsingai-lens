# Backend Request ID And Extraction Observability Plan

## Summary

This plan records one backend-wide observability wave for the current
collection indexing and Core extraction path.

The immediate problem is not only that `comparison_rows` may end up empty. It
is that the backend currently makes that failure mode hard to diagnose:

- logs do not carry a request-scoped correlation id
- background index tasks lose request-level context once they leave the HTTP
  request stack
- Core structured extraction does not emit enough diagnostics to distinguish
  between:
  - model returned no useful structured payload
  - model returned partial payload
  - post-processing dropped extracted results
  - comparison assembly had no usable upstream measurements

The target state is a backend where one request can be traced end to end
through HTTP entry, background indexing, Core extraction, and comparison
assembly with consistent request correlation and explicit extraction
diagnostics.

## Purpose

This page exists to answer one backend-owned question:

how should the backend add request-scoped logging and Core extraction
diagnostics without adding a new compatibility layer or a parallel logging
stack.

This is a backend-wide implementation plan. It does not redefine the public
product surface or the Core artifact semantics.

## Why This Belongs In `backend-wide/`

The lowest common owner of this wave is the backend module itself rather than a
single business layer.

The work crosses:

- HTTP app entry in `main.py`
- shared logging setup in `utils/logger.py`
- Source task creation in `controllers/source/tasks.py`
- Source indexing orchestration in `application/source/index_task_runner.py`
- Core document/evidence/comparison generation in `application/core/*`

This is therefore not only a Core quality plan and not only a Source task
plan.

## Scope

This wave covers:

- request id injection for incoming HTTP requests
- response echo of the effective request id
- request id propagation into background index tasks
- logger context binding so backend log records carry the same request id
- Core extraction diagnostics for document profiles, evidence extraction, and
  comparison assembly
- logging-level boundaries for `info`, `debug`, `warning`, and `error`
- focused verification for middleware and extraction diagnostics

This wave does not cover:

- shipping a new external tracing system
- changing Core extraction semantics
- changing comparison contract shape
- logging full prompts or full model raw responses by default
- persisting request ids into collection or task state as a new stored
  contract

## Current Problems

### 1. No request-scoped correlation in backend logs

Current logs may show that indexing or extraction ran, but they do not provide
a reliable request-scoped join key across:

- HTTP request handling
- background task enqueue
- background task execution
- Core extraction internals

This makes one user-reported failure hard to reconstruct from logs alone.

### 2. Core extraction diagnostics are too coarse

The current task runner can warn that no `comparison_rows` were produced, but
that is late and too aggregated.

It does not directly tell the operator whether:

- `table_cells` were empty
- section bundles returned no structured outputs
- table-row bundles returned no measurement payloads
- extracted measurements were dropped during normalization
- comparison assembly received zero measurement rows

### 3. Default logs should stay readable

The system needs better diagnosis, but the default `info` stream should still
be readable for normal operation. That means the implementation must separate:

- stable flow summaries at `info`
- per-section and per-row detail at `debug`
- suspicious-but-recoverable conditions at `warning`

## Decision

### 1. Use one backend-owned request id context

The backend should use one request-scoped id under the public header name
`X-Request-ID`.

Behavior:

- if the incoming request already has `X-Request-ID`, reuse it
- otherwise generate a backend-owned id such as `req_<hex>`
- bind that id into the logging context for the lifetime of the request
- write the effective id back to the response header

### 2. Propagate request id into background index execution

Index tasks started from the HTTP layer should explicitly inherit the current
request id when the background task is scheduled.

This keeps one log lineage across:

- `POST /collections/{collection_id}/tasks/index`
- task enqueue
- source indexing
- Core extraction
- comparison generation

The request id remains a logging concern, not a new persisted task contract in
this wave.

### 3. Add Core extraction diagnostics at the real owning services

Diagnostics should be added directly inside the owning implementations:

- `DocumentProfileService`
- `PaperFactsService`
- `ComparisonService`
- the structured OpenAI client only for failure logging

No wrapper logger, facade service, or alternate extraction path should be
introduced.

### 4. Keep prompt and raw-response logging off by default

The backend should not default to logging:

- full prompts
- full user document payloads
- full raw model responses

By default it should log only metadata and counters needed for diagnosis:

- collection id
- task id when available
- document id / section id / table row coordinates
- request id
- bundle counts
- drop reasons
- final artifact counts

## Logging Level Policy

### `INFO`

Use `info` for stable flow checkpoints and compact summaries that should remain
visible in normal operations:

- HTTP request start and finish
- index task start and finish
- collection-level extraction start and finish
- per-document extraction summaries
- comparison assembly summaries

### `DEBUG`

Use `debug` for high-cardinality diagnostic detail:

- per-section extraction start and bundle counts
- per-table-row extraction start and bundle counts
- measurement normalization detail
- measurement drop decisions
- row-level comparison filtering detail

### `WARNING`

Use `warning` when the system completes but produces suspicious low-value
output:

- empty `table_cells`
- evidence extracted but `measurement_results` still zero
- empty comparison output for a collection expected to be comparable
- invalid incoming request id replaced by a backend-generated id

### `ERROR` / `EXCEPTION`

Use `error` or `exception` for true failures:

- LLM call failure
- structured parse failure
- index task failure
- unhandled middleware failure

## Implementation Slices

### Slice 1: Shared logging context foundation

Update the shared backend logger so every log record can carry a `request_id`
field via backend-owned context binding.

Planned changes:

- add request-id context storage in `utils/logger.py`
- inject `request_id` into the logging formatter through a filter
- expose small helper functions for bind / clear / read of the current request
  id

### Slice 2: HTTP middleware request id injection

Add one FastAPI middleware in `main.py` that:

- reads `X-Request-ID`
- validates or normalizes it
- generates a new id when missing
- binds it to logging context
- sets `request.state.request_id`
- echoes `X-Request-ID` in the response
- logs request start and finish

### Slice 3: Background task propagation

Update `controllers/source/tasks.py` and
`application/source/index_task_runner.py` so background indexing inherits the
current request id explicitly.

The background runner should bind that request id for the task execution scope
and clear it afterward.

### Slice 4: Document profile diagnostics

Update `DocumentProfileService` to log:

- collection-level profile build start and finish
- number of documents and sections considered
- per-document classification result
- profile warning counts

### Slice 5: Paper facts extraction diagnostics

Update `PaperFactsService` to log:

- per-document section count and grouped table-row count
- per-section bundle counts
- per-table-row bundle counts
- final collection artifact totals for:
  - evidence cards
  - sample variants
  - test conditions
  - baseline references
  - measurement results
- explicit drop warnings when measurement payload normalization removes the
  result

This slice is the main diagnosis surface for “why did Core produce no
comparison inputs”.

### Slice 6: Comparison assembly diagnostics

Update `ComparisonService` to log:

- input counts for measurement results, sample variants, test conditions,
  baseline references, and evidence cards
- final comparison row count
- explicit warning when comparison rows are empty because measurement results
  are empty

### Slice 7: Verification

Add or update focused tests for:

- response header contains `X-Request-ID`
- caller-provided `X-Request-ID` is echoed back
- request id reaches the background task execution path
- Core diagnostic warnings are emitted for empty measurement output
- comparison diagnostic warning is emitted for empty upstream measurements

## Acceptance Criteria

This wave is complete when all of the following are true:

1. Every backend request emits logs with a stable `request_id`.
2. `POST /api/v1/collections/{collection_id}/tasks/index` can be traced from
   request entry through background task execution with the same request id in
   logs.
3. Core extraction logs make it possible to distinguish:
   - no table rows available
   - no measurement bundle returned
   - measurement dropped during normalization
   - comparison empty because upstream measurement results are empty
4. Default `info` logs remain compact and operationally readable.
5. The implementation adds no adapter, wrapper, shim, facade, or dual-path
   logging layer.

## Risks And Constraints

- Over-logging at `info` would make normal task logs harder to use, so
  per-section and per-row detail must stay at `debug`.
- Logging full prompts or raw responses would create noisy and potentially
  sensitive logs, so this wave intentionally avoids that.
- Background tasks do not automatically inherit request context; propagation
  must be explicit.

## Related Docs

- [`current-api-surface-migration-checklist.md`](../api-surface-migration/current-state.md)
- [`goal-source-core-business-layer-alignment-plan.md`](../goal-source-core-layering/proposal.md)
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
- [`../../specs/api.md`](../../../specs/api.md)
