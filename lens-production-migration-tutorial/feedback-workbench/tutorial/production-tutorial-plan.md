# Lens Agent 反馈分析工作台：生产项目教程计划

状态：2026-09-24，计划与迁移进行中。本文冻结 P1–P6 的生产目标和验收边界；P1、P2 已在本仓库逐版实现，P3–P6 仍按检查点推进。六篇正文、契约和生产代码共用本仓库历史，不把旧 nano 教程的完成状态当成生产能力。

本计划依据三份设计文档：

- [API 设计](../api-design.md)
- [核心模型与流转](../core-models-and-flow.md)
- [数据库设计](../database-design.md)

目标是让读者在 Lens 生产仓库中实现并验证这条真实链路：

~~~
用户正常聊天并反馈
  -> FeedbackSignal
  -> AnalysisJob
  -> FeedbackAnalysisWorker
  -> AnalysisResult + EvidenceCoverage
  -> FeedbackCase
  -> Annotation
  -> ReviewDecision
  -> DatasetSnapshot
  -> evaluation / sft / preference JSONL
  -> 离线评测或训练
~~~

## 1. 真实场景

材料研究者在一个 Collection 中比较三篇论文，询问某个工艺变量对结果的影响。回答声称“文献 B 没有该信息”，但信息实际位于 B 的图注。研究者在正常 Chat 中点踩并选择原因，必要时补充评论。系统随后检查这次回答实际读过哪些 Source、模型输入是否包含 B、哪些主张有证据、哪些材料没有被检查。用户在工作台中阅读这些材料，确认问题类型和支持证据，决定是否允许它进入某一种数据集，最后冻结一份可复现的 JSONL。

这个场景包含几个不同的事实：

1. 点踩是“值得检查”的信号，不是科学结论。
2. AI 分析是候选判断，不得修改 Chat、宣布答案错误或批准数据。
3. 案例是供人处理的工作单元，不是一条自动生成的训练样本。
4. 标注回答“问题是什么、目标和证据是什么”；审核回答“这份标注能否用于某种数据集”。
5. 快照复制已审核内容和排除原因，之后不随源案例变化。

用户在页面上操作的是回答、论文、原文片段、问题类型、目标和数据用途。case_id、document_id、source_ref、摘要和并发版本字段由前端从当前页面自动携带，用户不需要输入或理解这些 ID。

当前验证阶段不建立 RBAC，也不区分标注员、审核员或数据集管理员。任何已登录且能访问 Collection 的用户都可以查看案例、标注、审核、创建快照和下载数据；owner_id、reviewer_id 只记录归属和实际操作历史。

## 2. 生产基线与缺口

### 基线

- 生产仓库：/src/users/lens/date/2026/aug/week3/17,Mon/lens-objective-evidence-grounding
- 计划基线：e964a99b28be6e30573aee69be4cf98b8bad2ac3
- 教程仓库：/src/users/lens/date/2026/sep/lens-production-migration-tutorial/feedback-workbench
- 教程迁移方式：从旧 nano 仓库复制当前工作内容，不保留其独立 Git 历史
- 后端运行时：FastAPI、SQLAlchemy、Alembic、PostgreSQL、Python 3.10+
- 前端运行时：SvelteKit 2、Svelte 5、Vitest、Playwright

生产工作区在本计划开始时已有用户未提交改动，涉及：

~~~
backend/docs/architecture/paper-experiment-domain-contract.md
backend/docs/specs/api.md
frontend/src/routes/_shared/i18n.ts
frontend/src/routes/collections/README.md
frontend/src/routes/collections/[id]/assistant/MessageComposer.svelte
frontend/src/routes/collections/[id]/assistant/OperationPermissions.svelte
frontend/src/routes/collections/[id]/assistant/ResearchConversation.svelte
frontend/src/routes/collections/[id]/assistant/assistant-page.svelte.spec.ts
frontend/src/routes/_shared/researchAgentSlashCommands.ts
frontend/src/routes/_shared/researchAgentSlashCommands.spec.ts
backend/application/core/objectives/analysis_service.py
backend/domain/chat/permissions.py
backend/main.py
backend/tests/unit/application/test_objective_analysis_service.py
backend/application/core/objectives/analysis/experiment_compatibility_projection.py
backend/tests/unit/application/test_experiment_compatibility_projection.py
~~~

