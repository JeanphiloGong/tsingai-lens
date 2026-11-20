# Conversation and Agent Contracts

This directory is the backend source of truth for the module-first Conversation
and Agent contracts. It describes the target API and persistence model used by
the implementation tutorials and migration work. It does not claim that the
target runtime has already replaced the legacy Chat implementation.

## Reading Order

1. [`conversation-api.md`](conversation-api.md) for Conversation resources,
   paths, messages, edits, retries, and workspace scoping.
2. [`feedback-api.md`](feedback-api.md) for feedback on saved assistant
   messages and the `my_feedback` projection.
3. [`task-api.md`](task-api.md) for durable Task state, SSE, recovery, stop,
   and Operation decisions.
4. [`tree-api.md`](tree-api.md) for message branches, active-path selection,
   and explicit Fork.
5. [`data-model.md`](data-model.md) for PostgreSQL identities, ownership,
   constraints, and durable execution records.

## Ownership

Conversation owns Conversations, Messages, parent chains, active paths, Fork,
and Feedback. Agent owns Tasks, ModelCalls, Operations, TaskSteps, checkpoints,
recovery, Dispatcher, SSE, and approval execution. Workspace and Document/Source
ownership remain external contracts.

The implementation tutorials remain in the separate tutorial workspace. They
must link back to these files instead of maintaining another API or database
authority.
