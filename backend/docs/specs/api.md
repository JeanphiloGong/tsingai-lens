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
- `graph/*`、`reports/*` 当前是消费 Core artifact 的派生视图，不再定义独立研究事实模型
- 当前没有单独公开的 `query/search` 产品接口
- `goals/*` 当前只表示 Goal Brief / Intake，不是完整 Goal Consumer / Decision Layer
- 所有业务响应都会回传 `X-Request-ID`
  - 客户端可主动传入 `X-Request-ID` 参与链路关联
  - 如果未传入或值非法，后端会生成新的 request id 并回写到响应头

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
8. 在 comparison/evidence 中点击“查看原文证据”时，调用 traceback 接口并跳转文档查看器

可选 goal-first 流程（当前只覆盖 Goal Brief / Intake）：

1. `POST /api/v1/goals/intake`
2. 从响应读取 `seed_collection.collection_id`
3. 打开 `GET /api/v1/collections/{collection_id}/workspace`
4. 后续统一进入 `documents/profiles`、`evidence/cards`、`comparisons`

## 资源与接口

### Goal Brief / Intake（当前公开入口）

- `POST /api/v1/goals/intake`

最小请求结构：

- `material_system`
- `target_property`
- `intent`
- `constraints`
- `context`
- `max_seed_documents`

最小返回结构：

- `research_brief`
- `coverage_assessment`
- `seed_collection`
- `entry_recommendation`

其中 `seed_collection` 当前至少包含：

- `collection_id`
- `name`
- `created`
- `seeded_document_count`
- `source_channels`
- `handoff_id`
- `handoff_status`

语义约束：

- `goals/intake` 是问题定义与 collection handoff 入口，不是研究结论层
- `seed_collection` 是 collection-builder handoff，不是 Core artifact
- `seed_collection.handoff_id` 应稳定指向 collection-builder handoff 记录
- `seed_collection.handoff_status` 当前表示该 collection 正等待 source material 接入
- 当前返回里的 `coverage_assessment` 只是 intake-side 的粗粒度提示，用于帮助 collection
  build，不应被当成 Goal Consumer 的最终 coverage 判断
- 返回中不得直接内嵌 `document_profiles`、`evidence_cards`、`comparison_rows`
- 返回必须提供 `seed_collection.collection_id`，并收敛到统一 collection 路由

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
- `current_stage` 对外应使用：
  `queued | files_registered | source_index_started | source_index_completed | document_profiles_started | evidence_cards_started | comparison_rows_started | protocol_artifacts_started | artifacts_ready | failed`
- `graphrag_index_started`、`graphrag_index_completed`
  已退役，不再属于公开或内部活动合同

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
- `graph_generated`
  表示 `document_profiles.parquet`、`evidence_cards.parquet`、
  `comparison_rows.parquet` 三个 Core graph 输入文件都已生成
- `graph_ready`
  表示上述 Core graph 输入已具备图投影消费条件，而不是
  `entities.parquet` / `relationships.parquet` 是否存在
- `artifacts` 不再暴露 `graphml_generated` / `graphml_ready`
  因为 GraphML 已改为基于 Core graph 的按需导出能力，不再是索引阶段的 readiness 产物
- `capabilities.can_download_graphml`
  应与 `graph_ready` 保持一致，表达当前 collection 是否可以导出按需生成的 GraphML

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
- `protocol_extractability_signals` 当前为预留字段，返回空数组
- `parsing_warnings` 仅用于固定 triage warning，例如
  `insufficient_content | classification_uncertain`
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
  "protocol_extractability_signals": [],
  "parsing_warnings": [],
  "confidence": 0.91
}
```

单项 drilldown 路径：

- `GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`

其中 `/profile` 返回与 list item 同语义的单项 document profile，`/content`
返回原文阅读器内容与 section 结构。

### Evidence Cards

- `GET /api/v1/collections/{collection_id}/evidence/cards`
- `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}`

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

### Claim Traceback 与 PDF 定位合同

这是 comparison/evidence 到原文证据回溯的统一合同。

前端主展示仍是结构化结果（comparison rows、evidence cards），PDF 是证据回溯层，不是默认首页主视图。

当前这一波后端落地顺序与边界，记录在
[`../plans/claim-traceback-navigation-implementation-plan.md`](../plans/core/claim-traceback-navigation-implementation-plan.md)。

推荐入口接口：

- `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`

最小返回结构（traceback）：

- `collection_id`
- `evidence_id`
- `traceback_status`
  - `ready | partial | unavailable`
- `anchors`

每个 anchor 至少应包含：

- `anchor_id`
- `document_id`
- `locator_type`
  - `char_range | bbox | section`
- `locator_confidence`
  - `high | medium | low`
- `page`
- `quote`
- `section_id`
- `char_range`
- `bbox`
- `deep_link`

语义要求：

- `locator_type=char_range`
  - 适用于可提取文本层的 PDF，按页面内字符范围高亮
- `locator_type=bbox`
  - 适用于 OCR 或版面定位结果，按页面坐标框高亮
- `locator_type=section`
  - 无法提供精确范围时的降级定位；前端应跳转 section 并提示“定位精度低”
- `char_range`、`bbox` 为可选字段；不可用时必须返回 `null`，不能返回空字符串
- `deep_link` 由后端生成，前端不应依赖内部拼接规则推断

前端降级顺序（固定）：

1. `char_range`
2. `bbox`
3. `section`

comparison 对 traceback 的依赖约定：

- comparison row 通过 `supporting_evidence_ids` 关联 evidence card
- 前端从 `supporting_evidence_ids` 打到 evidence traceback 接口，不直接绕过 evidence 资源

示例（traceback item）：

```json
{
  "anchor_id": "anc_01",
  "document_id": "doc_01",
  "locator_type": "char_range",
  "locator_confidence": "high",
  "page": 12,
  "quote": "capacity retention improved after annealing...",
  "section_id": "sec_results_2",
  "char_range": { "start": 1880, "end": 1962 },
  "bbox": null,
  "deep_link": "/collections/col_xxx/documents/doc_01?page=12&anchor_id=anc_01"
}
```

### Comparisons

- `GET /api/v1/collections/{collection_id}/comparisons`
- `GET /api/v1/collections/{collection_id}/comparisons/{row_id}`

这是 Lens v1 的主 collection-facing 比较资源。

列表接口支持这些可选过滤参数：

- `material_system_normalized`
- `property_normalized`
- `test_condition_normalized`
- `baseline_normalized`

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

### Graph、Reports 次级界面

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`
- `GET /api/v1/collections/{collection_id}/graphml`
- `GET /api/v1/collections/{collection_id}/reports/communities`
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
- `GET /api/v1/collections/{collection_id}/reports/patterns`

