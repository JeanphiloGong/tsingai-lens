# Source Application Layer

This package owns collection construction, build-task orchestration, and
artifact readiness handoff inside the backend application layer. It is not the
parser implementation layer.

The Source parser and artifact builder live under
`backend/infra/source/runtime/`. After that Source runtime finishes, this
application package starts Core post-processing for document profiles, paper
facts, comparison rows, and protocol artifacts.

- `collection_service.py`
  Collection lifecycle, file membership, import provenance, and goal handoff
  registration
- `task_service.py`
  Collection build task registry and stage persistence
- `collection_build_task_runner.py`
  Source artifact build execution followed by Core post-processing kickoff
- `artifact_input_service.py`
  Normalized Source artifact loading for downstream consumers
- `artifact_registry_service.py`
  Collection artifact readiness and capability flags, including semantic/scope
  comparison artifacts such as `comparable_results.parquet` and
  `collection_comparable_results.parquet`
