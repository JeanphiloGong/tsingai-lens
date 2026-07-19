# Persistence Adapters

This node owns storage-specific repository construction and implementation.
The stable data ownership and identity contract lives in
[`../../docs/architecture/persistence-model.md`](../../docs/architecture/persistence-model.md).

## Scope

- `database.py`
- `factory.py`
- `file/`
- `memory/`
- `postgres/`
- `sqlite/`
- `mysql/`

## Responsibilities

- construct the concrete repository used by direct application callers
- keep file layout, database access, SQL, and row encoding inside infra
- map explicitly between persistence rows and domain records
- keep runtime composition visible and small

## Current Runtime

- `file/`
  Owns collection workspace directories, scratch/output paths, and immutable
  uploaded input bytes through `FileObjectStore`. It owns no structured task,
  build, artifact, collection, membership, or import state.
- `memory/`
  Direct isolated-test implementations for the collection and build
  aggregates. Neither implementation is selectable at runtime.
- `postgres/`
  Owns users, browser sessions, collection metadata, stored-object metadata,
  collection file membership, import provenance, Goal-intake handoffs, tasks,
  collection builds, stage state, artifact versions, and active-build
  selection through SQLAlchemy mappings and direct aggregate repositories.
  The application creates one engine and session factory and composes these
  repositories and services in the FastAPI lifespan.
- `sqlite/`
  Five handwritten repositories share `backend/data/lens.sqlite` for Goal
  sessions and plans, Source records, Core and Goal workflow records, and
  evaluation/review state. These remaining repositories currently create
  schema at runtime.
- `mysql/`
  Unimplemented placeholder with no active runtime selection path.

`factory.py` constructs SQLite repositories only for the remaining Goal,
Source, Core, and evaluation families. Auth, collection, and build aggregates
are composed directly in `main.py`; none has a repository factory or runtime
fallback. Source pipeline JSON and Parquet outputs live under `infra/source/`
runtime storage and are rebuildable intermediates, not a second persistence
authority.

`database.py` owns the validated synchronous SQLAlchemy engine and session
factory. The FastAPI lifespan shares this contract between auth, collection,
and build repositories and disposes its owned engine at shutdown; injected test
services remain caller-owned.

`postgres/base.py` owns declarative metadata. `postgres/models/auth.py`,
`postgres/models/collection.py`, and `postgres/models/build.py` own their
storage mappings; the matching direct repositories own explicit row/domain
mapping and short transactions.
`../../migrations/` owns the version history and is the only PostgreSQL schema
change path; repositories never create tables.

`PostgresCollectionRepository` is the single structured owner for collection
metadata, files, imports, imported-document links, and handoffs. Import
registration and collection count/status changes commit in one transaction.
Collection deletion commits relational removal before the workspace directory
is deleted. Maintained callers do not read or write collection file or import
manifest JSON and do not scan input directories as a fallback authority.

`PostgresBuildRepository` is the single structured owner for tasks, collection
builds, ordered stages, immutable artifact versions, and active-build
selection. It allocates collection-local build numbers and activates only newer
successful builds in short transactions. `MemoryBuildRepository` mirrors this
aggregate only for isolated tests. No maintained caller reads or writes task
JSON or `artifacts.json`.

## Target Boundary

Approved cutover slices replace the current owners directly:

- PostgreSQL repositories own structured mutable state.
- A single approved local object-store implementation owns immutable binary
  bytes by storage key.
- Alembic owns schema changes; repository reads never create or alter schema.
- Application services receive only the concrete aggregate repositories they
  use.

Do not add a generic repository, persistence facade, compatibility wrapper,
service locator, or runtime fallback. Update the real repository and its direct
callers in the same cutover slice.
