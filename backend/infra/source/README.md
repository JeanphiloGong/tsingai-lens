# Source Infrastructure

## Purpose

Source turns one uploaded file into an observable `SourceDocument` that Core can
inspect and cite. It parses structure; it does not infer materials, variables,
measurements, comparisons, or Findings.

## Current Flow

```text
Document bytes
  -> load_input_documents
  -> create_source_artifacts
  -> SourceArtifactBundle
  -> SourceDocument
```

`SourceArtifactBundle` is the parser interchange type. The Document preparation
service converts and persists its output as the current Source aggregate owned
by the same `document_id`. There is no collection-wide Source snapshot and no
`build_id` in Source reads or writes.

A parser failure is technical failure for that Document. It does not claim that
the paper lacks scientific evidence, and it does not block preparation or
research over other ready Documents.

## Source Artifacts

- `documents`: document metadata and parsed text.
- `text_units`: bounded text windows for extraction and traceback.
- `blocks`: reading-order text with heading and page context.
- `figures`: caption, page, object metadata, and stable references.
- `tables`: complete normalized table matrix, Markdown, caption, and headers.
- `table_rows`: row-level extraction and traceback anchors.
- `table_cells`: cell coordinates, header paths, units, spans, and stable IDs.

Complete normalized Markdown is preferred for model and reader context. An
oversized table may be divided only into continuous row slices with its caption
and complete flattened header repeated. This analysis-local repair never
overwrites the current Source table.

## Key Areas

- `config/`: parser runtime configuration.
- `contracts/`: artifact schema columns.
- `runtime/workflows/`: registered Source workflow entrypoints.
- `runtime/parsers/`: PDF and text parsers.
- `runtime/mapping/`: conversion into Source records.
- `runtime/storage/` and `runtime/cache/`: disposable runtime support.

Related authorities:

- [`../../application/source/README.md`](../../application/source/README.md)
- [`../../domain/source/README.md`](../../domain/source/README.md)
- [`../../docs/architecture/persistence-model.md`](../../docs/architecture/persistence-model.md)
