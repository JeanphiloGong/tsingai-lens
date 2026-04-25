# 前端同源 API 说明

本文档描述当前前端的浏览器公开合同，目标是让产品流程始终通过同源入口访问后端。

如果要看下一阶段 collection UI 的页面结构、路由迁移和 fixture 策略，请同时参考
[`../src/routes/collections/lens-v1-interface-spec.md`](../src/routes/collections/lens-v1-interface-spec.md)。

## 当前合同

- 浏览器公开业务 API 统一走 `/api/v1/*`
- 文档与 OpenAPI 入口统一走 `/api/*`
- API 文档地址：`/api/docs`
- 前端共享请求封装统一从 `frontend/src/routes/_shared/api.ts` 发起请求

## 产品主流程

- 首页集合列表：`GET /api/v1/collections`
- 创建集合：`POST /api/v1/collections`
- 集合详情：`GET /api/v1/collections/{collection_id}`
- 集合文件：`GET|POST /api/v1/collections/{collection_id}/files`
- 工作区概览：`GET /api/v1/collections/{collection_id}/workspace`
- 启动构建任务：`POST /api/v1/collections/{collection_id}/tasks/build`
- 查询任务与产物：`GET /api/v1/collections/{collection_id}/tasks`、`GET /api/v1/tasks/{task_id}`、`GET /api/v1/tasks/{task_id}/artifacts`
- 结果与文档证据链：`GET /api/v1/collections/{collection_id}/results/{result_id}`、`GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics?include_grouped_projections=true`
- 图谱与 GraphML：`GET /api/v1/collections/{collection_id}/graph`、`GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`、`GET /api/v1/collections/{collection_id}/graphml`
- 图谱 drilldown 详情：`GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`、`GET /api/v1/collections/{collection_id}/evidence/{evidence_id}`、`GET /api/v1/collections/{collection_id}/comparisons/{row_id}`
- 图谱聚合节点 drilldown：回到 `GET /api/v1/collections/{collection_id}/comparisons`，并使用 `material_system_normalized`、`property_normalized`、`test_condition_normalized`、`baseline_normalized` 过滤参数
- Protocol 结果：`GET /api/v1/collections/{collection_id}/protocol/steps`、`GET /api/v1/collections/{collection_id}/protocol/search`、`POST /api/v1/collections/{collection_id}/protocol/sop`
- 报告结果：`GET /api/v1/collections/{collection_id}/reports/communities`、`GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`、`GET /api/v1/collections/{collection_id}/reports/patterns`

## 前端实现约束

- 不再允许浏览器手工设置 Base URL
- 遗留调试入口已从浏览器产品流程中退役
- `frontend/nginx.conf` 只代理 `/api/` 到 `backend:8010`
- collection workspace 与首页统一把任务启动视为 `build`，不再向浏览器公开旧的 `/tasks/index` 合同
- 前端主合同不再依赖 `sections_ready` 或 `graphml_ready`；GraphML 导出能力统一看 `capabilities.can_download_graphml`
- 集合图谱页使用 `Cytoscape.js` 在浏览器端本地布局；邻域扩展保留已有节点位置并只对新增节点做增量重排，不依赖服务端坐标
- 图谱页的语义聚合节点目前是 `material / property / test_condition / baseline`；默认显示 `material / property`，并通过前端类型开关显式控制其余节点可见性
- 遗留调试页 `/upload`、`/index`、`/configs`、`/export` 已退役为说明页，不再发旧浏览器请求

## 验收重点

- Network 面板中的产品请求只出现 `/api/v1/*` 与 `/api/*`
- 首页、集合工作区、文件上传、任务轮询、图谱、步骤、SOP、报告都通过同源入口工作
- 浏览器中的 API 文档入口固定为 `/api/docs`
