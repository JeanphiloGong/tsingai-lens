# Backend Persistence Model

## Purpose

This document defines the current maintained storage identities. The model is
intentionally current-state-first: old collection build snapshots and their data
are not migrated, read, or retained through compatibility paths.

## Storage Rule

| Data | Authority | Rule |
| --- | --- | --- |
| Structured product state | PostgreSQL | Read and write only through explicit repositories. |
| Uploaded and extracted bytes | Object storage | Store immutable bytes; PostgreSQL stores identity and integrity metadata. |
| Parser/model scratch | Local runtime paths | Disposable and never a product read authority. |
| Schema | Alembic | Startup does not create or infer tables. |

## Domain Ownership

```text
Collection
  -> Documents

Document
  -> current DocumentPreparation (Source + Profile + optional PaperMap)

PipelineRun
  -> technical execution history for a Collection or Document scope
  -> nested node telemetry

Objective discovery
  -> current selected PreparedDocumentInputs
  -> ResearchObjectives

ResearchObjective
  -> ObjectiveAnalysis versions
     -> PaperExperiment revisions
     -> ObjectiveExperimentSelections
     -> optional ComparisonGroups
     -> Findings
```

### Collection and Document

`Collection` is identified by `collection_id` and belongs to one user. It owns
current Document membership. A Document is identified by `document_id`; its
filename, storage key, SHA-256, media type, status, size, and collection order
live on the Document record. Parser provenance and the Source fingerprint live
in the Source section of the current `DocumentPreparation` row. Profile
version, Source/profile fingerprints, and profile generation time live in its
Profile section. The domain-level preparation fingerprint is derived from the
current profile fingerprint.

There is no public CollectionDocument membership object and no DocumentVersion
aggregate. A Document is the current paper in the Collection.

The Collection row also owns the current discovery selection through
`discovery_ready`, `discovery_document_inputs`, `discovery_objective_ids`,
`discovery_study_dispositions`, and `discovery_updated_at`. This state is
replaced as one collection-local result; it is not a separate discovery
aggregate or historical snapshot.

### Document preparation

Source, Profile, and Paper Map sections belong to one `document_id` and
cascade when that Document is deleted. They share one current preparation
identity and deletion boundary.

`DocumentPreparation` stores one complete format-neutral parsed artifact and
its Profile and Paper Map results in named JSON sections. The envelope can
represent PDF pages, DOCX sections, and XLSX sheets without adding a new
relational table family for each format.

Preparation uses a dependency chain rather than one all-or-nothing cache key:

```text
Source fingerprint
  = SHA-256(document SHA-256 + parser version)

Profile fingerprint
  = SHA-256(Source fingerprint + Profile version)

Preparation fingerprint
  = Profile fingerprint
```

Changing Paper Map logic reuses Source and Profile because Paper Maps are built
by Objective work. Changing Profile logic reuses Source; changing document bytes
or parser logic invalidates all dependent preparation stages. The preparation
fingerprint identifies the exact ready Source/Profile state used by discovery or
analysis. The Profile section of the preparation row stores the complete Paper Map, including its
`input_fingerprint`, `map_version`, and `generated_at`, in one navigation
payload. The input fingerprint contains the preparation fingerprint plus the
current Paper Map policy and prompt versions. These values are not user-visible
versions and do not create a snapshot hierarchy.

### Pipeline Run

`pipeline_runs` stores observable technical execution history in one row per
invocation. Indexed columns carry `collection_id`, `pipeline_name`,
`scope_type`, `scope_id`, `input_fingerprint`, mode, status, and searchable
timestamps. `record_json` carries the complete validated run snapshot,
including current node, progress, nested node telemetry, warnings, errors,
statistics, timestamps, context, and retry lineage. It does not own scientific
artifacts or filesystem output paths.

A partial unique index permits at most one queued or running run for one
`(pipeline_name, scope_type, scope_id)` tuple. A repeated Document preparation
request receives the active run. A completed Document run can be reused only
if its input fingerprint equals the current requested fingerprint. Objective
discovery reuses an active Collection run but a later completed discovery does
not suppress a new explicit discovery request.

### Objective discovery

The current candidate-discovery result is stored on `collections` in the
`discovery_*` fields. It includes ordered `document_inputs`, each containing:

```json
{
  "document_id": "doc_...",
  "preparation_fingerprint": "..."
}
```

Discovery replacement changes the current candidates for that Collection. It
does not create a Collection snapshot or duplicate preparation aggregates.

### Objective analysis

Objective identity is `(collection_id, objective_id)`. Analysis identity is
that pair plus positive `analysis_version`.

Every analysis freezes its selected `document_inputs`. Before reading Source,
the service verifies that every Document is still ready and still has the same
fingerprint. A mismatch is stale input and blocks the run. This prevents one
analysis from reading Source from a different preparation than it recorded.

