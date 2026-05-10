# Source Table Artifact Plan

## Summary

This plan records the Source-to-Core structure handoff for table evidence.

The Source layer should preserve the observable evidence substrate of a paper
in three families:

- text context through `documents.parquet`, `text_units.parquet`, and
  `blocks.parquet`
- complete tables through `tables.parquet`, `table_rows.parquet`, and
  `table_cells.parquet`
- figures through `figures.parquet` and `image_assets/`

The active Source runtime now emits table evidence in three related artifacts:

- `tables.parquet`
- `table_rows.parquet`
- `table_cells.parquet`

That shape is the right ownership direction, but the contract still needs one
hardening step: the complete table artifact must be the primary structural
input to Core, while row and cell artifacts remain locators and evidence
anchors. Core should not have to reconstruct a full table from row text or
cells before it can decide how to route, split, or prompt extraction.

That reconstruction belongs in Source. A complete table is observable document
structure, not a Core semantic fact.

The proposed change is to harden the Source-owned complete table artifact:

- add an explicit `table_matrix` field to `tables.parquet`
- bind captions and headings with same-page bbox-aware nearest-neighbor logic
- keep `table_rows.parquet` and `table_cells.parquet` as row and cell anchors
- let Core decide routing, whole-table prompting, chunking, and semantic
  extraction strategy from the complete Source structure

Read this plan with:

- [`source-structure-first-substrate-plan.md`](source-structure-first-substrate-plan.md)
- [`source-parser-evaluation-plan.md`](source-parser-evaluation-plan.md)
- [`rag-anything-source-reference-plan.md`](rag-anything-source-reference-plan.md)
- [`source-figure-asset-extraction-plan.md`](source-figure-asset-extraction-plan.md)
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/table-first-extraction-plan.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/table-first-extraction-plan.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)

## Current Table Flow

The active Source runtime already emits structured table evidence:

- `tables.parquet` carries table-level caption, heading, page, bbox, row and
  column counts, headers, Markdown, and plain text.
- `table_cells.parquet` carries cell text, header paths, unit hints, row and
  column indexes, page, and bounding boxes.
- `table_rows.parquet` carries row-level evidence with `row_text`,
  `heading_path`, page, and row bounding boxes.

Core currently builds table extraction payloads from selected row batches, row
cells, and the matching table context. The remaining problem is that the
consumer path is still row-first: Core can select rows before it has treated
the complete table as the primary structural unit.

That can lose or underuse important table context:

- multi-row headers
- caption and footnotes
- table-wide units and labels
- group rows and section rows
- neighboring rows needed to interpret baseline, sample, or condition columns
- parser-native table HTML or Markdown that may preserve layout better than
  row text alone

Core should not own table reconstruction. Core should decide facts and
extraction grain. Source should preserve the table structure that Core needs to
interpret evidence.

## Proposed Table Artifact

Harden `tables.parquet` as the first-class complete-table Source artifact.

Recommended columns:

- `table_id`
- `document_id`
- `table_order`
- `caption_text`
- `caption_block_id`
- `page`
- `bbox`
- `heading_path`
- `row_count`
- `col_count`
- `column_headers`
- `table_matrix`
- `table_markdown`
- `table_text`
- `metadata`

The first implementation should prioritize:

- `table_matrix`
  Complete row-major cell text as parsed from the table. This is the stable
  structure Core can use to build whole-table prompts or bounded large-table
  views without reconstructing the matrix from row text.
- `table_markdown`
  Human-readable table context for LLM extraction.
- `table_text`
  Plain-text fallback for compact prompts and diagnostics.
- `column_headers`
  Structured header context that survives table rendering differences.
- `caption_text`, `heading_path`, `page`, and `bbox`
  Source locators and surrounding document context.

`table_html` should be deferred. Docling-backed Source can generate stable
Markdown and plain text first. MinerU's table HTML should be evaluated later
through the benchmark and mapping path before it becomes part of the production
artifact schema.

