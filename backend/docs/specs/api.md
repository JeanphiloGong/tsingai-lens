# API Contract

This document describes the maintained Lens v1 HTTP contract. The generated
OpenAPI document at `/api/openapi.json` is the field-level runtime reference;
this file owns resource boundaries and cross-endpoint semantics.

## Conventions

- Product APIs use `/api/v1/*`.
- API documentation uses `/api/docs`, `/api/redoc`, and `/api/openapi.json`.
- `POST /api/v1/auth/login` establishes an HttpOnly session cookie. Browser
  requests send that cookie through the same-origin `/api/v1/*` contract.
- Every business response carries `X-Request-ID`.
- A collection is the primary working scope; a document is a source inside it.
- PostgreSQL is the structured runtime authority.
- GET requests never trigger LLM analysis.
- Retired payloads and endpoints are not accepted through aliases or fallback
  parsers.

## Resource Map

### Authentication

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Invalid credentials return `401`. A missing or expired session cookie also
returns `401`; the frontend clears local auth state and returns the user to
login.

### Collections, Files, And Builds

- `GET /api/v1/collections`
- `POST /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `GET /api/v1/collections/{collection_id}/files`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/tasks`
- `POST /api/v1/collections/{collection_id}/tasks/build`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/collections/{collection_id}/workspace`

Collection build parses Source, creates document profiles and reusable paper
facts, and discovers Objective candidates. It does not run confirmed Objective
deep analysis. Task responses expose current stage, progress, terminal error,
and retry-appropriate status; a failed task is never presented as a new task.
The task artifact registry reports only persisted Source artifacts (documents,
blocks, figures, table rows, and table cells). Workspace document-profile and
Objective readiness is derived from their owning repositories rather than
duplicated into the task artifact registry.
The build request accepts `mode: standard | fast` and defaults to `standard`.
The selected mode is persisted before dispatch and determines the runtime
dependency graph for that task.

### Goal Intake

- `POST /api/v1/goals/intake`

Goal intake seeds a collection; it is not a second research-result identity.

### Research Agent Chat

- `POST /api/v1/chat-sessions`
- `GET /api/v1/chat-sessions/{session_id}`
- `GET /api/v1/chat-sessions/{session_id}/messages`
- `POST /api/v1/chat-sessions/{session_id}/messages`
- `POST /api/v1/chat-sessions/{session_id}/tool-calls/{tool_call_id}/decision`

Chat is the independent conversation and Agent trajectory owner. A Chat session
belongs to one authenticated user and one collection. Its ordered messages
record ordinary user and assistant conversation, model tool intent, and bounded
structured tool results. Chat references Core resources through stable resource
references; it does not own or duplicate Objective, Evidence, Finding, or
Analysis records.

An ordinary message may return a final answer without calling a tool. Registered
`read` and `draft` calls may execute automatically. A `write` call stops at
`approval_required` before execution. The decision request must submit the
stored 64-character `arguments_digest`; approval is bound to the tool call,
exact stored arguments, authenticated user, and decision timestamp. Changed
arguments, another user, or an incompatible call state return `409` or `404`
and never execute the call. Rejection records a tool result and does not execute
the capability. While a write remains `approval_required`, posting another
message to that session returns `409 chat_tool_approval_pending`; the user must
approve or reject the exact pending action before starting another turn.

The production Research Agent currently exposes these automatic capabilities:

- `get_collection_context` returns a bounded collection and Objective overview;
- `query_published_findings` returns bounded Finding and Evidence summaries
  only from published Objective analysis versions; an empty successful result
  is a scientific absence, not a provider failure;
- `propose_objective_drafts` records at most three focused, single-outcome
  drafts in the Chat trajectory. PaperSkim relationships may be reported as
  proposal context, but they are never presented as Evidence and this call does
  not persist, confirm, analyze, or publish a Core Objective;
- `create_objective_candidate` is a `write` capability. After exact-argument
  approval, it creates one unconfirmed `chat_assisted` Core candidate supported
  by PaperSkim relationship context. It never confirms the Objective or starts
  analysis. Repeating the same approved tool call is idempotent.

Model context is a bounded recent suffix of the durable trajectory. An
assistant tool call and its following tool result are retained or omitted as one
protocol unit, so context trimming never sends an orphan tool result to the
provider.

The server checkpoints the user message before the first model request, then
checkpoints model tool intent, running call state, structured tool results, and
the final assistant answer as separate append-only transitions. A process
interruption therefore cannot erase an already requested action or make an
approved write appear never to have started.

Turn status is one of `completed`, `approval_required`,
`step_limit_reached`, `failed`, or `rejected`. Tool call and result failures are
technical trajectory outcomes; they are not scientific absence, uncertainty,
or Evidence status. Provider response objects and internal exceptions are not
part of the public contract. Reaching the step limit appends a final assistant
message that explains how the researcher can continue; the trajectory never
ends on an opaque tool message alone.

Tool result status is `succeeded`, `queued`, or `failed`. A `queued` result is a
successful asynchronous handoff, must include at least one canonical resource
reference, and does not make the Agent wait for task completion. The final
assistant response tells the researcher that work started and where its state
can be inspected.

### Research Objectives

- `GET /api/v1/collections/{collection_id}/objectives`
- `GET /api/v1/collections/{collection_id}/paper-study-inventory`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/confirm`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`

`ResearchObjective` is the only business aggregate root. Its identity is
`(collection_id, objective_id)`. The Objective response contains:

- question and material/process/property/comparison scope;
- included and excluded document IDs;
- `confirmation_status`: `candidate | confirmed`;
- `active_analysis_version` and `published_analysis_version`;
- `origin`: `system_discovered | chat_assisted`, plus the immutable
  `source_build_id` and Chat creator provenance for an assisted candidate;
- ordered `source_relationship_ids` linking the Objective to paper-study
  relationships;
- `active_analysis`, `published_analysis`, analysis-level
  `paper_contributions`, and warnings on detail responses.

The Objective list places active generated candidates in persisted
collection-build rank, followed by durable Chat-assisted candidates in creation
order. Assisted candidates remain visible across later collection rebuilds and
retain the Source build inspected when the user approved them. The list supports
`offset` and optional `limit`. When `limit` is omitted, the response contains
every Objective from `offset` onward so lower-ranked candidates remain visible
without client pagination. An explicit `limit` applies ordinary pagination. The
response contains `total`, `offset`, and the applied `limit` (`null` when
omitted), and each Objective contains its one-based `rank`. Rank is for
researcher prioritization and never removes a paper-study relationship from the
persisted inventory.

The paper-study inventory reads the active persisted Objective build and
supports `offset` and `limit`. Its response contains `total`, `offset`, `limit`,
`research_objectives_ready`, and a mixed `items` sequence containing:

- one `paper_study` entry for each paper-local experiment, observation, or
  modeling study, including design, claim scope, material/process/sample/test
  context, comparator, and fixed conditions;
- every study relationship as one complete jointly varied factor set and one
  outcome with exact `source_kind + source_ref` locators; supported kinds are
  `document`, `block`, `table`, `table_row`, and `figure`, and `table_row`
  references the persisted Source `row_id` rather than its enclosing table;
- each relationship's `pending | promoted | rejected` disposition, linked
  Objective id for promoted relationships, or explicit backend-derived reason
  for rejection; the discovery model does not reject relationships, and a
  relationship too large for model labeling uses a backend-built standalone
  Objective fallback;
- one `unresolved_signal` entry for every source-backed variable or outcome
  that could not yet form a defensible relationship, preserving the same study
  context, exact Source locators, confidence, and reason;
- one `source_unit_coverage` entry for every eligible first-stage Source unit,
  preserving `source_unit_id`, `window_id`, exact Source kind/reference, and one
  of `relationship_emitted`, `unresolved_signal_emitted`, `no_study_signal`, or
  backend-derived `extraction_failed`.

The inventory is a typed audit projection of `ObjectiveFactSet`; it is not a
second aggregate and does not trigger extraction, grouping, or analysis.
First-stage Source windows split rather than truncate scientific text, table
metadata, or figure captions. Cross-window reconciliation may receive bounded
excerpts, while the persisted signal keeps its complete structured fields and
exact Source locator; failure leaves the signal unresolved. The inventory still
does not guarantee that the first-stage LLM extracted every source-supported
study or relationship, so it is complete for extracted records rather than proof
of complete paper interpretation. `source_unit_coverage_counts` always contains
all four status counts. `coverage_complete` is `false` when any window produced
`extraction_failed`; `true` means every eligible Source unit received a
contract-valid first-stage outcome. It measures extraction execution, not
scientific recall, relevance certainty, or systematic-review completeness.

`ObjectiveAnalysis` is addressed by the Objective identity plus a positive
`analysis_version`. It contains immutable Source/pipeline/model/prompt lineage,
`queued | running | succeeded | failed` status, phase, document progress,
current document, terminal error, timestamps, and provider-reported execution
`stats`. Statistics include duration, request counts and provider-reported token
usage grouped by response model, plus the prompt versions used by the analysis.
`total_document_count` is fixed when the analysis is queued from all Source
documents in its build; it does not reuse the Objective's seed-document count.
Seed documents remain available through the Objective scope, while
`processed_document_count` advances through the fixed candidate-paper scope.
`unreported_request_count` identifies calls that failed without provider usage
or omitted token fields. Token totals contain only reported usage and remain
`null` when no call reported usage; the backend never estimates missing tokens
from prompt or response text.

Confirmation does not start analysis. `POST .../analysis` creates the next
analysis version with `queued` status and returns immediately. The frontend
polls `GET .../analysis`. Retry allocates a new version. A failed active version
leaves the prior published version readable. Independent Objective analyses,
including analyses from different collections, execute as process-local asyncio
background tasks. An application semaphore bounds simultaneous analysis
execution while the synchronous analysis pipeline runs outside the event-loop
thread. The repository claim transition still allows only one task to execute a
specific Objective analysis version, and persisted analysis state remains the
status authority queried by the client. If the backend cannot create the
background task, it records that version as failed and returns `503`, allowing
the client to retry without leaving a permanently queued version. Only a
complete succeeded version can become published. A succeeded version may have
zero Findings when paper contributions and source-backed Evidence were
published but no defensible comparison survived; this is a scientific
abstention, not a technical failure. The Finding list then returns `total=0`
without a placeholder Finding.

Objective document scope and current-analysis projection are build-scoped. A
rebuild may preserve a confirmed Objective identity and all historical analysis
rows, but an analysis from an older Source build is not exposed as active or
published for the rebuilt Objective. It remains readable only by its explicit
historical `analysis_version`.

`ObjectiveAnalysisResponse.paper_contributions` reports framing, routing,
extraction, and comparability for each paper in the published analysis version.
It is empty until an analysis is published. If a newer active version is queued,
running, or failed, the list still belongs to `published_analysis`, not that
newer version. The Objective detail, confirm, start-analysis, and analysis-status
routes share this response contract.

Each analysis-level contribution exposes `evidence_disposition`,
`routed_source_count`, `extracted_source_count`,
`comparable_evidence_count`, `failed_source_count`, and an optional
`evidence_disposition_reason`. The disposition is one of `excluded`,
`no_routable_evidence`, `extraction_failed`, `no_comparable_evidence`, or
`comparable_evidence`. The disposition and all four counts are either present
together or all `null`. Historical analyses created before this accounting was
persisted retain `null`, meaning unknown; clients must not interpret those
values as zero. A successful `comparable_evidence` contribution with no partial
failure may have no reason.

Each published contribution's `warnings` reports only final degraded coverage:
conservative paper-framing fallback, PaperSkim Source units whose extraction
ultimately failed, and selected Objective Evidence Sources whose extraction
ultimately failed. A successful bounded retry or framing repair is not a
warning. Warning text contains bounded counts rather than provider errors or
raw exceptions. `ObjectiveAnalysisResponse.warnings` aggregates those persisted
contribution warnings in paper order, prefixes each entry with `document_id`,
and removes duplicates within the same paper. A clean published analysis
returns an empty list.

### Published Findings And Evidence

- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence-map`

