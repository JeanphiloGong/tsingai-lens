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
  -> build PaperMap
  -> status=ready + preparation_fingerprint
```

`DocumentPreparationService` is the single owner of this sequence. It prepares
different Documents concurrently while allowing at most one active preparation
task for the same Document. Failure updates only that Document and task.

## Files

- `collection_service.py`: Collection and current Document lifecycle, upload,
  source archive, and preparation-state updates.
- `document_preparation_service.py`: Source/Profile/PaperMap sequence,
  concurrency, fingerprinting, and failure handling.
- `task_service.py`: persisted per-document task admission, progress, and reads.
- `artifact_input_service.py`: current Source loading for downstream consumers.
- `document_markdown_service.py`: display Markdown from the current Source tree.
- `reference_extraction_service.py`: deterministic references from one prepared
  Document.

The parser implementation lives in [`../../infra/source/README.md`](../../infra/source/README.md).
Scientific Objective analysis lives in [`../core/objectives/README.md`](../core/objectives/README.md).
