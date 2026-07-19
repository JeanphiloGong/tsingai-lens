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
  Owns collection `meta.json`, `files.json`, `import_manifest.json`, uploaded
  input bytes, task JSON, and `artifacts.json`.
- `memory/`
  Test and isolated-run implementations for collection, task, and artifact
  state.
- `postgres/`
  Owns users and browser sessions through SQLAlchemy mappings and one direct
  `PostgresAuthRepository`. The application creates its engine, session factory,
  repository, and auth service in the FastAPI lifespan.
- `sqlite/`
  Five handwritten repositories share `backend/data/lens.sqlite` for Goal
  sessions and plans, Source records, Core and Goal workflow records, and
  evaluation/review state. These remaining repositories currently create
  schema at runtime.
- `mysql/`
  Unimplemented placeholder selected only by the legacy collection/task/artifact
  backend switch.

`factory.py` currently selects file, memory, or the unimplemented MySQL path
only for collection, task, and artifact repositories. It constructs SQLite
directly for the remaining Goal, Source, Core, and evaluation families. Auth is
composed directly in `main.py`; there is no auth repository factory or SQLite
fallback. Source pipeline JSON and Parquet outputs live under `infra/source/`
runtime storage and are rebuildable intermediates, not a second persistence
authority.

`database.py` owns the validated synchronous SQLAlchemy engine and session
factory. The auth lifespan uses this contract and disposes its owned engine at
shutdown; injected test services remain caller-owned.

`postgres/base.py` owns declarative metadata, `postgres/models/auth.py` owns the
two auth mappings, and `postgres/auth_repository.py` owns their direct reads and
writes. `../../migrations/` owns the version history and is the only PostgreSQL
schema change path; repositories never create tables.

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
