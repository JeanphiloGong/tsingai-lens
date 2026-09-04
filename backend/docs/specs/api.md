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
- Internal application logs correlate authenticated work by request ID and the
  stable internal user ID. They do not log email addresses, session values, or
  authentication credentials. Process-local background work inherits the
  initiating request and user context.
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

### Collections, Documents, And Preparation

- `GET /api/v1/collections`
- `POST /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `GET /api/v1/collections/{collection_id}/documents`
- `POST /api/v1/collections/{collection_id}/documents`
- `POST /api/v1/collections/{collection_id}/documents/{document_id}/preparation`
- `POST /api/v1/collections/{collection_id}/source-archives`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`

A Collection groups current Documents. Each Document independently owns its
preparation status, current Source structure, and current DocumentProfile. The
preparation command queues only the named Document; it does not prepare other
Collection members or discover Objectives. Paper Map construction is a lazy
Objective-core operation over an explicit ready-document selection. Task
responses expose `document_id`, input fingerprint, current stage, progress,
warnings, terminal errors, timestamps, and retry-appropriate status. Tasks do
not expose a filesystem output path; scientific artifacts are addressed by
their owning Document, Objective, analysis, Finding, or Evidence identities.

At most one `document_preparation` task may be queued or running for a Document.
Repeated requests reuse that active task. A completed task is reusable only when
its input fingerprint still matches the current document bytes, parser version,
and Profile version. Source and Profile fingerprints are tracked separately so
a downstream Profile change resumes from the latest still-valid stage. Different
Documents may prepare concurrently. Paper Map reuse has its own fingerprint,
which includes the selected Document preparation fingerprint and Paper Map
policy/prompt versions.
One failed or processing Document does not block upload, preparation, Objective
discovery, or analysis over other ready Documents.

PDF uploads are opened with the Source PDF engine before persistence. A damaged,
incomplete, password-protected, or otherwise unreadable PDF returns `400` and is
not added to the collection. This check establishes parser readability only;
scientific structure extraction happens during that Document's preparation.
A later parser or Profile failure sets only that Document and task to `failed`.
Paper Map failures belong to Objective discovery/analysis and do not change the
Document preparation task. All such failures stay technical; they do not claim
scientific absence.

The source archive request accepts between one and 100 unique collection
`document_id` values with at most 256 MiB of persisted source bytes and returns an
`application/zip` attachment. The archive contains the selected original
uploads under `sources/` plus `manifest.json` with their stable document IDs,
archive paths, media types, sizes, and SHA-256 digests. Selection is atomic: a
missing, oversized, unsafe, unavailable, or integrity-failing source prevents
the complete archive from being returned.
An unknown selected ID returns `404 collection_source_document_not_found`.
An oversized selection returns `413 collection_source_archive_too_large`
before any selected Source bytes are read.
Persisted metadata whose bytes are unavailable, unsafe, or fail integrity
verification returns `409` with the corresponding bounded
`collection_source_*` code; storage paths are never returned.
The endpoint does not infer which papers failed. Parsing, Paper Map, and
Objective analysis retain ownership of their failure states. Clients select
IDs from `Collection.documents` or from stage-specific failure lineage.

The preparation request accepts `mode: standard | fast` and defaults to
`standard`. It starts a process-local asyncio task and returns immediately;
clients read persisted state through `GET /api/v1/tasks/{task_id}`. A
process-local semaphore defaults to 10 concurrent document preparations. This
handoff and admission limit are not an external durable queue.

### Goal Intake

- `POST /api/v1/goals/intake`

Goal intake creates an empty collection directly; it does not create a durable
handoff record or a second research-result identity.

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

A user message may carry at most one `source_contexts` item selected from the
same Collection's document reader. The item contains a stable Source resource
reference, document identity, Source kind and reference, optional page and
heading, a bounded verbatim quote, and whether that quote was shortened. It is stored with that user message and
returned when the trajectory is reloaded. This context is material for the
Agent to inspect, not verified Evidence and not authorization to create or
modify an Objective, Evidence, Finding, or Analysis. The quoted content is never
treated as model instructions. Existing messages have an empty context list.

