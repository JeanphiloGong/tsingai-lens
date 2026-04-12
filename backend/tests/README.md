Backend test layout:

- `unit/` covers isolated behavior by module boundary such as services, repositories, routers, and support utilities.
- `integration/` covers multi-module flows such as API wiring, task execution, and processing pipelines.
- `e2e/` is reserved for transport-level and websocket scenarios.
- `load/` holds performance and traffic simulation entry points.

The directory structure mirrors the target test module layout so new tests can be added without growing a single flat bucket.
