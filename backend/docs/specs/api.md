# API Contract

This document describes the maintained Lens v1 HTTP contract. The generated
OpenAPI document at `/api/openapi.json` is the field-level runtime reference;
this file owns resource boundaries and cross-endpoint semantics. Detailed
module contracts are maintained in the linked topic directories under `specs/`.

The module-first Conversation and Agent contract is maintained in
[`conversation-agent/README.md`](conversation-agent/README.md). It owns the
target Conversation, Feedback, Task, tree, and persistence semantics.

## Conventions

- Product APIs use `/api/v1/*`.
- API documentation uses `/api/docs`, `/api/redoc`, and `/api/openapi.json`.
- The sibling user-service establishes the HttpOnly `lens_session` cookie.
  Browser identity requests use same-origin `/user-api/v1/*`; Lens business
  requests send that cookie through `/api/v1/*` and resolve it over mTLS gRPC.
- Every business response carries `X-Request-ID`.
- Internal application logs correlate authenticated work by request ID and the
  stable internal user ID. They do not log email addresses, session values, or
  authentication credentials. Process-local background work inherits the
  initiating request and user context.
- A workspace is the primary working scope; a document is a source inside it.
- PostgreSQL is the structured runtime authority.
- GET requests never trigger LLM analysis.
- Retired payloads and endpoints are not accepted through aliases or fallback
  parsers.

Unless an identity/shared endpoint below specifies an HTTP status, existing
failure numbers are business `code` values under HTTP 200. Stable reason strings
are carried in `data.code`.

## Resource Map

### Authentication

Identity HTTP routes belong to user-service: `POST /user-api/v1/login`,
`POST /user-api/v1/logout`, `GET /user-api/v1/me`,
`GET /user-api/v1/me/permissions`. The former Lens `/auth/*` routes are removed.

User-service HTTP errors return a flat object such as
`{"code":"invalid_credentials"}` with the corresponding HTTP error status.
A rate-limited response also includes top-level `retry_after` seconds and the
`Retry-After` header; other errors omit that field. These are user-service
responses; the Lens business envelope below keeps its existing shape.
User-service returns its own JSON contract and HTTP 401/403/409/422/503 errors.
Lens does not keep a second user/permission table or local-auth fallback.

Lens identity rejection uses HTTP 401 / business code `200301` with
`data.code=authentication_required`; unavailable identity uses HTTP 503 /
`200205`; an explicit capability denial uses HTTP 403 / `200203`.
Successful Lens JSON and unrelated existing business failures retain the
`{code,message,data,meta}` envelope; resource-hidden errors remain HTTP 200 /
`200201`. Business clients must read that envelope rather than infer success
solely from HTTP 200. Stable user IDs remain in business/audit records.

### Workspaces, Documents, And Preparation