## Source Responsibilities

Source should:

- generate one `tables.parquet` row per observed table
- keep `table_id` stable and shared with `table_rows.parquet` and
  `table_cells.parquet`
- preserve caption, heading path, page, bbox, row count, column count,
  `table_matrix`, and parser details
- bind headings and captions using same-page bbox proximity when coordinates
  are available, with page-order behavior only as fallback
- render a conservative Markdown table from parser cells when parser-native
  Markdown is not available
- keep table rows and cells as separate artifacts for row anchoring, unit
  hints, UI drilldown, and debugging

Source must not:

- extract sample, method, result, baseline, or comparison facts
- decide which row is scientifically important
- decide whether Core should use whole-table prompting or chunked prompting
- use generated table descriptions as research facts
- introduce a production multi-parser branch just to support table HTML

This keeps Source as the owner of observable document structure and keeps Core
as the owner of semantic extraction.

## Core Consumption

Core should consume `tables.parquet` as the primary table structure and use
`table_rows.parquet` plus `table_cells.parquet` as anchoring details.

The consuming flow should be:

```text
tables.parquet
      |
      v
Core table routing
      |
      +-- skip non-extractable tables
      |
      +-- whole-table extraction for small tables
      |
      +-- bounded chunk extraction for large tables
      |
      v
row and cell evidence binding
```

This means the split decision belongs to Core:

- Source returns the full table structure.
- Core decides whether to pass the whole table to the model.
- Core decides whether a large table needs caption, headers, neighbor rows, and
  chunk rows.
- Core binds extracted mentions back to `table_id`, `row_index`, `cell_id`,
  page, and bbox.

Target table context shape:

```json
{
  "table_context": {
    "caption_text": "...",
    "heading_path": "...",
    "column_headers": ["..."],
    "table_matrix": [["Sample", "Hardness"], ["A", "220 HV"]],
    "table_markdown": "...",
    "table_text": "...",
    "page": 3
  },
  "target_row": {
    "row_summary": "...",
    "cells": []
  },
  "supporting_text_windows": []
}
```

For small tables, the extraction prompt can use the complete table context and
all target rows. For large tables, Core should derive a bounded view from the
same complete Source artifact.

The model should be told:

- extract facts only when they are anchored in the target row or target row
  cells
- use the rest of the table only to interpret headers, units, groups,
  baselines, and row meaning
- do not copy values from other rows into facts for the target row
- keep evidence anchors tied to the target row, page, and source text

For large tables, Core should include a bounded view assembled from the Source
table artifact:

- caption and heading path
- column headers
- target row
- nearby rows
- row groups or section rows that apply to the target row
- table footnotes when present

The bounded large-table view should be Core prompt shaping over Source data,
not a new Source semantic artifact.

Core should apply the same principle to prose blocks: Source returns complete
ordered blocks, while Core decides whether a block or section is methods,
results, background, references, or noise before targeted extraction.

## First Implementation Slice

The first implementation should be deliberately narrow:

- add `table_matrix` to `tables.parquet` for the active Docling PDF path
- update heading and caption binding to prefer same-page bbox-nearest matches
- keep `table_rows.parquet` and `table_cells.parquet` unchanged
- keep `tables.parquet` as the primary table context exposed through the Source
  artifact loader
- change Core consumption so table context drives routing and split decisions
- keep row and cell artifacts as binding anchors

The first implementation should not:

- add MinerU as a production parser dependency
- add a production parser switch or compatibility layer
- add `table_html` to the stable schema
- change public API response shapes unless a consumer requires table readiness
  flags
- remove row or cell artifacts
- move scientific table classification into Source

This gives Core complete table structure without changing the active parser
choice or broadening Source into semantic extraction.

## Implementation Map

Update `backend/infra/source/contracts/artifact_schemas.py`:

