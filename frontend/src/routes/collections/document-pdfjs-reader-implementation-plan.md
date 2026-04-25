# Document PDF.js Reader Implementation Plan

## Summary

This plan records the frontend-local next step for the document detail route:

`/collections/[id]/documents/[document_id]`

The left reader should become a controlled PDF.js reader with a custom
highlight layer. It should no longer use hand-written paragraph or parsed-text
boxes as the source-of-truth reader. Parsed quotes and excerpts remain useful
inside evidence cards, result detail, and graph node detail, but not as a
second document reader.

This page is the frontend implementation child of the shared
[`../../../../docs/decisions/rfc-pdf-backed-document-workbench.md`](../../../../docs/decisions/rfc-pdf-backed-document-workbench.md).
The RFC owns the cross-module source-file and locator contract. This page owns
the Svelte/PDF.js reader architecture, page-local anchor model, interaction
flow, and frontend verification for the collection route family.

## Reader Boundary

The document workbench keeps the three-column layout:

- left: original PDF reader
- middle: structured extraction tabs
- right: local knowledge graph

The left column should contain one PDF reader surface only. It should not
render a separate parsed paragraph reader below, beside, or inside the PDF
area. If a selected item has no exact PDF rectangle yet, the reader should jump
to the best page and show a small pending badge rather than switching to a
hand-written text source.

The PDF reader should use `pdfjs-dist` or an existing PDF rendering capability.
It should not use TipTap, Slate, ProseMirror, or another rich-text editor as a
source-reader substitute.

## Source Anchors

The frontend workbench should normalize selected summary, method, result, and
evidence items into a page-local anchor shape:

```ts
type SourceAnchor = {
	pageIndex: number;
	rects: Array<{
		left: number;
		top: number;
		width: number;
		height: number;
	}>;
	quote?: string;
	section?: string;
	precision?: 'pdf-region' | 'pdf-page' | 'pending';
};
```

Rules:

- `pageIndex` is zero-based.
- `rects` use percentages relative to the PDF page container.
- highlight positioning must stay correct when PDF zoom changes.
- `quote` and `section` are context for cards, details, and pending states,
  not a second source-reader model.

When backend content blocks expose `page`, the frontend converts one-based
backend page numbers to zero-based `pageIndex`. When backend `bbox` values can
be converted reliably to page percentages, the adapter should emit one or more
`rects`. If conversion is not reliable, the anchor should keep the page target
and use `precision: 'pending'`.

## PDF Page Structure

`PaperReader.svelte` should render each PDF page with layered structure:

```text
page container
├─ canvas layer
├─ text layer, reserved if full text selection is not in the first slice
└─ custom highlight layer
```

Layout requirements:

- `PaperReader`: `height: 100%; display: flex; flex-direction: column;
overflow: hidden`
- toolbar: fixed `52px` height
- scroll container: `flex: 1; min-height: 0; overflow: auto`
- page container: `position: relative`
- canvas, text layer, and highlight layer are stacked inside the page container
- highlight layer: `position: absolute; inset: 0; pointer-events: none`

The first slice can reserve the text layer without implementing full text
selection. The highlight layer is required.

## Jump And Highlight Flow

`PaperReader` should expose behavior equivalent to `jumpToSource(anchor)`:

1. receive `activeSourceAnchor` or an equivalent selected anchor prop
2. scroll the PDF container to `anchor.pageIndex`
3. draw each rectangle from `anchor.rects` on that page's highlight layer
4. use a blue translucent highlight with a subtle border
5. apply a brief focus or flash animation to the current highlight
6. if `rects` is empty but `pageIndex` exists, jump to the page and show
   `Precise region pending`

The old paragraph DOM target pattern, including `pdf-source-{sourceSpanId}`,
should be removed from the source-reader path.

## Workbench Selection Flow

Middle-column selection should drive one selected workbench object and one
selected source anchor.

Clicking a summary card, method row, result row, or evidence card should:

1. set the selected item
2. mark the card or row selected
3. pass the selected item's `SourceAnchor` to `PaperReader`
4. update the local graph focus node

Clicking `Jump to source` should use the same anchor flow. It should not
trigger a paragraph-text fallback. The graph can still expose source jumps, but
the target should be a `SourceAnchor`, not a block id or parsed paragraph DOM
id.

Result and evidence rows should resolve source anchors in this order:

1. `direct_anchor_ids` from the result chain
2. `contextual_anchor_ids` from the result chain
3. the first traceback anchor returned for the evidence ID
4. block/page fallback only when no traceback anchor is available

