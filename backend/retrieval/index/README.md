# Retrieval Index Workflows

This node owns index-time transformations that convert documents into graph and
related retrieval artifacts.

## Scope

- `workflows/`
- `operations/`
- `update/`
- `input/`
- `text_splitting/`

## Responsibilities

- load source documents and text units
- build graph-oriented outputs
- support full and incremental index workflows
- persist the artifacts consumed by downstream backend features