- `GET /api/v1/workspaces`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}`
- `DELETE /api/v1/workspaces/{workspace_id}`
- `GET /api/v1/workspaces/{workspace_id}/documents`
- `POST /api/v1/workspaces/{workspace_id}/documents`
- `POST /api/v1/workspaces/{workspace_id}/documents/{document_id}/preparation`
- `POST /api/v1/workspaces/{workspace_id}/source-archives`
- `GET /api/v1/workspaces/{workspace_id}/pipeline-runs`
- `GET /api/v1/pipeline-runs/{run_id}`

A Workspace groups current Documents. Each Document independently owns its
preparation status, current Source structure, and current DocumentProfile. The
workspace-scoped preparation, Pipeline Run, and experiment-plan endpoints are
restricted to the authenticated Workspace owner and return `200201` for other
users.
Document upload accepts the optional query parameter `reuse_existing=true` for
retrying an uncertain upload outcome. If the normalized content already exists
in this Workspace, the server returns that Document with `200`, preserving its
identity, filename, and preparation state. Content matching uses server-side
SHA-256; a matching filename alone never selects an existing Document. The
default remains `false`, with duplicate content returning `200100`. Neither mode
starts preparation automatically; the caller uses the returned Document ID with
the existing preparation command. Ownership and upload validation apply before
recovery just as they do before an ordinary upload.

The preparation command queues only the named Document; it does not prepare other
Workspace members or discover Objectives. Paper Map construction is a lazy
Objective-core operation over an explicit ready-document selection. Workspace
Pipeline Run history returns compact rows with run identity,
pipeline and scope, status, current node, progress, warnings, terminal errors,
and last-update time. `GET /api/v1/pipeline-runs/{run_id}` returns the complete
technical record, including the input fingerprint, node telemetry, statistics,
context, timestamps, and retry lineage. Runs do not expose a filesystem output
path; scientific artifacts are addressed by their owning Document, Objective,
analysis, Finding, or Evidence identities.

`GET /api/v1/workspaces` is the workspace-picker projection. Each item
contains workspace identity, name, description, status, paper count, and
compact current-document rows (`document_id`, filename, media type, status,
size, and timestamps). It intentionally omits storage keys, SHA-256 values,
parser versions, and preparation fingerprints. Use the workspace detail or
document-list endpoints when those operational fields are required.

At most one `document_preparation` run may be queued or running for a Document.
Repeated requests reuse that active run. A completed run is reusable only when
its input fingerprint still matches the current document bytes, parser version,
and Profile version, the Document is ready, and its Source and completed Profile
still exist. A technically failed Profile is never a reusable completed result,
even when an older run incorrectly recorded success. Source and Profile fingerprints are tracked separately so
a downstream Profile change resumes from the latest still-valid stage. Different
Documents may prepare concurrently. Paper Map reuse has its own fingerprint,
which includes the selected Document preparation fingerprint and Paper Map
policy/prompt versions.
One failed or processing Document does not block upload, preparation, Objective
discovery, or analysis over other ready Documents.

PDF uploads are opened with the Source PDF engine before persistence. A damaged,
incomplete, password-protected, or otherwise unreadable PDF returns `200100` and is
not added to the workspace. This check establishes parser readability only;
scientific structure extraction happens during that Document's preparation.
A later parser or runtime failure sets only that Document and run to `failed`.
A recoverable model-classification failure preserves the parsed Source, leaves
the Document `stored`, and returns a `partial_success` run with a failed
`document_profile` node and a retryable warning. A subsequent preparation request
reuses the Source and retries classification. A successfully completed but
scientifically uncertain classification remains reusable. Only completed
preparation makes the Document ready for Objective scope selection.
Run-level and node-level preparation errors use safe stage-specific messages,
including historical records read through list and detail endpoints. Internal
exceptions remain in logs and traces rather than the public response.
Paper Map failures belong to Objective discovery/analysis and do not change the
Document preparation run. All such failures stay technical; they do not claim
scientific absence.

The source archive request accepts between one and 100 unique workspace
`document_id` values with at most 256 MiB of persisted source bytes and returns an
`application/zip` attachment. The archive contains the selected original
uploads under `sources/` plus `manifest.json` with their stable document IDs,
archive paths, media types, sizes, and SHA-256 digests. Selection is atomic: a
missing, oversized, unsafe, unavailable, or integrity-failing source prevents
the complete archive from being returned.
An unknown selected ID returns `200201 workspace_source_document_not_found`.
An oversized selection returns `200100 workspace_source_archive_too_large`
before any selected Source bytes are read.
Persisted metadata whose bytes are unavailable, unsafe, or fail integrity
verification returns `200204` with the corresponding bounded
`workspace_source_*` code; storage paths are never returned.
The endpoint does not infer which papers failed. Parsing, Paper Map, and
Objective analysis retain ownership of their failure states. Clients select
IDs from `Workspace.documents` or from stage-specific failure lineage.

The preparation command has no request body and runs the canonical Source and
DocumentProfile preparation pipeline. It starts a process-local asyncio task
and returns immediately; clients read persisted state through
`GET /api/v1/pipeline-runs/{run_id}`. A
process-local semaphore defaults to 10 concurrent document preparations. This
handoff and admission limit are not an external durable queue.

### Goal Intake

- `POST /api/v1/goals/intake`

Goal intake creates an empty workspace directly; it does not create a durable
handoff record or a second research-result identity.

### Shared Model Connections

The [model connection API](model-connections/api.md) defines the user catalog
and administrator configuration endpoints. Its
[data model](model-connections/data-model.md) defines connection storage,
encrypted credentials, and administrative audit records.

#### Chat Connection Binding

`POST /api/v1/conversations/{conversation_id}/messages` accepts an optional
`model_connection_id` alongside the existing message, Source, permission, and
branch fields. Resolve it only after ownership checks and under the existing
session execution lock. Omission selects the first enabled entry in the same
priority order as the directory. No available model or an invalid/disabled
selection fails before appending a user message
or calling the provider. A valid choice binds the whole response to that connection ID;
another user's selection cannot mutate that response's client.

Response snapshots include nullable `model_connection_id` and
`model_connection_name`. Internal model-call records retain the connection ID
and the model actually called. Existing completed
snapshots may have NULLs. Approval continuation reads the saved connection ID,
even when disabled, and never substitutes another enabled configuration. Auto-approved
tools and context compaction reuse the same response runner. GET event reconnects
read that saved snapshot without selecting a model or generating another answer.

Trajectory responses (GET messages and SSE trajectory events) include nullable
`retryable_decision`. It is the original call with status `approved` or `rejected`
when its decision is saved, no result has been recorded, and no worker is running.
`pending_approval` remains reserved for a decision the user has not made. A client
may explicitly retry the saved decision through the existing decision endpoint,
using that call's original decision and `arguments_digest`; it sends no model
selection and must never convert a rejection to an approval. A rejection with no
result resumes its refusal observation and explanation, without executing a write.
A recorded result suppresses this recovery projection, and repeated completed
requests do not create another response or execute again. GET and reconnect only
observe; they never perform the retry. New questions wait until this outstanding
continuation has been handled.

JSON endpoints keep HTTP 200 and return the existing business error envelope.
An unknown or disabled choice uses `ResourceConflictException` (business code
`200204`) and `data.code = "model_connection_unavailable"`. The request schema
accepts IDs of 1–64 characters; invalid input uses `200100`. A missing default,
missing saved binding, invalid configuration or an unreadable credential uses
`ServiceUnavailableException` (`200205`) with the stable reason in `data.code`:
`model_connection_default_unavailable`, `model_connection_binding_missing`,
`model_connection_invalid_configuration`, or `model_credentials_unavailable`.
Authentication failure uses the existing `200301` contract. The directory calls
the concrete repository directly; unexpected database errors follow the existing
application exception handler, without inventing a second directory error API.
If an SSE stream has already started, connection failures arrive as sanitized
`error` events within HTTP 200. No client may treat the status alone as a
completed scientific answer. Provider failures after dispatch continue to use
the existing `model_unavailable`/context error contract.

### Research Agent Chat

Session operation permissions are exposed by authenticated
`GET/PUT /api/v1/conversations/{conversation_id}/permissions`. PUT accepts `mode`
(`read_only`, `confirm`, `auto`), an explicit `actions` list, and
`expires_at` (`null` keeps an automatic grant active until it is
revoked or changed, while a non-null value must be no more than 24 hours
ahead), `all_actions`, and `expected_revision`. A session without a workspace default and every branched session defaults
to `confirm`; revision conflicts and invalid grants return `200204`, inaccessible
sessions return `200201`. The model cannot call this settings endpoint.

Automatic grants can cover every currently registered write action listed in
`domain/chat/permissions.py`, including research-process and Objective actions,
Evidence/Finding publication, review annotations, and research-plan changes.
Evidence and Finding version creation publish a new analysis version; there is no
separate save-only permission. The user selects the exact actions and optional
expiry in the session permission control, while the default mode still requires exact
confirmation. Calls record `decision_basis` (`explicit` or `scope_grant`) and
`authorization_revision`.

Revocation and acquiring execution authority lock the same session row. A
revocation completed first prevents a new claim; an already claimed operation
may finish. Repeated claims never restart a running/terminal call. A crash
after claim may leave an interrupted operation requiring investigation; this
does not promise transactional exactly-once effects across every domain service.
New grants do not automatically execute old pending calls. Read-only mode
blocks even explicit approvals. Request-level no-save constraints further
restrict writes; natural-language detection remains bounded, and read-only
settings are the deterministic control.

Workspace owners can set a default for newly created workspace Agent sessions through
authenticated `GET/PUT /api/v1/workspaces/{workspace_id}/agent-permissions`.
The endpoint uses the same mode, action, optional expiry, and revision contract and
returns `200201` for a workspace the caller does not own. A workspace default is
copied when a session is created; changing it does not silently change an
active session. Branches continue to default to confirmation. `all_actions=true` is expanded by the backend to every current
registered write action, so clients do not need to maintain that authoritative
list.

- `POST /api/v1/conversations`
- `GET /api/v1/conversations?workspace_id={workspace_id}`
- `GET /api/v1/conversations/{conversation_id}`
- `PUT /api/v1/conversations/{conversation_id}/pin`
- `PUT /api/v1/conversations/{conversation_id}/title`
- `DELETE /api/v1/conversations/{conversation_id}`
- `GET /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/edits`
- `GET /api/v1/conversations/{conversation_id}/tree`
- `POST /api/v1/conversations/{conversation_id}/forks`
- `PUT /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`
- `DELETE /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`
- `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/operations/{operation_id}/decision`

Model-call records are internal. Public Chat APIs no longer expose their list
or detail.

[Conversation V3](conversation-agent/conversation-api.md) exposes conversation metadata,
the selected message path, and [answer feedback](conversation-agent/feedback-api.md)
under `/api/v1/conversations`. Its path-conflict and resource errors use HTTP `409`
and `404` with `meta.error_code`.

The target contract defines how explicit Fork assigns new Message IDs and
preserves source execution ownership. [Tree API](conversation-agent/tree-api.md#3-explicit-fork)

Chat is the independent conversation and Agent trajectory owner. A Chat session
belongs to one authenticated user and one workspace. Its ordered messages
record ordinary user and assistant conversation, model tool intent, and bounded
structured tool results. Chat references Core resources through stable resource
references; it does not own or duplicate Objective, Evidence, Finding, or
Analysis records.

The workspace-scoped list returns the authenticated user's saved sessions,
ordered by `is_pinned` descending, then `updated_at` descending and `conversation_id`
descending, before applying `limit` and `offset` pagination. It is
the source for restoring Chat history on another device; browser local storage
may remember the active session but is not the authoritative history index. Each
list item also includes `title`: the saved manual or generated title, otherwise the trimmed first line of the first user question
(up to 160 characters), or `null` for an empty conversation. A client can render
history without loading every trajectory or relying on a local title cache.

`PUT .../{conversation_id}/title` accepts `{"title": "IN718 comparison"}` and
returns the saved session. The application service trims titles and then checks
the 1–160 character limit. NUL, CR and LF are rejected in the original input,
including at its edges; invalid requests return 200100. Both session and workspace
ownership are required; missing or unowned sessions return 200201. Renaming changes
only the title, preserving messages, progress, pin state and activity time.
Individual session reads expose the saved title or null. Later generation
checkpoints do not overwrite it; a revision starts without a saved title.

After the first normally completed answer, an untitled session receives a short
model-generated topic title in the first question's language. Naming uses the
same request-bound model connection, a bounded excerpt of the first question and
answer, no tools, and a 45-second timeout. It runs in the background without
holding the response or blocking the next question. It does not add a conversation message
or change research evidence. Only a null title can be filled automatically, so
manual renaming wins even while generation is pending. On naming failure the
answer remains valid and the question-based label stays available; a later
normally completed answer can retry naming. Named sessions are not regenerated.

Session responses include `is_pinned` (false by default). `PUT .../{conversation_id}/pin`
accepts exactly `{"is_pinned": true}` or `{"is_pinned": false}` and returns the
saved session. Setting the same state is idempotent. The authenticated user must
own both the session and its Workspace; missing or unowned sessions return 200201
`chat_session_not_found`. Pinning is independent of execution and does not
change `updated_at`, messages, approvals, or Source attachments. Generation
checkpoints preserve the saved preference, and new revisions start unpinned.

Deleting an owned idle session returns a success envelope with empty `data` and removes its trajectory. Execution
conflicts return 200204 `chat_session_busy`. A session still referenced by another
session's `parent_conversation_id` or `root_conversation_id` returns 200204
`chat_session_has_branches`; delete the dependent versions first. This preserves
their saved questions, Source attachments, and tree checkpoints. Missing or
unowned sessions return 200201 `chat_session_not_found`. Deletion and branch copying
serialize on the source session row so a concurrent branch cannot lose its source.

Message editing and answer regeneration preserve the original trajectory.
`POST /conversations/{conversation_id}/messages/{message_id}/edits` accepts a saved user `message_id`,
a UUID `request_id`, and optional revised `message` (1-12000 non-whitespace
characters). Omitting `message` retries the original question. It returns an
owned `ChatSession` with `root_conversation_id`, `parent_conversation_id`,
`fork_message_id`, `fork_position`, and `fork_content`; these fields are null
for an original session. The same UUID and revision return the same branch.
Reusing a UUID for different content is rejected with 200100.

The optional `mode` is `revise` by default. `mode: continue` requires a new
`message` and retains the selected question's completed answer before starting
that question on a new branch. Its `fork_message_id` identifies the retained
assistant answer and `fork_position` is the first position after that answer.
An incomplete answer cannot be used as a continuation checkpoint (200100).
Continuation drafts have no new Source attachments: earlier messages retain
their own Source context. Both modes use the existing branch storage and require
an idle session with no unresolved approvals or tool results.

`GET /tree` returns the owned session family's `root_conversation_id`, `active_path`
(canonical user-message IDs), and `nodes`. Each node contains its saved `message`,
`parent_message_id` (the preceding canonical user turn or null), `answer`,
`status`, and `can_branch`. Copied prefixes appear once. Status is `completed`,
`running`, `approval_required`, `failed`, `interrupted`, `incomplete`, or `draft`;
partial answer text comes only from the server-owned response snapshot. A draft
is a synthetic user message with stable `draft_{conversation_id}` identity. The
endpoint checks current user and Workspace ownership and does not mutate state.

Branch creation atomically copies complete turns before the selected question,
assigning new message and call identities while retaining canonical Source and
resource references. Later answers and writes stay in their original branch.
Copied terminal calls describe historical work; they cannot be claimed again.
New writes require a new exact approval. Branching requires both session and
current Workspace ownership, and returns 200204 during execution or unresolved
approval/recovery, 200201 for an unavailable saved user message, and 200100 for an
invalid revision or stale Source.

To execute the saved revision, `POST /messages` accepts `branch_revision: true`
with the exact `fork_content`. The backend restores Source contexts from the
original question for revisions (none for continuations), validates them against current Sources, and accepts this
branch's initial turn at most once. A repeated send returns 200204
`chat_branch_already_started`; the client reads the saved trajectory to recover.
Both ordinary JSON and SSE submission support this behavior.

`POST /conversations/{conversation_id}/tasks/{task_id}/stop` requires the
authenticated session owner and targets the exact current response. It returns
the response snapshot with `stop_requested: true` while execution is stopping.
The request survives ordinary snapshot updates and can be received by a different
Web process. A stale response ID returns `200204` with `chat_response_changed`;
repeating a request for the same finished response returns its terminal snapshot.
The executing turn cancels pending model/read waits, preserves saved observations,
and closes unresolved tool requests before saving response/turn status `cancelled`
and `error_code: user_cancelled`. An already claimed write finishes and checkpoints
first. Partial streamed text stays in the snapshot and is not a completed answer.
GET trajectory, tree and SSE expose the saved cancellation. Once execution
releases the session, an ordinary new message can revise the research direction.
Disconnecting an event stream alone continues to leave execution running.

`GET /messages` also returns `messages/{message_id}/edits` (per-question `message_id`, ordered
`conversation_ids`, and `active_conversation_id`), `branch_draft` (the unsent revision or
null), and `running`. These fields survive browser reloads. Execution uses a
PostgreSQL transaction advisory lock shared by direct Task execution and Conversation commands.
Each running turn holds one dedicated database connection outside the normal
checkpoint pool; transaction completion or connection loss releases the lock.
Browser disconnection does not cancel an already running turn. Apply migrations
through `20260910_0058` before running this version against an existing database.

Answer usefulness feedback is separate from scientific Finding review. For
example, a researcher can mark an LPBF comparison answer incomplete, request
the missing tensile test conditions, revise that assessment, or withdraw it.
This never changes an Objective, Evidence, Finding, approval, or model context.

`PUT /conversations/{conversation_id}/messages/{message_id}/feedback` accepts
`rating: helpful | not_helpful | null`, optional
`reason: incorrect | incomplete | unclear | other | null`, and an optional
`comment` of at most 2000 characters. A reason requires `not_helpful`.
`rating: null` withdraws the record and requires absent/null reason and comment;
the response is HTTP 200 with `code: 200` and `data: {}`. Comments are trimmed and blank
comments become null. Extra fields are rejected.

A non-null rating returns `feedback_id`, `conversation_id`, `message_id`, `user_id`,
`rating`, `reason`, `comment`, `response_digest`, `created_at`, and `updated_at`.
The server computes `response_digest` as SHA-256 of the UTF-8 content of the
canonical saved answer. Identity, authorship, digest, and timestamps cannot be
supplied by the client. One user has at most one current rating per message;
updates preserve identity and creation time, and identical PUTs also preserve
update time. Withdrawal is idempotent and removes the optional details.

The target must be a persisted, non-empty Assistant text message without tool
requests in the owned session. Authentication is required (`200301`); unavailable
session, workspace, or message ownership returns `200201`; ineligible message
roles or invalid input return `200100`. Temporary streaming messages have no saved
identity and cannot receive feedback.

`GET /conversations/{conversation_id}/messages` returns a separate `feedback` array
containing the current user's records, alongside `items` and `pending_approval`.
The immutable message records and turn/stream contracts contain no feedback.
The rating is not supplied directly to a model and does not itself assert that
an answer is wrong. In the current feedback-workbench flow, a saved rating is
an input signal for an internal analysis job. The analysis Worker creates a
candidate case and the task-specific sample process prepares a candidate for
each fixed task; a human then edits or confirms the task sample before an
immutable DatasetExport can include it.

### Conversation answer feedback

Conversation answer feedback remains a small user-facing interaction separate from
scientific Finding review. A researcher can mark a saved assistant answer helpful or
not helpful, add an optional reason and comment, revise the rating, or withdraw it.
The operation does not create an analysis job, FeedbackCase, dataset sample, export,
or model call. It never changes an Objective, Evidence, Finding, approval, or model
context.

- `PUT /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`
- `DELETE /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

