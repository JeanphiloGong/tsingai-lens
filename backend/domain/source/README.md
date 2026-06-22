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
- `SourceDocumentTree`
- `SourceArtifactSet`

The domain layer owns semantics such as heading paths, caption proximity,
complete table rendering, table row construction, unit hints, and stable Source
table ids.

`SourceArtifactSet` is the collection-level aggregate passed to Source artifact
repositories when a build replaces a collection's document-structure handoff.
`SourceDocumentTree` is a per-document projection over those same artifacts. It
groups headings, paragraphs, tables, figures, captions, and reference-list
entries into parent/child section nodes for downstream Core consumers.
Reference-list entries remain citation metadata for the current document; if a
cited paper is crawled and parsed later, it should become its own
`SourceDocumentTree` and be linked by reference metadata rather than embedded as
content inside the citing document tree.

## Boundaries

Source domain code must not depend on parser libraries, pandas, storage files, PDF
cropping, Docling objects, or storage implementations. Those details belong to
`backend/infra/source/`.

Infrastructure code parses inputs and persists artifacts. When it needs to
create Source handoff rows, it should construct these domain records first.
SQLite repositories persist these records directly; storage layout details are
not the Source business model.

## Related Infrastructure

- `backend/infra/source/runtime/parsers/`
  Parser-specific bundle builders.
- `backend/infra/source/runtime/mapping/`
  Parser-output mapping into Source domain records and artifact rows.
- `backend/infra/source/contracts/`
  Persisted artifact field ordering and schema metadata.
