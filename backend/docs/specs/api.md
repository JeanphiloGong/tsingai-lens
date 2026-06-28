# API 接口文档

这是当前 Lens v1 的前后端主合同。

前端应按这里的资源模型和接口组织设计界面。某些接口如果尚未落地，实现责任在后端，不影响这里作为约定合同的地位。

默认 Base URL：`http://localhost:8010`。当前接口未启用鉴权。

## 总体约定

- 业务接口统一位于：`/api/v1/*`
- 文档与静态资源统一位于：`/api/*`
- collection 是主业务单位，不是单篇 paper
- `workspace` 是 Lens v1 的主入口界面
- `comparisons` 是主分析资源
- `results` 是核心产品对象资源
- `documents` 是来源核验资源
- `evidence/cards` 是支撑型资源，主要服务于 result/document/comparison drilldown
- `graph/*` 当前是消费 Core artifact 的派生视图，不再定义独立研究事实模型
- 当前没有单独公开的 `query/search` 产品接口
- `goals/*` 当前只表示 Goal Brief / Intake，不是完整 Goal Consumer / Decision Layer
- `goal-sessions/*` 是绑定 collection 的 AI research copilot 会话层，必须区分
  collection evidence 与 general fallback
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
3. `POST /api/v1/collections/{collection_id}/tasks/build`
4. 轮询 `GET /api/v1/tasks/{task_id}`
5. 打开 `GET /api/v1/collections/{collection_id}/workspace`
6. 从 workspace 进入 `comparisons`
7. 从 `comparisons` drilldown 到 `results`
8. 需要核验来源时，从 `results` 回到 `documents`
9. 在 comparison/result/document 中需要核验证据时，调用 traceback 接口并跳转文档查看器

可选 collection-bound 短对话流程：

1. `POST /api/v1/goal-sessions` 绑定一个 collection
2. `PATCH /api/v1/goal-sessions/{session_id}` 设置 goal、focus material/paper 或回答模式
3. `POST /api/v1/goal-sessions/{session_id}/messages`
4. 根据返回的 `source_mode` 区分知识库证据、证据不足、通用背景回退或纯通用回答
5. 从返回的 `source_links` 进入可访问的文献或证据位置；`used_evidence_ids` 只作诊断追踪

可选 goal-first collection seeding 流程（当前只覆盖 Goal Brief / Intake）：

1. `POST /api/v1/goals/intake`
2. 从响应读取 `seed_collection.collection_id`
3. 打开 `GET /api/v1/collections/{collection_id}/workspace`
4. 后续统一进入 `goal-sessions`、`comparisons`、`results`、`documents`

## 资源与接口

### Goal Brief / Intake（可选 collection seeding 入口）

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

### Goal Sessions / Collection-bound Short Conversation

- `POST /api/v1/goal-sessions`
- `GET /api/v1/goal-sessions/{session_id}`
- `PATCH /api/v1/goal-sessions/{session_id}`
- `POST /api/v1/goal-sessions/{session_id}/messages`
- `GET /api/v1/goal-sessions/{session_id}/messages`

最小 session 字段：

- `session_id`
- `user_id`
- `collection_id`
- `focused_material_id`
- `focused_paper_id`
- `goal_text`
- `goal_brief_json`
- `answer_mode`
- `rolling_summary`
- `last_evidence_ids`
- `last_material_ids`
- `last_paper_ids`
- `collection_data_version`

最小创建请求只需要绑定 collection：

```json
{
  "collection_id": "col_xxx"
}
```

`goal_text`、`focused_material_id`、`focused_paper_id`、`answer_mode` 和
`goal_brief_json` 都是可选会话上下文。`goal_brief_json` 是可选 metadata，不是开始
对话的前置条件。

`answer_mode` 可选值：

- `grounded`：只允许基于当前 collection 的 Core 证据回答；无证据时返回受限说明
- `hybrid`：默认模式；优先查 collection，缺少证据时允许通用背景回退
- `general`：不以当前 collection 作为证据来源，只做通用背景回答

message 返回必须包含：

- `answer`
- `source_mode`
- `used_evidence_ids`
- `warnings`
- `links`
- `source_links`

`source_mode` 可选值：

- `collection_grounded`
- `collection_limited`
- `general_fallback`
- `general_only`

语义约束：

- session 必须绑定一个 collection
- session 可以在没有结构化 Goal Brief 的情况下开始
- grounded/hybrid 模式必须先检索当前 collection 的 Core 或 derived Core artifact
- collection-grounded 结论不得编造 evidence id、sample id、paper name 或 property value
- `source_links` 必须是前端可访问的 document/evidence 路由；普通回答 UI 不应把文献
  内部 ID 当作主要来源展示
- general fallback 必须明确标注不是当前 collection 证据结论
- rolling summary 可以记录对话连续性，但不得把 general fallback 提升为 collection evidence
- 当前短对话层不产出 final coverage assessment、gap detection、clue ranking 或
  next-step decision support