The record is keyed by `(user_id, message_id)` and stores the server-computed
`response_digest`. The message must be a persisted, non-empty final assistant text
answer in the owned Conversation. Fork copies do not inherit the source rating. The
message read path projects the current user's `my_feedback` value.

The former FeedbackCase, correction-signal, tool-failure, dataset-sample, snapshot,
and export APIs are retired. Historical migrations may retain their tables and ORM
mappings as one-time data sources, but no current HTTP route, chat send path,
application startup hook, or background consumer imports them. A future feedback
analysis module requires a new contract and implementation.

### Research Objectives

- `POST /api/v1/workspaces/{workspace_id}/objective-discovery`
- `GET /api/v1/workspaces/{workspace_id}/objectives`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/scope`
- `POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis/status`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/analysis`

Discovery accepts `{"document_ids": [...]}` with one or more unique current
Documents. The explicit selection is not truncated or divided into independent
discovery scopes, so candidate formation retains the complete cross-paper
context. Every selected Document must be `ready` with a preparation fingerprint.
The command freezes the resolved `(document_id, preparation_fingerprint)`
values in one workspace-scoped `objective_discovery` Pipeline Run and returns
that run immediately. At most one discovery run may be `queued` or `running`
for a Workspace; a repeated command returns the active run without scheduling a
second worker, even when another request reaches a different backend process.
Clients restore and poll its state through the Workspace Pipeline Run and
run-detail endpoints. On completion they read the replaced candidate set from
`GET .../objectives`; on failure the terminal run error remains visible and a
new command creates a retry run. A backend restart marks an interrupted run
failed rather than leaving it permanently active.

