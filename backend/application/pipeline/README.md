# Application Pipeline Layer

This package owns application pipeline execution.

Pipeline modules decide which application steps run, in which dependency order,
how step state is recorded, and how pipeline state is projected into task
status. Concrete implementation logic remains in the owning `application/source`,
`application/core`, `application/derived`, and `infra` modules.

Runtime state uses the shared `domain.pipeline.PipelineRun` aggregate. A run
records its pipeline name, mode, execution id, scope, status, node runs,
diagnostics, statistics, timestamps, and optional output build id. Starting a
mode materializes its configured dependency graph into the run. From that point
the run's node dependencies are the execution source of truth; configuration
order does not control scheduling. Model and token statistics are nullable and
must come from provider responses rather than estimates.
