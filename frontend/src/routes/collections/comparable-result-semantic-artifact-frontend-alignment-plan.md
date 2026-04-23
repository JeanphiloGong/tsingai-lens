# Comparable-Result Semantic Artifact Frontend Alignment Plan

## Purpose

This document records the frontend-local implementation plan for aligning the
collection workspace and graph surfaces with the comparable-result semantic
artifact rollout.

The goal is to make the frontend consume the new workspace artifact semantics
honestly without introducing a new route family, a second browser contract, or
a frontend-local compatibility facade that rebuilds graph readiness from row
cache assumptions.

## Scope

In scope:

- direct frontend adoption of the workspace artifact fields for
  `comparable_results` and `collection_comparable_results`
- shared workspace-client normalization updates for generated and ready flags
- graph-surface contract alignment so frontend graph gating remains driven by
  `graph_ready` and graph capabilities rather than `comparison_rows_ready`
- frontend copy updates where current wording still implies generic or
  row-cache-backed graph readiness
- frontend unit coverage for the workspace helper state rules introduced by
  this contract change
- optional secondary workspace observability for semantic artifacts when it can
  be added without demoting the workflow-first page structure

Out of scope:

- changing the public collection route family
- redesigning the primary workspace information architecture in the same wave
- making graph a primary Lens v1 acceptance surface
- exposing backend-internal semantic ids such as `comparable_result_id` in the
  main UI
- adding a second frontend store or wrapper layer just for workspace artifact
  translation
- changing comparisons, evidence, documents, protocol, or reports beyond
  existing navigation and readiness semantics

## Companion Docs

- [`../../../../backend/docs/plans/core/core-comparable-result-phase1-read-path-cutover-plan.md`](../../../../backend/docs/plans/core/core-comparable-result-phase1-read-path-cutover-plan.md)
  Backend-owned Phase 1 read-path plan for semantic and scope artifacts
- [`../../../../backend/docs/plans/core/core-comparable-result-phase1-service-boundary-plan.md`](../../../../backend/docs/plans/core/core-comparable-result-phase1-service-boundary-plan.md)
  Backend-owned Phase 1 service-boundary plan for `ComparisonService`
- [`comparable-result-stale-semantics-frontend-correctness-plan.md`](comparable-result-stale-semantics-frontend-correctness-plan.md)
  Frontend-local child plan for stale artifact preservation and fallback
  correctness after backend staleness semantics landed
- [`../../../docs/frontend-plan.md`](../../../docs/frontend-plan.md)
  Frontend same-origin contract guide
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family interface authority for Lens v1
- [`core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md`](core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md)
  Existing collection graph contract cutover plan

## Why This Needs A Separate Frontend Plan

The backend comparable-result rollout has already corrected the runtime graph
path:

- graph readiness now comes from semantic comparison artifacts rather than
  `comparison_rows.parquet`
- graph and report can rebuild row projection on demand from semantic artifacts
- workspace and task payloads now expose semantic-artifact status explicitly

The current frontend is only partially aligned with that reality.

It is functionally safe in the graph route today because the collection layout
and graph page already use `graph_ready` and graph capabilities. But the shared
workspace helper still narrows the artifact model to a small legacy subset and
drops the new semantic-artifact fields entirely.

That means frontend behavior is no longer fully wrong, but it is still partly
blind:

- graph route gating is correct
- workspace artifact parsing is incomplete
- graph readiness copy is too vague
- the UI cannot distinguish semantic comparison readiness from row-cache
  materialization when that distinction matters for debugging or secondary
  observability

This deserves a dedicated frontend-local child plan rather than an incidental
edit to the broader route-family interface spec.

## Current Frontend Mismatch

The current mismatch lives in four concrete places.

### 1. Workspace artifact model is too narrow

File:

- `frontend/src/routes/_shared/workspace.ts`

Current assumptions:

- `WorkspaceArtifactStatus` only keeps a small `ready`-only subset
- `comparable_results_generated`
- `comparable_results_ready`
- `collection_comparable_results_generated`
- `collection_comparable_results_ready`
  are dropped when the workspace payload is normalized
- `graph_generated` is also dropped even though it is now a meaningful
  collection-facing signal

This makes the frontend lose the semantic-artifact rollout state even when the
backend already provides it.

