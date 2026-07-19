# Source Infrastructure

## Purpose

This package owns the backend Source infrastructure. Source turns collection
input files into observable document-structure artifacts that Core can inspect
and cite.

The Source business records and shared structure logic live in
`backend/domain/source/`. Infrastructure should parse input files, build those
domain records, and serialize them into the persisted artifact tables.
The SQLite Source artifact repository is the structured persistence path; local
exports and traces are derived from that repository.

Source does not extract scientific facts. It does not decide materials,
samples, methods, measurements, baselines, comparisons, or report content.
Those semantic decisions belong to Core and downstream layers.

## Main Flow

The active Source runtime pipeline is:

```text
load_input_documents
      |
      v
create_source_artifacts
```

`load_input_documents` scans the configured input storage and writes a source
inventory. `create_source_artifacts` reads that inventory, parses each PDF or
text document, and writes the final Source handoff artifacts.

After Source finishes, `application/source` starts Core post-processing:

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
```

## Source Artifacts

The final Source artifact family persisted in the Source repository is:

- `documents`
  Document records, source metadata, full text, and text-unit ids.
- `text_units`
  Text windows used by Core extraction and traceback.
- `blocks`
  Reading-order blocks with block type, heading path, page, bbox, and
  character range. Text contained within a figure region is represented by the
  figure artifact instead of being duplicated as body blocks.
- `figures`
  Figure rows with captions, heading context, page, bbox, image asset paths,
  and parser metadata.
- `tables`
  The primary complete-table structure with caption, heading, page, bbox,
  headers, `table_matrix`, Markdown, and plain text.
- `table_rows`
  Row-level evidence anchors for table-grounded extraction and traceback.
- `table_cells`
  Cell-level evidence anchors with header paths, unit hints, row and column
  indexes, page, and bbox.
- `image_assets/`
  Extracted figure crops referenced by Source figure rows.

`tables` is the primary table context. `table_rows` and `table_cells` support
anchoring, UI drilldown, and debugging; they are not replacements for the
complete table artifact.

## Key Areas

- `config/`
  Runtime configuration models.
- `contracts/`
  Artifact schema column definitions.
- `ingestion/`
  Pre-Core upload, connector, and collection import normalization.
- `runtime/workflows/`
  Registered Source pipeline workflow entrypoints.
- `runtime/parsers/`
  Parser-specific bundle builders for PDF and plain-text inputs.
- `runtime/mapping/`
  Mapping from parser output into Source domain records and persisted artifact
  rows.
- `runtime/storage/`
  Runtime scratch table storage.
- `runtime/cache/`
  Runtime cache implementations.

Historical workflow helper files may still exist under `runtime/workflows/`.
Do not infer active runtime order from file names alone; use the registered
pipeline in `runtime/workflows/factory.py`.

## Related Docs

- [`../../docs/plans/source/source-structure-first-substrate-plan.md`](../../docs/plans/source/source-structure-first-substrate-plan.md)
- [`../../docs/plans/source/source-table-artifact-plan.md`](../../docs/plans/source/source-table-artifact-plan.md)
- [`../../docs/plans/source/source-runtime-organization-plan.md`](../../docs/plans/source/source-runtime-organization-plan.md)
