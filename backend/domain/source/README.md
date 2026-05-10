# Source Domain

## Purpose

This package owns Source business records and Source structure logic.

Source domain models describe the document-structure handoff that Core can
inspect and cite:

- `SourceDocument`
- `SourceTextUnit`
- `SourceBlock`
- `SourceTable`
- `SourceTableRow`
- `SourceTableCell`
- `SourceFigure`

The domain layer owns semantics such as heading paths, caption proximity,
complete table rendering, table row construction, unit hints, and stable Source
table ids.

## Boundaries

Source domain code must not depend on parser libraries, pandas, parquet, PDF
cropping, Docling objects, or storage implementations. Those details belong to
`backend/infra/source/`.

Infrastructure code parses inputs and persists artifacts. When it needs to
create Source handoff rows, it should construct these domain records first and
then serialize them into the existing artifact tables.

## Related Infrastructure

- `backend/infra/source/runtime/parsers/`
  Parser-specific bundle builders.
- `backend/infra/source/runtime/mapping/`
  Parser-output mapping into Source domain records and artifact rows.
- `backend/infra/source/contracts/`
  Persisted artifact column ordering for parquet/json handoff files.
