# RFC: Collection-Bound Research Agent

## Status

Accepted and extended through the bounded local-literature research loop. The
superseded Goal-session design is not an active compatibility contract.

## Decision

Lens provides a collection-bound Research Agent with a minimal, bounded control
loop:

```text
User
  -> Research Agent
  -> LLM
  -> optional Lens capability
  -> structured observation
  -> LLM continuation
  -> final answer or approval_required
```

This follows the useful architectural lesson from small coding agents: keep the
model decision separate from capability execution, persist the trajectory, and
bound every turn by steps and time. Lens does not adopt a shell environment,
generic plugins, filesystem tools, arbitrary HTTP tools, or untyped scientific
state.

Chat is the only assistant-session runtime authority. There is no parallel
session model, route adapter, or dual write.

## Real Research Scenario

A materials researcher has uploaded a collection about energy input in
additively manufactured Ti-6Al-4V. They first ask what Lens can do, then ask
whether the collection supports a relationship between energy input and grain
morphology. The Agent may inspect collection context and published Findings. If
the evidence is incomplete, it says so and may propose a focused Objective
draft. Only after the researcher reviews and approves the exact candidate does
Lens create an unconfirmed Objective. In the new Chat/Agent path, confirmation
of that question is a second explicit decision, and starting automatic or
Agent-authored analysis is a third decision over an exact paper scope;
confirmation alone never starts work. The existing Objective workspace REST
command intentionally retains its legacy atomic contract: submitting the
selected scope confirms a candidate and queues automatic analysis in one user
action. It is not a separate REST confirmation step.

This maps to implementation responsibilities as follows:

| Real action | Runtime owner | Durable scientific owner |
| --- | --- | --- |
| Ask or clarify | Chat message | none |
| Inspect the collection | read capability result | existing collection/Core records |
| Inspect conclusions | read capability result | published Finding and Evidence |
| Formulate a question | draft capability result | none |
| Approve exact candidate | Chat tool-call decision | none until execution |
| Create candidate | write capability | ResearchObjective |
| Confirm the question | approved Agent capability; the legacy Objective workspace may combine this with start | ResearchObjective |
| Start automatic analysis | approved Agent capability; the legacy Objective workspace atomic command | Objective Analysis |
| Publish Agent-authored analysis | approved Agent capability | Objective Analysis |

## Scientific Boundaries

- A relevant paper, Source, Paper Map signal, or Objective draft is not
  Evidence.
- Collection facts returned to the model are bounded and identify their
  canonical resource references.
- Published Findings and Evidence are read from Core; Chat never copies them
  into a second scientific model.
- Scientific absence is a successful observation with explicit uncertainty,
  not a provider failure.
- The Agent may propose confirmation, analysis, Evidence/Finding authorship,
  and a ResearchPlan save only through bounded capabilities whose exact
  arguments require researcher approval. It cannot infer that approval from
  prose, browse the web, execute an experiment, or ingest validation results in
  this version.
- A generated answer is prose, not a durable scientific artifact.

## Capabilities

The Agent exposes explicit domain capabilities in these families; the backend
API specification owns the complete capability list and payload contracts:

| Capability | Risk | Behavior |
| --- | --- | --- |
| Collection and Source inspection | read | Reads bounded collection state, published results, exact Sources, and complete tables. |
| Objective formation and scope | read/draft/write | Previews scope, drafts a focused question, creates a candidate, and confirms it through separate decisions. |
| Fast Path analysis | read/write | Starts and observes canonical automatic analysis over an exact confirmed scope. |
| Deep Path authorship | draft/write | Drafts and versions Source-grounded Evidence, Agent-authored analysis, and Findings. |
| Quality and next research step | read/draft/write | Separates technical failures from gaps, derives questions, and drafts or saves a ResearchPlan. |

Capabilities are registered explicitly in application code. There is no plugin
discovery mechanism and the model cannot name an arbitrary executable action.
For each model decision, the Runner exposes only the registered capabilities
that match the current research intent: ordinary conversation receives none,
paper screening receives collection reads, source questions add Source reads,
and conclusion or plan work adds the corresponding read or draft actions.
Mutation capabilities are added only when the researcher explicitly requests
the matching save, revision, confirmation, or start action. Deriving a new
Objective is likewise a separate explicit request and is not implied by merely
asking for current Objective status.

