# Goal Application Package

This package currently owns the backend-local Goal Brief / Intake entry.

## Scope

- build a minimal `research_brief`
- emit only intake-side guidance before Core execution
- create or update a seeded collection handoff
- return next-step recommendations without emitting Core artifacts

## Current Boundary

- this package is not the full Goal Consumer / Decision Layer
- current `coverage_assessment` here is only a coarse intake-side hint, not a
  final Core-grounded decision signal

## Non-Goals

- generating `document_profiles`, `evidence_cards`, or `comparison_rows`
- bypassing collection creation
- emitting protocol artifacts directly
