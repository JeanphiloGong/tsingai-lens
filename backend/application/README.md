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
  Collection lifecycle, current Document membership, per-document preparation,
  Source loading, and task state
- [`pipeline/README.md`](pipeline/README.md)
  Shared observable pipeline records; workflow ordering stays in owning services
- [`core/README.md`](core/README.md)
  Document profiles, Paper Maps, Objectives, Evidence, and Findings
- [`evaluation/README.md`](evaluation/README.md)
  Collection-bound Core/Goal quality evaluation over existing artifacts,
  gold answers, prediction snapshots, summary scores, and failure records
- [`derived/README.md`](derived/README.md)
  Retired parallel projection boundary

## Related Docs

- [`docs/application-layer-one-shot-cutover-plan.md`](docs/application-layer-one-shot-cutover-plan.md)
  Historical application cutover background
- [`../docs/architecture/goal-core-source-layering.md`](../docs/architecture/goal-core-source-layering.md)
  Goal, Source, Core, consumer, and Derived responsibility boundaries

## Non-Goals

- raw HTTP parsing or response serialization
- low-level persistence implementations
- engine-specific runtime logic living directly in controllers
