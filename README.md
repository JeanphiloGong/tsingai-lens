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

```text
tsingai-lens/
├── backend/   # Backend service, retrieval engine, and backend-owned docs
├── frontend/  # Browser application and frontend-owned docs
└── docs/      # Shared project architecture, policy, and research notes
```

## Typical User Journey (High-Level)

1) Create a collection.
2) Upload papers into the collection.
3) Run indexing once to build the graph.
4) Export GraphML for Gephi.
5) Run structured queries for insights.

## Documentation

- `docs/README.md` — shared documentation index and placement guide.
- `docs/30-architecture/system-overview.md` — shared system overview.
- `docs/05-policies/documentation-governance.md` — repository documentation governance and placement policy.
- `backend/README.md` — backend module entry, boundaries, and local docs map.
- `backend/docs/api.md` — backend public API contract.
- `frontend/README.md` — frontend module entry, boundaries, and local docs map.
- `frontend/docs/frontend-plan.md` — frontend same-origin integration guide.

## Docker Compose From Source

Prereqs: Docker + Docker Compose.

```bash
cp backend/.env.example backend/.env
# edit backend/.env with your LLM settings
docker compose up --build
```

Access:
- Frontend: http://localhost:8080
- Backend API docs: http://localhost:8010/api/docs
- Proxied API docs from frontend: http://localhost:8080/api/docs

Notes:
- Backend data is persisted under `backend/data` (mounted into the container).
- The frontend Docker image now proxies backend requests through Nginx, so the web UI works from `http://localhost:8080` without manual Base URL setup.

## Docker Hub Release Images

Use the release compose file when you publish `backend` and `frontend` as separate images.

Build and push:

```bash
docker build -t jeanphilo/tsingai-lens-backend:v0.2.2 ./backend
docker build -t jeanphilo/tsingai-lens-frontend:v0.2.2 ./frontend

docker push jeanphilo/tsingai-lens-backend:v0.2.2
docker push jeanphilo/tsingai-lens-frontend:v0.2.2
```

```bash
cp backend/.env.example backend/.env

export LENS_VERSION=v0.2.2
export LENS_HTTP_PORT=8080

docker compose -f docker-compose.release.yml up -d
```

Access:
- Web UI: http://localhost:8080
- API docs through frontend: http://localhost:8080/api/docs

Release notes:
- `docker-compose.release.yml` uses `image:` instead of `build:`.
- Default image names are `jeanphilo/tsingai-lens-backend` and `jeanphilo/tsingai-lens-frontend`.
- If you mirror images to another registry or namespace, override `LENS_BACKEND_IMAGE` and `LENS_FRONTEND_IMAGE`.
- The frontend image is built for same-origin API access, so users only need the frontend entrypoint in normal use.
- Backend data still persists under `./backend/data`.

GitHub Actions automation:
- Add repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.
- Push a tag such as `v0.2.2` to trigger `.github/workflows/release-images.yml`.
- The workflow publishes both images automatically and also updates `latest` for non-prerelease tags.

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

- `docs/README.md` — 共享文档索引与存放规则。
- `docs/30-architecture/system-overview.md` — 当前系统总览。
- `docs/05-policies/documentation-governance.md` — 仓库文档治理与存放规则。
- `backend/README.md` — 后端模块入口、边界与本地文档导航。
- `backend/docs/api.md` — 后端 API 合同。
- `frontend/README.md` — 前端模块入口、边界与本地文档导航。
- `frontend/docs/frontend-plan.md` — 前端同源集成说明。

## Docker Compose（源码构建）

前置条件：Docker + Docker Compose。

```bash
cp backend/.env.example backend/.env
# 在 backend/.env 中填写 LLM 配置
docker compose up --build
```

访问入口：
- 前端：http://localhost:8080
- 后端 API 文档：http://localhost:8010/api/docs
- 通过前端反代访问 API 文档：http://localhost:8080/api/docs

说明：
- 后端数据会持久化到 `backend/data`（容器内挂载）。
- 前端 Docker 镜像已经通过 Nginx 反代后端接口，直接打开 `http://localhost:8080` 即可使用，无需首次手工配置 Base URL。

## Docker Hub 发布版

当你把前后端分别发布成两个镜像后，推荐直接使用发布版 compose 文件。

构建并推送：

```bash
docker build -t jeanphilo/tsingai-lens-backend:v0.2.2 ./backend
docker build -t jeanphilo/tsingai-lens-frontend:v0.2.2 ./frontend

docker push jeanphilo/tsingai-lens-backend:v0.2.2
docker push jeanphilo/tsingai-lens-frontend:v0.2.2
```

```bash
cp backend/.env.example backend/.env

export LENS_VERSION=v0.2.2
export LENS_HTTP_PORT=8080

docker compose -f docker-compose.release.yml up -d
```

访问入口：
- Web UI：http://localhost:8080
- 通过前端反代访问 API 文档：http://localhost:8080/api/docs

说明：
- `docker-compose.release.yml` 使用 `image:` 拉取镜像，不再依赖本地构建。
- 默认镜像名分别是 `jeanphilo/tsingai-lens-backend` 和 `jeanphilo/tsingai-lens-frontend`。
- 如果你后续迁移到别的命名空间或镜像仓库，可以覆盖 `LENS_BACKEND_IMAGE` 和 `LENS_FRONTEND_IMAGE`。
- 前端镜像按同源 API 方式构建，普通用户只需要访问前端入口即可。
- 后端数据仍会持久化到 `./backend/data`。

GitHub Actions 自动发布：
- 在仓库 Secrets 中配置 `DOCKERHUB_USERNAME` 和 `DOCKERHUB_TOKEN`。
- 推送 `v0.2.2` 这类版本 tag 后，会自动触发 `.github/workflows/release-images.yml`。
- 对正式版本 tag，workflow 会同时发布版本标签和 `latest`。
