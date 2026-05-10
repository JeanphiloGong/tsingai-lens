# Persistence Adapters

This node owns repository construction and persistence backend implementations
for app-layer collection, task, artifact, and Goal session state.

## Scope

- `factory.py`
- `file/`
- `memory/`
- `sqlite/`
- `mysql/`

## Responsibilities

- choose the active repository backend
- define the boundary between app-layer services and persistence
- keep storage-specific details out of higher-level orchestration code
- keep database engine details, SQL, schema creation, and row encoding inside
  infra-owned repositories

## Current Implementations

- `file/`
  Primary file-backed persistence used by the app layer
- `memory/`
  In-memory implementations for tests and isolated runs
- `sqlite/`
  SQLite-backed Goal conversation session persistence. The application layer
  depends on the Goal session repository port and does not import SQLite,
  table names, SQL, or connection details.
- `mysql/`
  Placeholder for future relational persistence work
