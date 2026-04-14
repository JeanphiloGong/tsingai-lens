# TsingAI-Lens: Evidence-Grounded Literature Intelligence

TsingAI-Lens is a self-hosted literature intelligence system for paper
collections. The current Lens v1 direction is evidence-first and
comparison-first: uploaded papers are organized into document profiles,
evidence cards, and comparison rows so researchers can make traceable
cross-paper judgments faster.

Graph, report, and protocol outputs still matter, but they are supporting
surfaces rather than the primary product center.

## Current Lens V1 Direction

- Lens is a research judgment layer, not a generic paper chat shell.
- The primary Lens v1 surface is the collection comparison workspace.
- Materials science is the first proving vertical, not the permanent product
  boundary.
- Protocol generation is a conditional downstream branch for suitable corpora.
- Graph and report browsing are retained secondary surfaces.

The shared product and architecture authority lives in:

- [`docs/overview/lens-mission-positioning.md`](docs/overview/lens-mission-positioning.md)
- [`docs/contracts/lens-v1-definition.md`](docs/contracts/lens-v1-definition.md)
- [`docs/architecture/lens-v1-architecture-boundary.md`](docs/architecture/lens-v1-architecture-boundary.md)
- [`docs/contracts/lens-core-artifact-contracts.md`](docs/contracts/lens-core-artifact-contracts.md)

## Typical User Flow

1. Create a collection.
2. Upload PDF or TXT files.
3. Run indexing.
4. Inspect document profiles, evidence cards, and comparison rows.
5. Optionally browse graph, protocol, and report outputs.

## Repository Layout

```text
tsingai-lens/
├── backend/   # FastAPI backend, indexing orchestration, and backend-owned docs
├── frontend/  # SvelteKit browser application and frontend-owned docs
└── docs/      # Shared product, architecture, policy, and research context
```

## Start Here

- [`docs/README.md`](docs/README.md)
  Shared docs index, placement rules, and cross-module reading path
- [`docs/overview/lens-mission-positioning.md`](docs/overview/lens-mission-positioning.md)
  Long-lived Lens identity and positioning
- [`docs/contracts/lens-v1-definition.md`](docs/contracts/lens-v1-definition.md)
  Lens v1 product boundary and primary acceptance surface
- [`docs/overview/system-overview.md`](docs/overview/system-overview.md)
  Shared system overview and ownership map
- [`backend/README.md`](backend/README.md)
  Backend module entry page
- [`frontend/README.md`](frontend/README.md)
  Frontend module entry page

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

For backend-local operational details, see
[`backend/docs/runbooks/backend-ops.md`](backend/docs/runbooks/backend-ops.md).

## Release Images

Build and push:

```bash
docker build -t jeanphilo/tsingai-lens-backend:v0.2.2 ./backend
docker build -t jeanphilo/tsingai-lens-frontend:v0.2.2 ./frontend

docker push jeanphilo/tsingai-lens-backend:v0.2.2
docker push jeanphilo/tsingai-lens-frontend:v0.2.2
```

Run the release compose:

```bash
cp backend/.env.example backend/.env

export LENS_VERSION=v0.2.2
export LENS_HTTP_PORT=8080

docker compose -f docker-compose.release.yml up -d
```

## 中文简介

TsingAI-Lens 是一个面向论文集合的可私有化部署文献智能系统。当前
Lens v1 的主方向不是“把论文聊出来”，而是把论文组织成可追溯、可比较、
可审查的研究对象，帮助研究者更快做出跨论文判断。

当前主链路是：

- 文档画像 `document_profiles`
- 证据卡 `evidence_cards`
- 比较行 `comparison_rows`

图谱、报告和 protocol 仍然保留，但它们现在属于次级或条件性表面。

建议阅读顺序：

- [`docs/README.md`](docs/README.md)
- [`docs/overview/lens-mission-positioning.md`](docs/overview/lens-mission-positioning.md)
- [`docs/contracts/lens-v1-definition.md`](docs/contracts/lens-v1-definition.md)
- [`backend/README.md`](backend/README.md)
- [`frontend/README.md`](frontend/README.md)
