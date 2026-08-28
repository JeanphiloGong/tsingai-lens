# Application Pipeline Records

The maintained preparation workflow is owned directly by
`application/source/document_preparation_service.py`, and Objective execution is
owned by `application/core/objectives/analysis_service.py`.

`domain.pipeline.PipelineRun` and `PipelineNodeRun` remain shared observable
execution records for stages, diagnostics, statistics, and timestamps. They do
not define a collection snapshot, select Source versions, or carry an output
build ID. Scientific ordering remains in the owning application service.
