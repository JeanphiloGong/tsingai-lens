# Project Docs Index

This directory is the top-level index for durable repository documentation.

Read [documentation governance](05-policies/documentation-governance.md) before
adding new docs.

## Documentation Model

This repository uses an ownership-first documentation model:

- root `docs/` is the shared system-level source of truth
- `backend/README.md` is the backend module entry page
- `frontend/README.md` is the frontend module entry page
- `backend/docs/` and `frontend/docs/` hold formal module-owned docs
- node-local `README.md` files near code own submodule purpose and navigation
- `docs/research/` remains non-authoritative research context

## Shared Docs Layout

```text
docs/
├─ 05-policies/
├─ 10-rfcs/
├─ 20-adrs/
├─ 30-architecture/
├─ 40-specs/
├─ 50-guides/
├─ 60-runbooks/
├─ 70-postmortems/
├─ 90-archive/
├─ research/
└─ paper/
```

The root `docs/` tree is only for shared or cross-module knowledge. Backend-
owned and frontend-owned detail should stay with the owning module.

## Module Entry Pages

- [`backend/README.md`](../backend/README.md)
  Backend purpose, boundaries, local doc map, and submodule entry links
- [`frontend/README.md`](../frontend/README.md)
  Frontend purpose, boundaries, local doc map, and submodule entry links

## What Goes Where

| Location | Scope | Allowed content | Notes |
| --- | --- | --- | --- |
| `docs/05-policies/` | Shared / project-wide | governance and policy docs | Start here for repository-wide rules |
| `docs/10-rfcs/` | Shared / project-wide | proposed shared changes | Use for active proposals |
| `docs/20-adrs/` | Shared / project-wide | decision records | Use for accepted decisions |
| `docs/30-architecture/` | Shared / project-wide | cross-module architecture docs | Current shared design only |
| `docs/40-specs/` | Shared / project-wide | shared specs and contracts | Stable cross-module contracts |
| `docs/50-guides/` | Shared / project-wide | shared guides | Contributor and operator guidance |
| `docs/60-runbooks/` | Shared / project-wide | shared runbooks | Repeatable operational steps |
| `docs/70-postmortems/` | Shared / project-wide | postmortems | Durable incident learning |
| `docs/90-archive/` | Shared / project-wide | superseded historical docs | No current authority |
| `backend/README.md` | Backend module | backend purpose, boundaries, and doc navigation | Primary backend entry page |
| `frontend/README.md` | Frontend module | frontend purpose, boundaries, and doc navigation | Primary frontend entry page |
| `<node>/README.md` | Backend / frontend submodule | node purpose, boundary, and local navigation | Use only at real code-owned seams |
| `backend/docs/` | Backend domain | formal backend specs, architecture docs, runbooks, ADRs | Module-owned formal docs |
| `frontend/docs/` | Frontend domain | formal frontend guides, specs, architecture docs, ADRs | Module-owned formal docs |
| `docs/research/` | External domain context | research notes, literature summaries, curated external references | Not the source of truth for implementation behavior |
| `docs/paper/` | Supporting assets | PDFs and other reference binaries | Asset-only, not source of truth |

## Current Classified Docs

- [`docs/10-rfcs/evidence-first-literature-parsing.md`](10-rfcs/evidence-first-literature-parsing.md)
  Draft RFC for Lens v1 north star around evidence-grounded comparison, with
  materials as the first vertical and conditional protocol generation
- [`docs/10-rfcs/lens-agent-era-positioning.md`](10-rfcs/lens-agent-era-positioning.md)
  Draft RFC for Lens's agent-era position as a research evidence, judgment, and
  collection-memory layer rather than another generic research agent
- [`docs/30-architecture/system-overview.md`](30-architecture/system-overview.md)
  Active shared system overview
- [`docs/30-architecture/lens-v1-architecture-boundary.md`](30-architecture/lens-v1-architecture-boundary.md)
  Active shared Lens v1 evidence-first and comparison-first architecture boundary
- [`docs/40-specs/lens-v1-definition.md`](40-specs/lens-v1-definition.md)
  Active shared Lens v1 product boundary for evidence-grounded comparison
- [`docs/40-specs/lens-core-artifact-contracts.md`](40-specs/lens-core-artifact-contracts.md)
  Active shared minimum contracts for document profiles, evidence cards, and comparison rows
- [`docs/50-guides/lens-mission-positioning.md`](50-guides/lens-mission-positioning.md)
  Active shared Lens mission and long-lived product positioning
- [`docs/05-policies/documentation-governance.md`](05-policies/documentation-governance.md)
  Active repository documentation governance policy
- [`backend/docs/backend-application-layer-boundary.md`](../backend/docs/backend-application-layer-boundary.md)
  Active backend ADR for application-boundary direction
- [`backend/docs/backend-overview.md`](../backend/docs/backend-overview.md)
  Active backend module architecture overview
- [`backend/docs/api.md`](../backend/docs/api.md)
  Active backend API spec and current source of truth for the public API surface
- [`backend/docs/backend-ops.md`](../backend/docs/backend-ops.md)
  Active backend local development and operations runbook
- [`frontend/docs/frontend-plan.md`](../frontend/docs/frontend-plan.md)
  Active frontend same-origin integration guide
- [`docs/research/materials-optimize.md`](research/materials-optimize.md)
  Active research note retained as non-authoritative background material

## Legacy Exceptions To Clean Up

- Legacy research PDFs still live under `docs/paper/`; keep them non-authoritative
  and move new research notes to `docs/research/`.

## Placement Rules

- New durable docs must have a clear home before they are added.
- New formal docs should follow the authoring rules in [documentation governance](05-policies/documentation-governance.md) and stay header-free unless a workflow actually consumes metadata.
- Use the lowest common ancestor of the behavior or code ownership seam.
- Use `<node>/README.md` for node purpose and navigation before adding a local `docs/README.md`.
- Add `<node>/docs/README.md` only when that subtree needs a real secondary index.
- Secrets, passwords, tokens, and other credentials must never be stored under any docs directory.
- Large binary assets should not be dropped into `docs/` root. If they must live in the repo, place them under a dedicated research asset folder and make their purpose explicit.
- New files should not be added under legacy root-level buckets that do not have a clear governance rule.

## Authoring Rule Of Thumb

- If the file explains current system behavior or a stable contract, it belongs in repo docs.
- If the file tracks work, scope, or delivery progress, it belongs in an issue.
- If the file only explains a local implementation detail, keep it near the code as a comment or module-level docstring.

## Adoption Rule

- Apply the governance rules to all new formal docs now.
- Keep shared indexes and module entry pages current when discoverability changes.
- Upgrade touched high-value docs incrementally during normal work.
- Run `python3 scripts/check_docs_governance.py` when changing governed docs or
  docs-related workflow files.
