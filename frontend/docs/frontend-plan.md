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
- 研究目标工作区：`GET /api/v1/collections/{collection_id}/objectives`、`GET /api/v1/collections/{collection_id}/objectives/{objective_id}/research-view`
- 启动构建任务：`POST /api/v1/collections/{collection_id}/tasks/build`
- 查询任务与产物：`GET /api/v1/collections/{collection_id}/tasks`、`GET /api/v1/tasks/{task_id}`、`GET /api/v1/tasks/{task_id}/artifacts`
- 结果与文档证据链：`GET /api/v1/collections/{collection_id}/results/{result_id}`、`GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics?include_grouped_projections=true`
- 图谱与 GraphML：`GET /api/v1/collections/{collection_id}/graph`、`GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`、`GET /api/v1/collections/{collection_id}/graphml`
- 图谱 drilldown 详情：`GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`、`GET /api/v1/collections/{collection_id}/evidence/{evidence_id}`、`GET /api/v1/collections/{collection_id}/comparisons/{row_id}`
- 图谱聚合节点 drilldown：回到 `GET /api/v1/collections/{collection_id}/comparisons`，并使用 `material_system_normalized`、`property_normalized`、`test_condition_normalized`、`baseline_normalized` 过滤参数
- Collection-bound AI 研究助手：`POST /api/v1/goal-sessions`、
  `GET|PATCH /api/v1/goal-sessions/{session_id}`、
  `POST|GET /api/v1/goal-sessions/{session_id}/messages`

## 前端实现约束

- 不再允许浏览器手工设置 Base URL
- 遗留调试入口已从浏览器产品流程中退役
- `frontend/nginx.conf` 只代理 `/api/` 到 `backend:8010`
- collection workspace 与首页统一把任务启动视为 `build`，不再向浏览器公开旧的 `/tasks/index` 合同
- 前端主合同不再依赖 `sections_ready` 或 `graphml_ready`；GraphML 导出能力统一看 `capabilities.can_download_graphml`
- 集合图谱页使用 `Cytoscape.js` 在浏览器端本地布局；邻域扩展保留已有节点位置并只对新增节点做增量重排，不依赖服务端坐标
- 集合图谱页默认使用前端 overview 投影：画布收起 `comparison / evidence`
  细节点，展示 `document`、`material`、`property`、`process`、`variant`、
  `test_condition`、`baseline`、`unknown` 结构节点，并用聚合边表达文献、材料、性能和上下文之间的 collection-level 导航关系
- 单个材料的细粒度样品、工艺变量、性能、发现和证据关系由
  `/collections/{collection_id}/materials/{material_id}` 材料档案内的 material-scoped graph 承载；集合图谱只提供进入材料档案的导航入口
- `/collections/{collection_id}/objectives` 和
  `/collections/{collection_id}/objectives/{objective_id}` 是 objective-first
  工作区入口；它读取 objective list 与 objective research-view，不复用
  material endpoint 返回目标数据
- `/collections/{collection_id}/assistant` 使用同源 `goal-sessions` API，是绑定当前
  collection 的研究助手入口；它必须显示 `collection_grounded`、
  `collection_limited`、`general_fallback`、`general_only` 来源边界，并把材料详情页传入的
  `material_id` 作为显式 focus context
- 报告结果不再是当前浏览器主流程；frontend 不再维护 reports API 客户端或工作区占位入口
- 遗留调试页 `/upload`、`/index`、`/configs`、`/export` 已从前端路由中移除；
  产品入口统一收敛到 collection workspace 和 `/api/docs`

## 验收重点

- Network 面板中的产品请求只出现 `/api/v1/*` 与 `/api/*`
- 首页、集合工作区、文件上传、任务轮询、图谱、证据和比较都通过同源入口工作
- 浏览器中的 API 文档入口固定为 `/api/docs`
