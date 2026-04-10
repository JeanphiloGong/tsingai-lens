# Persistence Adapters

This node owns repository construction and persistence backend implementations
for app-layer collection, task, and artifact state.

## Scope

- `factory.py`
- `file/`
- `memory/`
- `mysql/`

## Responsibilities

- choose the active repository backend
- define the boundary between app-layer services and persistence
- keep storage-specific details out of higher-level orchestration code

## Current Implementations

- `file/`
  Primary file-backed persistence used by the app layer
- `memory/`
  In-memory implementations for tests and isolated runs
- `mysql/`
  Placeholder for future relational persistence work
