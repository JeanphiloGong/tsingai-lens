# Collection Build Pipeline

This package owns the default collection build pipeline. It coordinates Source
artifact generation, document profiles, lightweight objective candidates,
artifact readiness registration, and final collection/task state projection.

One task starts one pipeline run and one versioned collection build. The task id
is the run id; the separate build id is the versioned output identity. The
selected mode is persisted on the build and materializes a dependency graph
into the typed `PipelineRun`. The runner schedules only from that run graph,
while persistence projects its nodes to ordered build-stage rows. Those rows
retain dependencies, errors, warnings, timestamps, execution statistics, and
bounded node output summaries. Artifact registration appends immutable
artifact-version rows for that run. Finalization activates only a successful
newer build; failed or older concurrent builds remain diagnostic history.
Public task and artifact responses remain projections of these relational rows,
not file-backed JSON documents.

An Objective candidate node can succeed with incomplete PaperSkim coverage.
It records the processed and permanently failed Source-unit counts in its output
summary and exposes a node warning. A nonzero permanent failure count finalizes
the task as `partial_success`, while successful candidate Objectives remain part
of the activated build. A build with complete PaperSkim coverage remains
`completed`.

The pipeline layer does not parse documents or extract facts directly. Each
node delegates to the owning implementation module for one concrete step.

Deep Objective analysis is intentionally outside this default build path. Evidence
routing, evidence unit extraction, logic chains, and research-understanding
synthesis run after an Objective is confirmed so one oversized Objective
cannot fail the whole collection build.
