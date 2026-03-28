# API 接口文档

默认 Base URL：`http://localhost:8010`。当前接口未启用鉴权。

## 推荐接入方式
- 产品默认入口：`/collections`、`/tasks`、`/workspace`
- 结果接口优先：图谱、protocol、SOP 都优先走 collection 维度接口
- 兼容 / 调试接口：`/retrieval/*`
- 不建议前端默认直接调用：`/retrieval/index`、`/retrieval/index/upload`、`/retrieval/protocol/*`

## 前端标准调用顺序
1. `GET /collections`
2. `POST /collections`
3. `POST /collections/{collection_id}/files`
4. `POST /collections/{collection_id}/tasks/index`
5. 轮询 `GET /tasks/{task_id}`
6. 进入 `GET /collections/{collection_id}/workspace`
7. 再按页面进入：
   - `GET /collections/{collection_id}/graph`
   - `GET /collections/{collection_id}/graphml`
   - `GET /collections/{collection_id}/protocol/steps`
   - `GET /collections/{collection_id}/protocol/search`
   - `POST /collections/{collection_id}/protocol/sop`

## 前端页面映射
### 集合列表页
- 主接口：`GET /collections`
- 关键字段：`items[].collection_id`、`items[].name`、`items[].status`、`items[].paper_count`、`items[].updated_at`
- 展示重点：集合名称、论文数、最近更新时间、当前状态

### 新建集合弹窗
- 主接口：`POST /collections`
- 请求字段：`name`、`description`、`default_method`
- 展示重点：最小创建表单，成功后跳转集合详情

### 集合文件页
- 主接口：
  - `GET /collections/{collection_id}/files`
  - `POST /collections/{collection_id}/files`
- 关键字段：`file_id`、`original_filename`、`stored_filename`、`status`、`size_bytes`、`created_at`
- 展示重点：文件列表、上传状态、上传时间

### 处理进度区
- 主接口：
  - `POST /collections/{collection_id}/tasks/index`
  - `GET /tasks/{task_id}`
  - `GET /tasks/{task_id}/artifacts`
- 关键字段：`task_id`、`status`、`current_stage`、`progress_percent`、`errors`、`warnings`
- 展示重点：任务状态、阶段名称、进度百分比、失败信息
- 轮询建议：`queued/running` 状态下每 2-3 秒轮询一次

### 工作区首页
- 主接口：`GET /collections/{collection_id}/workspace`
- 关键字段：`collection`、`file_count`、`status_summary`、`artifacts`、`latest_task`、`recent_tasks`、`capabilities`
- 展示重点：集合总览、当前是否可看图谱 / protocol / SOP、最近任务

### 图谱页
- 主接口：
  - `GET /collections/{collection_id}/graph`
  - `GET /collections/{collection_id}/graphml`
- 关键字段：`nodes`、`edges`、`truncated`、`community`
- 展示重点：图谱预览、过滤条件、GraphML 下载

### Protocol 步骤页
- 主接口：`GET /collections/{collection_id}/protocol/steps`
- 关键字段：`items[].step_id`、`items[].paper_id`、`items[].order`、`items[].action`、`items[].materials`、`items[].conditions`、`items[].purpose`、`items[].confidence_score`
- 展示重点：实验步骤顺序、动作、材料、条件、置信度

### Protocol 搜索页
- 主接口：`GET /collections/{collection_id}/protocol/search`
- 关键字段：`items[].step_id`、`items[].paper_id`、`items[].action`、`items[].matched_fields`、`items[].excerpt`、`items[].score`
- 展示重点：命中片段、命中字段、相似度排序

### SOP 生成页
- 主接口：`POST /collections/{collection_id}/protocol/sop`
- 请求字段：`goal`、`target_properties`、`paper_ids`、`max_steps`
- 关键字段：`sop_draft.objective`、`sop_draft.hypothesis`、`sop_draft.variables`、`sop_draft.steps`、`sop_draft.measurement_plan`、`sop_draft.risks`、`sop_draft.open_questions`
- 展示重点：实验目标、步骤链、表征计划、风险和待确认问题

### 任务历史页
- 主接口：`GET /collections/{collection_id}/tasks`
- 关键字段：`items[].task_id`、`items[].status`、`items[].current_stage`、`items[].progress_percent`、`items[].created_at`、`items[].finished_at`
- 展示重点：历史任务、成功/失败状态、最近运行时间

## 产品主入口（App Layer）
- 说明：这一层是科研助手的主流程入口，围绕 `collection_id` 和 `task_id` 工作。