Finding and Evidence list endpoints support `offset` and `limit`. All responses
include an explicit `analysis_version`. If omitted from the query, the backend
uses the published Objective version. Evidence accepts an optional `finding_id`
filter.

The Evidence Map endpoint has no version query because it always projects the
Objective's current `published_analysis_version`. It deterministically returns
Objective, Finding, Evidence, exact Source, and Document nodes plus typed
lineage edges. Support, contradiction, and context come only from published
Finding Evidence bindings. Extraction failures and exclusions appear only in
document coverage and `includes_document` edges; they are never converted into
scientific contradiction. Multiple Evidence records with the same document,
Source kind, and stable `source_ref` share one Source node. The endpoint performs
no LLM call and persists no graph state. `projection_version` identifies the
read model contract, while `analysis_version` identifies the published domain
records from which it was produced.

A Finding contains:

- `finding_id`, statement, one complete `factors` tuple, one `outcome`, and
  direction;
- assertion strength, attribution scope, synthesis status, certainty, and
  display rank;
- subordinate mechanisms and typed material/sample/process/test scientific
  context;
- deterministic analysis limitations and one Finding-local PaperContribution
  binding for every analyzed, excluded, or failed paper.

The Finding-local `paper_contributions` bind supporting, contradicting,
context, and boundary Evidence IDs for that Finding. They are distinct from
`ObjectiveAnalysisResponse.paper_contributions`, which own paper-level framing,
routing, extraction, and comparability accounting for the whole analysis.

