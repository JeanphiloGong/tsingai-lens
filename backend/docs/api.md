# API 接口文档

默认 Base URL：`http://localhost:8010`（请根据部署实际修改主机与端口），当前接口未启用鉴权。

## 集合管理（/retrieval/collections）
- **POST** `/retrieval/collections` — 创建集合
  - 请求体（JSON）：`name`（可选，集合名称）。
  - 返回：`id`、`name`、`created_at`、`updated_at`、`status`、`document_count`、`entity_count`。
  ```bash
  curl -X POST http://localhost:8010/retrieval/collections \
    -H "Content-Type: application/json" \
    -d '{"name":"paper-lab"}'
  ```

- **GET** `/retrieval/collections` — 列出集合（含统计指标）
  - 返回：`items`（每项包含 `id`、`name`、`created_at`、`updated_at`、`status`、`document_count`、`entity_count`）。
  - 说明：未指定 `collection_id` 的接口默认使用系统内置 `default` 集合。
  - 字段说明：
    - `status`：`ready`（有实体输出）/ `empty`（未完成索引）。
    - `updated_at`：集合输出目录中的关键产物更新时间，缺失时可回退使用 `created_at`。
  ```bash
  curl http://localhost:8010/retrieval/collections
  ```

- **DELETE** `/retrieval/collections/{collection_id}` — 删除集合
  - 说明：删除集合目录及其全部输出文件；`default` 集合不可删除。
  - 返回：`id`、`deleted_at`、`status`（固定为 `deleted`）。
  ```bash
  curl -X DELETE http://localhost:8010/retrieval/collections/<COLLECTION_ID>
  ```

## 集合文件管理（/retrieval/collections/{collection_id}/files）
- **POST** `/retrieval/collections/{collection_id}/files` — 向集合上传文件（不触发索引）
  - 表单字段：`files`（必填；支持多个 PDF/TXT）。
  - 返回：`count` 与 `items`（包含 `stored_path` 等字段）。
  ```bash
  curl -X POST http://localhost:8010/retrieval/collections/<COLLECTION_ID>/files \
    -F "files=@/path/to/paper1.pdf" \
    -F "files=@/path/to/paper2.pdf"
  ```

- **GET** `/retrieval/collections/{collection_id}/files` — 列出集合文件
  - 返回：`collection_id`、`count` 与 `items`（每项包含 `key`、`original_filename`、`stored_path`、`size_bytes`、`created_at`）。
  ```bash
  curl http://localhost:8010/retrieval/collections/<COLLECTION_ID>/files
  ```

- **DELETE** `/retrieval/collections/{collection_id}/files` — 删除集合文件
  - 查询参数：`key`（必填，文件 key，如 `uploads/<uuid>_<name>.txt`）。
  - 返回：`collection_id`、`key`、`deleted_at`、`status`（固定为 `deleted`）。
  ```bash
  curl -X DELETE "http://localhost:8010/retrieval/collections/<COLLECTION_ID>/files?key=uploads/<FILE_KEY>"
  ```

## 索引与上传（/retrieval）
- **POST** `/retrieval/index` — 启动索引流程
  - 请求体（JSON）：`collection_id`（可选）、`method`（默认 `standard`，可选：`standard`/`fast`）、`is_update_run`（默认 `false`）、`verbose`（默认 `false`）、`additional_context`（可选字典）。
  - 返回：`status`、`workflows`、`errors`、`output_path`、`stored_input_path`。
  ```bash
  curl -X POST http://localhost:8010/retrieval/index \
    -H "Content-Type: application/json" \
    -d '{"collection_id":"<COLLECTION_ID>","method":"standard","is_update_run":false,"verbose":false}'
  ```

- **POST** `/retrieval/index/upload` — 上传文件并启动索引
  - 表单字段：`file`（必填；PDF 会先提取纯文本再入库），`collection_id`（可选），`method`（可选，默认 `standard`），`is_update_run`（可选，默认 `false`），`verbose`（可选，默认 `false`）。
  - 返回：同上，额外返回 `stored_input_path`（存储的输入文件路径/键）。
  ```bash
  curl -X POST http://localhost:8010/retrieval/index/upload \
    -F "file=@/path/to/document.pdf" \
    -F "collection_id=<COLLECTION_ID>" \
    -F "method=standard" \
    -F "is_update_run=false" \
    -F "verbose=false"
  ```

- **POST** `/retrieval/input/upload` — 批量上传文件到输入存储（不触发索引）
  - 表单字段：`files`（必填；支持多个 PDF/TXT），`collection_id`（可选）。
  - 返回：`count` 与 `items`（包含 `stored_path` 等字段）。
  ```bash
  curl -X POST http://localhost:8010/retrieval/input/upload \
    -F "collection_id=<COLLECTION_ID>" \
    -F "files=@/path/to/paper1.pdf" \
    -F "files=@/path/to/paper2.pdf"
  ```

- 批量导入推荐流程
  1) 可选：调用 `/retrieval/collections` 创建集合。
  2) 调用 `/retrieval/collections/{collection_id}/files` 批量上传（仅入库，不索引）。
  3) 调用 `/retrieval/index` 触发一次索引（扫描集合输入目录）。
  4) 调用 `/retrieval/graphml` 导出 Gephi 文件。

