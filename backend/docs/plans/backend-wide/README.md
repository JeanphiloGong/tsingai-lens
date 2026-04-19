# Backend-Wide Plans

This family owns backend plans whose lowest common ancestor is the backend
module itself rather than one business layer.

Use this family for:

- current-state checkpoints
- cross-layer contract freeze work
- package-alignment waves
- backend-wide closure waves
- product-surface or contract cleanup that spans Source, Core, and Derived

## Reading Order

- [`current-api-surface-migration-checklist.md`](current-api-surface-migration-checklist.md)
  Canonical current-state entry
- [`goal-source-core-business-layer-alignment-plan.md`](goal-source-core-business-layer-alignment-plan.md)
  Current code-tree alignment plan for `goal / source / core / derived`
- [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
  Parent five-layer rollout roadmap
- [`goal-core-source-contract-follow-up-plan.md`](goal-core-source-contract-follow-up-plan.md)
  Contract-freeze follow-up across the five-layer model
- [`materials-comparison-v2-plan.md`](materials-comparison-v2-plan.md)
  Backend-wide contract and closure page for the materials comparison backbone
- [`core-first-product-surface-cutover-plan.md`](core-first-product-surface-cutover-plan.md)
  Backend-wide closure page for the Core-first graph/report/product-surface cut
- [`frontend-facing-contract-cleanup-plan.md`](frontend-facing-contract-cleanup-plan.md)
  Backend-wide frontend-contract cleanup lineage

## Boundary Rule

If a plan mainly belongs to Source, Core, or Derived, keep it in that family
even when it has some neighboring impact.