- add `table_matrix` to `TABLES_FINAL_COLUMNS`
- keep existing `TABLE_ROWS_FINAL_COLUMNS` and `TABLE_CELLS_FINAL_COLUMNS`
  stable

Update `backend/infra/source/runtime/workflows/create_source_artifacts.py`:

- keep `table_id` generation aligned with `_build_pdf_table_cells(...)` and
  `_build_pdf_table_rows(...)`
- persist the Docling table matrix into `tables.parquet`
- replace page-only heading resolution for tables and rows with bbox-aware
  same-page heading resolution when table or row bbox exists
- keep caption fallback based on same-page bbox proximity and record linkage
  details in `metadata`

Update `backend/application/source/artifact_input_service.py`:

- preserve `table_matrix` when loading `tables.parquet`
- keep missing-artifact failures explicit for consumers that require complete
  table structure

Update `backend/application/core/semantic_build/paper_facts_service.py`:

- load `tables.parquet`
- group table records by `table_id`
- drive table extraction planning from table records rather than from selected
  rows alone
- decide in Core whether a table is skipped, sent whole, or split into bounded
  chunks
- bind extracted mentions back to rows and cells after extraction

Update `backend/application/core/semantic_build/llm/prompts.py`:

- allow complete small-table context in table prompts
- state that non-target rows remain context unless the prompt declares them as
  target rows

Update tests:

- extend Source Docling fixture coverage in
  `backend/tests/unit/services/test_source_evidence_workflows.py`
- extend Core payload and prompt tests in
  `backend/tests/unit/services/test_paper_facts_services.py`
- extend Source contract path coverage in
  `backend/tests/unit/services/test_materials_comparison_v2_contracts.py` or
  the nearest existing Source handoff contract test

## Delivery Sequence

### 1. Harden The Complete Table Artifact Schema

Add `table_matrix` to `TABLES_FINAL_COLUMNS` in
`backend/infra/source/contracts/artifact_schemas.py`.

Keep `tables.parquet` next to `table_rows.parquet` and `table_cells.parquet`.

Verification:

- Source workflow writes `tables.parquet` with `table_matrix`
- empty or no-table documents still produce an empty `tables.parquet` with the
  fixed columns
- existing `table_rows.parquet` and `table_cells.parquet` schemas remain stable
- `table_html` is not part of the first stable schema

### 2. Generate Tables From Docling

Add a direct Docling-backed table builder in
`backend/infra/source/runtime/workflows/create_source_artifacts.py`.

The builder should use Docling table objects and existing Source helpers to
produce:

- stable `table_id`
- caption linkage when available
- page and bbox
- heading path
- row and column counts
- column headers
- row-major `table_matrix`
- Markdown and plain-text renderings
- parser details in `metadata`

Markdown rendering should be conservative. It should preserve row order and
visible cell text rather than trying to infer scientific meaning. Merged cells
can be repeated or represented plainly in the first version as long as the raw
cell artifact remains available for debugging.

Verification:

- existing Docling fixture tests cover `tables`
- `table_id` matches rows and cells for the same table
- `table_matrix` preserves row order and visible cell text
- table Markdown contains headers and data cells in row order

### 3. Fix Heading And Caption Binding

Update table, row, and figure context binding so Source prefers same-page
bbox-nearest structure:

- for headings, choose the nearest same-page heading above the target bbox when
  possible
- for captions, choose the nearest same-page table or figure caption around the
  target bbox and avoid reusing the same caption block for multiple targets
- fall back to the existing page-order behavior only when bbox data is missing

Verification:

- table fixtures with two same-page sections bind to the nearer heading above
  the table
- table fixtures with nearby captions bind the expected caption block
- missing bbox still produces a deterministic fallback heading path

### 4. Expose Tables To Application Services

Update `backend/application/source/artifact_input_service.py` with:

- `tables` path in `CollectionArtifactPaths`
- `load_tables_artifact(...)`

