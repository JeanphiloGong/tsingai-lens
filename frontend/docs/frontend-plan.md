# 前端同源 API 说明

本文档描述当前前端的浏览器公开合同，目标是让产品流程始终通过同源入口访问后端。

如果要看下一阶段 collection UI 的页面结构、路由迁移和 fixture 策略，请同时参考
[`../src/routes/collections/lens-v1-interface-spec.md`](../src/routes/collections/lens-v1-interface-spec.md)。

## 当前合同

- 浏览器公开业务 API 统一走 `/api/v1/*`
- 文档与 OpenAPI 入口统一走 `/api/*`
- API 文档地址：`/api/docs`
- 前端共享请求封装统一从 `frontend/src/routes/_shared/api.ts` 发起请求，并用
  same-origin cookie 传递登录会话

## 产品主流程

- 首页集合列表：`GET /api/v1/collections`
- 登录会话：`POST /api/v1/auth/login`、`GET /api/v1/auth/me`、`POST /api/v1/auth/logout`
- 创建集合：`POST /api/v1/collections`
- 集合详情：`GET /api/v1/collections/{collection_id}`
- 集合文档：`GET|POST /api/v1/collections/{collection_id}/documents`
- 单篇文档准备：`POST /api/v1/collections/{collection_id}/documents/{document_id}/preparation`
- 从明确选择的已就绪文档形成研究问题：`POST /api/v1/collections/{collection_id}/objective-discovery`
- 研究目标工作区：`GET /api/v1/collections/{collection_id}/objectives`、
  `GET|POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence-map`、
  `GET|POST /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`、
  `PATCH /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}`

  其中 Objective discovery 和 `POST .../analysis` 都必须发送明确的
  `document_ids`。`POST .../analysis` 是唯一的确认并分析命令：候选 Objective
  会在同一事务中固化为 `confirmed`，并冻结所选文档的
  `document_id + preparation_fingerprint` 后进入排队状态；已确认 Objective
  则直接创建或复用分析版本。Objective discovery 立即返回持久化的
  `objective_discovery` Task；集合页通过 Task 接口恢复和轮询状态，不能用页面本地
  loading 作为运行事实。分析命令返回后，Objective 列表在当前行展示并轮询进度，
  不自动跳转到详情页。

- 查询文档准备任务：`GET /api/v1/collections/{collection_id}/tasks`、`GET /api/v1/tasks/{task_id}`
- 文档与 Source 核验：`GET /api/v1/collections/{collection_id}/documents/profiles`、
  `GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`、
  `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`、
  `GET /api/v1/collections/{collection_id}/documents/{document_id}/markdown`
- Collection-bound Research Agent：`POST /api/v1/chat-sessions`、
  `GET /api/v1/chat-sessions/{session_id}`、
  `GET|POST /api/v1/chat-sessions/{session_id}/messages`、
  `POST /api/v1/chat-sessions/{session_id}/tool-calls/{tool_call_id}/decision`

## 前端实现约束

- 不再允许浏览器手工设置 Base URL
- 遗留调试入口已从浏览器产品流程中退役
- `frontend/nginx.conf` 只代理 `/api/` 到 `backend:8010`
- Collection 只组织当前文档；Source、DocumentProfile、Paper Map 和就绪状态
  都属于单篇 Document。上传新文档或重试失败文档不会重新处理其他文档
- 同一 Document 同时最多一个准备任务，不同 Document 可以并发准备；上传在准备期间保持可用
- Objective discovery 和 analysis 只使用用户明确勾选的已就绪文档；处理中或失败文档
  不会阻塞已就绪子集的研究工作
- `/collections/{collection_id}/objectives` 和
  `/collections/{collection_id}/objectives/{objective_id}` 是 objective-first
  工作区入口；确认、分析、Findings 复核、数据集、Assistant focus 和实验方案都使用同一个
  `objective_id`，不维护第二套持久化目标身份
- `/collections/{collection_id}/assistant` 使用同源 `chat-sessions` API，是绑定当前
  collection 的 Research Agent 入口。普通对话不要求 capability；读取和草拟 capability
  自动执行并将结构化结果与最终回答分开显示；消息 POST 通过同一 URL 的
  `Accept: text/event-stream` 内容协商增量显示模型文本，并以服务端持久化后的完整 turn
  收尾；Core 写入停在持久化的精确参数审批点。
  Chat 是会话、消息、capability 轨迹和审批的唯一运行时权威，但不拥有 Objective、
  Evidence、Finding 或 Analysis 真值。Objective 链接仅指向 Core 的规范记录。
- `/collections/{collection_id}/comparisons` 只读取已发布 Objective analysis
  的 Findings；它不读取或重建旧 comparison row、Evidence Card、Materials
  或 Graph 投影
- `/collections/{collection_id}/graph` 是次级的 Objective Evidence Map：用户先选择
  一个已有已发布 analysis 的 Objective，再按 `Objective -> Finding -> Evidence ->
Source -> Document` 回溯关系。页面只调用 Objective 的 `evidence-map` 接口；失败
  或排除论文只表示覆盖情况，不表示反对证据
- `/collections/{collection_id}/documents/{document_id}` 只展示解析后的 Source
  内容，并通过 `source_ref` 与页码完成精确核验
- 报告结果不再是当前浏览器主流程；frontend 不再维护 reports API 客户端或工作区占位入口
- 遗留 collection-wide Graph API/模型、Materials、Results、Evidence Cards、
  `research-view` 以及调试页
  `/upload`、`/index`、`/configs`、`/export` 已从前端路由中移除；
  新 Evidence Map 不兼容或恢复这些旧合同；产品入口统一收敛到 collection
  collection route family 和 `/api/docs`

## 验收重点

- Network 面板中的产品请求只出现 `/api/v1/*` 与 `/api/*`
- 首页、集合文档、文件上传、单篇任务轮询、明确文档选择、Objective、Published Findings、
  ObjectiveEvidence 与 Source 核验都通过同源入口工作
- 浏览器中的 API 文档入口固定为 `/api/docs`