### Collection 与任务入口

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/files`
- `POST /api/v1/collections/{collection_id}/tasks/build`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `POST /api/v1/collections/{collection_id}/references/build`
- `GET /api/v1/collections/{collection_id}/references`

约束：

- `GET /api/v1/tasks/{task_id}` 只接收真正的 `task_id`
- `collection_id` 不能拿来调用 task 详情接口
- collection 页面如果要展示任务历史，应走 collection 维度的 tasks 接口
- `task_type` 对外固定为 `build`
- `current_stage` 对外应使用：
  `queued | files_registered | source_artifacts_started | source_artifacts_completed | document_profiles_started | document_profiles_completed | objective_candidates_started | objective_candidates_completed | objective_paper_skim_started | objective_discovery_started | objective_paper_framing_started | objective_evidence_routing_started | objective_evidence_units_started | objective_logic_chains_started | paper_facts_started | comparison_rows_started | research_understandings_started | research_understandings_completed | artifacts_ready | failed`
- `graphrag_index_started`、`graphrag_index_completed`
  已退役，不再属于公开或内部活动合同
- Source 结构产物当前包括
  `documents`、`text_units`、`blocks`、
  `figures`、`tables`、`table_rows`、
  `table_cells` 以及 `image_assets/`
- Source 引用文献扩展是独立流程，不属于 collection build 主链路：
  - `POST /api/v1/collections/{collection_id}/references/build`
    从已生成的 Source `blocks` 中抽取 References/Bibliography 条目、正文 citation
    mention 和 metadata-only candidate pool
  - `GET /api/v1/collections/{collection_id}/references`
    读取 `entries`、`mentions`、`resolutions`、`candidates`
  - 当前版本不自动下载引用 PDF，不自动把引用文献导入 collection input，不把引用
    条目提升为 Core research facts
  - 如果 Source artifacts 尚未生成，build 接口返回 `409`，错误码为
    `source_artifacts_not_ready`
- `GET /api/v1/tasks/{task_id}/artifacts`
  与 workspace 内的 `artifacts` 都应对 comparison semantic 相关产物额外暴露
  `*_stale` 字段，用来表达：
  - `collection_comparable_results_stale`
    表示 collection-scoped assessment 已因 policy/version drift 或 assessment
    input drift 而失效
  - `comparison_rows_stale`
    表示 row cache 已因上游 scope artifact 失效而不再 current
  - `graph_stale`
    表示 graph 的 comparison semantic 输入不再 current
  - stale 时对应的 `ready` 必须为 `false`，但 `generated` 可以保持 `true`

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

- `workflow` 应优先表达 `comparisons`、`results`、`documents`、`graph` 四个阶段的状态
  - `evidence` 可以在迁移期继续作为 secondary compatibility field 暴露
- 状态值应使用显式语义，例如
  `not_started | processing | ready | limited | not_applicable | failed`
- `workflow.results`
  应以 `comparable_results` 与
  `collection_comparable_results` 作为 readiness 语义判断
  - `comparison_rows` 只是可重建 projection/cache，不是 results 的
    contract 前提
- `workflow.comparisons`
  应以 `comparable_results` 与
  `collection_comparable_results` 作为 readiness 语义判断
  - `comparison_rows` 只是可重建 projection/cache，不是 comparisons
    或 graph 的 contract 前提
- `status_summary=ready`
  应表示 collection-scoped comparison read model 已就绪，即使 row cache 尚未预生成
- `document_summary` 应来自 `document_profiles` 的 collection 级汇总
- `warnings` 应表达 review-heavy、comparison-limited、traceability-limited 等
  collection 风险
- `links` 应指向主资源页面，而不是让前端自己拼内部跳转语义
- `links.comparisons`、`links.results`、`links.documents`
  应是 collection 主工作流入口
- `links.evidence`
  如果仍然暴露，应被视为 support/debug surface，而不是主导航中心
- `links.comparable_results`
  如果继续暴露，应直接给出当前 collection 对应的 filtered corpus retrieval
  路径，即 `/api/v1/comparable-results?collection_id={collection_id}`
  - 它是 semantic inspection / retrieval surface，不应替代 `links.results`
- `links.research_view`
  指向 collection research aggregation，即
  `/api/v1/collections/{collection_id}/research-view`
- `links.research_materials`
  指向 collection materials 主入口，即
  `/api/v1/collections/{collection_id}/materials`
- `links.research_material`
  是 collection material profile 路径模板，即
  `/api/v1/collections/{collection_id}/materials/{material_id}/research-view`
- `links.research_documents`
  是 document research aggregation 路径模板，即
  `/api/v1/collections/{collection_id}/documents/{document_id}/research-view`
- `links.research_document_materials`
  是 document-scoped material list 路径模板，即
  `/api/v1/collections/{collection_id}/documents/{document_id}/materials`
- `links.research_document_material`
  是 document-scoped material profile 路径模板，即
  `/api/v1/collections/{collection_id}/documents/{document_id}/materials/{material_id}/research-view`
- `artifacts` 对每类产物应同时提供
  `*_generated` 与 `*_ready` 两类布尔值：
  - `generated` 表示该阶段产物文件已生成（可能为空）
  - `ready` 表示该阶段产物可直接用于主界面消费（通常要求非空）
- `artifacts`
  对 comparison semantic 相关产物还应提供 `*_stale`：
  - `collection_comparable_results_stale`
  - `comparison_rows_stale`
  - `graph_stale`
- 对这些 comparison semantic 产物：
  - `generated=true` 仅表示文件或投影前提存在
  - `ready=true` 还要求它们当前没有 stale
- `figures_generated` / `figures_ready`
  对应 Source 层 `figures` 的生成与可消费状态
  - figure 行可以存在而 `image_path` 为空
  - 这种情况下仍应保留 figure traceability 行，不应直接丢弃
- `graph_generated`
  表示 `document_profiles`、`evidence_cards`、
  `comparable_results`、`collection_comparable_results`
  四个 Core graph 语义输入文件都已生成
- `graph_ready`
  表示上述 Core graph 语义输入已具备图投影消费条件，而不是
  `entities` / `relationships` 是否存在
- `artifacts` 不再暴露 `graphml_generated` / `graphml_ready`
  因为 GraphML 已改为基于 Core graph 的按需导出能力，不再是构建阶段的 readiness 产物
- `capabilities.can_download_graphml`
  应与 `graph_ready` 保持一致，表达当前 collection 是否可以导出按需生成的 GraphML
- `capabilities.can_view_results`
  应在 `comparable_results` 与 `collection_comparable_results`
  已生成时为 `true`
  - 它表达当前 collection 的 product-facing result surface 可被消费
- `capabilities.can_view_comparable_results`
  应在 `comparable_results` 与 `collection_comparable_results`
  已生成时为 `true`
  - 它表达 collection-filtered corpus comparable-result surface 可被消费
  - 不要求 `comparison_rows` 预先存在
- `capabilities.can_view_research_view`
  应在 paper facts 已生成时为 `true`
  - 它表达 sample matrix / paper coverage 聚合有可消费输入
  - 空 collection 仍可请求 research-view endpoint，但状态应为 `empty`

### Research Objectives

- `GET /api/v1/collections/{collection_id}/objectives`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/research-view`
- `POST /api/v1/collections/{collection_id}/goals`
- `GET /api/v1/collections/{collection_id}/goals`
- `GET /api/v1/collections/{collection_id}/goals/{goal_id}`
- `POST /api/v1/collections/{collection_id}/goals/{goal_id}/analysis`
- `GET /api/v1/collections/{collection_id}/goals/{goal_id}/analysis`

