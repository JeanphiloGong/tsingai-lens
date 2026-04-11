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
- 启动索引任务：`POST /api/v1/collections/{collection_id}/tasks/index`
- 查询任务与产物：`GET /api/v1/collections/{collection_id}/tasks`、`GET /api/v1/tasks/{task_id}`、`GET /api/v1/tasks/{task_id}/artifacts`
- 图谱与 GraphML：`GET /api/v1/collections/{collection_id}/graph`、`GET /api/v1/collections/{collection_id}/graphml`
- Protocol 结果：`GET /api/v1/collections/{collection_id}/protocol/steps`、`GET /api/v1/collections/{collection_id}/protocol/search`、`POST /api/v1/collections/{collection_id}/protocol/sop`
- 报告结果：`GET /api/v1/collections/{collection_id}/reports/communities`、`GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`、`GET /api/v1/collections/{collection_id}/reports/patterns`

## 前端实现约束
- 不再允许浏览器手工设置 Base URL
- 遗留调试入口已从浏览器产品流程中退役
- `frontend/nginx.conf` 只代理 `/api/` 到 `backend:8010`
- 遗留调试页 `/upload`、`/index`、`/configs`、`/export` 已退役为说明页，不再发旧浏览器请求

## 验收重点
- Network 面板中的产品请求只出现 `/api/v1/*` 与 `/api/*`
- 首页、集合工作区、文件上传、任务轮询、图谱、步骤、SOP、报告都通过同源入口工作
- 浏览器中的 API 文档入口固定为 `/api/docs`
