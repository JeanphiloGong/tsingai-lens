# Persistence Model Revision

## Purpose

This topic family owns the backend implementation plan for replacing scattered
file metadata and handwritten SQLite persistence with one explicit relational
authority, durable binary-object ownership, versioned build lineage, and an
optional traceable vector index.

The work spans collection, Source, Core, Goal, evaluation, authentication, and
deployment seams, so its lowest backend-local owner is `backend-wide/`.

## Authority Boundary

- this family owns backend implementation sequencing and verification
- shared product semantics remain owned by the repository-level RFCs
- stable HTTP behavior remains owned by `backend/docs/specs/api.md`
- stable backend architecture changes must be recorded under
  `backend/docs/architecture/` when the first implementation slice is approved
- deployment changes remain approval-gated even when listed in this plan

## Reading Order

- [`implementation-plan.md`](implementation-plan.md)
  Complete dependency-ordered revision and cutover plan

## Related Docs

- [`../../../architecture/application-layer-boundary.md`](../../../architecture/application-layer-boundary.md)
- [`../../../architecture/overview.md`](../../../architecture/overview.md)
- [`../../../../infra/persistence/README.md`](../../../../infra/persistence/README.md)
- [`../../../../../docs/decisions/rfc-comparable-result-substrate-and-materials-database-direction.md`](../../../../../docs/decisions/rfc-comparable-result-substrate-and-materials-database-direction.md)
- [`../../../../../docs/decisions/rfc-research-objective-first-product-flow.md`](../../../../../docs/decisions/rfc-research-objective-first-product-flow.md)