The background worker lazily builds or reuses the selected Documents' current
Paper Maps, reads their Profiles and maps, and replaces the current generated
candidates. It does not silently include all Workspace papers. This is
research-question formation, not Objective Evidence analysis: analysis still
requires the later, explicit Objective command. The worker is process-local,
while admission, progress, completion, and failure are persisted; the Pipeline Run
record is observable execution state rather than an external durable queue.

A Paper Map is preliminary scope metadata: paper type, material and process
themes, variable-to-outcome axes, review synthesis, Source lineage, coverage,
and uncertainty. It does not contain experiment samples, tests, comparators,
fixed conditions, parameter levels, or measurements. Confirmed-Objective
analysis may use it to prioritize Source inspection and surface coverage
warnings, but only facts grounded in inspected Sources may populate Evidence.

`ResearchObjective` is the aggregate root for the research question and its
analysis lifecycle. Its identity is `(workspace_id, objective_id)`. Reusable
paper-owned experiment content has a separate `PaperExperiment` revision
boundary: it is identified by `(experiment_id, experiment_version)` and does
not belong to one Objective. An Objective analysis connects the two through an
explicit `ObjectiveExperimentSelection`; optional cross-paper groups and
Findings are analysis-scoped records, not fields embedded in either aggregate.
The Objective analysis-state and command responses contain:

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
every current Workspace Paper Map and returns each mapped Document exactly once
as `likely_relevant`, `needs_inspection`, or
`confidently_out_of_scope`. The response contains complete
`recommended_document_ids`, `review_document_ids`, and
`excluded_document_ids`, category counts, per-document reasons, Paper Map
status/limitations, support basis, and `is_seed`. A relationship or review
synthesis match is navigation support only; `support_is_evidence` is always
false. Incomplete maps, partial matches, broad-variable uncertainty, and review
citation leads require researcher inspection and are not selected by default.
The endpoint performs no LLM call and persists no scope. An unknown Objective
returns `200201`; a Workspace with no Paper Maps returns
`200204 objective_scope_not_ready`.

