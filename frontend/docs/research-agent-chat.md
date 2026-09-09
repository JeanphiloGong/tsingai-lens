# Research Agent Chat Interface

## Purpose

This document owns the browser presentation contract for the collection-bound
Research Agent. Chat is the only supported assistant-session runtime; the
retired Goal-session design is not a compatibility contract.

The Assistant route presents one durable interaction:

```text
User message
  -> model response or capability request
  -> structured capability result
  -> model continuation
  -> final answer or exact write approval
```

Ordinary conversation does not require a capability. The Agent receives a
small, intent-matched set of collection, Source, Finding, Objective, or plan
actions for each decision; it does not receive the whole capability catalogue.
Collection screening stays separate from Source reading, and deriving a new
Objective requires an explicit request. A Core write remains paused until the
user approves the exact persisted arguments.

## Product Boundary

The Research Agent helps a materials researcher inspect a collection, ask what
the published analysis supports, formulate a focused candidate question,
review an existing published conclusion, and propose a new conclusion from
eligible published Evidence through the same controls as the Finding
workbench. It does not replace the comparison workspace or become a second
scientific fact store.

- Chat owns sessions, ordered messages, capability activity, and approval
  decisions.
- Core owns Research Objectives, Evidence, Findings, and Analysis.
- Current Documents and their preparation Pipeline Runs remain the runtime
  authority for paper preparation progress. Chat reads that state; it does not
  persist another workflow.
- Paper Map relationships may support an Objective proposal but are labeled as
  proposal context, never Evidence.
- Preparing papers and starting Objective analysis are separate approved writes.
  Preparation targets exact Documents; analysis targets an exact non-empty set
  of ready Documents.
- A created Objective remains an unconfirmed candidate. The Agent may propose
  `confirm_objective`, but the researcher must approve that exact action.
  Starting automatic or Agent-authored analysis is a later, separate approval;
  confirmation alone never queues work. The existing Objective workspace may
  still combine the researcher's confirmation and automatic-analysis start in
  its established browser action.
- A Finding review begins from the complete published Finding, linked Evidence,
  and exact Sources. Feedback and curation reuse `FindingFeedbackService` after
  exact user approval.
- Finding authoring begins from the current published analysis and its complete
  role-eligible Evidence. The Agent may propose exact Evidence roles, a bounded
  conclusion, or an explicit evidence abstention. After exact user approval,
  `FindingAuthoringService` publishes a new immutable analysis version. The
  Agent cannot alter the source version, parent Finding, Evidence, or Source
  identities.
- `create_evidence_version` is a `write` capability. It accepts one exact
  Source returned by `inspect_document_sources`, a verbatim excerpt, and the
  structured Evidence fields. The Agent must supply the Source digest; the
  backend verifies the canonical Source, analysis scope, and scientific shape.
  Exact user approval publishes a new immutable analysis version. A revision
  records supersession lineage and never changes the previous Evidence or any
  Finding that cites it.
- `read_source` is the exact Source-reading capability used before Evidence
  drafting. It returns complete text, table Markdown, or a figure caption when
  the bounded response fits, plus the canonical digest and continuation state
  for oversized content. A returned Source remains inspection context until a
  separate Evidence draft and approved write are completed.
- Research-plan prose becomes a transient structured draft first. The separate
  approved save rechecks the current Finding and Evidence fingerprints, then
  uses the same Objective-scoped ExperimentPlan service as the human workflow.
  Saving creates an editable draft; it does not authorize or execute an
  experiment.

## Browser Contract

The route uses only same-origin endpoints:

```text
POST /api/v1/chat-sessions
GET  /api/v1/chat-sessions/{session_id}
GET  /api/v1/chat-sessions/{session_id}/messages
POST /api/v1/chat-sessions/{session_id}/messages
POST /api/v1/chat-sessions/{session_id}/branches
PUT  /api/v1/chat-sessions/{session_id}/messages/{message_id}/feedback
POST /api/v1/chat-sessions/{session_id}/tool-calls/{tool_call_id}/decision
```

The composer also exposes an explicit PDF-paper upload action for the current
Collection. It calls the same `POST /collections/{collection_id}/documents`
and per-document preparation endpoint used by the Collection workspace. The
upload is a user action outside the Chat trajectory: PDF bytes are never sent
to the model or stored as a Chat attachment, and uploading does not create an
Objective, Evidence, or Finding. Each file reports its own stored, preparing,
queued, upload-failed, or preparation-failed state. A preparation retry reuses
the stored document ID, while the Collection workspace remains the canonical
view for long-running Pipeline Run progress.

