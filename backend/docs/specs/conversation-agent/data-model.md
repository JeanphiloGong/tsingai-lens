[[31mERROR[0m] - (starship::print): Under a 'dumb' terminal (TERM=dumb).
# Lens Conversation and Agent Data Model

状态：Conversation/Agent target contract

本文档是 Conversation 和 Agent 的后端持久化合同。它描述 Conversation、消息树
和 Agent Durable Execution 的持久化关系。当前生产运行时仍处于迁移阶段，生产
数据库只有在对应 Alembic migration 和观察窗口完成后才采用这些目标结构。

## 1. 设计决策

1. Conversation 拥有消息树。
2. Task 表示一次完整、可恢复的 Agent 执行。
3. User message 可以触发 Task，但通常不是该 Task 产生的消息。
4. Assistant 和 tool message 通过 `produced_by_task_id` 归属到 Task。
5. 模型工具请求属于 assistant message，并在 `agent_operations` 中保存执行状态。
   不建立独立的 `chat_tool_calls` 表。
6. `task_id` 是完整执行的唯一身份。`response_id` 不作为第二套执行身份存在。
7. `operation_id` 表示一次逻辑操作。物理执行重试继续使用同一个 `operation_id`。
8. Feedback 绑定具体 assistant message，不绑定整个 Task，也不进入模型上下文。

## 2. 领域关系

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

消息树回答用户和助手说了什么。Task 轨迹回答一轮助手回复怎样执行。Task
读取历史消息作为上下文时，不会因此拥有这些历史消息。

## 3. `chat_conversations`

每行表示工作空间侧栏中的一条对话。当前路径字段是用户当前选择的投影，
不表示执行所有权。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `conversation_id` | varchar(128) | 否 | 对话身份 |
| `user_id` | varchar(64) | 否 | 对话所有者 |
| `workspace_id` | varchar(64) | 否 | 所属工作空间 |
| `title` | text | 是 | 侧栏标题 |
| `is_pinned` | boolean | 否 | 是否固定，默认 `false` |
| `current_message_id` | varchar(128) | 是 | 当前选中的消息路径末端 |
| `current_task_id` | varchar(128) | 是 | 当前选中的运行中或已完成 Task |
| `path_revision` | bigint | 否 | 路径选择版本，初始为 `0` |
| `forked_from_message_id` | varchar(128) | 是 | 显式 Fork 的来源消息 |
| `created_at` | timestamptz | 否 | 创建时间 |
| `updated_at` | timestamptz | 否 | 最近一次对话或元数据更新时间 |

`current_message_id` 和 `current_task_id` 最多一个有值。对话为空时两者都为
`null`。一个 Conversation 可以同时有多个运行中的 Task。

## 4. `chat_messages`

消息在同一 Conversation 内组成树。父关系创建后不可修改。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `message_id` | varchar(128) | 否 | 消息身份 |
| `conversation_id` | varchar(128) | 否 | 所属对话 |
| `parent_message_id` | varchar(128) | 是 | 当前路径中的上一条消息 |
| `role` | varchar(16) | 否 | `user`、`assistant` 或 `tool` |
| `content` | text | 否 | 消息正文，工具消息可以为空字符串 |
| `produced_by_task_id` | varchar(128) | 是 | 产生 assistant/tool 消息的 Task |
| `copied_from_message_id` | varchar(128) | 是 | 显式 Fork 复制时的来源消息 |
| `tool_call_id` | varchar(128) | 是 | 模型工具调用身份 |
| `operation_id` | varchar(128) | 是 | 没有模型 `tool_call_id` 的内部 Operation 身份 |
| `source_contexts` | jsonb | 否 | 已验证的原文附件，默认 `[]` |
| `created_at` | timestamptz | 否 | 创建时间 |

普通 user message 的 `produced_by_task_id` 为空。Task 读取的历史上下文不会
增加新的任务归属关系。

assistant message 保存模型输出的结构化工具请求。工具请求属于该消息的内容，
不单独作为 `chat_tool_calls` 表中的消息实体。

模型产生的 tool message 使用 `tool_call_id` 关联 assistant 请求和 Operation。
内部 Operation 没有模型工具调用时，使用 `operation_id` 关联其 tool message。

## 5. `chat_message_feedback`

一行表示当前用户对一条 assistant 回答的评价。它用于回答下方的“有帮助 / 没
帮助”，不修改消息内容，不改变 Task，也不进入模型上下文。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `feedback_id` | varchar(64) | 否 | 评价身份 |
| `conversation_id` | varchar(128) | 否 | 所属对话 |
| `message_id` | varchar(128) | 否 | 被评价的 assistant message |
| `user_id` | varchar(64) | 否 | 提交评价的认证用户 |
| `rating` | varchar(16) | 否 | `helpful` 或 `not_helpful` |
| `reason` | varchar(16) | 是 | `incorrect`、`incomplete`、`unclear` 或 `other`；只用于负面评价 |
| `comment` | text | 是 | 用户补充说明，最多 2000 字符 |
| `response_digest` | varchar(64) | 否 | 被评价回答正文的 SHA-256 摘要 |
| `created_at` | timestamptz | 否 | 首次评价时间 |
| `updated_at` | timestamptz | 否 | 最近修改时间 |

约束：

- `message_id` 必须指向同一对话中角色为 `assistant` 的消息。
- `(user_id, message_id)` 唯一，同一用户对同一回答只有一条当前评价。
- `user_id` 从认证上下文取得，不由客户端提交。
- 消息接口把当前用户的记录投影为 `items[].my_feedback`，没有评价时为 `null`。
- 删除评价只删除评价行，不删除 assistant message。

## 6. `agent_tasks`

每行表示一次完整、可恢复的 Agent 执行。普通用户触发的 Task 从一条已保存
的 user message 开始，并可以产生多条 assistant/tool message。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `task_id` | varchar(128) | 否 | Durable Execution 身份 |
| `conversation_id` | varchar(128) | 否 | 所属对话 |
| `trigger_kind` | varchar(32) | 否 | `user_message`、`approval`、`retry`、`schedule` 或 `system` |
| `trigger_message_id` | varchar(128) | 是 | 触发 Task 的 user message |
| `final_message_id` | varchar(128) | 是 | 最终 assistant message |
| `status` | varchar(32) | 否 | `accepted`、`running`、`approval_required`、`completed`、`failed`、`interrupted` 或 `cancelled` |
| `checkpoint_revision` | bigint | 否 | 单调递增的检查点版本 |
| `checkpoint` | jsonb | 否 | Task 恢复状态 |
| `model_connection_id` | varchar(64) | 是 | 本次执行绑定的模型连接 |
| `model_connection_name` | text | 是 | 模型连接显示快照 |
| `started_at` | timestamptz | 否 | 执行开始时间 |
| `updated_at` | timestamptz | 否 | 最近一次状态或检查点更新时间 |
| `finished_at` | timestamptz | 是 | 终态时间 |

`trigger_kind = user_message` 时，`trigger_message_id` 必须指向同一对话中角色
为 `user` 的消息。审批恢复和系统任务可以没有触发消息。Task 等待审批、被
中断或失败且没有最终回答时，`final_message_id` 为空。

## 7. `chat_model_calls`

每行记录 Task 内的一次模型供应商请求。一个 Task 可以因为工具调用和恢复
产生多次 ModelCall。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `model_call_id` | varchar(128) | 否 | 模型请求审计身份 |
| `task_id` | varchar(128) | 否 | 所属 Task |
| `sequence` | integer | 否 | Task 内的零基顺序 |
| `provider` | varchar(64) | 否 | 模型供应商 |
| `model` | varchar(128) | 否 | 模型名称 |
| `purpose` | varchar(64) | 否 | `answer`、`tool_followup` 等请求用途 |
| `request_digest` | varchar(64) | 否 | 请求摘要 |
| `response_digest` | varchar(64) | 是 | 供应商响应摘要 |
| `status` | varchar(24) | 否 | `started`、`succeeded` 或 `failed` |
| `input_tokens` | integer | 是 | 输入 token 数 |
| `output_tokens` | integer | 是 | 输出 token 数 |
| `error_code` | varchar(128) | 是 | 稳定的供应商或运行时错误 |
| `started_at` | timestamptz | 否 | 请求开始时间 |
| `finished_at` | timestamptz | 是 | 请求结束时间 |

## 8. `agent_operations`

这是工具或其他外部操作的唯一持久化记录。它保存模型提出的操作意图、审批、
执行、幂等、恢复和结果状态。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `operation_id` | varchar(128) | 否 | 稳定的逻辑操作身份 |
| `task_id` | varchar(128) | 否 | 所属 Task |
| `tool_call_id` | varchar(128) | 是 | 适用时填写模型工具调用身份 |
| `assistant_message_id` | varchar(128) | 是 | 请求该操作的 assistant message |
| `name` | varchar(128) | 否 | 能力或操作名称 |
| `arguments` | jsonb | 否 | 已接受的确切参数 |
| `arguments_digest` | varchar(64) | 否 | 绑定审批和执行的参数摘要 |
| `risk` | varchar(16) | 否 | `read`、`draft`、`write` 或 `unknown` |
| `status` | varchar(32) | 否 | `requested`、`approval_required`、`approved`、`running`、`succeeded`、`failed`、`rejected` 或 `needs_reconciliation` |
| `idempotency_key` | varchar(128) | 是 | 外部副作用的稳定幂等键 |
| `result` | jsonb | 是 | 结构化操作结果 |
| `error_code` | varchar(128) | 是 | 稳定的失败原因 |
| `error_message` | text | 是 | 可展示的错误摘要 |
| `decision_user_id` | varchar(64) | 是 | 作出批准或拒绝的用户 |
| `decision_arguments_digest` | varchar(64) | 是 | 决定覆盖的参数摘要 |
| `decided_at` | timestamptz | 是 | 审批决定时间 |
| `started_at` | timestamptz | 是 | 第一次执行开始时间 |
| `finished_at` | timestamptz | 是 | 终态执行时间 |
| `created_at` | timestamptz | 否 | Operation 创建时间 |
| `updated_at` | timestamptz | 否 | 最近一次 Operation 更新时间 |

状态流转：

```text
requested
  -> approval_required
  -> approved
  -> running
  -> succeeded / failed / needs_reconciliation
```

超时或网络错误不会创建新的 Operation，而是在同一个 Operation 下产生新的
物理执行尝试。副作用结果未知时进入 `needs_reconciliation`，核实前禁止盲目
再次执行。若未来需要持久化每一次物理尝试，再增加 `chat_operation_attempts`。

## 9. `agent_task_steps`

Step 是 Durable Execution 的恢复检查点，不是 ModelCall，也不是科学研究结果。

| 字段 | 类型 | 可空 | 作用 |
| --- | --- | --- | --- |
| `step_id` | varchar(128) | 否 | Step 身份 |
| `task_id` | varchar(128) | 否 | 所属 Task |
| `sequence` | integer | 否 | Task 内顺序 |
| `name` | varchar(128) | 否 | 运行时步骤名称 |
| `status` | varchar(24) | 否 | `pending`、`running`、`completed` 或 `blocked` |
| `checkpoint` | jsonb | 否 | 恢复该 Step 所需的状态 |
| `started_at` | timestamptz | 是 | Step 开始时间 |
| `finished_at` | timestamptz | 是 | Step 完成时间 |

## 10. 一次完整执行

```text
M1 user：读取 target.py 并解释
  produced_by_task_id = null

T1
  trigger_message_id = M1
  status = running

M2 assistant：请求 read_file
  produced_by_task_id = T1
  tool_call_id = TC1

OP1
  task_id = T1
  tool_call_id = TC1
  operation_id = OP1
  status = approved

M3 tool：read_file 结果
  produced_by_task_id = T1
  tool_call_id = TC1

M4 assistant：最终解释
  produced_by_task_id = T1

T1
  final_message_id = M4
  status = completed
```

## 11. Fork、编辑和重试

### 重试

重试已保存的 user message 时，创建新的 Task，并继续使用同一个
`trigger_message_id`。新 Task 在同一 Conversation 中产生新的 assistant 分支。

### 编辑

编辑 user message 时，在原消息的父节点下创建新的 user message。新消息触发
新的 Task。

### 显式 Fork

Fork 创建新的 Conversation，并复制选定的消息路径。复制后的消息获得新的
消息 ID，并在 `copied_from_message_id` 中保留来源消息。只有选定路径需要历史
执行记录时，才复制已结束的 Task、Operation 和 ModelCall 作为只读历史。新对话
发送第一条新问题时才创建新的 Task。

## 12. 必须满足的不变量

1. 每条消息恰好属于一个 Conversation。
2. 每个 Task 恰好属于一个 Conversation。
3. Task 的触发消息如果存在，必须属于同一 Conversation。
4. Task 产生的消息和 Task 必须属于同一 Conversation。
5. 消息父节点必须属于同一 Conversation。
6. `operation_id` 在执行重试期间保持稳定。
7. 审批必须绑定精确的 `arguments_digest`。
8. 外部结果未知的 Operation 不得直接重复执行。
9. `final_message_id` 只能指向该 Task 产生的消息。
10. `current_message_id` 和 `current_task_id` 只描述用户当前视图，不改变历史归属。

## 13. 索引和约束

- `chat_messages(conversation_id, parent_message_id)` 用于消息树遍历。
- `chat_messages(produced_by_task_id)` 用于查询 Task 产出的消息。
- `agent_tasks(conversation_id, status, updated_at)` 用于查询活动 Task。
- `(task_id, sequence)` 唯一，保证 ModelCall 和 TaskStep 顺序稳定。
- `(task_id, operation_id)` 唯一，保证逻辑 Operation 身份稳定。
- `(user_id, message_id)` 唯一，保证每个用户对同一回答只有一条评价。

## 14. 迁移边界

当前生产结构使用 `chat_sessions`、线性消息位置、会话内回答快照、
`chat_tool_calls` 和 `chat_message_feedback`。迁移到本设计需要单独的迁移方案。

概念映射如下：

| 当前概念 | 目标概念 |
| --- | --- |
| `chat_sessions` | `chat_conversations` |
| `session_id` | `conversation_id` |
| `collection_id` | `workspace_id` |
| `chat_messages.position` | `parent_message_id` |
| 会话内 `response_snapshot` | `agent_tasks.checkpoint` |
| `response_id` | `task_id` |
| `chat_tool_calls` | `agent_operations` |
| 现有模型请求审计 | `chat_model_calls.task_id` |
| `chat_message_feedback.session_id` | `chat_message_feedback.conversation_id` |

迁移必须保留消息身份、Source 上下文、Feedback、工具结果和审计记录。旧线性
分支数据没有明确记录显式 Fork 意图时，不自动推断为显式 Fork。本设计没有执行
迁移，也没有修改当前 ORM。
