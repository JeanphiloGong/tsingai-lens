# Application Pipeline Records

The maintained preparation workflow is owned directly by
`application/source/document_preparation_service.py`, and Objective execution is
owned by `application/core/objectives/analysis_service.py`.

`PipelineRunService` owns admission, reuse, progress, terminal failure, retry
lineage, and restart recovery for those executions. `domain.pipeline.PipelineRun`
and `PipelineNodeRun` are the typed records persisted together in one
`pipeline_runs` row. They do not define a collection snapshot, select Source
versions, or carry scientific results. Scientific ordering and result writes
remain in the owning application service and artifact repository.
