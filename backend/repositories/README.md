# PostgreSQL Repositories

This node owns concrete PostgreSQL queries, writes, storage mappings, and the
query results their callers need. It is a sibling of `application/`, not a set
of application ports mirrored by another repository directory.

## Follow One Saved Research Question

A researcher opens a saved question about laser power and porosity:

1. The controller parses the request and the application service checks access.
2. `ObjectiveRepository.read_objective_record()` executes the query and returns
   `StoredObjective`: the existing `ResearchObjective` plus record timestamps.
3. The service reads the active and published analysis versions. A failed new
   analysis never replaces the previously published result.
4. The controller builds the existing HTTP response from these objects.

Domain objects retain scientific rules. Application services coordinate work.
Each repository owns SQL, ORM mapping and operation-local transactions; it
returns domain objects or dedicated query results, never ORM rows or HTTP models.
Read and write methods construct their values beside the query or assignment.
An aggregate loader may query related rows, but pure row factories, shared
record codecs and object-to-dictionary round trips are not repository interfaces.
Saved canonical fields are read directly; external formats are parsed at their
actual input boundary. Domain objects retain ownership, revision and state rules.

Experiment repositories load referenced selections in the write transaction and
call `Finding.validate_experiment_support()` or
`ComparisonGroup.validate_experiment_members()` with those facts. The domain
owns independent-experiment rules; repositories retain reference, scope, version
and concurrency checks. Rejection rolls back the whole publication.

Feedback review locks, annotation digests, request identities and sequence numbers
remain transactional checks. Annotation content rules belong to the existing
domain object and review service. Model configuration errors belong to
`application/model_connections/errors.py`; database failures propagate through
the persistence path.

## Find the Owner

| File | Data and operations |
| --- | --- |
| [collection_repository.py](collection_repository.py) | Collections, Documents, storage metadata, membership and list projections |
| [source_artifact_repository.py](source_artifact_repository.py) | Source documents, trees, tables, figures and references |
| [document_profile_repository.py](document_profile_repository.py) | Current `DocumentProfile` values |
| [paper_map_repository.py](paper_map_repository.py) | Current `PaperResearchMap` values |
| [objective_repository.py](objective_repository.py) | Objectives, discovery, analysis lifecycle and authored snapshots |
| [paper_experiment_repository.py](paper_experiment_repository.py) | Immutable paper experiment revisions |
| [objective_experiment_selection_repository.py](objective_experiment_selection_repository.py) | Objective-scoped experiment selections |
| [comparison_group_repository.py](comparison_group_repository.py) | Cross-paper comparison groups |
| [experiment_finding_repository.py](experiment_finding_repository.py) | Findings referencing fixed experiment selections |
| [experiment_analysis_repository.py](experiment_analysis_repository.py) | Atomic experiment graph publication |
| [model_connection_repository.py](model_connection_repository.py) | Read-only operator-managed model connection revisions |
| [chat_repository.py](chat_repository.py) | Sessions, messages, approvals, response snapshots and model-call audit |
| [auth_repository.py](auth_repository.py) | Users and browser sessions |
| [pipeline_run_repository.py](pipeline_run_repository.py) | Pipeline execution records, nodes, telemetry and history projections |
| [analysis_job_repository.py](analysis_job_repository.py) | Analysis jobs, leases, retries and shared sample-job identities |
| [feedback_case_repository.py](feedback_case_repository.py) | Feedback cases, signals, analysis results, annotations and reviews |
| [feedback_dataset_repository.py](feedback_dataset_repository.py) | Datasets and stored metadata |
| [feedback_dataset_sample_repository.py](feedback_dataset_sample_repository.py) | Samples, actions, build jobs and immutable sample revisions |
| [feedback_dataset_export_repository.py](feedback_dataset_export_repository.py) | Export previews and immutable exports |
| [dataset_snapshot_repository.py](dataset_snapshot_repository.py) | Feedback dataset snapshots |
| [experiment_plan_repository.py](experiment_plan_repository.py) | Experiment plan revisions and their record mappings |
| [finding_review_repository.py](finding_review_repository.py) | Expert Finding feedback, curation and their record mappings |
| [evaluation_repository.py](evaluation_repository.py) | Gold sets, prediction snapshots, scores and evaluation record mappings |

## Runtime and Test Boundaries

`infra.persistence.database.AsyncSessionLocal` is the native SQLAlchemy session
factory. `main.py` creates its engine and binds the factory during startup;
importing the application does not create an engine. Repository constructors do
not accept a session factory. There is one runtime implementation per database
repository, without a separate Protocol, base class or compatibility import.

Standalone reads use `async with AsyncSessionLocal() as db:`. Standalone writes
use `async with AsyncSessionLocal() as db, db.begin():`. Each operation creates
a task-local session and constructs its result before that session closes.

Cooperating experiment operations accept a required `db: AsyncSession`. The
application operation opens the shared transaction and passes that same `db`
through the writer, graph repositories and Objective publication. Suboperations
may flush but never commit or open a second session. A failure rolls back the
complete publication event. Transaction-level advisory locks and the system
dataset savepoint retain their original scope.
Database connections, ORM tables, schema migrations and file storage stay in
[the persistence infrastructure](../infra/persistence/README.md).

Database-backed tests use these same repositories against a separate PostgreSQL
test database. There is no maintained in-memory repository implementation.
Fixtures create the required users, collections and documents before exercising
service behavior, persistence, locking, constraints and rollback.

The [ObjectStore contract](object_store.py) describes uploaded/extracted bytes,
not database rows; its existing file implementation remains infrastructure.
The [model-call observer](chat_repository.py) reports model audit events; it is
not a second Chat repository interface.

Dedicated results reuse domain values when possible: `StoredObjective`,
`StoredDataset`, `StoredCollection` and `StoredDocument` attach metadata without
copying scientific or business fields. JSON formats and HTTP schemas retain
their existing contracts. Do not add duplicate Record/DTO models or serializers
merely to mark a layer.

See [backend architecture](../docs/architecture/overview.md) and
[research-flow verification](../tests/objective-analysis-verification.md).
