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
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans`
- `PATCH /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}`

最小 session 字段：

- `session_id`
- `user_id`
- `collection_id`
- `focused_material_id`
- `focused_paper_id`
- `focused_objective_id`
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

`goal_text`、`focused_material_id`、`focused_paper_id`、`focused_objective_id`、
`answer_mode` 和 `goal_brief_json` 都是可选会话上下文。
`focused_objective_id` 用于把对话绑定到已确认 Research Objective，并优先消费该 Objective 下已经进入
`training_ready` 的 research-understanding Findings。`goal_brief_json` 是可选 metadata，
不是开始对话的前置条件。

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
- `review_gate`: 只有基于专家确认且具备变量、结果、方向或范围、可追溯证据的
  protocol-ready Findings 生成的 collection-grounded 回答才返回
  `protocol_ready_findings`；实验方案保存会检查该字段

### Objective Experiment Plans

实验方案草稿是 Goal Consumer 的人类可编辑输出，不替代旧的 conditional protocol
浏览分支。它用于把 AI chat 基于 curated Findings 生成的下一步实验建议保存下来，后续由
专家继续修改。

Goal Copilot 生成的协议草稿必须为每个独立变量说明实际操纵方式。对于 VED 等派生或
复合变量，`Variable matrix` 必须分别说明哪些组成参数改变、哪些保持不变，不得在所有
组成参数固定时声称派生变量发生变化。若引用的文献比较同时改变多个组成参数，草稿必须
把它标为混杂比较，并提出隔离变量或因子实验验证；没有来源支持的参数和测量方法必须标为
拟议设计选择，不能表述成文献事实。

`Proposed design choice` 不得包含未归属来源的数值、材料牌号、设备缩写或方法缩写。
这些信息只有在后端投影为带来源标签的 `Source-backed` 行时才能作为文献事实出现；无法
安全归属的生成细节会被省略并替换为由专家选择或确认的方法/控制项，而不是无引用保留。

后端会对 VED 草稿执行确定性校验，而不是只依赖模型遵守提示词：至少一个组成参数必须
明确改变，激光功率、扫描速度、道间距和层厚都必须被归入改变或固定，且同一参数不能同时
属于两类。只改变一个组成参数时，方案只能表述为该参数介导的 VED 路径，不得声称已经
隔离出普适的 VED 单变量效应，也不得把“确认 VED-only effect”设为后续实验目标；可验证
目标应是所选组成参数路径和参数交互。该门禁覆盖 Copilot 回答、方案创建和方案编辑；历史 Copilot
方案如果违反契约，
读取时返回 `metadata.source_validity=stale` 和
`metadata.source_validity_reasons=["protocol_design_inconsistent"]`。
`Variable matrix`、`Measurements` 和 `Controls` 中的每一项必须明确标为
`Source-backed` 并带 `[Source N]` 引用，或标为 `Proposed design choice`；
`Risks or limits` 必须区分 `Evidence limit` 与 `Design risk`。来源未提供具体数值、
标准、样本量或方法时，草稿只能要求专家选择或确认，不能自行补全。
`Source-backed` 与对应引用必须位于同一条目，不能作为多条内容的组标题；只有原文片段
明确给出的操作设置才可标为来源支持，通用领域知识和提示词示例都不能升级为文献事实。
任何具有协议结构的候选回答都会通过 provider structured parse 归一化：Hypothesis、
已观察变量关系、已报告 outcomes 和 evidence limits 直接由 curated Findings 确定性
生成，模型只生成拟议变量操作和设计风险；`Measurements` 由来源支持的 outcomes 与专家
方法选择占位生成，`Controls` 由变量矩阵中已固定的组成参数与专家控制项占位生成。结构化解析、来源标签或
渲染校验失败的回答降级为 `collection_limited`，返回
`goal_copilot_protocol_contract_invalid` warning，清空可用于方案保存的 evidence/source
上下文，并由实验方案服务拒绝写入。

当且仅当已复核 Finding 属于 VED 且模型生成的全部变量操纵均包含不安全来源细节或不满足
组成参数契约时，渲染器回退为“改变激光功率、固定扫描速度/道间距/层厚、水平由专家选择”
的可编辑草稿。非 VED 变量没有该领域回退，候选无效时仍按协议契约失败处理。

最小创建请求：

```json
{
  "title": "Preheating validation matrix",
  "content": "Compare room-temperature and 150 C preheated LPBF builds.",
  "source_message_id": "msg_xxx",
  "source_links": [
    {
      "kind": "evidence",
      "label": "Source 1",
      "href": "/collections/col_xxx/documents/doc_xxx?evidence_id=ev_xxx"
    }
  ],
  "metadata": {
    "source": "goal_copilot"
  }
}
```

返回字段：

- `plan_id`
- `collection_id`
- `objective_id`
- `title`
- `content`
- `status`: `draft | ready_for_review | archived`
- `source_message_id`
- `source_links`
- `metadata`
- `created_by`
- `created_at`
- `updated_at`

带 `source_message_id` 的创建请求必须引用同一用户、同一 collection、同一 Objective 下已经保存的
assistant message。该 message 必须是 `collection_grounded`，包含 evidence citations 和
前端可跳转 `source_links`、生成回答时使用的 `source_finding_refs`，
`review_gate=protocol_ready_findings`，且不能带有
`curated_research_findings_empty` 或 `goal_copilot_model_unavailable` warning。
后端会从已验证的 message 回填权威 `source_links`，并在 `metadata` 中记录
`source=goal_copilot`、`source_session_id`、`source_mode`、`used_evidence_ids` 和
`review_gate=protocol_ready_findings`，同时将来源 Finding 的
`finding_fingerprint`、`protocol_source_fingerprint` 和 evidence ids 固化到
`metadata.source_findings`。保存的 `content` 必须保留可见 source label
（例如 `[Source 1]`）和结构化实验方案小节；不带 `source_message_id` 的请求视为专家手写草稿，可以直接保存。

读取或更新 Goal Copilot 方案时，后端会将 `metadata.source_findings` 与当前 Objective
dataset 比较，并在响应 metadata 中附加 `source_validity=current | stale | unverified`
和 `source_validity_reasons`。Finding/专家目标/训练证据版本变化、Finding 不再
`protocol_ready` 或已删除时为 `stale`；旧方案缺少来源快照或当前 dataset 无法读取时为
`unverified`。这些方案仍返回供审计和降级为草稿编辑，但只有 `current` 方案可以更新为
`ready_for_review`。

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
- collection-grounded assistant answer 必须引用返回的可见 source label（例如
  `[Source 1]`）；如果模型没有引用可见来源，后端应降级为 `collection_limited`
  并清空 `used_evidence_ids` / `source_links`
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
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/confirm`
- `POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis`
- `GET /api/v1/collections/{collection_id}/objectives/{objective_id}/research-view`

