# Source Application Layer

This package owns collection construction, Source indexing orchestration, and
artifact readiness handoff inside the backend application layer.

- `collection_service.py`
  Collection lifecycle, file membership, import provenance, and goal handoff
  registration
- `task_service.py`
  Source indexing task registry and stage persistence
- `index_task_runner.py`
  Source runtime execution followed by Core post-processing kickoff
- `artifact_input_service.py`
  Normalized Source artifact loading for downstream consumers
- `artifact_registry_service.py`
  Collection artifact readiness and capability flags
