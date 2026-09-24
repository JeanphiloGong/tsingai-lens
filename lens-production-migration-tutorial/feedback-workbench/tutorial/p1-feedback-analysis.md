# P1：反馈分析任务闭环

**起点**：Lens 当前生产基线已经能保存 Chat 消息、工具结果、Source 和点赞/点踩反馈，但没有把反馈转换成可追溯的分析对象。

**本版结果**：用户保存一条有效反馈后，系统创建一个幂等的 `feedback_analysis` 任务。显式运行 Worker 后，任务从真实会话和模型调用读取上下文，保存 `AnalysisResult`、`EvidenceCoverage` 和最小 `FeedbackCase`。AI 只提供候选分析，不能修改聊天、宣布回答错误或批准训练数据。

## 真实场景

材料研究者在一个 Collection 中比较三篇论文，回答声称“文献 B 没有预热信息”，但信息实际位于 B 的图注。研究者对回答点踩并留下原因。系统需要回答“模型实际检查了哪些来源、漏掉了什么”，而不是把点踩直接当成科学结论。

```text
ChatMessageFeedback
  -> AnalysisJob(feedback_analysis)
  -> FeedbackAnalysisWorker
  -> AnalysisResult + EvidenceCoverage
  -> FeedbackCase(status=needs_annotation)
```

用户不输入 `job_id`、`case_id` 或 `source_ref`。这些值由页面和服务端自动携带，用于稳定引用、并发校验和审计。

## 边界

- 当前验证阶段不建立 RBAC。能访问 Collection 的登录用户可以运行后续工作台动作。
- `ChatModelCall` 是后台审计事实，不是用户要理解的 prompt，也不是 Evidence 或 Finding。
- `AnalysisResult` 是 AI 假设；来源不足、无法比较和工具失败必须保留各自语义。
- 不添加常驻调度平台、租约字段、自动重试计数或部署配置。
- 反馈撤回不会生成新的分析结论；Worker 发现待处理反馈已撤回时将任务置为 `cancelled`。

## 1. 读取生产基线

在 Lens 生产仓库的隔离工作区中先运行现有 Chat、反馈和 Source 测试，确认缺口：保存点踩后没有 `AnalysisJob`、`AnalysisResult` 或 `FeedbackCase`。重点阅读：

```text
backend/domain/chat/feedback.py
backend/application/chat/session_service.py
backend/controllers/chat/sessions.py
backend/application/chat/model.py
backend/infra/llm/chat_model.py
backend/application/chat/agent_runner.py
backend/infra/persistence/postgres/chat_repository.py
```

不要从聊天历史事后拼造模型请求。没有持久请求快照的历史回答只能显示“无调用记录”。

## 2. 保存实际模型调用

在 Provider SDK 调用前保存完整、裁剪后的 JSON 请求，至少包含 `messages`、`tools`、模型参数、stream 选项和 `purpose`。调用完成后写入受控状态、Provider 响应证据、用量和错误码。

涉及文件：

```text
backend/application/repositories/chat_repository.py
backend/infra/persistence/postgres/models/chat.py
backend/infra/persistence/postgres/models/__init__.py
backend/infra/persistence/postgres/chat_repository.py
backend/application/chat/model.py
backend/infra/llm/chat_model.py
backend/application/chat/agent_runner.py
backend/main.py
backend/controllers/chat/sessions.py
backend/controllers/schemas/chat/session.py
```

`ChatModelCall` 至少保存：`call_id`、`session_id`、触发消息、结果消息、`purpose`、`model`、`request`、`request_digest`、状态、起止时间、错误码、`provider_confirmed` 和 token 用量。请求持久化失败时不得调用 Provider；重试使用新 `call_id`。

增加迁移 `chat_model_calls`，其 `down_revision` 必须从当前 `alembic heads` 读取。不能把认证头、密钥或环境变量写入快照。

## 3. 建立分析对象

