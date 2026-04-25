# RFC PDF-Backed Document Workbench Contract

## Summary

This RFC records the next implementation wave for the collection-scoped
document detail page:

`/collections/[id]/documents/[document_id]`

The target is a paper understanding workbench with:

- left: original source reader, preferably the uploaded PDF when available
- middle: structured extraction tabs for summary, methods, results, evidence,
  and QA
- right: local knowledge graph for the currently selected claim, result, or
  source paragraph

The important contract change is that the frontend must stop treating backend
`blocks` as visible paper sections. A block remains a backend source locator
unit. The user-facing page should present the original paper, readable
structured understanding, and local traceback behavior.

This RFC is a shared frontend/backend execution plan. After implementation,
the long-lived HTTP details still belong in
[`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md), and the
frontend route behavior still belongs under
[`../../frontend/src/routes/collections/`](../../frontend/src/routes/collections/).

## Related Docs

- [RFC Comparison-Result-Document Product Flow](rfc-comparison-result-document-product-flow.md)
- [RFC Document-Result Evidence-Chain Contract Freeze](rfc-document-result-evidence-chain-contract-freeze.md)
- [`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md)
- [`../../backend/docs/plans/core/claim-traceback-navigation-implementation-plan.md`](../../backend/docs/plans/core/claim-traceback-navigation-implementation-plan.md)
- [`../../frontend/src/routes/collections/document-evidence-review-split-view-plan.md`](../../frontend/src/routes/collections/document-evidence-review-split-view-plan.md)
- [`../../frontend/src/routes/collections/claim-traceback-navigation-contract.md`](../../frontend/src/routes/collections/claim-traceback-navigation-contract.md)

## Current State

The frontend document detail page has already moved toward a three-column
paper workbench, but the left reader is still a facsimile built from parsed
document content. It does not yet stream and render the original uploaded PDF.

The current backend state is close but incomplete:

- `blocks.parquet` already carries `page`, `bbox`, and `char_range` for PDF
  parser output.
