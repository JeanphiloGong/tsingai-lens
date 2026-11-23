[[31mERROR[0m] - (starship::print): Under a 'dumb' terminal (TERM=dumb).
# Conversation Tree API

本文档负责消息树、回答版本、版本切换和显式 Fork。消息版本和 Task 执行
是树中的不同节点类型。

## 1. 读取消息树

### `GET /api/v1/conversations/{conversation_id}/tree`

返回当前 Conversation 及其显式 Fork 连接的树。树中的节点包括：

- `message`：已保存的 user、assistant 或 tool message
- `task`：尚未形成最终消息或仍在运行的执行
- `conversation`：显式 Fork 后的新对话入口

If the Fork source Conversation has been soft-deleted, the tree keeps a source node
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

Deleting the source does not delete its child Fork. Opening the deleted source itself
still returns `conversation_not_found`. The child Fork remains readable through its own
Conversation identity.

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
        "preview":"两篇论文都研究 316L。"
      },
      {
        "node_id":"conversation:conv_02",
        "kind":"conversation",
        "parent_node_id":"message:msg_02",
        "edge_kind":"fork",
        "conversation_id":"conv_02",
        "message_id":null,
        "task_id":null,
        "preview":"316L 工艺比较 · 分支",
        "forked_from_message_id":"msg_02"
      }
    ]
  },
  "meta":null
}
```

正在运行的 Task 没有最终 message 时，以 `task:{task_id}` 节点挂在触发消息
下。Task 完成后，树读取已保存的 message 节点。

## 2. 切换已保存版本

### `PUT /api/v1/conversations/{conversation_id}/active-path`

版本切换接口定义在 [conversation-api.md](conversation-api.md)。树界面点击
message 或 Task 时，调用该接口保存用户的选择。

- 点击 message，提交 `tip_message_id`。
- 点击运行中或已完成的 Task，提交 `task_id`。
- 必须携带 `expected_path_revision`。
- 切换不会删除其他版本，也不会停止其他 Task。

## 3. 显式 Fork

### `POST /api/v1/conversations/{conversation_id}/forks`

从已保存的 user message 或完整 assistant message 创建新 Conversation。

请求正文：

```json
{
  "message_id":"msg_02"
}
```

服务端在一个事务中完成：

1. 检查来源消息属于当前用户、工作空间和 Conversation。
2. 检查选定路径上的必要 Operation 已进入终态。
3. 创建新的 Conversation。
4. 复制选定路径的 Message，并写入 `copied_from_message_id`。
5. 设置新 Conversation 的初始当前路径。

Fork 返回新 Conversation：

```json
{
  "conversation_id":"conv_02",
  "workspace_id":"ws_01",
  "title":"316L 工艺比较 · 分支",
  "forked_from_message_id":"msg_02",
  "current_message_id":"msg_copy_02",
  "current_task_id":null,
  "path_revision":0
}
```

Fork 创建本身不创建新的 Task。用户在新 Conversation 中发送第一条问题时，
才创建新的 Task。

## 4. 树节点的打开行为

| 点击节点 | 操作 |
| --- | --- |
| 已保存 message | 调用 `active-path`，读取该消息的父链 |
| 运行中 Task | 调用 `active-path` 选择该 Task，订阅 Task SSE |
| Fork Conversation | 使用新的 `conversation_id` 调用 messages 接口 |

不同 Conversation 的消息不会合并成同一条当前路径。Fork 只通过来源关系
在树视图中连接它们。

## 5. 树相关错误

| `error_code` | 说明 |
| --- | --- |
| `tree_message_not_found` | 树节点消息不存在或不可见 |
| `tree_target_not_saved` | 目标仍是未持久化的增量 |
| `fork_source_not_ready` | 来源路径存在未结束 Operation |
| `fork_request_conflict` | 相同 Fork 请求身份对应不同来源 |
| `fork_conversation_conflict` | 来源对话已有不可复制的活动状态 |
