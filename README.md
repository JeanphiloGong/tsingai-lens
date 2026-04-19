# TsingAI-Lens

TsingAI-Lens is a self-hosted literature intelligence workspace for
researchers working across paper collections.

Reading one paper is rarely the hard part. The hard part is comparing dozens
of papers without losing track of conditions, baselines, weak evidence, and
conflicting claims. Lens turns a collection into a traceable comparison
workflow so researchers can see what is actually comparable, where the
evidence is thin, and how each important judgment maps back to the source.

Lens v1 is designed to help a researcher finish in about one hour the kind of
cross-paper comparison work that would otherwise consume most of a day, while
keeping the result grounded in original evidence and conditions.

Its backbone is `document_profiles`, `evidence_cards`, and
`comparison_rows`. Graph, report, and protocol views are downstream or
conditional surfaces, not the product center.

## What Lens Helps You Do

- compare 20-50 papers without rereading each one repeatedly
- identify which results are genuinely comparable
- spot weak-evidence claims, missing conditions, and conflict sources
- trace important judgments back to source spans and experimental context

## Product Focus

Lens v1 is not a generic paper chat shell. Its primary surface is the
collection comparison workspace. Graph, report, and protocol outputs remain
supporting surfaces and should matter only when evidence quality and corpus
suitability support them.

Materials science is the first proving vertical, but the product goal is
broader: a reusable literature-intelligence workflow for evidence-backed
research decisions.

## Quick Start

Release images are published through CI/CD. In the common case, you do not
need to build the project from source.

```bash
cp backend/.env.example backend/.env
# set LLM_BASE_URL / LLM_MODEL / LLM_API_KEY
# set EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_API_KEY

export LENS_VERSION=<release-tag>   # optional but recommended
export LENS_HTTP_PORT=8080          # optional

docker compose -f docker-compose.release.yml up -d
```

Open:

- Web UI: http://localhost:8080
- API docs: http://localhost:8080/api/docs

Runtime data is stored under `backend/data/`.

If you are developing from source instead of deploying release images, start
with [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md).

## Core Workflow

1. Create a collection.
2. Upload PDF or TXT files.
3. Run indexing.
4. Review document profiles, evidence cards, and comparison rows.
5. Use graph, report, or protocol views only when the collection is suitable.

## Repository Guide

- `backend/`: FastAPI backend, indexing pipeline, API contract, and
  backend-owned docs
- `frontend/`: SvelteKit browser app, same-origin workspace UI, and
  frontend-owned docs
- `docs/`: shared product definition, contracts, decisions, and governance

## Read More

- [`docs/README.md`](docs/README.md)
  Shared documentation landing page
- [`docs/overview/lens-mission-positioning.md`](docs/overview/lens-mission-positioning.md)
  Long-lived product mission and positioning
- [`docs/contracts/lens-v1-definition.md`](docs/contracts/lens-v1-definition.md)
  Current Lens v1 scope and success bar
- [`backend/README.md`](backend/README.md)
  Backend module entry page
- [`frontend/README.md`](frontend/README.md)
  Frontend module entry page

## 中文简介

TsingAI-Lens 是一个面向论文集合的可私有化部署文献智能工作台。

研究者真正困难的地方，通常不是读懂一篇论文，而是在几十篇论文之间做比较：
哪些结果真的可比，哪些结论证据偏弱，哪些实验条件决定了判断是否成立。Lens
要解决的就是这个问题。它把一组论文组织成可追溯、可比较、可审查的分析流程，
帮助研究者把关键判断重新落回原始证据与实验条件，而不是停留在流畅但不可追溯
的总结文本上。

Lens v1 的核心骨架是 `document_profiles`、`evidence_cards` 和
`comparison_rows`。它的目标是把原本需要大半天的跨论文比较工作，压缩到大约
一小时内完成，同时保持每个重要结论都能追溯回原文证据。

当前版本优先验证材料科学场景，但产品边界并不局限于材料领域。图谱、
报告和 protocol 仍然有价值，但它们是建立在证据充分、语料适配基础上的
次级输出，不是产品中心。

部署默认使用 CI/CD 产出的预构建镜像。常规使用不需要本地构建源码；如果
需要做源码开发，请分别查看 [`backend/README.md`](backend/README.md) 和
[`frontend/README.md`](frontend/README.md)。
