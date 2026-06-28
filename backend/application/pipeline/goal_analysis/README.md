# Goal Analysis Pipeline

This package owns confirmed-goal deep analysis orchestration.

Collection build produces Source artifacts, document profiles, and lightweight
objective candidates. This pipeline starts after a user or benchmark confirms
one goal, then runs the goal-scoped evidence analysis and persists a
`ResearchUnderstanding` with `scope_type=goal`.

The pipeline layer does not extract evidence directly. Nodes delegate to the
owning Core semantic build services.

The HTTP `POST .../analysis` route starts this pipeline in the background and
returns the current confirmed-goal state immediately. Runtime progress is
persisted on `ConfirmedGoal.analysis_progress`, so clients can poll
`GET .../analysis` to show the active phase and paper while the pipeline runs.

Stage reuse is owned by Core facts, not by pipeline node state. If
confirmed-goal analysis fails after an intermediate Core stage, a later run
keeps the same pipeline order but `ResearchObjectiveService` reuses persisted
paper frames, evidence routes, evidence units, or logic chains for the active
objective before building the next missing stage.
