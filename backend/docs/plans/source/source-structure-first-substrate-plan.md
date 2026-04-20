# Source Structure-First Substrate Plan

## Summary

This document records the next Source follow-up after
[`docling-first-source-parser-cutover-plan.md`](docling-first-source-parser-cutover-plan.md).

The target is narrow:

turn Source into a document-structure substrate that preserves traceable PDF
and text structure, then move materials-oriented semantic labeling, paper-facts
extraction, and derived-view assembly into Core.

This plan exists because the Docling-first cutover fixes the most immediate
parser problem, but it does not yet fix the deeper layering problem:

- raw PDFs are now preserved and parsed inside Source
- Source still emits `sections.parquet` and `table_cells.parquet`
- those outputs are still shaped partly around downstream task semantics such
  as `methods` and `characterization`

That means the parser path is stronger, but the Source/Core ownership boundary
is still mixed.

Read this plan with:

- [`docling-first-source-parser-cutover-plan.md`](docling-first-source-parser-cutover-plan.md)
- [`born-digital-source-parser-first-plan.md`](born-digital-source-parser-first-plan.md)
- [`../backend-wide/materials-comparison-v2-plan.md`](../backend-wide/materials-comparison-v2-plan.md)
- [`../../../../docs/decisions/rfc-paper-facts-primary-domain-model.md`](../../../../docs/decisions/rfc-paper-facts-primary-domain-model.md)

## Context

As of 2026-04-20, the backend has already completed one important correction:

- upload no longer destroys PDF files by flattening them into `.txt`
- Source runtime can now consume `.pdf` and `.txt` directly
- Docling-backed parsing is now on the active Source path

That cutover is necessary, but it is still only the first half of the Source
repair.

The current active Source contract still mixes two jobs:

1. document-structure recovery
2. downstream semantic preparation for Core extraction

The main evidence of that mixing is:

- `sections.parquet` still behaves like a task-shaped slice rather than a
  neutral document-structure artifact
- Source still gives special treatment to labels such as `methods` and
  `characterization`
- `table_cells.parquet` still carries convenience shaping for current Core
  extraction instead of only preserving traceable table structure

That is backwards for the intended layering.

Source should answer:

- what document structure exists
- where each block or table fragment came from
- how later semantic objects can point back to original evidence

Core should answer:

- how each block or table row should be interpreted after extraction
- which mentions belong to the same sample or variant
- which conditions, methods, and results are comparable
- which evidence becomes cards, comparisons, protocol steps, or other
  semantic objects

## Current Implementation Status

As of 2026-04-20, the active code path has already completed the first hard
cut of the Source substrate and the direct Core consumers.

Implemented in code:

- Source artifact creation now writes `documents.parquet`,
  `text_units.parquet`, `blocks.parquet`, `table_rows.parquet`, and
  `table_cells.parquet`
- `backend/application/source/artifact_input_service.py` no longer exposes
  Source-owned `sections` loading
- document-profile building now reads Source `blocks`
- Core evidence extraction now reads Source `blocks`, `table_rows`, and
  `table_cells`
- document content and traceback resolution now use document `blocks` instead
  of Source `sections`
- collection artifact registry, task payloads, and workspace payloads now
  expose `blocks_*` and `table_rows_*` readiness flags instead of
  `sections_*`

Important boundary clarification after the cut:

- `sections.parquet` still exists inside the protocol branch, but it is now a
  protocol-owned derived artifact rather than a Source-owned substrate
- protocol artifacts are still built from `documents/text_units` plus the
  local `build_sections(...)` helper, not from a Source-level
  `sections.parquet` handoff contract

Known follow-up cleanup still outside this cut:

- the protocol branch still carries section-shaped local semantics because its
  own artifact family remains section-first
- several historical plan docs still describe Source as if it emits
  `sections.parquet`
- some Core-local internal names still use `section` as a local extraction
  unit label even though the persisted Source contract is now
  `blocks/table_rows/table_cells`

## Scope

This plan covers:

- replacing semantic-first Source handoff shaping with a structure-first
  Source substrate
- defining the next Source-owned artifact set around document-native
  structure, locators, and traceback
- moving `methods` and `characterization` style slicing out of Source and into
  Core-owned derivation logic
- updating Core consumers so they run extraction across the full structural
  Source substrate instead of depending on Source-owned semantic shortcuts or a
  prefilter stage
- retiring Source-local heuristic code that only exists to preserve the old
  semantic-first contract

This plan does not cover:

- redesigning the Core evidence ontology itself
- changing the current collection-facing route family or protocol-branch
  semantics outside the paper-facts-backed Core model
