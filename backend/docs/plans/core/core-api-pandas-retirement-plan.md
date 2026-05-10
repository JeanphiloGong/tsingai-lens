# Core/API Pandas Retirement Plan

## Summary

This plan records the backend-local direction for removing pandas from the
Core and API runtime path while keeping Source parsing free to use pandas as a
temporary tabular processing tool.

The target boundary is:

- `domain/` has no pandas dependency
- Core services operate on domain records, repository payloads, and plain
  Python collections
- API handlers serialize domain records directly instead of receiving
  `DataFrame` projections from application services
- Source runtime may keep pandas for parser, CSV, chunking, and table-shaping
  work until a separate Source cleanup justifies replacing it
- scripts and benchmarks may keep pandas temporarily for CSV export and
  analysis, outside the browser-facing runtime path

This is a computation-model cleanup plan. The storage-model cleanup has already
moved the active Core handoff away from file artifacts and into repository
persistence.

## Context

Pandas entered the backend for a practical reason: the first Source/Core
pipeline was artifact-file oriented. Source and Core produced tabular
intermediate results, persisted those tables as files, and downstream services
loaded them back into `DataFrame` objects for filtering, grouping, joining,
deduplication, and CSV-style inspection.

That made early iteration fast, but it also blurred three concerns:

- persisted state
- in-memory table computation
- stable Core business semantics

The active direction is now different. Core facts are represented by domain
records and repository persistence. Once storage no longer depends on tabular
files, keeping pandas in Core and API services mainly preserves old table
thinking: columns become implicit contracts, JSON/list fields need repeated
normalization, and route behavior is harder to reason about from the domain
model alone.

Source parsing is a different case. PDF, CSV, text-unit, table-cell, and
chunking work is naturally tabular and sits below the Core research semantics.
Keeping pandas there for now is acceptable because it remains an execution
detail of ingestion rather than the Core business model.

## Scope

This plan covers:

- `backend/application/core/*`
- Core-facing API serialization under `backend/controllers/core/*`
- derived views that read Core facts for graph, report, protocol, or workspace
  surfaces when they currently receive Core data as `DataFrame` tables
- tests that still set up Core behavior by writing or reading tabular artifacts

This plan does not cover:

- replacing pandas inside Source parser/runtime internals
- removing pandas from one-off scripts, benchmarks, or export utilities
- changing public API response shapes
- adding compatibility adapters for old table-oriented callers

## Target Shape

Core services should use repository-backed domain records as their primary
input and output.

Examples:

- document profiles are `DocumentProfile` records, not rows in a profile table
- paper facts are held in `CoreFactSet` collections, not a dictionary of named
  `DataFrame` objects
- comparable results, collection overlays, and comparison rows are
  `ComparableResult`, `CollectionComparableResult`, and `ComparisonRowRecord`
  records
- API handlers receive serialized domain payloads or plain dictionaries from
  services, not pandas rows

Small local list/dict transformations are acceptable when they make route
responses readable. They should not recreate a generic table layer.

## Migration Steps

1. Freeze the allowed pandas boundary.

   Keep pandas in Source runtime and export scripts for now. Remove it from
   `domain/`, Core application services, Core controllers, and API-facing
   read paths.

2. Convert Core read methods to domain-first returns.

   Replace methods such as `read_document_profiles`,
   `read_paper_fact_frames`, `read_comparable_results`, and
   `read_comparison_rows` with record-oriented service methods or internal
   helpers that read from `CoreFactRepository` and return domain objects or
   serialized payloads.

3. Replace Core table projection helpers.

   Move comparison assembly and comparison-row projection away from
   `DataFrame` inputs. Use typed records and small collection helpers for
   filtering, sorting, deduplication, reassessment, and row construction.

4. Remove API row serialization.

   Controllers should call application services that already return route-ready
   payloads. Any remaining `pd.Series` or `DataFrame` assumptions in API code
   should be replaced by plain mapping or domain-record serialization.

5. Move derived Core readers to `CoreFactSet`.

   Graph, report, protocol, and workspace services should consume
   repository-backed Core records directly. Derived output artifacts can remain
   derived products, but their inputs should not require Core pandas tables.

6. Clean tests after each slice.

   Tests should populate `SqliteSourceArtifactRepository` and
   `SqliteCoreFactRepository` directly. They should not monkeypatch
   `to_parquet` or `read_parquet`, and they should not assert that Core
   runtime behavior created table files.

## Verification

The migration is complete when these checks hold:

- `backend/domain/**` has no pandas import
- `backend/application/core/**` has no pandas import
- `backend/controllers/core/**` has no pandas import
- production code under Core/API has no `DataFrame`, `Series`, `read_parquet`,
  or `to_parquet` dependency
- Source runtime remains the only production runtime area where pandas is
  allowed by design
- Core/API tests set up state through repositories and domain records
- public API response tests still pass without response-shape changes

Useful local checks:

```bash
rg -n "import pandas|from pandas|pd\\.|DataFrame|Series" backend/domain backend/application/core backend/controllers/core -g '*.py'
rg -n "read_parquet|to_parquet|\\.parquet" backend/application backend/controllers backend/domain backend/infra -g '*.py'
```

## Risks

The main risk is replacing a large table operation with scattered ad hoc list
logic. The replacement should stay small and typed: move stable semantics into
domain records, keep orchestration in application services, and avoid creating
a new generic table abstraction.

Another risk is trying to remove pandas from Source at the same time. That
would mix parser/runtime cleanup with Core model cleanup. Source pandas usage
should be evaluated separately after Core/API no longer depend on tabular
runtime semantics.