If an upload response is lost, retrying can find the file already stored. The
composer retries the upload with `reuse_existing=true`. The import service
matches the normalized bytes by SHA-256 inside the owned Collection and returns
the existing Document, preserving its preparation state. The composer then
prepares that exact document ID. This works on ordinary HTTP installations
without browser hashing or filename-based matching. If recovery fails, the
paper keeps an explicit failure and retry action instead of being marked complete.

Message submission uses `Accept: text/event-stream` on the existing `POST
/messages` endpoint. The browser appends `text_delta` events to one temporary
assistant message, then replaces the temporary user/assistant pair with the
complete `turn` event returned after server persistence. Tool requests,
results, warnings, resource links, and approval state therefore continue to
come from the authoritative final turn rather than from partial model text. If
the stream is interrupted, the browser reloads the durable trajectory before
offering a retry.

A failed approval response or an empty idempotent acknowledgement triggers a
trajectory reload. The saved tool result, resource links, and current approval
state are restored together. If both the decision response and the recovery
read fail, the approval remains retryable using its original identity.
An unresolved persisted tool request retains a result-confirmation indicator
and Check result action beside its activity, including after conversation retry
or page reload. The page reads the trajectory every three seconds until the
result or an approval boundary is available. Read failures keep the confirmation
state and retry action; they do not imply a scientific failure. The composer
stays disabled while that result is unconfirmed, and recovery never resubmits a
write. Leaving the session or account cancels its timer and request and ignores
late results.

The selected session ID and a small presentation-only history are stored under:

```text
lens.chatSession.{encoded_user_id}:{encoded_collection_id}
lens.chatSessionHistory.{encoded_user_id}:{encoded_collection_id}
lens.chatSourceContext.{encoded_user_id}:{encoded_collection_id}
```

Chat waits for an authenticated account before reading these keys. Successful
authentication retains only that account's entries and removes unscoped legacy
entries. Logout clears Chat browser storage, including pending Source handoffs,
even if its HTTP request fails; it does not delete server conversations.
Logout also invalidates other open tabs through a browser storage event. Those
tabs clear their account state and pending Sources, leave the conversation, and
ignore late authentication and Chat responses.
A new login in the same tab waits for its pending logout request to settle
before setting a new session cookie. The old logout completion does not clear
authentication or navigate again; logout failure still permits a subsequent login.
An unavailable session read preserves its history entry and offers a retry of
that exact session. Only an explicit `404` removes the missing session and
creates a replacement; network errors and other HTTP failures remain visible.

The server trajectory is authoritative. Browser storage remembers which
session to load, how to label it in the local history list, and up to 12 pending
Source blocks from the document reader. Pending blocks are shown above the
composer and can be removed individually. They are cleared after the complete persisted turn
returns, or when recovery after an interrupted stream confirms that the sent
message and its Source locators were persisted. If persistence cannot be
confirmed, the pending Source remains available for retry. This check also runs
when returning to a conversation or reloading the page. A pending handoff records
its submitted session, question, and preceding message so an older use of the
same Source cannot consume a new submission. Selecting a Source again starts a
new handoff. These submission markers stay in browser storage and are not sent
as scientific context. The durable user
message then owns the Source context. The browser
sends the canonical locator kind (`text_window`, `table`, or `figure`) and a
bounded quote. The backend resolves that locator against the immutable prepared
Source, rejects forged or stale context with `422`, and persists canonical
title, location, link, quote, and full-Source digest metadata. The browser does
not establish Source authenticity itself, and a verified context is still not
Evidence until the Evidence authoring contract is completed.

## Reply Content

Assistant replies use MarkdownIt for paragraphs, headings, ordered and nested
lists, quotations, links, fenced code, and comparison tables. KaTeX renders
inline `$...$` and `\(...\)` expressions and display `$$...$$` and `\[...\]`
equations, including formulas inside table cells. The same renderer formats
inspected Source tables without changing their values or canonical Source links.
Rendered prose and tables remain presentation, not newly verified Evidence.

Tables, code blocks, and display equations scroll within the reply on narrow
screens. KaTeX fonts are bundled locally, with MathML retained for assistive
technology. Streaming reuses the same renderer: an unfinished display formula
remains readable text until its delimiter closes, and invalid completed math
retains its source text instead of breaking the rest of the answer.

