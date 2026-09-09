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

Message submission uses `Accept: text/event-stream` on the existing `POST
/messages` endpoint. The browser appends `text_delta` events to one temporary
assistant message, then replaces the temporary user/assistant pair with the
complete `turn` event returned after server persistence. Tool requests,
results, warnings, resource links, and approval state therefore continue to
come from the authoritative final turn rather than from partial model text. If
the stream is interrupted, the browser reloads the durable trajectory before
offering a retry.

The selected session ID and a small presentation-only history are stored under:

```text
lens.chatSession.{collection_id}
lens.chatSessionHistory.{collection_id}
lens.chatSourceContext.{collection_id}
```

The server trajectory is authoritative. Browser storage remembers which
session to load, how to label it in the local history list, and one pending
Source handoff from the document reader. The pending Source is shown above the
composer and can be removed. It is cleared after the complete persisted turn
returns; the durable user message then owns the Source context. The browser
sends the canonical locator kind (`text_window`, `table`, or `figure`) and a
bounded quote. The backend resolves that locator against the immutable prepared
Source, rejects forged or stale context with `422`, and persists canonical
title, location, link, quote, and full-Source digest metadata. The browser does
not establish Source authenticity itself, and a verified context is still not
Evidence until the Evidence authoring contract is completed.

## Presentation Architecture

The route follows the same message-first composition used by Open WebUI while
keeping Lens-specific research boundaries explicit:

- `+page.svelte` owns session orchestration, streaming, approval state, and
  the route shell. It does not create a second browser API or persistence
  model. Each session load has a request generation and abort signal; collection
  changes and unmounting invalidate pending reads, streams, and approval
  responses before they can update the current conversation or local history.
  Disconnecting the browser does not revoke an approved backend write; returning
  to the original session reloads its authoritative trajectory and approval state.
- `ResearchSidebar.svelte` owns collection navigation, session history, and
  the responsive desktop/mobile navigation rail. It receives presentation data
  and callbacks from the route; it does not load or persist sessions. On small
  screens the history rail is collapsed behind an explicit toggle so session
  switching remains available without consuming the conversation viewport.
- `ConversationHeader.svelte` owns the conversation title, current collection,
  and optional Objective link. Runtime status, elapsed time, and progress
  history belong to the corresponding Assistant response; the header does
  not duplicate them with a Ready/Working badge.
- `MessageComposer.svelte` owns the composer, PDF handoff presentation, and
  collection-bound upload state and orchestration. It sends on Enter and preserves
  Shift+Enter and IME composition. An upload already started finishes its
  upload/preparation chain against the original collection. Navigation drops its
  UI updates and stops the remaining batch from starting; it does not move papers
  to the newly selected collection.
- `MessageTimeline.svelte` owns history rendering and scroll position. It starts
  with the latest 20 presentation items and exposes earlier items in batches of
  20 while preserving the reading position. New turns follow the latest response;
  scrolling up suspends following until the researcher returns to the bottom.
- `UserMessage.svelte` and `AssistantMessage.svelte` own role presentation.
  `MessageContent.svelte` owns escaped text formatting and the transient cursor;
  `ResearchProgress.svelte` owns the response-local progress disclosure.
- `ResearchActivity.svelte`, `ResearchArtifact.svelte`, and `ApprovalPanel.svelte`
  own capability activity, reviewable research outputs, and exact write decisions.
  Shared result links and warnings retain one rendering path; the capability
  presentation helpers use the already-associated tool name instead of searching
  the conversation on every render.
- `_shared/IconButton.svelte` owns icon command sizing, disabled and focus states,
  and hover/focus labels for the return-to-latest action.
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
13. one document Source handed to the same Collection Agent, removable before
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
