# API 接口文档

默认 Base URL：`http://localhost:8010`（请根据部署实际修改主机与端口），当前接口未启用鉴权。

## 文件上传与处理状态（/file）
- **POST** `/file/upload` — 上传文件并异步入图
  - 表单字段：
    - `file`（必填）：上传文件。
    - `tags`（可选）：逗号分隔标签，如 `tag1,tag2`。
    - `metadata`（可选）：JSON 字符串，附加元数据，如 `{"source":"manual"}`。
  - 返回：`id`（文档 ID）、`status`（初始为 `pending`）。
  - 示例：
    ```bash
    curl -X POST http://localhost:8010/file/upload \
      -F "file=@/path/to/document.pdf" \
      -F "tags=finance,weekly" \
      -F 'metadata={"source":"manual"}'
    ```

- **GET** `/file/status/{doc_id}` — 查询文件处理状态
  - 返回：`id`、`status`、`status_message`、`updated_at`。
  - 示例：
    ```bash
    curl http://localhost:8010/file/status/<doc_id>
    ```

## 图谱与文档（/graph）
- **GET** `/graph/health` — 健康检查
  ```bash
  curl http://localhost:8010/graph/health
  ```

- **GET** `/graph/documents` — 文档列表
  - 返回：`items` 数组，每项含 `id`、`filename`、`original_filename`、`tags`、`metadata`、`created_at`、`status`、`status_message`、`updated_at` 等。
  ```bash
  curl http://localhost:8010/graph/documents
  ```

- **GET** `/graph/documents/{doc_id}` — 文档详情与元数据
  - 返回：
    - `record`：文档基础信息（同上）。
    - `meta`：`keywords`、`graph`、`mindmap`、`images`、`info`、`summary` 等。
  ```bash
  curl http://localhost:8010/graph/documents/<doc_id>
  ```

- **GET** `/graph/documents/{doc_id}/keywords` — 文档关键词
  ```bash
  curl http://localhost:8010/graph/documents/<doc_id>/keywords
  ```

- **GET** `/graph/documents/{doc_id}/graph` — 文档图谱快照与脑图
  - 返回：`graph`、`mindmap`。
  ```bash
  curl http://localhost:8010/graph/documents/<doc_id>/graph
  ```

## 图谱问答（/chat）
- **POST** `/chat/query` — 基于图谱的问答
  - 请求体（JSON）：
    - `query`（必填）：问题文本。
    - `mode`（可选，默认 `optimize`）：检索模式。
    - `top_k_cards`（可选，默认 `5`）：返回卡片数量。
    - `max_edges`（可选，默认 `80`）：考虑的最大边数。
  - 返回：`answer` 文本；`sources` 数组（字段包含 `doc_id`、`source`、`page`、`chunk_id`、`snippet`、`edge_id`、`community_id`、`head`、`tail`、`relation`、`score` 等）。
  ```bash
  curl -X POST http://localhost:8010/chat/query \
    -H "Content-Type: application/json" \
    -d '{"query":"市场报告的主要趋势是什么？","mode":"optimize","top_k_cards":5,"max_edges":80}'
  ```

## 检索与索引（/retrieval）
- **POST** `/retrieval/index` — 根据指定配置文件启动标准索引流程
  - 请求体（JSON）：`config_path`（必填），`method`（可选，默认 `standard`，可选：`standard`/`fast`/`standard-update`/`fast-update`），`is_update_run`（默认 `false`），`verbose`（默认 `false`），`additional_context`（可选字典）。
  - 返回：`status`、`workflows`、`errors`、`output_path`、`stored_input_path`。
  ```bash
  curl -X POST http://localhost:8010/retrieval/index \
    -H "Content-Type: application/json" \
    -d '{"config_path":"/path/to/config.yaml","method":"standard","is_update_run":false,"verbose":false}'
  ```

- **POST** `/retrieval/index/upload` — 上传文件并使用默认配置（`backend/data/configs/default.yaml`）启动索引
  - 表单字段：`file`（必填；PDF 会先提取纯文本再入库），`method`（可选，默认 `standard`），`is_update_run`（可选，默认 `false`），`verbose`（可选，默认 `false`）。
  - 返回：同上，额外返回 `stored_input_path`（存储的输入文件路径/键）。
  ```bash
  curl -X POST http://localhost:8010/retrieval/index/upload \
    -F "file=@/path/to/document.pdf" \
    -F "method=standard" \
    -F "is_update_run=false" \
    -F "verbose=false"
  ```

- 图数据导出
  - **GET** `/retrieval/graph` — 获取图数据（前端可视化用）
    - 查询参数：`output_path`（可选，使用 /retrieval/index 返回的路径或默认配置输出目录）、`max_nodes`（默认 200）、`min_weight`（默认 0.0，关系权重过滤）、`community_id`（可选，按社区筛选）。
    ```bash
    curl "http://localhost:8010/retrieval/graph?max_nodes=200&min_weight=0&community_id="
    ```
  - **GET** `/retrieval/graphml` — 导出 GraphML（可用于 Gephi 等）
    - 查询参数同上。
    ```bash
    curl -OJ "http://localhost:8010/retrieval/graphml?max_nodes=200&min_weight=0"
    ```

- 配置管理
  - **POST** `/retrieval/configs/upload` — 上传配置文件
    ```bash
    curl -X POST http://localhost:8010/retrieval/configs/upload \
      -F "file=@/path/to/config.yaml"
    ```
  - **POST** `/retrieval/configs` — 以文本创建配置文件
    - 请求体（JSON）：`filename`、`content`。
    ```bash
    curl -X POST http://localhost:8010/retrieval/configs \
      -H "Content-Type: application/json" \
      -d '{"filename":"my-config.yaml","content":"# yaml here"}'
    ```
  - **GET** `/retrieval/configs` — 列出配置文件
    ```bash
    curl http://localhost:8010/retrieval/configs
    ```
  - **GET** `/retrieval/configs/{filename}` — 查看配置文件内容
    ```bash
    curl http://localhost:8010/retrieval/configs/default.yaml
    ```
