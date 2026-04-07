# Project Docs Index

This directory is the top-level index for durable repository documentation.

Read [documentation governance](05-policies/documentation-governance.md) before
adding new docs.

## Documentation Roots

This repository currently uses four documentation roots:

- `docs/` for project-wide and shared documentation
- `backend/docs/` for backend contracts, architecture, and operations notes
- `frontend/docs/` for frontend contracts and product-flow guides
- `docs/research/` for non-authoritative research notes and curated references

## Root Layout

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

The root `docs/` tree is for shared project documents. Backend- and
frontend-owned source-of-truth documents stay in their module-local `docs/`
roots.

## Local Indexes

- [`backend/docs/README.md`](../backend/docs/README.md)
  Backend-owned docs index
- [`frontend/docs/README.md`](../frontend/docs/README.md)
  Frontend-owned docs index

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
| `backend/docs/` | Backend domain | API specs, backend architecture, runbooks, backend RFCs and ADRs | Backend durable knowledge lives here |
| `frontend/docs/` | Frontend domain | product-flow guides, frontend specs, frontend RFCs and ADRs | Frontend durable knowledge lives here |
| `docs/research/` | External domain context | research notes, literature summaries, curated external references | Not the source of truth for implementation behavior |
| `docs/paper/` | Supporting assets | PDFs and other reference binaries | Asset-only, not source of truth |

## Current Classified Docs

- [`docs/05-policies/documentation-governance.md`](05-policies/documentation-governance.md)
  Active repository documentation governance policy
- [`backend/docs/api.md`](../backend/docs/api.md)
  Active backend API spec and current source of truth for the public API surface
- [`frontend/docs/frontend-plan.md`](../frontend/docs/frontend-plan.md)
  Active frontend same-origin integration guide
- [`docs/research/materials-optimize.md`](research/materials-optimize.md)
  Active research note retained as non-authoritative background material

## Legacy Exceptions To Clean Up

- Legacy research PDFs still live under `docs/paper/`; keep them non-authoritative
  and move new research notes to `docs/research/`.
- A sensitive operational note still exists under the root docs tree; it should
  be removed from repository docs and moved to proper secret storage.

## Placement Rules

- New durable docs must have a clear home before they are added.
- New formal docs should follow the metadata rules in [documentation governance](05-policies/documentation-governance.md).
- Secrets, passwords, tokens, and other credentials must never be stored under any docs directory.
- Large binary assets should not be dropped into `docs/` root. If they must live in the repo, place them under a dedicated research asset folder and make their purpose explicit.
- New files should not be added under legacy root-level buckets that do not have a clear governance rule.

## Authoring Rule Of Thumb

- If the file explains current system behavior or a stable contract, it belongs in repo docs.
- If the file tracks work, scope, or delivery progress, it belongs in an issue.
- If the file only explains a local implementation detail, keep it near the code as a comment or module-level docstring.

## Adoption Rule

- Apply the governance rules to all new formal docs now.
- Keep docs-root indexes current when a governed doc root changes.
- Upgrade touched high-value docs incrementally during normal work.