### 2. Graph gating is correct, but only because the route bypasses the old row assumption

Files:

- `frontend/src/routes/_shared/workspace.ts`
- `frontend/src/routes/collections/[id]/+layout.svelte`

Current behavior:

- graph visibility is derived from
  `can_view_graph || can_download_graphml || artifacts.graph_ready`
- graph surface state also uses `graph_ready` and graph capabilities directly

This is the right rule and must be preserved.

The risk is not the current code path itself. The risk is future regression if
frontend cleanup reintroduces `comparison_rows_ready` as a graph fallback just
because row cache still exists in the workspace payload.

### 3. Legacy workflow fallback still centers the comparison row projection

File:

- `frontend/src/routes/_shared/workspace.ts`

Current assumptions:

- `deriveLegacyWorkflow()` still treats `comparison_rows_ready` as the
  comparison-stage readiness fallback

That is acceptable for the current collection-facing comparisons page because
the frontend still consumes `/comparisons` as a row-projection surface.

It is not acceptable for graph logic.

The frontend therefore needs to keep these two meanings separate:

- comparisons primary UI readiness may stay row-facing
- graph readiness must stay semantic-artifact-facing

### 4. Copy and secondary status surfaces do not explain the semantic / projection split

Files:

- `frontend/src/routes/_shared/i18n.ts`
- `frontend/src/routes/collections/[id]/+page.svelte`

Current assumptions:

- graph-not-ready copy still refers to generic “graph artifacts”
- workspace secondary information has no dedicated way to describe
  `comparison semantics` versus `row cache`

That makes rollout behavior harder to explain to operators and reviewers even
when the frontend works.

## Frontend Adoption Rules

- keep the existing collection route family and same-origin API contract
- keep `workspace` workflow-first and `comparisons` primary for analysis
- treat graph availability as owned by
  `capabilities.can_view_graph`,
  `capabilities.can_download_graphml`, and `artifacts.graph_ready`
- do not derive graph availability from `comparison_rows_ready`
- preserve raw semantic-artifact booleans in the shared workspace client when
  the backend provides them
- keep semantic-artifact observability secondary; do not turn the workspace
  into an artifact dashboard
- do not expose backend-internal ids as main UI fields
- do not add a wrapper that reconstructs old semantics from the new payload

## Target Frontend Contract

The shared workspace helper should preserve the semantic artifact fields that
matter to the comparable-result rollout.

Minimum target artifact model:

```ts
type WorkspaceArtifactStatus = {
  output_path: string;
  documents_generated: boolean;
  documents_ready: boolean;
  document_profiles_generated: boolean;
  document_profiles_ready: boolean;
  evidence_cards_generated: boolean;
  evidence_cards_ready: boolean;
  comparable_results_generated: boolean;
  comparable_results_ready: boolean;
  collection_comparable_results_generated: boolean;
  collection_comparable_results_ready: boolean;
  comparison_rows_generated: boolean;
  comparison_rows_ready: boolean;
  graph_generated: boolean;
  graph_ready: boolean;
  procedure_blocks_generated: boolean;
  procedure_blocks_ready: boolean;
  protocol_steps_generated: boolean;
  protocol_steps_ready: boolean;
  updated_at: string;
};
```

Frontend meaning after the cutover:

- `comparable_results_*` expresses semantic comparison artifact status
- `collection_comparable_results_*` expresses collection-scoped assessment
  status
- `comparison_rows_*` expresses projection/cache status
- `graph_*` expresses graph projection readiness from the semantic path

The frontend should keep `comparison_rows_*` because the comparisons page is
still row-facing. It should stop letting those fields leak into graph gating.

## Implementation Waves

### Phase 1: Contract Alignment

This is the required wave.

Goals:

- keep the graph surface aligned with the real backend runtime
- preserve semantic-artifact fields in the shared workspace client
- correct frontend wording that would otherwise imply the wrong readiness seam

### Phase 2: Secondary Observability

This is optional and should happen only if it stays secondary.

Goals:

- surface `comparison semantics`, `row cache`, and `graph projection` as
  separate concepts in an advanced or secondary workspace area
- avoid promoting raw artifact booleans into the primary workspace hierarchy