这是 objective-first / confirmed-goal 工作区的主读取合同。collection build
默认只生成 lightweight objective candidates；深度证据路由、证据单元、
logic chain 和 research-understanding 投影必须在用户确认 goal 后，通过
confirmed-goal analysis 运行。

Objective 接口只读取已经落库的 Core research-objective records，不在 GET
请求中触发 LLM 构建。

Objective list 最小返回结构：

- `collection_id`
- `state`
- `readiness`
- `objectives`
- `warnings`

Objective research-view 最小返回结构：

- `collection_id`
- `state`
- `objective`
- `objective_context`
- `readiness`
- `paper_frames`
- `evidence_routes`
- `evidence_units`
- `logic_chain`
- `understanding`
- `existing_comparison_rows`
- `warnings`

`objective` 至少包含：

- `objective_id`
- `question`
- `material_scope`
- `process_axes`
- `property_axes`
- `comparison_intent`
- `confidence`

`readiness` 使用：

- `objectives_ready`
- `frames_ready`
- `routes_ready`
- `evidence_units_ready`
- `logic_chain_ready`

语义要求：

- objective candidate 是系统推荐的候选研究问题；confirmed goal 是用户或
  benchmark 确认后的深度分析输入
- goal analysis 输出的 `understanding.scope.scope_type` 为 `goal`，并使用
  `goal_id` 作为人工标注、纠错和后续 AI grounding 的稳定 scope id
- objective 是候选资源身份；material 只作为 scope/facet 展示
- `/materials` 不返回 objective records
- `paper_frames` 来自 `ObjectivePaperFrame`，并补充 document title 与
  source filename
- `relevant_tables` 与 `excluded_tables` 必须是真实 Source table id
- `evidence_routes`、`evidence_units`、`logic_chain`
  在下游 builder 未完成时可以为空，但字段必须保留
- `understanding` 是 collection build 持久化的 Core research understanding
  artifact，由 objective evidence units、logic chain、evidence refs 和 context
  直接确定性投影，用于前端展示 Claim / Relation / Evidence / Context
  工作区；GET 请求只读取已持久化 artifact，不触发新的 LLM 调用或重建
- confirmed goal analysis 的 `POST` 是显式深度分析入口；失败只更新该
  `goal_id` 的 `status=failed` 和 `analysis_error`，不应让 collection build
  整体失败
- confirmed goal analysis 的 `POST` 只启动后台分析并立即返回当前
  `GoalAnalysisResponse`；前端应轮询 `GET .../analysis` 读取
  `goal.status`、`goal.analysis_progress` 和最终 `understanding`
