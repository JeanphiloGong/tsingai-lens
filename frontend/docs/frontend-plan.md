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
- 集合文件：`GET|POST /api/v1/collections/{collection_id}/files`
- 工作区概览：`GET /api/v1/collections/{collection_id}/workspace`
- 研究目标工作区：`GET /api/v1/collections/{collection_id}/objectives`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}`、
  `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/confirm`、
  `GET|POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/findings/{finding_id}`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence`、
  `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/evidence-map`、
  `GET|POST /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`、
  `PATCH /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}`
- 启动构建任务：`POST /api/v1/collections/{collection_id}/tasks/build`
- 查询任务与产物：`GET /api/v1/collections/{collection_id}/tasks`、`GET /api/v1/tasks/{task_id}`、`GET /api/v1/tasks/{task_id}/artifacts`
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
- collection workspace 与首页统一把任务启动视为 `build`，不再向浏览器公开旧的 `/tasks/index` 合同
- task artifact registry 只报告 Source 构建产物；文档画像和 Objective
  readiness 由 workspace 从各自领域仓储读取
- `/collections/{collection_id}/objectives` 和
  `/collections/{collection_id}/objectives/{objective_id}` 是 objective-first
  工作区入口；确认、分析、Findings 复核、数据集、Assistant focus 和实验方案都使用同一个
  `objective_id`，不维护第二套持久化目标身份
- `/collections/{collection_id}/assistant` 使用同源 `chat-sessions` API，是绑定当前
  collection 的 Research Agent 入口。普通对话不要求 capability；读取和草拟 capability
  自动执行并将结构化结果与最终回答分开显示；Core 写入停在持久化的精确参数审批点。
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
  workspace 和 `/api/docs`

## 验收重点

- Network 面板中的产品请求只出现 `/api/v1/*` 与 `/api/*`
- 首页、集合工作区、文件上传、任务轮询、Objective、Published Findings、
  ObjectiveEvidence 与 Source 核验都通过同源入口工作
- 浏览器中的 API 文档入口固定为 `/api/docs`
