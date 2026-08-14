# RFC PDF-Backed Document Workbench Contract

## Status

Accepted and amended on 2026-08-14.

The workbench uses stable Source artifact references. PDF coordinates and
character offsets are retired from the domain, persistence, HTTP, and browser
contracts.

## Decision

The collection document route remains the source-verification surface:

```text
/collections/[id]/documents/[document_id]
```

Its three regions are:

- original source reader;
- structured paper understanding and evidence;
- local graph for the selected result, Finding, or Evidence item.

Every traceable item resolves through one locator contract:

```text
document_id + source_kind + source_ref
```

Supported Source artifacts include blocks, tables, table rows, cells, and
figures. Text evidence uses `source_kind = "block"` and the stable `block_id` as
`source_ref`. `page` and `quote` are display context, not identity.

## Why

Parser coordinates and character offsets were neither stable nor portable:

- coordinate origin and units varied by parser;
- parsed text offsets changed when normalization changed;
- the browser could not reliably draw the same region across renderers;
- quote search could select the wrong repeated sentence;
- persisted geometry duplicated parser-private implementation detail.

Stable Source artifact IDs survive API serialization and give every evidence
record one deterministic owner. The workbench can still jump to a page, but it
does not claim false region precision.

## Backend Contract

Evidence anchors expose:

```json
{
  "anchor_id": "anchor_xxx",
  "document_id": "doc_xxx",
  "source_kind": "block",
  "source_ref": "blk_xxx",
  "source_type": "text",
  "page": 6,
  "quote": "The optimized sample reached 940 MPa.",
  "deep_link": "/collections/col_xxx/documents/doc_xxx?anchor_id=anchor_xxx"
}
```

The document content response exposes stable block IDs, reading order,
heading context, text-unit membership, text, and optional page. It does not
expose parser coordinates or character offsets.

Source domain records and persistence tables do not store geometry. Parser
adapters may inspect geometry privately while excluding text embedded inside a
figure or cropping an extracted figure image. That private value must not cross
the parser mapping boundary.

## Frontend Contract

The browser normalizes evidence into a `WorkbenchSourceTarget` containing:

- `documentId`;
- `sourceKind`;
- `sourceRef`;
- optional `page`, `quote`, and user-facing label;
- precision of `block`, `page`, or `unavailable`.

Selection follows this order:

1. resolve the stable Source artifact reference;
2. select or scroll to the matching parsed block/table/figure;
3. jump the PDF reader to the recorded page when available;
4. otherwise keep the document open and show that the exact location is
   unavailable.

The browser must not reconstruct locations from quotes and must not render PDF
region highlights without a stable persisted region contract.

## Source File Behavior

The backend serves the original collection document through:

```text
GET /api/v1/collections/{collection_id}/documents/{document_id}/source
```

The browser uses the original PDF when available and parsed Markdown/text as a
fallback. Internal Source IDs remain navigation identity and are not presented
as scientific content.

## Removed Contract

The following are intentionally unsupported:

- PDF bounding boxes in Source records or browser payloads;
- character ranges and start/end offsets as evidence locators;
- quote-search locator recovery;
- section-only locator fallback;
- locator confidence labels derived from coordinate availability;
- a second compatibility payload for historical anchors.

The database migration converts historical anchors to stable Source artifact
references where possible and falls back to a document reference when the old
record has no stable artifact ID. The migration is irreversible.

## Verification

The maintained checks cover:

- Source domain and persistence round trips without geometry;
- evidence API responses containing only stable source references;
- collection document content without offsets or coordinate payloads;
- frontend normalization and navigation by `sourceKind/sourceRef`;
- page-level PDF navigation without synthetic region highlighting.

The long-lived HTTP details belong in
[`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md). The
frontend route behavior belongs under
[`../../frontend/src/routes/collections/`](../../frontend/src/routes/collections/).

## Related Docs

- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [Research Objective Workspace Contract](../contracts/research-objective-workspace-contract.md)
- [Claim Traceback Navigation Contract](../../frontend/src/routes/collections/claim-traceback-navigation-contract.md)
