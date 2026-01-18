# TsingAI-Lens: Research Literature Intelligence Assistant

TsingAI-Lens is a self-hosted research literature system focused on batch ingestion, knowledge graph extraction, and structured retrieval for analysis and visualization.

## Overview

The system is built around a “collection” concept: each collection groups papers, indexing outputs, and exported graph artifacts. This keeps workflows predictable and makes it easy to manage multiple research topics in parallel.

## Project Goals

- Enable reliable ingestion and indexing for 10–100 papers per collection.
- Produce GraphML outputs for Gephi-based exploration.
- Provide structured retrieval for evidence-based answers.
- Keep the system self-hostable and privacy-friendly.

## Scope and Non-Goals

Scope:
- PDF/TXT ingestion and text extraction (PDF must be selectable text).
- Knowledge graph extraction and community clustering.
- Graph export for Gephi and offline analysis.

Non-goals:
- End-user chat experience (MVP focuses on backend workflows).
- OCR for scanned PDFs.
- Complex frontend visualization.

## Core Capabilities

- Collection-based ingestion and indexing.
- GraphML export for visualization tools.
- Structured retrieval with optional context evidence.

## Repository Layout

```
tsingai-lens/
├── backend/      # Backend service and retrieval workflows
├── frontend/     # Optional frontend assets
├── docs/         # Project-level documentation
└── backend/docs/ # Backend API documentation
```

## Typical User Journey (High-Level)

1) Create a collection.
2) Upload papers into the collection.
3) Run indexing once to build the graph.
4) Export GraphML for Gephi.
5) Run structured queries for insights.

## Documentation

- `backend/README.md` — backend setup and usage.
- `backend/docs/api.md` — API reference and curl examples.

## Docker Compose (Recommended)

Prereqs: Docker + Docker Compose.

```bash
cp backend/.env.example backend/.env
# edit backend/.env with your LLM settings
docker compose up --build
```

Access:
- Frontend: http://localhost:8080
- Backend API: http://localhost:8010/docs

Notes:
- Backend data is persisted under `backend/data` (mounted into the container).
- The frontend defaults to calling `http://localhost:8010` (adjust in the UI if needed).

---

# 中文说明

## 项目概述

TsingAI-Lens 是一个可私有化部署的科研文献系统，聚焦批量导入、知识图谱抽取与结构化检索，支持分析与可视化。

系统以“集合”为核心组织论文、索引结果与图谱导出，使流程清晰可控，便于并行管理多个研究主题。

## 项目目标

- 支持 10–100 篇论文稳定导入与索引。
- 产出可在 Gephi 中查看的 GraphML 图谱。
- 提供结构化检索以支持证据驱动结论。
- 支持私有化部署与数据可控。

## 范围与非目标

范围：
- PDF/TXT 导入与文本抽取（PDF 需可复制文本）。
- 知识图谱抽取与社区聚类。
- 图谱导出与离线分析。

非目标：
- 面向终端用户的聊天体验（MVP 以后端流程为主）。
- 扫描版 PDF OCR。
- 复杂前端可视化。

## 核心能力

- 基于集合的导入与索引。
- GraphML 导出用于图谱可视化。
- 结构化检索与证据上下文输出。

## 仓库结构

```
tsingai-lens/
├── backend/      # 后端服务与检索流程
├── frontend/     # 可选前端资源
├── docs/         # 项目级文档
└── backend/docs/ # 后端 API 文档
```

## 典型使用流程（高阶）

1) 创建集合。
2) 上传论文到集合。
3) 执行索引构建图谱。
4) 导出 GraphML 并在 Gephi 中查看。
5) 发起结构化检索获取洞察。

## 文档入口

- `backend/README.md` — 后端部署与使用说明。
- `backend/docs/api.md` — API 参考与示例。

## Docker Compose（推荐）

前置条件：Docker + Docker Compose。

```bash
cp backend/.env.example backend/.env
# 在 backend/.env 中填写 LLM 配置
docker compose up --build
```

访问入口：
- 前端：http://localhost:8080
- 后端 API：http://localhost:8010/docs

说明：
- 后端数据会持久化到 `backend/data`（容器内挂载）。
- 前端默认访问 `http://localhost:8010`（如需可在页面中修改）。
