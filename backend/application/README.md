# Backend Application Layer

This node owns use-case orchestration for backend flows that sit between HTTP
entrypoints and lower-level services or engine packages.

## Scope

- current flat application services under `application/*.py`
- the target domain-packaged application layout described in
  [`../docs/backend-domain-architecture.md`](../docs/backend-domain-architecture.md)

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
- `application/indexing/`
- `application/workspace/`
- `application/documents/`
- `application/evidence/`
- `application/comparisons/`
- `application/protocol/`

## Non-Goals

- raw HTTP parsing or response formatting
- low-level persistence implementation
- ad hoc direct route-to-engine coupling
- adding more unrelated top-level `*_service.py` files into a flat namespace