### 集合与文件
- **POST** `/collections` — 创建论文集合
  - 请求体：`name`（必填）、`description`（可选）、`default_method`（可选，默认 `standard`）
  ```bash
  curl -X POST http://localhost:8010/collections \
    -H "Content-Type: application/json" \
    -d '{"name":"Composite Papers","description":"复合材料论文集合"}'
  ```

- **GET** `/collections` — 列出论文集合
  - 返回每个集合的基础元数据：`collection_id`、`name`、`status`、`paper_count`、`updated_at`
  ```bash
  curl http://localhost:8010/collections
  ```

- **GET** `/collections/{collection_id}` — 获取集合详情
  ```bash
  curl http://localhost:8010/collections/<collection_id>
  ```

- **POST** `/collections/{collection_id}/files` — 上传论文到集合
  - 表单字段：`file`
  - 说明：当前是单文件上传接口；PDF 会自动转为文本后写入集合输入目录
  ```bash
  curl -X POST http://localhost:8010/collections/<collection_id>/files \
    -F "file=@/path/to/paper.pdf"
  ```

- **GET** `/collections/{collection_id}/files` — 列出集合文件
  - 返回：`file_id`、`original_filename`、`stored_filename`、`status`、`size_bytes`
  ```bash
  curl http://localhost:8010/collections/<collection_id>/files
  ```

### 任务
- **POST** `/collections/{collection_id}/tasks/index` — 创建集合索引任务
  - 请求体：`method`、`is_update_run`、`verbose`、`additional_context`
  - 返回：`task_id`、`status`、`current_stage`、`progress_percent`、`errors`、`warnings`
  ```bash
  curl -X POST http://localhost:8010/collections/<collection_id>/tasks/index \
    -H "Content-Type: application/json" \
    -d '{"method":"standard","is_update_run":false,"verbose":false}'
  ```

- **GET** `/collections/{collection_id}/tasks` — 列出集合任务历史
  - 查询参数：`status`（可选）、`limit`（默认 `20`）、`offset`（默认 `0`）
  ```bash
  curl "http://localhost:8010/collections/<collection_id>/tasks?status=completed&limit=20&offset=0"
  ```

- **GET** `/tasks/{task_id}` — 查询任务状态
  - 前端轮询主接口
  - 关键字段：`status`、`current_stage`、`progress_percent`、`errors`、`warnings`
  ```bash
  curl http://localhost:8010/tasks/<task_id>
  ```

- **GET** `/tasks/{task_id}/artifacts` — 查询任务产物状态
  - 用于判断 `documents`、`graph`、`sections`、`procedure_blocks`、`protocol_steps` 是否已就绪
  ```bash
  curl http://localhost:8010/tasks/<task_id>/artifacts
  ```

### 工作区与结果
- **GET** `/collections/{collection_id}/workspace` — 获取集合工作区概览
  - 返回：`collection`、`file_count`、`status_summary`、`artifacts`、`latest_task`、`recent_tasks`、`capabilities`
  - 用途：集合详情页主接口
  ```bash
  curl http://localhost:8010/collections/<collection_id>/workspace
  ```

- **GET** `/collections/{collection_id}/graph` — 获取集合图数据
  - 查询参数：`max_nodes`（默认 `200`）、`min_weight`（默认 `0.0`）、`community_id`（可选）
  - 返回：`nodes`、`edges`、`truncated`、`community`
  ```bash
  curl "http://localhost:8010/collections/<collection_id>/graph?max_nodes=200&min_weight=0"
  ```

- **GET** `/collections/{collection_id}/graphml` — 导出集合 GraphML
  ```bash
  curl -OJ "http://localhost:8010/collections/<collection_id>/graphml?max_nodes=200&min_weight=0"
  ```

- **GET** `/collections/{collection_id}/protocol/steps` — 列出集合 protocol steps
  - 查询参数：`paper_id`、`block_type`、`limit`、`offset`
  - 用途：展示从论文中抽取出的结构化实验步骤
  ```bash
  curl "http://localhost:8010/collections/<collection_id>/protocol/steps?limit=20"
  ```

- **GET** `/collections/{collection_id}/protocol/search` — 检索集合 protocol steps
  - 查询参数：`q`（必填）、`paper_id`（可选）、`limit`（默认 `10`）
  - 用途：按动作、材料、条件等检索步骤
  ```bash
  curl "http://localhost:8010/collections/<collection_id>/protocol/search?q=anneal%20600C&limit=5"
  ```