这是 objective-first 工作区的主合同。collection build
默认只生成 lightweight objective candidates；深度证据路由、证据单元、
logic chain 和 research-understanding 投影必须在用户确认 Objective 后，通过
Objective analysis 运行。

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
- `review_summary`
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
- `status`
- `analysis_error`
- `analysis_progress`
- `created_at`
- `updated_at`

`status` 只使用：

- `candidate`
- `confirmed`
- `queued`
- `running`
- `ready`
- `failed`

`ObjectiveAnalysisResponse` 最小返回结构：

- `collection_id`
- `objective`
- `understanding`
- `warnings`

`readiness` 使用：

- `objectives_ready`
- `frames_ready`
- `routes_ready`
- `evidence_units_ready`
- `logic_chain_ready`

语义要求：

- Objective candidate 是系统推荐的候选研究问题；确认操作固定该
  `objective_id` 对应的不可变 build 版本，并使其成为深度分析输入
- `objective_id` 是确认、分析、后台任务和新 Research Understanding 的唯一研究
  目标身份；analysis 输出的 `understanding.scope.scope_type` 为 `objective`
- Objective 是研究目标资源身份；material 只作为 scope/facet 展示
- `/materials` 不返回 objective records
- `paper_frames` 来自 `ObjectivePaperFrame`，并补充 document title 与
  source filename
- `relevant_tables` 与 `excluded_tables` 必须是真实 Source table id
- `evidence_routes`、`evidence_units`、`logic_chain`
  在下游 builder 未完成时可以为空，但字段必须保留
- `understanding` 是 Objective analysis 持久化的 Core research
  understanding artifact。系统先遍历候选文献并按文献积累 objective evidence
  units，再把可比的 direct results 对齐为瞬时 result sets，并用一次 objective-level
  synthesis 直接生成可包含多个 `outcomes` 的 Findings；不会持久化单篇 Finding，
  也不会再运行第二次字段聚类。GET 请求只读取已持久化 artifact，不触发新的
  LLM 调用或重建
- `understanding.presentation` 是面向材料专家默认界面的展示投影，包含
  `summary`、`effects`、`evidence_items` 和 `context_summaries`；前端应优先用
  `effects` 展示变量轴、目标性能、证据数量、文献数量和待复核状态，内部
  `claim_id` / `evidence_ref_id` 只用于反馈、校正、跳转和审计绑定
- Objective analysis 的 `POST` 是显式深度分析入口；失败只更新该
  `objective_id` 的 `status=failed` 和 `analysis_error`，不应让 collection build
  整体失败