- introducing scanned-PDF OCR work
- chart or figure understanding
- turning Source into a fact-producing layer
- adding long-lived dual-path compatibility layers

## Proposed Change

### Design Rule

Source becomes structure-first and traceability-first.

That means:

- Source preserves document-native structure
- Source preserves locator metadata such as page, box, character span, and
  heading path
- Source does not pre-classify document structure into materials-task
  semantics by default
- Core derives materials-task views from Source artifacts instead of asking
  Source to emit them directly

### Target Source-Owned Artifacts

The next Source substrate should converge on four primary artifacts:

- `documents.parquet`
- `blocks.parquet`
- `table_rows.parquet`
- `table_cells.parquet`

These are the Source-owned questions they answer:

- `documents.parquet`
  one row per source document with parser, path, media type, checksum, and
  top-level provenance
- `blocks.parquet`
  reading-order text blocks with block type, heading path, page, box, and
  character range
- `table_rows.parquet`
  row-level table evidence with heading path, page, and row-local traceability
- `table_cells.parquet`
  cell-level table evidence with header relationships and locators

The first wave should not require a separate `heading_nodes.parquet` if
`heading_path` and `heading_level` can remain explicit on blocks and table
artifacts.

### Target Artifact Semantics

#### `documents.parquet`

Keep one row per document and focus on durable document metadata.

Minimum intended fields:

- `document_id`
- `title`
- `media_type`
- `source_path`
- `checksum`
- `page_count`
- `parser_name`

Document full text may still exist as a convenience field, but it should be
treated as a derived join over reading-order blocks rather than as the primary
parser substrate.

#### `blocks.parquet`

This becomes the main Source substrate for non-tabular content.

Minimum intended fields:

- `block_id`
- `document_id`
- `block_type`
- `text`
- `block_order`
- `page`
- `bbox`
- `char_range`
- `heading_path`
- `heading_level`

Rules:

- blocks reflect document-native structure such as title, heading, paragraph,
  caption, or list item
- blocks keep traceability-first metadata even when later consumers do not
  need every field immediately
- blocks are not pre-labeled as `methods`, `characterization`, `comparison`,
  or `claim`

#### `table_rows.parquet`

This becomes the row-level bridge between document tables and Core extraction.

Minimum intended fields:

- `row_id`
- `document_id`
- `table_id`
- `row_index`
- `row_text`
- `page`
- `bbox`
- `heading_path`

Rules:

- rows preserve table-local reading order
- rows remain observable evidence, not interpreted measurement objects
- row text exists only as a convenience join over cells, not as a semantic
  collapse

#### `table_cells.parquet`

Cell-level table structure remains useful, but the artifact should stay
structure-first.

Minimum intended fields:

- `cell_id`
- `document_id`
- `table_id`
- `row_id`
- `row_index`
- `col_index`
- `cell_text`
- `is_header`
- `header_path`
- `page`
- `bbox`

Rules:

- preserve header relationships when possible
- preserve locator fidelity
- avoid Source-owned semantic hints such as unit normalization or materials
  interpretation unless they are purely structural and parser-native

### What Leaves Source

The following should stop being Source-owned responsibilities:

- deciding whether a section is `methods` or `characterization`
- deciding whether a table row is a measurement result
- deciding whether two observations are comparable
- emitting task-shaped semantic shortcuts purely for Core convenience

Those all become Core derivation work.

### Core Extraction Rule

Once Source emits the structure-first substrate, Core should not perform a
coarse candidate-selection pass that discards most blocks before extraction.

Instead, Core should run extraction across the full structural unit set:

- all `blocks.parquet` rows
- all `table_rows.parquet` rows
- table-local detail from `table_cells.parquet` when needed

The first Core pass should produce traceable labels and local annotations per
structural unit, for example:

- process-related
- characterization-related
- result-related
- background or discussion
- likely irrelevant to the materials task

Those labels remain Core outputs, not Source outputs.

This rule matters for two reasons:

1. prefiltering reintroduces a hidden heuristic gate before extraction
2. block-level labels are directly useful to the frontend as a visibility and
   traceback layer even before higher-order semantic objects are fully
   assembled

### Core-Derived Outputs

After the full-pass labeling step, Core can assemble higher-order semantic
views such as:

- labeled block or row inventories for UI differentiation
- sample or variant candidates
- process-condition candidates
- characterization observations
- measurement-result candidates
- comparison-ready groupings

Those are not Source artifacts. They are Core-owned outputs built over the
full Source substrate.

### Document Profile Boundary

`document_profile_service` should remain a document-level triage step rather
than expanding into the first block-labeling pass.

