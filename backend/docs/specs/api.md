# API 接口文档

这是当前 Lens v1 的前后端主合同。

前端应按这里的资源模型和接口组织设计界面。某些接口如果尚未落地，实现责任在后端，不影响这里作为约定合同的地位。

默认 Base URL：`http://localhost:8010`。当前接口未启用鉴权。

## 总体约定

- 业务接口统一位于：`/api/v1/*`
- 文档与静态资源统一位于：`/api/*`
- collection 是主业务单位，不是单篇 paper
- `workspace` 是 Lens v1 的主入口界面
- `documents/profiles`、`evidence/cards`、`comparisons` 是主业务资源
- `protocol/*` 是条件分支，不是所有 collection 的默认主产物

## 文档与静态资源

- `GET /api/docs`
- `GET /api/redoc`
- `GET /api/openapi.json`
- `GET /api/static/*`

## 推荐前端主流程

1. `POST /api/v1/collections`
2. `POST /api/v1/collections/{collection_id}/files`
3. `POST /api/v1/collections/{collection_id}/tasks/index`
4. 轮询 `GET /api/v1/tasks/{task_id}`
5. 打开 `GET /api/v1/collections/{collection_id}/workspace`
6. 从 workspace 跳转到 document profiles、evidence cards、comparison rows
7. 只有 collection 适合 protocol 分支时，才进入 protocol steps/search/sop

## 资源与接口

### Collection 与任务入口

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

约束：

- `GET /api/v1/tasks/{task_id}` 只接收真正的 `task_id`
- `collection_id` 不能拿来调用 task 详情接口
- collection 页面如果要展示任务历史，应走 collection 维度的 tasks 接口

### Workspace

- `GET /api/v1/collections/{collection_id}/workspace`

这是前端新界面的主入口接口。

它至少应表达这些业务信息：

- `collection`
- `file_count`
- `status_summary`
- `workflow`
- `document_summary`
- `warnings`
- `latest_task`
- `recent_tasks`
- `capabilities`
- `links`

其中：

- `workflow` 应表达 `documents`、`evidence`、`comparisons`、`protocol`
  四个阶段的状态
- 状态值应使用显式语义，例如
  `not_started | processing | ready | limited | not_applicable | failed`
- `document_summary` 应来自 `document_profiles` 的 collection 级汇总
- `warnings` 应表达 review-heavy、protocol-limited、comparison-limited、
  traceability-limited 等 collection 风险
- `links` 应指向主资源页面，而不是让前端自己拼内部跳转语义
- `artifacts` 对每类产物应同时提供
  `*_generated` 与 `*_ready` 两类布尔值：
  - `generated` 表示该阶段产物文件已生成（可能为空）
  - `ready` 表示该阶段产物可直接用于主界面消费（通常要求非空）

### Document Profiles

- `GET /api/v1/collections/{collection_id}/documents/profiles`

这是 Lens v1 主链路的第一层业务资源。

最小返回结构：

- `collection_id`
- `total`
- `count`
- `summary`
- `items`

每个 item 至少应包含：

- `document_id`
- `collection_id`
- `title`
- `source_filename`
- `doc_type`
- `protocol_extractable`
- `protocol_extractability_signals`
- `parsing_warnings`
- `confidence`

语义要求：

- `document_id` 是内部稳定标识，用于追踪和关联，不是主展示名称
- `title` 是文档/论文标题
  - 如果无法可靠获得，返回 `null`
  - 不要用 `document_id` 回填
  - 不要用 `source_filename` 冒充
- `source_filename` 是用户上传的原始文件名，或系统能稳定追溯到的源文件名
  - 如果当前链路拿不到，返回 `null`
  - 不要用 `title` 或 `document_id` 冒充
- 空字符串不应返回给前端，应统一归一化为 `null`
- `doc_type` 使用
  `experimental | review | mixed | uncertain`
- `protocol_extractable` 使用
  `yes | partial | no | uncertain`
- 这是增量字段扩展，不改变 endpoint，也不破坏旧字段

前端消费约定：

- 主标题优先级：`title ?? source_filename ?? short(document_id)`
- 副标题优先级：`source_filename ?? document_id`
- 后端不需要额外生成 `display_name`，只需要保证字段语义真实

示例 item：

