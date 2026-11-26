# Research Database Design

This document defines the Research persistence boundary for the module reconstruction. Alembic
migrations own physical schema changes. Runtime repositories use the SQLAlchemy ORM mappings.
Domain objects enforce research invariants. Relational constraints enforce identity, ownership,
uniqueness, and version relationships.

## `research_objectives`

One row represents the current Research Objective aggregate inside a Workspace.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| `workspace_id` | varchar(64) | no | Workspace foreign key and composite primary-key column |
| `objective_id` | varchar(128) | no | Stable Objective identity and composite primary-key column |
| `rank` | integer | no | Current rank, positive |
| `origin` | varchar(32) | no | `system_discovered` or `chat_assisted` |
| `created_by_tool_call_id` | varchar(128) | yes | Unique Agent creation call for chat-assisted candidates |
| `payload` | JSON/JSONB | no | Question, scope, provenance, confirmation, and analysis-version fields |
| `created_at`, `updated_at` | timestamptz | no | Aggregate timestamps |

The table has a Workspace foreign key and a unique constraint on
`created_by_tool_call_id`. The payload contains the domain fields below.

```text
question
material_scope
variables
outcomes
mechanisms
constraints
requested_comparator
seed_document_ids
excluded_document_ids
source_relationship_ids
confidence
reason
parent_objective_id
parent_analysis_version
derivation_basis
confirmation_status
active_analysis_version
published_analysis_version
origin
created_by_user_id
created_by_tool_call_id
```

`seed_document_ids` and `excluded_document_ids` cannot overlap. Parent Objective,
parent-analysis-version, and derivation-basis fields must be supplied consistently. A published
version cannot be newer than the active version. The `ResearchObjective` domain model repeats
these checks before persistence.

## `objective_analyses`

One row represents one versioned analysis of one Objective.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| `workspace_id`, `objective_id`, `analysis_version` | composite key | no | Objective analysis identity |
| `status` | varchar(16) | no | Queued, running, succeeded, abstained, or failed analysis state |
| `payload` | JSON/JSONB | no | Fixed Document inputs, preparation fingerprints, progress, contributions, and errors |
| `worker_id` | varchar(255) | yes | Current analysis claimant |
| `lease_version` | integer | no | Claim concurrency version, default `0` |
| `lease_expires_at`, `heartbeat_at` | timestamptz | yes | Recovery metadata |
| `created_at`, `updated_at` | timestamptz | no | Version timestamps |

A composite foreign key ensures that the analysis belongs to the same Workspace and Objective.
The claim index supports selection by status, lease expiry, and creation time. PipelineRun records
workflow execution. ObjectiveAnalysis records the scientific analysis version. They are separate
lifecycles.

## Research relationships

- `objective_experiment_selection` binds an Objective analysis version to a PaperExperiment
  revision.
- `selection_measurement` binds a selection to a concrete measurement result.
- Findings, Evidence, comparison groups, and Research Plan revisions reference fixed Objective
  analysis versions and Source identities.
- Document and Source versions remain owned by Document. Research stores the identity, version,
  and digest needed to verify the reference.

## Naming migration

Some historical migrations still use `collection_id`, while the target ORM and API use
`workspace_id`. Before adding new Research migrations, inventory every old foreign key, index,
Repository query, and JSON key. The migration chain must rename these references explicitly and
provide a tested downgrade or a documented irreversible boundary. Renaming the ORM attribute alone
does not change the deployed database.

## ORM ownership

The current mapped classes live in `backend/infra/persistence/postgres/models/objective.py`.
The future module-first layout places Research repositories under `backend/research/repositories/`
while keeping persistence mappings under the shared infrastructure boundary. Research repositories
return domain objects or named projections to application services. ORM records do not become HTTP
responses.
