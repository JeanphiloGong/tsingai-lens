# Repository Contracts

This directory defines what application code can save and load. Open the
repository's file to find both its methods and any dedicated query-result types.
SQL and transactions remain in `infra/persistence/`; business objects and their
rules remain in `domain/`.

## Follow One Saved Research Question

A researcher opens a saved question about laser power and porosity:

1. `ObjectiveRepository.read_objective_record()` returns `StoredObjective`.
   Its `objective` field is the existing `ResearchObjective`, not a copy of its
   scientific fields. The other fields are the record timestamps.
2. The PostgreSQL implementation decodes the scientific payload and attaches
   timestamps from the database columns.
3. `ObjectiveAnalysisService` uses that snapshot's version pointers to read
   active and published analyses. A failed new analysis never replaces the
   previously published result.
4. The controller formats the object and timestamps into the existing HTTP
   response. Repository contracts do not import HTTP schemas.

When only the research question is needed, `read_objective()` returns
`ResearchObjective` directly. Source identities, scientific provenance, analysis
versions and review decisions also remain domain concepts even when persisted.

## Find the Owner

| File | Records returned |
| --- | --- |
| [objective_repository.py](objective_repository.py) | Objectives, Evidence, Findings; `StoredObjective` for metadata reads and `ObjectiveAnalysis` for versioned execution snapshots |
| [collection_repository.py](collection_repository.py) | Collection/Document detail; `CollectionSummary` and `CollectionDocumentSummary` for listing |
| [pipeline_run_repository.py](pipeline_run_repository.py) | `PipelineRun`, node execution records and model usage; `PipelineRunSummary` for history |
| [auth_repository.py](auth_repository.py) | `AuthUserRecord` and `AuthSessionRecord`; token hashes are separate write inputs |
| [source_artifact_repository.py](source_artifact_repository.py) | Source documents, trees, tables, figures and references |
| [document_profile_repository.py](document_profile_repository.py) | `DocumentProfile` |
| [paper_map_repository.py](paper_map_repository.py) | `PaperResearchMap` |
| [chat_repository.py](chat_repository.py) | Sessions, messages, approved tool-call state, model-call audit inputs/outcomes and response progress |
| [analysis_job_repository.py](analysis_job_repository.py) | `AnalysisJob` execution snapshots, including leases and retry state |
| [feedback_dataset_repository.py](feedback_dataset_repository.py) | `Dataset` and `StoredDataset`; the latter adds database record timestamps |
| [feedback_dataset_sample_repository.py](feedback_dataset_sample_repository.py) | Collected samples, confirmed revisions, build-job payloads and idempotency inputs |
| [experiment_plan_repository.py](experiment_plan_repository.py) | Immutable `ExperimentPlanRecord` revisions |
| [finding_review_repository.py](finding_review_repository.py) | Expert feedback and curated Findings |
| [evaluation_repository.py](evaluation_repository.py) | Gold sets, prediction snapshots and evaluation runs |
| [object_store.py](object_store.py) | Uploaded/extracted bytes, addressed by storage key and hash |

## Make a Change

Change a scientific rule in the domain object, orchestration in its application
service, a query or storage mapping in the concrete repository, and HTTP fields
in the controller/schema. A new query projection belongs beside its repository
contract; an implementation-only row helper stays private to the implementation.
Do not add a result wrapper when the domain object already expresses the answer.

Job leases, worker identities, model-call token counts, and Pipeline progress are
execution metadata. Their types live beside the repository contract that uses
them. Queue payload versions and idempotency keys also belong here; the feedback
domain keeps the observed signal, evidence judgment, and sample rules.

`Dataset` contains its identity, Collection scope, task, construction rules and
author. Creation validation belongs in `FeedbackDatasetService` and the HTTP
request schema. The PostgreSQL implementation assigns database record timestamps;
`StoredDataset` includes them for metadata reads without copying the domain
fields. Builders read `Dataset` directly. Controllers combine the domain object
and stored timestamps into the existing response.

HTTP schemas can read domain attributes directly with Pydantic
`from_attributes`; domain entities do not need a dictionary conversion solely
for an API response. Scientific artifact encoders used for frozen snapshots and
hashes retain their existing format. They are distinct from HTTP formatting.
Keep evidence, revision, and state-transition invariants when removing
transport-specific normalization. See the
[model ownership rules](../../docs/architecture/overview.md#model-responsibilities)
for the package-by-package boundary.

`ResearchObjective` has no persistence encoder. The PostgreSQL repository maps
its scientific fields to the existing JSON payload and supplies timestamps
through `StoredObjective`. Record parsers in `objective_repository.py` own their
local parsing helpers instead of importing domain-private functions.

Collection summaries use two queries without loading preparation artifacts.
Pipeline history reads only its indexed and JSON summary fields; full diagnostics
remain available through detail reads. These are read-path choices, not changes
to stored formats or execution rules.

See [persistence ownership](../../infra/persistence/README.md) and
[research-flow verification](../../tests/objective-analysis-verification.md).
