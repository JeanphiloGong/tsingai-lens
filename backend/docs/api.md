# API 接口文档

默认 Base URL：`http://localhost:8010`（请根据部署实际修改主机与端口），当前接口未启用鉴权。

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
  - **GET** `/retrieval/graphml` — 导出 GraphML（可用于 Gephi 等）
    - 查询参数：`output_path`（可选，使用 /retrieval/index 返回的路径或默认配置输出目录）、`max_nodes`（默认 200）、`min_weight`（默认 0.0，关系权重过滤）、`community_id`（可选，按社区筛选）。
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
