# Backend Module Overview

## Purpose

The backend turns uploaded papers into traceable document-level preparation and
then performs research only over papers the researcher explicitly selects.

## Real-World Chain

For a materials researcher comparing how a process variable affects an outcome:

1. Add candidate papers to a Collection.
2. Prepare each paper independently into readable Source structure, a coarse
   DocumentProfile, and a bounded PaperMap.
3. Inspect readiness and select the papers relevant to the current question.
4. Discover candidate Objectives from that exact ready-paper selection, or use
   a researcher-authored Objective.
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
  -> current PaperMap

Objective discovery
  -> exact selected ready Documents

ObjectiveAnalysis
  -> frozen document_id + preparation_fingerprint inputs
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

## Related Docs

- [`persistence-model.md`](persistence-model.md)
- [`../specs/api.md`](../specs/api.md)
- [`../../application/source/README.md`](../../application/source/README.md)
- [`../../application/core/objectives/README.md`](../../application/core/objectives/README.md)
