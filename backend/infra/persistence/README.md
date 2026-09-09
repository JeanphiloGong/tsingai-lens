# Persistence Adapters

This node owns storage-specific repository implementations. The authoritative
identity model is [`../../docs/architecture/persistence-model.md`](../../docs/architecture/persistence-model.md).

## Runtime Boundary

- PostgreSQL owns structured current state and versioned Objective analyses.
- Object storage owns uploaded and extracted bytes.
- Local output and cache paths are disposable scratch.
- Alembic is the only runtime schema-change path.
- Memory repositories exist only for isolated tests.

Maintained runtime composition uses one SQLAlchemy `AsyncEngine`, one
`async_sessionmaker`, and explicit PostgreSQL repositories from `main.py`. Each
operation creates a short task-local `AsyncSession`.

## Current Aggregate Ownership

- `PostgresCollectionRepository`: `Collection -> current Documents`, including
  file metadata and preparation state.
- `PostgresPipelineRunRepository`: observable Collection- or Document-scoped
  execution and nested node telemetry in one row.
- `PostgresSourceArtifactRepository`: the current Source aggregate for each
  Document, stored in the Source section of `document_preparations`.
- `PostgresDocumentProfileRepository`: one current profile per Document,
  stored in `document_preparations.profile_json` with its own input fingerprint.
- `PostgresPaperMapRepository`: reads and writes the embedded Paper Map fields
  on `document_preparations`, after a profile exists.
- `PostgresObjectiveRepository`: Collection discovery fields, Objective records,
  versioned analyses (including private checkpoints and contributions), Evidence,
  and Findings.
- `PostgresChatRepository`: Agent sessions, messages, tool calls, embedded
  results, and approval decisions.
- `PostgresFindingReviewRepository`, `PostgresExperimentPlanRepository`, and
  `PostgresEvaluationRepository`: their named downstream records.

## Objective Aggregate

```text
collections.discovery_*
research_objectives
  -> objective_analyses
     -> payload.paper_contributions / payload.document_evidence_checkpoints
     -> payload.evidence_records
     -> payload.findings
```

Discovery and each analysis store exact `document_inputs`, where every item is
`document_id + preparation_fingerprint`. Retry allocates a new analysis version.
Only a complete succeeded version advances the published pointer; failure never
hides the prior published version.

Each preparation producer owns its section. Updating a Profile cannot relabel
the current Source fingerprint, and Collection status updates cannot rewrite
artifact provenance. A profile without a known input fingerprint remains
unversioned; a preparation row without a Source artifact is not a parsed Source.

SQLAlchemy models own storage shape, domain records own scientific invariants,
and Pydantic models own HTTP payloads. Do not add a generic repository, storage
selector, compatibility wrapper, dual write, schema probe, or fallback store.