这些改动与本教程规划无关，后续重放必须保留，不能用清理工作区的方式制造教程基线。

旧 nano 仓库的 v0/v1 文档、运行产物和独立源码不属于新的生产教程依赖。迁移后的统一仓库只保留 P1–P6 正文、计划和验证说明；旧仓库的 Git 历史不作为本教程基线。

### 已有能力

| 已有事实 | 生产路径与符号 | 对教程的影响 |
| --- | --- | --- |
| 点赞、点踩、原因、评论和撤回 | backend/domain/chat/feedback.py::ChatMessageFeedback；backend/application/chat/session_service.py::ChatSessionService.set_message_feedback_for_user；backend/controllers/chat/sessions.py 的 feedback 路由 | P1 复用现有反馈；它不是标注或审核记录 |
| 消息、工具调用、工具结果和 Source 轨迹 | backend/domain/chat/message.py::ChatMessage；backend/infra/persistence/postgres/chat_repository.py::PostgresChatRepository.save_trajectory | 分析器读取权威轨迹，不复制一套 Chat |
| Collection 与会话访问校验 | backend/application/source/collection_service.py::CollectionService.get_collection_for_user；ChatSessionService.get_session_for_user | 所有工作台接口复用现有范围校验 |
| Provider 调用入口 | backend/application/chat/model.py::ChatModel.respond；backend/infra/llm/chat_model.py::OpenAIChatModel.respond | P1 在 SDK 请求提交前保存内部 ChatModelCall |
| 应用装配 | backend/main.py | 新 Repository、Service、Worker 必须接入真实装配 |
| 旧反馈和 Finding 导出 | chat_message_feedback；backend/application/evaluation/finding_feedback_service.py | 不把用途反馈或 Finding 数据误当成新的 Chat 数据集 |
| 历史纠错表已清理 | backend/migrations/versions/20260924_0065_remove_chat_corrections.py | chat_correction_* 不存在于当前基线，不能恢复旧教程的表作为新模型 |
| 没有常驻分析 Worker | 当前只有应用内异步任务和脚本 | P1 使用显式 FeedbackAnalysisWorker.run_once()/CLI 验证，不假装已有调度平台 |
| pipeline_runs | backend/domain/source/pipeline_run.py 及对应 Repository | 它记录文献处理运行，不承担 AnalysisJob 语义 |

当前没有以下新能力：analysis_jobs、feedback_analysis_results、feedback_cases、feedback_annotations、审核历史、数据快照和反馈分析 Worker。也没有可供本流程读取的持久 ChatModelCall；历史回答不得事后拼装一个请求来冒充事实。

## 3. 不变量与已确定的边界

### 领域边界

核心对象按责任分层：

| 层次 | 对象 | 负责的问题 | 不能代表的东西 |
| --- | --- | --- | --- |
| 事实 | ChatSession、ChatMessage、ChatModelCall、工具结果、Source | 实际发生了什么、模型实际收到了什么 | 科学正确性 |
| 信号 | FeedbackSignal，第一种持久来源是 ChatMessageFeedback | 为什么值得分析 | 正确答案或训练准入 |
| 分析 | AnalysisJob、AnalysisResult、EvidenceCoverage | AI 认为可能漏了什么、证据覆盖如何 | 人工确认 |
| 整理 | FeedbackCase、Annotation、ReviewDecision | 人确认问题、目标、证据和准入 | 自动修改 Chat |
| 发布 | DatasetSnapshot | 哪些固定内容用于哪种实验 | 科学真理或在线模型更新 |

案例状态表示处理进度：

~~~
detected -> collecting_context -> needs_annotation -> ready_for_review
                                      |                    |
                                      +-> rejected          +-> accepted
                                      +-> insufficient      +-> withdrawn
~~~

failed 只表示技术执行失败，属于任务或分析结果；来源不足、回答有问题、人工拒绝不能都写成 failed。

### 任务边界

