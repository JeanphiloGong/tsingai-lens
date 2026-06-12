# Collection Build Pipeline

This package owns the collection build workflow. It coordinates Source artifact
generation, Core semantic build steps, artifact readiness registration, and
final collection/task state projection.

The pipeline layer does not parse documents or extract facts directly. Each
node delegates to the owning implementation module for one concrete step.
