# Application Pipeline Records

The maintained preparation workflow is owned directly by
`application/source/document_preparation_service.py`, and Objective execution is
owned by `application/core/objectives/analysis_service.py`.

`pipeline_run_service` owns admission, node transitions, progress, terminal failure,
retry lineage, and restart recovery for those executions. It constructs execution
records directly from the fixed node graphs defined in the service. Tests check
the preparation and discovery dependencies; creating a run does not revalidate
these internal definitions.

Operations return the existing `PipelineRun` values; list and recovery reads
return `PipelineRunSummary` values. Preparation and discovery consume their
fields directly. HTTP output is constructed in
`controllers/schemas/source/pipeline_run.py`, while Agent capabilities construct
their existing tool observations. Both output boundaries replace private
preparation errors with safe stage messages without rewriting stored diagnostics.
`PipelineRun` and
`PipelineNodeRun` live beside their contract in
[`../../repositories/pipeline_run_repository.py`](../../repositories/pipeline_run_repository.py)
and are persisted together in one `pipeline_runs` row. Reading them does not
rerun graph validation or advance nodes. They do not define a
collection snapshot, select Source
versions, or carry scientific results. Scientific ordering and result writes
remain in the owning application service and artifact repository.