所有分析任务共用 analysis_jobs，输入由 job_type + payload_version + payload 解释。当前只实现：

~~~json
{
  "job_type": "feedback_analysis",
  "payload_version": 1,
  "payload": {"feedback_id": "feedback_123"}
}
~~~

任务调度字段为 job_id、status、available_at、started_at、finished_at、result_id、error_code、idempotency_key 和时间字段。当前验证阶段不添加 locked_at、locked_by 或 attempt_count；同类型多副本的租约、队列和恢复策略留给后续部署设计。任务失败保留错误码，人工重试由显式重新置为 pending 或创建新幂等任务完成。

FeedbackAnalysisWorker 只领取 feedback_analysis，Handler 校验 payload、读取反馈关联的消息/会话/模型调用/工具结果/Source，校验 AI JSON，保存结果，再将任务标记 succeeded 或 failed。AI 输出只创建或更新候选 FeedbackCase，不能直接写 Annotation、ReviewDecision 或 DatasetSnapshot。

### 数据准入边界

- Annotation 保存人工确认的 problem_type、严重程度、可空 target、支持 Source、dataset_uses 和理由，并生成 annotation_digest。
- ReviewDecision 是追加历史，决定值为 accept、reject、insufficient 或 withdraw；标注变化会使旧摘要失效。
- 一个 DatasetSnapshot 只有一个 dataset_type：evaluation、sft 或 preference。
- evaluation 可没有 target；sft 必须有明确 target、支持来源和训练授权；preference 必须有同一输入下的 chosen/rejected。
- 快照复制 rows、provenance、论文家族、会话树、split 和 exclusions；新案例变化或反馈撤回不修改旧快照。
- train/eval 不得共享论文家族或会话树；不合格项进入排除报告，不静默丢失。
- ChatModelCall.request 是后台审计输入，EvidenceCoverage 是用户可理解的诊断投影，二者不能互相替代。

## 4. 六个教程文件与版本线

每个版本是一项可观察的垂直能力，包含真实调用方、迁移、测试和必要的 UI；不是按 ORM、Repository、Service 人为拆层。本目录的六个文件已经按这个边界整理，build 阶段负责在真实生产代码上逐版重放并补齐实测证据。

| 版本 | 教程文件 | 从哪里开始 | 本版可观察结果 | 包含 | 明确不做 | 验收重点 |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | p1-feedback-analysis.md | 当前生产基线，已有 Chat feedback、消息和 Source | 每个持久 feedback 版本产生一个幂等分析任务；显式运行 Worker 后形成带 EvidenceCoverage 的候选案例 | 内部模型调用快照、任务表、结果表、最小案例存储、Worker、反馈接线、迁移、CLI、后端测试 | 案例工作台 UI、标注、审核、导出、RBAC、常驻调度 | 正常、撤回、重复反馈、AI 输出无效、Worker 失败、来源缺失都不越权或伪造结论 |
| P2 | p2-feedback-case-workbench.md | 已验证 P1 | 用户打开反馈工作台，看到问题、回答、文献、已检查 Source、漏读候选、主张支持和 AI 建议 | GET /api/v1/feedback-cases、详情 API、Collection 校验、列表/详情 UI | 标注写入、审核、数据导出、用户手工输入 ID | 不同 Collection 不能读取；UI 不要求用户理解 prompt/ID；空、失败和待处理状态明确 |
| P3 | p3-annotation.md | 已验证 P2 | 用户在案例页面保存一版人工标注，得到可追踪的 digest | PATCH /api/v1/feedback-cases/{case_id}/annotation、Annotation 表/服务/UI、并发摘要校验 | 审核准入、快照、自动批准、RBAC | expected_digest 冲突返回 409；无 target 只能用于 evaluation；标注不改原 Chat |
| P4 | p4-review-decisions.md | 已验证 P3 | 用户针对当前标注追加 accept/reject/insufficient/withdraw 决定 | ReviewDecision 追加表/服务、POST /api/v1/feedback-cases/{case_id}/review、状态投影、UI | 动态 accepted 布尔值、审核角色、自动进入训练 | 旧 digest 失效；撤回优先；历史可重放；没有标注不能审核 |
| P5 | p5-dataset-snapshots.md | 已验证 P4 | 用户按用途冻结快照并下载可复现 JSONL | POST/GET /api/v1/dataset-snapshots、详情和 /jsonl、manifest/provenance/exclusions、三种用途准入 | 在线训练、自动论文消歧、分发平台、动态修改旧快照 | 三种格式准入正确；论文家族/会话树隔离；下载内容与 manifest digest 一致 |
| P6 | p6-offline-evaluation-training.md | 已验证 P5；读取冻结快照 | 用固定快照先基线评测，再训练或偏好实验，再用同一留出集比较 | 离线协议校验、tokenizer 模板、loss mask、训练/评测脚本、权重重载和报告 | 在线学习、自动部署、科学效果承诺、部署配置 | 不泄漏原错误答案；不静默截断 Source；记录 revision/seed/digest；环境缺失写 not_run |