Do not update readiness surfaces in the first slice unless a consumer requires
table-level readiness. If added later, `tables_generated` and `tables_ready`
should mean only that the Source table artifact exists and has rows.

Verification:

- path contract tests include `tables.parquet`
- missing `tables.parquet` fails clearly when a consumer requires table context

### 5. Change Core To Consume Complete Table Structure

Update `PaperFactsService` so it loads `tables.parquet`, groups tables by
`table_id`, and plans table extraction from complete table records.

Rows and cells remain anchors. The table is the structural unit Core routes
and splits.

Verification:

- payload tests assert `table_context.table_matrix` and `table_markdown` are
  present for small-table extraction
- prompt tests assert extraction remains row and cell anchored after Core
  decides the target rows
- paper-facts service tests cover missing table context explicitly
- small-table tests assert Core can pass the whole table context
- large-table tests assert Core builds a bounded view from the complete Source
  table artifact

### 6. Re-score Parser Candidates Against The New Shape

Update `source_parser_benchmark.py` so parser scoring includes table-level
dimensions:

- table context availability
- Markdown or HTML readability
- caption linkage
- header recovery
- row and column count consistency
- mapping into `tables.parquet`

MinerU should be evaluated for how well its `content_list` table HTML or
Markdown can populate `tables.parquet`. This does not make MinerU a production
dependency by itself.

Verification:

- benchmark reports table-level metrics for Docling
- MinerU benchmark output records whether table HTML or Markdown could map
  into the proposed table artifact

## Verification Commands

Run the focused checks for the changed surfaces:

```bash
cd backend
./.venv/bin/python -m pytest \
  tests/unit/services/test_source_evidence_workflows.py \
  tests/unit/services/test_paper_facts_services.py \
  tests/unit/services/test_materials_comparison_v2_contracts.py
cd ..
python3 scripts/check_docs_governance.py
```

If the implementation only touches Source schema and runtime mapping in the
first pass, run the Source evidence workflow tests before expanding to Core.

## Parser Implications

The table artifact makes parser comparison more meaningful.

Docling remains the safest active production parser because it already maps
into Source rows, cells, figures, and locators.

MinerU remains a useful benchmark candidate because it exposes table HTML,
Markdown, images, and content-list structures that may produce better
whole-table context. Its value should be judged by how cleanly it can populate:

- `tables.parquet`
- `table_rows.parquet`
- `table_cells.parquet`
- figure rows and assets
- stable locators

Do not choose a parser because it has a richer demo output. Choose the parser
that best fills the Lens Source evidence contract.

## Success Criteria

This plan is successful when:

- Source emits `tables.parquet` with complete `table_matrix`, Markdown, text,
  caption, heading, page, and bbox context
- Core can plan table routing, whole-table prompting, or bounded chunking
  without reconstructing tables from cells
- table extraction remains anchored to rows and cells after Core chooses the
  target extraction grain
- Docling and MinerU can be compared on table-level context quality
- no Source-generated table description becomes a research fact

It is not successful if:

- Core owns parser-specific table reconstruction
- `tables.parquet` replaces rows or cells instead of complementing them
- Source starts deciding whether a table is composition, current-work results,
  prior work, or otherwise scientifically extractable
- table context causes the model to extract facts without row or cell anchors
- the implementation introduces a production parser compatibility layer

## Risks

Large tables can exceed prompt budgets. Core should use bounded table views for
large tables while Source keeps the complete table artifact.

Markdown rendering can hide spans and merged cells. Source should keep cells
and metadata so table context can be debugged against `table_cells.parquet`.

Caption or heading linkage may be incomplete for some parser outputs. Missing
captions or headings should be explicit in `metadata` rather than filled with
generated summaries.

Adding `table_matrix` changes the Source artifact surface. It should be
treated as a forward contract addition and verified with targeted Source and
Core tests before any parser adoption decision.