An Evidence record contains:

- `evidence_id`, `document_id`, `source_kind`, and stable `source_ref`;
- exact `source_excerpt`, page numbers, and related typed Source locators;
- evidence role and selection/extraction state;
- normalized material, sample, process, test, value, baseline, interpretation,
  and join fields.

Failed extraction attempts remain Evidence with their exact Source locator,
`selection_status=failed`, and a non-empty `failure_reason`. They do not
participate in Findings. Finding-generation prompts may use a bounded,
document-balanced representative subset, but backend validation, support and
contradiction binding, paper counts, and traceback use the complete eligible
Evidence set.

The consumer identity is always:

```text
(collection_id, objective_id, analysis_version, finding_id)
```

Direct contributing paper count is computed from PaperContribution Evidence
bindings rather than stored as a second declaration. `agreement`, `conflict`,
and `condition_dependent` require direct results from at least two distinct
papers; otherwise synthesis remains `insufficient_confirmation`. Context-only
Evidence cannot establish an outcome, and repeated rows from one paper do not
count as independent cross-paper confirmation.

### Finding Feedback, Curation, And Dataset Export

- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `PUT /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/finding-dataset`
- `GET /api/v1/collections/{collection_id}/finding-dataset`
- `GET /api/v1/collections/{collection_id}/finding-gold-draft`

