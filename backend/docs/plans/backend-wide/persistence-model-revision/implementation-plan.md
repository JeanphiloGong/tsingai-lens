# Backend Persistence and Data Model Revision Plan

## Status

Proposed. Human review and approval are required before implementation.

## Overview

Revise Lens persistence around three explicit storage roles:

1. PostgreSQL is the authority for mutable metadata, workflow state, structured
   Source records, Core facts, goals, understandings, and evaluation records.
2. File or object storage owns immutable binary inputs, extracted media,
   downloadable exports, traces, and rebuildable runtime scratch data.
3. `pgvector` is an optional, rebuildable semantic index over canonical Source
   record identifiers. It never becomes an evidence authority.

Use SQLAlchemy 2.0 for persistence mappings, Alembic for schema migrations, and
`psycopg` for synchronous PostgreSQL access. Preserve the current HTTP contract
and evidence-first product semantics. Do not add an async database rewrite, a
generic search product, a long-lived dual-write path, or a compatibility facade.

## Planning Assumptions

- PostgreSQL becomes required for supported runtime deployments after cutover.
- Local filesystem storage remains the first object-storage implementation.
- Binary objects are addressed by stable storage keys, never domain-owned
  absolute paths.
- Existing SQLite and JSON state is imported during a controlled maintenance
  window, then retained read-only for a rollback period.
- Each data family has exactly one runtime authority after its cutover.
- Public API paths, response models, error meanings, and collection-first user
  workflows remain stable unless separately approved.
- Partial implementation phases are not release candidates.

## Non-Goals

- redesigning the frontend or public API
- turning Lens into generic paper chat or generic vector search
- adding a separate vector-database service before measured need
- putting PDFs, images, or archives into PostgreSQL
- normalizing every nested or model-specific field into a separate table
- retaining SQLite as a supported runtime fallback after cutover
- adding a dependency-injection framework or service container
- changing release or deployment files without explicit operator approval

## Current-State Findings

- Collection metadata, file manifests, import provenance, tasks, and artifact
  readiness are persisted as JSON files.
- Six handwritten SQLite repository classes share `data/lens.sqlite`; the
  current database contains 53 tables.
- Most structured tables use string identifiers without declared foreign keys.
- Core persistence exposes a broad `CoreFactRepository` and collection-wide
  `CoreFactSet`, encouraging large aggregate reads.
- `ConfirmedGoal` is stored as a Core fact even though it is Goal workflow
  state.
- Research-understanding claims and evidence links live inside one JSON payload,
  while feedback and curation live in separate tables that cannot reference
  those claims relationally.
- Source and Core builds use collection-wide delete-and-replace writes rather
  than durable build versions.
- Source runtime JSON outputs coexist with SQLite Source records even though the
  SQLite repository is documented as authoritative.
- No active vector-store implementation is present in backend runtime code;
  embedding caches and the `lancedb` dependency remain as residue.
- Generated caches, documents, images, and outputs are tracked under
  `backend/data`, mixing runtime state with maintained source.
- Database configuration includes a hard-coded password default and is not the
  authority used by current repository factories.

## Architecture Decisions

### One Authority Per Data Family

Every record family must name one authoritative store. Exports, caches,
projections, and indexes must be explicitly rebuildable from that authority.

### Relational Root And Reusable Semantics

`Collection` remains the user-facing working scope, but it must not permanently
own reusable paper semantics. The target identity chain is:

```text
User
  -> Collection
      -> CollectionDocument membership
          -> Document
              -> DocumentVersion
                  -> SourceBuild and Source records
                  -> CoreBuild and reusable paper facts

Collection
  -> ResearchObjective and objective-scoped evidence
  -> ConfirmedGoal
      -> GoalAnalysisBuild
          -> ResearchUnderstanding
              -> Claims, relations, contexts, and evidence links
```

Use an internal document identifier plus immutable content SHA-256. DOI and
other bibliographic identifiers are metadata and deduplication signals, not the
sole primary key.

### Versioned Build Lineage

Replace destructive collection-wide refresh semantics with immutable build
identities and an atomic active-build pointer:

```text
Task -> CollectionBuild -> BuildStage -> ArtifactVersion
                           |              |
                           |              -> schema/content/model versions
                           -> source/core/goal build status
```

Future Source and Core rows carry their owning build identifier. A failed build
cannot replace the last successful active build.

### ORM, Domain, And API Separation

- SQLAlchemy models define storage shape and relationships.
- Domain records define scientific meaning and invariants.
- Pydantic schemas define HTTP input and output.
- Repositories map directly between ORM and domain records.
- Do not make one class serve all three responsibilities.

### JSONB Policy

Use typed columns for identifiers, ownership, scope, lifecycle state,
timestamps, scores, fields used in filters, and relational links. Use JSONB for
variable parser metadata, locators, presentation settings, model diagnostics,
and payload fragments that are not independently queried or constrained.

Do not duplicate an entire authoritative record into a JSON payload beside the
same typed columns.

### Object Storage Policy

The database stores object metadata:

```text
storage_key, sha256, media_type, byte_size, object_kind, created_at
```

The object store holds PDFs, uploaded text, figure crops, report exports,
GraphML exports, archives, and large trace payloads. Local filesystem storage is
the first implementation. Cloud object storage is deferred until required.

### Vector Policy

Start with no separate vector service. Measure an internal text-unit retrieval
use case first. If accepted, add `pgvector` rows keyed to canonical
`SourceTextUnit` records with embedding model, dimensions, content hash, and
build version. Retrieval returns candidate IDs; authoritative text and evidence
are always loaded from relational tables.

### Runtime Composition

Create one SQLAlchemy engine and session factory at application startup.
Repositories receive that session factory; each operation owns a short session
and transaction. Background threads may share the engine/session factory but
must never share a live session. Do not introduce a DI framework.

### Cutover Policy

- no runtime dual writes
- no read fallback from PostgreSQL to SQLite or JSON files
- migration utilities are offline operator tools, not compatibility adapters
- each accepted slice updates direct callers and removes the superseded runtime
  path for that family
- old data is archived outside the active path for the agreed rollback window

## Target Storage Matrix