依赖为 P1 -> P2 -> P3 -> P4 -> P5 -> P6。旧的“候选提取”不再单独占用一个版本；自动分析本身已经是 P1，未来若要从普通追问中生成候选，只能作为 P1 之后的可选增强，并必须回到同一 FeedbackCase 校验链。

## 5. 当前选择：P1 反馈分析任务闭环

P1 选择的原因是当前产品已经有用户反馈，但没有任何后台对象把反馈转换成可解释案例。没有这一步，P2 的工作台没有事实来源，后续标注和导出只能是手工拼数据。P1 的用户可观察结果是“反馈经过一次显式分析后出现在待处理案例池”；它不要求用户直接查看内部 prompt。

### P1 步骤 1：重现现有缺口

阅读并运行当前真实链路：

~~~
MessageFeedback.svelte
  -> frontend/src/routes/_shared/chatSessions.ts
  -> backend/controllers/chat/sessions.py
  -> ChatSessionService.set_message_feedback_for_user
  -> ChatRepository.save_feedback
  -> chat_message_feedback
~~~

同时确认 OpenAIChatModel.respond 的最终 SDK 请求、工具结果和 Source 在哪里产生，确认 pipeline_runs 不能替代分析任务。测试先用一个真实 Collection 场景建立失败断言：保存点踩后目前没有 AnalysisJob、没有 AnalysisResult、没有 FeedbackCase。

### P1 步骤 2：在真实 Provider 边界保存内部事实

为分析器提供可追溯事实，不从聊天历史事后拼装请求。

- 修改 backend/application/chat/model.py::ChatModel.respond 和 backend/infra/llm/chat_model.py::OpenAIChatModel.respond，在 SDK 提交前保存完整 JSON 请求（messages、tools、模型参数和 stream 选项）。
- 修改 backend/application/chat/agent_runner.py::ResearchAgentRunner._respond、_prepare_model_context 和 _finalize_with_current_evidence，把每次决策、压缩和收尾调用的 purpose、触发消息和最终 response 关联传入模型记录。
- 修改 backend/application/repositories/chat_repository.py、backend/infra/persistence/postgres/chat_repository.py、backend/infra/persistence/postgres/models/chat.py 和 models/__init__.py，增加内部 ChatModelCall 的开始/完成/读取能力。
- 修改 backend/controllers/chat/sessions.py 和 backend/controllers/schemas/chat/session.py，提供仅用于会话范围内工程诊断的调用列表/详情读取；它们不成为普通用户工作台的导航入口。
- 修改 backend/main.py，把新的 Repository、反馈分析 Service/Worker 和诊断读取依赖接入真实应用装配。
- 新增 Alembic 迁移 backend/migrations/versions/<next_revision>_chat_model_calls.py（NEW，revision/down_revision 在 build 时读取真实 head）。字段与数据库设计一致：call_id、session_id、trigger_message_id、可空 response_message_id、purpose、model、request、request_digest、状态、起止时间、错误码、provider_confirmed 和 token 用量。
- 只保存请求快照和受控错误码，不保存认证头、密钥或环境变量。请求持久化失败时不得调用 Provider；重试使用新 call_id。
- 这一步只服务后台分析和审计。P1 可以提供 API 设计中已有的后台诊断接口 `GET /api/v1/chat-sessions/{session_id}/model-calls` 和详情接口，但不在普通用户工作台增加“查看 prompt”入口；P2 的案例详情以 `EvidenceCoverage` 为主，完整 request 只在已有会话/Collection 访问范围内按需读取，不新增角色。

