# Lens Conversation and Agent Data Model

Status: Conversation and Agent target contract

This document defines the backend persistence contract for Conversation and Agent.
It describes the persistence relationships among Conversations, message trees, and
durable Agent execution. Production is still in migration. The production database
adopts these target structures only after the corresponding Alembic migrations and
observation window are complete.

## 1. Design Decisions

1. Conversation owns the message tree.
2. A Task represents one complete and resumable Agent execution.
3. A user Message can trigger a Task, but it is normally not produced by that Task.
4. Assistant and tool Messages belong to a Task through `produced_by_task_id`.
5. Model tool requests belong to an assistant Message, with execution state stored in
   `agent_operations`. There is no separate `chat_tool_calls` table.
6. `task_id` is the unique identity of a complete execution. `response_id` is not a
   second execution identity.
7. `operation_id` identifies one logical Operation. Physical retries reuse the same
   `operation_id`.
8. Feedback binds to a specific assistant Message, not to a whole Task, and is not
   included in model context.

## 2. Domain Relationships

```text
Conversation 1 ─── N Message
Conversation 1 ─── N Task
Conversation 1 ─── N Feedback

Task ───> trigger Message
Task 1 ─── N produced Message
Task 1 ─── N ModelCall
Task 1 ─── N Operation
Task 1 ─── N TaskStep

Operation 1 ─── N execution attempts
Message 1 ─── N Feedback, one row per user
```

The message tree answers what the user and assistant said. The Task trajectory
answers how one assistant response was executed. Reading historical Messages as
Task context does not give the Task ownership of those Messages.

## 3. `chat_conversations`

Each row represents one Conversation in a workspace sidebar. Current-path fields
are a projection of the user's selection and do not represent execution ownership.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `conversation_id` | varchar(128) | no | Conversation identity |
| `user_id` | varchar(64) | no | Conversation owner |
| `workspace_id` | varchar(64) | no | Owning workspace |
| `title` | text | yes | Sidebar title |
| `is_pinned` | boolean | no | Whether pinned, default `false` |
| `current_message_id` | varchar(128) | yes | Tip of the selected Message path |
| `current_task_id` | varchar(128) | yes | Currently selected running or completed Task |
| `path_revision` | bigint | no | Path selection revision, initially `0` |
| `forked_from_message_id` | varchar(128) | yes | Source Message of an explicit Fork |
| `deleted_at` | timestamptz | yes | Soft-deletion timestamp |
| `created_at` | timestamptz | no | Creation time |
| `updated_at` | timestamptz | no | Most recent Conversation or metadata update |

At most one of `current_message_id` and `current_task_id` is set. Both are `null`
for an empty Conversation. A Conversation can have multiple running Tasks at once.
Soft-deleted Conversations remain stored for audit and are hidden from ordinary
Conversation and Agent reads.

## 4. `chat_messages`

Messages form a tree within one Conversation. The parent relationship is immutable
after creation.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `message_id` | varchar(128) | no | Message identity |
| `conversation_id` | varchar(128) | no | Owning Conversation |
| `parent_message_id` | varchar(128) | yes | Previous Message on the current path |
| `role` | varchar(16) | no | `user`, `assistant`, or `tool` |
| `content` | text | no | Message content, possibly empty for tool Messages |
| `produced_by_task_id` | varchar(128) | yes | Task producing an assistant or tool Message |
| `copied_from_message_id` | varchar(128) | yes | Source Message when copied by an explicit Fork |
| `tool_call_id` | varchar(128) | yes | Model tool-call identity |
| `operation_id` | varchar(128) | yes | Internal Operation identity when no model `tool_call_id` exists |
| `source_contexts` | jsonb | no | Validated source attachments, default `[]` |
| `created_at` | timestamptz | no | Creation time |

Ordinary user Messages have no `produced_by_task_id`. A Task reading historical
context does not create a new ownership relationship.

An assistant Message stores structured tool requests from the model. A tool request
is part of that Message and is not a separate entity in `chat_tool_calls`.

A model-produced tool Message uses `tool_call_id` to connect the assistant request
and Operation. An internal Operation without a model tool call uses `operation_id`
to connect its tool Message.

## 5. `chat_message_feedback`

One row represents the current user's rating of one assistant answer. It supports
the helpful or not-helpful response shown below the answer. It does not change the
Message, Task, or model context.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `feedback_id` | varchar(64) | no | Feedback identity |
| `conversation_id` | varchar(128) | no | Owning Conversation |
| `message_id` | varchar(128) | no | Rated assistant Message |
| `user_id` | varchar(64) | no | Authenticated user submitting the feedback |
| `rating` | varchar(16) | no | `helpful` or `not_helpful` |
| `reason` | varchar(16) | yes | `incorrect`, `incomplete`, `unclear`, or `other`, only for negative feedback |
| `comment` | text | yes | Additional user explanation, at most 2000 characters |
| `response_digest` | varchar(64) | no | SHA-256 digest of the rated answer content |
| `created_at` | timestamptz | no | First submission time |
| `updated_at` | timestamptz | no | Last modification time |

