# Conversation API

This document defines Conversation listing, opening, message paths, sending,
editing, retrying, and soft deletion.

The API exposes list, create, detail, current message path, path selection, title,
pin, and [Feedback](feedback-api.md) operations. Historical parent links and the
current selection are established by the history backfill stage.

<!-- vim-markdown-toc GFM -->

* [1. Conversation List](#1-conversation-list)
  * [`GET /api/v1/conversations`](#get-apiv1conversations)
  * [`POST /api/v1/conversations`](#post-apiv1conversations)
  * [`GET /api/v1/conversations/{conversation_id}`](#get-apiv1conversationsconversation_id)
  * [`PUT /api/v1/conversations/{conversation_id}/title`](#put-apiv1conversationsconversation_idtitle)
  * [`PUT /api/v1/conversations/{conversation_id}/pin`](#put-apiv1conversationsconversation_idpin)
  * [`DELETE /api/v1/conversations/{conversation_id}`](#delete-apiv1conversationsconversation_id)
* [2. Read the Current Message Path](#2-read-the-current-message-path)
  * [`GET /api/v1/conversations/{conversation_id}/messages`](#get-apiv1conversationsconversation_idmessages)
* [3. Save the Current Path](#3-save-the-current-path)
  * [`PUT /api/v1/conversations/{conversation_id}/active-path`](#put-apiv1conversationsconversation_idactive-path)
* [4. Send a New Message](#4-send-a-new-message)
  * [`POST /api/v1/conversations/{conversation_id}/messages`](#post-apiv1conversationsconversation_idmessages)
* [5. Edit a Question](#5-edit-a-question)
  * [`POST /api/v1/conversations/{conversation_id}/messages/{message_id}/edits`](#post-apiv1conversationsconversation_idmessagesmessage_idedits)
* [6. Retry an Answer](#6-retry-an-answer)
  * [`POST /api/v1/conversations/{conversation_id}/messages/{message_id}/regenerations`](#post-apiv1conversationsconversation_idmessagesmessage_idregenerations)
* [7. Common Errors](#7-common-errors)

<!-- vim-markdown-toc -->
## 1. Conversation List

### `GET /api/v1/conversations`

List the Conversations in a workspace.

Query parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `workspace_id` | string | yes | Stable workspace identity |
| `limit` | integer | no | 1-100, default 50 |
| `offset` | integer | no | Non-negative integer, default 0 |

The endpoint returns `ConversationSummary[]`. The `status` value is a summary. It is
`approval` when a Task is waiting for approval or a resume decision, `running` when
a Task is running, and `idle` otherwise.

### `Conversation` response fields

List, detail, title update, and pin update responses use this Conversation object.
`ConversationSummary` uses the same field set, with pagination fields added by the
list response.

| Field | Type | Nullable | Description |
| --- | --- | --- | --- |
| `conversation_id` | string | no | Stable Conversation identity |
| `workspace_id` | string | no | Stable identity of the owning workspace |
| `title` | string | yes | Saved title, or `null` for an empty Conversation |
| `is_pinned` | boolean | no | Whether the Conversation is pinned, default `false` |
| `current_message_id` | string | yes | Tip of the selected saved Message path |
| `current_task_id` | string | yes | Currently selected running or completed Task |
| `path_revision` | integer | no | Current path revision, initially `0` |
| `forked_from_message_id` | string | yes | Source Message of an explicit Fork, or `null` for a root Conversation |
| `status` | string | no | `idle`, `running`, or `approval` |
| `created_at` | datetime | no | Creation time in UTC RFC3339 format |
| `updated_at` | datetime | no | Last update time in UTC RFC3339 format |

At most one of `current_message_id` and `current_task_id` is set. Both are `null`
for an empty Conversation. `status` summarizes the Conversation and does not
represent the complete state of one Task.

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "conversation_id": "conv_01",
        "workspace_id": "ws_01",
        "title": "316L process comparison",
        "is_pinned": false,
        "current_message_id": "msg_06",
        "current_task_id": null,
        "path_revision": 3,
        "forked_from_message_id": null,
        "status": "idle",
        "created_at": "2026-11-19T02:00:00Z",
        "updated_at": "2026-11-19T02:15:00Z"
      }
    ],
    "limit": 50,
    "offset": 0
  },
  "meta": null
}
```

### `POST /api/v1/conversations`

Create an empty Conversation.

Request body:

```json
{"workspace_id":"ws_01"}
```

Success returns HTTP `201` and the new `ConversationSummary`. Creating an empty
Conversation does not create a Task or Message. If the workspace does not exist or
does not belong to the authenticated user, the endpoint returns `404` with
`workspace_not_found`.

### `GET /api/v1/conversations/{conversation_id}`

Return Conversation metadata and its current path selection. Read Message content
and the complete Message path through the messages endpoint below.

Path parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `conversation_id` | string | yes | Conversation identity to read |

This endpoint has no query parameters or request body.

The response is the `Conversation` object described above.

```http
GET /api/v1/conversations/conv_01
```

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "conversation_id": "conv_01",
    "workspace_id": "ws_01",
    "title": "316L process comparison",
    "is_pinned": false,
    "current_message_id": "msg_06",
    "current_task_id": null,
    "path_revision": 3,
    "forked_from_message_id": null,
    "status": "idle",
    "created_at": "2026-11-19T02:00:00Z",
    "updated_at": "2026-11-19T02:15:00Z"
  },
  "meta": null
}
```

Possible error: `conversation_not_found`. The response does not reveal whether a
Conversation exists for another authenticated user.

### `PUT /api/v1/conversations/{conversation_id}/title`

Update the Conversation title. This changes metadata only and does not modify
Messages, Tasks, Operations, or the current path.

Path parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `conversation_id` | string | yes | Conversation identity to update |

Request body:

| Field | Type | Required | Constraint |
| --- | --- | --- | --- |
| `title` | string | yes | 1-160 characters after trimming; NUL, CR, and LF are forbidden |

```json
{"title":"New title"}
```

The endpoint returns the updated `Conversation` object. The server stores the title
after trimming leading and trailing whitespace.

Possible errors:

- `conversation_not_found`
- `conversation_title_invalid`

### `PUT /api/v1/conversations/{conversation_id}/pin`

Update the sidebar pin state. Setting the current value succeeds and is idempotent.

Path parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `conversation_id` | string | yes | Conversation identity to update |

Request body:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `is_pinned` | boolean | yes | `true` to pin, `false` to unpin |

```json
{"is_pinned":true}
```

The endpoint returns the updated `Conversation` object. Pinning does not create a
Task, change the Message path, or change the Conversation's chat activity time.

Possible errors: `conversation_not_found`, `conversation_pin_invalid`.

### `DELETE /api/v1/conversations/{conversation_id}`

Soft-delete the Conversation. The Conversation, Message, Task, ModelCall, Operation,
and feedback records remain available for audit. Ordinary list, detail, Message,
and Agent queries hide the deleted Conversation. The tree keeps only a deleted-source
marker without Message content.

Path parameters:

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `conversation_id` | string | yes | Conversation identity to delete |

This endpoint has no query parameters or request body.

Successful response:

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "meta": null
}
```

The delete transaction changes `accepted`, `running`, `approval_required`, and
`interrupted` Tasks to `cancelled`. It changes `requested`, `approval_required`, and
`approved` Operations to `rejected`, and changes a running Operation to
`needs_reconciliation` because the transaction cannot infer whether its external
side effect completed. Repeating the delete succeeds.

A deleted source Conversation does not prevent its child Fork from remaining usable.
The tree marks the source with `edge_kind: "fork_deleted_source"` and
`deleted_source: true`, without returning the source Message body.

The only documented error is `conversation_not_found`.

## 2. Read the Current Message Path

### `GET /api/v1/conversations/{conversation_id}/messages`

Return the Message path from the Conversation's saved current selection. Each
Message includes the authenticated user's feedback, and the response includes
active Task summaries. Each active Task contains `task_id`, `status`, and
`checkpoint_revision` for `accepted`, `running`, `approval_required`, and
`interrupted` Tasks. `source_contexts` preserves saved source-location metadata.

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "conversation": {"conversation_id":"conv_01","path_revision":3},
    "tip_message_id": "msg_06",
    "items": [
      {
        "message_id":"msg_01",
        "role":"user",
        "content":"Compare these two papers.",
        "my_feedback":null
      },
      {
        "message_id":"msg_02",
        "role":"assistant",
        "content":"Both papers examine 316L.",
        "my_feedback":{
          "feedback_id":"feedback_01",
          "rating":"helpful",
          "reason":null,
          "comment":"The comparison conditions are clear.",
          "response_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "created_at":"2026-11-19T02:20:00Z",
          "updated_at":"2026-11-19T02:20:00Z"
        }
      }
    ],
    "active_tasks": [],
    "meta": {"has_more": false}
  },
  "meta": null
}
```

`items` are ordered from the root Message to the current tip. Historical context
Messages do not acquire Task ownership when a new Task reads them. `my_feedback` is
the authenticated user's feedback object, or `null` when no feedback exists. User
and tool Messages normally have `null` feedback.

## 3. Save the Current Path

### `PUT /api/v1/conversations/{conversation_id}/active-path`

The request must contain `expected_path_revision` and exactly one target.

```json
{"expected_path_revision":3,"tip_message_id":"msg_06"}
```

The target can also be a running, approval-waiting, or completed Task:

```json
{"expected_path_revision":3,"task_id":"task_07"}
```

The target must belong to the current Conversation. A stale revision returns HTTP
`409` with `meta.error_code` set to `conversation_path_conflict` and
`meta.current_path_revision` set to the server revision. The client should reread
the current revision and submit the user's last selected target. The conflict should
not normally be shown as a user-facing error. Re-selecting the same target does not
increment the revision.

When a user selects a version, the client may update its local display before saving
the selection. If the server returns a conflict, the client rereads
`current_message_id` and `path_revision`, confirms that the last selection remains
the user's intent, and retries. Show an error only when the target is missing,
unauthorized, or no longer available, then restore the server-confirmed path.

## 4. Send a New Message

### `POST /api/v1/conversations/{conversation_id}/messages`

Send a new question from a selected continuation point and create a Task.

The optional `request_id` is used only for log correlation. Every accepted logical
execution receives a new `task_id`; a retry never looks up an old Task by
`request_id`.

Request body:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `request_id` | UUID | no | Log correlation only; not a business identity |
| `parent_message_id` | string / null | yes | Message receiving the follow-up, or `null` for an empty Conversation |
| `message` | string | yes | 1-12000 characters, stored after trimming |
| `source_contexts` | object[] | no | Validated source context, default `[]` |
| `model_connection_id` | string / null | no | Model connection binding |
| `permission_mode` | string | no | `read_only`, `confirm`, or `auto`, default `confirm` |

The transaction saves the user Message before creating the `agent_tasks` record.
After the Task commits, the caller explicitly invokes the Agent direct execution
entry point. The response is `TaskAccepted` with the new `task_id` and initial state.

```json
{
  "task_id":"task_07",
  "trigger_message_id":"msg_07",
  "status":"accepted"
}
```

## 5. Edit a Question

### `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/edits`

The target must be a saved user Message in the current Conversation. The server
creates a new user Message under the original parent and creates a Task for it.

The request must contain at least:

```json
{
  "request_id":"00000000-0000-4000-8000-000000000001",
  "message":"Compare only samples using the same heat-treatment conditions."
}
```

The original `source_contexts` are reused by default. Passing `source_contexts: []`
explicitly clears them.

## 6. Retry an Answer

### `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/regenerations`

The target must be a saved user Message.

Request body:

```json
{"request_id":"00000000-0000-4000-8000-000000000002"}
```

The retry uses the original user Message as `trigger_message_id` and creates a new
Task. Each explicit retry receives a new `task_id`. The request's `request_id` is
used only for log correlation, so multiple retries can run in parallel.

## 7. Common Errors

| `error_code` | Description |
| --- | --- |
| `conversation_not_found` | The Conversation does not exist or does not belong to the authenticated user |
| `message_not_found` | The Message does not exist or does not belong to the Conversation |
| `task_not_found` | The Task does not exist, belongs to another Conversation, or cannot be selected in its current state |
| `message_parent_invalid` | The continuation target is not a valid saved path tip |
| `message_content_invalid` | The Message is empty, too long, or contains a forbidden character |
| `conversation_path_conflict` | `path_revision` is stale |
| `source_context_invalid` | The source context does not exist, is forged, or is expired |
