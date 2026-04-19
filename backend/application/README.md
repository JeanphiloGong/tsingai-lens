# Backend Application Layer

This node owns backend use-case orchestration between HTTP controllers and
lower-level runtime or persistence implementations.

## Scope

- application-level orchestration for Goal, Source, Core, and Derived flows
- wiring between controllers and domain or infra concerns
- collection-facing workflows that should stay testable above engine level

## Responsibilities

- coordinate business flows without leaking route concerns into services
- keep the business-layer split explicit inside the technical application layer
- consume Source handoff contracts and produce Core and Derived views

## Internal Structure

`application/` keeps the outer technical layer.
Inside it, business responsibilities are now grouped as:

- [`goal/README.md`](goal/README.md)
  Goal Brief intake and research-intent shaping
- [`source/README.md`](source/README.md)
  Collection lifecycle, Source indexing orchestration, and artifact readiness
- [`core/README.md`](core/README.md)
  Research-fact backbone generation and workspace overview assembly
- [`derived/README.md`](derived/README.md)
  Graph, reports, and protocol views derived from Core or Source artifacts

## Related Docs

- [`docs/application-layer-one-shot-cutover-plan.md`](docs/application-layer-one-shot-cutover-plan.md)
  Historical application cutover background
- [`../docs/plans/goal-source-core-business-layer-alignment-plan.md`](../docs/plans/goal-source-core-business-layer-alignment-plan.md)
  Active backend-wide package-alignment plan for Goal, Source, Core, and
  Derived

## Non-Goals

- raw HTTP parsing or response serialization
- low-level persistence implementations
- engine-specific runtime logic living directly in controllers
