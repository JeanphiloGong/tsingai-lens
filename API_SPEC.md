# TsingAI-Lens API 文档

- 版本：0.1.0（来源 `backend/main.py`）
- 基础地址：`http://localhost:8000`
- 启动方式：在 `backend/` 目录执行 `uvicorn main:app --reload`
- 跨域：已允许全部源（适合本地前端联调）
- 鉴权：当前无认证；生产请在网关层补充鉴权与限流
- 返回格式：`application/json`
- 错误格式：`{"detail": "message"}`，常见状态码 400/404

## 数据模型
- DocumentRecord：`{id, filename, original_filename, tags: [], metadata: {}, created_at}`
- DocumentMeta：`{keywords: [], graph: {nodes, edges}, mindmap: {...}, images: [...], summary: "..."}`，存放于 `documents_dir/{doc_id}_meta.json`
- Source：`{content: "...", metadata: {doc_id, source, chunk}}`

## 健康检查
- `GET /health`
  - 响应：`{"status": "ok"}`

## 文档列表
- `GET /documents`
  - 功能：返回已注册文档列表（来源 `backend/services/document_manager.py`）
  - 响应：`{"items": [DocumentRecord, ...]}`

## 上传文档
- `POST /documents`
  - Content-Type：`multipart/form-data`
  - 表单字段：
    - `file` 必填：支持 PDF/DOCX/TXT/MD/CSV
    - `tags` 选填：逗号分隔字符串，例如 `"LLM,经济学"`
    - `metadata` 选填：JSON 字符串，例如 `{"source":"local"}`
  - 行为：
    - 保存文件到 `settings.documents_dir`
    - 文本切片→向量化入库
    - 生成 `keywords`、`graph`、`mindmap`、`summary`，并写入 `{doc_id}_meta.json`
  - 成功响应：
    ```json
    {
      "id": "uuid",
      "keywords": ["..."],
      "graph": {"nodes": [...], "edges": [...]},
      "mindmap": {...},
      "summary": "..."
    }
    ```
  - 失败：文件类型不支持等 → 400

## 获取文档详情
- `GET /documents/{doc_id}`
  - 功能：返回文档注册信息与元数据
  - 响应：
    ```json
    {
      "record": DocumentRecord,
      "meta": {
        "keywords": ["..."],
        "graph": {"nodes": [...], "edges": [...]},
        "mindmap": {...},
        "images": ["..."],
        "summary": "..."
      }
    }
    ```
  - 文档不存在 → 404

## 获取关键词
- `GET /documents/{doc_id}/keywords`
  - 响应：`{"keywords": [...]}`；若元数据缺失 → 404

## 获取知识图谱/思维导图
- `GET /documents/{doc_id}/graph`
  - 响应：`{"graph": {"nodes": [...], "edges": [...]}, "mindmap": {...}}`
  - 元数据缺失 → 404

## RAG 问答
- `POST /query`
  - Content-Type：`application/json`
  - 请求体：`{"query": "<问题文本>", "top_k": 4}`（`top_k` 选填，默认 4）
  - 行为：在向量库中相似度检索 → 将片段传入 LLM 生成回答
  - 响应：
    ```json
    {
      "answer": "...",
      "sources": [
        {
          "content": "...",
          "metadata": {"doc_id": "...", "source": "<原文件名>", "chunk": 0}
        }
      ]
    }
    ```
  - 若向量库为空：`sources` 为空，答案可能退化为模型自答

## 调用示例
```bash
# 上传
curl -X POST http://localhost:8000/documents \
  -F "file=@/path/paper.pdf" \
  -F "tags=LLM,经济学" \
  -F "metadata={\"source\":\"local\"}"

# 列表
curl http://localhost:8000/documents

# 关键词 / 图谱
curl http://localhost:8000/documents/{doc_id}/keywords
curl http://localhost:8000/documents/{doc_id}/graph

# 问答
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "GDP 与能源消耗的关系？", "top_k": 4}'
```