`POST /api/v1/chat-sessions/{session_id}/messages` returns the existing JSON
`ChatTurnResponse` by default. A caller may send `Accept: text/event-stream` on
the same endpoint to receive UTF-8 server-sent events. `text_delta` events have
`{"content": string}` data and are transient presentation updates. The stream
ends with one `turn` event whose data is the complete `ChatTurnResponse` after
the durable trajectory checkpoints have succeeded. A terminal `error` event
contains only a stable code and sanitized message. Partial text is never a
stored Chat message or a scientific result; clients reload the server
trajectory after an interrupted stream.

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
- `inspect_document_sources` reads one prepared Document's parsed paragraphs,
  bounded table Markdown, and figure captions through exact or focused,
  paginated Source filters. Each Source includes a digest of its complete
  canonical content and a `content_truncated` flag; callers must not treat a
  truncated quote as the complete Source. It returns canonical Document and
  Source links; matched content remains inspection material rather than
  verified Evidence;
- `inspect_research_process` reads each current Document and its latest
  preparation task. It reports stored, processing, ready, and failed papers plus
  observable stages and warnings. It never exposes model chain-of-thought,
  prompt repair, or retry internals;
- `start_research_process` is a `write` capability. After exact-argument
  approval, it queues independent preparation for the supplied `document_ids`,
  or for all current Documents when the list is empty. It returns the per-paper
  task records immediately. Preparation parses paper content and classifies
  paper type and role. It does not build a Paper Map, discover or confirm an
  Objective, run Objective-specific Evidence extraction, or publish a Finding.
  Unknown IDs fail before any task is created. A Collection with no
  uploaded papers returns `collection_has_no_papers`;
- `query_published_findings` returns bounded Finding and Evidence summaries
  only from published Objective analysis versions; an empty successful result
  is a scientific absence, not a provider failure;
- `inspect_published_finding` returns one complete canonical published Finding
  and a bounded page of its linked Evidence. This exact read, followed by any
  necessary Source inspection, is required before the Agent proposes a review
  or a new conclusion;
- `create_finding_version` is a `write` capability. It accepts the same
  statement, assertion strength, version-local Evidence roles, limitations,
  optional parent Finding, or explicit abstention as the human Finding
  authoring command. After exact-argument approval it calls
  `FindingAuthoringService.create_version()` and returns the canonical new
  analysis and optional Finding. The source analysis and all existing Finding,
  Evidence, and Source records remain unchanged;
- `record_finding_feedback` is a `write` capability. After exact-argument
  approval, it calls the same `FindingFeedbackService.record_feedback()` path
  as the Finding workbench and records the authenticated user as reviewer. It
  does not mutate the published Finding, Evidence, or Sources;
- `curate_finding` is a `write` capability. After exact-argument approval, it
  passes one complete canonical Finding to the same
  `FindingFeedbackService.record_curation()` path as the Finding workbench.
  Service validation preserves Finding identity, paper coverage, Evidence IDs,
  and Source lineage; curation cannot create a new Finding;
- `propose_objective_drafts` records at most three focused, single-outcome
  drafts in the Chat trajectory. PaperResearchMap relationships may be reported
  as proposal context, but they are never presented as Evidence and this call
  does not persist, confirm, analyze, or publish a Core Objective;
- `create_objective_candidate` is a `write` capability. After exact-argument
  approval, it creates one unconfirmed `chat_assisted` Core candidate. Optional
  seed-document IDs record where the question came from, not the complete
  analysis scope, support, or Evidence; an empty seed set is valid. The candidate has zero confidence until
  Objective analysis tests it. It never confirms the Objective or starts
  analysis. Repeating the same approved tool call is idempotent;
- `preview_research_scope` is a `read` capability. For one proposed material,
  variable, and outcome scope, it projects mapped papers as
  `likely_relevant`, `needs_inspection`, or `confidently_out_of_scope`.
  `insufficient_map` papers always need inspection, and review citation leads
  can request inspection but cannot establish relevance or Evidence. Results
  and full counts are bounded independently;
- `start_objective_analysis` is a `write` capability. A separate exact-argument
  approval confirms the chosen candidate and calls the same canonical
  `ObjectiveAnalysisService.start_analysis()` used by the HTTP route with the
  exact approved ready `document_ids`. It
  returns the persisted queued, running, succeeded, or failed state and never
  introduces a Chat-owned analysis path;
- `publish_agent_objective_analysis` is a separate `write` capability for the
  case where the researcher explicitly asks the Agent itself to analyze a
  bounded paper scope. Before proposing the write, the Agent reads exact
  Sources through `inspect_document_sources` over one or more turns. The
  approved payload contains one summary and at least one structured Evidence
  draft for every selected ready Document. The backend revalidates each Source
  locator, complete-content SHA-256 digest, normalized verbatim excerpt, and
  Evidence contract before allocating a version. It then publishes one
  `agent_authored` analysis through the existing repository queue, claim, and
  atomic publication lifecycle. The version contains PaperContributions and
  Evidence but no Finding; any conclusion requires a later approved
  `create_finding_version` call. This capability has no separate HTTP endpoint,
  draft store, background extraction, or Finding-synthesis call;
