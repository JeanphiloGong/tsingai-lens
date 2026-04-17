# Retrieval Index Workflows

This node owns Source-side index-time normalization that converts collection
files into the minimal handoff consumed by Core.

## Scope

- `workflows/`
- `operations/`
- `input/`
- `text_splitting/`

## Responsibilities

- load source documents
- chunk and normalize text units
- normalize documents with source-level text-unit linkage
- support full index workflows
- persist the minimal artifacts consumed by downstream backend features:
  `documents.parquet` and `text_units.parquet`