`GET .../analysis/status` is the polling projection for the active analysis.
It returns only lifecycle state, phase, processed/total document counts, the
current document, a bounded progress message, terminal error fields, and
timestamps. It does not include Findings, Evidence, contributions, telemetry,
or other scientific result payloads. Clients should fetch `GET .../analysis`
once the status is `succeeded` or `failed`.

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
This REST command is intentionally the legacy Fast Path exception to the
Chat/Agent three-step approval lifecycle. For a candidate Objective it
atomically confirms the Objective and queues automatic analysis; this contract
does not introduce a separate REST confirmation request.
Independent Objective analyses,
including analyses from different workspaces, execute as process-local asyncio
background tasks. An application semaphore bounds simultaneous analysis
execution. Tasks above that limit wait on the in-process semaphore; this is not
a durable application queue. Synchronous model and scientific computations run
outside the event-loop thread, while PostgreSQL reads and writes use awaited,
task-local `AsyncSession` transactions. The repository claim transition still
allows only one task to execute a specific Objective analysis version, and
persisted analysis state remains the status authority queried by the client. If
the backend cannot create the background task, it records that version as
failed and returns `200205`, allowing the client to retry without leaving a
permanently queued version. Only a complete succeeded version can become
published. A succeeded version may have zero Findings when paper contributions
and source-backed Evidence were published but no defensible comparison
survived; this is a scientific abstention, not a technical failure. The Finding
list then returns `total=0` without a placeholder Finding.

