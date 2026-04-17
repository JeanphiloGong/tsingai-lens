# Backend Indexing Application Node

This node owns backend indexing orchestration between collection files, the
GraphRAG engine, and collection-facing artifact readiness.

## Scope

- `index_task_runner.py`
- `task_service.py`

## Responsibilities

- create and update index task records
- load collection-specific indexing config
- invoke GraphRAG indexing
- run the Lens v1 post-index backbone in order:
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`
- publish collection and artifact readiness state after execution

## Boundary

This node owns orchestration, not extraction semantics.

It may call:

- `application/documents/`
- `application/evidence/`
- `application/comparisons/`
- `application/protocol/`
- `application/workspace/`
- `retrieval/`

It should not reimplement:

- document profiling heuristics
- evidence extraction rules
- comparison normalization logic
- protocol search or SOP assembly

## Important Files

- `index_task_runner.py`
  Main task orchestration entry for real collection indexing
- `task_service.py`
  Task persistence and task-state lifecycle

## Upstream / Downstream

- upstream inputs:
  collection files, task creation requests, backend config
- downstream artifacts:
  `document_profiles.parquet`, `evidence_cards.parquet`,
  `comparison_rows.parquet`, optional `protocol_steps.parquet`
- downstream APIs:
  task status, workspace readiness, documents/evidence/comparisons endpoints

## Related Docs

- [`../../docs/architecture/domain-architecture.md`](../../docs/architecture/domain-architecture.md)
- [`../../docs/plans/evidence-first-parsing-plan.md`](../../docs/plans/evidence-first-parsing-plan.md)
- [`../README.md`](../README.md)