The document route may fetch
`/api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback` for the
evidence IDs already referenced by the document comparison semantics response.
When a traceback anchor contains a usable `page`, the reader must at least jump
to that PDF page. If the anchor also contains percentage-like `bbox` values,
the highlight layer may draw a region; otherwise the reader shows the pending
region badge and keeps the PDF page as the source of truth.

## Fixture Anchors

The first PDF.js slice can use fixture anchors when backend coordinate data is
missing or cannot yet be converted.

Example:

```ts
{
	pageIndex: 0,
	rects: [
		{ left: 18, top: 62, width: 64, height: 4.5 },
		{ left: 18, top: 67, width: 58, height: 4.5 }
	],
	quote: '...',
	section: 'Abstract',
	precision: 'pdf-region'
}
```

Fixtures should cover summary, method, result, and evidence interactions so
the selection, scroll, and highlight path can be reviewed before every backend
block has production PDF rectangles.

When only page-level data exists:

```ts
{
	pageIndex: 4,
	rects: [],
	quote: 'Reported source excerpt',
	section: 'Results',
	precision: 'pending'
}
```

The UI should jump to the page and show the pending badge. It should not show a
second reader.

## File Change Plan

Primary files:

- `frontend/src/routes/collections/[id]/documents/[document_id]/_components/PaperReader.svelte`
- `frontend/src/routes/_shared/documents.ts`

Likely companion files:

- `frontend/src/routes/collections/[id]/documents/[document_id]/+page.svelte`
- `frontend/src/routes/collections/[id]/documents/[document_id]/_components/StructuredExtractionPanel.svelte`
- `frontend/src/routes/collections/[id]/documents/[document_id]/_components/EvidenceCard.svelte`
- `frontend/src/routes/collections/[id]/documents/[document_id]/_components/ResultTable.svelte`
- `frontend/src/routes/collections/[id]/documents/[document_id]/_components/LocalGraphPanel.svelte`
- `frontend/src/routes/_shared/i18n.ts`
- `frontend/src/routes/collections/[id]/documents/[document_id]/document-detail-page.svelte.spec.ts`

If `pdfjs-dist` is not already available, add it as a frontend dependency and
commit the package and lockfile changes with the implementation.

## Implementation Order

1. Add `SourceAnchor` and anchor normalization to the shared document workbench
   model.
2. Replace native PDF object/embed rendering in `PaperReader` with PDF.js page
   canvas rendering.
3. Add page containers, reserved text layer, and custom highlight layer.
4. Remove the parsed paragraph reader from `PaperReader`.
5. Wire selected summary, method, result, evidence, and graph actions to
   selected anchors.
6. Add fixture anchors for missing backend rectangle data.
7. Add pending-page fallback for anchors without precise rectangles.
8. Update tests and i18n copy.

## Verification

Required checks:

```text
cd frontend
npm run check
npm run test:unit -- --run src/routes/collections/[id]/documents/[document_id]/document-detail-page.svelte.spec.ts
```

The unit test can mock `pdfjs-dist` if the browser test environment cannot
render canvas reliably. It should still verify:

- the document route renders one PDF reader surface
- the old parsed paragraph reader is absent
- clicking `Jump to source` creates an active highlight layer rectangle
- selecting a result row keeps card selection and graph focus working
- fixture anchors use percentage-based styles

Manual review should cover:

- PDF pages render from `/api/v1/collections/{collection_id}/documents/{document_id}/source`
- zooming preserves highlight alignment because the rectangles are percentages
- page fallback shows `Precise region pending`
- quotes appear in evidence or detail surfaces only

## Acceptance

This plan is complete when:

- the left column contains one controlled PDF.js reader
- the reader has page canvas, reserved text layer, and custom highlight layer
- selecting middle-column cards jumps to a PDF page and highlights a region
- highlights are driven by zero-based `pageIndex` and percentage rectangles
- zoom changes do not detach highlights from their page regions
- no hand-written paragraph reader remains under the PDF
- missing precise coordinates degrade to page jump plus pending badge
- raw block ids and backend artifact codes stay out of the default UI

## Backend Follow-Up

The frontend can ship with fixture anchors, but production precision still
depends on backend PDF rectangle quality. Later backend work should provide a
stable mapping from evidence/result/block anchors to PDF page rectangles and a
clear coordinate origin or page-size contract so the frontend can convert
stored coordinates to percentages without guessing.
