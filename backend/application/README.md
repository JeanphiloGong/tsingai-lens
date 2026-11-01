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
need service objects or forwarding interfaces. Research task submission stores work for concrete independent workers. The
preparation, discovery and analysis entry points own their actual model and file
resources, claims and lease heartbeats. Feedback and sample worker scripts also
create only their own resources and never construct the Web runtime.
Shared instances live beside their owning implementations:
`application.chat.session_service.ChatService`,
`infra.persistence.file.collection_workspace.Workspace`, and
`infra.persistence.file.object_store.Store`. `main.py` initializes these values
and the database engine at startup; importing their modules does not initialize
resources. Chat controllers call the shared Chat service directly. File-facing
application operations use the shared workspace or store internally, so HTTP
controllers do not select or pass file resources. Independent workers continue
to construct and pass their own resources where the operation requires them.
The Web lifespan cancels active Chat tasks, closes the model client, and disposes
the database engine on shutdown, including partial startup failures. Chat
preserves disconnect continuation, approval and snapshot replay. There is no
central runtime container, locator, or compatibility service.

External formats are parsed at their input boundary. An expected missing
resource, invalid decision, stale version, or write conflict is reported by its
owning operation with an explicit application exception. Repositories report
storage facts and concrete write conflicts; they do not create HTTP responses or
classify provider failures. Controllers construct response models and use
`make_api_response`; the shared exception handlers produce safe JSON failures.
