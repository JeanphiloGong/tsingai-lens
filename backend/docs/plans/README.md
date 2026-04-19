# Backend Plans

This directory is the backend-local landing page for implementation current
state, active delivery waves, and retained lineage.

Use [../README.md](../README.md) for the backend formal-doc landing page.
Use this subtree only when you are already inside backend change work and need
wave sequencing, execution lineage, or a business-layer-local plan family.

## Plan Families

- [`backend-wide/README.md`](backend-wide/README.md)
  Cross-layer plans, current-state checkpoints, and backend-wide contract or
  rollout waves
- [`source/README.md`](source/README.md)
  Collection construction, Source runtime, parser, and Source-retirement waves
- [`core/README.md`](core/README.md)
  Core backbone stabilization, quality, traceback, and domain-semantic waves
- [`derived/README.md`](derived/README.md)
  Graph, query retirement, and other downstream derived-surface waves
- [`historical/README.md`](historical/README.md)
  Retained origin plans and superseded migration notes

## Start Here

- [`backend-wide/current-api-surface-migration-checklist.md`](backend-wide/current-api-surface-migration-checklist.md)
  Canonical backend current-state entry point
- [`backend-wide/goal-source-core-business-layer-alignment-plan.md`](backend-wide/goal-source-core-business-layer-alignment-plan.md)
  Current package-alignment authority for the `goal / source / core / derived`
  business-layer split

## Reading Paths By Intent

- Backend-wide migration state:
  start at [`backend-wide/current-api-surface-migration-checklist.md`](backend-wide/current-api-surface-migration-checklist.md),
  then move to [`backend-wide/README.md`](backend-wide/README.md)
- Source runtime and parser work:
  start at [`source/README.md`](source/README.md)
- Core quality, traceback, and domain semantics:
  start at [`core/README.md`](core/README.md)
- Graph, reports, protocol, and retired derived surfaces:
  start at [`derived/README.md`](derived/README.md)
- Historical lineage only:
  use [`historical/README.md`](historical/README.md)

## Placement Rules

- Put a plan in the lowest backend-local family that fully owns the wave.
- Use `backend-wide/` only when the wave spans multiple business layers or
  freezes backend-wide contracts.
- Use `historical/` only for pages that are intentionally retained lineage and
  are no longer the current execution entry point.
- Keep stable contracts in `../specs/`, stable architecture in
  `../architecture/`, and operations in `../runbooks/`.
