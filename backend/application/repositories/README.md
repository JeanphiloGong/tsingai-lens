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
| [objective_repository.py](objective_repository.py) | Objectives, analyses, Evidence, Findings; `StoredObjective` for metadata reads |
| [collection_repository.py](collection_repository.py) | Collection/Document detail; `CollectionSummary` and `CollectionDocumentSummary` for listing |
| [pipeline_run_repository.py](pipeline_run_repository.py) | Complete `PipelineRun` for execution/detail; `PipelineRunSummary` for history |
| [auth_repository.py](auth_repository.py) | `AuthUserRecord` and `AuthSessionRecord`; token hashes are separate write inputs |
| [source_artifact_repository.py](source_artifact_repository.py) | Source documents, trees, tables, figures and references |
| [document_profile_repository.py](document_profile_repository.py) | `DocumentProfile` |
| [paper_map_repository.py](paper_map_repository.py) | `PaperResearchMap` |
| [chat_repository.py](chat_repository.py) | Sessions, messages and approved tool-call state |
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

Collection summaries use two queries without loading preparation artifacts.
Pipeline history reads only its indexed and JSON summary fields; full diagnostics
remain available through detail reads. These are read-path choices, not changes
to stored formats or execution rules.

See [persistence ownership](../../infra/persistence/README.md) and
[research-flow verification](../../tests/objective-analysis-verification.md).
