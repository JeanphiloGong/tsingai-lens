# Source Table Artifact Plan

## Summary

This plan records the next Source-layer contract change for table evidence.

The Source layer should preserve the observable evidence substrate of a paper
in three families:

- text context through `documents.parquet`, `text_units.parquet`, and
  `blocks.parquet`
- complete tables through `tables.parquet`, `table_rows.parquet`, and
  `table_cells.parquet`
- figures through `figures.parquet` and `image_assets/`

The current Source artifacts preserve table evidence only as row and cell
outputs:

- `table_rows.parquet`
- `table_cells.parquet`

That shape is useful for evidence anchors and fine-grained locators, but it is
not enough for table-grounded extraction. Core currently receives one selected
table row plus row cells and nearby text windows. When a table needs whole-table
context, Core must reconstruct that context from cells.

That reconstruction belongs in Source. A complete table is observable document
structure, not a Core semantic fact.

The proposed change is to add a Source-owned table artifact:

- `tables.parquet`

Core should then use `tables.parquet` as table context while still anchoring
extraction to selected rows from `table_rows.parquet`.

Read this plan with:

- [`source-structure-first-substrate-plan.md`](source-structure-first-substrate-plan.md)
- [`source-parser-evaluation-plan.md`](source-parser-evaluation-plan.md)
- [`rag-anything-source-reference-plan.md`](rag-anything-source-reference-plan.md)
- [`source-figure-asset-extraction-plan.md`](source-figure-asset-extraction-plan.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)

## Current Table Flow

The active Source runtime already emits structured table evidence:

- `table_cells.parquet` carries cell text, header paths, unit hints, row and
  column indexes, page, and bounding boxes.
- `table_rows.parquet` carries row-level evidence with `row_text`,
  `heading_path`, page, and row bounding boxes.

Core currently builds table extraction payloads from the selected row and its
cells. The prompt asks the model to extract facts from one table row and to use
supporting text windows only when needed.

This keeps extraction anchored, but it loses important table context:

- multi-row headers
- caption and footnotes
- table-wide units and labels
- group rows and section rows
- neighboring rows needed to interpret baseline, sample, or condition columns
- parser-native table HTML or Markdown that may preserve layout better than
  row text alone

Core should not own this reconstruction. Core should decide facts. Source
should preserve the table structure that Core needs to interpret evidence.

## Proposed Table Artifact

Add `tables.parquet` as a first-class Source artifact.

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
- `table_markdown`
- `table_text`
- `metadata`

The first implementation should prioritize:

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
- preserve caption, heading path, page, bbox, row count, column count, and
  parser details
- render a conservative Markdown table from parser cells when parser-native
  Markdown is not available
- keep table rows and cells as separate artifacts for row anchoring, unit
  hints, UI drilldown, and debugging

Source must not:

- extract sample, method, result, baseline, or comparison facts
- decide which row is scientifically important
- use generated table descriptions as research facts
- introduce a production multi-parser branch just to support table HTML

This keeps Source as the owner of observable document structure and keeps Core
as the owner of semantic extraction.

## Core Use

Core should continue to select table rows as extraction units, but each
table-row payload should include a table context object.

Target payload shape:

