# Backend V1 API Contract Notes

## Purpose

The authoritative frontend/backend API contract now lives in
[`api.md`](api.md).

This document remains only as a backend-local companion note for implementation
sequencing and migration decisions behind that contract.

## Backend Implications

The agreed API contract implies the following backend direction:

1. `workspace` is the primary entry surface
2. `documents/profiles` is the first new backbone resource
3. `evidence/cards` is the second new backbone resource
4. `comparisons` is the third new backbone resource
5. `protocol/*` remains a conditional downstream branch

## Implementation Order

The recommended backend order remains:

1. align `workspace` toward workflow-facing fields
2. repair current protocol payload fidelity
3. add `document_profiles`
4. add `evidence_cards`
5. add `comparison_rows`
6. keep protocol behind the evidence-first backbone

## Related Docs

- [`api.md`](api.md)
- [`backend-domain-architecture.md`](backend-domain-architecture.md)
- [`backend-evidence-first-parsing-plan.md`](backend-evidence-first-parsing-plan.md)
- [`../../docs/40-specs/lens-v1-definition.md`](../../docs/40-specs/lens-v1-definition.md)