检查：fake Provider 收到的 JSON 与保存快照相同；后续 mutation 不改变 digest；压缩、普通决策、收尾和工具失败使用独立调用身份；进程/解析失败不伪装成功。

### P1 步骤 3：建立通用任务信封和反馈分析领域对象

新增以下生产文件，正文必须给出完整实现和所有直接调用方：

~~~
backend/domain/feedback/analysis_job.py                         NEW
backend/domain/feedback/evidence_coverage.py                    NEW
backend/domain/feedback/analysis_result.py                      NEW
backend/domain/feedback/feedback_case.py                        NEW
backend/application/repositories/analysis_job_repository.py      NEW
backend/application/repositories/feedback_case_repository.py     NEW
backend/application/feedback/analysis_handler.py                 NEW
backend/application/feedback/analysis_worker.py                  NEW
backend/infra/persistence/postgres/models/feedback.py            NEW
backend/infra/persistence/postgres/analysis_job_repository.py     NEW
backend/infra/persistence/postgres/feedback_case_repository.py    NEW
~~~

其中：

- AnalysisJob 持久化 job_type、payload_version、payload、执行状态、时间、结果 ID、错误码和幂等键；不添加 locked_at、locked_by、attempt_count。
- FeedbackAnalysisHandler 只接受 feedback_analysis 和版本 1 的 {feedback_id} payload，从权威反馈反查会话、回答、调用、工具结果和 Source。
- AnalysisResult 保存 problem_type、confidence、关联消息、模型/输入摘要和 EvidenceCoverage。覆盖对象至少包含 requested_scope、inspected_sources、omitted_candidates、claim_support、gaps、coverage_status。
- `problem_type` 必须使用设计文档冻结的受控枚举（例如 `source_missing`），而不是让模型自由生成标签；完整枚举和界面显示文案在 build 前核对 API 契约。
- FeedbackCase 保存信号、会话/Collection、锚点回答、分析结果引用和处理状态；它引用原 Chat，不复制或改写原始消息。
- AI 结果只是一种候选意见；缺 Source、未读取、无法比较和技术失败必须保持原语义，不能被转换成“已确认错误”。

新增迁移 backend/migrations/versions/<next_revision>_feedback_analysis.py（NEW），建立 analysis_jobs、feedback_analysis_results 和最小 feedback_cases。如果多个迁移更容易按领域拆分，教程必须说明每个 revision 的实际上下游，不能预占编号。

### P1 步骤 4：把现有反馈接到任务创建

直接修改 ChatSessionService.set_message_feedback_for_user 及其构造和测试替身：

1. 保存或更新有效 ChatMessageFeedback 后，创建一个 `feedback_analysis` 任务。
2. 使用持久化返回值中的 `feedback_id + updated_at` 作为反馈版本，组成 `idempotency_key`；完全相同的 PUT 保留原版本并不重复创建，原因/评论/回答摘要发生变化则产生新的版本任务。
3. 任务 payload 只保存 `feedback_id`，不另建不同任务类型的可空 `session_id`、`message_id` 列；Handler 读取当前反馈版本，旧版本任务只能使用设计中的 `cancelled` 状态并记录受控 `feedback_version_superseded` 错误码，具体并发规则在实现前确认。
4. 服务端重新验证 Session 与 Collection 访问范围，客户端不能指定 owner 或操作人。
5. 撤回反馈不产生新的分析结论；P1 采用“待执行任务被 Worker 识别为已撤回并转为 `cancelled`，不写结果和案例”的暂定规则，若实现前设计文档决定采用重新置 `pending`，必须同步修改教程和迁移测试。

任务创建与反馈写入要有明确事务边界：反馈已保存但任务失败时保留受控错误；不能返回“分析已完成”。

### P1 步骤 5：实现显式 Worker，而不是假装已有调度平台

实现：