- Objective analysis 的 `POST` 只排队后台分析并立即返回当前
  `ObjectiveAnalysisResponse`；前端应轮询 `GET .../analysis` 读取
  `objective.status`、`objective.analysis_progress` 和最终 `understanding`
- PostgreSQL 原子 claim 决定哪个 worker 可以把 `queued` 变成 `running`；重复
  请求不会并行运行同一个 Objective
- `ready` 只表示已经持久化的 Understanding 至少包含一个
  `primary_findings` 或 `review_queue_findings`；logic chain 本身不代表分析完成
- `review_summary` 与处理 `status` 分离，分别表达 Findings 审阅数量与后台处理状态
- `objective.analysis_progress` 是可选对象，运行中可包含 `phase`、`current`、
  `total`、`unit`、`message`、`active_document_id`、
  `active_document_title`、`active_source_filename` 和
  `active_objective_id`，用于展示当前阶段和正在分析的文献
- `existing_comparison_rows` 当前是投影保留字段，不作为第一版 objective
  research-view 的事实来源

错误语义：

- collection 不存在：`404`
- research objectives 尚未生成且 collection 非空：`409 research_objectives_not_ready`
- objective research-view 指向不存在目标：`404 research_objective_not_found`
- 未确认的 candidate 直接请求 analysis：`409`

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
  `status`、`evidence_ref_ids` 和 `context_ids`；goal-level synthesis relation
  还可包含 `synthesis_status`、`supporting_evidence_ref_ids`、
  `conflicting_evidence_ref_ids`、`context_evidence_ref_ids`、
  `mechanism_evidence_ref_ids`、`common_conditions`、`incomparable_conditions`
  和 `paper_contributions`
- `evidence_refs`：可跳回来源文献、表格、文本窗口或 fact 的证据引用；每条至少包含
  `evidence_ref_id`、`source_kind`、`document_id`、`label`、`locator`、
  `fact_ids`、`anchor_ids`、`traceability_status` 和可选的
  `evidence_role`
- `contexts`：结论成立的材料、工艺、测试条件、性能范围和局限
- `warnings`
- `summary`：`claim_count`、`relation_count`、`evidence_ref_count`、
  `context_count`
- `presentation`：默认材料专家工作区使用的用户可读投影
  - `presentation.summary` 至少包含 `material_scope`、`variable_axes`、
    `property_scope`、`evidence_count` 和 `review_queue_count`
  - `presentation.effects` 是默认 UI 主列表，每行包含 `effect_id`、
    `claim_id`、`title`、`statement`、`variable_axis`、`target_property`、
    `support_status`、`confidence`、`paper_count`、`evidence_count`、
    `evidence_ref_ids` 和 `context_ids`
  - `presentation.findings` 是面向材料专家的研究发现行，每行包含
    `finding_id`、`claim_id`、`statement`、`variables`、`mediators`、
    `outcomes`、`direction`、`scope_summary`、`support_grade`、
    `review_status`、`paper_count`、`evidence_count`、`evidence_ref_ids`、
    `context_ids`、`relation_ids`、`relation_chain`、`expert_use_status`、
    `generalization_status`、`generalization_note`、`evidence_gap_summary`、
    `related_review_finding_ids`、`evidence_bundle`、`synthesis_status`、
    `common_conditions`、`incomparable_conditions` 和 `paper_contributions`；
    `related_review_finding_ids`
    指向同一 presentation 中可用于确认、反驳或扩展当前 finding 的 review-queue
    finding，不复制或升级其 evidence 归属；`generalization_status`
    用于说明该 finding 当前只能作为单篇文献发现、
    跨文献候选、限定范围内跨文献发现、需要修复证据或需要处理冲突；
    `generalization_note` 和 `evidence_gap_summary` 面向专家解释使用边界和剩余证据缺口；
    `relation_chain` 是经过当前 Finding 条件边界和方向修正后的展示链路，专家界面应优先
    使用它；`relation_ids` 只保留到底层 relation 的审计绑定，不能覆盖投影后的语义；
    `synthesis_status` 使用 `agreement | conflict | condition_dependent |
    insufficient_confirmation`；`paper_count` 只统计被该 Finding 引用且提供
    直接结果证据的独立文献，不等于遍历过的候选文献数；
    `paper_contributions` 按文献保留标题、来源文件、支持/反驳角色、贡献表述和
    evidence refs；
    同一组 direct evidence units 只能投影为一个 Finding，即使模型使用不同 outcome
    顺序或宽窄不同的同义概念重复返回；单篇复合 Finding 的 `statement` 必须显式说明
    仅由一篇论文直接支持；模型漏选的 qualification/mechanism context 只有在来自同一
    直接证据文献且与所选 outcome 明确匹配时才可由后端补回；
    `evidence_bundle`
    按 `evidence_role` 分到 `direct_result`、`mechanism`、
    `condition_context`、`background`、`conflict`、`noise`，没有显式角色的证据保留在
    `uncategorized`
  - `presentation.evidence_items` 是用户可读证据卡片，内部 block/table id
    不应作为默认标题；精确 source locator 只能用于跳转参数或审计；每项可带
    `evidence_role` 用于解释它在研究发现中的作用；表格证据可带
    `table_audit.columns` 和 `table_audit.relevant_rows`，用于展示系统认为与 finding
    相关的列和行预览，但原始表格仍以 source locator 跳转为准
  - `presentation.context_summaries` 是用户可读条件摘要，不直接暴露原始
    `process_context` / `test_condition` 字典 dump

