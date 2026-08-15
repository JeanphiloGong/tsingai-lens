# Source Infrastructure

## Purpose

This package owns the backend Source infrastructure. Source turns collection
input files into observable document-structure artifacts that Core can inspect
and cite.

The Source business records and shared structure logic live in
`backend/domain/source/`. Infrastructure should parse input files, build those
domain records, and return one `SourceArtifactBundle` to the application build
pipeline. The build pipeline persists document structure to build-versioned
PostgreSQL rows, writes extracted figure bytes through the existing object
store, and persists figure metadata plus deterministic references under the
same pending build before activation.

`SourceArtifactBundle` is a parser interchange type backed by data frames. It
is not a domain aggregate. Before persistence, the application converts each
bundle into `SourceDocument` aggregates, with every block, table, row, cell,
text unit, and figure attached to its owning document.

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
inventory. `create_source_artifacts` reads that inventory and parses each PDF
or text document. It does not construct a repository or persist authoritative
rows; the application Source node persists its returned bundle with the pending
collection `build_id`.

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

The final Source artifact family is:

- `documents`
  Document records, source metadata, and full text. In the domain handoff each
  document owns the parsed structures listed below.
- `text_units`
  Text windows used by Core extraction and traceback.
- `blocks`
  Reading-order blocks with stable block IDs, block type, heading path, and
  page. Text contained within a figure region is represented by the figure
  artifact instead of being duplicated as body blocks.
- `figures`
  Figure rows with stable figure IDs, captions, heading context, page, immutable object key,
  SHA-256, MIME type, dimensions, byte size, and parser metadata.
- `tables`
  The primary complete-table structure with stable table IDs, caption, heading, page,
  headers, `table_matrix`, Markdown, and plain text.
- `table_rows`
  Row-level evidence anchors for table-grounded extraction and traceback.
- `table_cells`
  Cell-level evidence anchors with header paths, unit hints, row and column
  indexes, page, and stable cell IDs.
- `image_assets/`
  Parser scratch crops handed to the application pipeline. Product reads use
  the registered object key and never depend on this directory.

`tables` is the primary table context. `table_rows` and `table_cells` support
anchoring, UI drilldown, and debugging; they are not replacements for the
complete table artifact.

Parser adapters may inspect PDF geometry privately to exclude text embedded in
figures or crop figure images. Geometry is not a Source domain field, persisted
artifact, evidence locator, or browser contract.

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

- [`../../domain/source/README.md`](../../domain/source/README.md)
  Source domain aggregates and stable artifact identities
- [`../../application/pipeline/collection_build/README.md`](../../application/pipeline/collection_build/README.md)
  Collection build ordering and Source handoff
- [`../../docs/architecture/persistence-model.md`](../../docs/architecture/persistence-model.md)
  Durable Source ownership and build lineage
