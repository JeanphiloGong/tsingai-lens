# Evaluation Application Layer

This package owns collection-bound quality evaluation over existing Lens
artifacts.

## Scope

- registering gold answers for a collection
- freezing Core artifacts into prediction snapshots
- scoring Core and future Goal outputs against gold answers
- producing summary scores and failure records that can guide parser, prompt,
  schema, model, or reasoning improvements

## Boundaries

- This package does not parse source documents or rebuild collections.
- This package does not own HTTP routes or response schemas.
- Source artifacts are diagnostic inputs only; the user-facing evaluation
  target is Core or Goal output.
- Persistence details belong under `infra/persistence/`.

## Current Services

- `gold_service.py`
  Registers a versioned gold set for one collection.
- `prediction_snapshot_service.py`
  Creates Core prediction snapshots from already-persisted facts.
- `core_evaluation_service.py`
  Compares materials Core gold answers with prediction snapshots and records
  metrics plus failures.
