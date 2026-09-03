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

Ordinary conversation does not require a capability. Collection reads and
Objective drafts run automatically. A Core write remains paused until the user
approves the exact persisted arguments.

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
- Current Documents and their preparation tasks remain the runtime authority for
  paper preparation progress. Chat reads that state; it does not persist another
  workflow.
- Paper Map relationships may support an Objective proposal but are labeled as
  proposal context, never Evidence.
- Preparing papers and starting Objective analysis are separate approved writes.
  Preparation targets exact Documents; analysis targets an exact non-empty set
  of ready Documents.
- A created Objective remains an unconfirmed candidate. Confirmation and
  analysis stay in the Objective workspace.
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
- General Agent prose cannot be saved as an Experiment Plan. New plans are
  authored manually until a dedicated scientifically validated capability
  exists.

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
view for long-running task progress.

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
returns; the durable user message then owns the Source context.

## Visible States

### Empty and ordinary conversation

The page offers realistic prompts for collection overview, published Findings,
and focused Objective proposals. A greeting or general conversational response
is rendered incrementally as a normal assistant message with no fake capability
activity. A stable response cursor occupies the assistant row before the first
text delta; it does not create a stored partial message.

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
  canonical Objective analysis.

A tool request paused for approval is represented by the approval panel only;
the browser does not duplicate it as a second activity row. Images or embedded
media are presented only when a capability returns a real inspectable research
artifact. The browser does not synthesize decorative screenshots for routine
tool work.

A `queued` capability result is rendered as started rather than completed. It
shows the canonical analysis or task link and lets the researcher continue the
conversation instead of waiting for the long-running operation.

Raw tool JSON is not presented as an assistant claim.
The process view shows persisted stage decisions and warnings, not model
chain-of-thought, prompts, JSON repair, or retry mechanics.

### Write approval

For `start_research_process`, `create_objective_candidate`,
`start_objective_analysis`, `record_finding_feedback`, `curate_finding`,
`create_finding_version`, `create_evidence_version`, and
`publish_agent_objective_analysis`, the page renders the exact persisted
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

### Failure

Provider, capability, and step-limit failures remain visible and distinct from
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