~~~
FeedbackAnalysisWorker.run_once()
  -> claim_next_feedback_analysis_job()
  -> FeedbackAnalysisHandler.handle(job)
  -> save feedback_analysis_result and FeedbackCase
  -> mark succeeded or failed(error_code)
~~~

新增验证入口：

~~~
backend/scripts/feedback_analysis_worker.py  NEW
~~~

它只运行一次或按显式参数循环，不修改 Docker、compose、workflow 或部署配置。Worker 失败保留稳定错误码；人工重试是新任务或显式回置 pending，不在本版引入自动重试次数、锁字段或外部队列。任务类型边界由 FeedbackAnalysisWorker 和 Repository 的类型明确方法表达，业务调用方不写通用 if job_type 分支。

### P1 步骤 6：P1 测试与完整场景

新增或修改：

~~~
backend/tests/unit/feedback/test_analysis_job.py                     NEW
backend/tests/unit/feedback/test_analysis_worker.py                   NEW
backend/tests/unit/application/test_chat_session_service.py           existing
backend/tests/unit/infra/test_chat_model.py                           existing
backend/tests/integration/persistence/test_feedback_analysis.py       NEW
backend/tests/integration/persistence/test_chat_model_calls.py        NEW
backend/tests/unit/routers/test_chat_sessions_api.py                   existing
backend/tests/support/chat_repository.py                              existing
~~~

至少验证：

- 首次问题 -> 回答 -> 点踩 -> 任务 -> Worker -> AnalysisResult -> FeedbackCase。
- 同一反馈重复保存只产生一个幂等任务；反馈撤回不产生案例。
- AI 返回无效 JSON、超时、Provider 失败、Source 不足分别保留技术/证据语义。
- Worker 不能修改 Chat、写入 Annotation、写入 ReviewDecision 或直接生成数据集。
- 不同用户或 Collection 不能通过反馈 ID 读取别人的事实；消息缺失和历史无调用记录明确失败/不可用。
- 请求快照覆盖裁剪后的真实输入，而不是把后续补读资料放回原回答输入。
- 同一反馈的相同 PUT 不重复建任务；反馈内容版本变化会产生新任务，旧任务不会覆盖新分析。

## 6. P2–P6 的生产落点

下面的路径是计划新增路径，均标记为 NEW；它们不是当前仓库中已经存在的实现。

### P2：FeedbackCase 工作台

目标是让用户从论文和证据完成判断，而不是阅读 prompt 或输入 ID。

~~~
backend/application/feedback/case_service.py                    NEW
backend/controllers/feedback/cases.py                           NEW
backend/controllers/schemas/feedback.py                         NEW
backend/infra/persistence/postgres/feedback_case_repository.py   P1 新增，P2 扩展
frontend/src/routes/_shared/feedbackCases.ts                    NEW
frontend/src/routes/collections/[id]/feedback/+page.svelte      NEW
frontend/src/routes/collections/[id]/feedback/[case_id]/+page.svelte NEW
~~~

实现 GET /api/v1/feedback-cases 和 GET /api/v1/feedback-cases/{case_id}。列表返回摘要；详情返回 question、answer、requested scope、inspected Source、omitted candidates、claim support、gaps、AI analysis、当前 annotation digest。Controller 通过已有 Collection/Session 服务校验范围，不能把 URL 中的 ID 当成授权凭证。

页面按“原问题与回答 -> 要求检查的文献 -> 已检查证据 -> 可能漏读内容 -> AI 建议”展示；用户点击文献和原文完成核对。覆盖 loading、empty、failed、权限 404、无 Source 和案例状态。新增 backend/tests/unit/routers/test_feedback_cases_api.py、backend/tests/integration/persistence/test_feedback_cases.py 与对应 Svelte/Playwright 测试。

### P3：Annotation

~~~
backend/domain/feedback/annotation.py                         NEW
backend/application/feedback/annotation_service.py             NEW
backend/application/repositories/feedback_annotation_repository.py NEW
backend/infra/persistence/postgres/models/feedback.py          P1 新增，P3 扩展
backend/infra/persistence/postgres/feedback_annotation_repository.py NEW
frontend/src/routes/collections/[id]/feedback/[case_id]/AnnotationEditor.svelte NEW
~~~

