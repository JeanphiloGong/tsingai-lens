# Backend Module Overview

## Purpose

The backend turns uploaded papers into traceable document-level preparation and
then performs research only over papers the researcher explicitly selects.

## Start Here

Read this page first, then follow the first entry point that matches the task:

| Research step | First code entry point | Reads | Calls the LLM | Persists |
|---|---|---|---|---|
| Upload a paper | `controllers/source/collections.py:upload_collection_document` | upload bytes | No | Document and original bytes |
| Prepare one paper | `application/source/document_preparation_service.py:queue_document_preparation` | current Document and source file | Profile stage only; Docling parses the PDF | Source, Profile, Pipeline Run |
| Map selected papers | `application/core/objectives/paper_research_map_service.py:build_document_paper_map` | prepared Source, Profile, tree | Extraction and signal reconciliation | None directly; input service stores map |
| Form candidate questions | `controllers/core/research_objectives.py:discover_collection_objectives` | selected ready Documents and Paper Maps | Yes | candidate Objectives |
| Create or confirm a question | `application/core/objectives/objective_authoring_service.py:create_chat_assisted_candidate` or `confirm_objective` | exact candidate or approved arguments | No | Objective |
| Analyze one confirmed question | `controllers/core/research_objectives.py:start_collection_objective_analysis` | frozen Objective and ready Documents | Yes | analysis version, Evidence, Findings |
| Chat or Agent request | `application/chat/session_service.py:post_message_for_user` | Chat trajectory and canonical resources | Yes, when needed | messages, tool calls, approvals |

The normal reading path is:

```text
HTTP controller -> application use case -> repository port -> storage implementation
                         |
                         +-> scientific stage -> model when needed -> grounded records
```

Start with the owning application README before opening a large service file.
Controllers authorize the request and shape HTTP responses; application
services organize work; domain records express scientific objects and their
invariants; infrastructure implements parsing, model access, and repositories.
The scientific meaning belongs to the Core services and analysis stages.

[`../../main.py`](../../main.py) is the assembly point. `create_app()` configures
routes, middleware, and the startup lifecycle. On startup,
`build_application_runtime()` constructs repositories and services;
`install_application_runtime()` exposes them on `app.state` to controllers.
Startup then recovers interrupted work before serving requests. Start there to
understand construction, not to add scientific rules. Start with the owning
service to change an existing behavior.

For Paper Maps, read `PaperResearchMapService` as the coordinator. It orders
Source selection, bounded extraction, optional expansion, reconciliation, and
status assessment. `paper_map_sources.py` selects Sources and builds windows;
`paper_map_extraction.py` performs model calls, structured-output recovery, and
window-result normalization; `paper_map_aggregation.py` owns merging, signal
reconciliation, and map status. This separation is structural: the scientific
selection rules and persisted Paper Map contract remain unchanged.

## Find The Modification Point

| Your question | Read next |
|---|---|
| How does a file become a ready paper? | [Source](../../application/source/README.md) |
| How are questions discovered, created, and confirmed? | [Objectives](../../application/core/objectives/README.md) |
| Why did a Source become Evidence, or fail to support a Finding? | [Analysis](../../application/core/objectives/analysis/README.md) |
| Why did the Agent read a tool, ask permission, or stop? | [Chat](../../application/chat/README.md) |
| Where are records stored and reloaded? | [Persistence model](persistence-model.md) |
| Which test should accompany my change? | [Backend tests](../../tests/README.md) |

Read the module's entry method, its result type, and its nearest scenario test
before editing. A new capability needs a handler, registry entry, and policy;
a changed scientific stage needs its owner and checkpoint-version review. There
is no second implementation for Agent callers. Public HTTP contracts remain in
[`../specs/api.md`](../specs/api.md), not in duplicated module schemas.

For a first change, follow one paper all the way through the owning scenario
test before editing. For example, a broken table layout starts in
`analysis/table_repair.py` and its P004 table regressions, not in Finding
synthesis. Record the current result, change that owner, run its focused tests,
then run the four-paper integration flow. The test guide below each module
identifies the command and any database prerequisites. API, stored-record, and
scientific-rule changes require their own explicit contract review; a code move
alone should not alter them.

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

For example, a researcher asks whether build-platform preheating changes steel
elongation. One paper's tensile table reports the values; Methods identifies
the preheated and non-preheated specimens. Analysis must inspect and ground
both before binding them. A review of the same topic is a citation lead, not an
independent measurement. The researcher can inspect the resulting Source links
and decide whether missing controls warrant another question or a research plan.

Preparation stops at readiness. Explicit selection starts discovery or analysis;
discovery does not authorize analysis. A user-supplied question may bypass
candidate discovery. For Agent writes, exact user approval is required before
execution. Successful analysis publication is automatic; expert review is a
separate human action.

Technical retries, JSON repair, and provider limits support these steps but do
not become scientific states.

## Ownership

```text
Collection
  -> current Documents

Document
  -> one active preparation Pipeline Run at most
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
- [`application/repositories/`](../../application/repositories/README.md) owns
  storage contracts and repository-specific query results. Domain objects do
  not depend on those contracts.
- `infra/` owns PostgreSQL, object storage, model providers, and parsing.

PostgreSQL stores structured current state and analysis history. Object storage
stores uploaded and extracted bytes. Local files are disposable runtime scratch.

## Concurrency And Reuse

- One queued or running `document_preparation` Pipeline Run may exist per
  Document scope.
- Different Documents may prepare concurrently; the default process-local limit
  is `10`.
- A queued or running run is reused even if a caller asks again.
- A completed preparation run is reused only when its input fingerprint still matches the
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

- queued or running Document preparation runs become failed with the
  `interrupted` node; a Document left in `processing` returns to `stored`, while
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
