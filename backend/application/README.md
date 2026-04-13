# Backend Application Layer

This node owns use-case orchestration for backend flows that sit between HTTP
entrypoints and lower-level services or engine packages.

## Scope

- current flat application services under `application/*.py`
- the target domain-packaged application layout described in
  [`../docs/architecture/domain-architecture.md`](../docs/architecture/domain-architecture.md)

## Responsibilities

- coordinate use-case execution for backend business domains
- keep orchestration explicit and testable
- shield HTTP route code from direct engine-level wiring where practical

## Current State

The current `application/` node is still in transition.

It contains a flat mix of:

- collection lifecycle services
- indexing task orchestration
- workspace assembly
- graph access
- query and reports
- protocol parsing and SOP helpers

That flat shape should not be deepened further.

## Target Direction

The target direction is domain-local packaging inside `application/`, for
example:

- `application/collections/`
- `application/goals/`
- `application/indexing/`
- `application/workspace/`
- `application/documents/`
- `application/evidence/`
- `application/comparisons/`
- `application/protocol/`

## Local Navigation

- [`collections/README.md`](collections/README.md)
  Collection lifecycle, file membership, and collection input preparation
- [`goals/README.md`](goals/README.md)
  Goal Brief / Intake today, with future Goal Consumer logic kept explicit
- [`indexing/README.md`](indexing/README.md)
  Index task orchestration and backbone execution order
- [`workspace/README.md`](workspace/README.md)
  Collection-facing workspace read model and artifact readiness summary
- [`documents/README.md`](documents/README.md)
  Document profiling, protocol suitability, and collection-level summaries
- [`evidence/README.md`](evidence/README.md)
  Claim-centered evidence-card generation and retrieval
- [`comparisons/README.md`](comparisons/README.md)
  Collection-facing comparison-row generation and comparability semantics
- [`protocol/README.md`](protocol/README.md)
  Conditional protocol branch for sections, blocks, protocol steps, search,
  and SOP drafting

## Non-Goals

- raw HTTP parsing or response formatting
- low-level persistence implementation
- ad hoc direct route-to-engine coupling
- adding more unrelated top-level `*_service.py` files into a flat namespace
