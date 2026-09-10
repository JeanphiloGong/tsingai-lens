# Document Profiles

This package owns collection-time document classification and bounded profile
summaries derived from normalized Source artifacts.

## Owner

- `service.py`
  Builds and reads `DocumentProfile` records and the collection profile
  summary used by downstream Core workflows.
- `extraction.py`
  Calls the configured model provider and owns document-profile completion
  limits, retry behavior, and extraction traces.
- `prompts.py` and `schemas.py`
  Define the document-triage prompt and its validated response contract.

## Boundary

Document profiles describe document role and available content. They do not
discover research Objectives, extract paper facts, synthesize Findings, or own
HTTP and persistence implementations.

`doc_type=uncertain` describes a completed but unresolved scientific
classification. `profile_status=extraction_failed` describes a technical model
failure; it must remain visible as a retryable warning and must not be treated
as evidence that the document itself is scientifically uncertain.

Single-paper content and Profile reads query the selected document directly.
An empty Source collection remains a not-ready response; a missing document in
a collection with prepared Sources remains not-found. The existence check does
not load other papers' artifacts.

Classification consumes `SourceDocument` directly and returns `DocumentProfile`.
Metadata aliases are resolved from the normalized Source metadata; this layer
does not parse metadata strings or rebuild generic document rows. Text-unit,
block, title, and filename fallbacks remain part of the reader contract.