The automatic path writes immutable PaperExperiment revisions and explicit
ObjectiveExperimentSelections. A later supplement or correction creates a
successor revision; it never mutates the revision used by an earlier Finding.
Optional ComparisonGroups organize selections only when a cross-paper question
requires them. Human- or Agent-authored analysis versions retain their own
immutable Evidence/Finding snapshot.

Public analysis results use the same Objective/version identity inside the
`objective_analyses.payload` arrays:

- ObjectiveEvidence adds `evidence_id` and references one contribution.
- Finding adds `finding_id`.
- Finding relations and context remain children of that Finding.

The former `document_evidence_checkpoints` payload is historical data only. A
one-time migration records each entry in
`objective_analysis_legacy_checkpoints` with a payload hash and
`manual_review_required` classification, then removes it from the runtime
analysis payload. No repository reads or writes that key anymore.

Retry creates another `analysis_version`. Only a complete succeeded version may
become published. Failure leaves the prior published pointer unchanged.

## Relational Backbone

```mermaid
erDiagram
    USER ||--o{ COLLECTION : owns
    COLLECTION ||--o{ DOCUMENT : contains
    COLLECTION ||--o{ PIPELINE_RUN : executes
    DOCUMENT }o..o{ PIPELINE_RUN : logical_scope
    DOCUMENT ||--o| DOCUMENT_PREPARATION : has_current
    DOCUMENT_PREPARATION ||--o| SOURCE_SECTION : embeds
    DOCUMENT_PREPARATION ||--o| PROFILE_SECTION : embeds
    DOCUMENT_PREPARATION ||--o| PAPER_MAP_CACHE : embeds
    COLLECTION ||--o| DISCOVERY_STATE : embeds
    COLLECTION ||--o{ RESEARCH_OBJECTIVE : frames
    RESEARCH_OBJECTIVE ||--o{ OBJECTIVE_ANALYSIS : retries
    OBJECTIVE_ANALYSIS ||--o{ PAPER_EXPERIMENT : produces
    OBJECTIVE_ANALYSIS ||--o{ OBJECTIVE_EXPERIMENT_SELECTION : selects
    PAPER_EXPERIMENT ||--o{ OBJECTIVE_EXPERIMENT_SELECTION : fixed_revision
    OBJECTIVE_EXPERIMENT_SELECTION ||--o{ FINDING_SELECTION : supports
    COMPARISON_GROUP ||--o{ FINDING_COMPARISON_GROUP : supports
    OBJECTIVE_ANALYSIS ||--o{ FINDING : publishes
```

## Replacement And Deletion

- Re-preparing a Document replaces the relevant Source/Profile sections of its
  current preparation row only after the owning step succeeds; a later
  Objective operation rebuilds the embedded Paper Map cache when its
  fingerprint is stale. Pipeline Run history remains observable.
- Uploading another Document adds a peer and does not touch prepared peers.
- Deleting a Collection cascades its Documents, prepared artifacts, Pipeline Runs,
  Objectives, analyses, and downstream records.
- The destructive current-model migrations drop old collection-build,
  active-build, artifact-version, workspace-projection, persisted paper-fact,
  and comparison tables before creating the current model. Migration
  `20260908_0043` backfills the consolidated Source aggregate from the retired
  normalized Source tables before dropping them; migration `20260908_0044`
  moves preparation provenance to artifact ownership. Migration
  `20260908_0045` backfills the former Task history into `pipeline_runs` and
  removes `tasks` and `task_stages`; `20260908_0047`-`0053` merge lifecycle-local
  Paper Map, Chat result, analysis-intermediate, discovery, evaluation child,
  and redundant Source/count storage; `0054` merges current document
  preparation artifacts and `0055` merges public Objective result records.
  Revisions `20260924_0066`-`20260924_0070` add the immutable experiment,
  selection, comparison-group, and Finding graph. Revisions
  `20260924_0071`-`20260924_0074` add the feedback workbench aggregates, and
  `20260924_0075` classifies retired per-document checkpoints for manual review.

## Implementation Boundary

Repositories map domain records directly to SQLAlchemy rows. Do not add a
generic repository, build selector, compatibility facade, dual read/write,
runtime table detection, or JSON fallback. A contract change updates the owning
domain record, repository, application caller, API schema, and tests together.

## Related Authorities

- [`overview.md`](overview.md)
- [`../specs/api.md`](../specs/api.md)
- [`../../infra/persistence/README.md`](../../infra/persistence/README.md)
- [`../../../docs/contracts/research-objective-workspace-contract.md`](../../../docs/contracts/research-objective-workspace-contract.md)
