# Source Application Layer

This package owns Collection lifecycle, current Document membership, and
one-Document preparation orchestration.

## Start Here

- HTTP upload: `controllers/source/collections.py:upload_collection_document`
- Queue preparation: `DocumentPreparationService.queue_document_preparation()`
- Execute preparation: `DocumentPreparationService.run_document_preparation()`
- Read prepared Source: `ArtifactInputService`

The preparation input is one stored Document. The output is the current
`SourceDocument`, its `DocumentProfile`, and a `ready` Document status. Source
parsing and profile classification may call the model, but Collection and
Document membership do not. This package owns Pipeline Run progress for this
flow; it does not form Objectives or create Evidence.

## Boundary Checklist

| Concern | Owner | Persistent result |
|---|---|---|
| Collection and Document membership | `collection_service.py` | Collection/Document records |
| Source/Profile preparation | `document_preparation_service.py` | Source artifact, Profile, run |
| Display Markdown | `document_markdown_service.py` | none |
| References | `reference_extraction_service.py` | Source references |
| Original-file archive | `collection_service.py` | temporary download only |

When changing this package, begin with the single-document flow and preserve
the storage keys, fingerprints, task states, and controller response shapes.

## Main Flow

```text
upload Document
  -> status=uploaded
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

## Files

- `collection_service.py`: Collection and current Document lifecycle, upload,
  source archive, and preparation-state updates.
- `document_preparation_service.py`: Source/Profile preparation sequence,
  concurrency, fingerprinting, and failure handling.
- `artifact_input_service.py`: current Source loading for downstream consumers.
- `document_markdown_service.py`: display Markdown from the current Source tree.
- `reference_extraction_service.py`: deterministic references from one prepared
  Document.

The parser implementation lives in [`../../infra/source/README.md`](../../infra/source/README.md).
Scientific Objective analysis lives in [`../core/objectives/README.md`](../core/objectives/README.md).