It may consume a small structure-first payload derived from Source artifacts,
for example:

- title-bearing blocks
- lead or abstract-like blocks
- heading paths derived from `blocks.parquet`

But it should not own:

- block-level labels
- row-level local annotations
- higher-order grouping over samples, conditions, methods, or results

Those belong to the first full-pass Core extraction pass after document triage.

## Migration Shape

The migration should happen in three explicit waves so the repository does not
quietly keep two architectures forever.

### Wave A: Introduce the Canonical Source Substrate

- extend Source runtime to emit `blocks.parquet` and `table_rows.parquet`
- keep `documents.parquet` and `table_cells.parquet`
- derive any temporary legacy `sections.parquet` view from the new structural
  artifacts rather than from independent heuristic recovery
- keep the compatibility surface narrow and clearly transitional

Wave A exists to make the real Source substrate available before changing Core
consumers.

### Wave B: Move Semantic Extraction Into Core

- keep `document_profile_service` as a lightweight document-level triage step
  built from structure-first inputs rather than from Source-owned `methods` or
  `characterization` sections
- update `evidence_card_service` so it extracts against
  `blocks.parquet`, `table_rows.parquet`, and `table_cells.parquet` without a
  prefilter discard stage
- make the first full-pass block and row labeling pass a Core extraction
  responsibility after document triage
- keep semantic labeling, paper-facts assembly, derived-view assembly, and
  task assembly inside Core

Wave B is the true ownership repair. Until it lands, the Source/Core boundary
is still mixed.

### Wave C: Remove the Old Semantic-First Source Contract

- delete Source-local heuristics that only exist to manufacture old semantic
  section types
- remove or drastically shrink `sections.parquet` if it no longer serves as a
  neutral structural artifact
- keep only one active Source design rather than a permanent dual contract

Wave C is required cleanup. Without it, the old contract will keep dragging
the system back toward mixed ownership.

## File Change Plan

The expected code-owned change surface is:

- `backend/infra/source/contracts/artifact_schemas.py`
  define the new Source-owned structural artifacts and shrink or retire the
  semantic-first Source contract
- `backend/infra/source/runtime/workflows/create_source_artifacts.py`
  emit `documents`, `blocks`, `table_rows`, and `table_cells` from parser
  output
- `backend/infra/source/runtime/input.py`
  keep the document inventory and parser inputs aligned with the new
  substrate-driven runtime
- `backend/application/source/artifact_input_service.py`
  load Source structural artifacts for downstream application consumers
- `backend/application/core/document_profile_service.py`
  keep document-level triage narrow and build triage payloads from
  structure-first artifacts rather than consuming Source-owned semantic
  sections
- `backend/application/core/evidence_card_service.py`
  run the first full-pass labeling and extraction pass over structural blocks
  and table rows, then assemble higher-order evidence objects from the labeled
  outputs
- `backend/tests/unit/services/*` and `backend/tests/integration/*`
  rewrite Source and Core tests around the new artifact ownership boundary

## Verification

The implementation wave for this plan should verify three things explicitly.

### Source Verification

- Source emits raw-structure artifacts for both `.pdf` and `.txt` inputs
- blocks preserve heading path, page, and locator metadata where available
- table rows and cells preserve row order and header relationships

### Boundary Verification

- Source tests no longer require `methods` or `characterization` semantics as
  primary Source behavior
- Core tests prove that `document_profile_service` remains a document-level
  triage step rather than the owner of block-level labels
- Core tests prove that extraction runs across the full structural unit set
  and emits labels or local annotations before higher-order grouping
- no new compatibility wrapper or duplicate data path remains after the final
  cleanup wave

### Backbone Verification

- `document_profiles -> paper facts family -> comparison_rows / evidence_cards
  -> protocol branch` still completes after the migration
- task runner and app-layer integration continue to operate on the new
  artifact set without silent contract drift

## Risks

- changing the Source substrate before Core consumers move may create a
  temporary contract mismatch
- if `blocks.parquet` is too coarse, Core will rebuild its own hidden chunking
  layer and recreate the same ambiguity
- if compatibility artifacts are left in place too long, the migration will
  stall with two overlapping Source designs
- if Source keeps emitting semantic hints for convenience, ownership confusion
  will persist even after new artifact names are introduced

## Decision Trigger

This plan should become active once the repository agrees on one rule:

Source owns document structure and traceability.
Core owns materials-task semantics.

The Docling-first cutover already fixes raw parser quality enough to make this
split implementable.
This follow-up plan exists to finish the layering correction instead of
stopping halfway.