Research understanding 专家反馈资源：

- `POST /api/v1/collections/{collection_id}/research-understanding/feedback`
- `GET /api/v1/collections/{collection_id}/research-understanding/feedback`
- `POST /api/v1/collections/{collection_id}/research-understanding/curations`
- `GET /api/v1/collections/{collection_id}/research-understanding/curations`
- `GET /api/v1/collections/{collection_id}/research-understanding/gold-draft`
- `GET /api/v1/collections/{collection_id}/research-understanding/dataset`
- `GET /api/v1/collections/{collection_id}/research-understanding/dataset/collection`

`POST` 请求体：

- `objective_id`：被复核 Finding 所属的稳定 Research Objective id
- `finding_id`：被复核的 finding id
- `claim_id`：可选，finding 绑定的底层 claim id
- `review_status`：`correct | partial | incorrect | unclear`
- `issue_type`：
  `none | evidence_not_grounded | missing_evidence | insufficient_evidence |
  wrong_variable | wrong_outcome | wrong_direction | wrong_context |
  wrong_relation | overclaim | unclear_statement | other`
- `note`：可选专家备注，最多 2000 字符
- `reviewer`：可选自动复核人标识，最多 120 字符。浏览器/人工提交时后端
  使用当前登录用户作为 reviewer，忽略请求体中的普通 reviewer 字符串；只有
  以 `ai-reviewer` / `agent-` 开头的自动复核标识会按请求体保留，并且只能进入
  silver/review-candidate，不能升级为 gold/training-ready

`GET` 支持可选 query filter：`objective_id`、`finding_id`、`claim_id`。
返回 `collection_id` 和 `items`，每条 item 包含
`feedback_id`、`objective_id`、`finding_id`、`claim_id`、`finding_fingerprint`、`review_status`、
`issue_type`、`note`、`reviewer` 和 `created_at`。该资源用于沉淀专家评价数据，
不改变 `understanding` artifact 本身。`finding_fingerprint` 由后端根据提交时的
Finding statement、变量/结果/方向、适用范围、证据绑定和风险状态计算，客户端不能指定。

`curations` 用于保存专家校正后的 finding 副本，不覆盖系统生成的
`understanding` artifact。`POST` 请求体包含：

- `objective_id`、`finding_id`，以及可选 `claim_id`
- `curated_claim_type`：
  `finding | measurement | comparison | mechanism | limitation | context`
- `curated_status`：`supported | limited | conflicted | unsupported`
- `curated_statement`：专家校正后的 claim 表述，最多 4000 字符
- `curated_evidence_ref_ids`：专家认可绑定的 evidence ref id 列表
- `curated_context_ids`：专家认可绑定的 context id 列表
- `note`：可选校正备注，最多 2000 字符
- `reviewer`：可选自动校正人标识，最多 120 字符。浏览器/人工提交时后端
  使用当前登录用户作为 reviewer，忽略请求体中的普通 reviewer 字符串；只有
  以 `ai-reviewer` / `agent-` 开头的自动校正标识会按请求体保留，并且只能作为
  unverified/AI curation 进入 silver/review-candidate，不能升级为
  gold/training-ready

`GET /curations` 支持可选 query filter：`objective_id`、`finding_id`、
`claim_id`。返回 `collection_id` 和 `items`，每条 item 包含
`curation_id`、`objective_id`、`finding_id`、`claim_id`、`finding_fingerprint`、专家校正字段、`note`、
`reviewer` 和 `updated_at`。同一 collection/Objective/Finding 的 curation 使用稳定
id 覆盖更新，便于后续把系统 finding 与专家 curation 对齐评价。

`GET /gold-draft` 需要 query：`objective_id`。返回从该 Objective 下
专家 curation 派生的只读 gold 草稿：

- `gold_id`
- `target_layer`，当前为 `core`
- `metric_profile`，当前为 `research_understanding_v1`
- `item_count`
- `items`