- `goal.analysis_progress` 是可选对象，运行中可包含 `phase`、`current`、
  `total`、`unit`、`message`、`active_document_id`、
  `active_document_title`、`active_source_filename` 和
  `active_objective_id`，用于展示当前阶段和正在分析的文献
- `existing_comparison_rows` 当前是投影保留字段，不作为第一版 objective
  research-view 的事实来源

错误语义：

- collection 不存在：`404`
- research objectives 尚未生成且 collection 非空：`409 research_objectives_not_ready`
- objective research-view 指向不存在目标：`404 research_objective_not_found`

### Research View

- `GET /api/v1/collections/{collection_id}/research-view`
- `GET /api/v1/collections/{collection_id}/materials`
- `GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/research-view`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/materials/{material_id}/research-view`

这是 research-facing 聚合合同，用来把 Core 研究证据组织成样品矩阵、
条件序列、文献覆盖、材料档案和 collection 比较组。

它不是 raw `measurement_results` 或 result-card list 的兼容包装；前端不应在
主界面重新从一条条 fact 自行拼矩阵。

Collection-scoped materials 是 objective-first 输出：`/materials` 与
`/materials/{material_id}/research-view` 只能由 objective evidence units 和
objective material rows 驱动。旧 paper facts 路径可以继续服务 document-scoped
research-view、debug 或 source 核验，但不得作为 collection material 主页面的
fallback。collection 已有文件但尚未生成 objective material evidence 时，这两个
collection material 接口应返回 `409 research_view_not_ready`。

Collection research-view 最小返回结构：

- `collection_id`
- `state`
- `overview`
- `materials`
- `paper_coverage`
- `comparable_groups`
- `cross_paper_matrices`
- `trend_series`
- `evidence_links`
- `debug_links`
- `warnings`

Paper research-view 最小返回结构：

- `collection_id`
- `document_id`
- `paper_title`
- `state`
- `overview`
- `materials`
- `sample_matrix`
- `condition_series`
- `evidence_links`
- `debug_links`
- `warnings`

Collection materials 最小返回结构：

- `collection_id`
- `state`
- `materials`
- `warnings`

Collection material profile 最小返回结构：

- `collection_id`
- `material_id`
- `canonical_name`
- `aliases`
- `state`
- `overview`
- `papers`
- `sample_matrix`
- `process_parameter_ranges`
- `measured_properties`
- `comparison_groups`
- `condition_series`
- `evidence_refs`
- `understanding`
- `debug_links`
- `warnings`

Document materials 最小返回结构：

- `collection_id`
- `document_id`
- `state`
- `materials`
- `warnings`

Document material profile 最小返回结构：

- `collection_id`
- `document_id`
- `material_id`
- `canonical_name`
- `aliases`
- `state`
- `overview`
- `sample_matrix`
- `process_conditions`
- `test_conditions`
- `measured_properties`
- `within_paper_comparisons`
- `condition_series`
- `evidence_refs`
- `debug_links`
- `warnings`

状态值使用：

```text
empty | processing | partial | ready | failed
```

`understanding` 最小结构：

- `schema_version`：当前为 `research_understanding.v1`
- `state`：`empty | partial | ready | limited`
- `scope`：包含 `scope_type`、`collection_id`，并按范围补充
  `objective_id`、`material_id`、`document_id` 和 `title`
- `claims`：系统认为成立、受限或冲突的结论；每条至少包含
  `claim_id`、`claim_type`、`statement`、`status`、`evidence_ref_ids`、
  `context_ids` 和 `source_object_ids`
- `relations`：claim 或条件之间的关系；每条至少包含
  `relation_id`、`relation_type`、`subject`、`predicate`、`object`、
  `status`、`evidence_ref_ids` 和 `context_ids`
- `evidence_refs`：可跳回来源文献、表格、文本窗口或 fact 的证据引用；每条至少包含
  `evidence_ref_id`、`source_kind`、`document_id`、`label`、`locator`、
  `fact_ids`、`anchor_ids` 和 `traceability_status`
- `contexts`：结论成立的材料、工艺、测试条件、性能范围和局限
- `warnings`
- `summary`：`claim_count`、`relation_count`、`evidence_ref_count`、
  `context_count`

Research understanding 专家反馈资源：

- `POST /api/v1/collections/{collection_id}/research-understanding/feedback`
- `GET /api/v1/collections/{collection_id}/research-understanding/feedback`
- `POST /api/v1/collections/{collection_id}/research-understanding/curations`
- `GET /api/v1/collections/{collection_id}/research-understanding/curations`
- `GET /api/v1/collections/{collection_id}/research-understanding/gold-draft`

`POST` 请求体：

- `scope_type`：`objective`、`material`、`document` 或 collection scope
- `scope_id`：对应 scope 的稳定 id
- `claim_id`：被复核的 claim id
- `review_status`：`correct | partial | incorrect | unclear`
- `issue_type`：
  `none | evidence_not_grounded | missing_evidence | wrong_context |
  wrong_relation | overclaim | unclear_statement | other`
- `note`：可选专家备注，最多 2000 字符
- `reviewer`：可选复核人标识，最多 120 字符

`GET` 支持可选 query filter：`scope_type`、`scope_id`、`claim_id`。
返回 `collection_id` 和 `items`，每条 item 包含
`feedback_id`、scope、`claim_id`、`review_status`、`issue_type`、`note`、
`reviewer` 和 `created_at`。该资源用于沉淀专家评价数据，不改变
`understanding` artifact 本身。

`curations` 用于保存专家校正后的 claim 副本，不覆盖系统生成的
`understanding` artifact。`POST` 请求体包含：

- `scope_type`、`scope_id`、`claim_id`
- `curated_claim_type`：
  `finding | measurement | comparison | mechanism | limitation | context`
- `curated_status`：`supported | limited | conflicted | unsupported`
- `curated_statement`：专家校正后的 claim 表述，最多 4000 字符
- `curated_evidence_ref_ids`：专家认可绑定的 evidence ref id 列表
- `curated_context_ids`：专家认可绑定的 context id 列表
- `note`：可选校正备注，最多 2000 字符
- `reviewer`：可选校正人标识，最多 120 字符

`GET /curations` 支持可选 query filter：`scope_type`、`scope_id`、
`claim_id`。返回 `collection_id` 和 `items`，每条 item 包含 `curation_id`、
scope、`claim_id`、专家校正字段、`note`、`reviewer` 和 `updated_at`。同一
collection/scope/claim 的 curation 使用稳定 id 覆盖更新，便于后续把系统 claim
与专家 curation 对齐评价。

`GET /gold-draft` 需要 query：`scope_type` 和 `scope_id`。返回从该 scope 下
专家 curation 派生的只读 gold 草稿：

- `gold_id`
- `target_layer`，当前为 `core`
- `metric_profile`，当前为 `research_understanding_v1`
- `item_count`
- `items`

每个 item 使用 `family=research_understanding_claims`，并包含 `gold_item_id`、
`item_key`、`payload`、`evidence_refs` 和 `metadata`。该接口不注册正式
gold set，只用于把专家校正数据导出给评价流程或人工审查。

前端 workbench 应读取 `feedback` 和 `curations` 并叠加到 claim 视图：curation
可作为当前显示的专家校正副本，feedback 作为复核历史展示；两者都不修改原始
`understanding` artifact。

语义要求：

- `paper_coverage` 每篇文献一行，表达样品数、工艺参数数、measurement 数、
  condition 数、evidence 数和主要 warning
- `materials` 是 collection 的主材料入口；`comparison_groups` 是材料档案内
  的分析模块和高级调试入口，不是顶级主导航对象
- collection material profile 可以跨文献聚合别名、样品、工艺范围、性能摘要、
  比较组和 research understanding
- collection material profile 可以附带 `understanding`，其语义与 objective
  research-view 中的 `understanding` 一致，但 scope 固定为 `material`；
  该字段同样只读取 collection build 已持久化 artifact，旧 collection 缺失时
  可以为 `null`
- document material profile 只表达单篇文献内一个材料的事实，不做跨文献合并
- `sample_matrix.rows` 应优先是一行一个真实 sample / variant
- generic material/process mention 不应成为主矩阵样品行
- 重复 measurement facts 应折叠到同一 `EvidenceBackedValue.duplicate_count`
  中，而不是产生重复 visible rows
- 温度、时间、应变率、频率等条件轴应形成 `condition_series`
- 每个 observed value 应保留 `evidence_refs`，无法保留时应给出结构化
  warning

错误语义：

- collection 不存在：`404`
- paper facts 尚未生成且 collection 非空：`409 research_view_not_ready`
- document research-view 指向不存在文档：`404 research_view_document_not_found`
- material profile 指向不存在材料：`404 research_view_material_not_found`

### Documents

- `GET /api/v1/collections/{collection_id}/documents/profiles`

这是 Lens v1 的来源核验资源。

产品语义上它对应 `Documents` 页面；当前 list endpoint 仍然使用
`/documents/profiles` 路径。

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
  "parsing_warnings": [],
  "confidence": 0.91
}
```