```json
{
  "table_context": {
    "caption_text": "...",
    "heading_path": "...",
    "column_headers": ["..."],
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

The extraction prompt should change from "this one table row" to "this target
row using table context".

The model should be told:

- extract facts only when they are anchored in the target row or target row
  cells
- use the rest of the table only to interpret headers, units, groups,
  baselines, and row meaning
- do not copy values from other rows into facts for the target row
- keep evidence anchors tied to the target row, page, and source text

For small tables, Core can include the full `table_markdown`. For large tables,
Core should include a bounded view assembled from the Source table artifact:

- caption and heading path
- column headers
- target row
- nearby rows
- row groups or section rows that apply to the target row
- table footnotes when present

The bounded large-table view should be Core prompt shaping over Source data,
not a new Source semantic artifact.

## First Implementation Slice

The first implementation should be deliberately narrow:

- add `tables.parquet` for the active Docling PDF path
- keep `table_rows.parquet` and `table_cells.parquet` unchanged
- expose `tables.parquet` through the Source artifact loader
- pass table context into Core table-row extraction
- keep the extraction unit as the selected target row

The first implementation should not:

- add MinerU as a production parser dependency
- add a production parser switch or compatibility layer
- add `table_html` to the stable schema
- change public API response shapes unless a consumer requires table readiness
  flags
- remove row or cell artifacts

This gives Core whole-table context without changing the active parser choice
or broadening Source into semantic extraction.

## Implementation Map

Update `backend/infra/source/contracts/artifact_schemas.py`:

- add `TABLES_FINAL_COLUMNS`
- keep existing `TABLE_ROWS_FINAL_COLUMNS` and `TABLE_CELLS_FINAL_COLUMNS`
  stable

Update `backend/infra/source/runtime/workflows/create_source_artifacts.py`:

- add `tables` to `SourceArtifactBundle`
- write `tables` in `run_workflow(...)`
- concatenate `tables` across bundles in `create_source_artifacts(...)`
- return an empty `tables` frame in `_build_text_bundle(...)`
- add `_build_pdf_tables(...)` and call it from `_build_pdf_bundle(...)`
- keep `table_id` generation aligned with `_build_pdf_table_cells(...)` and
  `_build_pdf_table_rows(...)`

Update `backend/application/source/artifact_input_service.py`:

- add a `tables` path to `CollectionArtifactPaths`
- add `load_tables_artifact(...)`

Update `backend/application/core/semantic_build/paper_facts_service.py`:

- load `tables.parquet`
- group table records by `table_id`
- pass the matching table record into table-row extraction payload building
- keep target row selection and evidence binding unchanged

Update `backend/application/core/semantic_build/llm/prompts.py`:

- change the table prompt from one-row-only wording to target-row-with-context
  wording
- state that non-target rows are context only

Update tests:

- extend Source Docling fixture coverage in
  `backend/tests/unit/services/test_source_evidence_workflows.py`
- extend Core payload and prompt tests in
  `backend/tests/unit/services/test_paper_facts_services.py`
- extend Source contract path coverage in
  `backend/tests/unit/services/test_materials_comparison_v2_contracts.py` or
  the nearest existing Source handoff contract test

## Delivery Sequence

### 1. Add The Table Artifact Schema

Add `TABLES_FINAL_COLUMNS` to
`backend/infra/source/contracts/artifact_schemas.py`.

Update `SourceArtifactBundle` and `create_source_artifacts` so the active
workflow writes `tables.parquet` next to `table_rows.parquet` and
`table_cells.parquet`.

Verification:

- Source workflow writes `tables.parquet`
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
- Markdown and plain-text renderings
- parser details in `metadata`

Markdown rendering should be conservative. It should preserve row order and
visible cell text rather than trying to infer scientific meaning. Merged cells
can be repeated or represented plainly in the first version as long as the raw
cell artifact remains available for debugging.

Verification:

- existing Docling fixture tests cover `tables`
- `table_id` matches rows and cells for the same table
- table Markdown contains headers and data cells in row order

### 3. Expose Tables To Application Services

Update `backend/application/source/artifact_input_service.py` with:

- `tables` path in `CollectionArtifactPaths`
- `load_tables_artifact(...)`

Do not update readiness surfaces in the first slice unless a consumer requires
table-level readiness. If added later, `tables_generated` and `tables_ready`
should mean only that the Source table artifact exists and has rows.

Verification:

- path contract tests include `tables.parquet`
- missing `tables.parquet` fails clearly when a consumer requires table context

### 4. Add Table Context To Core Extraction

Update `PaperFactsService` so it loads `tables.parquet`, groups tables by
`table_id`, and passes table context into table-row extraction payloads.

The row remains the extraction unit. The table is context.

Verification:

- payload tests assert `table_context.table_markdown` is present
- prompt tests assert extraction remains target-row anchored
- paper-facts service tests cover missing table context explicitly
- empty table context degrades to the existing row-and-cell payload behavior
  only if the first implementation deliberately preserves that fallback

### 5. Re-score Parser Candidates Against The New Shape

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

- Source emits `tables.parquet` as a stable artifact
- Core can include whole-table context without reconstructing tables from
  cells
- table-row extraction remains anchored to selected rows
- Docling and MinerU can be compared on table-level context quality
- no Source-generated table description becomes a research fact

It is not successful if:

- Core owns parser-specific table reconstruction
- `tables.parquet` replaces rows or cells instead of complementing them
- table context causes the model to extract facts from non-target rows
- the implementation introduces a production parser compatibility layer

## Risks

Large tables can exceed prompt budgets. Core should use bounded table views for
large tables while Source keeps the complete table artifact.

Markdown rendering can hide spans and merged cells. Source should keep cells
and metadata so table context can be debugged against `table_cells.parquet`.

Caption linkage may be incomplete for some parser outputs. Missing captions
should be explicit in `metadata` rather than filled with generated summaries.

Adding `tables.parquet` changes the Source artifact surface. It should be
treated as a forward contract addition and verified with targeted Source and
Core tests before any parser adoption decision.