Constraints:

- `message_id` must reference an assistant Message in the same Conversation.
- `(user_id, message_id)` is unique, so each user has one current rating per answer.
- `user_id` comes from the authentication context and is not submitted by the client.
- The messages endpoint projects the current user's row as `items[].my_feedback`, or `null` when absent.
- Deleting feedback deletes only the feedback row, not the assistant Message.

## 6. `agent_tasks`

Each row represents one complete and resumable Agent execution. A Task triggered by
a user starts from a saved user Message and can produce multiple assistant or tool
Messages.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `task_id` | varchar(128) | no | Durable execution identity |
| `conversation_id` | varchar(128) | no | Owning Conversation |
| `trigger_kind` | varchar(32) | no | `user_message`, `approval`, `retry`, `schedule`, or `system` |
| `trigger_message_id` | varchar(128) | yes | User Message triggering the Task |
| `final_message_id` | varchar(128) | yes | Final assistant Message |
| `status` | varchar(32) | no | `accepted`, `running`, `approval_required`, `completed`, `failed`, `interrupted`, or `cancelled` |
| `checkpoint_revision` | bigint | no | Monotonically increasing checkpoint version |
| `checkpoint` | jsonb | no | Task recovery state |
| `model_connection_id` | varchar(64) | yes | Model connection bound to this execution |
| `model_connection_name` | text | yes | Snapshot of the connection display name |
| `started_at` | timestamptz | no | Execution start time |
| `updated_at` | timestamptz | no | Most recent state or checkpoint update |
| `finished_at` | timestamptz | yes | Terminal-state time |

When `trigger_kind = user_message`, `trigger_message_id` must reference a user
Message in the same Conversation. Approval, resume, and system Tasks may have no
trigger Message. When a Task is waiting for approval, interrupted, or failed without
a final answer, `final_message_id` is `null`.

## 7. `chat_model_calls`

Each row records one model-provider request inside a Task. One Task can create
multiple ModelCalls through tool calls and recovery.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `model_call_id` | varchar(128) | no | Model request audit identity |
| `task_id` | varchar(128) | no | Owning Task |
| `sequence` | integer | no | Zero-based order within the Task |
| `provider` | varchar(64) | no | Model provider |
| `model` | varchar(128) | no | Model name |
| `purpose` | varchar(64) | no | Request purpose such as `answer` or `tool_followup` |
| `request_digest` | varchar(64) | no | Request digest |
| `response_digest` | varchar(64) | yes | Provider response digest |
| `status` | varchar(24) | no | `started`, `succeeded`, or `failed` |
| `input_tokens` | integer | yes | Input token count |
| `output_tokens` | integer | yes | Output token count |
| `error_code` | varchar(128) | yes | Stable provider or runtime error |
| `started_at` | timestamptz | no | Request start time |
| `finished_at` | timestamptz | yes | Request finish time |

## 8. `agent_operations`

This is the single durable record for a tool or other external Operation. It stores
the model's intent, approval, execution, idempotency, recovery, and result states.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `operation_id` | varchar(128) | no | Stable logical Operation identity |
| `task_id` | varchar(128) | no | Owning Task |
| `tool_call_id` | varchar(128) | yes | Model tool-call identity when applicable |
| `assistant_message_id` | varchar(128) | yes | Assistant Message requesting the Operation |
| `name` | varchar(128) | no | Capability or Operation name |
| `arguments` | jsonb | no | Accepted exact arguments |
| `arguments_digest` | varchar(64) | no | Digest binding approval and execution |
| `risk` | varchar(16) | no | `read`, `draft`, `write`, or `unknown` |
| `status` | varchar(32) | no | `requested`, `approval_required`, `approved`, `running`, `succeeded`, `failed`, `rejected`, or `needs_reconciliation` |
| `idempotency_key` | varchar(128) | yes | Stable key for external side effects |
| `result` | jsonb | yes | Structured Operation result |
| `error_code` | varchar(128) | yes | Stable failure reason |
| `error_message` | text | yes | Displayable error summary |
| `decision_user_id` | varchar(64) | yes | User who approved or rejected |
| `decision_arguments_digest` | varchar(64) | yes | Digest covered by the decision |
| `decided_at` | timestamptz | yes | Approval decision time |
| `started_at` | timestamptz | yes | First execution start time |
| `finished_at` | timestamptz | yes | Terminal execution time |
| `created_at` | timestamptz | no | Operation creation time |
| `updated_at` | timestamptz | no | Most recent Operation update |