- **POST** `/collections/{collection_id}/protocol/sop` — 为集合生成 SOP 草案
  - 请求体：`goal`、`target_properties`、`paper_ids`、`max_steps`
  - 用途：基于现有 protocol steps 组装实验方案草案
  ```bash
  curl -X POST http://localhost:8010/collections/<collection_id>/protocol/sop \
    -H "Content-Type: application/json" \
    -d '{"goal":"为复合材料设计实验方案","target_properties":["mechanical","thermal"],"max_steps":8}'
  ```

## 兼容 / 调试接口（/retrieval）
- 说明：这部分保留给兼容旧调用、底层调试和排障使用，不建议前端作为默认产品入口直接接入。

### 旧集合接口
- **POST** `/retrieval/collections` — 创建集合
  ```bash
  curl -X POST http://localhost:8010/retrieval/collections \
    -H "Content-Type: application/json" \
    -d '{"name":"paper-lab"}'
  ```

- **GET** `/retrieval/collections` — 列出集合
  ```bash
  curl http://localhost:8010/retrieval/collections
  ```

- **DELETE** `/retrieval/collections/{collection_id}` — 删除集合
  ```bash
  curl -X DELETE http://localhost:8010/retrieval/collections/<COLLECTION_ID>
  ```

- **POST** `/retrieval/collections/{collection_id}/files` — 向集合上传文件
  - 表单字段：`files`
  ```bash
  curl -X POST http://localhost:8010/retrieval/collections/<COLLECTION_ID>/files \
    -F "files=@/path/to/paper1.pdf" \
    -F "files=@/path/to/paper2.pdf"
  ```

- **GET** `/retrieval/collections/{collection_id}/files` — 列出集合文件
  ```bash
  curl http://localhost:8010/retrieval/collections/<COLLECTION_ID>/files
  ```

- **DELETE** `/retrieval/collections/{collection_id}/files` — 删除集合文件
  - 查询参数：`key`
  ```bash
  curl -X DELETE "http://localhost:8010/retrieval/collections/<COLLECTION_ID>/files?key=uploads/<FILE_KEY>"
  ```

### 索引与检索
- **POST** `/retrieval/index` — 启动索引流程
  - 请求体：`collection_id`（可选）、`method`、`is_update_run`、`verbose`、`additional_context`
  - 成功完成 GraphRAG 索引后，会继续自动生成 `sections.parquet`、`procedure_blocks.parquet`、`protocol_steps.parquet`
  ```bash
  curl -X POST http://localhost:8010/retrieval/index \
    -H "Content-Type: application/json" \
    -d '{"collection_id":"<COLLECTION_ID>","method":"standard","is_update_run":false,"verbose":false}'
  ```

- **POST** `/retrieval/index/upload` — 上传文件并启动索引
  - 表单字段：`file`、`collection_id`（可选）、`method`、`is_update_run`、`verbose`
  ```bash
  curl -X POST http://localhost:8010/retrieval/index/upload \
    -F "file=@/path/to/document.pdf" \
    -F "collection_id=<COLLECTION_ID>" \
    -F "method=standard" \
    -F "is_update_run=false" \
    -F "verbose=false"
  ```

- **POST** `/retrieval/input/upload` — 批量上传文件到输入存储
  ```bash
  curl -X POST http://localhost:8010/retrieval/input/upload \
    -F "collection_id=<COLLECTION_ID>" \
    -F "files=@/path/to/paper1.pdf" \
    -F "files=@/path/to/paper2.pdf"
  ```

- **POST** `/retrieval/query` — 基于索引结果进行检索问答
  - 请求体：`query`、`method`、`collection_id`、`response_type`、`community_level`、`dynamic_community_selection`、`include_context`、`verbose`
  ```bash
  curl -X POST http://localhost:8010/retrieval/query \
    -H "Content-Type: application/json" \
    -d '{
      "collection_id":"<COLLECTION_ID>",
      "query":"基于这些论文给出可执行的实验方案（步骤/变量/指标）",
      "method":"global",
      "response_type":"List of 5-7 Points",
      "include_context":false
    }'
  ```

### 图数据导出
- **GET** `/retrieval/graphml` — 导出 GraphML
  - 查询参数：`collection_id`、`max_nodes`、`min_weight`、`community_id`、`include_community`
  ```bash
  curl -OJ "http://localhost:8010/retrieval/graphml?collection_id=<COLLECTION_ID>&max_nodes=200&min_weight=0&include_community=true"
  ```

### Protocol 兼容接口
- 说明：这些接口消费 protocol 中间产物。`output_path` 为空时，会回退到默认 collection 的 output 目录。
- `/retrieval/protocol/extract` 只消费已经生成的 `sections.parquet`、`procedure_blocks.parquet`、`protocol_steps.parquet`，不会自行执行 parser/extractor。

