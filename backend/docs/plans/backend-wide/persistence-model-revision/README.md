# Persistence Model Revision Records

## Purpose

This topic family retains durable decision evidence from the completed backend
persistence revision. It does not duplicate implementation sequencing or task
status from the canonical issues.

The revision established PostgreSQL as the structured runtime authority,
object storage as the immutable-byte authority, and local files as rebuildable
scratch. The accepted retrieval gate stopped before adding a vector index.

## Authority Boundary

- [`../../../architecture/persistence-model.md`](../../../architecture/persistence-model.md)
  owns the stable implemented persistence model
- [issue #232](https://github.com/JeanphiloGong/tsingai-lens/issues/232)
  owns the revision's execution history and child-issue map
- [issue #245](https://github.com/JeanphiloGong/tsingai-lens/issues/245)
  owns final closure evidence and human acceptance
- [`retrieval-decision.md`](retrieval-decision.md) retains the accepted
  no-pgvector decision evidence
- shared product semantics remain owned by the repository-level RFCs
- stable HTTP behavior remains owned by `backend/docs/specs/api.md`

## Reading Order

- [`../../../architecture/persistence-model.md`](../../../architecture/persistence-model.md)
  Stable authority, identity, relationship, lifecycle, and deletion contract.
- [`retrieval-decision.md`](retrieval-decision.md)
  Measured retrieval result and the accepted decision not to add pgvector.
- [issue #232](https://github.com/JeanphiloGong/tsingai-lens/issues/232)
  Historical sequencing, delivery slices, and linked acceptance records.

## Related Docs

- [`../../../architecture/application-layer-boundary.md`](../../../architecture/application-layer-boundary.md)
- [`../../../architecture/overview.md`](../../../architecture/overview.md)
- [`../../../../infra/persistence/README.md`](../../../../infra/persistence/README.md)
- [`../../../../../docs/decisions/rfc-comparable-result-substrate-and-materials-database-direction.md`](../../../../../docs/decisions/rfc-comparable-result-substrate-and-materials-database-direction.md)
- [`../../../../../docs/decisions/rfc-research-objective-first-product-flow.md`](../../../../../docs/decisions/rfc-research-objective-first-product-flow.md)