`analysis_service` owns queue-and-dispatch for this HTTP command and
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

PaperContribution is analysis-level coverage metadata, not a PaperExperiment
field or scientific evidence for a Finding. Finding authoring
copy the source analysis coverage into the new version, including excluded and
failed papers with no experiment revision. This preserves the original input
processing record; it does not assert that every paper supports the new Finding.
The metadata is saved in the same publication transaction as the experiment
graph. Finding synthesis consumes only fixed experiment revisions and their
Selections and ComparisonGroups; it never consumes PaperContribution.
Authored Finding graph snapshots retain the source analysis version and user
identity. PaperExperiment authoring saves paper facts independently and creates
no analysis snapshot or copied coverage. A later automatic analysis may reuse
current fixed revisions after validating the routed Source coverage and the
Objective's required facts; otherwise it extracts new revisions.

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

- `POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings`
- `POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/evidence-map`

Finding and Evidence list endpoints support `offset` and `limit`. All responses
include an explicit `analysis_version`. If omitted from the query, the backend
uses the published Objective version. Evidence accepts an optional `finding_id`
filter.

Finding lists include `evidence_reviews`, keyed by the returned Finding IDs;
Finding detail includes `evidence_review`. Each contains `needs_review` and
`evidence_replacements` (referenced Evidence ID to its latest replacement ID,
or `null` for an unresolved lineage). The projection covers support,
contradiction, and context/condition references in the selected published
snapshot. It is separate from the canonical Finding and from expert curation.
An updated input requires reassessment, not automatic scientific rejection.
A parent remains a historical judgment even after a child is saved; readers
can follow `parent_finding_id` to distinguish original and revised conclusions.

Evidence reads expose `eligible_for_finding_authoring`: the Evidence must be
structurally eligible and not superseded. `supports_finding` retains its
historical structural meaning. New Finding writes reject superseded Evidence
in every selected role with `200204`; existing Findings retain their original
Evidence and remain readable. Replacement never transfers a scientific role
automatically.

Each Finding and Evidence record exposes its `origin`, optional
`created_by_user_id`, and optional `created_by_tool_call_id`. The tool-call field
is populated for an `agent_authored` record and for an Agent-assisted revision;
it is `null` for system-generated and ordinary direct human-authored records.
It is durable authoring provenance, not scientific support; Evidence remains
grounded through its Source identity and a Finding remains supported through
its version-local Evidence bindings.

The Findings POST command selects one Finding already aggregated from a fixed
experiment analysis snapshot. The request identifies the
`source_analysis_version`, one or more `selection_ids`, and optional
`comparison_group_ids`. The authenticated user identity is server-derived;
the conclusion, factors, outcome, direction, and evidence projection remain
derived from the experiment records. Paper coverage, factors,
outcome, direction, attribution, synthesis status, certainty, target version,
and Source content are also server-derived and cannot be supplied by the
browser.

```json
{
  "source_analysis_version": 3,
  "selection_ids": ["selection-1", "selection-2"],
  "comparison_group_ids": ["comparison-group-1"]
}
```

A successful command returns `code: 200` with a new immutable analysis snapshot and
the canonical Finding synthesized from the requested selection/group set.
Unknown selections, groups, or an unaggregated combination are rejected; the
source snapshot remains unchanged.

Optional `parent_finding_id` must identify a Finding in the source experiment
analysis graph. The new Finding records that parent, hybrid origin, source
analysis version, authenticated author, and authoring time. Optional
`limitations` are trimmed, deduplicated, and appended to synthesized scientific
limitations (at most 20 supplied entries, 1000 characters each). They do not
replace the Source-grounded conclusion or its experiment selections.
Experiment-backed Finding responses expose their `selection_ids` and optional
`comparison_group_ids`; their legacy Evidence `paper_contributions` may be
empty because selections carry that support. A one-study Finding uses
`synthesis_status=single_study`. Responses require either paper contributions
or experiment selections rather than accepting an unsupported conclusion.

A researcher may instead submit one of `no_comparable_evidence`,
`no_grounded_evidence`, or `insufficient_evidence` as `abstention_reason`, with
an explanatory `limitations` entry and no selections, comparison groups, or
parent. The new version retains the source analysis's document coverage.

The new analysis version records the abstention as metadata and creates no
placeholder Finding. An unauthenticated request returns `200301`; missing or
unowned workspaces and missing Objectives return `200201`; stale source versions,
concurrent analysis, unknown or ineligible Evidence, and scientifically
inconsistent role selections return `200204`; malformed request shapes return
`200100`.

### Paper Experiment Analysis Projection