## 检索（/retrieval）
- **POST** `/retrieval/query` — 基于索引结果进行检索问答
  - 请求体（JSON）：`query`（必填），`method`（可选，默认 `global`，可选：`global`/`local`/`drift`/`basic`），`collection_id`（可选），`response_type`（可选，默认 `List of 5-7 Points`），`community_level`（可选，默认 `2`），`dynamic_community_selection`（可选，默认 `false`，仅 `global` 生效），`include_context`（可选，默认 `false`），`verbose`（可选，默认 `false`）。
  - 返回：`answer`（回答内容）、`method`（实际检索方法）、`collection_id`、`output_path`（集合输出目录）、`context_data`（可选，需 `include_context=true`）。
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

## 图数据导出（/retrieval）
- **GET** `/retrieval/graphml` — 导出 GraphML（可用于 Gephi 等）
  - 查询参数：`collection_id`（可选），`max_nodes`（默认 200）、`min_weight`（默认 0.0，关系权重过滤）、`community_id`（可选，按社区筛选）、`include_community`（可选，默认 `true`，是否输出节点 `community` 字段用于分组着色）。
  - GraphML 字段：
    - 节点字段：`label`、`type`、`description`、`degree`、`frequency`、`x`、`y`、`community`
    - 边字段：`weight`、`edge_description`
    - 证据字段（节点）：
      - `node_text_unit_ids`、`node_text_unit_count`
      - `node_document_ids`、`node_document_titles`、`node_document_count`
    - 证据字段（边）：
      - `edge_text_unit_ids`、`edge_text_unit_count`
      - `edge_document_ids`、`edge_document_titles`、`edge_document_count`
  ```bash
  curl -OJ "http://localhost:8010/retrieval/graphml?collection_id=<COLLECTION_ID>&max_nodes=200&min_weight=0&include_community=true"
  ```

注意事项
- PDF 需可复制文本（扫描版 PDF 暂不支持 OCR）。
- 证据字段依赖 `text_units.parquet` 与 `documents.parquet`，若缺失则不输出。
- 配置由服务端在集合级别管理，客户端无需传入配置路径。

## Protocol 产物与 SOP（/retrieval/protocol）
- 说明：这些接口消费 protocol 中间产物。`output_path` 为空时，会回退到默认 collection 的 output 目录。

- **POST** `/retrieval/protocol/extract` — 读取并汇总 protocol 产物
  - 请求体（JSON）：
    - `output_path`（可选）：GraphRAG 输出目录
    - `paper_ids`（可选）：按论文 ID 过滤
    - `limit`（可选，默认 `50`，范围 `1-500`）
  - 返回：`summary`、`sections`、`procedure_blocks`、`protocol_steps`。
  ```bash
  curl -X POST http://localhost:8010/retrieval/protocol/extract \
    -H "Content-Type: application/json" \
    -d '{"output_path":"/path/to/output","paper_ids":["paper-1"],"limit":20}'
  ```

- **GET** `/retrieval/protocol/steps` — 列出 protocol steps
  - 查询参数：
    - `output_path`（可选）
    - `paper_id`（可选）
    - `block_type`（可选）
    - `limit`（默认 `50`，范围 `1-500`）
    - `offset`（默认 `0`）
  ```bash
  curl "http://localhost:8010/retrieval/protocol/steps?output_path=/path/to/output&paper_id=paper-1&limit=20"
  ```

- **GET** `/retrieval/protocol/search` — 检索 protocol steps
  - 查询参数：
    - `q`（必填）
    - `output_path`（可选）
    - `paper_id`（可选）
    - `limit`（默认 `10`，范围 `1-100`）
  ```bash
  curl "http://localhost:8010/retrieval/protocol/search?q=anneal%20N2&output_path=/path/to/output&limit=5"
  ```

- **POST** `/retrieval/protocol/sop` — 基于 protocol steps 生成结构化 SOP 草案
  - 请求体（JSON）：
    - `goal`（必填）
    - `output_path`（可选）
    - `paper_ids`（可选数组）
    - `target_properties`（可选数组）
    - `max_steps`（可选，默认 `12`，范围 `1-50`）
  - 返回：`count`、`sop_draft`。
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

## Protocol 数据合同（字段定义）
- 下列结构为即将接入 `/retrieval/protocol/*` 接口的合同定义，本次先定义字段，不代表路由已全部实现。
- 目录级输入统一使用 `output_path` 指向 GraphRAG 产物目录；为空时回退默认配置输出目录。

- `NormalizedValueItem`
  - `value`：归一化后的数值。
  - `unit`：归一化单位，建议温度统一 `K`、时长统一 `s`、压力统一 `Pa`。
  - `raw_value`：原始文本值。
  - `operator`：`=`、`>`、`<`、`~`、`range`。
  - `min_value` / `max_value`：区间值。
  - `status`：`reported` / `inferred` / `not_reported` / `ambiguous`。

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