新增生产模块：

```text
backend/domain/feedback/analysis_job.py
backend/domain/feedback/evidence_coverage.py
backend/domain/feedback/analysis_result.py
backend/domain/feedback/feedback_case.py
backend/application/repositories/analysis_job_repository.py
backend/application/repositories/feedback_case_repository.py
backend/application/feedback/analysis_handler.py
backend/application/feedback/analysis_worker.py
backend/infra/persistence/postgres/models/feedback.py
backend/infra/persistence/postgres/analysis_job_repository.py
backend/infra/persistence/postgres/feedback_case_repository.py
```

任务信封只保存调度字段和版本化 payload：

```json
{
  "job_type": "feedback_analysis",
  "payload_version": 1,
  "payload": {"feedback_id": "feedback_123"}
}
```

任务表不增加 `locked_at`、`locked_by` 或 `attempt_count`，也不把不同任务类型的 `session_id`、`message_id`、`tool_call_id` 做成一组可空列。Handler 按 `job_type + payload_version` 校验输入，再从反馈反查会话、回答、模型调用、工具结果和 Source。

`EvidenceCoverage` 至少包含：

```text
requested_scope[]
inspected_sources[]
omitted_candidates[]
claim_support[]
gaps[]
coverage_status = complete | partial | failed | unknown
```

`FeedbackCase` 引用原 Chat 和 Collection，不复制或改写原始消息。最小状态为 `detected -> collecting_context -> needs_annotation`，技术执行失败保存在任务/结果错误字段中，不冒充案例状态。

## 4. 把反馈接到任务创建

在 `ChatSessionService.set_message_feedback_for_user` 保存有效反馈后创建任务：

1. 使用持久化的 `feedback_id` 和反馈版本组成 `idempotency_key`。
2. 相同 PUT 不重复创建任务；原因、评论或回答摘要改变时产生新版本任务。
3. payload 只保存 `feedback_id`，不接受客户端指定 owner 或操作者。
4. 服务端重新验证 Session 和 Collection 访问范围。
5. 撤回反馈时，Worker 将尚未执行的任务标记 `cancelled`，不写分析结果或案例。

反馈写入和任务创建要有清楚的事务边界。任务创建失败时保留反馈，并返回可重试的受控错误，不能声称分析已完成。

## 5. 显式运行 Worker

实现：

```text
FeedbackAnalysisWorker.run_once()
  -> claim_next_feedback_analysis_job()
  -> FeedbackAnalysisHandler.handle(job)
  -> save AnalysisResult and FeedbackCase
  -> mark succeeded or failed(error_code)
```

新增 `backend/scripts/feedback_analysis_worker.py`，支持运行一次或按显式参数循环。Worker 失败保留稳定错误码；人工重试使用新幂等任务或显式置回 `pending`。业务调用方不自行根据 `job_type` 写处理器分支。

## 6. 测试与冻结

至少增加或修改：

```text
backend/tests/unit/feedback/test_analysis_job.py
backend/tests/unit/feedback/test_analysis_worker.py
backend/tests/unit/application/test_chat_session_service.py
backend/tests/unit/infra/test_chat_model.py
backend/tests/integration/persistence/test_feedback_analysis.py
backend/tests/integration/persistence/test_chat_model_calls.py
backend/tests/unit/routers/test_chat_sessions_api.py
```

覆盖以下完整链路：问题 -> 回答 -> 点踩 -> 任务 -> Worker -> 分析结果 -> 案例。还要覆盖重复反馈、撤回、无效 JSON、超时、Provider 失败、Source 不足、跨 Collection 访问、历史回答没有真实调用记录，以及 Worker 不能写 Annotation、ReviewDecision 或 DatasetSnapshot。

P1 通过后创建独立文档和生产代码检查点。P2 只消费已验证的 `FeedbackCase`，不再引入旧的 `ChatCorrectionCase` 表。