State flow:

```text
requested
  -> approval_required
  -> approved
  -> running
  -> succeeded / failed / needs_reconciliation
```

Timeouts and network errors do not create a new Operation. They create another
physical execution attempt under the same Operation. An uncertain side effect enters
`needs_reconciliation`, and blind replay is forbidden until it is checked. If future
requirements need every physical attempt persisted, add `chat_operation_attempts`.

## 9. `agent_task_steps`

A Step is a Durable Execution recovery checkpoint. It is neither a ModelCall nor a
scientific research result.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `step_id` | varchar(128) | no | Step identity |
| `task_id` | varchar(128) | no | Owning Task |
| `sequence` | integer | no | Order within the Task |
| `name` | varchar(128) | no | Runtime step name |
| `status` | varchar(24) | no | `pending`, `running`, `completed`, or `blocked` |
| `checkpoint` | jsonb | no | State required to resume the Step |
| `started_at` | timestamptz | yes | Step start time |
| `finished_at` | timestamptz | yes | Step finish time |

## 10. One Complete Execution

```text
M1 user: read target.py and explain it
  produced_by_task_id = null

T1
  trigger_message_id = M1
  status = running

M2 assistant: request read_file
  produced_by_task_id = T1
  tool_call_id = TC1

OP1
  task_id = T1
  tool_call_id = TC1
  operation_id = OP1
  status = approved

M3 tool: read_file result
  produced_by_task_id = T1
  tool_call_id = TC1

M4 assistant: final explanation
  produced_by_task_id = T1

T1
  final_message_id = M4
  status = completed
```

## 11. Fork, Edit, and Retry

### Retry

Retrying a saved user Message creates a new Task and keeps the same
`trigger_message_id`. The new Task produces a new assistant branch in the same
Conversation.

### Edit

Editing a user Message creates a new user Message under the original parent. The
new Message triggers a new Task.

### Explicit Fork

Fork creates a new Conversation and copies the selected Message path. Copied
Messages receive new IDs and retain the source in `copied_from_message_id`. Copy
ended Task, Operation, and ModelCall records as read-only history only when the
selected path needs that execution history. The first new question in the new
Conversation creates its first new Task.

## 12. Required Invariants

1. Every Message belongs to exactly one Conversation.
2. Every Task belongs to exactly one Conversation.
3. If a Task has a trigger Message, that Message belongs to the same Conversation.
4. Task-produced Messages and their Task belong to the same Conversation.
5. A Message parent belongs to the same Conversation.
6. `operation_id` remains stable across physical retries.
7. Approval binds to the exact `arguments_digest`.
8. An Operation with an uncertain external result cannot be replayed directly.
9. `final_message_id` can reference only a Message produced by that Task.
10. `current_message_id` and `current_task_id` describe the user's current view and do not change historical ownership.

## 13. Indexes and Constraints

- `chat_messages(conversation_id, parent_message_id)` supports message-tree traversal.
- `chat_messages(produced_by_task_id)` supports queries for Task-produced Messages.
- `agent_tasks(conversation_id, status, updated_at)` supports active-Task queries.
- `(task_id, sequence)` is unique, keeping ModelCall and TaskStep order stable.
- `(task_id, operation_id)` is unique, keeping logical Operation identity stable.
- `(user_id, message_id)` is unique, giving each user one current rating per answer.

## 14. Migration Boundary

Conversation V2 Alembic revision `b71000000002` renames the Conversation table and
ownership columns in place. It preserves existing Conversation, Message, and
Feedback identities and constrains Feedback and its target Message to the same
Conversation. `workspace_id` continues to reference `workspaces.workspace_id`
at this stage. Parent-chain backfill for existing Messages, Agent runtime migration,
and HTTP cutover happen in later stages.

The conceptual mapping is:

| Pre-migration concept | Target concept |
| --- | --- |
| `chat_sessions` | `chat_conversations` |
| `session_id` | `conversation_id` |
| `workspace_id` | `workspace_id` |
| `chat_messages.position` | `parent_message_id` |
| Session `response_snapshot` | `agent_tasks.checkpoint` |
| `response_id` | `task_id` |
| `chat_tool_calls` | `agent_operations` |
| Existing model request audit | `chat_model_calls.task_id` |
| `chat_message_feedback.session_id` | `chat_message_feedback.conversation_id` |

Migration must preserve Message identities, Source context, Feedback, tool results,
and audit records. Legacy linear branch data is backfilled as an explicit Fork only
when the stored data proves that explicit Fork intent.
