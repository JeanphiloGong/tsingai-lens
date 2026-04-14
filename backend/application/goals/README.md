# Goal Application Package

This package currently owns the backend-local Goal Brief / Intake entry.

## Scope

- build a minimal `research_brief`
- emit only intake-side guidance before Core execution
- create or update a seeded collection handoff
- register a `goal_brief` handoff at the collection-builder boundary
- return next-step recommendations without emitting Core artifacts

## Current Boundary

- this package is not the full Goal Consumer / Decision Layer
- current `coverage_assessment` here is only a coarse intake-side hint, not a
  final Core-grounded decision signal

## Non-Goals

- generating `document_profiles`, `evidence_cards`, or `comparison_rows`
- bypassing collection creation
- writing normalized import batches directly
- emitting protocol artifacts directly
