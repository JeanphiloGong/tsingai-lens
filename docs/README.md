# Project Docs Index

This directory is the top-level index for durable repository documentation.

Read [file-management-system.md](file-management-system.md) before adding new docs.

## Documentation Roots

This repository currently uses four documentation roots:

- `docs/` for project-wide and shared documentation
- `backend/docs/` for backend contracts, architecture, and operations notes
- `frontend/docs/` for frontend contracts and product-flow guides
- `docs/research/` for non-authoritative research notes and curated references

## Local Indexes

- [`backend/docs/README.md`](../backend/docs/README.md)
  Backend-owned docs index
- [`frontend/docs/README.md`](../frontend/docs/README.md)
  Frontend-owned docs index

## What Goes Where

| Location | Scope | Allowed content | Notes |
| --- | --- | --- | --- |
| `docs/` | Shared / project-wide | policy, RFC, ADR, architecture, cross-cutting guides, research notes | Do not use as a dumping ground for random files |
| `backend/docs/` | Backend domain | API specs, backend architecture, runbooks, backend RFCs and ADRs | Backend durable knowledge lives here |
| `frontend/docs/` | Frontend domain | product-flow guides, frontend specs, frontend RFCs and ADRs | Frontend durable knowledge lives here |
| `docs/research/` | External domain context | research notes, literature summaries, curated external references | Not the source of truth for implementation behavior |

## Current Classified Docs

- [`backend/docs/api.md`](../backend/docs/api.md)
  Active backend API spec and current source of truth for the public API surface
- [`frontend/docs/frontend-plan.md`](../frontend/docs/frontend-plan.md)
  Active frontend same-origin integration guide
- [`docs/materials_optimize.md`](materials_optimize.md)
  Legacy research note; migrate into `docs/research/` when touched

## Legacy Exceptions To Clean Up

- Legacy research PDFs still live under `docs/paper/`; keep them non-authoritative
  and move new research notes to `docs/research/`.
- A sensitive operational note still exists under the root docs tree; it should
  be removed from repository docs and moved to proper secret storage.

## Placement Rules

- New durable docs must have a clear home before they are added.
- New formal docs should follow the metadata rules in [file-management-system.md](file-management-system.md).
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
