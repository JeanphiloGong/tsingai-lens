# Claim Traceback Navigation Contract

## Purpose

This document records the implementation contract for claim-to-source
navigation in the collection route family.

It aligns frontend behavior and backend payload/API expectations so users can
move from comparison/evidence outputs to original document context with
deterministic fallback.

## Scope

In scope:

- frontend navigation behavior from comparisons/evidence to source documents
- minimum anchor payload required from backend
- fallback policy when precise anchors are unavailable
- phased rollout and verification path

Out of scope:

- OCR internals and PDF parsing internals
- detailed visual design and interaction styling
- backend extraction algorithm internals

## Companion Docs

- [`../../../../backend/docs/plans/claim-traceback-navigation-implementation-plan.md`](../../../../backend/docs/plans/claim-traceback-navigation-implementation-plan.md)
  Backend-owned child implementation plan for the current v1 traceback slice
- [`../../../../backend/docs/specs/api.md`](../../../../backend/docs/specs/api.md)
  Authoritative public API contract for traceback and document content

## User-Level Workflow Contract

1. user views a claim-bearing output in `comparisons` or `evidence`
2. user clicks `查看原文证据`
3. frontend opens the collection-scoped document viewer
4. frontend resolves the best available anchor and highlights context
5. user can return to comparison/evidence flow without losing context

## Shared Anchor Payload

Each claim-bearing evidence output should include one or more anchors with the
following minimum shape:

```json
{
  "anchor_id": "anc_xxx",
  "document_id": "doc_xxx",
  "section_id": "sec_xxx",
  "block_id": "blk_xxx",
  "span_start": 120,
  "span_end": 188,
  "quote": "source evidence snippet",
  "source_type": "text",
  "page": null,
  "deep_link": "/collections/{collection_id}/documents/{document_id}?anchor_id=anc_xxx"
}
```

Minimum required fields:

- `anchor_id`
- `document_id`
- `source_type`
- `deep_link`

Recommended when available:

- `section_id`
- `block_id`
- `span_start`
- `span_end`
- `quote`
- `page`

## Backend Coordination Contract

### Artifact Payload Requirements

- `evidence_cards` should provide `evidence_anchors` for `direct` and
  `partial` traceability cases.
- `comparison_rows` should keep `supporting_evidence_ids` resolvable to
  evidence anchors.
- backend should return `deep_link` semantics directly; frontend should not
  infer deep links from internal assumptions.

### API Surface Requirements

Backend should expose source-viewer APIs compatible with anchor-based
navigation:

- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/anchors/{anchor_id}`

### Missingness Rules

- optional anchor fields must be `null` when unavailable
- `anchor_id` should stay stable for a given artifact build
- if span/page precision is unavailable, section-level anchoring is still
  required

## Frontend Coordination Contract

### Route and Entry Points

- document viewer route:
  `/collections/[id]/documents/[document_id]`
- entry points:
  - `/collections/[id]/comparisons`
  - `/collections/[id]/evidence`

### Fallback Policy (Strict Order)

1. resolve `anchor_id` and highlight quote/span
2. if anchor resolution fails, jump to `section_id`
3. if section is unavailable, open document top and show explicit warning

Frontend must never silently drop traceback actions.

## Rollout Phases

### Phase 1 (v1): Section/Span Traceback

- enable claim to section/span navigation
- enable quote highlight when quote/span exists
- do not block on precise PDF page coordinates

### Phase 2 (v2): Page/Figure/Table Precision

- add page-level deep navigation
- support figure/table anchor targets
- keep phase-1 fallback behavior intact

## Verification Path

Required end-to-end path:

`comparison row -> supporting evidence -> anchor deep link -> document highlight`

Required checks:

- one-click jump from comparisons to source viewer
- one-click jump from evidence cards to source viewer
- deterministic fallback behavior with explicit warning copy
- no silent failure path
