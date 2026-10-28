# Persistence Infrastructure

This node owns database connections, ORM tables, shared transactions, file
workspaces, and object storage. Concrete SQL repositories live in
[`repositories/`](../../repositories/README.md). The authoritative
identity model is [`../../docs/architecture/persistence-model.md`](../../docs/architecture/persistence-model.md).

## Runtime Boundary

- PostgreSQL owns structured current state and versioned Objective analyses.
- Object storage owns uploaded and extracted bytes.
- Local output and cache paths are disposable scratch.
- Alembic is the only runtime schema-change path.
- Test doubles live under `tests/support/`, outside runtime infrastructure.

`database.py` exposes the native `AsyncSessionLocal` factory with
`expire_on_commit=False`. `main.py` creates one SQLAlchemy `AsyncEngine` during
startup and calls `AsyncSessionLocal.configure(bind=engine)` before bootstrap.
Imports do not create engines; startup failure and normal shutdown dispose the
owned engine. The process uses one database binding, so overlapping runtimes
cannot configure different databases in the same process.

Standalone reads create a task-local session with `AsyncSessionLocal() as db`;
writes add `db.begin()`. Application operations that publish several related
records open one transaction and pass a required `db: AsyncSession` to all
participants. No optional transaction scope or transaction factory wrapper is
maintained. Test fixtures replace the factory at each consumer with an isolated
native test factory, without rebinding a running application's factory.

## Current Aggregate Ownership

- `CollectionRepository`: `Collection -> current Documents`, including
  file metadata and preparation state.
- `PipelineRunRepository`: observable Collection- or Document-scoped
  execution and nested node telemetry in one row.
- `SourceArtifactRepository`: the current Source aggregate for each
  Document, stored in the Source section of `document_preparations`.
- `DocumentProfileRepository`: one current profile per Document,
  stored in `document_preparations.profile_json` with its own input fingerprint.
- `PaperMapRepository`: reads and writes the embedded Paper Map fields
  on `document_preparations`, after a profile exists.
- `ObjectiveRepository`: Collection discovery fields, Objective records,
  and analysis lifecycle metadata. Automatic scientific facts belong to the
  PaperExperiment, ObjectiveExperimentSelection, ComparisonGroup, and Finding
  repositories; authored snapshots remain in the analysis payload.
- `ChatRepository`: Agent sessions, messages, tool calls, embedded
  results, and approval decisions.
- `FindingReviewRepository`, `ExperimentPlanRepository`, and
  `EvaluationRepository`: their named downstream records.

## Objective Aggregate

```text
collections.discovery_*
research_objectives
  -> objective_analyses
     -> execution metadata and authored snapshots
  -> paper_experiment revisions
  -> objective_experiment_selections
  -> optional comparison_groups
  -> findings
```

Discovery and each analysis store exact `document_inputs`, where every item is
`document_id + preparation_fingerprint`. Retry allocates a new analysis version.
Only a complete succeeded version advances the published pointer; failure never
hides the prior published version.

Each preparation producer owns its section. Updating a Profile cannot relabel
the current Source fingerprint, and Collection status updates cannot rewrite
artifact provenance. A profile without a known input fingerprint remains
unversioned; a preparation row without a Source artifact is not a parsed Source.

SQLAlchemy models own storage shape, domain records own scientific invariants,
and Pydantic models own HTTP payloads. Concrete repository classes, SQL,
mappings and dedicated query results live together in
[`repositories/`](../../repositories/README.md).
Repositories return those results or domain objects, never ORM rows or HTTP
response models. Do not add a generic repository, storage
selector, compatibility wrapper, dual write, schema probe, or fallback store.
