# Source Application Layer

This package owns Collection lifecycle, current Document membership, observable
task state, and one-Document preparation orchestration.

## Main Flow

```text
upload Document
  -> status=uploaded
  -> queue one document_preparation task
  -> parse Source
  -> build DocumentProfile
  -> status=ready + preparation_fingerprint

selected ready Documents
  -> build or reuse a lightweight PaperMap for Objective discovery
```

`DocumentPreparationService` owns the upload-time sequence through Source and
DocumentProfile. It prepares different Documents concurrently while allowing at
most one active preparation task for the same Document. Failure updates only
that Document and task. PaperMap construction is owned by the Objective core
and is lazy: discovery or analysis builds it only for the explicitly selected
ready Documents, then reuses it while its document and PaperMap policy
fingerprint still match.

## Files

- `collection_service.py`: Collection and current Document lifecycle, upload,
  source archive, and preparation-state updates.
- `document_preparation_service.py`: Source/Profile preparation sequence,
  concurrency, fingerprinting, and failure handling.
- `task_service.py`: persisted per-document task admission, progress, and reads.
- `artifact_input_service.py`: current Source loading for downstream consumers.
- `document_markdown_service.py`: display Markdown from the current Source tree.
- `reference_extraction_service.py`: deterministic references from one prepared
  Document.

The parser implementation lives in [`../../infra/source/README.md`](../../infra/source/README.md).
Scientific Objective analysis lives in [`../core/objectives/README.md`](../core/objectives/README.md).