Raw HTML is escaped, unsafe Markdown links are rejected, and model-authored
images remain captions without starting external requests. Inspectable images
continue to belong to Source artifacts. KaTeX runs with `trust: false`, bounded
macro expansion and size, and fresh macro definitions for each render. This
prevents formulas from enabling external resources or affecting later replies.

## Answer Feedback

Each saved Assistant text answer has Helpful and Not helpful icon toggles
directly below its content. User messages, tool requests/results, and temporary
streaming text have no feedback controls. Selecting the active rating withdraws
it; selecting the other rating replaces it and clears the previous details.

A negative rating is saved immediately and opens an inline editor for an
optional reason and comment. Either rating can be supplemented using Edit
feedback. Cancel/Escape discards the editor draft while preserving the saved
rating. Save persists the details; an error leaves the input intact and shows a
local retry message. Busy controls prevent duplicate in-flight submissions.
Icon controls have labels, tooltips, and pressed state; the editor focuses its
comment input and respects reduced motion and narrow viewports.

`ResearchConversation.svelte` owns the message-keyed saved state, errors, and pending requests.
It restores feedback from the trajectory's separate `feedback` array and
aborts/ignores stale responses after session, collection, or account changes.
`MessageFeedback.svelte` owns the per-answer editor. No feedback is stored in
browser storage or sent as a conversation message or scientific review action.
See the backend API authority for the persistence and authorization contract.

The verification scenario starts with a saved answer comparing LPBF tensile
results under differing conditions. The researcher rates it, requests missing
test temperatures and Source links, retries a failed save, refreshes to recover
the details, changes the rating, and withdraws it. Browser tests cover this
sequence at 320, 768, 1024, and 1440 pixels; PostgreSQL integration tests cover
the actual authenticated API, concurrent upserts, cascades, and migration.

## Message Revisions

A researcher comparing LPBF tensile results may revise an earlier question to
restrict the comparison to specimens tested at the same temperature, or retry
an answer that failed. The sent user message owns its edit action; the final
assistant answer owns its regenerate action. A question with no final answer
also exposes retry beside the user message. Editing supports cancel, Escape,
Enter to submit, and Shift+Enter for a newline; IME composition never submits.

Both operations create a durable conversation branch before the selected user
turn. The original question, answers, approvals, and research artifacts remain
available. Earlier complete turns retain their Source and result references.
Version arrows beside the question switch between alternatives, including
after a reload. Later edits form their own version group.

The branch stores its intended question before generation. A lost branch
creation response can be retried with the same request UUID, and an unsent
revision remains available after reload. Sending that revision is accepted at
most once. Its Source contexts are restored and validated by the backend from
the original saved question. Unrelated composer text, selected papers, and
pending Source handoffs are not consumed by editing or regeneration.

While loading, generating, recovering, or awaiting approval, revision actions
are disabled. The backend also serializes turns and branch creation across
workers. A disconnected browser can poll the persisted trajectory and its
`running` flag, including when no tool request has been produced yet.
Completed writes remain historical observations. A newly proposed write always
requires a fresh exact-argument approval and cannot reuse a historical call.

`ResearchConversation.svelte` owns requests, branch recovery, and version
selection. `UserMessage.svelte` owns the local edit draft and keyboard/focus
behavior; `MessageTimeline.svelte` associates each answer with its user turn.
No second runtime or client-side conversation store is introduced.

## Presentation Architecture

The route follows the same message-first composition used by Open WebUI while
keeping Lens-specific research boundaries explicit:

- `+page.svelte` is the standalone route entry. `ResearchConversation.svelte`
  owns session orchestration, streaming, and approval state for both that route
  and the documents split workspace. It does not create a second browser API or persistence
  model. Each session load has a request generation and abort signal; collection
  changes, account changes, and unmounting invalidate pending reads, streams, and approval
  responses before they can update the current conversation or local history.
  Disconnecting the browser does not revoke an approved backend write; returning
  to the original session reloads its authoritative trajectory and approval state.
- `ResearchSidebar.svelte` owns collection navigation, session history, and
  the responsive desktop/mobile navigation rail. It receives presentation data
  and callbacks from the route; it does not load or persist sessions. On small
  screens the history rail is collapsed behind an explicit toggle so session
  switching remains available without consuming the conversation viewport.
  Collection context stays visible on mobile and displays the name from the
  shared Collection store loaded by the parent layout. Missing names use the
  existing untitled label; identifiers remain in navigation URLs. Long names
  are truncated with the full name available on hover.
