# Frontend-Facing Contract Cleanup

## Purpose

This topic family records backend-owned cleanup work for contract semantics
that the frontend consumes but should not have to reinterpret.

## Authority Boundary

- shared cross-module contract freeze work belongs in root `docs/`
- [`../../../specs/api.md`](../../../specs/api.md) owns the backend API
  contract after cleanup lands
- this family records the backend-local cleanup lineage and rollout details

## Reading Order

- [`implementation-plan.md`](implementation-plan.md)
  Backend-owned cleanup plan for frontend-consumed semantics

## Related Docs

- [`../index-to-build-contract/implementation-plan.md`](../index-to-build-contract/implementation-plan.md)
- [`../api-surface-migration/current-state.md`](../api-surface-migration/current-state.md)
- [`../goal-source-core-layering/contract-follow-up.md`](../goal-source-core-layering/contract-follow-up.md)