- `inspect_objective_analysis` is a `read` capability. It returns the current
  canonical Objective analysis version, paper progress, terminal error, and
  published-version identity without starting or retrying work.

Model context is a bounded recent suffix of the durable trajectory. An
assistant tool call and its following tool result are retained or omitted as one
protocol unit, so context trimming never sends an orphan tool result to the
provider.

The server checkpoints the user message before the first model request, then
checkpoints model tool intent, running call state, structured tool results, and
the final assistant answer as separate append-only transitions. A process
interruption therefore cannot erase an already requested action or make an
approved write appear never to have started. Lens allocates every durable tool
call ID; any request-local identifier returned by a model provider is not a
Chat identity and is not persisted.

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

- `POST /api/v1/collections/{collection_id}/objective-discovery`
- `GET /api/v1/collections/{collection_id}/objectives`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/scope`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`

Discovery accepts `{"document_ids": [...]}` with one or more unique current
Documents. The explicit selection is not truncated or divided into independent
discovery scopes, so candidate formation retains the complete cross-paper
context. Every selected Document must be `ready` with a preparation fingerprint.
The command freezes the resolved `(document_id, preparation_fingerprint)`
values in one collection-scoped `objective_discovery` Task and returns that
Task immediately. At most one discovery Task may be `queued` or `running` for
a Collection; a repeated command returns the active Task without scheduling a
second worker, even when another request reaches a different backend process.
Clients restore and poll its state through the ordinary Collection Task and
Task-detail endpoints. On completion they read the replaced candidate set from
`GET .../objectives`; on failure the terminal Task error remains visible and a
new command creates a retry Task. A backend restart marks an interrupted Task
failed rather than leaving it permanently active.

The background worker lazily builds or reuses the selected Documents' current
Paper Maps, reads their Profiles and maps, and replaces the current generated
candidates. It does not silently include all Collection papers. This is
research-question formation, not Objective Evidence analysis: analysis still
requires the later, explicit Objective command. The worker is process-local,
while admission, progress, completion, and failure are persisted; the Task
record is observable execution state rather than an external durable queue.

A Paper Map is preliminary scope metadata: paper type, material and process
themes, variable-to-outcome axes, review synthesis, Source lineage, coverage,
and uncertainty. It does not contain experiment samples, tests, comparators,
fixed conditions, parameter levels, or measurements. Confirmed-Objective
analysis may use it to prioritize Source inspection and surface coverage
warnings, but only facts grounded in inspected Sources may populate Evidence.

`ResearchObjective` is the only business aggregate root. Its identity is
`(collection_id, objective_id)`. The analysis-state and command responses
contain:

- question and material/process/property/comparison scope;
- seed document IDs as question provenance and explicit exclusions as scope
  constraints, neither of which is Evidence;
- `confirmation_status`: `candidate | confirmed`;
- `active_analysis_version` and `published_analysis_version`;
- `origin`: `system_discovered | chat_assisted`, plus Chat creator provenance
  for an assisted candidate;
- ordered `source_relationship_ids` linking the Objective to paper-study
  relationships;
- `active_analysis`, `published_analysis`, analysis-level
  `paper_contributions`, and warnings.

The Objective list places current generated candidates in persisted rank,
followed by durable Chat-assisted candidates in creation order. The list supports
`offset` and optional `limit`. When `limit` is omitted, the response contains
every Objective from `offset` onward so lower-ranked candidates remain visible
without client pagination. An explicit `limit` applies ordinary pagination. The
response contains `total`, `offset`, and the applied `limit` (`null` when
omitted), and each Objective contains its one-based `rank`. Rank is for
researcher prioritization. Paper Maps and Source remain owned by their Documents
rather than embedded in Objective list responses.

`GET .../scope` is the read-only screening step between question formation and
deep analysis. It applies the Objective's material, variables, and outcome to
every current Collection Paper Map and returns each mapped Document exactly once
as `likely_relevant`, `needs_inspection`, or
`confidently_out_of_scope`. The response contains complete
`recommended_document_ids`, `review_document_ids`, and
`excluded_document_ids`, category counts, per-document reasons, Paper Map
status/limitations, support basis, and `is_seed`. A relationship or review
synthesis match is navigation support only; `support_is_evidence` is always
false. Incomplete maps, partial matches, broad-variable uncertainty, and review
citation leads require researcher inspection and are not selected by default.
The endpoint performs no LLM call and persists no scope. An unknown Objective
returns `404`; a Collection with no Paper Maps returns
`409 objective_scope_not_ready`.

