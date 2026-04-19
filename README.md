# TsingAI-Lens: Evidence-Grounded Literature Intelligence

TsingAI-Lens is a self-hosted literature intelligence system for paper
collections. The current Lens v1 direction is evidence-first and
comparison-first: uploaded papers are organized into document profiles,
evidence cards, and comparison rows so researchers can make traceable
cross-paper judgments faster.

Graph, report, and protocol outputs still matter, but they are supporting
surfaces rather than the primary product center.

## What Lens Optimizes For

- evidence before fluent summary
- comparison before isolated paper chat
- traceability before opaque generation
- research judgment support rather than automation theater

## Lens V1 Flow

1. Create a collection.
2. Upload PDF or TXT files.
3. Run indexing.
4. Inspect document profiles, evidence cards, and comparison rows.
5. Optionally browse graph, protocol, and report outputs.

## Quick Start From Source

Prereqs: Docker + Docker Compose.

```bash
cp backend/.env.example backend/.env
# edit backend/.env with your model settings
docker compose up --build
```

Access:

- Web UI: http://localhost:8080
- Backend API docs: http://localhost:8010/api/docs
- Proxied API docs from frontend: http://localhost:8080/api/docs

For backend-local operational detail, see
[`backend/docs/runbooks/backend-ops.md`](backend/docs/runbooks/backend-ops.md).

## Repository Layout

- `backend/`
  FastAPI backend, indexing orchestration, and backend-owned docs
- `frontend/`
  SvelteKit browser application and frontend-owned docs
- `docs/`
  Shared product, architecture, contracts, decisions, and governance

## Read More

- [`docs/README.md`](docs/README.md)
  Shared docs landing page and reading paths
- [`docs/contracts/lens-v1-definition.md`](docs/contracts/lens-v1-definition.md)
  Current Lens v1 product boundary
- [`docs/overview/system-overview.md`](docs/overview/system-overview.md)
  Cross-module system overview
- [`backend/README.md`](backend/README.md)
  Backend module entry page
- [`frontend/README.md`](frontend/README.md)
  Frontend module entry page

## Release Compose

Use the release compose when running prebuilt images:

```bash
cp backend/.env.example backend/.env

export LENS_VERSION=<tag>
export LENS_HTTP_PORT=8080

docker compose -f docker-compose.release.yml up -d
```

## 中文简介

TsingAI-Lens 是一个面向论文集合的可私有化部署文献智能系统。当前
Lens v1 的主方向不是“把论文聊出来”，而是把论文组织成可追溯、可比较、
可审查的研究对象，帮助研究者更快做出跨论文判断。

主链路是 `document_profiles`、`evidence_cards` 和 `comparison_rows`；
图谱、报告和 protocol 属于次级或条件性表面。

详细文档入口在 [`docs/README.md`](docs/README.md)，模块入口在
[`backend/README.md`](backend/README.md) 和
[`frontend/README.md`](frontend/README.md)。