- `ConversationHeader.svelte` is a compact toolbar showing the conversation's
  first question and optional Objective link. An empty conversation without an
  Objective has no toolbar. It does not repeat the Research Agent brand or the
  Collection context. Runtime status, elapsed time, and progress history belong
  to the corresponding Assistant response.
- `MessageComposer.svelte` owns the composer, PDF handoff presentation, and
  collection-bound upload state and orchestration. It sends on Enter, preserves
  Shift+Enter and IME composition, and grows the textarea up to a bounded height.
  An upload already started finishes its upload/preparation chain against the
  original collection. Navigation drops its UI updates and stops the remaining
  batch from starting; it does not move papers to the newly selected collection.
  Account changes clear the attachment UI and prevent an uploaded paper from
  starting preparation under a different account. On constrained viewports,
  attachments and pending Source context share a bounded scroll area above the
  input, keeping the send control visible alongside a long question. Timeline
  spacing scrolls with its content so it cannot overlap this input area when
  the available height shrinks.
- `MessageTimeline.svelte` owns history rendering and scroll position. It starts
  with the latest 20 presentation items and exposes earlier items in batches of
  20 while preserving the reading position. New turns follow the latest response;
  scrolling up suspends following until the researcher returns to the bottom.
- `UserMessage.svelte` and `AssistantMessage.svelte` own role presentation.
  `MessageContent.svelte` owns safe Markdown/math formatting and the transient cursor;
  `ResearchProgress.svelte` owns the response-local progress disclosure.
- `ResearchActivity.svelte`, `ResearchArtifact.svelte`, and `ApprovalPanel.svelte`
  own capability activity, reviewable research outputs, and exact write decisions.
  Shared result links and warnings retain one rendering path; the capability
  presentation helpers use the already-associated tool name instead of searching
  the conversation on every render.
- `_shared/IconButton.svelte` owns icon command sizing, disabled and focus states,
  and hover/focus labels for upload, send, and return-to-latest actions.
- `conversationPresentation.ts` converts the durable trajectory into ordered
  message, activity, and artifact items. This keeps grouping and display
  policy out of the transport callbacks. Streamed text is separate from the
  trajectory and is flushed at most once per animation frame, so text deltas do
  not rebuild historical activity groups. The final persisted turn replaces
  the transient response.
- The message timeline gives each role a stable visual grammar: user content
  is a right-aligned bubble, Assistant text is an open reading column with an
  avatar and inline progress, and evidence-bearing artifacts retain the
  stronger framed treatment needed for review.
- State history and capability activity are native disclosures. Their
  transitions are short and reversible, while `prefers-reduced-motion`
  disables non-essential movement. Status labels remain observable research
  stages; hidden model reasoning and provider internals never enter the view.
- The header, timeline, and composer share a 900px reading measure. The
  sidebar is a navigation rail on desktop and a compact collection/session
  bar on mobile. The composer remains the final focus target and honors the
  device safe area.

This composition is intentionally a presentation boundary, not a new domain
layer: server trajectory data remains authoritative, and structured result
cards continue to link to the canonical Collection, Objective, Finding,
Evidence, and Source routes.

## Visible States

### Empty and ordinary conversation

The page offers realistic prompts for collection overview, published Findings,
and focused Objective proposals. A greeting or general conversational response
is rendered incrementally as a normal assistant message with no fake capability
activity. A stable response cursor occupies the assistant row before the first
text delta; it does not create a stored partial message.

While a turn is running, the Assistant response owns an inline status history.
It names the current research phase and shows available progress signals such
as cycle, completed/requested research actions, and elapsed time. Earlier
observable stages can be expanded from the current status line. These are
bounded user-facing measures; hidden model reasoning, provider calls, and
internal budgets remain undisclosed.

### Document Source handoff

Source-mapped paragraphs, list items, figures, tables, and parsed-source blocks
offer an action to ask the Research Agent. The handoff opens the Agent for the
same Collection and preserves the document, Source kind/reference, page,
heading, canonical return link, bounded quote, and any explicit shortened-quote
state. The user reviews that
context and writes the actual question before sending it.

The Papers list supports individual selection and selecting the current page;
selection survives pagination and filtering. The selected paper titles and
canonical reader links are included in the question, so the selected scope is
visible in the persisted message. Selecting papers does not imply that they
have been read or establish a server-enforced tool scope.

The documents layout owns the split workspace and its local selection state.
On desktop, the paper list or reader remains beside the conversation; on narrow
screens, closing the conversation returns to the mounted reading surface.
Collapsing the panel keeps the same conversation and ongoing work mounted.
New session creates a separate session in the same Collection and retains
unsent selections; opening the panel alone resumes the current session.
The standalone route and split panel both use `ResearchConversation.svelte`,
which owns session loading, streaming, approvals, and recovery.

