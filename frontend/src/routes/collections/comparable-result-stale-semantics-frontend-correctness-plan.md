# Comparable-Result Stale Semantics Frontend Correctness Plan

## Purpose

This document records the frontend-local plan for closing the stale-semantics
gap after the comparable-result rollout exposed collection-scoped staleness in
the backend workspace and task payloads.

The immediate goal is not a UI redesign. It is to make the frontend preserve
and use the existing backend stale signals honestly so collection workspace and
graph surfaces stop collapsing "generated but stale" into a generic
"not ready" state.

## Scope

In scope:

- preserving `collection_comparable_results_stale`,
  `comparison_rows_stale`, and `graph_stale` in the shared workspace helper
- making frontend fallback state derivation treat stale comparison and graph
  artifacts as `limited` rather than generic `not_started` or
  `not_applicable`
- protecting the existing rule that graph availability stays keyed to
  `graph_ready` and graph capabilities rather than `comparison_rows_ready`
- unit coverage for stale workspace normalization and stale surface-state
  derivation

Out of scope:

- redesigning the collection workspace information architecture
- changing the public browser contract or backend payload shape
- making graph a primary Lens v1 acceptance surface
- exposing backend-internal semantic ids in the main UI
- introducing a second frontend store, adapter, or compatibility facade
- broad secondary observability or new workspace status panels in the same wave

## Related Docs

- [`comparable-result-semantic-artifact-frontend-alignment-plan.md`](comparable-result-semantic-artifact-frontend-alignment-plan.md)
  Parent frontend-local plan for the comparable-result semantic artifact
  rollout
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family interface authority
- [`../../../docs/frontend-plan.md`](../../../docs/frontend-plan.md)
  Frontend same-origin contract guide
