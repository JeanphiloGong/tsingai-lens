# API 接口文档

默认 Base URL：`http://localhost:8010`。当前接口未启用鉴权。

## 公开合同

- 业务接口统一位于：`/api/v1/*`
- 文档与静态资源统一位于：`/api/*`
- 旧公开入口 `/collections/*`、`/tasks/*`、`/retrieval/*`、`/docs`、`/redoc`、`/openapi.json`、`/static/*` 不再暴露

### 文档与静态资源

- `GET /api/docs`
- `GET /api/redoc`
- `GET /api/openapi.json`
- `GET /api/static/*`

### App Layer

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/files`
- `POST /api/v1/collections/{collection_id}/tasks/index`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/collections/{collection_id}/workspace`
- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graphml`
- `GET /api/v1/collections/{collection_id}/protocol/steps`
- `GET /api/v1/collections/{collection_id}/protocol/search`
- `POST /api/v1/collections/{collection_id}/protocol/sop`

### Query 与 Reports

- `POST /api/v1/query`
- `GET /api/v1/collections/{collection_id}/reports/communities`
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
- `GET /api/v1/collections/{collection_id}/reports/patterns`

## 推荐前端主流程

1. `POST /api/v1/collections`
2. `POST /api/v1/collections/{collection_id}/files`
3. `POST /api/v1/collections/{collection_id}/tasks/index`
4. 轮询 `GET /api/v1/tasks/{task_id}`
5. 使用 `GET /api/v1/collections/{collection_id}/workspace` 驱动状态展示
6. 按页面调用 graph / protocol / sop 相关 collection 维度接口

## 迁移提示

- 浏览器与前端代码只能假设 `/api/v1/*` 与 `/api/*` 两类前缀。
- 旧 `/retrieval/*` 不属于主应用公开浏览器接口，不应作为前端集成入口。
- protocol 公共入口只保留 collection 维度 `/api/v1/collections/{collection_id}/protocol/*`。
