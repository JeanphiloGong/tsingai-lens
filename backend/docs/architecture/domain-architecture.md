# Backend Domain Architecture

## Purpose

This document defines the target backend-local code organization for Lens v1
implementation work.

It answers:

- how backend code should be grouped by business domain
- what responsibilities belong in each backend domain
- how the current flat `application/` layout should migrate

It does not redefine the root product boundary or artifact contracts.

## Why Change

The current backend shape is workable for a small surface, but it is too flat
for the Lens v1 direction.

The main problems are:

- `application/` mixes collection lifecycle, task orchestration, workspace
  assembly, graph access, and protocol logic in one flat namespace
- transport-facing concerns and business-domain concerns are not clearly
  separated
- protocol services currently occupy too much of the parsing backbone
- frontend-facing collection workflow semantics are not clearly mirrored in code
  ownership

For Lens v1, backend code should reflect the actual business loop:

1. collections enter
2. indexing runs
3. documents are profiled
4. evidence is extracted
5. comparisons are generated
6. protocol remains a conditional branch

## Architecture Rules

- group code by business domain first, not by generic technical label
- keep HTTP parsing thin and close to route ownership
- keep use-case orchestration inside domain-local application packages
- keep shared artifact contracts in root docs, not copied into ad hoc code
- keep protocol behind documents, evidence, and comparisons
- do not introduce a catch-all `services/` layer as a second junk drawer

## Target Domain Map

### Collections

Owns collection lifecycle and file membership:

- create collection
- list collections
- read collection metadata
- upload and list files
- delete collection

### Indexing

Owns background execution and task progression:

- start indexing task
- persist task status
- expose task history
- coordinate GraphRAG and parsing post-processing

### Workspace

Owns the collection-facing summary read model:

- workspace overview
- workflow readiness summary
- collection-level warnings
- navigation links into profiles, evidence, comparisons, and protocol

### Documents

Owns document-level profiling:

- `document_profiles`
- document type classification
- protocol suitability decisions
- collection-level profile rollups

### Evidence

Owns claim-centered evidence extraction and retrieval:

- `evidence_cards`
- evidence traceback
- evidence filters and inspection

### Comparisons

Owns collection-facing comparison views:

- `comparison_rows`
- comparability judgments
- comparison warnings
- collection comparison filtering and sorting

### Protocol

Owns the conditional downstream branch:

- protocol source preparation
- section and block parsing
- protocol candidate or step derivation
- protocol search
- SOP draft generation

This domain must not be the default parsing backbone for Lens v1.

### Graph

Owns graph browsing and exports as a retained secondary surface.

### Reports

Owns report retrieval and browsing as a retained secondary surface.

### Query

Owns generic query entrypoints outside the primary Lens v1 comparison workflow.

## Target Package Layout

The target direction is:

```text
backend/
  controllers/
    collections/
      router.py
      schemas.py
    indexing/
      router.py
      schemas.py
    workspace/
      router.py
      schemas.py
    documents/
      router.py
      schemas.py
    evidence/
      router.py
      schemas.py
    comparisons/
      router.py
      schemas.py
    protocol/
      router.py
      schemas.py
    graph/
      router.py
      schemas.py
    reports/
      router.py
      schemas.py
    query/
      router.py
      schemas.py
  application/
    collections/
    indexing/
    workspace/
    documents/
    evidence/
    comparisons/
    protocol/
    graph/
    reports/
    query/
  domain/
    collections/
    indexing/
    workspace/
    documents/
    evidence/
    comparisons/
    protocol/
  infra/
    persistence/
    ingestion/
    graphrag/
```

This is a target architecture, not a requirement to rename every file in one
large refactor.

## Controller Boundary Rules

Each controller package should own one business-facing HTTP surface.

That means:

- route declaration stays with the domain package
- HTTP request parsing stays with the domain package
- HTTP response schema modules stay with the same domain package
- controllers should call one domain-local application service or orchestrator,
  not stitch together multiple unrelated domains inline

Examples:

- workspace routes should not manually assemble task, artifact, and collection
  state
- protocol routes should not decide collection suitability on their own if that
  decision belongs to document profiles
