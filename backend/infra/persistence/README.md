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
  canonical documents and versions, collection-document membership, collection
  file provenance, import provenance, Goal-intake handoffs, tasks, collection
  builds, stage state, artifact versions, active-build selection, and
  build-versioned Source structure, figures, references, document profiles,
  reusable paper facts, research objectives, contexts, paper frames, evidence
  routes, evidence units, logic chains, comparable results, collection
  comparison assessments, pairwise relations, and Research Objective lifecycle
  state through SQLAlchemy mappings and direct aggregate repositories.
  The application creates one engine and session factory and composes these
  repositories and services in the FastAPI lifespan.
- `sqlite/`
  Handwritten repositories share `backend/data/lens.sqlite` for Goal sessions
  and plans, understandings, and evaluation/review state.
  These remaining repositories currently create schema at runtime. SQLite
  Source, paper-fact, objective, and comparison tables are isolated
  test/legacy residue and are not composed into maintained runtime readers,
  writers, or supported scripts.
- `mysql/`
  Unimplemented placeholder with no active runtime selection path.

`factory.py` constructs SQLite repositories only for the remaining Goal session
and plan, Understanding, and evaluation families. Auth, collection, build, Source,
paper-fact, objective, and comparison aggregates are composed directly in
`main.py`; none
has a repository factory or
runtime fallback. Source pipeline JSON and Parquet
outputs live under `infra/source/` runtime storage and are rebuildable
intermediates, not a second persistence authority.

`database.py` owns the validated synchronous SQLAlchemy engine and session
factory. The FastAPI lifespan shares this contract between auth, collection,
and build repositories and disposes its owned engine at shutdown; injected test
services remain caller-owned.

`postgres/base.py` owns declarative metadata. `postgres/models/auth.py`,
`postgres/models/collection.py`, `postgres/models/document.py`,
`postgres/models/build.py`, `postgres/models/source.py`,
`postgres/models/paper_fact.py`, `postgres/models/objective.py`, and
`postgres/models/comparison.py` own their storage mappings; the matching direct
aggregate repositories own explicit row/domain mapping and short transactions.
`../../migrations/` owns the version history and is the only PostgreSQL schema
change path; repositories never create tables.

`PostgresCollectionRepository` is the single structured owner for collection
metadata, canonical documents and versions, exact-version collection
membership, object/file replicas, imports, imported-document links, and
handoffs. Import registration creates or reuses document identity and commits
membership, provenance, and membership-based collection count/status in one
transaction. Identical content may have separate collection-scoped object
replicas but only one immutable version. Collection deletion removes final
unreferenced document identity and commits relational removal before the
workspace directory is deleted. Maintained callers do not read or write
collection file or import manifest JSON and do not scan input directories as a
fallback authority.

There is no separate document repository or service. Canonical registration is
part of collection import, and keeping one repository preserves the single
transaction that also owns file provenance and collection count.

`PostgresBuildRepository` is the single structured owner for tasks, collection
builds, ordered stages, immutable artifact versions, and active-build
selection. It allocates collection-local build numbers and activates only newer
successful builds in short transactions. `MemoryBuildRepository` mirrors this
aggregate only for isolated tests. No maintained caller reads or writes task
JSON or `artifacts.json`.

`PostgresSourceArtifactRepository` is the single structured owner for Source
documents, text units, blocks, tables, rows, cells, figures, references, and
their associations. A write names one pending build; a normal read resolves
only the active successful build. Exact stored-filename matching links every
Source document to canonical collection membership and its immutable document
version. Figure rows store object keys and verification metadata; figure bytes
remain in the existing object store. References are extracted and persisted
before activation, so the public reference POST is an idempotent active-build
read rather than a post-build mutation.

`PostgresPaperFactRepository` is the single structured owner for document
profiles, evidence anchors, methods, sample variants, test conditions,
baselines, measurements, characterization observations, and structure
features. Writes name one pending build and validate each Source document and
document version in the same transaction. Default reads resolve only the
active successful build. Callers that also need objectives or comparisons
receive the direct Objective and Comparison repositories explicitly; no
composite repository or SQLite paper-fact fallback exists.

`PostgresObjectiveRepository` is the single structured owner for research
objectives, contexts, paper frames, evidence routes, evidence units, logic
chains, and their ordered document, Source, paper-fact anchor, and evidence-unit
links. Writes replace one explicitly named pending build; default reads resolve
only the active successful build. The same repository owns
`research_objective_lifecycles`, keyed by `(collection_id, objective_id)`, and
pins each confirmed Objective to its exact immutable source build. Objective
analysis derives its stages in memory and persists only the final
objective-scoped Understanding through its current owner. It does not mutate
the collection Objective build. No second Goal identity, lifecycle repository,
SQLite objective path, fallback, or dual path remains.

Alembic revision `20260720_0013` also defines the final Objective-scoped
Understanding, expert-review, session/message, experiment-plan, and sanitized
migration-audit tables used by the offline Goal identity importer. In this
slice those tables are an offline migration target only. Maintained runtime
services continue to use their existing downstream repositories until the
direct Objective-scope cutover replaces those callers in the next slice; no
runtime fallback or dual read is introduced.

`PostgresComparisonRepository` is the single structured owner for comparable
results, collection-scoped assessments, pairwise relations, and their ordered
source/evidence links. Writes replace one explicitly named pending build;
default reads resolve only the active successful build. `ComparisonService`
regenerates `ComparisonRowRecord` values from those semantic records for every
row-facing read. No comparison-row table, SQLite comparison read, fallback, or
dual write exists.

The former broad Core persistence path and ConfirmedGoal runtime path have been
deleted. `SqliteResearchUnderstandingRepository` is the direct temporary owner
for its legacy table, and services receive that narrow repository contract
explicitly. Its later PostgreSQL cutover replaces the concrete implementation
directly; there is no aggregate facade, fallback alias, or compatibility path.

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