The experiment-domain migration adds read-only routes; it does not replace or
change the Objective, Finding, Evidence, or Agent request contracts above:

- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-analysis?analysis_version={n}`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-analysis/export?analysis_version={n}&format=json|csv`

Both routes require a positive, explicit `analysis_version` and read the same
fixed Selection, optional ComparisonGroup, Finding, and PaperExperiment
revisions. The JSON projection preserves relations and source references; the
CSV projection is a long table with one selected reported measurement per row.
The export never uses a later experiment revision implicitly and never turns a
derived difference into a reported measurement.

Each CSV row keeps the selected measurement together with its experiment and
Selection identity, variant label and subject/intervention/state/population
context, applicable test method/protocol/population context, binding status,
comparison keys, and Source references. Structured values remain JSON-encoded
inside their CSV cells. The export does not infer missing conditions, pair
different specimens merely because they share a group label, or silently
average repeated measurements.

A partial PaperExperiment revision that has no eligible Objective Selection is
kept as an archive for later targeted rereading. A partial revision can still
have an eligible Selection for a concrete, source-bound Objective slice; only
the unresolved measurements are absent from these Selection-based projections.
An incomplete archive without an eligible slice cannot appear as usable
Evidence or a Finding. Such a revision remains discoverable through the
PaperExperiment repository/document lineage rather than through an Objective
analysis export.

These are additive capabilities. Existing route paths, request parameters,
authentication, task states, and response meanings remain frozen while the
internal scientific records are migrated. A client that does not use these
routes requires no request change.

The Evidence POST command records one source-grounded Evidence decision from a
specific prepared Document Source. It accepts `source_analysis_version`,
`document_id`, `source_kind` (`text_window | table | figure`), `source_ref`, an
exact `source_excerpt`, an Evidence role, optional changed variables,
comparison, reported result, attribution scope, and scientific context. The
server checks workspace ownership, the published analysis version, the
analysis document scope, the Source locator, and that the normalized excerpt
is a substring of the canonical Source. It derives identity, page, resolution,
confidence, and creator provenance. The browser cannot provide a creator,
analysis target version, or Source outside the selected analysis.

Evidence remains available through read-only projections for historical analyses
and source traceback. New researcher and Agent writes use the reviewed
PaperExperiment draft and the approved `create_paper_experiment_revision`
capability; that write validates the complete Source digest, creates an
immutable paper-local revision, and does not start or publish Objective
analysis, create an Objective Selection, or create a Finding. A later Objective
analysis may select the fixed revision for comparison. Historical Evidence
records remain readable, but no new Evidence version or independent Evidence
identity can be created through the browser or Agent.

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

An optional reading summary is available through
`POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}/summary`.
The authenticated Workspace owner supplies `analysis_version` (positive integer)
and `language` (`en` or `zh`, default `en`), not browser-provided evidence.
The service reads the published Finding and all its linked Evidence, then asks
the configured model for one short paragraph. The response contains `text`,
`citation_ids`, exact Source `references`, scoped identity, language, model,
prompt version, and generation time. It has no section arrays or record counts.
The summary is transient: it creates no analysis version and changes no Finding,
Evidence, or review. Known citation IDs are checked, not the scientific truth of
every generated sentence. Original records remain authoritative.

