# Source Runtime Organization Plan

## Summary

This plan records the next Source cleanup wave after the table-matrix handoff.
The goal is to make the active Source runtime easier to read without changing
the Source/Core contract.

The active Source job remains narrow:

```text
collection input files
      |
      v
observable document structure
      |
      v
Source artifacts
```

Source should preserve document structure and locators. Core should decide
scientific meaning, extraction routing, paper facts, and comparisons.

Read this plan with:

- [`source-structure-first-substrate-plan.md`](source-structure-first-substrate-plan.md)
- [`source-table-artifact-plan.md`](source-table-artifact-plan.md)
- [`source-figure-asset-extraction-plan.md`](source-figure-asset-extraction-plan.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)

## Current Runtime Shape

The active Source build is now much smaller than the remaining file layout
suggests.

The collection build runner in `backend/application/source/` orchestrates the
whole build:

```text
Source artifacts
      |
      v
document profiles
      |
      v
paper facts
      |
      v
comparison rows
      |
      v
protocol artifacts
```

The actual active Source runtime pipeline is:

```text
load_input_documents
      |
      v
create_source_artifacts
```

`load_input_documents` scans the configured input storage and creates a source
inventory. `create_source_artifacts` reads that inventory, parses PDF or text
inputs, and writes the final Source handoff artifacts.

The final Source artifact family is:

- `documents.parquet`
- `text_units.parquet`
- `blocks.parquet`
- `figures.parquet`
- `tables.parquet`
- `table_rows.parquet`
- `table_cells.parquet`
- `image_assets/`

## Why The Current Layout Is Hard To Read

The code still carries names and file boundaries from earlier GraphRAG-shaped
pipeline work. That creates several sources of confusion.

`backend/application/source/` sounds like the parser layer, but it is mostly
collection lifecycle and build-task orchestration. It also starts Core
post-processing after Source completes, so the package name is narrower than
its runtime responsibility.

`backend/infra/source/runtime/workflows/create_source_artifacts.py` owns too
many implementation details:

- workflow orchestration
- PDF parsing through Docling
- plain-text fallback
- block, table, row, cell, and figure mapping
- caption and heading binding
- figure asset extraction
- final dataframe concatenation

`load_input_documents` writes an initial `documents` table, then
`create_source_artifacts` overwrites `documents.parquet` with final document
artifacts. That is technically workable, but the name hides the difference
between input inventory and final document artifacts.

Several historical workflow files still exist, including
`create_base_text_units.py`, `create_final_documents.py`,
`create_final_text_units.py`, and `create_table_cells.py`. The active pipeline
does not run them as separate steps, even though some helper functions are
still reused. Readers can mistake those files for the active runtime order.

The table artifact family also needs clear local documentation:

- `tables.parquet` is the primary complete-table structure.
- `table_rows.parquet` is row-level evidence anchoring.
- `table_cells.parquet` is cell-level evidence anchoring and unit/header
  support.

Rows and cells should not be read as replacements for the complete table.

## Target Shape

The first cleanup should keep behavior stable and split the large runtime file
by direct responsibilities.

Target layout:

```text
backend/infra/source/README.md
backend/infra/source/runtime/artifact_bundle.py
backend/infra/source/runtime/workflows/create_source_artifacts.py
backend/infra/source/runtime/parsers/common.py
backend/infra/source/runtime/parsers/docling_pdf.py
backend/infra/source/runtime/parsers/plain_text.py
backend/infra/source/runtime/mapping/block_artifacts.py
backend/infra/source/runtime/mapping/table_artifacts.py
backend/infra/source/runtime/mapping/figure_artifacts.py
backend/infra/source/runtime/mapping/layout_binding.py
```

The proposed ownership is:

- `backend/infra/source/README.md`
  Explains the active Source runtime, Source/Core boundary, output artifact
  family, and local file map.
- `runtime/artifact_bundle.py`
  Owns the existing `SourceArtifactBundle` shape shared by parser paths and the
  workflow.