单项 drilldown 路径：

- `GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/markdown`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/source`
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`

其中 `/profile` 返回与 list item 同语义的单项 document profile，`/content`
返回原文阅读器内容与 section fallback 结构，`/source` 以 inline file
response 返回该 document 的原始上传文件，供浏览器 PDF/source reader
直接展示。`/markdown` 返回从 Source artifacts 生成的展示用 Markdown
投影，供文档详情页默认阅读论文原文；它不是新的事实来源，也不替代
`documents`、`blocks`、`tables`、`figures` 等 Source artifacts。

`/markdown` 最小返回结构：

- `collection_id`
- `document_id`
- `title`
- `source_filename`
- `parser`
- `markdown`
- `source_map`
- `warnings`

`source_map` 用于把 Markdown 展示片段回指到 Source artifact，至少包含：

- `markdown_anchor`
- `artifact_type`
- `artifact_id`
- `block_id`
- `table_id`
- `figure_id`
- `block_type`
- `page`
- `heading_path`
- `text_unit_ids`

`/content` 的每个 block 仍是 backend source locator unit，不是前端可见
章节模型。前端可以用这些字段做 fallback 定位，但默认 UI 不应暴露
`block_id`、`blk_xxx` 或重复的 block-level `heading_path`。block locator
字段：

