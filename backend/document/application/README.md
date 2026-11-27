# Document Profiles

This package owns workspace-time document classification and bounded profile
summaries derived from normalized Source artifacts.

## Owner

- `service.py`
  Builds and reads `DocumentProfile` records and the workspace profile
  summary used by downstream Core workflows.
- `extraction.py`
  Calls the configured model provider and owns document-profile completion
  limits, retry behavior, extraction traces, the document-triage prompt, and
  its validated model output contract.

## Prompt contract

The `document_profile.v2` system prompt performs one bounded navigation
classification. It asks the model to choose `doc_type` from `experimental`,
`review`, `mixed`, or `uncertain`, then write a short `description` grounded in
the supplied title, lead text, and headings. The prompt explicitly forbids
inferring experimental findings or evidence from navigation material. The
`uncertain` value is used when the document role cannot be established from
the supplied Source excerpt.

The model output is strict JSON with exactly these fields:

```json
{
  "doc_type": "experimental",
  "description": "A short source-grounded description of the document."
}
```

The extractor validates this contract before the preparation pipeline creates a
persisted `DocumentProfile`. Fingerprints, version, and generation time are
assigned by the application after extraction and are never model output.

## Boundary

Document profiles describe document role and available content. They do not
discover research Objectives, extract paper facts, synthesize Findings, or own
HTTP and persistence implementations.

`doc_type=uncertain` describes a completed but unresolved scientific
classification. Model extraction failures are surfaced as preparation failures
and remain retryable. They are not evidence that the document itself is
scientifically uncertain.

Single-paper content and Profile reads query the selected document directly.
An empty Source workspace remains a not-ready response; a missing document in
a workspace with prepared Sources remains not-found. The existence check does
not load other papers' artifacts.

Classification consumes `SourceDocument` directly and returns `DocumentProfile`.
Metadata aliases are resolved from the normalized Source metadata; this layer
does not parse metadata strings or rebuild generic document rows. Text-unit,
block, title, and filename fallbacks remain part of the reader contract.
