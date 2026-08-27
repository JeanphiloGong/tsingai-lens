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

The domain layer owns semantics such as heading paths, caption proximity,
complete table rendering, table row construction, unit hints, and stable Source
table ids. Complete tables preserve the parser's header-row count and logical
cell spans. Their Markdown projection uses flattened header paths once and
keeps every data row in Source order.

`SourceDocument` is the parsed-document aggregate. It owns its text units,
blocks, tables, table rows, table cells, and figures. `text_unit_ids` is derived
from the owned text units rather than stored as a second source of truth.

Collection records own current Document membership. Document preparation passes
one `SourceDocument` aggregate to the Source repository, where it replaces that
Document's current parsed structure. There is no collection-wide artifact
aggregate or Source build identity in the domain.

`SourceDocumentTree` is a per-document projection over one `SourceDocument`.
It groups headings, paragraphs, tables, figures, captions, and reference-list
entries into parent/child section nodes for downstream Core consumers.
Tables and figures use an exact heading-path match when available. If a parser
supplies an unusable path, they bind to the nearest preceding non-reference
section by page; without page evidence they remain at the document root rather
than inheriting the final section visited while the tree was built.
Reference-list entries remain citation metadata for the current document; if a
cited paper is crawled and parsed later, it should become its own
`SourceDocumentTree` and be linked by reference metadata rather than embedded as
content inside the citing document tree.

## Boundaries

Source domain code must not depend on parser libraries, pandas, storage files, PDF
cropping, Docling objects, or storage implementations. Those details belong to
`backend/infra/source/`.

Infrastructure code parses inputs and persists artifacts. Parser runtimes may
use flat tables as an interchange format, but they must assemble those rows
into `SourceDocument` aggregates at the application boundary. Assembly rejects
duplicate documents and artifacts whose owning document is missing. PostgreSQL
may normalize aggregates into separate tables; storage layout details are not
the Source business model. Memory repositories exist only for isolated tests.

## Related Infrastructure

- `backend/infra/source/runtime/parsers/`
  Parser-specific bundle builders.
- `backend/infra/source/runtime/mapping/`
  Parser-output mapping into Source domain records and artifact rows.
- `backend/infra/source/contracts/`
  Persisted artifact field ordering and schema metadata.