Missing Findings return `200201`; a changed or absent published version returns
`200204` with `summary_stale_analysis`, including if it changed during generation.
Unavailable summaries return `200205` with a safe `summary_*` reason code. Missing
linked Evidence or input exceeding 200 records or the 24,000-token prompt budget
is rejected explicitly, never silently truncated. Summary failure does not fail
or replace the published analysis. Clients discard responses after changing the
Workspace, Objective, Finding, version, or language.

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
Test and characterization attributes may also include
`applies_to_outcomes`, listing only outcomes that the same Source explicitly
says the method measures or characterizes. An empty list means that the method
remains auditable paper context but cannot be assumed to apply to a particular
result.

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
(workspace_id, objective_id, analysis_version, finding_id)
```

Direct contributing paper count is computed from PaperContribution Evidence
bindings rather than stored as a second declaration. `agreement`, `conflict`,
and `condition_dependent` require direct results from at least two distinct
papers; otherwise synthesis remains `insufficient_confirmation`. Context-only
Evidence cannot establish an outcome, and repeated rows from one paper do not
count as independent cross-paper confirmation.

### Finding Feedback, Curation, And Dataset Export

- `POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}/feedback`
- `PUT /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/finding-dataset`
- `GET /api/v1/workspaces/{workspace_id}/finding-dataset`
- `GET /api/v1/workspaces/{workspace_id}/finding-gold-draft`

Feedback requires `analysis_version`, `review_status`, and `issue_type`.
Curation requires `analysis_version` and one complete canonical
`curated_finding`. The service validates its exact identity and every
version-local Evidence/PaperContribution binding. Unknown, stale, unpublished,
partial, and cross-version references return `200201`, `200204`, or `200100` and are
never silently rebound.

Optional `curated_finding.created_at` is parsed as a datetime by the request
model. Invalid timestamps return `200100` before curation runs. JSON timestamps
remain ISO 8601 strings with their UTC offsets preserved.

The Finding workbench and Research Agent share these same service operations.
The Agent first reads the complete published Finding and linked Evidence,
inspects exact Sources as needed, and proposes the same feedback or curation
arguments. The write runs only after the authenticated user approves those
exact arguments. Chat does not own a second Finding identity or review store.

Finding authoring is distinct from review. The Agent may propose a new
Evidence-to-Finding decision only from `supports_finding` Evidence in the exact
current published version. The approved capability calls the same
`finding_authoring_service` as the HTTP workbench, including immutable version
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

- `GET /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-plans`
- `POST /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-plans`
- `PATCH /api/v1/workspaces/{workspace_id}/objectives/{objective_id}/experiment-plans/{plan_id}`

Plans are human-editable downstream drafts, not scientific source records.
The HTTP POST creates a manual draft without Chat provenance. The Research
Agent can propose the same Objective-scoped plan structure and, after exact
approval, save it through the same `experiment_plan_service`. Agent-created plans
store the approved tool-call identity, visible Evidence links, and complete
Finding/Evidence fingerprints. Reads recheck those snapshots; stale grounded
plans cannot be promoted to `ready_for_review`. Historical plans that reference
a migrated Chat message retain their existing lineage and validation rules.
Saving a plan never schedules or claims that an experiment was executed.
`PATCH` is a partial update: omitted fields retain their previous values and
the request must include at least one of `title`, `content`, `status`, or
`structured_plan`. The service creates a new immutable plan revision; it does
not mutate the historical revision addressed by `plan_id`.
Only one successor can be saved for a parent revision. A second update returns
`200204` with `data.code: experiment_plan_revision_superseded` and the parent
plan ID; it creates no revision and leaves the accepted successor intact.
An attempted overwrite or duplicate revision identity also returns `200204`,
with `experiment_plan_revision_immutable` or
`experiment_plan_revision_identity_conflict` and the affected plan identity.

### Documents And Source Verification

- `GET /api/v1/workspaces/{workspace_id}/documents/profiles`
- `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/profile`
- `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/content`
- `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/markdown`
- `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/source`
- `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/figures/{figure_id}/image`
- `GET /api/v1/workspaces/{workspace_id}/references`
- `POST /api/v1/workspaces/{workspace_id}/references/build`

The document reader shows parsed paper content and supports precise Source
navigation. A Finding Evidence link names the owning document, stable
`source_ref`, and page when available. Internal Source IDs are audit/navigation
parameters, not visible paper titles.

The document-profile list accepts `offset`, `limit`, and optional `query`,
`doc_type`, and `has_warnings` filters. `query` performs case-insensitive
matching against the profile title. `doc_type` accepts
`experimental`, `review`, `mixed`, or `uncertain`; `has_warnings` filters by
whether profile-classification warnings are present. Profile items contain
`document_id`, `title`, `doc_type`, `profile_warnings`, and `confidence`;
workspace ownership and filenames remain on the workspace's Document records.
All active criteria are combined before
pagination. `total` is the number of matching profiles, `count` is the current
page size, and `summary.total_documents` remains the complete profiled
workspace size.

The browser comparison overview has no separate comparison aggregate endpoint.
It reads the Objective list and each published Finding list described above.
Legacy research-view, Materials, comparable-result, Evidence-card, and
workspace-wide Graph routes are not part of the maintained HTTP contract.

## Error Contract

All application JSON success and failure responses use HTTP 200 and
`{code, message, data, meta}`. `code` is numeric, `meta` is null unless supplied,
and an absent result has `data: {}`. Successful commands, including creation,
queuing and deletion, use `code: 200`; queued/running is expressed by the result's
own execution state. The schema in OpenAPI describes the envelope around each
existing response model.

| Business code | Meaning |
|---|---|
| `200` | Success |
| `200000` | Unexpected internal failure; diagnostic details stay in server logs |
| `200100` | Invalid external input or rejected request decision |
| `200201` | Resource missing or hidden from the caller |
| `200202` | Method not allowed |
| `200203` | Permission denied |
| `200204` | Stale version, invalid state, approval or write conflict |
| `200205` | Required work could not be scheduled or a dependency is unavailable |
| `200301` | Missing/expired authentication or invalid login credentials |

Stable reason strings and relevant resource IDs live in `data`, for example:

```json
{
  "code": 200204,
  "message": "The published analysis has changed. Reload before generating a summary.",
  "data": {"code": "summary_stale_analysis"},
  "meta": null
}
```

The centralized handlers cover explicit application errors, framework not-found
and method errors, request validation, and unexpected exceptions. Builtin
`ValueError`, `FileNotFoundError`, or `RuntimeError` is not automatically a client
error. Public messages never include provider responses, credentials, or stack
traces. Request correlation remains available through `X-Request-ID`.

File successes keep their media type and bytes, with encoded `filename*` headers
where applicable. Document Source and figure reads always use
`inline; filename*=UTF-8''` followed by the percent-encoded filename.
SSE successes remain `text/event-stream`. A failure before a
file/SSE response starts uses the JSON envelope. After SSE starts, failure uses
an `error` event; cancellation still releases the stream and execution lock.
An enqueue failure after saving feedback reports the saved feedback ID, and an
analysis scheduling failure reports its already allocated version. These
failures do not imply that earlier durable writes were rolled back.

## Frontend Integration

- Use same-origin requests through the shared API helper; `requestJson` returns
  `data` and raises `ApiError` for any business code other than 200.
- Authentication expiry uses `200301` plus `authentication_required`; an HTTP
  status or arbitrary error string is not an authentication decision.
- `requestBlob` checks JSON failures before downloads, keeps actual file bytes,
  and unwraps ordinary successful JSON exports. SSE readers verify the response
  media type before parsing events.
- Poll only queued/running Pipeline Run or Objective analysis states.
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