每个 item 使用 `family=research_understanding_findings`，并包含 `gold_item_id`、
`item_key`、`payload`、`evidence_refs` 和 `metadata`。该接口不注册正式
gold set，只用于把专家校正数据导出给评价流程或人工审查。只有
`finding_fingerprint` 仍与当前 Finding 完全一致的 curation 才会进入 gold draft；
历史或内容已变化的 curation 仍保存在审计资源中，但不会继续作为当前 gold。

`GET /dataset` 需要 query：`objective_id`；可选
`label_status=candidate | silver | gold | rejected` 过滤标签状态；可选
`dataset_use_status=training_ready | review_candidate | rejected` 过滤用途状态；
可选 `task_type` 过滤样本任务类型；当前可产出的任务类型只有
`research_understanding_finding`，传入其他值时返回空数据集 envelope，并在
`task_type_filter` 中回显请求值；可选
`format=json | jsonl | messages_jsonl | training_jsonl | review_jsonl |
decision_template | decision_board_tsv | agent_review_prompt_jsonl | review_packet`，默认 `json`。`json` 返回完整数据集
envelope，`jsonl` 返回 newline-delimited 完整 sample，
`messages_jsonl` 返回 newline-delimited `{"messages": [...]}` 行，便于常见
chat evaluation/fine-tuning 工具直接消费；`training_jsonl` 在 message 行外附带
traceable training metadata，包括训练 schema/prompt 版本、task type、研究目标、
Finding 层级、Finding fingerprint、相关 document IDs、专家状态和 evidence ref IDs。
`messages_jsonl` 与 `training_jsonl` 都只写出通过 `training_message_diagnostic`
校验的 message 对；有 Gold/`training_ready` Finding 但 message 校验失败时不会输出空壳样本。
`review_jsonl` 返回可编辑的人工复核模板，
每行默认 `action=skip`，并包含 `allowed_actions`、`reject_issue_options`、
`review_instructions`、`review_risk_flags`、候选 Finding 字段、推荐动作、证据片段、
`acceptance_gate` 和 `protocol_readiness`。`decision_template` 返回更紧凑的 newline-delimited
导入模板，保留 `action`、`issue_type`、`expert_note`、`suggested_target`、
`curated_evidence_ref_ids` 和可审计的 `evidence` 摘要（source label、page、
value summary、table audit、quote、open link），适合专家或复核 agent 编辑后直接交给导入脚本预检。
`decision_board_tsv` 返回 `text/tab-separated-values` 表格，列名与离线
`expert-decision-board.tsv` 工作流兼容，适合专家在电子表格中填写
`expert_action`、`issue_type`、`expert_note` 和 `corrected_*` 字段；只读的
`label_status`、`ai_review_status`、`ai_review_issue_type`、`ai_review_note` 和
`ai_reviewer` 列显示当前 Finding 已对齐的最新 Agent 复核，但不会预填或替代人工
`expert_action`；浏览器可以把填写后的
TSV 直接作为 `decision_board_tsv` dry-run/import，CLI 仍可通过
`merge_expert_decision_board.py` 合并为 reviewed JSONL 后再导入。
`agent_review_prompt_jsonl` 返回独立复核 agent 可消费的任务 JSONL，只包含
`review_lens_research_finding` 任务、Finding、acceptance gate、protocol readiness、
evidence 和期望的 `agent_review` 输出 schema；它不输出顶层 `action`，并且 schema 中
`human_confirmed=false`，因此不能直接作为 gold/training-ready 导入。专家必须确认
agent 建议并通过 `review-decisions/import` 或离线确认脚本显式写入。
`review_packet` 返回 `text/plain` 人工可读复核包，包含同一批
`review_candidate` 的 statement、变量/结果/方向、推荐动作、acceptance gate、复核原因、
protocol readiness、证据 quote 和打开来源的链接，适合专家先快速浏览再决定是否导入
`review_jsonl` 或 `decision_template`。`protocol_readiness` 给出 `status`、`missing`、
`blocking_missing` 和逐项 `checks`，用于判断该候选在专家接受/校正后是否具备
实验方案输入所需的 statement、variables、outcomes、direction/scope 和可追溯证据；
`acceptance_gate` 把 `protocol_readiness` 与 `review_action` 合并成行级复核门槛，
包含 `status`、`accept_allowed`、`requires_correction`、`blocking_missing`、
`accept_blockers`、`review_checks` 和 `guidance`。`accept_blockers` 是直接接受的
硬阻断；例如 `verify_table_rows` 或 `table_row_alignment_uncertain` 表示表格行对齐
不确定，必须先 `correct` 修正证据/结论或 `reject`，不能直接 `accept`。当
`acceptance_gate.accept_allowed=false` 时，
专家不应把模板行直接改为 `accept`，而应先 `correct` 补齐缺口或 `reject`。
专家填写 `accept | reject | correct` 后可交给
`scripts/evaluation/expert_gold/import_goal_review_decisions.py` 导入。前端下载训练集时应使用
`dataset_use_status=training_ready`，避免把未复核候选样本混入训练输入。

