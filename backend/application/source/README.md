# Source Application Layer

This package owns Collection lifecycle, current Document membership, and
one-Document preparation orchestration.

## Start Here

- HTTP upload: `controllers/source/collections.py:upload_collection_document`
- Import implementation: `SourceImportService.add_document()`
- External import: `SourceImportService.import_from_adapter()`
- Queue preparation: `DocumentPreparationService.queue_document_preparation()`
- Execute preparation: `DocumentPreparationService.run_document_preparation()`
- Read prepared Source: `ArtifactInputService`

The preparation input is one stored Document. The output is the current
`SourceDocument`, its `DocumentProfile`, and a `ready` Document status. PDF
parsing uses Docling; Profile classification calls the configured LLM. Collection
and Document membership do not call the LLM. This package owns Pipeline Run progress for this
flow; it does not form Objectives or create Evidence.

## Boundary Checklist

| Concern | Owner | Persistent result |
|---|---|---|
| Collection and Document membership | `collection_service.py` | Collection/Document records |
| Upload and external import | `source_import_service.py` | stored Document records |
| Source/Profile preparation | `document_preparation_service.py` | Source artifact, Profile, run |
| Display Markdown | `document_markdown_service.py` | none |
| References | `reference_extraction_service.py` | Source references |
| Original-file archive | `source_archive_service.py` | temporary download only |

When changing this package, begin with the single-document flow and preserve
the storage keys, fingerprints, task states, and controller response shapes.

## Main Flow

```text
upload Document
  -> status=stored
  -> queue one document_preparation Pipeline Run
  -> parse Source
  -> build DocumentProfile
  -> status=ready; preparation fingerprint comes from DocumentProfile

selected ready Documents
  -> build or reuse a lightweight PaperMap for Objective discovery
```

`DocumentPreparationService` owns the upload-time sequence through Source and
DocumentProfile. It prepares different Documents concurrently while allowing at
most one active preparation run for the same Document. Failure updates only
that Document and run; input loading preserves skipped-file failures in the
pipeline trace, and reference extraction warnings do not invalidate a
successfully parsed Source. PaperMap construction is owned by the Objective core
and is lazy: discovery or analysis builds it only for the explicitly selected
ready Documents, then reuses it while its document and PaperMap policy
fingerprint still match.

A technical Profile classification failure keeps the parsed Source readable,
leaves the Document `stored`, and finishes its run as `partial_success` with a
failed classification node and a retryable warning. Only a completed Profile
makes the Document `ready`. Retrying checks the actual Source and Profile as
well as their fingerprints, so historical completed runs cannot hide a failed
classification. A completed but scientifically uncertain Profile is reusable.

## Files

- `collection_service.py`: Collection and current Document lifecycle, Figure
  assets, and preparation-state updates.
- `source_import_service.py`: Upload normalization, adapter imports, object
  storage writes, and Document registration.
- `source_archive_service.py`: Original-file lookup and bounded reproduction
  archives. It verifies stored bytes but does not change Collection state.
- `document_preparation_service.py`: Source/Profile preparation sequence,
  concurrency, fingerprinting, and failure handling.
- `artifact_input_service.py`: current Source loading for downstream consumers.
- `document_markdown_service.py`: display Markdown from the current Source tree.
- `reference_extraction_service.py`: deterministic references from one prepared
  Document.

The parser implementation lives in [`../../infra/source/README.md`](../../infra/source/README.md).
Scientific Objective analysis lives in [`../core/objectives/README.md`](../core/objectives/README.md).

## Changing This Module

For upload or external import behavior, start with `SourceImportService`.
For reproduction downloads, start with `SourceArchiveService`. For readiness,
retry, or stage reuse, start with `DocumentPreparationService`; its fingerprints
decide which existing artifacts can be reused. Do not put these responsibilities
back into `CollectionService` or reproduce them in an Agent capability.

The HTTP handler checks the authenticated user's Collection ownership. A
background preparation task inherits the existing request trace context, even
after the request returns; it does not accept a separate unused request ID.
Preparation failure leaves that Document retryable and does not imply a paper
lacks scientific evidence. Success only makes it eligible for later selected
Objective work; preparation does not start discovery automatically.

Dispatch and startup failures share the execution failure boundary. Document
and run failure writes are attempted independently; a secondary database error
is logged without replacing the original failure. If storage remains unavailable,
restart recovery handles the surviving active record. Public run errors use
stage-specific wording, including for historical records; original exceptions
remain in internal logs linked by run ID.

## Tests

From `backend/`, run:

```bash
.venv/bin/python -m pytest -q tests/unit/services/test_collection_service.py tests/unit/services/test_document_preparation_service.py tests/integration/test_app_layer_api.py
```

These cases cover upload and adapter import, original-byte archive retrieval,
partial preparation failure, stage reuse, and HTTP responses. Parser-specific
tests live under `tests/unit/infra/source/`; fixture and database setup are
described in [`../../tests/README.md`](../../tests/README.md).
