# Source Application Layer

This package owns collection lifecycle state, build-task records, Source
artifact loading, and artifact readiness handoff inside the backend application
layer. It is not the parser implementation layer or the collection build
pipeline owner.

The Source parser and artifact builder live under
`backend/infra/source/runtime/`. The collection build workflow that calls Source
runtime and then Core post-processing lives under
`backend/application/pipeline/collection_build/`.

- `collection_service.py`
  Collection lifecycle, file membership, import provenance, and goal handoff
  registration
- `task_service.py`
  Collection build task registry and stage persistence
- `artifact_input_service.py`
  Normalized Source artifact loading for downstream consumers
- `document_markdown_service.py`
  Display Markdown projection built from the Source document tree
- `artifact_registry_service.py`
  Collection artifact readiness and capability flags, including semantic/scope
  comparison artifacts persisted through the Core repository