`POST /review-decisions/import` 用于批量预检或导入专家复核决策。请求体包含：

- `rows`: 从 `review_jsonl` 或 `decision_template` 导出的行，专家显式把
  `action=skip` 改为 `accept | reject | correct` 后才会写入。
- `decision_board_tsv`: 可选，来自 `decision_board_tsv` 下载结果的 TSV 内容。
  提供该字段时后端会按当前 Objective dataset 重新补齐 acceptance gate、protocol
  readiness 和 evidence refs，再复用同一套 accept/reject/correct 校验。
- `reviewer`: 可选；未提供时使用当前登录用户。
- `dry_run`: 默认 `true`。为 `true` 时只校验、汇总，不写入反馈或 curation。
- `fail_on_warnings`: 默认 `false`。为 `true` 时，paper-level、table-row、
  cross-paper confirmation 等风险提示会阻止导入。

响应包含 `status`、`errors`、`warnings`、`review_progress`、
`decision_progress_by_objective` 和 `affected_objectives`。响应还包含
`readiness_summary`，用于汇总这批决策导入后会有多少 Objective 具备
training-ready、message-ready 和 protocol-ready 输入，以及是否仍有
review candidates。`review_progress.ready_to_write=false` 表示模板仍没有可写入的
人工决策。该接口不会把未复核 AI 候选自动提升为 gold/training-ready。

`GET /dataset/collection` 用于按 collection 聚合导出所有 Objective
research-understanding 样本。它不需要 `objective_id`；支持
`label_status`、`dataset_use_status`、`task_type` 和
`format=json | jsonl | messages_jsonl | training_jsonl | review_jsonl |
decision_template | decision_board_tsv | agent_review_prompt_jsonl | review_packet`。返回 envelope 的
`objective_id=null`，每个 sample 保留自己的 `objective_id`。专家批量导出训练数据时应优先使用
`/dataset/collection?dataset_use_status=training_ready&format=messages_jsonl`，
这样可以一次导出同一 collection 下所有已人工复核可训练的 Objective Findings 作为
chat-style 训练行。

返回 envelope 包含：

- `schema_version`，当前为 `research_understanding_dataset.v1`
- `dataset_id`
- `collection_id`、`objective_id`；collection 聚合导出时 `objective_id=null`
- `task_type`，当前为 `research_understanding_finding`
- `metric_profile`，当前为 `research_understanding_v1`
- `label_status_filter`
- `dataset_use_status_filter`
- `task_type_filter`
- `item_count`
- `label_counts`
- `quality_summary`
- `items`
- `warnings`

`quality_summary` 从本次返回的 sample 列表直接派生，用于真实 Objective 质量验证和
优化排查。它包含 `total_samples`、`usable_sample_count`、
`training_ready_sample_count`、`training_message_sample_count`、
`protocol_ready_sample_count`、`review_candidate_sample_count`、
`needs_review_count`、`rejected_count`、`labeled_sample_count`、
`accepted_system_sample_count`、`accepted_after_curation_match_count`、
`curated_correction_count`、`system_error_count` 和 `resolved_feedback_count`，
以及以下分布：`by_label_status`、`by_dataset_use_status`、`by_review_status`、
`by_issue_type`、`by_error_category`、`by_support_grade`、`by_trace_status`、
`by_evidence_role`、`by_evidence_traceability_status`、`by_quality_decision`、
`by_presentation_bucket` 和 `by_bucket_quality_decision`。
同时提供按数量降序排序的前 5 项诊断列表：
`top_error_categories`、`top_issue_types`、`top_review_reasons` 和
`top_system_warnings`，用于在专家标注后直接看到最常见的系统错误类别、
原始标注问题、复核原因和系统风险提示。
`by_issue_type` 保留专家标注的原始错误类型；`by_error_category` 把原始错误聚合为
`variable_error`、`outcome_error`、`direction_error`、`context_error`、
`relation_error`、`evidence_error`、`claim_scope_error`、`statement_error`、
`other_error`、`none` 和 `unreviewed`，用于统计变量误判、方向误判、证据不足等
高频失败类别，指导后续 evaluation、prompt 和 fine-tuning 数据修复。
`by_presentation_bucket` 区分 `primary`、`review_queue` 和 `unbucketed`：`primary`
对应专家界面默认展示的高信号研究发现，`review_queue` 对应仍需标注或复核的候选发现，
`unbucketed` 对应历史或 fallback artifact 中没有 presentation 分桶的样本。
`by_bucket_quality_decision` 用于判断系统主结论质量和待复核候选质量，避免把
review-queue 泛化候选误当作当前专家结论。`by_quality_decision`
用于区分 `accepted_system`、`accepted_after_curation_match`、
`curated_correction`、`ai_curated_suggestion`、`unverified_curation`、
`rejected_system`、`partial_review` 和 `candidate`。
`accepted_after_curation_match` 表示该样本仍保留专家 curation 作为 gold target，
但当前系统 prediction 已与 curation 的 statement/evidence 高度对齐；因此
`label_status=gold` 仍可能表示专家校正后可用，而不是系统原始 finding 已完全正确。
当这类样本仍带有旧的 rejecting feedback 时，反馈保留在 sample 中供审计，但
`quality_summary` 计入 `resolved_feedback_count` 和
`warning_counts.resolved_feedback`，不再计入当前未解决的 `system_error_count`。
`warning_counts` 汇总缺失 evidence、缺失原文片段、缺失 context、trace 不可用/失败、
未解决 rejected feedback 和 resolved feedback 等诊断信号。若请求带
`label_status` 过滤，`quality_summary` 只统计过滤后的返回样本；`jsonl` 格式仍只输出
逐行完整 sample，不输出 envelope summary；`messages_jsonl` 只输出带
`training_messages` 的 `{"messages": [...]}` 行；`review_jsonl` 只输出
`dataset_use_status=review_candidate` 样本的复核模板行；`decision_template` 只输出
可编辑导入行和行级证据摘要；`decision_board_tsv` 只输出这些待复核样本的电子表格复核板；
`review_packet` 只输出这些待复核样本的人类可读文本复核包。
`protocol_ready_sample_count` 是 `training_ready` 的严格子集：样本必须有有效
`training_messages`、statement、variables、outcomes、direction 或 scope，并保留
可追溯训练证据；Goal Copilot 只能把这类样本作为带证据实验方案草稿输入。

