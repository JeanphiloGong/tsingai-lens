# Chat Application Layer

This package owns the collection-bound Research Agent conversation. It turns
an authenticated user's message into resource-bounded model decisions, ordered
typed capability calls, and a durable, reviewable trajectory.

Chat is the orchestration and approval boundary for the Agent. It references
Source and Core application services for collection facts and scientific work;
it does not create a second Objective, Evidence, Finding, or Analysis model.

## Main Flow

```text
authenticated user + collection
  -> ChatSessionService validates and persists the user message
  -> ChatContextBuilder selects a bounded trajectory for the model
  -> ResearchAgentRunner exposes capabilities relevant to the intent
  -> ChatModel returns an answer, independent reads, or one draft/write call
  -> Runner checkpoints the complete ordered request before execution
  -> capabilities return paired observations or exact approval_required
  -> ChatSessionService checkpoints the trajectory and final response
```

Source context attached from the document reader is resolved against the
canonical Source before the model runs. A quote is inspection material, not
Evidence or permission to mutate a scientific record.

Read and draft capabilities can execute during the turn. Write capabilities
persist their exact arguments and digest, stop for the authenticated user's
approval, and execute only that approved call once. Rejection, provider
failure, malformed model output, and resource limits remain technical trajectory
outcomes; they are not scientific conclusions.

If an approved write fails, its continuation explains that failure without
starting more capability work. A fresh user decision can inspect changed
Sources or propose a new exact approval; the failed action is not retried
implicitly.

## Responsibilities

- keep one ordered trajectory of user and assistant messages, capability calls,
  structured results, and approval decisions;
- bound model context, capability exposure, elapsed time, tools, model usage, and continuation
  behavior for each turn;
- authorize capabilities by risk and bind writes to the exact stored arguments,
  user, and pending call;
- preserve canonical resource references so collection observations can be
  traced back to Source and Core records; and
- checkpoint durable state after each meaningful transition so refresh and
  interrupted streams remain understandable.

## Key Areas

- `session_service.py`: owns session reads, source-context validation, turn
  persistence, streaming, and approval execution.
- `agent_runner.py`: runs the bounded model, capability, and continuation loop
  and reports `completed`, `approval_required`, or `failed`. Completion records
  why work stopped: a model answer, resource budget, repeated observations, or
  the emergency cycle ceiling. Technical limits permit one answer-only
  finalization with scope warnings; a failed finalization remains a failure.
- `context_builder.py`: selects a bounded, protocol-safe conversation context
  while pinning the active question and keeping whole request/result batches
  together. Omitted history contributes deterministic lineage, not paper text
  or scientific claims, to a transient rollover summary.
- `model.py`: defines the provider-neutral model contract and the Research
  Agent instructions.
- `authorization.py`: maps capability risk to automatic execution or exact
  user approval.
- `capabilities/`: contains the explicit typed capability registry and handlers
  for collection and Source inspection, Objective work, Finding and Evidence
  authoring, analysis review, and research-plan drafts or writes.

## Boundaries

- `application/source/` owns Collection membership, Document preparation, and
  canonical Source loading.
- `application/core/` owns Objective discovery and analysis, Evidence, and
  Findings.
- `application/goal/` owns research briefs and Objective-scoped plans after an
  approved Chat or workspace action.
- `domain/chat/` owns the durable session, message, capability-call, result,
  and approval records.
- `controllers/chat/` owns the HTTP route and response boundary.

Do not add arbitrary tools, network access, shell access, or untyped scientific
state to this package. New capabilities need a real research responsibility,
an explicit input and result contract, authorization semantics, and an
end-to-end scenario that preserves Source traceability.

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md): HTTP and capability
  contracts, including the approval lifecycle.
- [`../../docs/architecture/overview.md`](../../docs/architecture/overview.md):
  backend ownership and runtime boundaries.
- [`../../../docs/decisions/rfc-collection-bound-research-agent.md`](../../../docs/decisions/rfc-collection-bound-research-agent.md):
  accepted Research Agent design and real-world scenario mapping.
- [`../core/README.md`](../core/README.md): scientific Objective, Evidence, and
  Finding ownership referenced by Chat.