- `page`: 源文件页码；不可用或非法时为 `null`
- `bbox`: 页面坐标框；不可用或非法时为 `null`
  - `x0`
  - `y0`
  - `x1`
  - `y1`
  - `coord_origin`
- `char_range`: 源文本字符范围；不可用或非法时为 `null`
  - `start`
  - `end`

`/source` 行为：

- 成功时返回 `200`，`Content-Disposition` 为 inline，`Content-Type` 优先使用
  collection metadata 中的 `media_type`，否则按文件名推断
- collection 或 document 无法解析时返回 `404`
- document 存在但 source file 缺失、无法安全解析或存在歧义时返回 `409`
  structured detail
- endpoint 不接受任何 request path；文件路径只能从 collection-owned
  metadata 解析，且必须位于 collection input 目录内

文档页语义要求：

- `documents` 是 source-of-truth recovery surface，不是主比较页
- document detail 默认展示解析后的 Markdown 论文阅读视图
- PDF/source file 是可选预览和证据定位参考，不是默认阅读入口
- comparison 或 result drilldown 回到文档时，应能稳定落到对应 paper
- document detail 应能够承载来自 result/evidence 的 traceback deep link

### Results

- `GET /api/v1/collections/{collection_id}/results`
- `GET /api/v1/collections/{collection_id}/results/{result_id}`

这是 Lens v1 的核心产品对象资源。

它的产品语义顺序必须是：

`comparison row -> result -> document`

它的内部投影顺序必须是：

`comparable_results -> current collection_comparable_results -> product-facing result projection`

而不是把 raw semantic payload 直接暴露成主页面模型。

列表接口支持这些可选过滤参数：

- `material_system_normalized`
- `property_normalized`
- `test_condition_normalized`
- `baseline_normalized`
- `comparability_status`
- `source_document_id`

列表最小返回结构：

- `collection_id`
- `total`
- `count`
- `items`

每个 list item 至少应包含：

- `result_id`
- `document_id`
- `document_title`
- `material_label`
- `property`
- `value`
- `unit`
- `baseline`
- `test_condition`
- `process`
- `traceability_status`
- `comparability_status`

详情最小返回结构：

- `result_id`
- `document`
- `material`
- `measurement`
- `context`
- `assessment`
- `evidence`
- `actions`

已支持的 additive evidence-chain 字段：

- `variant_dossier`
- `test_condition_detail`
- `baseline_detail`
- `structure_support`
- `value_provenance`
- `series_navigation`

语义要求：

- `result_id` 是产品向标识；当前可以内部映射到 deterministic
  `comparable_result_id`
- 结果页必须由 `ComparableResult` 与当前 collection 的
  `CollectionComparableResult` 共同投影
- 结果页的 additive evidence-chain contract 已在
  `docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`
  冻结；该 contract 把结果页提升为 chain-first drilldown，而不是继续停留在
  generic measurement card
- `variant_dossier` 是当前 result 对应的 parent dossier summary，不是第二个主页面模型
- `test_condition_detail`、`baseline_detail`、`structure_support`、
  `value_provenance` 应作为 additive fields 暴露，不应挤压现有根级结果合同
- `series_navigation`
  只在同一 dossier 下存在 sibling result series 时出现，可选返回
- 结果页应同时提供回到 comparison 视图和 source document 的链接
- 结果页不应把 `binding`、`normalized_context`、`collection_overlays`
  这些 raw semantic 字段直接作为主页面合同
- `comparison_rows` 不是 results contract 的语义真源
- 如果 collection 还没有生成 comparable result semantic artifacts，应返回
  `409 results_not_ready`

### Document Comparison Semantics

- `GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`

这是 document-first 的 comparison semantic drilldown 路径，不是产品向
`Result detail` 合同。

它的语义顺序必须是：

`document -> comparable_results -> collection_comparable_results -> optional row projection`

而不是从 `comparison_rows` 反推语义。

最小返回结构：

- `collection_id`
- `document_id`
- `total`
- `count`
- `items`

已支持的 additive grouped projection 字段：

- `variant_dossiers`

每个 item 至少应包含：

- `comparable_result_id`
- `source_result_id`
- `source_document_id`
- `binding`
- `normalized_context`
- `axis`
- `value`
- `evidence`
- `variant_label`
- `baseline_reference`
- `result_source_type`
- `epistemic_status`
- `normalization_version`
- `collection_overlays`
- `projected_rows`

每个 `collection_overlays` item 至少应包含：