每个 sample 包含 `sample_id`、scope、`finding_id`、可选 `claim_id`、
`finding_fingerprint`、`protocol_source_fingerprint`、
`label_status`、`dataset_use_status`、`presentation_bucket`、`trace_status`、
`input_blocks`、`prompt_version`、`model_output`、`system_prediction`、
`review_action`、`expert_target`、`evidence_refs`、`training_evidence_refs`、
`training_messages`、`protocol_readiness`、`acceptance_gate`、`context_refs`、
`feedback_refs` 和 `metadata`。`evidence_refs` 保留完整审计证据链，包含
direct、mechanism、condition context、background 等角色；`training_evidence_refs`
只保留应作为监督输入的 direct/mechanism/condition context 证据，若旧样本没有角色
分桶则回退到 `evidence_refs`。每条 evidence record 里的 `source_text` 保留完整原文块供审计；
`training_source_text` 优先使用精确 `quote`，没有 quote 时才回退到 `source_text`。
只有 fingerprint 与当前 Finding 一致的 feedback/curation 才进入
`feedback_refs`、`expert_target`、`gold`、`training_ready` 和训练消息；不一致或没有
fingerprint 的历史记录列在 `metadata.ignored_feedback_refs` / `ignored_curation_refs`，
不会静默继承到语义已变化的 Finding。
`protocol_source_fingerprint` 进一步覆盖当前专家目标、训练证据原文、用途状态和
`protocol_readiness`；即使系统 Finding 本身未变，只要专家校正或方案输入证据变化，
该版本也会变化，供 Goal Copilot 消息和实验方案执行精确的来源有效性检查。
`review_action` 是从系统 review reasons、warnings 和证据绑定状态派生的
`{code, label}`，用于专家 UI、review packet 和 agent 复核队列排序；它只说明下一步
应该核对什么，例如 `verify_table_rows`、`repair_evidence_binding`、
`review_table_rows`、`check_mechanism_requirement` 或 `accept_as_paper_level`，
不代表人工标签结果。
离线 `check_goal_dataset_quality.py --format review-packet|review-jsonl` 和 HTTP
`format=review_jsonl|review_packet` 使用同一套 `protocol_readiness` 语义：`ready_after_review`
表示只缺人工复核决定，`needs_correction` 表示还缺会阻断实验方案生成的字段或证据，
`protocol_ready` 表示已满足复核、训练 messages 和方案输入要求。
普通 `json` / `jsonl` dataset sample 也包含 `protocol_readiness`，前端可以用它在
Finding 复核界面提示专家是否只差复核决定，还是还需要补变量、结果、方向/范围、
support 或可追溯证据。
离线训练或微调准备应优先消费
`training_evidence_refs[*].training_source_text`；其中 condition context 只用于约束实验
分组和固定变量，不能当作结论证据，background/noise 不进入训练证据。`training_messages` 会
把 condition context 单独放在 `Condition evidence` 段，避免与 direct/mechanism 结论证据
混淆。`training_messages` 是从
`training_evidence_refs` 和 `expert_target` 派生的 chat-style
`[{role, content}]` 样本：user message 包含可审计证据与上下文，assistant message
是专家确认或校正后的结构化 finding JSON，并保留
`generalization_status` / `generalization_note`，避免把专家接受的单篇论文
paper-level finding 训练成跨论文结论。它用于离线 evaluation/fine-tuning
准备；需要直接生成 chat-style JSONL 时使用 `format=messages_jsonl`。审计和 UI 仍应读取 `expert_target`、`training_evidence_refs`、
`context_refs` 和 `feedback_refs`。`trace_status` 可以是 `available`、`failed`、
`evidence_derived` 或 `unavailable`。只有带文本输入块的 matched trace 才作为
`available`/`failed` 输入导出；历史 trace 缺少文本输入块、或 matched trace 失败但
evidence 已能定位到原文时，导出使用 `trace_status=evidence_derived`，并从
resolved evidence quote/source text 重建 `input_blocks`。
user message 还会显式包含当前 `scope.title` 研究目标、由 `paper_count` 派生的
`paper_level | cross_paper` Finding 层级，以及每条 Evidence 的
`evidence_ref_id`、evidence role、document ID、source label 和 page。assistant
只能返回输入 Evidence header 中出现的 `evidence_ref_id`，避免生成无法从输入复制的
内部引用。缺少研究目标时不会生成 training messages。
训练 message readiness 会校验 assistant JSON 的 statement、variables、outcomes、
direction/scope、support_grade、generalization_status 和 evidence_ref_ids 与
`expert_target` / `system_prediction` / `training_evidence_refs` 对齐，避免只含
一句自然语言结论的样本进入微调导出。不通过时，sample metadata 中的
`training_message_diagnostic` 会列出缺失或不匹配的字段，供专家修正和导出排查。
`model_output` 仍保留
bounded `raw_output` 和 `parsed_output` 摘要用于诊断，不包含 API key、Authorization
header、完整环境变量或 client 配置。该接口只从已持久化 understanding artifact、
feedback 和 curations 派生样本，不注册 gold set，也不修改原始 artifact。

