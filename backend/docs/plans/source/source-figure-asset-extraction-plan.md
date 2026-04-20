# Source Figure Asset Extraction Plan

## Summary

This document records the next Source-layer follow-up after the structure-first
substrate cut:

add figure extraction as a traceable Source-owned artifact family without
turning Source into a figure-understanding or multimodal semantic layer.

The target is narrow:

- preserve figure regions as retraceable source assets
- preserve figure captions and figure-to-caption linkage
- keep page, box, and heading-path traceability
- do not perform image semantics, materials interpretation, or Core fact
  generation inside Source

Read this plan with:

- [`source-structure-first-substrate-plan.md`](source-structure-first-substrate-plan.md)
- [`docling-first-source-parser-cutover-plan.md`](docling-first-source-parser-cutover-plan.md)
- [`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md)

## Context

As of 2026-04-20, the active Source runtime already emits:

- `documents.parquet`
- `text_units.parquet`
- `blocks.parquet`
- `table_rows.parquet`
- `table_cells.parquet`

The active PDF path is Docling-backed and already preserves:

- reading-order text items
- block-level page and bounding-box locators
- table cells and derived table rows

But the active Source runtime does not yet emit a figure artifact family.

Current gaps:

- figure or image regions are not persisted as Source-owned rows
- no cropped figure assets are materialized into the collection output
- captions are not split between `table_caption` and `figure_caption`
- Core already has `source_type="figure"` and `figure_or_table`, but Source
  does not provide a first-class figure substrate for them to point to

This leaves a traceability hole:

- tables have a structured Source substrate
- free text has a structured Source substrate
- figures do not

That is the wrong asymmetry for a structure-first Source layer.

## Scope

This plan covers:

- adding Source-owned figure artifacts and figure asset files
- adding figure caption separation at the Source block layer
- preserving figure locator metadata such as page, bbox, and heading path
- defining first-wave backend contracts for figure readiness
- defining optional second-wave read APIs for frontend display

This plan does not cover:

- OCR of scanned figures
- chart or microscopy semantic interpretation
- multimodal LLM extraction from images
- moving figure understanding into Source
- changing the Core evidence ontology
- making figure extraction a hard prerequisite for the current document,
  table, or paper-facts backbone

## Proposed Change

### Design Rule

Source should treat figures the same way it treats tables:

- preserve the document-native structure
- preserve locators and traceability
- preserve a light convenience projection
- stop before semantic interpretation

That means Source owns:

- figure region detection
- caption linkage
- cropped asset materialization
- traceability metadata

And Source does not own:

- what the image means scientifically
- whether a figure implies a result, mechanism, or comparison
- image-derived paper facts

### Target Source-Owned Artifacts

Add two new Source outputs:

- `figures.parquet`
- `image_assets/`

`image_assets/` is a collection-local output directory under the Source output
path. Each extracted figure asset is written as a cropped image file named by
stable `figure_id`.

### Target `figures.parquet` Contract

The first wave should add one row per extracted figure region.

Minimum intended fields:

- `figure_id`
- `document_id`
- `figure_order`
- `figure_label`
- `caption_text`
- `caption_block_id`
- `page`
- `bbox`
- `heading_path`
- `image_path`
- `image_mime_type`
- `image_width`
- `image_height`
- `asset_sha256`
- `metadata`

Rules:

- `figure_id` is the stable collection-local figure identifier
- `figure_label` stores the visible label when one is detectable, such as
  `Figure 2` or `Fig. 3a`
- `caption_text` stores the linked caption text, not a semantic summary
- `caption_block_id` points to the Source block row that owns the caption when
  such a block exists
- `bbox` is the figure-region locator in page coordinates
- `image_path` is a Source-owned relative asset path under `image_assets/`
- `metadata` may carry parser-specific details such as Docling object ids,
  extraction confidence, or fallback linkage method

### Target Block Semantics

The current block contract should split caption kinds:

- `table_caption`
- `figure_caption`

Current behavior over-collapses all captions into `table_caption`. That should
be corrected so later consumers can distinguish:

- caption text that belongs to a table artifact
- caption text that belongs to a figure artifact

This is still structure-first work, not figure semantics.

### Wave A: Source Substrate And Asset Materialization

The first implementation wave should change only the Source seam and its
readiness surfaces.

Primary behavior:

1. Parse PDF figures from the Docling document object when available.
2. Build one `figures` dataframe per document.
3. Render the source PDF page and crop the figure region by `page + bbox`.
4. Write cropped image assets to `output/image_assets/`.
5. Write `figures.parquet` beside the existing Source parquet outputs.
6. Surface `figures_generated` and `figures_ready` through Source task and
   workspace payloads.

Important fallback rule:

- if a figure row can be detected but the asset crop cannot be materialized,
  keep the row with `image_path = null`
- traceability rows should not disappear just because asset rendering failed

### Wave B: Optional Collection Read APIs

The second wave is optional for backend/frontend integration.

If frontend or debugging workflows need direct access, add:

- `GET /api/v1/collections/{collection_id}/source/figures`
- `GET /api/v1/collections/{collection_id}/source/figures/{figure_id}/asset`

These routes should remain Source-owned read surfaces, not Core fact routes.

### Core Boundary Rule

Core should not be changed in the first wave except for optional passive
reading of the new Source artifact later.

First-wave non-goals:

- do not update the main paper-facts extraction flow to require figure inputs
- do not add multimodal extraction into `paper_facts_service`
- do not convert figure rows directly into evidence cards in Source

The only required Core-facing cleanup in this plan is that Source block types
should no longer mislabel figure captions as table captions.

## Extraction Strategy

### PDF Parsing Path

For born-digital PDFs:

- keep using the Docling-backed path in
  `backend/infra/source/runtime/workflows/create_source_artifacts.py`
- add `_build_pdf_figures(...)` beside `_build_pdf_blocks(...)`,
  `_build_pdf_table_cells(...)`, and `_build_pdf_table_rows(...)`

Preferred source of truth:

- figure or picture objects directly exposed by the Docling document

If Docling exposes:

- figure region provenance
- caption relationship
- page locator

then use that directly.

If caption linkage is not directly available, use a bounded fallback:

- same-page caption candidates only
- nearest caption block below or above the figure bbox
- label match if both figure label and caption label are available

The fallback must write its linkage method into `metadata`.

### Asset Crop Strategy

Do not make Source depend on recovering the original embedded bitmap stream.

Instead:

- render the PDF page to an image
- crop by the Source `bbox`
- write a normalized PNG asset

Why this path is preferred:

- it matches the visible document coordinate system
- it shares the same traceability frame as Source bbox locators
- it works even when the figure in the PDF is vector content rather than an
  embedded bitmap

### Text And Non-PDF Fallback

For `.txt` or non-PDF inputs:

- do not attempt asset generation
- optionally detect caption-like lines such as `Figure 1 ...` and emit
  `figure_caption` blocks only if the heuristic is high-confidence
- do not emit `figures.parquet` rows without a real figure region

This keeps the first wave honest:

- text-only inputs may preserve figure-caption mentions
- only PDF inputs produce actual figure assets

## File Change Plan

### Wave A: Required Files

- `backend/infra/source/contracts/artifact_schemas.py`
  add `FIGURES_FINAL_COLUMNS`
- `backend/infra/source/runtime/workflows/create_source_artifacts.py`
  build `figures` rows, split caption types, and materialize cropped assets
- `backend/application/source/artifact_registry_service.py`
  surface figure readiness
- `backend/application/source/artifact_input_service.py`
  expose the new figure artifact path
- `backend/controllers/schemas/source/task.py`
  add `figures_generated` and `figures_ready`
- `backend/controllers/schemas/core/workspace.py`
  add `figures_generated` and `figures_ready`
- `backend/tests/...`
  add Source and API verification for figure artifacts

### Wave B: Optional Files

- `backend/controllers/source/...`
  add collection-scoped figure list and asset routes
- `backend/docs/specs/api.md`
  document the new Source figure routes if Wave B lands

## Verification

### Wave A Verification

Use one born-digital PDF that contains:

- at least one visible figure
- at least one visible caption
- at least one table

Minimum checks:

- `figures.parquet` is produced
- `image_assets/` contains at least one cropped figure asset
- each figure row carries `document_id`, `page`, and `bbox`
- `caption_block_id` resolves to a `figure_caption` block when a caption exists
- existing `documents`, `text_units`, `blocks`, `table_rows`, and
  `table_cells` still build
- `table_caption` and `figure_caption` are no longer conflated

### Wave B Verification

If read APIs land:

- the figure list route returns the expected count and locator fields
- the asset route serves the cropped image with the expected content type
- figure readiness surfaces appear in workspace and task artifact payloads

## Risks

- Docling figure APIs may be less stable or less explicit than the table APIs
- page rendering and cropping adds runtime cost and storage cost
- caption linkage fallback can be wrong when page layout is dense
- scanned PDFs remain out of scope, so image-heavy legacy papers will still
  need a later OCR wave

## Delivery Rule

The first delivery should prefer a conservative, honest substrate over a broad
feature claim.

That means:

- ship figure rows only when the figure region is really detected
- ship cropped assets only when the crop is really materialized
- keep missing values explicit instead of inventing figure structure
- keep multimodal semantics out of Source

This preserves the Source/Core boundary while finally closing the figure-side
traceability gap in the Source substrate.