- comparison routes should not reimplement evidence normalization logic

## Application Boundary Rules

Each application domain package should own use-case orchestration for its
domain.

Examples:

- `application/workspace/`
  collection-facing summary assembly
- `application/documents/`
  document profiling generation and retrieval
- `application/evidence/`
  evidence card extraction and retrieval
- `application/comparisons/`
  comparison row generation and retrieval
- `application/protocol/`
  protocol-specific parsing, search, and SOP flows
- `application/indexing/`
  task kickoff and indexing orchestration

Application packages may depend on shared infrastructure and on upstream domain
artifacts, but they should not collapse back into one flat utility namespace.

## Immediate File Migration Shape

The current flat files can move into domain packages in waves.

### Wave 1: No-behavior-change packaging

Create domain folders and relocate current files without changing behavior:

- `application/collection_service.py`
  -> `application/collections/service.py`
- `application/task_service.py`
  -> `application/indexing/task_service.py`
- `application/index_task_runner.py`
  -> `application/indexing/index_task_runner.py`
- `application/index_run_mode_service.py`
  -> `application/indexing/run_mode_service.py`
- `application/workspace_service.py`
  -> `application/workspace/service.py`
- `application/artifact_registry_service.py`
  -> `application/workspace/artifact_registry_service.py`
- `application/graph_service.py`
  -> `application/graph/service.py`
- `application/query_service.py`
  -> `application/query/service.py`
- `application/report_service.py`
  -> `application/reports/service.py`

Protocol files should move together under one domain package:

- `application/protocol_source_service.py`
- `application/protocol_section_service.py`
- `application/protocol_block_service.py`
- `application/protocol_normalize_service.py`
- `application/protocol_validate_service.py`
- `application/protocol_extract_service.py`
- `application/protocol_pipeline_service.py`
- `application/protocol_search_service.py`
- `application/protocol_sop_service.py`
- `application/protocol_document_meta_service.py`

to:

- `application/protocol/*`

### Wave 2: Add the Lens v1 backbone packages

Introduce new domain-local packages that match the agreed Lens v1 backbone:

- `application/documents/`
- `application/evidence/`
- `application/comparisons/`

These should be added before protocol is expanded further.

### Wave 3: Rewire controllers by domain

Move flat controller modules into domain packages, for example:

- `controllers/workspace.py`
  -> `controllers/workspace/router.py`
- `controllers/protocol.py`
  -> `controllers/protocol/router.py`
- `controllers/schemas/workspace.py`
  -> `controllers/workspace/schemas.py`
- `controllers/schemas/protocol.py`
  -> `controllers/protocol/schemas.py`

The same pattern should apply to collections, indexing tasks, graph, reports,
and query.

## Migration Safety Rules

- do not mix packaging refactors with new behavior in the same first-wave move
- prefer compatibility re-export shims while imports are being updated
- preserve route paths during packaging refactors
- preserve existing tests while packages move
- add new documents, evidence, and comparison behavior only after domain seams
  exist

## Priority Order

The recommended backend order is:

1. freeze the v1 API contract
2. carve out domain packages without changing behavior
3. repair current protocol payload fidelity
4. add `documents` domain support for `document_profiles`
5. add `evidence` domain support for `evidence_cards`
6. add `comparisons` domain support for `comparison_rows`
7. push protocol behind the evidence-first backbone

## Relationship To Root Docs

This backend-local architecture exists to implement, not redefine:

- Lens mission and positioning
- Lens v1 definition
- Lens v1 architecture boundary
- Lens core artifact contracts

## Related Docs

- [`../plans/v1-api-migration-notes.md`](../plans/v1-api-migration-notes.md)
- [`overview.md`](overview.md)
- [`../plans/evidence-first-parsing-plan.md`](../plans/evidence-first-parsing-plan.md)
- [`../../../docs/30-architecture/lens-v1-architecture-boundary.md`](../../../docs/30-architecture/lens-v1-architecture-boundary.md)
- [`../../../docs/40-specs/lens-core-artifact-contracts.md`](../../../docs/40-specs/lens-core-artifact-contracts.md)