- `runtime/workflows/create_source_artifacts.py`
  Keeps workflow orchestration only: load inventory rows, choose parser path,
  combine bundles, and write artifacts.
- `runtime/parsers/common.py`
  Owns parser-shared source document id, title, and metadata normalization.
- `runtime/parsers/docling_pdf.py`
  Owns Docling converter setup and PDF-to-Source bundle assembly.
- `runtime/parsers/plain_text.py`
  Owns text fallback bundle assembly.
- `runtime/mapping/block_artifacts.py`
  Owns block extraction, heading paths, captions, and text block normalization.
- `runtime/mapping/table_artifacts.py`
  Owns `tables`, `table_rows`, `table_cells`, table matrix preservation, and
  conservative table rendering.
- `runtime/mapping/figure_artifacts.py`
  Owns `figures.parquet` rows and `image_assets/` extraction.
- `runtime/mapping/layout_binding.py`
  Owns bbox-aware heading and caption binding helpers.

This split should be direct movement of existing implementation into clearer
files. It should not introduce adapters, compatibility layers, or a second
runtime path.

## Delivery Sequence

### Clarify The Runtime Boundary

Add `backend/infra/source/README.md` as the node entry page for Source
infrastructure. It should explain:

- Source preserves observable document structure.
- Core owns semantic interpretation.
- The active pipeline is `load_input_documents -> create_source_artifacts`.
- `tables.parquet` is primary table structure while rows and cells are
  evidence anchors.
- Historical workflow files are not the active pipeline order.

Update `backend/application/source/README.md` only enough to clarify that the
application package is collection-build orchestration, not parser ownership.

### Split The Large Runtime File

Move code out of `create_source_artifacts.py` into parser and mapping modules
with the target layout above. Keep imports direct and local. Keep public
artifact names unchanged.

The workflow file should still expose the same runtime behavior:

```text
inventory row
      |
      +-- PDF -> Docling parser -> Source artifact bundle
      |
      +-- text -> plain-text parser -> Source artifact bundle
      |
      v
concat final artifact frames
```

### Defer Workflow Renaming

Do not rename active workflow names in the same change. Names such as
`load_input_documents` and `create_source_artifacts` appear in pipeline
registration, config override paths, logs, and tests.

A later cleanup may rename:

```text
load_input_documents -> load_source_inventory
create_source_artifacts -> build_source_handoff_artifacts
```

That should be a separate commit with direct caller updates and no long-lived
alias unless compatibility is explicitly approved.

## Stable Contracts

The first cleanup must not rename persisted artifacts:

- keep `documents.parquet`
- keep `text_units.parquet`
- keep `blocks.parquet`
- keep `figures.parquet`
- keep `tables.parquet`
- keep `table_rows.parquet`
- keep `table_cells.parquet`
- keep `image_assets/`

It must also preserve the Source/Core ownership boundary:

- Source emits structure, locators, parser-derived table matrices, captions,
  headings, pages, boxes, and asset paths.
- Core decides table routing, target rows, samples, methods, measurements,
  baselines, comparisons, and evidence cards.

No Source-generated table description, figure description, sample label, or
scientific claim should become a Core fact without Core extraction.

## Verification

The refactor should be verified with the smallest checks that cover the moved
code:

```bash
cd backend
./.venv/bin/python -m pytest tests/unit/services/test_source_evidence_workflows.py
./.venv/bin/python -m pytest tests/unit/services/test_materials_comparison_v2_contracts.py
```

If the cleanup also changes docs or README files, run:

```bash
python3 scripts/check_docs_governance.py
```

If the workflow names are later renamed, add tests that cover pipeline
registration and collection build task execution before committing that
separate change.

## Risks

The main risk is accidental behavior drift while moving code. Keep the first
change mechanical and avoid changing parser heuristics, artifact schemas, or
Core extraction behavior.

A second risk is retaining historical workflow files without explanation. The
Source infrastructure README should name the active path clearly so readers do
not infer runtime order from file names alone.

The workflow rename should stay deferred until the runtime split is stable.
Renaming too early would mix readability cleanup with pipeline configuration
and log semantics.