标签语义：

- `candidate`：没有决定性专家反馈或 curation 的系统 finding
- `silver`：专家标记为 `partial` 且没有 hard issue，或 AI/匿名 reviewer
  标记为 `correct`，或 AI/匿名 curation 尚未被人工确认
- `gold`：存在带明确非 AI reviewer 的专家 curation，或带明确非 AI reviewer
  的专家反馈标记 `correct`
- `rejected`：专家反馈标记 `incorrect`，或 issue 是
  `evidence_not_grounded`、`missing_evidence`、`insufficient_evidence`、
  `wrong_variable`、`wrong_outcome`、`wrong_direction`、`wrong_context`、
  `wrong_relation`、`overclaim`、`unclear_statement`

历史样本或 deterministic-only finding 没有匹配模型调用且没有可定位原文证据时使用
`trace_status=unavailable`，不能伪造 prompt/model trace。`evidence_refs` 应尽量带
`quote` 或 `source_text`、文献/页码/block/table provenance 和 source locator，便于
从导出样本回查原文；这些可追踪证据也是 `evidence_derived` 样本重建训练输入的来源。

前端 workbench 应读取 `feedback` 和 `curations` 并叠加到 finding 视图：
curation 可作为当前显示的专家校正副本，feedback 作为复核历史展示；两者都不修改
原始 `understanding` artifact。

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
- `GET /api/v1/collections/{collection_id}/documents/{document_id}/figures/{figure_id}/image`
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

当 Source figure 包含已抽取的图片 asset 时，`markdown` 正文应在对应 figure
位置包含同源图片引用：

- Markdown 图片语法：图片 alt 文本使用 figure label 或 caption，URL 使用下方图片接口
- 图片 URL：`/api/v1/collections/{collection_id}/documents/{document_id}/figures/{figure_id}/image`

图片引用只用于展示解析结果，不替代 `figures` artifact。没有图片 asset 的
figure 仍应保留图注文本。

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

`/figures/{figure_id}/image` 行为：

- 成功时返回 `200`，`Content-Disposition` 为 inline，`Content-Type` 优先使用
  `source_figures.image_mime_type`，否则按文件名推断
- collection、document 或当前 document 下的 figure 无法解析时返回 `404`
- figure 存在但 image asset 缺失、路径不安全或无法读取时返回 `409`
  structured detail
- endpoint 不接受任何 request path；对象 key 只能来自当前 active build、当前
  collection/document 下已登记的 Source figure，并同时校验 collection/build
  scope 与 SHA-256。collection output 和 `output/image_assets` 不参与产品读取

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
