# Goal Analysis Pipeline

This package owns confirmed-goal deep analysis orchestration.

Collection build produces Source artifacts, document profiles, and lightweight
objective candidates. This pipeline starts after a user or benchmark confirms
one goal, then runs the goal-scoped evidence analysis and persists a
`ResearchUnderstanding` with `scope_type=goal`.

The pipeline layer does not extract evidence directly. Nodes delegate to the
owning Core semantic build services.
