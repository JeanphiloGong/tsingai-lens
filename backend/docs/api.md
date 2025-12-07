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