| Data family | Authority | Important modeling rule |
|-------------|-----------|-------------------------|
| users and auth sessions | PostgreSQL | secure hashes, expiry, ownership FKs |
| collections | PostgreSQL | user-facing working-scope root |
| collection document membership | PostgreSQL | separate collection scope from document identity |
| uploaded-file metadata and import provenance | PostgreSQL | reference immutable object keys and hashes |
| uploaded PDFs and text | object storage | immutable binary objects |
| tasks, builds, stages, progress, errors | PostgreSQL | transactional lifecycle and active-build pointer |
| Source documents and structure | PostgreSQL | document-version and Source-build lineage |
| extracted figures | object storage plus PostgreSQL metadata | bytes outside DB, trace metadata inside DB |
| reusable paper facts | PostgreSQL | document/Core-build scoped, not projection scoped |
| objectives and objective evidence | PostgreSQL | collection working scope plus reusable fact links |
| comparable results | PostgreSQL | reusable fact substrate |
| collection comparison assessment | PostgreSQL | collection-scoped projection over reusable results |
| confirmed goals | PostgreSQL | Goal-owned workflow state and objective provenance |
| research-understanding claims | PostgreSQL | stable claim IDs and relational evidence links |
| presentation and model diagnostics | PostgreSQL JSONB or trace objects | not a semantic authority |
| feedback, curation, and evaluation | PostgreSQL | foreign keys to versioned claims and predictions |
| reports and GraphML | object storage | rebuildable downloadable exports |
| runtime scratch, logs, caches | local ephemeral files | purgeable and never source controlled |
| text-unit embeddings | conditional `pgvector` | rebuildable index with canonical Source FK |

## Dependency Graph

```text
Authority contract and behavior baseline
  -> secure PostgreSQL/session foundation
      -> Alembic migration discipline
      -> supported deployment and test database
      -> object-storage boundary
          -> identity and collection root
              -> file/import metadata
              -> task/build lineage
                  -> document identity and Source records
                      -> Core facts/objectives/comparisons
                          -> Goal and understanding normalization
                              -> evaluation links
                                  -> offline import and cutover
                                      -> optional pgvector index
                                      -> final legacy cleanup
```

## Success Targets

| Target | Quality bar | Evidence required | Failure policy |
|--------|-------------|-------------------|----------------|
| one authoritative store | every data family has one documented runtime authority and no fallback read | source-of-truth matrix, dependency scan, integration tests | block |
| API compatibility | representative API status codes and response payloads remain semantically equivalent | OpenAPI diff and golden API tests | block |
| evidence traceability | every surfaced claim resolves through evidence records to a document locator and source object | migration validator and end-to-end traceback tests | block |
| relational integrity | no orphan collection, document, build, goal, claim, evidence, feedback, or curation links | PostgreSQL constraint checks and orphan audit | block |
| durable build lifecycle | failed or concurrent builds cannot replace the last successful active build | transaction and concurrency integration tests | block |
| migration completeness | IDs, record counts, canonical payload hashes, and object hashes match the accepted source snapshot | signed migration report with zero unexplained differences | block |
| rollback readiness | operator can restore the pre-cutover database and object metadata within the agreed window | rehearsed backup/restore log | block |
| performance | accepted workspace and goal reads stay within 20% of baseline p95; collection build duration stays within 15% | before/after benchmark report | block |
| vector usefulness | if implemented, top-10 recall is at least 0.90 on an approved retrieval fixture and every result is traceable | retrieval benchmark and source-resolution tests | block |
| security | no committed database credential defaults; runtime fails clearly when required configuration is absent | config tests and secret scan | block |
| repository hygiene | generated runtime data and caches are not tracked as source | Git path audit and clean fixture tests | block |

## Task List

### Phase 0: Contract And Baseline

## Task 1: Freeze The Persistence Authority Contract

**Description:** Record the current and target data families, identities,
ownership, lifecycle, JSONB policy, deletion policy, and ERD in the stable
backend architecture path before implementation begins.

**Acceptance criteria:**
- [ ] Every current JSON, SQLite, scratch, object, export, and cache family has an owner and rebuildability classification.
- [ ] The target ERD defines primary keys, foreign keys, build lineage, and collection-versus-document ownership.
- [ ] Shared RFC semantics and the public API contract remain explicitly unchanged.

**Quality target:**
- [ ] A new engineer can locate the authoritative model for any record family without tracing runtime factories.

**Verification:**
- [ ] Run `python3 scripts/check_docs_governance.py`.
- [ ] Manually review the ERD against all repository protocols and SQLite tables.

**Dependencies:** None.

**Files likely touched:**
- `backend/docs/architecture/persistence-model.md`
- `backend/docs/architecture/overview.md`
- `backend/infra/persistence/README.md`
- `backend/docs/plans/backend-wide/persistence-model-revision/README.md`

**Estimated scope:** Medium, 3-4 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `foundation-contract`; verify one accepted authority and identity contract.

## Task 2: Freeze Behavioral And Migration Baselines

**Description:** Build a synthetic, non-sensitive fixture and capture current
API, domain-record, row-count, ordering, and evidence-trace behavior before any
storage implementation changes.

**Acceptance criteria:**
- [ ] The fixture covers collection, task, Source, Core, Goal, understanding, feedback, curation, and evaluation records.
- [ ] Golden checks cover the collection build, workspace read, confirmed-goal analysis read, and source traceback flows.
- [ ] Baseline performance and data-integrity reports are reproducible without using local user data.

**Quality target:**
- [ ] Migration parity can be judged mechanically rather than by visual inspection alone.

**Verification:**
- [ ] Run the new baseline test command from `backend/`.
- [ ] Run existing focused API and repository tests against the fixture.

**Dependencies:** Task 1.

**Files likely touched:**
- `backend/tests/fixtures/persistence_revision/`
- `backend/tests/integration/test_persistence_baseline.py`
- `backend/scripts/persistence/capture_baseline.py`
- `backend/tests/unit/scripts/test_capture_persistence_baseline.py`

**Estimated scope:** Medium, 4 paths.

**Issue handoff:** `yes`, `delivery_task`, grouping key `foundation-contract`; verify a reproducible non-sensitive migration baseline.

### Checkpoint: Contract Approval

- [ ] Human approves PostgreSQL as the required relational authority.
- [ ] Human approves the permanent object-store boundary.
- [ ] Human approves the target ERD, JSONB policy, and versioned build model.
- [ ] Baseline tests and docs governance pass.
- [ ] No implementation begins until this checkpoint is accepted.

### Phase 1: PostgreSQL And Object Foundation

## Task 3: Establish Secure Database Configuration

**Description:** Add the minimal synchronous SQLAlchemy and `psycopg`
dependencies, replace scattered database fields with one validated
`DATABASE_URL`, and create one engine/session-factory module.

**Acceptance criteria:**
- [ ] Missing or malformed production database configuration fails with an actionable error.
- [ ] No credential or password default remains in maintained source.
- [ ] Engine and session lifecycle tests cover commit, rollback, and thread-safe session creation.

**Quality target:**
- [ ] Every PostgreSQL repository receives the same explicit session-factory contract.

**Verification:**
- [ ] Run `uv run pytest tests/unit/persistence/test_database.py` from `backend/`.
- [ ] Run the repository secret/config scan defined by the task.

**Dependencies:** Tasks 1-2.