## File-Level Change Plan

### 1. Shared workspace helper

File:

- `frontend/src/routes/_shared/workspace.ts`

Changes:

- extend `WorkspaceArtifactStatus` to preserve generated and ready flags for
  `document_profiles`, `evidence_cards`, `comparable_results`,
  `collection_comparable_results`, `comparison_rows`, `graph`,
  `procedure_blocks`, and `protocol_steps`
- update `fetchWorkspaceOverview()` normalization to read those fields directly
  from the backend payload
- keep `getWorkspaceSurfaceState(workspace, 'graph')` keyed to graph
  capabilities and `graph_ready`
- keep comparison workflow fallback row-facing, but make that distinction
  explicit in code comments or helper naming where needed

Do not:

- add a second workspace adapter
- infer graph readiness from `comparison_rows_ready`
- collapse semantic artifacts and row cache into one synthesized comparison
  flag

### 2. Shared copy

File:

- `frontend/src/routes/_shared/i18n.ts`

Changes:

- rewrite `graphNotReady` copy so it no longer implies a generic legacy graph
  cache
- if Phase 2 lands, add narrow labels for:
  - comparison semantics
  - comparison row cache
  - graph projection

Do not:

- introduce backend-internal wording that normal users cannot interpret
- frame graph as the main collection outcome

### 3. Collection layout and graph route guardrails

Files:

- `frontend/src/routes/collections/[id]/+layout.svelte`
- `frontend/src/routes/collections/[id]/graph/+page.svelte`

Changes:

- preserve the current graph visibility rule
- preserve the current graph surface-state rule
- if any cleanup touches these files, keep them explicitly independent from
  `comparison_rows_ready`

Do not:

- add a row-cache fallback to graph tab visibility
- add a row-cache fallback to graph page readiness

### 4. Workspace secondary observability

File:

- `frontend/src/routes/collections/[id]/+page.svelte`

Changes:

- optionally add a secondary or advanced status block that distinguishes:
  - comparison semantics
  - comparison row cache
  - graph projection

Rules:

- keep the main workflow rail unchanged
- do not move artifact booleans into the main call-to-action hierarchy
- prefer a compact summary instead of a full raw artifact table

### 5. Shared workspace tests

File:

- `frontend/src/routes/_shared/workspace.spec.ts`

Changes:

- add unit coverage for semantic-artifact normalization
- add unit coverage proving graph surface readiness when:
  - `graph_ready=true`
  - `comparison_rows_ready=false`
- add unit coverage ensuring collection workspace state does not regress when
  the artifact payload grows

## Recommended Implementation Order

1. update `frontend/src/routes/_shared/workspace.ts` types and normalization
2. add `frontend/src/routes/_shared/workspace.spec.ts`
3. update `frontend/src/routes/_shared/i18n.ts` graph readiness copy
4. perform any minimal layout or graph-page guardrail cleanup only if needed
5. add optional secondary workspace observability if the UI still stays
   workflow-first

## Verification Plan

Minimum frontend checks for this wave:

- `npm run test:unit -- --run`
- `npm run check`

Behavioral checks:

- graph tab remains visible when `graph_ready=true` and
  `comparison_rows_ready=false`
- graph page surface state is still `ready` under the same condition
- workspace helper preserves `comparable_results_*` and
  `collection_comparable_results_*` when provided by the backend
- frontend copy for graph-not-ready no longer implies the wrong readiness seam
- optional workspace observability remains secondary and does not displace the
  primary workflow rail

## Risks

Main frontend risks:

- keeping the shared artifact model too narrow will hide the semantic rollout
  state and make future debugging harder
- using `comparison_rows_ready` as a graph fallback would reintroduce the wrong
  dependency even though the backend runtime has already moved on
- overexposing semantic and projection internals in the workspace can regress
  the page into an artifact dashboard and weaken the workflow-first design

## Relationship To The Existing Interface Spec

This child plan does not replace
[`lens-v1-interface-spec.md`](lens-v1-interface-spec.md).

That parent spec still owns the collection route-family direction:

- workspace remains primary
- comparisons remain the main analysis surface
- graph remains secondary

This child plan only records how the frontend should absorb the
comparable-result rollout without drifting back toward stale row-cache-based
semantics.
