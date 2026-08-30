# Backend Module Overview

## Purpose

The backend turns uploaded papers into traceable document-level preparation and
then performs research only over papers the researcher explicitly selects.

## Real-World Chain

For a materials researcher comparing how a process variable affects an outcome:

1. Add candidate papers to a Collection.
2. Prepare each paper independently into readable Source structure and a coarse
   DocumentProfile.
3. Inspect readiness and select the papers relevant to the current question.
4. Build or reuse a bounded PaperMap only for that exact ready-paper selection,
   then discover candidate Objectives, or use a researcher-authored Objective.
5. Confirm an Objective and select the ready papers to analyze.
6. Extract Source-backed facts within each paper, reconstruct experiments, and
   preserve missing, failed, and non-comparable cases.
7. Compare compatible evidence across papers and publish Findings with exact
   Source traceback.

Technical retries, JSON repair, and provider limits support these steps but do
not become scientific states.

## Ownership

```text
Collection
  -> current Documents

Document
  -> one active preparation task at most
  -> current SourceDocument
  -> current DocumentProfile
  -> optional current PaperMap (lazy, selected by Objective work)

Objective discovery
  -> exact selected ready Documents

ObjectiveAnalysis
  -> frozen document_id + preparation_fingerprint inputs
  -> per-document Evidence checkpoints
     -> PaperContribution
     -> ObjectiveEvidence
  -> Finding
```

Collections only assemble Documents. Readiness and preparation failures belong
to each Document. One failed or processing Document does not block uploads,
preparation of other Documents, Objective discovery from ready Documents, or
analysis of an explicitly selected ready subset.

## Runtime Boundaries

- `controllers/` parses HTTP and shapes responses.
- `application/source/` owns Collection and Document preparation use cases.
- `application/core/` owns scientific preparation, Objective discovery, and
  Objective analysis.
- `application/chat/` owns conversation, capability trajectory, and approval;
  it references rather than duplicates scientific records.
- `domain/` owns records and invariants.
- `infra/` owns PostgreSQL, object storage, model providers, and parsing.

PostgreSQL stores structured current state and analysis history. Object storage
stores uploaded and extracted bytes. Local files are disposable runtime scratch.

## Concurrency And Reuse

- One queued or running preparation task may exist per Document and task type.
- Different Documents may prepare concurrently; the default process-local limit
  is `10`.
- A queued or running task is reused even if a caller asks again.
- A completed task is reused only when its input fingerprint still matches the
  Document bytes and all preparation-stage versions.
- Source and Profile fingerprints allow a retry or downstream version change to
  resume from the latest valid stage instead of rerunning Docling.
- Objective analysis validates every frozen fingerprint before reading Source.
  A changed or re-prepared Document makes the old analysis input stale and the
  operation fails instead of mixing versions.
- Evidence inspection runs independently for each selected Document with a
  process-local limit of `4`. A matching succeeded checkpoint is reused across
  analysis retries; failed or unfinished inspection is rerun. Findings are
  synthesized once after the selected checkpoint set is assembled.
- Inspection that finds no routable or comparable Evidence is completed
  scientific work and remains reusable. Provider, parsing, and execution errors
  are technical failure and remain retryable.

## Restart Recovery And Scientific Versioning

The process-local background workers are not durable queues. Before the API
starts serving requests, startup recovery converts persisted work that no live
worker can own into retryable state:

- queued or running Document preparation tasks become failed with the
  `interrupted` stage; a Document left in `processing` returns to `stored`, while
  already written Source and DocumentProfile artifacts remain
  available for fingerprinted reuse. Research-facing status projects this
  technical interruption as `not_started` rather than a scientific failure;
- queued or running Objective analyses become failed with
  `analysis_interrupted`; an unpublished interrupted analysis is not projected
  as active work, so the current state is `not_started` until the researcher
  retries it; and
- recovery never resumes a scientific operation from an unknown in-memory
  position and never treats a restart as a scientific absence or conclusion.

Published analyses are immutable readable snapshots. An interrupted or failed
new analysis does not replace the published version. A retry uses the selected
Documents' current preparation fingerprints and the current scientific logic,
then atomically replaces the published version only after the complete analysis
succeeds.

Per-Document Objective Evidence checkpoints are reusable only when their input
fingerprint matches the Objective, Document preparation, model, extraction
version, and the six scientific stages: paper framing, evidence routing, Source
extraction, Source grounding, paper experiment reconstruction, and Evidence
materialization. Changing any of those stage versions invalidates the cached
Evidence for new analysis without making an older published result unreadable.

## Related Docs

- [`persistence-model.md`](persistence-model.md)
- [`../specs/api.md`](../specs/api.md)
- [`../../application/source/README.md`](../../application/source/README.md)
- [`../../application/core/objectives/README.md`](../../application/core/objectives/README.md)