这些接口可以保留，但不是 Lens v1 新界面的主验收面。

Graph 语义约束：

- `/graph` 与 `/graphml` 只消费
  `document_profiles.parquet`、`evidence_cards.parquet`、
  `comparison_rows.parquet`
- 它们当前是 Core-derived graph projection，不再以
  `entities.parquet`、`relationships.parquet`、`communities.parquet`
  作为产品语义前提
- `/graph` 返回结构字段：
  `collection_id / nodes / edges / truncated`
- graph node 只保留：
  `id / label / type / degree`
- graph edge 只保留：
  `id / source / target / weight / edge_description`
- graph node `type` 当前可以是：
  `document | evidence | comparison | material | property | test_condition | baseline`
- graph edge `edge_description` 当前可以是：
  `document_to_evidence | evidence_to_comparison | comparison_to_material |
  comparison_to_property | comparison_to_test_condition | comparison_to_baseline`
- `/graph/nodes/{node_id}/neighbors` 返回中心节点的一跳邻域，字段与 `/graph`
  保持同一精简结构
- 节点详情不再经由 graph 聚合透出；前端应根据 `doc:` / `evi:` / `cmp:`
  前缀回到 document / evidence / comparison canonical 资源
- 聚合节点 `mat:` / `prop:` / `tc:` / `base:` 不提供 graph-owned detail；
  前端应回到 `/comparisons` 并使用对应过滤参数做 canonical drilldown
- graph 输入未就绪时，应返回 `409`，并携带稳定错误码
  `graph_not_ready`

Reports 语义约束：

- `/reports/communities` 与 `/reports/communities/{community_id}`
  当前是兼容路径名，语义底座已经改为 Core-derived pattern grouping
- 这里的 `community_id` 应被解释为当前 pattern group 标识，不是
  GraphRAG community 拓扑 id
- report detail 里的 `entities`、`relationships`、`documents`
  都应被视为从 document / evidence / comparison Core artifact
  派生出的二级投影，而不是旧 entity graph 的直接透出
- `/reports/patterns` 与上述 report 路由属于同一组 Core-derived
  派生视图，只是命名更直接

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
- `graph`
  - Core graph 输入缺失时返回 `409`
  - 请求的 `node_id` 不存在时，`/graph/nodes/{node_id}/neighbors` 返回 `404`

## 前端集成约束

- 浏览器与前端代码只应依赖 `/api/v1/*` 与 `/api/*` 两类前缀
- collection 详情页的主状态来源是 `workspace`
- 前端不应把 `sections_ready`、`procedure_blocks_ready` 这类内部产物状态当成长期主合同
- protocol 页面不是默认首页，comparison workspace 才是
- goal-first 响应只用于 Goal Brief / Intake 与 collection handoff，主展示仍必须消费 Core 资源
- graph 与 reports 是从 Core artifact 派生出的次级视图，不能反向充当 document/evidence/comparison 的事实来源
- query 的 runtime 选项是次级搜索接口参数，不应被提升成主界面信息架构或主业务对象语义

## 相关文档

- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
- [`../plans/core-first-product-surface-cutover-plan.md`](../plans/backend-wide/core-first-product-surface-cutover-plan.md)
- [`../plans/evidence-first-parsing-plan.md`](../plans/historical/evidence-first-parsing-plan.md)
- [`../plans/goal-core-source-contract-follow-up-plan.md`](../plans/backend-wide/goal-core-source-contract-follow-up-plan.md)
- [`../plans/claim-traceback-navigation-implementation-plan.md`](../plans/core/claim-traceback-navigation-implementation-plan.md)
- [`../../../docs/contracts/lens-v1-definition.md`](../../../docs/contracts/lens-v1-definition.md)
- [`../../../docs/contracts/lens-core-artifact-contracts.md`](../../../docs/contracts/lens-core-artifact-contracts.md)
- [`../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md`](../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md)