`ObjectiveAnalysis` is addressed by the Objective identity plus a positive
`analysis_version`. It contains immutable selected `document_inputs`,
pipeline/model/prompt lineage,
`queued | running | succeeded | failed` status, phase, document progress,
current document, terminal error, timestamps, and provider-reported execution
`stats`. Statistics include duration, request counts and provider-reported token
usage grouped by response model, plus the prompt versions used by the analysis.
`total_document_count` is fixed from the exact selected `document_ids` supplied
to the analysis command. Seed documents remain proposal context, while
`processed_document_count` advances through the frozen analysis inputs.
`unreported_request_count` identifies calls that failed without provider usage
or omitted token fields. Token totals contain only reported usage and remain
`null` when no call reported usage; the backend never estimates missing tokens
from prompt or response text.

Analysis responses also expose their authoring lineage. `origin` distinguishes
`system_generated`, `human_authored`, `agent_authored`, and `hybrid` versions;
`created_by_user_id` identifies the accountable researcher and the optional
`created_by_tool_call_id` links an Agent-authored version to the approved Chat
tool call. These fields record authorship only and do not make a statement or
Source into verified Evidence.

`POST .../analysis` accepts the same required `{"document_ids": [...]}` shape
as discovery and expresses researcher approval of both the Objective definition
and the selected ready-paper analysis scope.
The browser obtains its default selection from `GET .../scope`'s complete
`recommended_document_ids`; it never substitutes `seed_document_ids` for that
screening result. The researcher may add a `needs_inspection` paper or override
another decision before submitting the command.
For a candidate, it atomically changes `confirmation_status` to `confirmed` and
creates the next analysis version with `queued` status. For an already confirmed
Objective, it creates or reuses the active analysis normally. The command returns
immediately, and the frontend polls `GET .../analysis`. Retry allocates a new
version. A failed active version leaves the prior published version readable.
Independent Objective analyses,
including analyses from different collections, execute as process-local asyncio
background tasks. An application semaphore bounds simultaneous analysis
execution. Tasks above that limit wait on the in-process semaphore; this is not
a durable application queue. Synchronous model and scientific computations run
outside the event-loop thread, while PostgreSQL reads and writes use awaited,
task-local `AsyncSession` transactions. The repository claim transition still
allows only one task to execute a specific Objective analysis version, and
persisted analysis state remains the status authority queried by the client. If
the backend cannot create the background task, it records that version as
failed and returns `503`, allowing the client to retry without leaving a
permanently queued version. Only a complete succeeded version can become
published. A succeeded version may have zero Findings when paper contributions
and source-backed Evidence were published but no defensible comparison
survived; this is a scientific abstention, not a technical failure. The Finding
list then returns `total=0` without a placeholder Finding.

`ObjectiveAnalysisService` owns queue-and-dispatch for this HTTP command and
the Agent's automatic `start_objective_analysis` capability. Direct
Agent-authored analysis does not call that extraction pipeline; its application
service revalidates the approved Source-grounded payload and uses the same
Objective repository queue, claim, failure, and publication transitions.
Both commands therefore share confirmation, version allocation, active-version
exclusion, and published-pointer semantics without sharing scientific authorship.

Every version stores ordered `document_inputs` containing `document_id` and
`preparation_fingerprint`. Execution checks these fingerprints against the
current ready Documents before reading Source. If a Document was re-prepared or
is no longer ready, analysis fails explicitly instead of mixing preparation
states. A retry sends the failed version's frozen Document IDs so the researcher
can reproduce the same scope after restoring readiness.

`ObjectiveAnalysisResponse.paper_contributions` reports framing, routing,
extraction, and comparability for each paper in the published analysis version.
It is empty until an analysis is published. If a newer active version is queued,
running, or failed, the list still belongs to `published_analysis`, not that
newer version. The analysis command and analysis-status route share this
response contract.

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
conservative paper-framing fallback, deterministic evidence-routing fallback,
PaperResearchMap Source units whose extraction ultimately failed, and selected
Objective Evidence Sources whose extraction ultimately failed. A successful
bounded retry or framing repair is not a warning. Warning text contains bounded
counts rather than provider errors or raw exceptions.
`ObjectiveAnalysisResponse.warnings` aggregates those persisted contribution
warnings in paper order, prefixes each entry with `document_id`, and removes
duplicates within the same paper. A clean published analysis returns an empty
list.

