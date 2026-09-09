Backend test layout:

- `unit/` covers isolated behavior by module boundary such as services, repositories, routers, and support utilities.
- `integration/` covers multi-module flows such as API wiring, Pipeline Run execution, and processing pipelines.
- `e2e/` is reserved for transport-level and websocket scenarios.
- `load/` holds performance and traffic simulation entry points.
- `fixtures/` holds small tracked fixture guidance and local-only fixture
  entry points. Large expert gold-set PDFs and CSV exports belong under the
  git-ignored `fixtures/local_expert_gold/` path.

The directory structure mirrors the target test module layout so new tests can be added without growing a single flat bucket.

Objective workflow tests follow their application responsibilities under
`unit/application/`:

- `test_paper_research_map_service.py` covers per-document research maps.
- `test_objective_candidate_service.py` covers collection-level candidate
  discovery and validation.
- `test_objective_evidence_comparison.py`,
  `test_objective_evidence_extraction.py`, and
  `test_objective_evidence_routing.py` cover confirmed-objective analysis.
- `test_objective_analysis_workflow.py` covers persistence and model-failure
  fallbacks.

Reusable Objective service builders and model doubles live under `support/`;
test modules should not import helpers from other test modules.

## Run A Focused Check

Run commands from `backend/` with the existing development environment:

```bash
.venv/bin/python -m pytest -q tests/unit/services/test_document_preparation_service.py
.venv/bin/python -m pytest -q tests/unit/application/test_paper_research_map_service.py
.venv/bin/python -m pytest -q tests/unit/application/test_research_agent_runner.py
```

For the complete suite, use `.venv/bin/python -m pytest -q tests`. PostgreSQL
tests require `LENS_TEST_DATABASE_URL` to name a dedicated `*_test` database
using the `postgresql+psycopg` driver. They reset that database's schema and run
migrations; never point them at development or production data. Without the
test URL, PostgreSQL cases are skipped, which is not storage acceptance.

See [Objective Analysis Verification](objective-analysis-verification.md) for
the four-paper flow, real P002 Source fixture, numeric table regressions, and
the limits of deterministic model doubles.
