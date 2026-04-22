# Project Docs

This directory is the shared documentation landing page for repository-level
knowledge.

Use it when the question spans backend and frontend, defines product meaning,
or establishes a cross-module contract. Module-local implementation detail
belongs with the owning module.

Read [documentation governance](governance.md) before adding or relocating
shared docs.

## Shared Docs Model

This repository uses an ownership-first documentation model:

- root `docs/` owns shared or cross-module knowledge only
- `backend/README.md` and `frontend/README.md` are the primary module entry
  pages
- `backend/docs/` and `frontend/docs/` hold formal module-owned docs
- narrower code-owned seams may use local `README.md` files for purpose and
  navigation
- `docs/research/` holds non-authoritative research context and supporting
  assets

## Shared Layout

```text
docs/
├─ README.md
├─ governance.md
├─ overview/
├─ architecture/
├─ contracts/
├─ decisions/
└─ research/
```

Supporting research binaries live under `docs/research/assets/`.

## Start Here

- [`overview/system-overview.md`](overview/system-overview.md)
  Shared system overview and ownership map
- [`contracts/lens-v1-definition.md`](contracts/lens-v1-definition.md)
  Lens v1 product boundary and primary acceptance surface
- [`architecture/lens-v1-architecture-boundary.md`](architecture/lens-v1-architecture-boundary.md)
  Shared evidence-first and comparison-first architecture boundary
- [`governance.md`](governance.md)
  Shared placement and authorship rules for repo docs
- [`../backend/README.md`](../backend/README.md)
  Backend module entry page
- [`../frontend/README.md`](../frontend/README.md)
  Frontend module entry page

## Reading Paths By Intent

- Product direction and Lens identity:
  start at the repo root `README.md`, then read
  [`overview/lens-mission-positioning.md`](overview/lens-mission-positioning.md),
  [`contracts/lens-v1-definition.md`](contracts/lens-v1-definition.md), and
  [`architecture/lens-v1-architecture-boundary.md`](architecture/lens-v1-architecture-boundary.md),
  then
  [`decisions/rfc-comparison-result-document-product-flow.md`](decisions/rfc-comparison-result-document-product-flow.md),
  then
  [`decisions/rfc-comparable-result-substrate-and-materials-database-direction.md`](decisions/rfc-comparable-result-substrate-and-materials-database-direction.md)
- Shared system understanding:
  start with [`overview/system-overview.md`](overview/system-overview.md), then
  move to the relevant module entry page
- Shared contracts:
  start with [`contracts/lens-v1-definition.md`](contracts/lens-v1-definition.md)
  and
  [`contracts/lens-core-artifact-contracts.md`](contracts/lens-core-artifact-contracts.md)
- Historical or proposed shared decisions:
  use docs under [`decisions/`](decisions/)
- Backend implementation and API:
  start with [`../backend/README.md`](../backend/README.md), then
  [`../backend/docs/README.md`](../backend/docs/README.md), then the owning
  backend submodule `README.md`
- Frontend workspace behavior:
  start with [`../frontend/README.md`](../frontend/README.md), then
  [`../frontend/docs/frontend-plan.md`](../frontend/docs/frontend-plan.md), then
  route-family docs under `frontend/src/routes/`
- Research context only:
  use [`research/README.md`](research/README.md) and treat that subtree as
  non-authoritative background material

## What Goes Where

| Location | Scope | Allowed content | Notes |
| --- | --- | --- | --- |
| `docs/governance.md` | Shared / project-wide | documentation governance and placement policy | Primary rule page for shared docs |
| `docs/overview/` | Shared / project-wide | system overview, long-lived product framing, contributor orientation | Start here for cross-module understanding |
| `docs/architecture/` | Shared / project-wide | current shared architecture and current-state boundary docs | Cross-module design only |
| `docs/contracts/` | Shared / project-wide | stable shared product and artifact contracts | Shared source of truth |
| `docs/decisions/` | Shared / project-wide | RFCs, ADRs, and postmortems | Prefix filenames with `rfc-`, `adr-`, or `postmortem-` |
| `docs/research/` | External domain context | research notes, literature summaries, curated references | Not implementation authority |
| `docs/research/assets/` | Supporting assets | PDFs and other reference binaries | Asset-only, not source of truth |
| `backend/README.md` | Backend module | backend purpose, boundaries, and doc navigation | Primary backend entry page |
| `frontend/README.md` | Frontend module | frontend purpose, boundaries, and doc navigation | Primary frontend entry page |
| `<node>/README.md` | Backend / frontend submodule | node purpose, boundary, and local navigation | Use only at real code-owned seams |
| `backend/docs/` | Backend domain | formal backend specs, architecture docs, runbooks, ADRs | Module-owned formal docs |
| `frontend/docs/` | Frontend domain | formal frontend guides, specs, architecture docs, ADRs | Module-owned formal docs |

## Current Shared Docs

Overview:

- [`overview/system-overview.md`](overview/system-overview.md)
- [`overview/lens-mission-positioning.md`](overview/lens-mission-positioning.md)

Architecture:

- [`architecture/lens-v1-architecture-boundary.md`](architecture/lens-v1-architecture-boundary.md)
- [`architecture/graph-surface-current-state.md`](architecture/graph-surface-current-state.md)
- [`architecture/paper-facts-and-comparison-current-state.md`](architecture/paper-facts-and-comparison-current-state.md)

Contracts:

- [`contracts/lens-v1-definition.md`](contracts/lens-v1-definition.md)
- [`contracts/lens-core-artifact-contracts.md`](contracts/lens-core-artifact-contracts.md)

Decisions:

- [`decisions/rfc-evidence-first-literature-parsing.md`](decisions/rfc-evidence-first-literature-parsing.md)
- [`decisions/rfc-lens-agent-era-positioning.md`](decisions/rfc-lens-agent-era-positioning.md)
- [`decisions/rfc-paper-facts-primary-domain-model.md`](decisions/rfc-paper-facts-primary-domain-model.md)
- [`decisions/rfc-comparable-result-substrate-and-materials-database-direction.md`](decisions/rfc-comparable-result-substrate-and-materials-database-direction.md)
- [`decisions/rfc-comparison-result-document-product-flow.md`](decisions/rfc-comparison-result-document-product-flow.md)

Research:

- [`research/README.md`](research/README.md)
- [`research/materials-optimize.md`](research/materials-optimize.md)

## Placement Rules

- New shared docs must have a clear home before they are added.
- Use the lowest common ancestor of the behavior or ownership seam.
- Do not put backend- or frontend-local implementation detail in root `docs/`.
- Prefer `<node>/README.md` for node purpose and navigation before adding a
  local `docs/README.md`.
- Add `<node>/docs/README.md` only when that subtree needs a real secondary
  index.
- Create a new top-level shared bucket only when multiple durable docs and a
  distinct reading path justify it.
- Keep the repo root `README.md` lightweight and point readers here for the
  shared docs map.
- Run `python3 scripts/check_docs_governance.py` when changing governed docs or
  docs-related workflow files.
