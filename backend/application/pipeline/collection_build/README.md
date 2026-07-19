# Collection Build Pipeline

This package owns the default collection build workflow. It coordinates Source
artifact generation, document profiles, lightweight objective candidates,
artifact readiness registration, and final collection/task state projection.

One task owns one versioned collection build. Pipeline node state is persisted
as ordered build-stage rows, and artifact registration appends immutable
artifact-version rows for that task. Finalization activates only a successful
newer build; failed or older concurrent builds remain diagnostic history.
Public task and artifact responses are projections of these relational rows,
not file-backed JSON documents.

The pipeline layer does not parse documents or extract facts directly. Each
node delegates to the owning implementation module for one concrete step.

Deep goal analysis is intentionally outside this default build path. Evidence
routing, evidence unit extraction, logic chains, and research-understanding
projection run from a confirmed-goal workflow so one oversized goal cannot fail
the whole collection build.