`ObjectiveAnalysisResponse.evidence_review` is the researcher-facing coverage
ledger for the published Evidence set. It counts every retained Source-backed
Evidence record by scientific status (`comparable`, `association_only`,
`descriptive`, `needs_context`, `non_comparable`, or `extraction_failed`) and
includes bounded gap records with the document, Source locator, page, reason,
and excerpt. A gap is not silently converted into a missing Finding: it tells
the researcher whether to inspect more same-paper context, preserve a
non-comparable observation, or retry a technical extraction. The field is
derived from immutable published Evidence and is zero-valued for historical
responses that predate this ledger.

### Published Findings And Evidence

- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence-map`

Finding and Evidence list endpoints support `offset` and `limit`. All responses
include an explicit `analysis_version`. If omitted from the query, the backend
uses the published Objective version. Evidence accepts an optional `finding_id`
filter.

Each Finding and Evidence record exposes its `origin`, optional
`created_by_user_id`, and optional `created_by_tool_call_id`. The tool-call field
is populated for an `agent_authored` record and for an Agent-assisted revision;
it is `null` for system-generated and ordinary direct human-authored records.
It is durable authoring provenance, not scientific support; Evidence remains
grounded through its Source identity and a Finding remains supported through
its version-local Evidence bindings.

The Findings POST command records one deliberate researcher Evidence-to-Finding
decision. It never inserts into the published source version. The request
identifies that current `source_analysis_version`, assigns existing
version-local Evidence to support, contradiction, context, and optional
condition-boundary roles, and supplies a statement, assertion strength,
limitations, and optional `parent_finding_id`.
The authenticated user identity is server-derived. Paper coverage, factors,
outcome, direction, attribution, synthesis status, certainty, target version,
and Source content are also server-derived and cannot be supplied by the
browser.

```json
{
  "source_analysis_version": 3,
  "statement": "Higher laser power is associated with lower porosity under the reported scan conditions.",
  "assertion_strength": "associative",
  "supporting_evidence_ids": ["evidence_a"],
  "contradicting_evidence_ids": [],
  "context_evidence_ids": ["evidence_b"],
  "condition_boundary_evidence_ids": ["evidence_b"],
  "limitations": ["Direct support is currently limited to one paper."],
  "parent_finding_id": null,
  "abstention_reason": null
}
```

A successful command returns `201` with the newly published authored analysis
and its new canonical Finding. The repository clones the complete published
PaperContribution, Evidence, and Finding snapshot into the next version,
validates every selected Evidence and exact Source, appends the human-authored
or hybrid Finding, and atomically advances the Objective's published pointer.
The source version and parent Finding remain unchanged. `parent_finding_id`
therefore means derivation, not in-place editing.

A researcher may instead submit one of `no_comparable_evidence`,
`no_grounded_evidence`, or `insufficient_evidence` as `abstention_reason`, with
an explanatory `limitations` entry and no statement, parent, or Evidence roles.
The new analysis version records the abstention as metadata and creates no
placeholder Finding. An unauthenticated request returns `401`; missing or
unowned collections and missing Objectives return `404`; stale source versions,
concurrent analysis, unknown or ineligible Evidence, and scientifically
inconsistent role selections return `409`; malformed request shapes return
`422`.

The Evidence POST command records one source-grounded Evidence decision from a
specific prepared Document Source. It accepts `source_analysis_version`,
`document_id`, `source_kind` (`text_window | table | figure`), `source_ref`, an
exact `source_excerpt`, an Evidence role, optional changed variables,
comparison, reported result, attribution scope, and scientific context. The
server checks collection ownership, the published analysis version, the
analysis document scope, the Source locator, and that the normalized excerpt
is a substring of the canonical Source. It derives identity, page, resolution,
confidence, and creator provenance. The browser cannot provide a creator,
analysis target version, or Source outside the selected analysis.

An Evidence correction never overwrites the old record. Supplying
`supersedes_evidence_id` must refer to the current Evidence at the same Source
locator; publication clones the complete source snapshot into the next
immutable analysis version, marks the old record as superseded, and leaves old
Findings pointing at their original Evidence. A successful command returns
`201` with the new analysis and Evidence. Stale versions, running analyses,
unknown or out-of-scope Sources, invalid excerpts, and attempts to revise an
already superseded record return `409`; malformed scientific shapes return
`422`. The Research Agent exposes the same operation as the approved
`create_evidence_version` write capability and must supply the digest returned
by `inspect_document_sources`; it does not create a second Evidence identity.

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
records from which it was produced. `complete` is true when every included paper
reached a non-technical analysis outcome. A scientifically valid empty result is
complete; any paper with `analysis_status=failed` makes it false.

A Finding contains:

- `finding_id`, statement, one complete `factors` tuple, one `outcome`, and
  direction;
- assertion strength, attribution scope, synthesis status, certainty, and
  display rank;
- subordinate mechanisms and typed material/sample/process/test scientific
  context;
- deterministic analysis limitations and one Finding-local PaperContribution
  binding for every analyzed, excluded, or failed paper.

Every Finding also exposes `origin`, optional `source_analysis_version`,
optional `parent_finding_id`, optional `created_by_user_id`, and optional
`created_at`. `system_generated` is the default for historical/system results;
`human_authored` is a new conclusion formed from existing Evidence; `hybrid`
is derived from a named parent Finding. Authored analysis states expose the
same source-version and creator lineage plus optional abstention metadata.

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

Each scientific-context attribute may include `context_scope`:
`experimental`, `simulation`, `background`, or `unknown`. This records how the
paper presents the setting without changing its Source grounding. Simulation
and background attributes remain visible for audit, but cannot by themselves
close the experimental process-context requirements for a comparable result.
Historical Evidence without this field is read as `unknown`.

Failed extraction attempts remain Evidence with their exact Source locator,
`selection_status=failed`, and a non-empty `failure_reason`. They do not
participate in Findings. Finding-generation prompts may use a bounded,
document-balanced representative subset, but backend validation, support and
contradiction binding, paper counts, and traceback use the complete eligible
Evidence set. `supports_finding` is a backend-derived eligibility signal for
the authoring editor; it does not turn an Evidence record into support until a
researcher assigns it a Finding role and publishes the new version.

The authoring command currently consumes existing published Evidence only. It
does not create, replace, or remove Evidence from a raw Source. Source-to-
Evidence annotation and correction remain the separate #191 workflow.

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

The Finding workbench and Research Agent share these same service operations.
The Agent first reads the complete published Finding and linked Evidence,
inspects exact Sources as needed, and proposes the same feedback or curation
arguments. The write runs only after the authenticated user approves those
exact arguments. Chat does not own a second Finding identity or review store.

Finding authoring is distinct from review. The Agent may propose a new
Evidence-to-Finding decision only from `supports_finding` Evidence in the exact
current published version. The approved capability calls the same
`FindingAuthoringService` as the HTTP workbench, including immutable version
publication, role validation, Source validation, and abstention semantics.
Agent prose or raw Source text cannot become Evidence.

Dataset export supports `format=json | training_jsonl | llamafactory_alpaca`
plus optional `label_status` and `dataset_use_status` filters.
`objective_finding_dataset.v2` includes canonical system prediction, optional
expert target, resolved training target, deterministic Finding/Evidence
fingerprints, and exact Evidence excerpts with document/page/locator
provenance. `training_jsonl` contains one `{messages, metadata}` object per
line. `llamafactory_alpaca` contains one `{instruction, input, output,
metadata}` object per line, where `instruction` and `output` are projected from
the existing Lens user/assistant training messages and `input` is empty. Both
training formats omit samples without valid training messages and include only
`training_ready` samples. IDs preserve lineage; source text and scientific
context are part of model input. The latest feedback or curation event controls
dataset status.

For LlamaFactory, register the downloaded JSONL with its existing Alpaca
formatter (the default column names are already correct):

```json
{
  "lens_finding": {
    "file_name": "lens_finding_alpaca.jsonl",
    "formatting": "alpaca",
    "columns": {
      "prompt": "instruction",
      "query": "input",
      "response": "output"
    }
  }
}
```

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

The document-profile list accepts `offset`, `limit`, and optional `query`,
`doc_type`, and `has_warnings` filters. `query` performs case-insensitive
matching against the profile title and source filename. `doc_type` accepts
`experimental`, `review`, `mixed`, or `uncertain`; `has_warnings` filters by
whether parsing warnings are present. All active criteria are combined before
pagination. `total` is the number of matching profiles, `count` is the current
page size, and `summary.total_documents` remains the complete profiled
collection size.

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
