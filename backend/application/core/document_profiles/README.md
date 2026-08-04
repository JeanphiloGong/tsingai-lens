# Document Profiles

This package owns collection-time document classification and bounded profile
summaries derived from normalized Source artifacts.

## Owner

- `service.py`
  Builds and reads `DocumentProfile` records and the collection profile
  summary used by downstream Core workflows.

## Boundary

Document profiles describe document role and available content. They do not
discover research Objectives, extract paper facts, synthesize Findings, or own
HTTP and persistence implementations.
