# Backend Application Layer

This node owns use-case orchestration for backend flows that sit between HTTP
entrypoints and lower-level services or engine packages.

## Scope

- `query.py`
- `reports.py`

## Responsibilities

- coordinate use-case execution for browser-facing query and report flows
- keep orchestration explicit and testable
- shield HTTP route code from direct engine-level wiring where practical

## Non-Goals

- raw HTTP parsing or response formatting
- low-level persistence implementation
- ad hoc direct route-to-engine coupling