**Files likely touched:**
- `backend/pyproject.toml`
- `backend/config.py`
- `backend/infra/persistence/database.py`
- `backend/tests/unit/persistence/test_database.py`

**Estimated scope:** Medium, 4 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `postgres-foundation`; verify secure shared database construction.

## Task 4: Establish Alembic Migration Discipline

**Description:** Create one SQLAlchemy declarative base and Alembic environment,
including upgrade, downgrade, and empty-database smoke verification. Runtime
repository reads must not create or alter schema.

**Acceptance criteria:**
- [ ] `alembic upgrade head` creates the expected baseline schema on an empty PostgreSQL database.
- [ ] The baseline migration downgrades cleanly before application data exists.
- [ ] New schema changes are rejected when model metadata and migrations diverge.

**Quality target:**
- [ ] Database shape is reviewable through versioned migrations rather than hidden `_ensure_schema()` calls.

**Verification:**
- [ ] Run `uv run alembic upgrade head`, `uv run alembic check`, and the migration smoke test.

**Dependencies:** Task 3.

**Files likely touched:**
- `backend/alembic.ini`
- `backend/migrations/env.py`
- `backend/migrations/script.py.mako`
- `backend/infra/persistence/postgres/base.py`
- `backend/tests/integration/persistence/test_migrations.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `postgres-foundation`; verify migration-owned schema lifecycle.

## Task 5: Provision PostgreSQL For Supported Deployments

**Description:** Add the approved PostgreSQL service, persistent volume,
healthcheck, environment contract, and operator diagnostics to the supported
deployment bundle. This task is approval-gated because it changes deployment
and runtime requirements.

**Acceptance criteria:**
- [ ] Backend startup waits for a healthy database and reports connection failures clearly.
- [ ] Database data persists across container recreation.
- [ ] Deployment docs include backup, restore, and credential-generation procedures without committed secrets.

**Quality target:**
- [ ] A self-hosted operator can start, diagnose, back up, and restore PostgreSQL without inspecting application code.

**Verification:**
- [ ] Run `docker compose --env-file deploy/.env.example -f deploy/compose.yml config` with safe test values.
- [ ] Run the approved deployment smoke and doctor commands.

**Dependencies:** Tasks 3-4 and explicit deployment approval.

**Files likely touched:**
- `deploy/compose.yml`
- `deploy/backend.env.example`
- `deploy/scripts/doctor.sh`
- `deploy/README.md`

**Estimated scope:** Medium, 4 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `postgres-foundation`; verify operable persistent PostgreSQL deployment.

## Task 6: Separate Binary Object Storage

**Description:** Replace the file-backed collection repository's mixed metadata
and byte responsibilities with one permanent object-store port and a direct
local-filesystem implementation. Do not add cloud adapters in this task.

**Acceptance criteria:**
- [ ] Upload, read, hash verification, and deletion operate through stable storage keys.
- [ ] Domain and database records no longer own absolute filesystem paths.
- [ ] Object operations reject path traversal and preserve current document-download behavior.

**Quality target:**
- [ ] Switching metadata to PostgreSQL does not require moving or duplicating PDF and image bytes.

**Verification:**
- [ ] Run object-store unit tests and existing upload/download API tests.

**Dependencies:** Task 1.

**Files likely touched:**
- `backend/domain/source/ports.py`
- `backend/infra/persistence/file/object_store.py`
- `backend/application/source/collection_service.py`
- `backend/tests/unit/persistence/test_file_object_store.py`
- `backend/tests/unit/services/test_collection_service.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `object-foundation`; verify one safe object-key boundary.

### Checkpoint: Storage Foundation

- [ ] Database and migration tests pass on real PostgreSQL.
- [ ] Object-store tests pass without database coupling.
- [ ] Deployment smoke and backup/restore rehearsal pass.
- [ ] Human confirms the permanent new abstraction is limited to the object-store port.

### Phase 2: Identity, Collection, And Build Root

## Task 7: Cut Identity And Authentication To PostgreSQL

**Description:** Replace handwritten SQLite auth persistence with SQLAlchemy
models and a PostgreSQL repository while preserving password, bootstrap,
session-expiry, and API behavior.

**Acceptance criteria:**
- [ ] User and auth-session rows have explicit uniqueness, expiry, and user foreign-key constraints.
- [ ] Existing auth service and endpoint behavior passes unchanged against PostgreSQL.
- [ ] The SQLite auth repository is removed from the runtime path in the same slice.

**Quality target:**
- [ ] Collection ownership can reference a durable relational user root.

**Verification:**
- [ ] Run auth domain, service, repository, and router tests against PostgreSQL.