新增 feedback_annotations 表和迁移，实现 PATCH /api/v1/feedback-cases/{case_id}/annotation。保存 problem_type、severity、可空 target、support source refs、dataset uses、reason 和 digest；expected_digest 由页面自动携带，用户不填写。没有明确 target 的案例可以申请 evaluation，不能申请 sft；没有成对答案不能申请 preference。标注保存不改 Chat 和 AI 原始结果。

测试 409 并发冲突、跨 Collection、空/无效证据、target 与用途不匹配、刷新后仍能读取当前标注。当前所有有 Collection 访问权的登录用户都可以执行此动作，不添加角色表或 allowlist。

### P4：ReviewDecision

~~~
backend/domain/feedback/review_decision.py                    NEW
backend/application/feedback/review_service.py                NEW
backend/application/repositories/feedback_review_repository.py NEW
backend/infra/persistence/postgres/models/feedback.py          P1 新增，P4 扩展
backend/infra/persistence/postgres/feedback_review_repository.py NEW
~~~

新增 feedback_review_decisions 追加表，实现 POST /api/v1/feedback-cases/{case_id}/review。请求包含 expected_annotation_digest、decision、dataset_uses 和 reason。读取案例时从当前 Annotation 与追加历史计算 pending/accept/reject/insufficient/withdrawn/stale，不存一个可被覆盖的 accepted 布尔值。

验证标注变更使旧审核摘要失效；withdraw 不能被历史 accept 覆盖；没有 Annotation 不能审核；每种用途分别判断准入。前端显示论文、证据、标注和用途，用户点击决定按钮，仍不输入 ID 或摘要。测试并发追加、序号唯一、撤回优先、历史重放和失败重试。

### P5：DatasetSnapshot 与导出

~~~
backend/domain/feedback/dataset_snapshot.py                    NEW
backend/application/feedback/dataset_snapshot_service.py        NEW
backend/application/repositories/dataset_snapshot_repository.py NEW
backend/infra/persistence/postgres/models/feedback.py           P1 新增，P5 扩展
backend/infra/persistence/postgres/dataset_snapshot_repository.py NEW
backend/controllers/feedback/datasets.py                        NEW
frontend/src/routes/collections/[id]/feedback/datasets/+page.svelte NEW
~~~

新增 feedback_dataset_snapshots（NEW）及 manifest/provenance/exclusions。实现：

~~~
POST /api/v1/dataset-snapshots
GET  /api/v1/dataset-snapshots
GET  /api/v1/dataset-snapshots/{dataset_id}
GET  /api/v1/dataset-snapshots/{dataset_id}/jsonl
~~~

教程先用 evaluation 完成一个可复现快照，再在同一版本中加入 sft 和 preference 的类型转换与准入规则。每个快照只允许一种 dataset_type；同一案例可以分别进入不同类型的快照。服务端检查当前 annotation digest、审核用途、输入涉及的全部论文家族、会话树、train/eval 分区和数据授权；不合格项进入 exclusions。下载内容必须是冻结 manifest 的逐行转换，不重新判断事实、不补写 target、不静默截断 Source。

测试同一 manifest digest 可重建、撤回后新快照排除、旧快照保持不变、论文家族/会话树泄漏拒绝、空快照和下载 application/x-ndjson。页面提供筛选、类型选择、split、排除原因和下载状态；不提供“对所有案例一键批准”捷径。

### P6：离线评测与训练

P6 不新增在线 API，也不修改部署路径。建议新增：

~~~
backend/scripts/evaluation/feedback_dataset/README.md             NEW
backend/scripts/evaluation/feedback_dataset/validate_snapshot.py  NEW
backend/scripts/evaluation/feedback_dataset/run_evaluation.py     NEW
backend/scripts/evaluation/feedback_dataset/run_sft.py            NEW
backend/scripts/evaluation/feedback_dataset/run_preference.py     NEW
~~~