- `collection_id`
- `comparable_result_id`
- `assessment`
- `epistemic_status`
- `included`
- `sort_order`
- `policy_family`
- `policy_version`
- `comparable_result_normalization_version`
- `assessment_input_fingerprint`
- `reassessment_triggers`

语义要求：

- 这是 `ComparableResult` 的 document-scoped inspection surface，不是 row list
- 该路由的 additive grouped drilldown contract 已在
  `docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`
  冻结
- flat `items` list 必须继续保留；grouped projections 是 additive read model，
  不是第二套相互冲突的 semantic truth
- `variant_dossiers`
  应作为 document-side grouped drilldown 的顶层字段，由 backend 从同一 semantic
  truth 投影而来
- `collection_overlays`
  必须来自 `collection_comparable_results`，按 `comparable_result_id`
  关联
- `collection_overlays`
  必须显式带出评估策略元数据与 reassessment trigger，而不是只返回裸
  assessment 结果
- `projected_rows`
  只是按需附带的 projection/cache 视图，默认可为空或 `null`
- 该接口不应要求 `comparison_rows` 预先存在

查询参数：

- `include_row_projections=true|false`
  - `false` 时不要求返回 row projection
  - `true` 时允许为 document-facing drilldown 附带按需生成的 row payload
- `include_grouped_projections=true|false`
  - `false` 时允许省略 grouped dossier/series projection
  - `true` 时返回 `variant_dossiers`

### Corpus Comparable Results

- `GET /api/v1/comparable-results`
- `GET /api/v1/comparable-results/{comparable_result_id}`

这是 `ComparableResult` 的 corpus-level retrieval surface，不是 collection
产品页里的 `results` 合同。

它的语义顺序必须是：

`collection outputs -> comparable_results -> current collection_comparable_results overlays`

而不是从 `comparison_rows` 回推语义。

列表接口支持这些可选过滤参数：

- `material_system_normalized`
- `property_normalized`
- `test_condition_normalized`
- `baseline_normalized`
- `source_document_id`
- `collection_id`

最小返回结构：

- `collection_id`
- `total`
- `count`
- `items`

每个 item 至少应包含：

- `comparable_result_id`
- `source_result_id`
- `source_document_id`
- `binding`
- `normalized_context`
- `axis`
- `value`
- `evidence`
- `variant_label`
- `baseline_reference`
- `result_source_type`
- `epistemic_status`
- `normalization_version`
- `observed_collection_ids`
- `collection_overlays`

每个 `collection_overlays` item 至少应包含：

- `collection_id`
- `comparable_result_id`
- `assessment`
- `epistemic_status`
- `included`
- `sort_order`
- `policy_family`
- `policy_version`
- `comparable_result_normalization_version`
- `assessment_input_fingerprint`
- `reassessment_triggers`

语义要求：

- 这是 `ComparableResult` 的 corpus retrieval surface，不是 collection row list
- 基础 item 必须按 deterministic `comparable_result_id` 去重
- `observed_collection_ids` 表达该 semantic unit 当前在哪些 collection 中被观测到
- `collection_overlays`
  只能附着 current 的 `CollectionComparableResult`，不能直接回传 stale overlay
- 如果 `collection_id` 存在：
  - 结果集只保留该 collection 当前观测到的 comparable results
  - `collection_overlays` 也只返回该 collection 的 current overlay
- 如果 `collection_id` 不存在：
  - 结果集按 corpus-wide scan 返回
  - 可附带所有匹配 collection 的 current overlays
- 该接口不应要求 `comparison_rows` 预先存在
- `GET /api/v1/comparable-results/{comparable_result_id}`
  读取单个 corpus comparable result；如果同时传 `collection_id`，则按该 collection 的
  current scope 解释是否命中
- 如果 `collection_id` 指向的 collection 尚未生成 comparable result semantic
  artifacts，应返回 `409 comparable_results_not_ready`

### Evidence Cards

- `GET /api/v1/collections/{collection_id}/evidence/cards`
- `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}`

这是 Lens v1 的 claim-centered 支撑型证据资源。

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
- 该资源主要服务于 result detail、document detail、comparison traceback
  等支撑性阅读流，而不是主 collection 导航中心

### Claim Traceback 与 PDF 定位合同

这是 comparison/result/document 到原文证据回溯的统一合同。

前端主展示应优先围绕 comparison rows、results、documents 组织；PDF 是证据回溯层，不是默认首页主视图。

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

1. `page + bbox` when the active reader can draw PDF overlays
2. `char_range`
3. `page`
4. `section`
5. `quote`
6. source location unavailable message

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
- `result_id`
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
- `/comparisons`
  当前以 `comparable_results` +
  `collection_comparable_results` 为语义真源，并可按需重投影 row cache
- `comparability_status` 使用
  `comparable | limited | not_comparable | insufficient`
- 前端应把 comparison rows 作为主比较表
- comparison row 的主 drilldown 应进入 `results/{result_id}`，而不是把 row
  自己当成最终事实页

