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
the published analysis supports, and formulate a focused candidate question.
It does not replace the comparison workspace or become a second scientific
fact store.

- Chat owns sessions, ordered messages, capability activity, and approval
  decisions.
- Core owns Research Objectives, Evidence, Findings, and Analysis.
- Collection build tasks remain the single runtime authority for research
  preparation progress. Chat reads that state; it does not persist another
  workflow.
- PaperSkim relationships may support an Objective proposal but are labeled as
  proposal context, never Evidence.
- A created Objective remains an unconfirmed candidate. Confirmation and
  analysis stay in the Objective workspace.
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
```

The server trajectory is authoritative. Browser storage only remembers which
session to load and how to label it in the local history list.

## Visible States

### Empty and ordinary conversation

The page offers realistic prompts for collection overview, published Findings,
and focused Objective proposals. A greeting or general conversational response
is rendered incrementally as a normal assistant message with no fake capability
activity. A stable response cursor occupies the assistant row before the first
text delta; it does not create a stored partial message.

### Capability activity

An assistant capability request and its result are separate from the final
answer. The result panel shows:

- the named Lens capability;
- a bounded human-readable summary;
- structured Objective drafts when present;
- the observable research stages and active paper when process status is read;
- warnings and scientific absence;
- links to canonical collection, Objective, Finding, or Evidence records.

A `queued` capability result is rendered as started rather than completed. It
shows the canonical analysis or task link and lets the researcher continue the
conversation instead of waiting for the long-running operation.

Raw tool JSON is not presented as an assistant claim.
The process view shows persisted stage decisions and warnings, not model
chain-of-thought, prompts, JSON repair, or retry mechanics.

### Write approval

For `create_objective_candidate`, the page renders the exact persisted
arguments and exposes explicit Reject and Approve actions. While approval is
pending:

- the message composer is disabled;
- refresh restores the pending decision from the server;
- approval sends the stored argument digest;
- rejection creates no Core record;
- successful approval returns a link to the canonical Objective.

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
3. canonical research-process status with user-visible scientific stages;
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