- text-source block generation carries `char_range` where plain text offsets
  can be resolved.
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`
  currently drops `page`, `bbox`, and `char_range` from each content block.
- original uploaded source files are stored under the collection input area and
  tracked by `files.json` plus `import_manifest.json`.
- there is no document-scoped endpoint that streams the original source file
  for a browser PDF reader.

The repeated-section problem in the left reader comes from exposing block-level
parser units as visible section units. Many paragraph blocks share the same
`heading_path`, so rendering one visible section per block repeats the same
chapter or section title.

## Decision

The next wave should make one direct backend contract improvement and one
direct frontend workbench improvement.

### Source Is User-Facing; Blocks Are Internal

The document page should show either:

- the original PDF/source file when it can be safely served, or
- coherent parsed paper text grouped by real section fallback when the source
  file is unavailable or not displayable in the browser.

It should not present `blk_xxx`, `ev_method_xxx`, or one visible section per
parser block as the main reading model.

### Locators Travel Through The Document Content Contract

Document content blocks should expose locator fields that already exist in
source artifacts:

```json
{
  "block_id": "blk_doc_12",
  "block_type": "paragraph",
  "heading_path": "Results > Mechanical properties",
  "order": 12,
  "text": "The optimized sample reached 940 MPa...",
  "start_offset": 1880,
  "end_offset": 1962,
  "page": 6,
  "bbox": {
    "x0": 72.4,
    "y0": 182.1,
    "x1": 512.8,
    "y1": 228.6,
    "coord_origin": "top_left"
  },
  "char_range": {
    "start": 1880,
    "end": 1962
  }
}
```

Rules:

- `page`, `bbox`, and `char_range` are nullable.
- `page` is the display page number from the source artifact; invalid,
  missing, or non-positive values become `null`.
- `char_range` uses `{ "start": number, "end": number }` and must satisfy
  `0 <= start <= end`.
- `bbox` should normalize public keys to `x0`, `y0`, `x1`, `y1`, and may
  preserve `coord_origin` when the parser provides it.
- the normalizer should accept existing artifact bbox keys `l`, `t`, `r`, and
  `b`, mapping them to `x0`, `y0`, `x1`, and `y1`.
- invalid JSON strings, `NaN`, empty strings, and malformed objects become
  `null`.
- `block_id` remains useful for diagnostics and fallback anchors, but the
  default UI copy must not expose it.

### The Backend Serves The Original Source File

Add a document-scoped source endpoint:

```text
GET /api/v1/collections/{collection_id}/documents/{document_id}/source
```

Behavior:

- stream the stored original source file for the requested document
- return `Content-Type` from stored metadata when available, otherwise infer it
  from the filename
- use inline content disposition by default so a browser PDF viewer can render
  it
- return a clear missing-source response when the collection or document
  exists but no source file can be resolved

Security rules:

- never accept a filesystem path from the request
- resolve files only from repository-owned collection metadata
- resolve candidate paths and reject anything outside the collection directory,
  preferably outside the collection input directory
- do not expose `backend/data/**` directory structure in user-facing errors

### The Frontend Uses A Locator, Not A Block UI

The frontend should normalize claim, result, evidence, paragraph, and block
payloads into one page-local source target concept:

```ts
type SourceTargetPrecision =
  | 'pdf-region'
  | 'text-range'
  | 'pdf-page'
  | 'section'
  | 'quote-search'
  | 'unavailable';

type WorkbenchSourceTarget = {
  documentId: string;
  label: string;
  page: number | null;
  bbox: PdfBoundingBox | null;
  charRange: TextCharRange | null;
  sectionId: string | null;
  headingPath: string | null;
  quote: string | null;
  precision: SourceTargetPrecision;
  userMessage: string | null;
};
```

This can live inside the existing document workbench model code. It should not
be a new route family or a second browser API contract.

## Fallback Behavior

The workbench selection flow should be deterministic.

When the user selects a claim, result row, evidence card, graph node, or source
paragraph, the frontend should:

1. find the best evidence anchor or document content locator for the selected
   object
2. if `page` and `bbox` exist and the active reader can draw PDF overlays,
   jump to that page and draw a region highlight
3. otherwise, if `char_range` exists, highlight that range in parsed source
   text
4. otherwise, if `page` exists, jump the PDF reader to that page and show that
   the precise region is unavailable
5. otherwise, if `section_id` or `heading_path` exists, scroll to the first
   matching section and highlight the section range
6. otherwise, if `quote` exists, search the parsed source text and highlight
   the first match
7. otherwise, keep the document open and show a source-location-unavailable
   message

The first implementation can use a native browser PDF view with `#page=N` for
page navigation. Native PDF viewers cannot reliably draw custom highlights
inside the PDF surface. Exact PDF-region highlighting requires a controlled
viewer such as PDF.js or an equivalent existing project dependency.

Until controlled PDF rendering exists, the acceptable fallback is:

- show the original PDF when the source endpoint works
- synchronize selection to page-level PDF navigation when possible
- keep parsed text as the highlightable fallback for `char_range`, section, or
  quote-based source verification

## User-Facing Copy Rules

Backend and artifact codes should not appear in the default workbench UI.

Examples:

| Internal value | Default user-facing copy |
| --- | --- |
| `insufficient` | Evidence is insufficient for a strong comparison. |
| `variant_fact_not_available` | The material or variant is not clearly reported. |
| `process_context_not_reported` | The paper does not report enough process context. |
| missing baseline | This result does not include a comparable baseline. |
| section-only locator | Location precision is limited; review the nearby source section. |
| missing `bbox` | The PDF region is unavailable; page or section fallback is used. |

Raw codes may appear only in a deliberate detail, diagnostics, or debug mode.

## Backend Implementation

### Extend The Document Content Response

Change:

- `backend/controllers/schemas/core/documents.py`

Add typed locator fields to `DocumentContentBlockResponse`:

- `page: int | None`
- `bbox: DocumentBoundingBoxResponse | None`
- `char_range: DocumentCharRangeResponse | None`

Recommended first-slice shape:

```py
class DocumentCharRangeResponse(BaseModel):
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)


class DocumentBoundingBoxResponse(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    coord_origin: str | None = None
```

Keep these models local to `documents.py` for the first slice. If later work
needs one shared locator schema across evidence, documents, figures, and
tables, that can be a separate explicit cleanup.

### Preserve Existing Artifact Locator Fields

Change:

- `backend/application/core/semantic_build/document_profile_service.py`

Inside `_build_document_content_blocks()`:

- read `page`, `bbox`, and `char_range` from each block row
- parse locator values from either dictionaries or JSON strings
- normalize `bbox` from both `x0/y0/x1/y1` and `l/t/r/b`
- return normalized locator fields in each block payload
- keep existing `start_offset` and `end_offset` as text fallback offsets
- do not invent a `char_range` from `start_offset` unless the implementation
  deliberately documents that it is content-text-derived rather than
  parser-provenance-derived

Helper behavior:

- `_normalize_page(value) -> int | None`
- `_normalize_char_range_payload(value) -> dict[str, int] | None`
- `_normalize_bbox_payload(value) -> dict[str, float | str | None] | None`
- `_normalize_object_payload(value) -> dict | None`

The service already computes `start_offset` and `end_offset`; those should
remain available for degraded parsed-text highlighting even when artifact
`char_range` is missing.

### Add Source File Resolution

Change:

- `backend/application/source/collection_service.py`

Add a focused method that resolves the stored source file for one document:

```py
def resolve_document_source_file(
    self,
    collection_id: str,
    document_id: str,
) -> dict[str, Any]:
    ...
```

The returned payload should include:

- `path: Path`
- `filename: str`
- `media_type: str | None`
- `source_document_id: str`

Resolution order:

1. read the collection to ensure it exists
2. read `import_manifest.json`
3. find `imports[*].documents[*]` where `source_document_id == document_id`
4. resolve `storage_relpath` against the collection directory when available
5. otherwise resolve `stored_path` from the manifest
6. validate the resolved path stays inside the collection directory and points
   to an existing file
7. if the manifest cannot resolve a file, fall back to `files.json` only when
   it is unambiguous:
   - the stored or original filename matches `document_id`, or
   - the collection has exactly one document file and one document profile
8. raise a typed missing-source error for unresolved or ambiguous cases

Do not make the controller reconstruct paths itself. Path resolution belongs in
the source collection service because that service owns collection file
metadata.

### Add The Source Endpoint

Change:

- `backend/controllers/core/documents.py`

Add:

```py
@router.get(
    "/{collection_id}/documents/{document_id}/source",
    summary="Stream the original source file for one document",
)
async def get_collection_document_source(...):
    ...
```

Use `fastapi.responses.FileResponse`.

Response rules:

- success: `200` with inline file response
- missing collection or document: `404`
- source file unavailable or ambiguous: `409` with structured detail
- unsafe resolved path: `404` or `409` with structured detail, without leaking
  local filesystem paths

### Update Backend API Docs And Tests

Change:

- `backend/docs/specs/api.md`
- `backend/tests/unit/routers/test_documents_api.py`
- any narrower service test if the source-file resolver is easier to verify
  below the controller

Test cases:

- document content blocks include `page`, normalized `bbox`, and `char_range`
- malformed locator payloads become `null` instead of crashing response
- source endpoint streams a stored PDF with the expected content type
- source endpoint returns a structured unavailable response when no source file
  can be resolved
- path traversal is impossible because the endpoint never accepts a requested
  path

Suggested backend verification:

```text
cd backend
./.venv/bin/python -m pytest tests/unit/routers/test_documents_api.py
./.venv/bin/python -m pytest tests/unit/services/test_paper_facts_services.py -k traceback
```

## Frontend Implementation

### Extend The Shared Document Model

Change:

- `frontend/src/routes/_shared/documents.ts`

Add locator fields to the shared document content block type:

- `page: number | null`
- `bbox: PdfBoundingBox | null`
- `charRange: TextCharRange | null`

Keep normalizing backend snake_case to UI-friendly camelCase in the existing
shared helper. Do not add a second browser client or a second API base URL.

Add the document source URL to the workbench model:

```ts
sourceFileUrl: `/api/v1/collections/${collectionId}/documents/${documentId}/source`
```

This should be a same-origin URL. The component can try it only when rendering
the source reader; the normal API helper remains responsible for JSON
contracts.

### Replace Block Rendering With Source Modes

Change:

- `frontend/src/routes/collections/[id]/documents/[document_id]/_components/PaperReader.svelte`

Reader modes:

- `pdf`: render the original source with native browser PDF/object view when
  the source endpoint is available and the file is likely PDF
- `text`: render parsed `content_text` grouped into unique sections
- `unavailable`: show an explicit empty state when neither source nor parsed
  text exists

Section grouping:

- derive section navigation from unique `heading_path` values or true heading
  blocks
- do not create one visible section per block
- use block locators only for scroll targets and fallback highlights

PDF behavior in the first source-backed slice:

- source URL can be loaded through `<object>`, `<iframe>`, or `<embed>`
- page changes can update the URL fragment, for example `#page=6`
- custom region highlights should remain disabled unless a controlled PDF
  renderer is added

### Wire Structured Selection To Source Targets

Change:

- `StructuredExtractionPanel.svelte`
- `ExtractionTabs.svelte`
- `EvidenceCard.svelte`
- `ResultTable.svelte`
- `LocalGraphPanel.svelte`
- `DocumentQaPanel.svelte` only if it surfaces selected-source context
- `+page.svelte`

Behavior:

- selecting a summary card, method row, result row, evidence card, or graph
  node sets one selected workbench object
- the selected object resolves to one `WorkbenchSourceTarget`
- the source reader receives that target and applies the fallback behavior
- the local graph receives the same selected object and rebuilds only the
  local neighborhood
- the selected card remains visibly highlighted

Graph rules:

- center the graph on the selected result, claim, or paragraph
- show at most 6-8 neighbor nodes
- keep graph as auxiliary context; do not make it the primary route

### Keep Fixture Data Close To Future Contracts

When backend data is missing, fixtures may still fill the workbench, but they
must use the same model shape:

- document metadata
- page list and thumbnails
- summary cards
- method table rows
- result rows
- evidence cards
- local graph nodes and edges
- source targets with `page`, `bbox`, `charRange`, `sectionId`, or
  `headingPath`

Fixture source targets should exercise all fallback paths:

- exact text range
- page-only fallback
- section fallback
- unavailable source

### Frontend Verification

Suggested frontend checks:

```text
cd frontend
npm run check
npm run test:unit -- --run src/routes/collections/[id]/documents/[document_id]/document-detail-page.svelte.spec.ts
```

Browser acceptance should cover:

- the document detail route renders a three-column workbench
- the left reader uses original PDF/source mode when the source endpoint works
- parsed text fallback does not repeat section headings for every block
- selecting a structured card highlights the card
- selecting a structured card changes the source target
- source fallback copy is readable and does not expose raw internal codes
- local graph center node changes with the selected object
- graph remains auxiliary and collapses responsively

## Implementation Order

1. Add backend document-content locator fields.
   Verify with document API tests that `page`, `bbox`, and `char_range` round
   trip from stored block artifacts.
2. Add backend source file resolution and source streaming endpoint.
   Verify success, missing-source, and unsafe-path cases.
3. Update `backend/docs/specs/api.md`.
   Keep the API authority aligned with the new response fields and endpoint.
4. Extend frontend document types and workbench model.
   Verify TypeScript and existing route unit tests.
5. Update the source reader so it prefers original PDF/source mode and keeps
   parsed text as a highlightable fallback.
   Verify the reader no longer renders repeated sections from block units.
6. Wire structured selection to `WorkbenchSourceTarget`.
   Verify card selection, source target fallback, and graph neighborhood update
   from the same selected object.
7. Replace default debug/status copy with user-facing language.
   Keep raw codes only in an explicit detail or debug view.

## Acceptance

This wave is accepted when:

- `/collections/[id]/documents/[document_id]` is a paper reading and
  structured understanding workbench, not a debug dashboard
- the left side can display the original PDF/source file when available
- parsed text fallback is coherent and does not expose block repetition as the
  paper structure
- document content blocks expose `page`, `bbox`, and `char_range` when those
  locators exist in source artifacts
- selecting a result, claim, evidence card, or paragraph updates the selected
  source target
- source targeting falls back from exact location to page, section, quote, or
  unavailable states deterministically
- user-facing copy hides raw backend artifact codes by default
- the local graph shows only the selected object's neighborhood
- existing collection navigation, comparisons, results, graph, workspace, and
  protocol routes still work through the same-origin `/api/v1/*` contract

## Risks

Native browser PDF viewers are enough to show the original PDF, but not enough
to draw reliable custom highlights. If exact PDF-region highlighting is a hard
acceptance requirement for this wave, the frontend needs a controlled PDF
renderer. Since the current frontend does not already depend on PDF.js, adding
that dependency should be treated as a separate explicit implementation
decision.

Older collections may not have enough import manifest data to resolve a source
file unambiguously. The source endpoint should return an explicit unavailable
state rather than guessing the wrong file.

PDF bbox coordinate origin differs across parsers. The backend should normalize
field names in the public response and preserve `coord_origin`; the frontend
should avoid drawing bbox overlays until the active PDF renderer understands
the same coordinate convention.
