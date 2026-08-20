# RFC: Collection-Bound Research Agent

## Status

Accepted and implemented for the first bounded Agent loop. The historical
filename remains stable for documentation links; the superseded session design
is not an active compatibility contract.

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
Lens create an unconfirmed Objective. The researcher then uses the existing
Objective workspace to confirm it and start evidence analysis.

This maps to implementation responsibilities as follows:

| Real action | Runtime owner | Durable scientific owner |
| --- | --- | --- |
| Ask or clarify | Chat message | none |
| Inspect the collection | read capability result | existing collection/Core records |
| Inspect conclusions | read capability result | published Finding and Evidence |
| Formulate a question | draft capability result | none |
| Approve exact candidate | Chat tool-call decision | none until execution |
| Create candidate | write capability | ResearchObjective |
| Confirm and analyze | existing Objective workspace | Objective Analysis |

## Scientific Boundaries

- A relevant paper, Source, PaperSkim signal, or Objective draft is not
  Evidence.
- Collection facts returned to the model are bounded and identify their
  canonical resource references.
- Published Findings and Evidence are read from Core; Chat never copies them
  into a second scientific model.
- Scientific absence is a successful observation with explicit uncertainty,
  not a provider failure.
- The Agent cannot confirm an Objective, start analysis, publish analysis,
  browse the web, or create an Experiment Plan in this version.
- A generated answer is prose, not a durable scientific artifact.

## Capabilities

The first version exposes four explicit domain capabilities:

| Capability | Risk | Behavior |
| --- | --- | --- |
| `get_collection_context` | read | Returns bounded collection and Objective context. |
| `query_published_findings` | read | Returns published Finding/Evidence summaries and absence warnings. |
| `propose_objective_drafts` | draft | Returns at most three focused, single-outcome proposals. |
| `create_objective_candidate` | write | Creates one unconfirmed candidate after exact approval. |

Capabilities are registered explicitly in application code. There is no plugin
discovery mechanism and the model cannot name an arbitrary executable action.

## Authorization

Read and draft capabilities execute automatically because they do not mutate
Core state. A write capability follows this invariant:

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
removed. New Experiment Plans accept manual authoring only.

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
- a real collection scenario that reaches a user-reviewable candidate without
  changing the existing Objective analysis semantics.

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Architecture Boundary](../architecture/lens-v1-architecture-boundary.md)
- [Research Agent Chat Interface](../../frontend/docs/goal-copilot-proposal.md)
- [Backend API](../../backend/docs/specs/api.md)
