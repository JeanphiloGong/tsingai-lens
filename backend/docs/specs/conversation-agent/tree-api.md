# Conversation Tree API

This document defines message trees, answer versions, version selection, and
explicit Fork. Message versions and Task execution are different node types.

## 1. Read the Message Tree

### `GET /api/v1/conversations/{conversation_id}/tree`

Return the current Conversation and the tree of its explicit Fork connections.
The tree contains these node types:

- `message`: a saved user, assistant, or tool Message
- `task`: an execution that has not produced a final Message or is still running
- `conversation`: the entry point of a Conversation created by an explicit Fork

If a Fork source Conversation has been soft-deleted, the tree keeps a source node
without message content:

```json
{
  "node_id":"conversation:conv_deleted",
  "kind":"conversation",
  "parent_node_id":null,
  "edge_kind":"fork_deleted_source",
  "conversation_id":"conv_deleted",
  "message_id":null,
  "task_id":null,
  "preview":"已删除的 Conversation",
  "deleted_source":true
}
```

Deleting the source does not delete its child Fork. Opening the deleted source
itself still returns `conversation_not_found`. The child Fork remains readable
through its own Conversation identity.

```json
{
  "code":200,
  "message":"success",
  "data":{
    "root_conversation_id":"conv_01",
    "active_path":[
      "conversation:conv_01",
      "message:msg_01",
      "message:msg_02"
    ],
    "nodes":[
      {
        "node_id":"message:msg_02",
        "kind":"message",
        "parent_node_id":"message:msg_01",
        "edge_kind":"parent",
        "conversation_id":"conv_01",
        "message_id":"msg_02",
        "task_id":"task_01",
        "preview":"Both papers examine 316L."
      },
      {
        "node_id":"conversation:conv_02",
        "kind":"conversation",
        "parent_node_id":"message:msg_02",
        "edge_kind":"fork",
        "conversation_id":"conv_02",
        "message_id":null,
        "task_id":null,
        "preview":"316L process comparison - Fork",
        "forked_from_message_id":"msg_02"
      }
    ]
  },
  "meta":null
}
```

When a running Task has no final Message, the tree attaches a `task:{task_id}`
node to its trigger Message. After the Task completes, tree reads use the saved
Message node.

## 2. Select a Saved Version

### `PUT /api/v1/conversations/{conversation_id}/active-path`

The path selection endpoint is defined in
[conversation-api.md](conversation-api.md#3-save-the-current-path). When the tree
interface selects a Message or Task, it calls this endpoint to save the selection.

- Selecting a Message submits `tip_message_id`.
- Selecting a running or completed Task submits `task_id`.
- The request must include `expected_path_revision`.
- Selection does not delete other versions or stop other Tasks.

## 3. Explicit Fork

### `POST /api/v1/conversations/{conversation_id}/forks`

Create a new Conversation from a saved user Message or complete assistant Message.

Request body:

```json
{
  "message_id":"msg_02"
}
```

The server completes these steps in one transaction:

1. Verify that the source Message belongs to the authenticated user, workspace, and Conversation.
2. Verify that required Operations on the selected path are terminal.
3. Create the new Conversation with `forked_from_message_id` pointing to the selected source Message.
4. Copy the path from the root through the selected Message, including its content
   and SourceContext. Assign each copy a new `message_id` and the new `conversation_id`.
   Rebuild `parent_message_id` with the copied IDs and set `copied_from_message_id`
   to the corresponding source Message.
5. Set `current_message_id` to the last copy, `current_task_id` to `null`, and
   `path_revision` to `0`.

The Fork returns the new Conversation:

```json
{
  "conversation_id":"conv_02",
  "workspace_id":"ws_01",
  "title":"316L process comparison - Fork",
  "forked_from_message_id":"msg_02",
  "current_message_id":"msg_copy_02",
  "current_task_id":null,
  "path_revision":0
}
```

The Fork starts with only the copied Messages. Their `produced_by_task_id`,
`tool_call_id`, and `operation_id` are `null`. Tasks, Operations, ModelCalls,
checkpoints, and Feedback stay with the source Conversation. The first send, edit,
or regeneration creates a Task in the new Conversation. [Feedback API](feedback-api.md)

## 4. Opening a Tree Node

| Selected node | Action |
| --- | --- |
| Saved Message | Call `active-path` and read the Message's parent path |
| Running Task | Select the Task through `active-path` and subscribe to Task SSE |
| Fork Conversation | Use its new `conversation_id` to call the messages endpoint |

Messages from different Conversations are never merged into one current path. A
Fork connects Conversations in the tree only through the source relationship.

## 5. Tree Errors

| `error_code` | Description |
| --- | --- |
| `tree_message_not_found` | The tree node Message does not exist or is not visible |
| `tree_target_not_saved` | The target is still an unpersisted increment |
| `fork_source_not_ready` | The source path contains an unfinished Operation |
| `fork_conversation_conflict` | The source Conversation has an active state that cannot be copied |
