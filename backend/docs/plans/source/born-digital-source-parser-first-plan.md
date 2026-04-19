# Born-Digital Source Parser-First Plan

## Summary

This document records the next backend-local follow-up plan after the current
Source handoff shrink and residual GraphRAG retirement work.

The target is narrow:

replace the active generic ingest-and-chunk Source path with a born-digital
PDF parser-first path while targeting the Source evidence contract required by
Materials Comparison V2.

This plan assumes:

- no scanned-PDF support is required in this wave
- no OCR path is required in this wave
- no GraphRAG graph, community, report, or query semantics return in this wave
- Core remains the only producer of research facts
- Source stays observable and locator-backed only
- the target Source evidence surface is:
  `documents.parquet`, `text_units.parquet`, `sections.parquet`, and
  `table_cells.parquet`

For the parent Source retirement lineage, read
[`source-residual-graphrag-retirement-plan.md`](source-residual-graphrag-retirement-plan.md).
For the downstream consumer target, read
[`materials-comparison-v2-plan.md`](../backend-wide/materials-comparison-v2-plan.md).

## Why This Follow-up Exists

The backend has already completed the important architectural cut:

- product-facing graph, report, and query semantics no longer define the
  system
- the active Source indexing path has been reduced to the minimal Core handoff
- Core now owns the only stable research-fact backbone

That means the next Source problem is no longer GraphRAG retirement by itself.
The next Source problem is input quality.

Current active Source indexing still runs through a generic path:

- `load_input_documents`
- `create_base_text_units`
- `create_final_documents`
- `create_final_text_units`

That path is stable enough for handoff shape, but it is still weak for
born-digital scientific PDFs because it starts from generic input loading and
token chunking rather than document-structure-aware parsing.

It is also too thin for the next comparison backbone wave.

`materials-comparison-v2-plan.md` already establishes the Source contract that
the next Core expansion expects:

- `documents.parquet`
- `text_units.parquet`
- `sections.parquet`
- `table_cells.parquet`

So this plan should not optimize only for today's minimum consumer contract.
It should make the born-digital parser-first path target that stronger
Source-only evidence surface directly.

Since this repository does not currently need scanned-PDF handling, the next
best move is not OCR expansion. It is to make the Source path much better for
born-digital PDFs while freezing the Source evidence surface needed by the next
materials comparison wave.

## Current State

As of 2026-04-17, the active Source handoff and Core dependency boundary are:

- active Source pipeline:
  `load_input_documents -> create_base_text_units -> create_final_documents -> create_final_text_units`
- required Source outputs for Core:
  `documents.parquet` and `text_units.parquet`
- app-layer handoff consumers:
  `application/documents/input_service.py` and `application/indexing/index_task_runner.py`
- current `text_units` normalization still expects generic chunk output columns:
  `id`, `text`, `document_ids`, `n_tokens`
- `sections.parquet` and `table_cells.parquet` are not yet emitted by the
  default indexing pipeline

This means Source implementation can change aggressively inside the indexing
path.

It also means the current default Source path is still below the contract level
needed by Materials Comparison V2 even though it is sufficient for the current
claim-centric Core.

## Scope

This plan covers:

- born-digital PDF parser-first Source ingestion
- an internal Source-owned structured block model for parsing output
- contract freeze for the Source evidence surface needed by
  `materials-comparison-v2-plan.md`
- replacement of generic chunk-first text-unit construction on the active path
- regeneration of `documents.parquet`, `text_units.parquet`,
  `sections.parquet`, and `table_cells.parquet` from parser output
- locator-backed section and table evidence extraction
- test coverage for the new Source handoff path

This plan does not cover:

- scanned PDF support
- OCR engines
- image-based extraction
- Core-owned `sample_variants`, `measurement_results`, or upgraded
  `comparison_rows`
- protocol redesign
- graph, report, or query surface restoration
- dual-path compatibility or fallback execution branches

## Target Design

### Design Rule

Source becomes parser-first internally, but stays minimal externally.

That means:

- Source may build richer transient parsing structures
- Source targets one observable evidence surface:
  `documents.parquet`, `text_units.parquet`, `sections.parquet`, and
  `table_cells.parquet`
- Core continues to treat Source as a normalized upstream provider, not as a
  fact-producing layer
- Source does not emit `sample_variants`, `measurement_results`, or final
  `comparison_rows`

### Target Source Evidence Contract

This plan adopts the Source evidence contract required by
[`materials-comparison-v2-plan.md`](../backend-wide/materials-comparison-v2-plan.md) as its
target output.

The target collection-local Source artifacts are:

- `documents.parquet`
- `text_units.parquet`
- `sections.parquet`
- `table_cells.parquet`

