# Task API

This document defines one Agent execution's state, parallel answers, SSE,
stopping, recovery, and Operation approval. It replaces the old
`response-api.md`. Execution identity is always `task_id`.

The request `request_id` is used only for log and trace correlation. It does not
create or look up a `task_id` and is not a database unique key. Every accepted
logical execution receives a new `task_id` from the server.

## 1. Read a Task

### `GET /api/v1/conversations/{conversation_id}/tasks/{task_id}`

Return the current Task state and recovery information. Complete ModelCall,
Operation, and Step details are returned only by the Task detail endpoint.

```json
{
  "task_id":"task_07",
  "conversation_id":"conv_01",
  "trigger_message_id":"msg_07",
  "final_message_id":null,
  "status":"approval_required",
  "checkpoint_revision":4,
  "active_operation_id":"op_03",
  "started_at":"2026-11-19T02:16:00Z",
  "updated_at":"2026-11-19T02:16:08Z"
}
```

### `GET /api/v1/conversations/{conversation_id}/tasks`

List Tasks in the current Conversation. The endpoint supports `status`, `limit`,
and `offset` query parameters. A recovery page can request only `running`,
`approval_required`, and `interrupted` Tasks.

## 2. SSE Output

### `GET /api/v1/conversations/{conversation_id}/tasks/{task_id}/events`

Return Task snapshots and incremental events as `text/event-stream`. Reconnect with
the `after_revision` query parameter. The server returns events after that
checkpoint or the current complete snapshot.

Example events:

```text
event: task.snapshot
data: {"task_id":"task_07","revision":4,"status":"running"}

event: message.delta
data: {"task_id":"task_07","message_id":"msg_09","content":"Reading the file"}

event: operation.updated
data: {"task_id":"task_07","operation_id":"op_03","status":"succeeded"}

event: task.completed
data: {"task_id":"task_07","final_message_id":"msg_10"}
```

The client discards events with an old `revision`. When multiple Tasks run in
parallel, every event includes `task_id`, allowing the client to route output by
Task.

## 3. Stop a Task

### `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/stop`

Request body:

```json
{"request_id":"00000000-0000-4000-8000-000000000003"}
```

The stop request first changes the Task to `interrupted`. Direct execution observes
this state at the next checkpoint boundary and ends. A response state of
`interrupted` or `cancelled` indicates that execution has ended.

## 4. Resume a Task

### `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/resume`

Use this after a process interruption, network disconnect, or reopening the page.
After submitting the resume request, the caller invokes `TaskExecution.run_task()`
again with the original `task_id` and latest `checkpoint_revision`.

Request body:

```json
{
  "request_id":"00000000-0000-4000-8000-000000000004",
  "expected_checkpoint_revision":4
}
```

Use the Operation decision endpoint below to resume an approval-waiting Task. An
explicit user regeneration creates a new Task and does not use this endpoint.

## 5. Operation Approval

### `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/operations/{operation_id}/decision`

Request body:

```json
{
  "decision":"approved",
  "arguments_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "request_id":"00000000-0000-4000-8000-000000000005"
}
```

`decision` is `approved` or `rejected`. The server must validate all of the
following:

- The Operation belongs to the Task and Conversation in the path.
- The current Operation state accepts a decision.
- `arguments_digest` exactly matches the parameters awaiting approval.
- The current user has the permission required by the Operation.

After approval, the caller continues the original Task. After rejection, the
Operation enters `rejected`, and the Task follows its execution plan into continued
answering, failure, or a request for user input.

## 6. Operation States

```text
requested
  -> approval_required
  -> approved
  -> running
  -> succeeded / failed / needs_reconciliation
```

One `operation_id` can have multiple physical execution attempts. When an external
side effect is uncertain, the Operation must enter `needs_reconciliation` before it
can be considered for another execution.

## 7. Task States and Errors

| State | Description |
| --- | --- |
| `accepted` | The Task is persisted and has not started execution |
| `running` | `TaskExecution` is executing the Task |
| `approval_required` | Waiting for the user to decide an Operation |
| `completed` | A final answer has been produced |
| `failed` | An unrecoverable error occurred |
| `interrupted` | Stopped or interrupted by the process and still resumable |
| `cancelled` | Explicitly cancelled and cannot continue the original execution |

Error responses use a common envelope:

```json
{
  "code": 409,
  "message":"operation result is unknown",
  "data":null,
  "meta":{"error_code":"operation_needs_reconciliation"}
}
```

## 8. Parallel Execution Rules

- One user Message can have multiple Tasks, for example after multiple retries.
- Each Task uses an independent `task_id`, checkpoint, and execution lock.
- Incremental output from one Task cannot be written to another Task's message path.
- The client saves the Conversation's current selection through the active-path endpoint.
- Task completion order does not determine the version currently shown to the user.