### Graph 次级界面

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`
- `GET /api/v1/collections/{collection_id}/graphml`

这些接口可以保留，但不是 Lens v1 新界面的主验收面。

Graph 语义约束：

- `/graph` 与 `/graphml` 只消费
  `document_profiles`、`research_objectives`、
  `objective_evidence_units`、`objective_logic_chains`
- graph 派生读路径应从 objective-first semantic records 投影，不要求
  `comparison_rows` 预先存在
- 它们当前是 Core-derived graph projection，不再以
  `entities`、`relationships`、`communities`
  作为产品语义前提
- collection-wide `comparison_rows` 不再是这条链路的语义输入；paper-local
  keys such as `Case`、`condition number`、`sample number` may appear as
  sample or trace context, but must not be projected as test conditions unless
  resolved evidence says they are real test conditions
- `/graph` 返回结构字段：
  `collection_id / nodes / edges / truncated`
- graph node 只保留：
  `id / label / type / role / summary / metrics / detail_rows / objective_id /
  logic_chain_id / degree`
- graph edge 只保留：
  `id / source / target / weight / edge_description / source_role / target_role`
- graph node `type` 当前可以是：
  `objective | material_system | material_scope | process_sample_context |
  test_conditions | characterization | measurement_results |
  controlled_comparisons | mechanism_interpretation | limitations`
- graph node `role` 当前可以是：
  `research_objective | material_system | material_scope |
  process_sample_context | test_conditions | characterization | measurement_results |
  controlled_comparisons | mechanism_interpretation | limitations`
- `detail_rows` 是聚合 step 的证据明细表。paper-local keys such as
  `Case 15`、`condition no. 2`、单条 measurement value 不应作为默认画布节点；
  它们应进入对应 semantic node `detail_rows`
- graph edge `edge_description` 当前可以是：
  `objective_to_material_system | material_system_to_material_scope |
  objective_to_material_scope | semantic_chain_step_to_step`
- 当 `edge_description=semantic_chain_step_to_step` 时，`source_role` 和
  `target_role` 表达具体链路环节，例如
  `material_scope -> process_sample_context`。这样 graph API 保持稳定边类型，
  前端仍能恢复具体科研链路顺序
- `/graph/nodes/{node_id}/neighbors` 返回中心节点的一跳邻域，字段与 `/graph`
  保持同一结构
- graph 输入未就绪时，应返回 `409`，并携带稳定错误码
  `graph_not_ready`
- `graph_not_ready.detail.missing_artifacts` 应返回缺失的 graph 语义输入文件名，
  而不是要求旧的 graph cache 文件

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

- `documents/profiles`、`results`、`comparisons`
  - 对应 `*_generated=false`：返回 `409`
  - 对应 `*_generated=true` 且结果为空：返回 `200`，`count=0`
  - 对应 `*_ready=true`：返回 `200`，可直接用于主界面
- `evidence/cards`
  - 作为支撑型资源，未生成时返回 `409`
  - 生成后即使为空也可返回 `200`，`count=0`
- `graph`
  - Core graph 输入缺失时返回 `409`
  - 请求的 `node_id` 不存在时，`/graph/nodes/{node_id}/neighbors` 返回 `404`

## 前端集成约束

- 浏览器与前端代码只应依赖 `/api/v1/*` 与 `/api/*` 两类前缀
- collection 详情页的主状态来源是 `workspace`
- 前端不应把内部产物状态当成长期主合同
- 前端主工作流应理解为 `comparisons -> results -> documents`
- `results` 是主 drilldown 对象，不应直接用 raw `comparable-results` retrieval payload 代替
- goal-first 响应只用于 Goal Brief / Intake 与 collection handoff，主展示仍必须消费 Core 资源
- `evidence` 是支撑型阅读流，不应重新上升为主导航中心
- graph 是从 Core artifact 派生出的次级视图，不能反向充当 document/result/comparison 的事实来源
- query 的 runtime 选项是次级搜索接口参数，不应被提升成主界面信息架构或主业务对象语义

## 相关文档

- [`../../../docs/decisions/rfc-comparison-result-document-product-flow.md`](../../../docs/decisions/rfc-comparison-result-document-product-flow.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`../architecture/goal-core-source-layering.md`](../architecture/goal-core-source-layering.md)
- [`../plans/core-first-product-surface-cutover-plan.md`](../plans/backend-wide/core-first-product-surface/implementation-plan.md)
- [`../plans/evidence-first-parsing-plan.md`](../plans/historical/evidence-first-parsing-plan.md)
- [`../plans/goal-core-source-contract-follow-up-plan.md`](../plans/backend-wide/goal-source-core-layering/contract-follow-up.md)
- [`../plans/claim-traceback-navigation-implementation-plan.md`](../plans/core/claim-traceback-navigation-implementation-plan.md)
- [`../../../docs/contracts/lens-v1-definition.md`](../../../docs/contracts/lens-v1-definition.md)
- [`../../../docs/contracts/lens-core-artifact-contracts.md`](../../../docs/contracts/lens-core-artifact-contracts.md)
- [`../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md`](../../../frontend/src/routes/collections/claim-traceback-navigation-contract.md)
