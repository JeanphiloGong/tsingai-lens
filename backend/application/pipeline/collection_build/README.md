# Collection Build Pipeline

This package owns the default collection build workflow. It coordinates Source
artifact generation, document profiles, lightweight objective candidates,
artifact readiness registration, and final collection/task state projection.

The pipeline layer does not parse documents or extract facts directly. Each
node delegates to the owning implementation module for one concrete step.

Deep goal analysis is intentionally outside this default build path. Evidence
routing, evidence unit extraction, logic chains, and research-understanding
projection run from a confirmed-goal workflow so one oversized goal cannot fail
the whole collection build.
