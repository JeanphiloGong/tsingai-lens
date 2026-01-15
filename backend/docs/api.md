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
  2) 调用 `/retrieval/input/upload` 批量上传（仅入库，不索引）。
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
  ```bash
  curl -OJ "http://localhost:8010/retrieval/graphml?collection_id=<COLLECTION_ID>&max_nodes=200&min_weight=0&include_community=true"
  ```

注意事项
- PDF 需可复制文本（扫描版 PDF 暂不支持 OCR）。
- 配置由服务端在集合级别管理，客户端无需传入配置路径。