- [`../../../../backend/docs/plans/core/core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](../../../../backend/docs/plans/core/core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
  Backend-owned Phase 2 document-first semantic inspection plan

## Why A Separate Child Plan Exists

The parent frontend alignment plan already corrected the major contract drift:

- graph gating no longer falls back to `comparison_rows_ready`
- the shared workspace helper preserves semantic-artifact readiness fields
- collection graph visibility follows `graph_ready` and graph capabilities

The remaining gap is smaller and narrower.

The backend now exposes three explicit stale booleans:

- `collection_comparable_results_stale`
- `comparison_rows_stale`
- `graph_stale`

Those flags matter because the backend also changed the meaning of readiness:

- stale scope artifacts are no longer current
- stale artifacts keep `generated=true`
- stale artifacts force the corresponding `ready=false`

The frontend is still only partially aligned with that model. It is mostly
safe because `ready` is already honest, but it is still losing information that
now matters for correctness and operator understanding.

## Current Frontend Gap

The current gap lives in two places.

### Shared workspace normalization drops the new stale fields

File:

- `frontend/src/routes/_shared/workspace.ts`

Current behavior:

- `WorkspaceArtifactStatus` does not preserve the three backend stale booleans
- `normalizeArtifacts()` drops them from the workspace payload

Consequence:

- frontend consumers cannot distinguish `generated but stale` from generic
  `not ready`
- any follow-on UI logic must guess instead of reading the real contract

### Fallback surface-state logic treats stale as if nothing meaningful exists

File:

- `frontend/src/routes/_shared/workspace.ts`

Current behavior:

- `deriveLegacyWorkflow()` still decides comparison fallback from
  `comparison_rows_ready`
- `getWorkspaceSurfaceState(workspace, 'graph')` only differentiates `ready`,
  `processing`, `failed`, `not_applicable`, and `ready_to_process`

Consequence:

- a stale comparison surface can degrade into a generic "not started" style
  state even though semantic artifacts already exist
- a stale graph surface can degrade into `not_applicable` even though graph
  inputs exist but are no longer current

## Frontend Rules For This Wave

- keep the collection route family unchanged
- keep the same-origin browser contract unchanged
- keep `comparisons` row-facing in the current frontend
- keep graph gating independent from row-cache readiness
- preserve backend stale booleans directly instead of synthesizing substitutes
- treat stale comparison and graph surfaces as `limited`
- keep stale messaging secondary; do not turn the workspace into an artifact
  dashboard

## Target Behavior

After this wave:

- `WorkspaceArtifactStatus` preserves the three stale fields
- stale comparison artifacts make the comparison workflow fallback `limited`
- stale graph artifacts make the graph surface fallback `limited`
- graph visibility and graph readiness still do not depend on
  `comparison_rows_ready`
- the frontend can distinguish:
  - not generated
  - generated but stale
  - current and ready

## Delivery Waves

### Wave 1: Correctness

This is the required implementation wave.

Goals:

- preserve backend stale booleans in the shared workspace helper
- make stale comparison and graph states land in the right fallback category
- add tests that lock those semantics in place

### Wave 2: Secondary UX Semantics

This is optional follow-on work.

Goals:

- preserve backend workflow `detail` strings instead of only stage `status`
- show stale-specific user-facing copy where it helps operators understand why
  a surface is limited

This second wave should remain secondary. It should not turn the main workspace
rail into a raw artifact debugger.

## File-Level Plan

### 1. Shared workspace helper

File:

- `frontend/src/routes/_shared/workspace.ts`

Changes:

- extend `WorkspaceArtifactStatus` with:
  - `collection_comparable_results_stale`
  - `comparison_rows_stale`
  - `graph_stale`
- update `normalizeArtifacts()` to preserve those fields
- update fallback logic so:
  - stale comparisons return `limited`
  - stale graph returns `limited`

Do not:

- add a second workspace adapter
- synthesize a new comparison readiness flag
- reintroduce row-cache-based graph gating

### 2. Shared workspace tests

File:

- `frontend/src/routes/_shared/workspace.spec.ts`

Changes:

- add unit coverage for stale artifact normalization
- add unit coverage for stale comparison workflow fallback
- add unit coverage for stale graph surface fallback
- keep the existing graph-ready-without-row-cache behavior covered

### 3. Collection layout guardrail

File:

- `frontend/src/routes/collections/[id]/+layout.svelte`

Changes:

- no behavior change is required if the current graph-tab visibility rule
  remains intact
- if cleanup touches this file in the same wave, preserve the rule that graph
  visibility is driven by graph capability and `graph_ready`, not by
  `comparison_rows_ready`

### 4. Optional follow-on copy and detail work

Files:

- `frontend/src/routes/_shared/workspace.ts`
- `frontend/src/routes/_shared/i18n.ts`
- `frontend/src/routes/collections/[id]/+page.svelte`

Changes:

- preserve backend workflow detail text
- add stale-specific secondary copy only if the page remains workflow-first

This stays out of the first correctness patch unless the implementation proves
too entangled to separate cleanly.

## Recommended Order

1. update `frontend/src/routes/_shared/workspace.ts`
2. update `frontend/src/routes/_shared/workspace.spec.ts`
3. verify stale comparison and graph fallback semantics
4. decide whether Wave 2 is still worth doing after the correctness patch lands

## Verification

Minimum checks for Wave 1:

- `npm run test:unit -- --run --workspace-spec`
  if the repository already supports a scoped unit target
- otherwise run the smallest equivalent unit command that covers
  `src/routes/_shared/workspace.spec.ts`
- `npm run check`

Behavioral assertions:

- stale fields survive workspace normalization
- stale comparisons normalize to a `limited` fallback state
- stale graph normalizes to a `limited` fallback state
- graph ready behavior still stays independent from `comparison_rows_ready`

## Risks

Main risks in this wave:

- keeping stale booleans out of the shared workspace helper will force future
  UI work to keep guessing about collection state
- treating stale graph as `not_applicable` would hide a real correctness
  problem behind a misleading state label
- mixing Wave 1 correctness with too much Wave 2 UI work would broaden a small
  contract-fix task into an avoidable route redesign

## Relationship To The Parent Plan

This plan does not replace
[`comparable-result-semantic-artifact-frontend-alignment-plan.md`](comparable-result-semantic-artifact-frontend-alignment-plan.md).

That parent plan still owns the broader frontend-local comparable-result
alignment problem.

This child plan only records the next narrow correctness wave:

- preserve stale artifact semantics
- use stale signals in fallback state derivation
- keep graph semantics independent from row-cache assumptions