The reading area keeps one tab per opened paper. `DocumentTabs.svelte` owns tab
selection and keyboard controls; the documents layout owns the opened tabs and
the primary and comparison pane assignments. `DocumentReader.svelte` receives
an explicit Collection, document, and Source-location request. Each mounted
reader retains its reading mode and scroll position across tab switches within
the workspace. Closing a tab releases that reader without removing its pending
Source selections or changing the conversation. Leaving the documents workspace
or reloading restores the canonical document URL, not the entire tab arrangement.

At desktop widths of at least 1100 pixels, researchers may compare two open
papers side by side. Both paper and conversation separators support dragging
and keyboard adjustment with bounded widths. Narrower viewports show the active
paper while retaining the comparison choice; at 820 pixels and below, the Agent
and reading area alternate. Opening an Agent citation activates the matching
paper tab and locates its Source within that reader only. Repeating a citation
repeats the location request without refetching the document. Parsed Source
locators, PDF page navigation, and fit-width rendering are scoped to each reader.

Opened tabs, selected question context, and completed Agent reads remain distinct:
opening a paper does not add it to a question or claim the Agent inspected it.
The selection disclosure reviews and removes pending passages from all open or
closed paper tabs. Sent context remains in the user message, while actual Agent
reads remain observable through the conversation's capability results and Source
links. An unavailable paper shows an error and retry in its own pane; other open
papers and the conversation remain available.

Clicking a source-mapped paragraph, list item, table, or figure toggles that
whole block in the pending question context. Selected blocks use a background,
edge marker, and check mark; there is no separate checkbox or selection mode.
The native selection button remains available to keyboard and assistive-technology
users, with focus shown around its block. Dragging to copy text and clicking a
link or another control do not toggle the block. Duplicate locators cannot create
duplicate attachments. The composer can request inspection of related sections in those
papers; this option is enabled initially in the split workspace. Its explicit
request becomes part of the saved question and asks for exact links, supporting
or conflicting passages, and disclosure of unread or unavailable content.
It is a research request, not a guarantee that relevant passages exist or that
the model will find every one. New selection is disabled during an active turn.

The selected Source is context, not Evidence. Opening the Agent creates no Core
record, and Agent prose cannot become Evidence or a Finding without a later
explicit, grounded workflow. Any write capability remains subject to the same
exact-argument approval contract.

### Capability activity

Assistant capability work remains separate from the final answer, but the
browser does not give every technical operation equal visual weight.
Consecutive routine reads are combined into one compact native disclosure.
Successful work is collapsed by default; queued work stays labeled in
progress, and failed work or work with warnings opens automatically. The
disclosure names the user-facing research actions and their bounded summaries,
not provider calls, prompts, model reasoning, JSON payloads, or retry mechanics.
A checkpointed capability request without a result remains visible as prepared
research activity after reload.

One assistant message can contain an ordered `tool_calls` batch. The browser
matches each request to its own result by durable call ID and preserves request
order, even when reads finish concurrently. An individual failed read does not
hide successful results from the same batch.

Reviewable research outputs remain visible outside that disclosure. These
include Objective drafts, research-scope previews, literature and Objective
analysis status, a complete Finding inspection, and the canonical outcome of
an approved Objective, Evidence, Finding, or Agent-authored analysis write.
Their result panels show:

- the named Lens capability;
- a bounded human-readable summary;
- bounded paper Source match counts and canonical Source links;
- one complete published Finding with paginated linked Evidence when a review
  needs exact scientific context;
- structured Objective drafts when present;
- the observable research stages and active paper when process status is read;
- per-paper stored, processing, ready, and failed states;
- selected PDF papers and their upload/preparation state when papers are added
  from the composer;
- warnings and scientific absence;
- links to canonical collection, Objective, Finding, or Evidence records;
- a distinct Agent paper-analysis activity whose completed summary reports the
  number of published Source-grounded Evidence records and links to the
  canonical Objective analysis. An inspected paper with no grounded Evidence
  remains visible through its explicit paper disposition instead of receiving
  an invented Evidence record;
- transient Evidence/Finding drafts, derived-question drafts, quality results,
  and research-plan drafts with their source links and review status.

A tool request paused for approval is represented by the approval panel only;
the browser does not duplicate it as a second activity row. Images or embedded
media are presented only when a capability returns a real inspectable research
artifact. The browser does not synthesize decorative screenshots for routine
tool work.

