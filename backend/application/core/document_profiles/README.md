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