脚本先校验 dataset_id、dataset_type、manifest/provenance digest、split、Source 和模型/tokenizer revision；再执行基线评测、训练/偏好实验、同一留出集评测、权重保存与重载。输入 prompt 和最终 target 边界必须明确，原错误答案只能作为上下文，不能成为监督目标；超长已审核材料拒绝并记录原因，不静默截断。报告记录 seed、环境、模型 revision、数据摘要、结果和来源回查；环境/授权缺失写 not_run，不把“导出成功”说成“模型改进”。

## 7. 迁移范围

旧 nano 文件已从活动工作区移出；本次迁移不改生产代码，build 阶段只在 Lens 生产仓库按 P1–P6 实现和验证。

| 当前内容 | 后续处理 |
| --- | --- |
| 旧 `TUTORIAL.md` | 迁移为 `tutorial/p1-feedback-analysis.md` |
| 旧 `docs/p2-correction-cases.md` | 不保留旧 ChatCorrectionCase 方案，改为 `p2-feedback-case-workbench.md` |
| 旧 `docs/p3-sample-review.md` | 改为 `p3-annotation.md` |
| 旧 `docs/p4-datasets.md` | 改为 `p4-review-decisions.md` |
| 旧 `docs/p5-candidates.md` | 改为 `p5-dataset-snapshots.md` |
| 旧 `docs/p6-training-evaluation.md` | 改为 `p6-offline-evaluation-training.md` |
| docs/v0-*、旧 replay/revision 文档和 nano 源码 | build 阶段删除；保留 Git 历史，不复制 archive |
| README.md、docs/verification.md、docs/version-history.md | 更新为六版新入口和真实验证状态 |

旧文件名中的 correction case、candidate 不能继续作为新模型的权威命名。P2–P5 的新文件名与 API/核心模型一致；若 build 发现已有外部链接，先更新链接再删除旧文件。

## 8. 验证、冻结与交接

### 本计划阶段的检查

计划文件写入后执行：

~~~
python3 - <<'PY'
import yaml
from pathlib import Path

path = Path('.agent-runs/tutorial-plan/lens-production-feedback/planning.yaml')
data = yaml.safe_load(path.read_text())
ids = [item['id'] for item in data['versions']]
assert len(ids) == len(set(ids))
assert data['selected_version'] in ids
known = set(ids)
for item in data['versions']:
    assert set(item.get('depends_on', [])) <= known
print('planning record valid')
PY
git check-ignore -v .agent-runs/tutorial-plan/lens-production-feedback/planning.yaml
git diff --check
~~~

同时检查本文件中的本地链接和文档治理；生产功能测试、迁移、浏览器联调在 build 阶段才运行，当前不能声称已通过。

### P1 冻结条件

P1 只有在以下条件同时满足时才可交给下一版：

- 反馈写入、幂等任务、显式 Worker、分析结果和最小案例贯通真实生产装配。
- 请求快照、Provider 状态和证据覆盖语义经过单元与专用 PostgreSQL 集成测试。
- 正常、撤回、重复、AI 失败、Provider 失败、Source 不足和越权场景都可重放。
- 旧 Chat、Finding、pipeline_runs 和现有 feedback 语义未被改写。
- 教程可从统一迁移仓库记录的 Lens 基线加上保留的未提交文件开始重放；不依赖 nano 源码或历史 chat_correction_* 表。

每个版本的 commit_when 同时是该版本的独立 checkpoint 条件：通过本版验收后只暂存本版实现、测试、契约文档和教程，创建一个可回退的 P1、P2、P3、P4、P5 或 P6 提交。教程正文完成与生产实现合入仍分别记录；本轮计划阶段不提交任何 Git 变更。

## 9. 交接说明

当前选中的版本是 P1。下一步 project-implementation-tutorial-build 应先重新读取生产基线和本计划，再从 `p1-feedback-analysis.md` 开始逐版重放；完成 P1 的验证后依次验证 P2–P6。未决事项集中记录在 `.agent-runs/tutorial-plan/lens-production-feedback/planning.yaml`，尤其是反馈撤回时待处理任务的最终状态、分析模型的 Provider/提示协议、模型调用审计是否需要内部读取端点，以及快照中训练授权的实际来源。它们不能被旧教程的假设掩盖。