- **POST** `/retrieval/protocol/extract`
  - 请求体：`output_path`、`paper_ids`、`limit`
  ```bash
  curl -X POST http://localhost:8010/retrieval/protocol/extract \
    -H "Content-Type: application/json" \
    -d '{"output_path":"/path/to/output","paper_ids":["paper-1"],"limit":20}'
  ```

- **GET** `/retrieval/protocol/steps`
  - 查询参数：`output_path`、`paper_id`、`block_type`、`limit`、`offset`
  ```bash
  curl "http://localhost:8010/retrieval/protocol/steps?output_path=/path/to/output&paper_id=paper-1&limit=20"
  ```

- **GET** `/retrieval/protocol/search`
  - 查询参数：`q`、`output_path`、`paper_id`、`limit`
  ```bash
  curl "http://localhost:8010/retrieval/protocol/search?q=anneal%20N2&output_path=/path/to/output&limit=5"
  ```

- **POST** `/retrieval/protocol/sop`
  - 请求体：`goal`、`output_path`、`paper_ids`、`target_properties`、`max_steps`
  ```bash
  curl -X POST http://localhost:8010/retrieval/protocol/sop \
    -H "Content-Type: application/json" \
    -d '{
      "goal":"Design a composite protocol for mechanical and thermal optimization",
      "output_path":"/path/to/output",
      "target_properties":["mechanical","thermal"],
      "paper_ids":["paper-1"],
      "max_steps":8
    }'
  ```

### 兼容接口注意事项
- PDF 需可复制文本；扫描版 PDF 暂不支持 OCR
- Graph 证据字段依赖 `text_units.parquet` 与 `documents.parquet`
- 新产品流不应依赖 `output_path`
- 旧 `/retrieval/*` 接口仍可用于排障和底层能力验证

## Protocol 数据合同（字段定义）
- 下列结构为 `/retrieval/protocol/*` 及 collection 维度 protocol 结果接口的核心合同定义。
- 目录级输入统一使用 `output_path` 指向 GraphRAG 产物目录；collection 维度接口内部会将 `collection_id` 映射到对应输出目录。

- `NormalizedValueItem`
  - `value`：归一化后的数值
  - `unit`：归一化单位，建议温度统一 `K`、时长统一 `s`、压力统一 `Pa`
  - `raw_value`：原始文本值
  - `operator`：`=`、`>`、`<`、`~`、`range`
  - `min_value` / `max_value`：区间值
  - `status`：`reported` / `inferred` / `not_reported` / `ambiguous`

- `ConditionItem`
  - `temperature` / `duration` / `pressure` / `heating_rate` / `cooling_rate` / `ph`
  - `atmosphere`
  - `environment`
  - `raw_text`

- `MaterialRefItem`
  - `name`
  - `formula`
  - `role`：`precursor` / `solvent` / `additive` / `matrix` / `filler` / `sample` / `product` / `other`
  - `amount`
  - `composition_note`
  - `grade`
  - `source_text`

- `MeasurementSpecItem`
  - `method`
  - `instrument`
  - `target_property`
  - `metrics`
  - `conditions`
  - `output_ref`
  - `source_text`

- `ControlSpecItem`
  - `control_type`：`baseline` / `blank` / `untreated` / `literature` / `ablation` / `other`
  - `description`
  - `rationale`
  - `source_text`

- `EvidenceRefItem`
  - `paper_id`
  - `section_id`
  - `block_id`
  - `snippet_id`
  - `section_type`
  - `page_start` / `page_end`
  - `figure_or_table`
  - `quote_span`
  - `source_text`
  - `confidence_score`

- `ProtocolStepItem`
  - `step_id`
  - `paper_id`
  - `order`
  - `action`
  - `section_id`
  - `block_id`
  - `phase`：`preparation` / `synthesis` / `post_treatment` / `characterization` / `property_test` / `analysis` / `other`
  - `materials`
  - `conditions`
  - `purpose`
  - `expected_output`
  - `characterization`
  - `controls`
  - `evidence_refs`
  - `confidence_score`

- `SOPDraftItem`
  - `sop_id`
  - `objective`
  - `hypothesis`
  - `variables`
  - `constraints`
  - `controls`
  - `steps`
  - `measurement_plan`
  - `acceptance_criteria`
  - `risks`
  - `open_questions`
  - `review_status`

- 预留请求/响应模型
  - `ProtocolExtractRequest` / `ProtocolExtractResponse`
  - `ProtocolStepListResponse`
  - `ProtocolSearchHit` / `ProtocolSearchResponse`
  - `SOPDraftRequest` / `SOPDraftResponse`