A `queued` capability result is rendered as started rather than completed. It
shows the canonical analysis or Pipeline Run link and lets the researcher continue the
conversation instead of waiting for the long-running operation.

Raw tool JSON is not presented as an assistant claim.
The process view shows persisted stage decisions and warnings, not model
chain-of-thought, prompts, JSON repair, or retry mechanics.

### Write approval

For `start_research_process`, `create_objective_candidate`,
`confirm_objective`, `start_objective_analysis`, `record_finding_feedback`, `curate_finding`,
`create_finding_version`, `create_evidence_version`,
`publish_agent_objective_analysis`, and `create_research_plan`, the page renders the exact persisted
arguments and exposes explicit Reject and Approve actions. Finding feedback and curation are
separate writes against an existing published Finding. Finding authoring is a
separate Evidence-to-conclusion decision that publishes a new immutable
analysis version. Agent-authored Objective analysis is also distinct from the
automatic analysis command: it publishes the Agent's reviewed Evidence first
and creates no Finding. While approval is pending:

- the message composer is disabled;
- refresh restores the pending decision from the server;
- approval sends the stored argument digest;
- rejection creates no Core record;
- successful approval returns links to the resulting canonical records.

The page does not allow editing the displayed arguments in place. Changed
arguments require a new proposal and a new tool call.

### Partial Completion And Failure

Completed turns carry `completion_reason`: `model_answer`, `resource_budget`,
`no_progress`, or `emergency_ceiling`. Non-empty `warnings` produce a
non-blocking notice while retaining the answer and allowing the next question.
A budget stop is not a failed research conclusion; the answer distinguishes
inspected Sources, unread scope, technical failures, and scientific uncertainty.

Provider, capability, and finalization failures remain visible and distinct from
scientific absence. A successful capability that finds no published Evidence
is not rendered as a technical error.

## Responsive And Accessibility Contract

- The desktop layout provides conversation history beside the active thread.
- The mobile layout removes the secondary history rail but retains collection
  navigation, active conversation, structured results, approval controls, and
  the composer.
- The mobile composer keeps its input and send action on one row, follows the
  dynamic viewport as browser chrome changes, and preserves the device bottom
  safe area.
- Assistant colors and status treatments use the shared Lens design tokens in
  both light and dark themes.
- Every interactive control has an accessible name and native keyboard
  behavior.
- Status, warning, and approval states use text as well as color.
- Exact arguments and long scientific terms wrap without obscuring adjacent
  controls.

## Verification Scenarios

The focused browser suite covers:

1. greeting with no capability;
2. collection read with structured result, warning, resource link, and final
   answer;
3. canonical per-paper preparation status with user-visible stages;
4. Objective draft proposal without a Core write;
5. pending write with exact arguments and blocked composer;
6. rejection with no Objective;
7. approval with a canonical Objective link;
8. refresh recovery of persisted approval;
9. removal of stale legacy browser session keys without calling a retired API;
10. queued capability presentation with a canonical resource link;
11. a visible mobile composer across consecutive turns and reduced viewport
    height;
12. text visible before the final persisted turn arrives.
13. multiple document Sources handed to the same Collection Agent, removable before
    submission and persisted only with the sent user message;
14. exact published Finding and linked Evidence inspection before review;
15. distinct feedback and curation approvals, including rejection without a
    write;
16. exact Evidence roles and statement before approval publishes a new Finding
    version.
17. Agent-authored paper analysis shown as a separate approval, rejection, and
    completed Evidence publication state without changing the automatic
    Objective-analysis presentation.
18. consecutive routine capability work compressed into one collapsed activity
    disclosure, with warnings opened automatically;
19. Objective drafts and other reviewable research results kept visible as
    standalone artifacts while the underlying tool mechanics stay secondary.

The page audit additionally verifies desktop and mobile framing, accessible
interaction names, horizontal overflow, and browser console errors.

## Related Docs

- [`frontend-plan.md`](frontend-plan.md)
  Current same-origin browser API contract.
- [`../src/routes/collections/README.md`](../src/routes/collections/README.md)
  Collection route ownership and Objective interaction flow.
- [`../../docs/decisions/rfc-collection-bound-research-agent.md`](../../docs/decisions/rfc-collection-bound-research-agent.md)
  Shared Research Agent product, scientific, and authorization decision.
- [`../../backend/docs/specs/api.md`](../../backend/docs/specs/api.md)
  Backend Chat and capability contract.