```json
{
  "document_id": "c48b...",
  "collection_id": "col_xxx",
  "title": "High-Rate Performance of Layered Oxide Cathodes",
  "source_filename": "wang_2024_battery.pdf",
  "doc_type": "experimental",
  "protocol_extractable": "yes",
  "protocol_extractability_signals": ["methods_section_detected"],
  "parsing_warnings": [],
  "confidence": 0.91
}
```

### Evidence Cards

- `GET /api/v1/collections/{collection_id}/evidence/cards`

这是 Lens v1 主链路的 claim-centered 证据资源。

最小返回结构：

- `collection_id`
- `total`
- `count`
- `items`

每个 item 至少应包含：

- `evidence_id`
- `document_id`
- `collection_id`
- `claim_text`
- `claim_type`
- `evidence_source_type`
- `evidence_anchors`
- `material_system`
- `condition_context`
- `confidence`
- `traceability_status`

语义要求：

- 一张 evidence card 只有一个 primary claim
- 可以有一个或多个 evidence anchors
- `condition_context` 不能退化成不可解释的黑盒，至少应保留
  process、baseline、test 三类上下文

### Comparisons

- `GET /api/v1/collections/{collection_id}/comparisons`

这是 Lens v1 的主 collection-facing 比较资源。

最小返回结构：

- `collection_id`
- `total`
- `count`
- `items`

每个 item 至少应包含：

- `row_id`
- `collection_id`
- `source_document_id`
- `supporting_evidence_ids`
- `material_system_normalized`
- `process_normalized`
- `property_normalized`
- `baseline_normalized`
- `test_condition_normalized`
- `comparability_status`
- `comparability_warnings`

语义要求：

- 一行表示一个可供 collection 级检查的 normalized result，不是 pairwise 对比对象
- `comparability_status` 使用
  `comparable | limited | not_comparable | insufficient`
- 前端应把 comparison rows 作为主比较表，而不是把 protocol steps 当主表

### Protocol 条件分支

- `GET /api/v1/collections/{collection_id}/protocol/steps`
- `GET /api/v1/collections/{collection_id}/protocol/search`
- `POST /api/v1/collections/{collection_id}/protocol/sop`

这些接口仍然保留，但前端不能假设每个 collection 都有高质量 protocol 输出。

前端约束：

- protocol 入口必须保持 collection 维度
- 如果 workspace 或 document profiles 已经表明 collection 不适合 protocol，
  前端应降级展示，而不是强推 protocol 页面

### Graph、Reports、Query 次级界面

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graphml`
- `GET /api/v1/collections/{collection_id}/reports/communities`
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
- `GET /api/v1/collections/{collection_id}/reports/patterns`
- `POST /api/v1/query`

这些接口可以保留，但不是 Lens v1 新界面的主验收面。

## 错误合同

- `400` 请求参数错误
- `404` collection 或 task 不存在
- `409` 资源存在但当前阶段尚未就绪
- `500` 后端内部错误

readiness 类错误至少应包含：

- 稳定的 `code`
- 可读的 `message`
- 对应的 `collection_id` 或 `task_id`
- 当前被阻塞的 workflow stage 或相关资源信息

核心资源的阶段语义约定：

- `documents/profiles`、`evidence/cards`、`comparisons`
  - 对应 `*_generated=false`：返回 `409`
  - 对应 `*_generated=true` 且结果为空：返回 `200`，`count=0`
  - 对应 `*_ready=true`：返回 `200`，可直接用于主界面
- `protocol/*`
  - 入口基于 `protocol_steps_generated` 判断是否可访问
  - `protocol_steps_generated=true` 且 `protocol_steps_ready=false` 时允许返回空列表或空结果

## 前端集成约束

- 浏览器与前端代码只应依赖 `/api/v1/*` 与 `/api/*` 两类前缀
- collection 详情页的主状态来源是 `workspace`
- 前端不应把 `sections_ready`、`procedure_blocks_ready` 这类内部产物状态当成长期主合同
- protocol 页面不是默认首页，comparison workspace 才是

## 相关文档

- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`../plans/evidence-first-parsing-plan.md`](../plans/evidence-first-parsing-plan.md)
- [`../../../docs/40-specs/lens-v1-definition.md`](../../../docs/40-specs/lens-v1-definition.md)
- [`../../../docs/40-specs/lens-core-artifact-contracts.md`](../../../docs/40-specs/lens-core-artifact-contracts.md)
