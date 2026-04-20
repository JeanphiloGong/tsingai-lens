# Source Application Layer

This package owns collection construction, Source build orchestration, and
artifact readiness handoff inside the backend application layer.

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
  Collection artifact readiness and capability flags
