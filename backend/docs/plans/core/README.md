# Core Plans

This family owns backend plans for the Core research-fact backbone: artifact
stabilization, parsing and evidence quality, traceback reviewability, and
domain-semantic backfill.

## Reading Order

- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
  Earlier stabilization wave for the shared parsing seam
- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
  Current Core quality hardening wave
- [`claim-traceback-navigation-implementation-plan.md`](claim-traceback-navigation-implementation-plan.md)
  Core traceback vertical slice for reviewable evidence grounding
- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
  Backfill stable Core research semantics into `backend/domain/`

## Boundary Rule

Keep artifact-quality and research-semantic work here. If a wave primarily
changes graph, reports, or protocol as downstream views, move it to
`../derived/`.
