# Goal Source Core Layering

## Purpose

This topic family records the backend-local work for making the
`goal / source / core / derived` business layering explicit in code structure,
delivery order, and contract follow-up.

## Authority Boundary

- [`../../../architecture/goal-core-source-layering.md`](../../../architecture/goal-core-source-layering.md)
  owns the stable backend layering description
- root `docs/` owns shared product boundary and cross-module contracts
- this family owns backend-local proposal, rollout, and follow-up material for
  the layering cut

## Reading Order

- [`proposal.md`](proposal.md)
  Why the explicit business-layer split is needed
- [`implementation-plan.md`](implementation-plan.md)
  Main backend rollout plan for the layering wave
- [`contract-follow-up.md`](contract-follow-up.md)
  Backend contract cleanup and freeze follow-up after the main cut
- [`collection-bound-short-conversation-plan.md`](collection-bound-short-conversation-plan.md)
  Current implementation plan for keeping Goal sessions as a simple
  collection-bound conversation surface before later decision-layer expansion

## Related Docs

- [`../api-surface-migration/current-state.md`](../api-surface-migration/current-state.md)
- [`../core-first-product-surface/implementation-plan.md`](../core-first-product-surface/implementation-plan.md)
- [`../../../architecture/goal-core-source-layering.md`](../../../architecture/goal-core-source-layering.md)