Feedback requires `analysis_version`, `review_status`, and `issue_type`.
Curation requires `analysis_version` and one complete canonical
`curated_finding`. The service validates its exact identity and every
version-local Evidence/PaperContribution binding. Unknown, stale, unpublished,
partial, and cross-version references return `404`, `409`, or `422` and are
never silently rebound.

Dataset export supports `format=json | training_jsonl` plus optional
`label_status` and `dataset_use_status` filters. `objective_finding_dataset.v2`
includes canonical system prediction, optional expert target, resolved training
target, deterministic Finding/Evidence fingerprints, and exact Evidence
excerpts with document/page/locator provenance. `training_jsonl` contains one
`{messages, metadata}` object per line and omits samples without valid training
messages. IDs preserve lineage; source text and scientific context are part of
model input. The latest feedback or curation event controls dataset status.

### Objective Experiment Plans

- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`
- `PATCH /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}`

Plans are human-editable downstream drafts, not scientific source records.
New plans are manual and cannot claim Chat-message provenance. Historical plans
that already reference a migrated Chat message retain their stored
Finding/Evidence lineage. Reads report whether that snapshot is still current;
stale historical plans cannot be promoted to `ready_for_review`.

### Documents And Source Verification

- `GET /api/v1/collections/{collection_id}/documents/profiles`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/markdown`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/source`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/figures/{figure_id}/image`
- `GET /api/v1/collections/{collection_id}/references`
- `POST /api/v1/collections/{collection_id}/references/build`

The document reader shows parsed paper content and supports precise Source
navigation. A Finding Evidence link names the owning document, stable
`source_ref`, and page when available. Internal Source IDs are audit/navigation
parameters, not visible paper titles.

The browser comparison overview has no separate comparison aggregate endpoint.
It reads the Objective list and each published Finding list described above.
Legacy research-view, Materials, comparable-result, Evidence-card, and
collection-wide Graph routes are not part of the maintained HTTP contract.

## Error Contract

Errors use the status appropriate to the failure:

- `400`: malformed input;
- `401`: invalid or expired authentication;
- `403`: authenticated user lacks access;
- `404`: collection, Chat, Objective, Finding, Evidence, or source record is absent;
- `409`: lifecycle or Chat approval conflict, unpublished/stale version, or
  artifact not ready;
- `422`: request schema validation;
- `500/502/503`: internal or upstream service failure.

Where an endpoint returns a structured detail object, it includes a stable
`code`, user-readable `message`, and relevant resource IDs. Internal stack
traces and credentials never enter the HTTP response.

## Frontend Integration

- Use same-origin requests through the shared API helper.
- Poll only queued/running task or Objective analysis states.
- On a failed Objective analysis, show retry while retaining the last published
  Findings if one exists.
- Paginate Findings and Evidence; do not request a complete Objective object
  graph.
- Use `source_excerpt` as the displayed original Evidence and `source_ref` plus
  page for document navigation.
- Submit feedback against the selected `analysis_version + finding_id`.

## Related Docs

- [Research Objective and Finding contract](../../../docs/contracts/research-objective-workspace-contract.md)
- [Persistence model](../architecture/persistence-model.md)
- [Backend architecture overview](../architecture/overview.md)