The first two are already present in the current runtime.
The latter two become explicit targets of this parser-first plan rather than a
later undefined add-on.

### Internal Transient Object: `source_blocks`

The new active path should introduce one Source-owned internal parsing object
for born-digital PDFs:

- `block_id`
- `document_id`
- `page`
- `order`
- `block_type`
- `text`
- `bbox` when available
- `font_size` when available
- `heading_level` when available
- `parser_metadata` when available

Rules:

- `source_blocks` is an internal Source object, not a new public artifact
- it exists to preserve layout-aware parsing semantics before Source evidence
  artifacts are built
- Core must not depend on `source_blocks`
- if a block is empty noise after normalization, Source drops it before
  handoff construction

### `documents.parquet` Builder Rules

`documents.parquet` should remain the collection-level document handoff.

Builder rules:

- one row per source document
- `id` remains the stable source document identifier
- `title` prefers parser-derived title, then stored filename fallback
- `text` is rebuilt by joining accepted `source_blocks` in reading order
- existing file/provenance metadata continues to pass through when available
- no Core semantic fields are introduced here

The goal is to make document text cleaner and more faithful without changing
the Core boundary.

### `text_units.parquet` Builder Rules

`text_units.parquet` should stop being primarily token-chunk-derived on the
active path.

Builder rules:

- build text units from normalized semantic blocks or small block groups
- preserve reading order and source-document linkage
- keep the required final columns unchanged:
  `id`, `human_readable_id`, `text`, `n_tokens`, `document_ids`
- compute `n_tokens` from the final unit text rather than from chunker state
- do not require entities, relationships, covariates, communities, or reports

Preferred unit shape for this wave:

- headings stay separate when useful
- short adjacent body blocks may merge into one text unit
- tables, references, and obvious boilerplate should be filtered or clearly
  isolated by Source rules rather than silently mixed into generic chunks

### `sections.parquet` Builder Rules

`sections.parquet` should become a first-class Source artifact rather than a
local heuristic owned only by app-layer helpers.

Minimum intended columns:

- `section_id`
- `document_id`
- `title`
- `section_type`
- `heading`
- `text`
- `text_unit_ids`
- `page`
- `char_range`
- `confidence`

Builder rules:

- derive sections from ordered `source_blocks`
- keep heading and section typing descriptive rather than interpretive
- preserve page or character locators whenever available
- keep text-to-text-unit linkage explicit
- do not assign sample, baseline, or measurement semantics here

### `table_cells.parquet` Builder Rules

`table_cells.parquet` should expose table evidence as observable Source output.

Minimum intended columns:

- `cell_id`
- `document_id`
- `table_id`
- `row_index`
- `col_index`
- `cell_text`
- `header_path`
- `page`
- `bbox`
- `char_range`
- `unit_hint`

Builder rules:

- derive table cells from the same born-digital parser view that produces
  `source_blocks`
- keep row and column position explicit
- keep locator data whenever available
- preserve header context as descriptive evidence
- do not normalize values into Core result semantics here

### Active Boundary Rule

The new parser-first path replaces the current active generic path directly.

This plan does not allow:

- temporary dual-path runtime
- fallback to the old generic chunk-first chain
- compatibility shims that preserve both parsing models after the cut

## Primary Code Seams

The main implementation seams for this wave are:

- `backend/retrieval/index/workflows/load_input_documents.py`
- `backend/retrieval/index/workflows/create_base_text_units.py`
- `backend/retrieval/index/workflows/create_final_documents.py`
- `backend/retrieval/index/workflows/create_final_text_units.py`
- `backend/retrieval/index/workflows/create_sections.py`
- `backend/retrieval/index/workflows/create_table_cells.py`
- `backend/retrieval/index/workflows/factory.py`
- `backend/retrieval/data_model/schemas.py`

Likely supporting seams:

- `backend/retrieval/index/input/`
- `backend/retrieval/index/operations/`
- `backend/application/documents/section_service.py`
- Source-facing tests under `backend/tests/`

The app-layer Source/Core seam should stay stable:

- `backend/application/indexing/index_task_runner.py`
- `backend/application/documents/input_service.py`

## Execution Waves

### Wave A: Freeze The Target Source Contract

Goal:

- make the Source evidence contract required by Materials Comparison V2
  explicit before parser implementation lands

Primary changes:

- freeze `documents.parquet`, `text_units.parquet`, `sections.parquet`, and
  `table_cells.parquet` as the parser-first target outputs
- freeze the minimum `sections` and `table_cells` columns in
  `retrieval/data_model/schemas.py`
- align `application/documents/input_service.py` and related readers with the
  expanded Source artifact set
- keep this wave contract-first and documentation-first

