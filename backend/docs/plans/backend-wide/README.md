# Backend-Wide Plans

This family owns backend-local plan topics whose lowest common ancestor is the
backend module itself rather than `source/`, `core/`, or `derived/`.

Use this family when the work is still backend-owned but spans multiple
business layers, records backend-wide current state, or coordinates one
backend-local rollout wave across several seams.

Shared frontend/backend authority does not belong here. Put cross-module
product meaning, shared contract freeze work, and repository-level delivery
order in root `docs/`.

## Topic Families

- [`api-surface-migration/README.md`](api-surface-migration/README.md)
  Backend-local API migration current-state family
- [`goal-source-core-layering/README.md`](goal-source-core-layering/README.md)
  Proposal, rollout, and contract follow-up family for explicit
  `goal / source / core / derived` layering
- [`evidence-chain-product-surface/README.md`](evidence-chain-product-surface/README.md)
  Backend implementation family for dossier, chain, and series delivery on
  the current semantic backbone
- [`core-first-product-surface/README.md`](core-first-product-surface/README.md)
  Backend-local cutover family for the Core-first product surface shift
- [`frontend-facing-contract-cleanup/README.md`](frontend-facing-contract-cleanup/README.md)
  Backend-owned cleanup family for frontend-consumed contract semantics
- [`index-to-build-contract/README.md`](index-to-build-contract/README.md)
  Backend implementation family for the `index` to `build` vocabulary cut
- [`materials-comparison-v2/README.md`](materials-comparison-v2/README.md)
  Backend-local materials comparison direction and closure family
- [`request-id-and-extraction-observability/README.md`](request-id-and-extraction-observability/README.md)
  Backend-wide request correlation and extraction diagnostics family

## Reading Paths

- Backend migration state:
  start at [`api-surface-migration/current-state.md`](api-surface-migration/current-state.md)
- Backend layering and package alignment:
  start at [`goal-source-core-layering/README.md`](goal-source-core-layering/README.md)
- Backend evidence-chain delivery:
  start at [`evidence-chain-product-surface/README.md`](evidence-chain-product-surface/README.md)
- Backend-local materials comparison direction:
  start at [`materials-comparison-v2/README.md`](materials-comparison-v2/README.md)

## Boundary Rule

- If a plan mainly belongs to `source/`, `core/`, or `derived/`, keep it in
  that family even when it has neighboring impact.
- If the topic needs both frontend and backend to follow one shared contract,
  keep the authority in root `docs/` and let this family hold only the
  backend-owned companion material.
- Inside `backend-wide/`, prefer one topic directory per subject and let child
  filenames express role, such as `proposal.md`, `current-state.md`, or
  `implementation-plan.md`.
