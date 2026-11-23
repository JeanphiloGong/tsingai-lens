[[31mERROR[0m] - (starship::print): Under a 'dumb' terminal (TERM=dumb).
# Task API

本文档负责一次 Agent 执行的状态、并行回答、SSE、停止、恢复和 Operation
审批。它取代旧的 `response-api.md`。执行身份统一使用 `task_id`。

请求中的 `request_id` 只用于日志和链路关联，不生成或查找 `task_id`，也不作为数据库
唯一键。每次被接受的逻辑执行都由服务端生成新的 `task_id`。

## 1. 查询 Task

### `GET /api/v1/conversations/{conversation_id}/tasks/{task_id}`

返回一个 Task 的当前状态和恢复信息。完整模型调用、Operation 和 Step 只在
Task 详情接口返回。

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

查询当前对话的 Task。支持 `status`、`limit` 和 `offset` 查询参数。前端
恢复页面时可以只查询 `running`、`approval_required` 和 `interrupted`。

## 2. SSE 输出

### `GET /api/v1/conversations/{conversation_id}/tasks/{task_id}/events`

以 `text/event-stream` 返回 Task 的快照和增量事件。断线重连使用查询参数
`after_revision`，服务端返回该检查点之后的事件或当前完整快照。

事件示例：

```text
event: task.snapshot
data: {"task_id":"task_07","revision":4,"status":"running"}

event: message.delta
data: {"task_id":"task_07","message_id":"msg_09","content":"正在读取文件"}

event: operation.updated
data: {"task_id":"task_07","operation_id":"op_03","status":"succeeded"}

event: task.completed
data: {"task_id":"task_07","final_message_id":"msg_10"}
```

客户端按 `revision` 丢弃旧事件。多个 Task 并行运行时，每条事件都包含
`task_id`，前端按 Task 分配输出。

## 3. 停止 Task

### `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/stop`

请求正文：

```json
{"request_id":"00000000-0000-4000-8000-000000000003"}
```

停止请求先把 Task 标记为 `interrupted`。当前直接执行调用在下一个 checkpoint
边界观察这个状态并结束，响应状态为 `interrupted` 或 `cancelled` 时，才表示执行已结束。

## 4. 恢复 Task

### `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/resume`

用于进程中断、网络断开或用户重新打开页面后的显式恢复。调用方提交恢复请求后，
再次直接调用 `TaskExecution.run_task()`，继续使用原 `task_id` 和最近的
`checkpoint_revision`。

请求正文：

```json
{
  "request_id":"00000000-0000-4000-8000-000000000004",
  "expected_checkpoint_revision":4
}
```

审批等待状态使用下方的 Operation decision 接口恢复。用户主动重新生成会
创建新的 Task，不使用 resume 接口。

## 5. Operation 审批

### `POST /api/v1/conversations/{conversation_id}/tasks/{task_id}/operations/{operation_id}/decision`

请求正文：

```json
{
  "decision":"approved",
  "arguments_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "request_id":"00000000-0000-4000-8000-000000000005"
}
```

`decision` 为 `approved` 或 `rejected`。服务端必须同时校验：

- Operation 属于路径中的 Task 和 Conversation。
- Operation 当前状态允许作出决定。
- `arguments_digest` 与待审批参数完全一致。
- 当前用户拥有该 Operation 所需的权限。

批准后由调用方提交后继续调用原 Task。拒绝后 Operation 进入 `rejected`，Task 根据
执行计划进入继续回答、失败或等待用户输入状态。

## 6. Operation 状态

```text
requested
  -> approval_required
  -> approved
  -> running
  -> succeeded / failed / needs_reconciliation
```

同一个 `operation_id` 可以有多个物理执行尝试。外部副作用结果未知时，
Operation 必须先进入 `needs_reconciliation`，不能直接自动重试。

## 7. Task 状态和错误

| 状态 | 说明 |
| --- | --- |
| `accepted` | 已写入 Task，尚未开始执行 |
| `running` | `TaskExecution` 正在执行 |
| `approval_required` | 等待用户对 Operation 作决定 |
| `completed` | 已产生最终回答 |
| `failed` | 发生不可恢复错误 |
| `interrupted` | 被停止或进程中断，仍可恢复 |
| `cancelled` | 用户明确取消，不能继续原执行 |

错误响应统一包含：

```json
{
  "code": 409,
  "message":"operation result is unknown",
  "data":null,
  "meta":{"error_code":"operation_needs_reconciliation"}
}
```

## 8. 并行执行规则

- 同一个 user message 可以有多个 Task，例如多次重试。
- 每个 Task 使用独立的 `task_id`、检查点和执行锁。
- 一个 Task 的增量不能写入另一个 Task 的消息路径。
- Conversation 的当前选择由前端通过 active-path 接口保存。
- Task 完成顺序不决定用户当前显示的版本。
