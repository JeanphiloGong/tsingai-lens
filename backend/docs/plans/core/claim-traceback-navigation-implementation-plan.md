# Claim Traceback Navigation Implementation Plan

## Summary

This document records the backend-owned implementation slice for
claim-to-source navigation in the current Lens v1 Core hardening wave.

This is not a new architecture layer. It is a vertical slice inside the
Research Intelligence Core path:

`comparison row -> evidence card -> traceback anchor -> document viewer`

Its job is to make Core-produced evidence more reviewable and more trustworthy
by giving the user a deterministic way to move from structured claims back to
document context.

For the broader five-layer roadmap, read
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md).
For the current parent execution wave, read
[`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md).

## Why This Slice Exists Now

The current backend priority is Core quality, not new adapters and not Goal
Consumer work.

That means better parsing and better evidence extraction should not stop at
artifact generation. The system also needs a usable verification path so
researchers can check whether a claim is grounded in real document context.

This traceback slice exists now because it strengthens one of the most
important Core promises:

- evidence is not only structured
- evidence is traceable
- comparison remains reviewable rather than opaque

Without this slice, stronger anchors and stronger extraction quality would
still be hard to inspect in the UI.

## Place In The System

### Five-Layer Position

This plan belongs to Layer 3, the Research Intelligence Core, with a small
handoff into collection-facing route behavior.

It is not:

- Goal Brief / Intake work
- Source & Collection Builder work
- Goal Consumer / Decision-layer work
- a new downstream surface like graph or report

The document viewer here is a traceback surface, not a replacement for the
workspace, evidence, or comparison-first flow.

### Product Position

The primary user-facing surfaces remain:

- workspace
- document profiles
- evidence cards
- comparison rows

Traceback is a supporting verification capability behind evidence and
comparison review. It should improve trust in Core artifacts without making
raw document browsing the new default center of the product.

### Dependency Direction

This slice must preserve one dependency rule:

Goal, graph, protocol, and other derived surfaces may consume traceback-ready
Core artifacts later, but traceback facts themselves must continue to come
from the Core-owned evidence/document path.

## Parent, Child, And Companion Relationships

### Parent Docs

- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
  is the immediate parent execution plan. This traceback slice is one concrete
  child implementation wave under its evidence-quality and traceback-quality
  scope.
- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md)
  is the broader backend roadmap. This traceback slice helps complete the Core
  before Source expansion or Goal Consumer work resumes.
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
  defines why traceback belongs to the Core rather than to Goal or Source.

### Companion Docs

- [`../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md`](../../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md)
  owns the collection-route-family navigation contract and fallback behavior.
- [`../specs/api.md`](../../specs/api.md)
  owns the public backend API contract for traceback and document content.

### Child Scope Of This Plan

This plan is the detailed child implementation page for the current v1
traceback slice. If later work adds OCR/bbox precision, comparison-native
traceback endpoints, or richer PDF viewers, those should be recorded as later
child docs rather than folded back into this v1 slice.

## Scope

This implementation slice covers:

- backend evidence traceback endpoint for one evidence card at a time
- backend collection-scoped document content endpoint for viewer rendering
- v1 evidence anchor normalization needed by traceback
- frontend minimal document viewer routing and fallback handling
- integration and regression checks for ready, partial, and unavailable
  traceback states

This slice does not cover:

- OCR pipeline redesign
- precise bbox-first PDF navigation
- figure, table, or image-region traceback
- direct comparison-native traceback endpoints
- Goal Consumer / Decision-layer features
- search, crawler, or connector adapter work

## Proposed V1 Flow

1. User clicks `查看原文证据` from an evidence card or from a comparison flow.
2. Comparison routes resolve `supporting_evidence_ids` first; they do not
   bypass evidence and jump straight to document internals.
3. Frontend requests
   `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback`.
4. Backend returns `traceback_status` plus the best available anchors.
5. Frontend opens the collection-scoped document viewer route.
6. Frontend requests
   `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`.
7. Viewer highlights by `char_range` when available, otherwise falls back to
   `section`.
8. If only low-precision location exists, the viewer shows an explicit warning
   rather than failing silently.

## Backend Changes

### 1. Anchor Shape Hardening

The existing evidence anchor shape should be normalized toward the public
traceback contract.

Minimum v1 fields:

- `anchor_id`
- `document_id`
- `locator_type`
- `locator_confidence`
- `quote`
- `section_id`
- `char_range`
- `bbox`
- `page`
- `deep_link`

Guardrails:

- optional fields must use `null`, not empty strings
- `anchor_id` should be stable for one artifact build
- `section` fallback is required when precise spans are unavailable
- anchor payloads must remain Core-derived rather than viewer-specific

### 2. Evidence Traceback Endpoint

Add or finalize:

- `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback`

Minimum response:

- `collection_id`
- `evidence_id`
- `traceback_status`
- `anchors`

Status semantics:

- `ready`
  at least one usable anchor exists for viewer navigation
- `partial`
  only downgraded or low-confidence location exists
- `unavailable`
  evidence exists but no usable source location can be served

### 3. Document Content Endpoint

Add or finalize:

- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`

The v1 contract only needs enough structured content to support:

- document title / metadata
- section navigation
- section-level or span-level highlighting
- explicit empty / missing-state handling

This endpoint should not wait for a full PDF-native viewer architecture.

### 4. Core Ownership Rules

Implementation should keep traceback inside the Core artifact path:

- evidence traceback is resolved from Core-owned anchors
- comparison uses evidence linkage rather than inventing a parallel traceback
  model
- viewer-specific state must not redefine evidence facts

## Frontend Changes

Frontend work in this slice should stay minimal and contract-driven:

- keep the collection route family as the owning navigation surface
- add a collection-scoped document viewer route
- support evidence-entry and comparison-entry navigation
- render explicit fallback warnings for `partial` and `unavailable`
- avoid making PDF browsing the new collection homepage

The detailed route behavior remains owned by
[`../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md`](../../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md).

## Execution Order

1. Freeze the v1 evidence anchor payload shape in backend schemas.
2. Add traceback service logic and controller endpoint.
3. Add document content endpoint with section-oriented viewer payload.
4. Wire frontend document viewer routing and evidence/comparison entry points.
5. Add regression coverage for ready, partial, and unavailable cases.

## Verification

Required checks for this slice:

- evidence cards can open source context with deterministic fallback
- comparison flows can reach source context through `supporting_evidence_ids`
- `traceback_status=partial` still returns a useful downgraded navigation path
- `traceback_status=unavailable` is explicit and non-silent
- workspace, evidence, and comparison remain the primary surfaces
- protocol, graph, and Goal surfaces do not gain a separate traceback model

## Risks And Guardrails

- do not block v1 on bbox or OCR precision work
- do not let comparison add a second traceback API before evidence traceback is
  stable
- do not let document-viewer concerns mutate Core artifact semantics
- do not turn traceback into a justification for shifting the product center
  back to raw PDF browsing

## Related Docs

- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../specs/api.md`](../../specs/api.md)
- [`../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md`](../../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md)
