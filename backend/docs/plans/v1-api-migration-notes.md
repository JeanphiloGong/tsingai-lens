# Backend V1 API Migration Notes

## Purpose

The authoritative frontend/backend API contract now lives in
[`../specs/api.md`](../specs/api.md).

The current backend migration state now lives in
[`current-api-surface-migration-checklist.md`](current-api-surface-migration-checklist.md).

This document remains only as a historical backend-local bridge note for
earlier implementation sequencing and migration decisions behind that contract.
It should not be used as the current execution entry point.

## Backend Implications

The agreed API contract implies the following backend direction:

1. `workspace` is the primary entry surface
2. `documents/profiles` is the first new backbone resource
3. `evidence/cards` is the second new backbone resource
4. `comparisons` is the third new backbone resource
5. `protocol/*` remains a conditional downstream branch

## Original Implementation Order

The recommended backend order remains:

1. align `workspace` toward workflow-facing fields
2. repair current protocol payload fidelity
3. add `document_profiles`
4. add `evidence_cards`
5. add `comparison_rows`
6. keep protocol behind the evidence-first backbone

## Related Docs

- [`../specs/api.md`](../specs/api.md)
- [`current-api-surface-migration-checklist.md`](current-api-surface-migration-checklist.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`evidence-first-parsing-plan.md`](evidence-first-parsing-plan.md)
- [`../../../docs/contracts/lens-v1-definition.md`](../../../docs/contracts/lens-v1-definition.md)
