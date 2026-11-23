[[31mERROR[0m] - (starship::print): Under a 'dumb' terminal (TERM=dumb).
# Conversation API

本文档负责对话列表、打开对话、消息路径、发送、编辑和重试。

V3 已接入列表、创建、详情、当前消息路径、路径选择、标题、置顶和
[Feedback](feedback-api.md)。现有线性历史的父链和当前选择由历史回填阶段建立。

<!-- vim-markdown-toc GFM -->

* [1. 对话列表](#1-对话列表)
  * [`GET /api/v1/conversations`](#get-apiv1conversations)
  * [`POST /api/v1/conversations`](#post-apiv1conversations)
  * [`GET /api/v1/conversations/{conversation_id}`](#get-apiv1conversationsconversation_id)
  * [`PUT /api/v1/conversations/{conversation_id}/title`](#put-apiv1conversationsconversation_idtitle)
  * [`PUT /api/v1/conversations/{conversation_id}/pin`](#put-apiv1conversationsconversation_idpin)
  * [`DELETE /api/v1/conversations/{conversation_id}`](#delete-apiv1conversationsconversation_id)
* [2. 读取当前消息路径](#2-读取当前消息路径)
  * [`GET /api/v1/conversations/{conversation_id}/messages`](#get-apiv1conversationsconversation_idmessages)
* [3. 保存当前路径](#3-保存当前路径)
  * [`PUT /api/v1/conversations/{conversation_id}/active-path`](#put-apiv1conversationsconversation_idactive-path)
* [4. 发送新消息](#4-发送新消息)
  * [`POST /api/v1/conversations/{conversation_id}/messages`](#post-apiv1conversationsconversation_idmessages)
* [5. 编辑问题](#5-编辑问题)
  * [`POST /api/v1/conversations/{conversation_id}/messages/{message_id}/edits`](#post-apiv1conversationsconversation_idmessagesmessage_idedits)
* [6. 重试回答](#6-重试回答)
  * [`POST /api/v1/conversations/{conversation_id}/messages/{message_id}/regenerations`](#post-apiv1conversationsconversation_idmessagesmessage_idregenerations)
* [7. 公共错误](#7-公共错误)

<!-- vim-markdown-toc -->
## 1. 对话列表

### `GET /api/v1/conversations`

查询一个工作空间中的对话。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `workspace_id` | string | 是 | 工作空间身份 |
| `limit` | integer | 否 | 1-100，默认 50 |
| `offset` | integer | 否 | 非负整数，默认 0 |

返回 `ConversationSummary[]`。列表中的 `status` 是摘要值：存在等待审批或
决定恢复的 Task 时为 `approval`，存在运行中 Task 时为 `running`，其余为
`idle`。

### `Conversation` 返回字段

列表、详情、标题更新和置顶更新都返回以下对话对象。`ConversationSummary`
使用同一字段集合，列表接口只额外包装分页字段。

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | string | 否 | 对话稳定身份 |
| `workspace_id` | string | 否 | 所属工作空间稳定身份 |
| `title` | string | 是 | 已保存标题；空白对话可以为 `null` |
| `is_pinned` | boolean | 否 | 是否固定，默认 `false` |
| `current_message_id` | string | 是 | 当前选中的已保存消息路径末端 |
| `current_task_id` | string | 是 | 当前选中的运行中或已完成 Task |
| `path_revision` | integer | 否 | 当前路径版本，初始为 `0` |
| `forked_from_message_id` | string | 是 | 显式 Fork 的来源消息；根对话为 `null` |
| `status` | string | 否 | `idle`、`running` 或 `approval` |
| `created_at` | datetime | 否 | UTC RFC3339 创建时间 |
| `updated_at` | datetime | 否 | UTC RFC3339 最近更新时间 |

`current_message_id` 和 `current_task_id` 最多一个有值。对话为空时两者都为
`null`。`status` 是摘要状态，不代表某个单独 Task 的完整状态。

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "conversation_id": "conv_01",
        "workspace_id": "ws_01",
        "title": "316L 工艺比较",
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

创建空白对话。

请求正文：

```json
{"workspace_id":"ws_01"}
```

成功时 HTTP 返回 `201` 和新建的 `ConversationSummary`。创建空白对话不会创建
Task 或 Message。工作空间不存在或不属于当前用户时返回 `404` 和 `workspace_not_found`。

### `GET /api/v1/conversations/{conversation_id}`

返回对话元数据和当前路径选择。消息正文和完整消息路径通过下方的 messages
接口读取。

路径参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | string | 是 | 要读取的对话身份 |

无查询参数和请求正文。

返回字段为上方的 `Conversation` 对象。

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
    "title": "316L 工艺比较",
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

可能的错误：`conversation_not_found`。对话不存在或不属于当前认证用户时，
不返回其他用户的存在信息。

### `PUT /api/v1/conversations/{conversation_id}/title`

更新对话标题，只修改元数据，不修改消息、Task、Operation 或当前路径。

路径参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | string | 是 | 要更新的对话身份 |

请求正文：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `title` | string | 是 | 去除首尾空白后 1-160 字符；禁止 NUL、CR、LF |

```json
{"title":"新的标题"}
```

返回更新后的 `Conversation` 对象。服务端保存去除首尾空白后的标题。

可能的错误：

- `conversation_not_found`
- `conversation_title_invalid`

### `PUT /api/v1/conversations/{conversation_id}/pin`

更新侧栏固定状态。设置为当前值时操作仍然成功且保持幂等。

路径参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | string | 是 | 要更新的对话身份 |

请求正文：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `is_pinned` | boolean | 是 | `true` 固定，`false` 取消固定 |

```json
{"is_pinned":true}
```

返回更新后的 `Conversation` 对象。置顶不会创建 Task，不改变消息路径，也不
改变对话的聊天活动时间。

可能的错误：`conversation_not_found`、`conversation_pin_invalid`。

### `DELETE /api/v1/conversations/{conversation_id}`

Soft-delete the Conversation. The Conversation, Message, Task, ModelCall, Operation,
and feedback records remain available for audit. Ordinary list, detail, message, and
Agent queries hide the deleted Conversation. The tree keeps only a deleted-source
marker without message content.

路径参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | string | 是 | 要删除的对话身份 |

无查询参数和请求正文。

成功响应：

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
`deleted_source: true`, without returning the source message body.

The only documented error is `conversation_not_found`.

## 2. 读取当前消息路径

### `GET /api/v1/conversations/{conversation_id}/messages`

按照对话中保存的当前选择返回消息路径。每条消息直接携带当前用户的反馈，
同时返回活动 Task 摘要。每项包含 `task_id`、`status` 和 `checkpoint_revision`，
覆盖 `accepted`、`running`、`approval_required` 和 `interrupted`。消息的
`source_contexts` 保留已保存的原文定位信息。

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
        "content":"比较这两篇论文。",
        "my_feedback":null
      },
      {
        "message_id":"msg_02",
        "role":"assistant",
        "content":"两篇论文都研究 316L。",
        "my_feedback":{
          "feedback_id":"feedback_01",
          "rating":"helpful",
          "reason":null,
          "comment":"比较条件说明得很清楚。",
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

`items` 沿父消息从根到当前末端排列。历史上下文消息不因为被新 Task
读取而增加任务归属。`my_feedback` 是当前用户对该消息的反馈对象，没有反馈
时为 `null`。user 和 tool message 通常始终为 `null`。

## 3. 保存当前路径

### `PUT /api/v1/conversations/{conversation_id}/active-path`

正文必须包含 `expected_path_revision`，并且只能选择一个目标。

```json
{"expected_path_revision":3,"tip_message_id":"msg_06"}
```

也可以选择正在运行、等待审批或已完成的 Task：

```json
{"expected_path_revision":3,"task_id":"task_07"}
```

目标必须属于当前对话。版本过期返回 HTTP `409`，`meta.error_code` 为
`conversation_path_conflict`，`meta.current_path_revision` 为服务端版本。前端应
在后台重新读取当前版本，并重新提交用户最后一次点击的目标。这个冲突不应
直接展示为用户错误。重复选择同一目标时版本不递增。

用户点击版本时，前端可以先切换本地显示，再提交保存请求。服务端返回冲突
时，前端重新读取 `current_message_id` 和 `path_revision`，确认最后一次点击
仍然是用户当前意图后重试。只有目标消息不存在、无权访问或已经不可用时，才
向用户展示提示，并恢复到服务端确认的路径。

## 4. 发送新消息

### `POST /api/v1/conversations/{conversation_id}/messages`

从指定的可继续消息末端发送一条新问题，并创建一个 Task。

请求中的 `request_id`（如果客户端提供）只用于日志关联。每次接受的逻辑执行都生成新的
`task_id`，重试不会通过 `request_id` 找回旧 Task。

请求正文：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `request_id` | UUID | 否 | 仅用于日志关联，不保存为业务身份 |
| `parent_message_id` | string / null | 是 | 追问接入的消息，空对话为 null |
| `message` | string | 是 | 1-12000 字符，去除首尾空白后保存 |
| `source_contexts` | object[] | 否 | 已验证的原文上下文，默认 `[]` |
| `model_connection_id` | string / null | 否 | 绑定的模型连接 |
| `permission_mode` | string | 否 | `read_only`、`confirm` 或 `auto`，默认 `confirm` |

事务内先保存 user message，再创建 `agent_tasks` 记录。Task 提交成功后由调用方
显式调用 Agent 的直接执行入口。返回 `TaskAccepted`，其中包含 `task_id` 和初始状态。

```json
{
  "task_id":"task_07",
  "trigger_message_id":"msg_07",
  "status":"accepted"
}
```

## 5. 编辑问题

### `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/edits`

目标必须是当前对话中已保存的 user message。服务端在目标消息的原父节点
下创建新的 user message，并用新消息创建 Task。

请求正文至少包含：

```json
{
  "request_id":"00000000-0000-4000-8000-000000000001",
  "message":"只比较使用相同热处理条件的试样。"
}
```

默认沿用原问题的 `source_contexts`。传入 `source_contexts: []` 表示明确清空。

## 6. 重试回答

### `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/regenerations`

目标必须是已保存的 user message。请求正文：

```json
{"request_id":"00000000-0000-4000-8000-000000000002"}
```

重试使用原 user message 作为 `trigger_message_id`，创建新的 Task。每次主动
重试都生成新的 `task_id`，请求中的 `request_id` 只作为日志关联，多个重试可以并行。

## 7. 公共错误

| `error_code` | 说明 |
| --- | --- |
| `conversation_not_found` | 对话不存在或不属于当前用户 |
| `message_not_found` | 消息不存在或不属于当前对话 |
| `task_not_found` | Task 不存在、不属于当前对话或当前状态不能作为路径目标 |
| `message_parent_invalid` | 追问目标不是可继续的路径末端 |
| `message_content_invalid` | 消息为空、超长或包含禁止字符 |
| `conversation_path_conflict` | `path_revision` 已过期 |
| `source_context_invalid` | 原文上下文不存在、伪造或已过期 |