Exit criteria:

- the target Source evidence surface is explicit
- later implementation waves no longer need to redefine what born-digital
  parser-first indexing is supposed to emit

### Wave B: Define Source-Owned Parser Output

Goal:

- introduce one internal born-digital PDF parsing output shape that can feed
  all four target Source artifacts

Primary changes:

- add a parser-first extraction step that emits normalized `source_blocks`
- keep parser metadata internal to Source
- make the active input-loading path explicitly PDF-structure-aware

Exit criteria:

- one Source-owned block model exists for born-digital PDFs
- the active path no longer begins from raw generic text chunking

### Wave C: Rebuild Documents And Text Units From Blocks

Goal:

- replace generic chunk-first document and text-unit construction with
  block-aware construction

Primary changes:

- rewrite `create_base_text_units.py` around block grouping rather than
  `chunk_text(...)`
- rebuild `create_final_documents.py` from ordered accepted blocks
- define deterministic merge and filtering rules for headings, body blocks,
  tables, references, and boilerplate
- compute final `n_tokens` from the new unit text

Exit criteria:

- active `text_units.parquet` is produced from parser-normalized blocks
- `documents.parquet` and `text_units.parquet` are consistent products of one
  parser-first normalization flow

### Wave D: Emit Sections And Table Cells

Goal:

- make the born-digital parser-first path emit the full Source evidence surface
  required by Materials Comparison V2

Primary changes:

- add `create_sections.py`
- add `create_table_cells.py`
- persist `sections.parquet`
- persist `table_cells.parquet`
- ensure every section and table cell remains locator-backed to the source
  document

Exit criteria:

- the default indexing pipeline emits `sections.parquet`
- the default indexing pipeline emits `table_cells.parquet`
- section and table cell records trace back to document locators

### Wave E: Remove Generic Active-Path Residuals And Verify Current Consumers

Goal:

- remove generic chunk-first code and configuration that no longer belongs on
  the active Source path while keeping current Core consumers stable

Primary changes:

- delete obsolete active-path chunking dependencies and dead workflow code
- trim config knobs that only mattered to the replaced chunk-first runtime
- remove tests that validate the old active path and replace them with parser
  path tests
- add Source-focused unit and integration coverage for born-digital PDFs
- run Core-adjacent regression checks on document profiles, evidence cards,
  comparison rows, and protocol gating
- run Source contract checks for `sections.parquet` and `table_cells.parquet`
- document any deliberate Source-only parsing heuristics that affect handoff
  quality

Exit criteria:

- no active runtime path still depends on the old generic chunk-first flow
- no dead active-path workflow branches remain after cutover
- current Core still runs without a new compatibility layer
- the Source evidence surface is ready for `materials-comparison-v2-plan.md`
- no new Source-to-Core adapter or compatibility layer is needed

## Acceptance Criteria

This plan is complete when all of the following are true:

- active Source indexing for born-digital PDFs is parser-first
- active Source indexing no longer depends on generic token chunking
- Source emits `documents.parquet`, `text_units.parquet`, `sections.parquet`,
  and `table_cells.parquet`
- section and table-cell artifacts remain observable and locator-backed
- current Core code does not need schema or orchestration changes just to keep
  current behavior working
- no GraphRAG graph/community/report/query semantics return through Source
- no dual-path or fallback migration code remains after cutover

## Risks

### Parser Library Lock-In

A parser-first path can accidentally leak parser-specific assumptions deep into
Source code.

Mitigation:

- keep parser-specific details inside Source-owned extraction code
- keep final handoff rules expressed in Source terms, not vendor-specific terms

### Overfitting To One PDF Layout

Scientific PDFs vary.

Mitigation:

- write deterministic but narrow rules for the born-digital layouts actually
  seen in this repository now
- add fixtures that cover title pages, headings, multi-column body text,
  references, and table-heavy pages

### Silent Core Regression

Cleaner Source text can still change extraction behavior downstream.

Mitigation:

- keep Core unchanged
- verify document profiles, evidence cards, comparison rows, and protocol
  gating after each wave

### Contract Drift Between Source And Materials Comparison V2

If parser-first work lands without freezing the target Source evidence
contract, the next comparison wave will likely have to reopen Source design.

Mitigation:

- make `sections.parquet` and `table_cells.parquet` explicit deliverables here
- keep this plan aligned with `materials-comparison-v2-plan.md`

## Recommended Next Step

Start with Wave A and Wave B together.

That is the smallest cut that proves the direction:

- freeze the Source evidence contract
- introduce `source_blocks`
- make born-digital parsing the active Source entry shape

If those two waves do not improve born-digital PDF handoff quality, there is
no reason to continue deeper parser-first replacement.