**Dependencies:** Tasks 3-5.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/auth.py`
- `backend/infra/persistence/postgres/auth_repository.py`
- `backend/application/auth/session_service.py`
- `backend/migrations/versions/*_auth.py`
- `backend/tests/integration/persistence/test_postgres_auth_repository.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `relational-root`; verify PostgreSQL auth parity and integrity.

## Task 7A: Make Collection Runtime Composition Explicit

**Description:** Remove implicit `CollectionService()` construction from
application services and controller modules, then compose one shared collection
service explicitly at the FastAPI lifecycle boundary. This is a behavior-neutral
precondition for replacing the collection repository without leaving hidden
file-backed readers in the active service graph.

**Acceptance criteria:**
- [ ] Every application service that consumes collections requires an explicit
  `CollectionService` dependency.
- [ ] FastAPI owns one shared collection service and passes that exact instance
  to collection, build, workspace, Goal, document, evidence, comparison, graph,
  and research-view entry points.
- [ ] Importing the application does not construct collection persistence or
  connect to a database.
- [ ] Public collection, ownership, build, workspace, Goal, and evidence
  behavior remains baseline-equivalent.

**Quality target:**
- [ ] Collection runtime ownership is visible in one composition root before
  its persistence implementation changes.

**Verification:**
- [ ] Run focused service tests after making dependencies explicit.
- [ ] Run application import, collection ownership, collection build, and
  application-layer integration tests after centralizing runtime composition.
- [ ] Scan maintained application and controller code for implicit
  `CollectionService()` construction.

**Dependencies:** Tasks 6-7.

**Delivery slices:**
- `explicit-collection-service-dependencies`: require and update direct
  collection-service callers without changing the file-backed authority.
- `collection-runtime-composition`: construct and bind one shared collection
  service in the FastAPI lifecycle before the PostgreSQL cutover.

**Files likely touched:**
- `backend/application/**` collection consumers
- `backend/controllers/**` collection-consuming entry points
- `backend/main.py`
- focused service, router, and application integration tests

**Estimated scope:** Large, two atomic behavior-neutral slices.

**Issue handoff:** reuse #235; this work is inseparable preparation for the
relational collection root and does not create a separate product requirement.

## Task 8: Cut Collection Metadata To PostgreSQL

**Description:** Persist collection identity, ownership, name, lifecycle, counts,
and timestamps relationally while preserving collection routes and using the
object store for bytes.

**Acceptance criteria:**
- [ ] Collections reference users and enforce unique collection identity.
- [ ] Create, list, get, update, ownership-check, and delete behavior matches the baseline.
- [ ] `meta.json` is no longer read or written at runtime after this slice.

**Quality target:**
- [ ] Collection becomes the explicit relational working-scope root.

**Verification:**
- [ ] Run collection domain, service, ownership-router, and API integration tests.

**Dependencies:** Tasks 6-7A.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/collection.py`
- `backend/infra/persistence/postgres/collection_repository.py`
- `backend/application/source/collection_service.py`
- `backend/migrations/versions/*_collections.py`
- `backend/tests/integration/persistence/test_postgres_collection_repository.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `relational-root`; verify relational collection ownership and API parity.

## Task 9: Cut File Catalog And Import Provenance To PostgreSQL

**Description:** Replace `files.json` and `import_manifest.json` with normalized
file-object, import, handoff, and provenance records linked to collections and
stable object keys.

**Acceptance criteria:**
- [ ] File metadata includes object key, content hash, size, media type, source name, and upload/import provenance.
- [ ] Goal-intake handoffs and imported-document lookup preserve current behavior.
- [ ] File and import JSON manifests are no longer runtime authorities.

**Quality target:**
- [ ] Every document byte can be audited from collection membership to immutable object hash.

**Verification:**
- [ ] Run collection upload, import, goal-intake handoff, and document-source tests.

**Dependencies:** Task 8.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/collection_file.py`
- `backend/infra/persistence/postgres/collection_file_repository.py`
- `backend/application/source/collection_service.py`
- `backend/migrations/versions/*_collection_files.py`
- `backend/tests/integration/persistence/test_collection_file_provenance.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `relational-root`; verify object-backed file and provenance authority.

## Task 10: Cut Tasks And Build Lineage To PostgreSQL

**Description:** Replace file-backed task JSON and artifact-readiness JSON with
transactional task, collection-build, build-stage, artifact-version, and
active-build records.

**Acceptance criteria:**
- [ ] Task polling, progress, errors, warnings, and timestamps preserve the public contract.
- [ ] Failed builds cannot replace the previous active successful build.
- [ ] `tasks/*.json` and `artifacts.json` are no longer runtime authorities.

**Quality target:**
- [ ] Build readiness is derived from versioned build records instead of a duplicated boolean matrix.

**Verification:**
- [ ] Run task service/API tests, collection-build pipeline tests, and concurrent active-build transaction tests.

**Dependencies:** Tasks 8-9.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/build.py`
- `backend/infra/persistence/postgres/build_repository.py`
- `backend/application/source/task_service.py`
- `backend/application/source/artifact_registry_service.py`
- `backend/tests/integration/persistence/test_build_lifecycle.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `relational-root`; verify durable task and active-build lifecycle.

### Checkpoint: Relational Root

- [ ] Auth, collection, upload, import, task, and build flows pass end to end.
- [ ] No runtime read touches `meta.json`, `files.json`, `import_manifest.json`, task JSON, or `artifacts.json`.
- [ ] Foreign-key and concurrent-build tests pass.
- [ ] HTTP contract diff is empty or explicitly approved.

### Phase 3: Document Identity And Source

## Task 11: Introduce Canonical Document Versions

**Description:** Separate reusable document identity from collection membership
using `documents`, immutable `document_versions`, and `collection_documents`.
Backfill current source filenames and hashes without treating DOI as a primary
key.

**Acceptance criteria:**
- [ ] One document version can belong to multiple collections without duplicating its immutable identity.
- [ ] Version identity is based on internal ID plus content hash and records parser-relevant metadata.
- [ ] Existing collection document routes preserve collection scoping and authorization.

**Quality target:**
- [ ] Collection is a working scope, not the permanent owner of reusable paper semantics.

**Verification:**
- [ ] Run deduplication, membership, ownership, and document-download integration tests.

**Dependencies:** Tasks 9-10.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/document.py`
- `backend/infra/persistence/postgres/document_repository.py`
- `backend/application/source/collection_service.py`
- `backend/migrations/versions/*_documents.py`
- `backend/tests/integration/persistence/test_document_identity.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `source-cutover`; verify reusable document identity and collection membership.

## Task 12: Cut Source Structure To Versioned PostgreSQL Records

**Description:** Replace SQLite Source document, text-unit, block, table,
table-row, table-cell, and association persistence with build-versioned ORM
records and explicit foreign keys.

**Acceptance criteria:**
- [ ] Source rows reference document version and successful Source build.
- [ ] Text-unit, block, table, row, cell, and document associations enforce referential integrity.
- [ ] Source document tree and evidence-locator responses match baseline content and ordering.

**Quality target:**
- [ ] Every structured Source locator resolves to one immutable document version and build.

**Verification:**
- [ ] Run Source repository round-trip, parser handoff, document-tree, and traceback tests on PostgreSQL.

**Dependencies:** Task 11.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/source.py`
- `backend/infra/persistence/postgres/source_artifact_repository.py`
- `backend/infra/source/runtime/workflows/create_source_artifacts.py`
- `backend/migrations/versions/*_source_structure.py`
- `backend/tests/integration/persistence/test_postgres_source_artifacts.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `source-cutover`; verify versioned Source structure and traceback parity.

## Task 13: Cut Source References And Figure Metadata

**Description:** Move reference entries, mentions, resolutions, candidates, and
figure metadata to PostgreSQL while keeping figure bytes in object storage and
Source JSON tables as scratch-only build output.

**Acceptance criteria:**
- [ ] Reference and figure records have collection/document/build constraints and stable object links.
- [ ] Source reference APIs and figure traceback preserve behavior.
- [ ] Runtime reads no longer treat Source output JSON or global image directories as authoritative.

**Quality target:**
- [ ] Source has one structured authority and one explicit binary-object authority.

**Verification:**
- [ ] Run Source reference workflow/router tests, figure asset tests, and scratch-rebuild tests.

**Dependencies:** Task 12.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/source_reference.py`
- `backend/infra/persistence/postgres/source_reference_repository.py`
- `backend/application/source/reference_workflow_service.py`
- `backend/migrations/versions/*_source_references.py`
- `backend/tests/integration/persistence/test_source_references.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `source-cutover`; verify one Source/reference authority and object-backed figures.

### Checkpoint: Source Cutover

- [ ] A complete collection Source build succeeds on PostgreSQL.
- [ ] Source tree, table, figure, and reference traceback match the baseline.
- [ ] Zero Source orphans are reported.
- [ ] Source output JSON can be deleted and rebuilt without losing authority.

### Phase 4: Core Semantic Substrate

## Task 14: Cut Reusable Paper Facts To PostgreSQL

**Description:** Move document profiles, anchors, methods, samples, conditions,
baselines, measurements, characterization, and structure facts to ORM records
scoped by immutable document version and Core build.

**Acceptance criteria:**
- [ ] Paper facts retain stable source IDs, normalized semantics, and evidence locators.
- [ ] A failed Core build cannot replace facts from the active successful build.
- [ ] Existing fact extraction and document-facing projections match the baseline.

**Quality target:**
- [ ] Reusable paper facts are not permanently owned by one collection projection.

**Verification:**
- [ ] Run paper-fact domain, extraction, repository, and source-trace integration tests.

**Dependencies:** Tasks 10 and 12.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/paper_fact.py`
- `backend/infra/persistence/postgres/paper_fact_repository.py`
- `backend/application/core/semantic_build/paper_facts_service.py`
- `backend/migrations/versions/*_paper_facts.py`
- `backend/tests/integration/persistence/test_postgres_paper_facts.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `core-cutover`; verify reusable versioned paper facts.

## Task 15: Cut Objectives And Evidence Chains To PostgreSQL

**Description:** Move paper skims, research objectives, contexts, paper frames,
evidence routes, evidence units, and logic chains to focused ORM persistence
linked to collection scope, Core build, reusable facts, and Source locators.

**Acceptance criteria:**
- [ ] Objective-scoped records preserve question, axes, inclusion, and per-paper provenance.
- [ ] Every evidence unit and logic-chain input resolves to Source and Core records.
- [ ] Objective APIs and goal-analysis inputs match the baseline.

**Quality target:**
- [ ] Objective analysis remains evidence-first while reusing document-level facts.

**Verification:**
- [ ] Run objective extraction, repository, workspace, evidence, and logic-chain tests.

**Dependencies:** Task 14.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/objective.py`
- `backend/infra/persistence/postgres/objective_repository.py`
- `backend/application/core/semantic_build/research_objective_service.py`
- `backend/migrations/versions/*_objectives.py`
- `backend/tests/integration/persistence/test_postgres_objectives.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `core-cutover`; verify objective/evidence lineage and API parity.

## Task 16: Cut Comparable Results And Assessments To PostgreSQL

**Description:** Persist reusable comparable results separately from
collection-scoped comparison assessment and row/card projections, preserving
the shared RFC's substrate-versus-projection boundary.

**Acceptance criteria:**
- [ ] Comparable results link to reusable facts and evidence independently of collection ordering.
- [ ] Collection assessments link membership, comparability judgment, and projection state to a collection build.
- [ ] Comparison, workspace, evidence-card, and graph projections match the baseline.

**Quality target:**
- [ ] Projection rows never become the semantic source of truth.

**Verification:**
- [ ] Run comparison assembly, aggregation, workspace, graph, and API contract tests.

**Dependencies:** Tasks 14-15.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/comparison.py`
- `backend/infra/persistence/postgres/comparison_repository.py`
- `backend/application/core/comparison_service.py`
- `backend/migrations/versions/*_comparisons.py`
- `backend/tests/integration/persistence/test_postgres_comparisons.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `core-cutover`; verify reusable comparison semantics and collection projections.

## Task 17: Replace Whole-Collection Core Reads

**Description:** Convert workspace, graph, research-view, and evaluation callers
from `read_collection_facts()` to focused repository queries with explicit
ordering and projection inputs.

**Acceptance criteria:**
- [ ] Each caller requests only the record families it consumes.
- [ ] Ordering and empty-but-completed semantics remain explicit and tested.
- [ ] Query counts and payload volume are recorded for representative reads.

**Quality target:**
- [ ] A read path can be understood without materializing the entire Core semantic store.

**Verification:**
- [ ] Run workspace, graph, research-view, and prediction-snapshot tests plus query-count assertions.

**Dependencies:** Tasks 14-16.

**Files likely touched:**
- `backend/application/core/workspace_overview_service.py`
- `backend/application/core/research_view_aggregation_service.py`
- `backend/application/derived/graph_service.py`
- `backend/application/evaluation/prediction_snapshot_service.py`
- `backend/tests/integration/test_focused_core_reads.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `core-read-cutover`; verify focused Core reads and projection parity.

## Task 18: Retire The Core Aggregate Persistence Path

**Description:** Remove the persistence-facing `CoreFactSet` aggregate,
`CoreFactRepository` protocol methods, SQLite implementation, runtime factory,
and obsolete readiness helpers after all direct callers use focused
repositories.

**Acceptance criteria:**
- [ ] No runtime import references `SqliteCoreFactRepository`, `CoreFactRepository`, or collection-wide Core replacement/read methods.
- [ ] Domain-only aggregate helpers remain only if a demonstrated computation requires them.
- [ ] Obsolete schema-creation and payload codecs are deleted.

**Quality target:**
- [ ] Core persistence ownership is visible through bounded repository contracts rather than one broad service locator.

**Verification:**
- [ ] Run `rg` dependency guards and the complete Core-focused test suite.

**Dependencies:** Task 17.

**Files likely touched:**
- `backend/domain/ports.py`
- `backend/domain/core/fact_store.py`
- `backend/infra/persistence/factory.py`
- `backend/infra/persistence/sqlite/core_fact_repository.py`
- `backend/tests/unit/services/test_source_boundary_guards.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `core-read-cutover`; verify full retirement of the broad Core persistence path.

### Checkpoint: Core Cutover

- [ ] Source-to-Core build succeeds with versioned lineage.
- [ ] Objective, evidence, comparison, workspace, graph, and traceback behavior matches baseline.
- [ ] No active Core path imports SQLite or loads a whole collection aggregate.
- [ ] Shared RFC invariants are reviewed manually before Goal migration proceeds.

### Phase 5: Goal, Understanding, And Evaluation

## Task 19: Move Confirmed Goals Into Goal Persistence

**Description:** Move `ConfirmedGoal` and its lifecycle from the Core objective
module and Core repository into the Goal domain with direct PostgreSQL
persistence and explicit objective/build provenance.

**Acceptance criteria:**
- [ ] Goal identity, question snapshot, hints, source objective provenance, status, progress, errors, and timestamps are typed columns or justified JSONB.
- [ ] Goal creation, list, read, start, progress, ready, and failure behavior matches baseline.
- [ ] The Goal application service replaces the Core-owned service, and no full duplicate goal payload is stored beside the typed record.

**Quality target:**
- [ ] A confirmed goal is clearly modeled as selected workflow state, not a generated scientific fact.

**Verification:**
- [ ] Run confirmed-goal domain, repository, router, and goal-analysis pipeline tests.

**Dependencies:** Tasks 15 and 18.

**Files likely touched:**
- `backend/domain/goal/confirmed_goal.py`
- `backend/infra/persistence/postgres/goal_repository.py`
- `backend/application/goal/confirmed_goal_service.py`
- `backend/migrations/versions/*_confirmed_goals.py`
- `backend/tests/integration/persistence/test_confirmed_goals.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `goal-cutover`; verify Goal-owned lifecycle and objective provenance.

## Task 20: Cut Goal Sessions And Experiment Plans To ORM Records

**Description:** Replace handwritten SQLite session, message, and experiment
plan repositories with PostgreSQL ORM records linked to users, collections,
confirmed goals, evidence versions, and reviewed findings.

**Acceptance criteria:**
- [ ] Session/message ordering, review gates, source links, and experiment-plan provenance preserve current behavior.
- [ ] User, collection, goal, and reviewed-source links enforce referential integrity.
- [ ] SQLite Goal session and experiment-plan repositories leave the runtime path.

**Quality target:**
- [ ] Goal working state and downstream plans are auditable against the exact evidence version used.

**Verification:**
- [ ] Run Goal session, message, experiment-plan, router, and protocol-contract tests on PostgreSQL.

**Dependencies:** Task 19.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/goal_session.py`
- `backend/infra/persistence/postgres/goal_session_repository.py`
- `backend/infra/persistence/postgres/experiment_plan_repository.py`
- `backend/migrations/versions/*_goal_sessions.py`
- `backend/tests/integration/persistence/test_goal_working_state.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `goal-cutover`; verify relational Goal working state and provenance.

## Task 21: Normalize Research Understanding Identity And Scope

**Description:** Replace polymorphic string-only scope identity with a versioned
understanding header that explicitly identifies collection, build, scope type,
and the applicable goal, objective, material, or document scope.

**Acceptance criteria:**
- [ ] Each understanding has immutable version identity and one valid scope target.
- [ ] Database checks prevent contradictory or empty scope combinations.
- [ ] Primary and review presentation states remain projections over the same versioned understanding.

**Quality target:**
- [ ] Understanding ownership and scope can be inspected and constrained without decoding a payload blob.

**Verification:**
- [ ] Run scope-domain, repository, goal-understanding read, and projection tests.

**Dependencies:** Tasks 19-20.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/research_understanding.py`
- `backend/infra/persistence/postgres/research_understanding_repository.py`
- `backend/domain/core/research_understanding.py`
- `backend/migrations/versions/*_understanding_header.py`
- `backend/tests/integration/persistence/test_understanding_scope.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `understanding-cutover`; verify constrained versioned understanding scope.

## Task 22: Normalize Claims, Relations, Contexts, And Evidence Links

**Description:** Persist reviewable claims, relations, contexts, evidence
references, and their associations relationally. Keep presentation and
non-queryable model diagnostics in JSONB or object-backed trace payloads.

**Acceptance criteria:**
- [ ] Claims and relations have stable versioned IDs and many-to-many evidence/context links.
- [ ] Every evidence reference resolves to canonical Source/Core records and locators.
- [ ] Goal analysis produces the same primary/review findings and source traceback as the baseline.

**Quality target:**
- [ ] Claim-level review and evaluation no longer depend on IDs hidden inside one JSON payload.

**Verification:**
- [ ] Run finding synthesis, claim validation, goal-analysis, review projection, and source-trace tests.

**Dependencies:** Task 21.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/research_claim.py`
- `backend/infra/persistence/postgres/research_understanding_repository.py`
- `backend/application/core/research_understanding_service.py`
- `backend/migrations/versions/*_research_claims.py`
- `backend/tests/integration/persistence/test_research_claim_traceability.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `understanding-cutover`; verify normalized claim/evidence traceability.

## Task 23: Cut Feedback, Curation, And Evaluation To Versioned Links

**Description:** Move evaluation repositories to ORM models and replace loose
finding/claim strings with foreign keys to versioned predictions, claims,
evidence, feedback, and curation decisions.

**Acceptance criteria:**
- [ ] Gold sets, predictions, runs, scores, failures, feedback, and curations preserve current exports and APIs.
- [ ] Feedback and curation reference an exact understanding/claim content version.
- [ ] Deleting or superseding a prediction cannot silently orphan expert decisions.

**Quality target:**
- [ ] Expert review and evaluation remain reproducible after later analysis rebuilds.

**Verification:**
- [ ] Run evaluation domain/repository/service, expert-review API, and export-script tests on PostgreSQL.

**Dependencies:** Task 22.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/evaluation.py`
- `backend/infra/persistence/postgres/evaluation_repository.py`
- `backend/application/evaluation/research_understanding_feedback_service.py`
- `backend/migrations/versions/*_evaluation.py`
- `backend/tests/integration/persistence/test_evaluation_lineage.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `understanding-cutover`; verify versioned expert-review and evaluation links.

### Checkpoint: Goal And Evaluation Cutover

- [ ] Confirmed-goal analysis completes from queued through ready on PostgreSQL.
- [ ] Primary findings, review candidates, feedback, curation, and plan provenance resolve to exact evidence versions.
- [ ] No Goal, understanding, or evaluation runtime repository imports SQLite.
- [ ] Claim-level parity and traceability reports have zero unexplained differences.

### Phase 6: Data Import And Direct Cutover

## Task 24: Build The Offline Importer And Validator

**Description:** Create an operator tool that reads a frozen SQLite database and
JSON metadata tree, copies binary objects without changing them, imports into
the target schema, and produces a deterministic validation report. It is not a
runtime fallback.

**Acceptance criteria:**
- [ ] Import is idempotent for one recorded migration run and rejects changed source snapshots.
- [ ] Validation covers counts, stable IDs, canonical hashes, foreign keys, active builds, source links, and object hashes.
- [ ] Sensitive data values are never written to logs or committed reports.

**Quality target:**
- [ ] Operators receive a machine-readable pass/fail report with no manual guesswork.

**Verification:**
- [ ] Run importer unit tests, synthetic full-import integration tests, and deliberate corruption tests.

**Dependencies:** Tasks 7-23.

**Files likely touched:**
- `backend/scripts/persistence/import_legacy_state.py`
- `backend/scripts/persistence/validate_import.py`
- `backend/scripts/persistence/migration_model.py`
- `backend/tests/integration/persistence/test_legacy_import.py`
- `backend/tests/unit/scripts/test_validate_import.py`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `migration-cutover`; verify deterministic offline import and validation.

## Task 25: Rehearse Migration And Rollback

**Description:** Run the complete import against a recoverable copy of realistic
state, compare behavior and performance to Task 2, exercise rollback, and
record every accepted discrepancy before production cutover.

**Acceptance criteria:**
- [ ] Migration validation reports zero unexplained row, hash, link, or API differences.
- [ ] Performance meets the success-target thresholds.
- [ ] Backup restore and application rollback complete within the agreed maintenance window.

**Quality target:**
- [ ] Production cutover is a repeated procedure, not the first full migration attempt.

**Verification:**
- [ ] Attach sanitized migration, benchmark, traceback, and restore reports to the issue.
- [ ] Human manually reviews representative goals, claims, tables, figures, and source links.

**Dependencies:** Task 24.

**Files likely touched:**
- `backend/docs/runbooks/postgres-migration.md`
- `backend/scripts/persistence/rehearse_migration.py`
- `backend/tests/integration/persistence/test_migration_parity.py`
- `backend/tests/load/test_postgres_read_paths.py`

**Estimated scope:** Medium, 4 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `migration-cutover`; verify rehearsed parity, performance, and rollback.

## Task 26: Execute The Approved Direct Cutover

**Description:** During the approved maintenance window, stop writes, snapshot
SQLite and object metadata, run the importer, validate, switch the supported
runtime to PostgreSQL, and retain the source snapshot read-only for the agreed
rollback window.

**Acceptance criteria:**
- [ ] Runtime starts with only PostgreSQL structured authorities and object storage.
- [ ] Smoke, API, collection build, goal analysis, source traceback, and expert-review checks pass.
- [ ] Any failed blocking gate triggers rollback rather than a dual-read or dual-write workaround.

**Quality target:**
- [ ] Cutover completes with one active data path and an independently recoverable pre-cutover snapshot.

**Verification:**
- [ ] Run the approved cutover checklist and archive its sanitized result.
- [ ] Run the complete targeted backend suite and operator smoke checks.

**Dependencies:** Task 25, explicit destructive-data approval, and explicit production/deployment approval.

**Files likely touched:**
- `backend/docs/runbooks/postgres-migration.md`
- `deploy/README.md`
- `backend/infra/persistence/factory.py`
- `backend/tests/integration/test_app_layer_api.py`

**Estimated scope:** Medium, 4 maintained files plus operator state changes.

**Issue handoff:** `yes`, `delivery_task`, grouping key `migration-cutover`; verify one-path production cutover and rollback readiness.

### Checkpoint: Direct Cutover

- [ ] All blocking success targets pass.
- [ ] PostgreSQL backup and restore are verified after cutover.
- [ ] Old SQLite and JSON metadata are outside active runtime paths.
- [ ] Human accepts the migration report before cleanup begins.

### Phase 7: Conditional Retrieval And Final Cleanup

## Task 27: Establish A Retrieval Quality Gate

**Description:** Define one evidence-retrieval use case and a gold fixture over
Source text units before adding vector infrastructure. Keep this internal to
the evidence workflow; do not add a generic public search endpoint.

**Acceptance criteria:**
- [ ] The fixture defines relevant text-unit IDs, collection/document filters, and source locators.
- [ ] Exact/keyword and embedding candidates are evaluated with the same recall and traceability metrics.
- [ ] Human records a proceed/stop decision for vector implementation.

**Quality target:**
- [ ] Vector storage is introduced only for a measured retrieval problem.

**Verification:**
- [ ] Run the retrieval benchmark and manually inspect false positives and missed evidence.

**Dependencies:** Tasks 12 and 26.

**Files likely touched:**
- `backend/tests/fixtures/retrieval/text_unit_gold.json`
- `backend/scripts/evaluation/benchmark_source_retrieval.py`
- `backend/tests/unit/scripts/test_benchmark_source_retrieval.py`
- `backend/docs/plans/backend-wide/persistence-model-revision/retrieval-decision.md`

**Estimated scope:** Medium, 4 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `retrieval-index`; verify measured need and an explicit vector decision.

## Task 28: Add Traceable Text-Unit Embeddings

**Description:** Conditional on Task 27 approval, add `pgvector`, one
text-unit-embedding model, deterministic indexing, filtered nearest-neighbor
queries, and canonical Source resolution. Do not index goals, status records,
numeric facts, or binary files in this slice.

**Acceptance criteria:**
- [ ] Embeddings record text-unit FK, Source build, model, dimensions, content hash, and creation time.
- [ ] Reindexing is deterministic and stale embeddings cannot serve after an active-build change.
- [ ] Retrieval meets the approved quality threshold and every result resolves to source evidence.

**Quality target:**
- [ ] Vector search remains a disposable acceleration index over canonical evidence.

**Verification:**
- [ ] Run pgvector migration, indexing, stale-index, filter, recall, and traceback tests.

**Dependencies:** Task 27 approval.

**Files likely touched:**
- `backend/infra/persistence/postgres/models/source_embedding.py`
- `backend/application/source/retrieval_service.py`
- `backend/migrations/versions/*_pgvector_text_units.py`
- `backend/tests/integration/persistence/test_pgvector_retrieval.py`
- `backend/pyproject.toml`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `implementation_task`, grouping key `retrieval-index`; verify rebuildable traceable text-unit retrieval.

## Task 29: Remove Runtime Data And Dependency Residue

**Description:** After the rollback window and explicit cleanup approval,
remove unused LanceDB configuration and dependency, stale graph-store
configuration, generated runtime files from Git, and obsolete fixture residue.
The earlier vertical slices already remove superseded runtime adapters. Preserve
the approved local filesystem object store and deliberate sanitized fixtures.

**Acceptance criteria:**
- [ ] No maintained runtime code references SQLite database paths, file metadata repositories, LanceDB, or graph-store JSON.
- [ ] Generated caches, uploads, images, outputs, traces, and local databases are ignored rather than tracked.
- [ ] Required tests use explicit fixtures outside runtime data paths.

**Quality target:**
- [ ] Repository source and runtime state are visibly separated and no compatibility baggage remains.

**Verification:**
- [ ] Run dependency/path scans, docs governance, targeted fixture tests, and `git status` review.

**Dependencies:** Task 26, completion of the rollback window, and explicit destructive cleanup approval. Task 28 only if vector work proceeds.

**Files likely touched:**
- `backend/.gitignore`
- `backend/pyproject.toml`
- `backend/config.py`
- `backend/data/`
- `backend/tests/fixtures/`

**Estimated scope:** Medium, 5 maintained paths. Material generated-data
deletion remains separately approval-gated and must retain
`backend/infra/persistence/file/object_store.py`.

**Issue handoff:** `yes`, `delivery_task`, grouping key `legacy-cleanup`; verify complete recoverable retirement of legacy paths.

## Task 30: Close Documentation And Quality Gates

**Description:** Update stable architecture, persistence, API operational notes,
and runbooks to the accepted final state, then run the complete backend
verification and one manual evidence-chain review.

**Acceptance criteria:**
- [ ] Stable docs name PostgreSQL, object storage, build lineage, and conditional pgvector ownership without duplicating shared product authority.
- [ ] Every success target has attached evidence or an explicit blocking failure.
- [ ] Final dependency scan finds one structured persistence path and no stale compatibility interfaces.

**Quality target:**
- [ ] The final system is easier to navigate than the current one and its source-of-truth boundaries are independently auditable.

**Verification:**
- [ ] Run `python3 scripts/check_docs_governance.py`.
- [ ] Run the full approved backend test, migration, performance, restore, and manual traceback checklist.

**Dependencies:** Task 29 and Task 28 if approved.

**Files likely touched:**
- `backend/docs/architecture/persistence-model.md`
- `backend/infra/persistence/README.md`
- `backend/docs/specs/api.md`
- `backend/docs/runbooks/postgres-migration.md`
- `backend/README.md`

**Estimated scope:** Medium, 5 files.

**Issue handoff:** `yes`, `delivery_task`, grouping key `closure`; verify documented, tested, single-path closure.

### Checkpoint: Complete

- [ ] All blocking success targets are met.
- [ ] Current collection build and confirmed-goal analysis work end to end.
- [ ] Source traceback and expert review remain evidence-complete.
- [ ] Migration and restore evidence are archived.
- [ ] No generated runtime data or legacy persistence path remains in maintained source.
- [ ] Human approves closure.

## Risks And Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| semantic drift during ORM mapping | High | freeze synthetic golden records and compare canonical payloads at every vertical slice |
| current orphan identifiers fail new FKs | High | audit before schema import; block on unexplained orphan records rather than weakening constraints |
| delete-and-replace behavior loses lineage | High | import current state as one baseline build, then use immutable future builds and active pointers |
| partial branch is deployed | High | mark every intermediate phase non-releaseable and require checkpoint approval before deployment |
| deployment becomes harder for self-hosted users | High | healthchecks, persistent volume, doctor checks, backup/restore rehearsal, clear required configuration |
| over-normalizing model-specific data | Medium | apply the typed-column/JSONB rule based on query and integrity needs |
| repository split creates too many abstractions | Medium | split only by business aggregate and direct caller need, never one repository per table |
| vector index becomes a second truth | High | FK every vector row to Source, store model/content version, and prove complete rebuildability |
| migration logs expose research data | High | log identifiers/counts/hashes only and use sanitized attached reports |
| cleanup removes recoverable local state | High | require explicit approval, verified backup, rollback-window completion, and target inventory |
| performance regresses through ORM N+1 queries | Medium | query-count assertions, eager-loading review, and relative p95 gates |
| background threads share sessions | High | share only engine/session factory and test concurrent goal/build operations |

## Open Questions And Recommended Defaults

| Question | Recommended default | Approval point |
|----------|---------------------|----------------|
| Is PostgreSQL required after cutover? | Yes; do not retain SQLite runtime fallback. | Contract checkpoint |
| Which PostgreSQL version is supported? | Choose one maintained major version and pin it in deployment/tests. | Task 5 |
| Is local filesystem still supported for binaries? | Yes, through stable object keys; cloud adapters remain deferred. | Contract checkpoint |
| How is document identity deduplicated? | Internal ID plus content SHA-256; DOI is metadata. | Task 1 |
| How much legacy history is imported? | Import current authoritative state as one baseline build; preserve source snapshot separately. | Task 24 |
| How many old builds are retained? | Retain active plus an operator-approved number of successful builds; never purge reviewed evidence versions automatically. | Task 10 |
| Are model traces stored in PostgreSQL? | Store searchable metadata in DB and large raw trace payloads in object storage. | Task 22 |
| Is vector retrieval required for the migration? | No; Tasks 27-28 are conditional and occur after relational cutover. | Task 27 |
| What is the rollback window? | Define before rehearsal based on backup size and operator tolerance. | Task 25 |
| Can deployment files change? | Only after explicit operator approval under repository governance. | Task 5 |

## Parallelization And Sequencing

The repository defaults to single-agent execution. Do not delegate unless the
human explicitly changes that rule.

Sequential work is mandatory for schema migrations, identity changes, data
imports, direct cutover, and legacy deletion. After the authority contract is
frozen, independent sessions may prepare test fixtures, documentation, and
already-defined repository slices, but shared model or migration files must
have one owner and one landing order.

## Issue Handoff

- parent_issue_needed: yes
- task_issue_policy: grouped_by_phase

| Tasks | issue_candidate | suggested_issue_level | grouping_key | acceptance summary | issue rationale |
|-------|-----------------|-----------------------|--------------|--------------------|-----------------|
| 1-2 | yes | implementation_task | foundation-contract | freeze authority, ERD, behavior, and migration baseline | required before any code decision |
| 3-5 | yes | implementation_task | postgres-foundation | provide secure migrated and operable PostgreSQL foundation | dependency and deployment approval boundary |
| 6 | yes | implementation_task | object-foundation | separate binary ownership through one permanent object-store port | independent permanent boundary |
| 7-10 | yes | implementation_task | relational-root | cut auth, collection, files, tasks, and builds to the relational root | first complete operational vertical wave |
| 11-13 | yes | implementation_task | source-cutover | establish reusable document identity and versioned Source records | independently verifiable Source wave |
| 14-16 | yes | implementation_task | core-cutover | persist reusable facts, objective evidence, and comparison assessment | semantic substrate wave |
| 17-18 | yes | delivery_task | core-read-cutover | replace whole-collection reads and retire broad Core persistence | cleanup depends on prior Core slices |
| 19-20 | yes | implementation_task | goal-cutover | move Goal lifecycle, sessions, and plans to relational ownership | Goal working-state wave |
| 21-23 | yes | implementation_task | understanding-cutover | normalize understandings and bind expert evaluation to versions | claim-level integrity wave |
| 24-26 | yes | implementation_task | migration-cutover | import, rehearse, validate, and directly cut over with rollback | high-risk operator wave |
| 27-28 | yes | implementation_task | retrieval-index | prove retrieval need and conditionally add pgvector | optional measured feature wave |
| 29 | yes | delivery_task | legacy-cleanup | remove retired adapters, dependencies, and generated runtime residue | destructive cleanup needs separate approval |
| 30 | yes | delivery_task | closure | close docs and all quality gates | independently reviewable final acceptance |

## Plan Verification Checklist

- [x] Every task has explicit acceptance criteria.
- [x] Final success targets and failure policies are defined.
- [x] Every task has a verification method.
- [x] Dependencies and checkpoints are explicit.
- [x] High-risk contract, deployment, migration, and cleanup gates occur before action.
- [x] Tasks target approximately three to five maintained files or require further split.
- [x] Issue handoff is prepared without creating issues.
- [ ] Human has reviewed and approved the plan.
