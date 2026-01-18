# TsingAI-Lens Backend

This directory contains the FastAPI backend for TsingAI-Lens. It manages collection-based ingestion, indexing, knowledge graph export, and structured retrieval.

## Capabilities

- Upload PDF/TXT into collections (PDF is converted to text before indexing).
- Manage collection input files (add/list/delete).
- Run GraphRAG indexing pipelines (standard/fast).
- Export GraphML for Gephi, including evidence metadata.
- Query indexed outputs with structured retrieval.

## Tech Stack

- Python, FastAPI
- GraphRAG indexing pipeline (retrieval)
- PyMuPDF for PDF text extraction

## Project Layout

```
backend/
├── app/          # Application layer (use cases/services)
├── controllers/  # FastAPI routes (/retrieval)
├── retrieval/    # GraphRAG indexing/retrieval pipelines
├── utils/        # helpers (logging, etc.)
├── data/         # configs, collections, outputs
├── docs/         # API docs (docs/api.md)
└── tests/        # unit tests
```

## Local Development

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync

# OpenAI-compatible LLM endpoint example
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local

uvicorn main:app --reload --port 8010
```

## Core API

- POST `/retrieval/collections` - create collection
- GET `/retrieval/collections` - list collections with stats
- DELETE `/retrieval/collections/{collection_id}` - delete collection (default cannot be deleted)
- POST `/retrieval/collections/{collection_id}/files` - upload files to a collection
- GET `/retrieval/collections/{collection_id}/files` - list collection files
- DELETE `/retrieval/collections/{collection_id}/files` - delete a collection file
- POST `/retrieval/index` - run indexing on a collection
- POST `/retrieval/index/upload` - upload a file and index immediately
- POST `/retrieval/input/upload` - upload multiple files without indexing
- POST `/retrieval/query` - query indexed outputs
- GET `/retrieval/graphml` - export GraphML for Gephi

## Collection Fields

- `status`: `ready` (entities exist) / `empty` (not indexed)
- `document_count`: from `documents.parquet` or `stats.json`
- `entity_count`: from `entities.parquet`
- `updated_at`: last output artifact timestamp (fallback to `created_at`)

## Recommended Flow (MVP)

1) Optional: POST `/retrieval/collections`
2) POST `/retrieval/collections/{collection_id}/files`
3) POST `/retrieval/index`
4) GET `/retrieval/graphml`
5) POST `/retrieval/query`

## GraphML Export Parameters

- `include_community`: attach community id to nodes for Gephi coloring
- `community_id`: export a single community
- `max_nodes`: limit node count
- `min_weight`: filter relationships by weight

GraphML evidence fields (nodes and edges):
- `node_text_unit_ids`, `node_text_unit_count`
- `node_document_ids`, `node_document_titles`, `node_document_count`
- `edge_text_unit_ids`, `edge_text_unit_count`
- `edge_document_ids`, `edge_document_titles`, `edge_document_count`

## Model Configuration

Backend uses an OpenAI-compatible endpoint. Set:

- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY`

## Notes

- PDF must contain selectable text (OCR is not provided).

## References

- `backend/docs/api.md` for detailed API docs and curl examples

---

# 中文说明

## 功能说明

本目录为 TsingAI-Lens 的 FastAPI 后端，提供集合式导入、索引、知识图谱导出与结构化检索能力。

## 能力清单

- 上传 PDF/TXT 到集合（PDF 会先抽取为文本）。
- 集合文件管理（添加/列表/删除）。
- 运行 GraphRAG 索引流程（standard/fast）。
- 导出 GraphML 供 Gephi 使用，包含证据字段。
- 基于索引结果进行结构化检索。

## 技术栈

- Python、FastAPI
- GraphRAG 索引流程（retrieval）
- PyMuPDF 负责 PDF 文本抽取

## 目录结构

```
backend/
├── app/          # 应用层（use cases / services）
├── controllers/  # FastAPI 路由（/retrieval）
├── retrieval/    # GraphRAG 索引/检索流程
├── utils/        # 工具模块（日志等）
├── data/         # 配置、集合与输出目录
├── docs/         # API 文档
└── tests/        # 单元测试
```

## 本地开发

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync

# OpenAI 兼容 LLM 端点示例
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local

uvicorn main:app --reload --port 8010
```

## 核心 API

- POST `/retrieval/collections` - 创建集合
- GET `/retrieval/collections` - 列出集合与统计
- DELETE `/retrieval/collections/{collection_id}` - 删除集合（默认集合不可删）
- POST `/retrieval/collections/{collection_id}/files` - 上传集合文件
- GET `/retrieval/collections/{collection_id}/files` - 列出集合文件
- DELETE `/retrieval/collections/{collection_id}/files` - 删除集合文件
- POST `/retrieval/index` - 触发索引
- POST `/retrieval/index/upload` - 上传单文件并索引
- POST `/retrieval/input/upload` - 批量上传不索引
- POST `/retrieval/query` - 结构化检索
- GET `/retrieval/graphml` - 导出 GraphML

## 集合字段说明

- `status`：`ready`（已有实体输出）/ `empty`（未索引）
- `document_count`：来自 `documents.parquet` 或 `stats.json`
- `entity_count`：来自 `entities.parquet`
- `updated_at`：输出产物最后更新时间（缺失回退 `created_at`）

## 推荐流程（MVP）

1) 可选：POST `/retrieval/collections`
2) POST `/retrieval/collections/{collection_id}/files`
3) POST `/retrieval/index`
4) GET `/retrieval/graphml`
5) POST `/retrieval/query`

## GraphML 导出参数

- `include_community`：输出社区字段用于 Gephi 着色
- `community_id`：导出指定社区
- `max_nodes`：限制节点数量
- `min_weight`：按关系权重过滤

GraphML 证据字段（节点/边共用）：
- `node_text_unit_ids`、`node_text_unit_count`
- `node_document_ids`、`node_document_titles`、`node_document_count`
- `edge_text_unit_ids`、`edge_text_unit_count`
- `edge_document_ids`、`edge_document_titles`、`edge_document_count`

## 模型配置

后端使用 OpenAI 兼容接口，需配置：

- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY`

## 注意事项

- PDF 需可复制文本（不含 OCR）。

## 参考文档

- `backend/docs/api.md`
