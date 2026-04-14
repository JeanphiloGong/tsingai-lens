# Backend Workspace Application Node

This node owns the collection-facing workspace read model for Lens v1.

## Scope

- `service.py`
- `artifact_registry_service.py`

## Responsibilities

- compose collection metadata, file state, task state, and artifact readiness
- expose one collection-level workspace overview for the frontend entry surface
- derive workflow states for `documents`, `evidence`, `comparisons`, and
  `protocol`
- surface collection warnings such as review-heavy, protocol-limited, and
  uncertain-profile conditions
- publish stable navigation links into primary and conditional resources

## Boundary

This node owns collection-facing summary assembly, not artifact generation.

It may depend on:

- `application/collections/`
- `application/indexing/`
- `application/documents/`
- persistence-backed artifact registry state

It should not own:

- indexing execution
- document profiling heuristics
- evidence extraction
- comparison normalization
- protocol parsing internals

## Important Files

- `service.py`
  Builds the frontend-facing workspace overview and workflow/readiness model
- `artifact_registry_service.py`
  Tracks collection-level artifact readiness over persisted outputs

## Upstream / Downstream

- upstream inputs:
  collection records, task records, artifact registry state,
  `document_profiles` summary
- downstream consumers:
  `GET /collections/{collection_id}/workspace`, frontend entry routing, task
  polling surfaces, conditional protocol entry gating

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md)
- [`../../docs/architecture/overview.md`](../../docs/architecture/overview.md)
- [`../../../docs/contracts/lens-v1-definition.md`](../../../docs/contracts/lens-v1-definition.md)
- [`../README.md`](../README.md)
