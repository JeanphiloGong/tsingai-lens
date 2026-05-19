Backend test layout:

- `unit/` covers isolated behavior by module boundary such as services, repositories, routers, and support utilities.
- `integration/` covers multi-module flows such as API wiring, task execution, and processing pipelines.
- `e2e/` is reserved for transport-level and websocket scenarios.
- `load/` holds performance and traffic simulation entry points.
- `fixtures/` holds small tracked fixture guidance and local-only fixture
  entry points. Large expert gold-set PDFs and CSV exports belong under the
  git-ignored `fixtures/local_expert_gold/` path.

The directory structure mirrors the target test module layout so new tests can be added without growing a single flat bucket.
