# Backend Application Layer

This node owns backend use-case orchestration between HTTP controllers and
lower-level runtime or persistence implementations.

## Scope

- application-level orchestration for Goal, Source, Core, Chat, Evaluation,
  and Derived flows
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
  and Source loading
- [`chat/README.md`](chat/README.md)
  Collection-bound Research Agent trajectory, capabilities, and write approval
- [`pipeline/README.md`](pipeline/README.md)
  Pipeline Run admission, telemetry, persistence, and recovery; scientific
  workflow ordering stays in owning services
- [`core/README.md`](core/README.md)
  Document profiles, Paper Maps, Objectives, Evidence, and Findings
- [`evaluation/README.md`](evaluation/README.md)
  Collection-bound Core/Goal quality evaluation over existing artifacts,
  gold answers, prediction snapshots, summary scores, and failure records
- [`derived/README.md`](derived/README.md)
  Retired parallel projection boundary

## Related Docs

- [`../repositories/README.md`](../repositories/README.md)
  Concrete PostgreSQL repositories used by application services

- [`../docs/architecture/goal-core-source-layering.md`](../docs/architecture/goal-core-source-layering.md)
  Goal, Source, Core, consumer, and Derived responsibility boundaries

## Non-Goals

- raw HTTP parsing or response serialization
- low-level persistence implementations
- engine-specific runtime logic living directly in controllers


## Calling Application Operations

HTTP controllers import the owning module functions. Those functions use the
concrete repository singletons defined in `repositories/*_repository.py`.
They own resource authorization and orchestrate reads, domain decisions, and
writes; callers pass the actor's user ID explicitly. Stateless operations do not
need service objects or forwarding interfaces. Runtime components with live
tasks belong to `ApplicationRuntime`; controllers obtain those components from
their own app's runtime. `ObjectiveDiscoveryService`,
`DocumentPreparationService`, `ObjectiveAnalysisService`, and `ChatSessionService`
retain their own admitted tasks and cancel and await them on shutdown. Chat keeps
its existing session operations on the runtime owner alongside its runner and
model-call observer. Feedback handlers and workers call concrete repository
instances directly; their constructors retain actual engines, handlers, builders
and execution limits. Lease renewal and terminal writes use the claimed job
worker identity and lease version.

External formats are parsed at their input boundary. An expected missing
resource, invalid decision, stale version, or write conflict is reported by its
owning operation with an explicit application exception. Repositories report
storage facts and concrete write conflicts; they do not create HTTP responses or
classify provider failures. Controllers construct response models and use
`make_api_response`; the shared exception handlers produce safe JSON failures.
