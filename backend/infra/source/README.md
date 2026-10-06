# Source Infrastructure

## Purpose

Source turns one uploaded file into an observable `SourceDocument` that Core can
inspect and cite. It parses structure; it does not infer materials, variables,
measurements, comparisons, or Findings.

## Current Flow

```text
Document bytes
  -> build_source_artifacts
  -> PDF or plain-text parser
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

`DocumentPreparationService` owns user-visible preparation progress through
`PipelineRunService`. The Source parser returns the bundle directly and raises
parsing errors to that service. It has no workflow registry, factory, or generic
pipeline runner. Its scratch output includes the seven artifact tables and
figure bytes; `context.json` records input and document failures for the current
parse, and `stats.json` records document count and elapsed time. These files do
not control preparation state or retries.

Preparation reuses persisted Source and Profile artifacts through their
fingerprints in `DocumentPreparationService`. Parsing has no cache.

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

- `ingestion/upload_validation.py`: UTF-8, PDF readability, and supported upload
  type checks before original-file storage; it does not construct import models
  or parsed Source artifacts.
- `config/source_parser_config.py`: parser configuration.
- `contracts/`: artifact schema columns.
- `input_inventory.py`: loads the configured document inventory.
- `artifact_bundle.py`: parser output exchanged with the application layer.
- `build_source_artifacts.py`: direct parsing and scratch-output entrypoint.
- `parsers/`: PDF and text parsers, including text chunking and normalization.
- `mapping/`: conversion into Source records.
- `storage/`: file-backed scratch storage for parser input and output.

Logging is configured by the application logger. Source parsing uses module
loggers and does not install its own handlers or logging namespace configuration.

Related authorities:

- [`../../application/source/README.md`](../../application/source/README.md)
- [`../../domain/source/README.md`](../../domain/source/README.md)
- [`../../docs/architecture/persistence-model.md`](../../docs/architecture/persistence-model.md)
