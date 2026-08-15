# Claim Traceback Navigation Contract

## Purpose

This contract defines navigation from comparisons, results, Findings, and
Evidence to the original collection document.

The backend API authority is
[`../../../../backend/docs/specs/api.md`](../../../../backend/docs/specs/api.md).

## Anchor Payload

Every usable anchor has one stable Source reference:

```json
{
  "anchor_id": "anchor_xxx",
  "document_id": "doc_xxx",
  "source_kind": "block",
  "source_ref": "blk_xxx",
  "source_type": "text",
  "page": 4,
  "quote": "source evidence snippet",
  "deep_link": "/collections/col_xxx/documents/doc_xxx?anchor_id=anchor_xxx"
}
```

Required identity fields are `anchor_id`, `document_id`, `source_kind`, and
`source_ref`. `page`, `quote`, and `deep_link` provide display and navigation
context but do not replace the stable Source reference.

Text anchors use `source_kind = "block"`. Table, row, cell, and figure anchors
use their corresponding Source artifact kind and ID.

## Navigation

The document viewer route is:

```text
/collections/[id]/documents/[document_id]
```

The strict resolution order is:

1. load the requested anchor or selected evidence item;
2. resolve `source_kind + source_ref` in the document Source artifacts;
3. select or scroll to the matching parsed source artifact;
4. jump the PDF reader to `page` when available;
5. otherwise keep the document open and display an explicit unavailable state.

The browser does not infer a location from quote text, character offsets,
section names, or PDF coordinates. It never silently drops a traceback action.

## Backend Requirements

- Evidence cards provide stable anchors for direct and partial traceability.
- Comparison and Finding records keep their Evidence IDs resolvable to those
  anchors.
- Deep links are emitted by the backend when needed; the browser does not
  reconstruct backend paths from storage assumptions.
- A missing Source artifact is returned as an explicit partial or unavailable
  traceback state.

Relevant endpoints include:

```text
GET /api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback
GET /api/v1/collections/{collection_id}/documents/{document_id}/content
GET /api/v1/collections/{collection_id}/documents/{document_id}/source
```

## Verification

The required product path is:

```text
comparison or Finding
  -> Evidence
  -> stable Source reference
  -> document artifact selection
  -> optional PDF page jump
```

Tests must cover block, table, and figure references, missing artifacts, and
page-only display context. Coordinate and character-range highlighting are not
part of this contract.