## Authorization

Read and draft capabilities execute automatically because they do not mutate
Core state. In the Chat/Agent trajectory, candidate creation, Objective
confirmation, analysis start, and scientific publication remain distinct write
events. The legacy Objective workspace Fast Path intentionally combines
candidate confirmation with automatic analysis in its existing REST command;
that backward-compatible exception does not apply to the separate Chat/Agent
capabilities. Every write capability follows this invariant:

```text
persist exact tool name + arguments + digest
  -> return approval_required
  -> owning user approves or rejects that digest
  -> approved call executes once
  -> persist structured result and model continuation
```

Approval is not inferred from conversational language. Changed arguments,
another user, a stale digest, or a rejected call cannot execute the pending
write. Browser refresh reloads the persisted pending call.

## Runtime And Persistence

A Chat session belongs to one user and one collection. Its ordered trajectory
contains:

- user and assistant messages;
- assistant capability intent;
- typed tool calls and exact arguments;
- structured tool results, warnings, and canonical resource references;
- write approval decisions and execution status.

The application persists each completed transition instead of waiting for the
whole turn to finish: user message, model tool intent, running call, structured
result, and final answer. The Runner reports checkpoints through a narrow
callback while `ChatSessionService` remains the sole persistence owner.

The Runner enforces a finite step limit and predictable terminal states:

- `completed`;
- `approval_required`;
- `rejected`;
- `step_limit_reached`;
- `failed`.

Every terminal turn remains intelligible to the researcher. In particular,
`step_limit_reached` appends a final assistant explanation rather than leaving
the trajectory at an intermediate tool result. A long-running capability may
return `queued`; that is a successful observation only when it includes a
canonical resource reference the researcher can inspect while work continues.

Retries, provider errors, malformed tool arguments, and time limits are
technical states. They are never translated into scientific evidence states.

## Migration

Historical assistant conversations are copied once into Chat while preserving
message identity, order, content, and timestamps. Historical Experiment Plans
retain their message provenance. Retired session tables and APIs are then
removed. New ResearchPlans use the same Objective-scoped service whether the
reviewed draft came from the human UI or an approved Agent capability.

The migration is reversible for operational rollback, but application code has
one active contract and does not dual write.

## Rejected Alternatives

- Keeping two assistant-session APIs through an adapter or feature flag.
- Copying a coding agent's Bash environment or generic tool/plugin layer.
- Allowing arbitrary network, shell, or filesystem access.
- Treating free-form model output as an Objective, Evidence record, Finding, or
  Experiment Plan.
- Letting the model infer user consent or edit an already confirmed Objective.
- Starting Objective analysis automatically after candidate creation.

## Consequences

The architecture can grow by adding narrow, scientifically meaningful
capabilities with their own contracts and authorization level. It cannot grow
by giving the model an unrestricted execution environment. New write or
external-data capabilities require an explicit real research scenario,
structured result contract, authority decision, failure semantics, and
end-to-end verification.

## Verification

Acceptance requires:

- deterministic Runner tests for direct answers, multi-step capability use,
  invalid calls, failures, and step limits;
- persistence and migration round-trip tests;
- ownership and digest-bound approval tests;
- frontend tests for ordinary conversation, structured results, proposal,
  rejection, approval, and refresh recovery;
- desktop/mobile browser checks with no console, network, overlap, or overflow
  errors;
- a real collection scenario that reaches a user-reviewable candidate, records
  a separate confirmation, and starts only the explicitly selected Fast or Deep
  analysis path without changing the existing Objective analysis semantics;
- one continuous Deep Path replay from exact Source inspection through
  Source-grounded Evidence, Finding review, quality assessment, follow-up
  Objective, and ResearchPlan persistence;
- parity checks proving that Fast and Deep paths publish the same canonical
  scientific object types and preserve equivalent Source lineage and failure
  semantics.

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Research Agent Chat Interface](../../frontend/docs/research-agent-chat.md)
- [Backend API](../../backend/docs/specs/api.md)
