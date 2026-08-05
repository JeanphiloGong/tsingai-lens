Backend test layout:

- `unit/` covers isolated behavior by module boundary such as services, repositories, routers, and support utilities.
- `integration/` covers multi-module flows such as API wiring, task execution, and processing pipelines.
- `e2e/` is reserved for transport-level and websocket scenarios.
- `load/` holds performance and traffic simulation entry points.
- `fixtures/` holds small tracked fixture guidance and local-only fixture
  entry points. Large expert gold-set PDFs and CSV exports belong under the
  git-ignored `fixtures/local_expert_gold/` path.

The directory structure mirrors the target test module layout so new tests can be added without growing a single flat bucket.

Objective workflow tests follow their application responsibilities under
`unit/application/`:

- `test_paper_skim_service.py` covers per-document research maps.
- `test_objective_candidate_service.py` covers collection-level candidate
  discovery and validation.
- `test_objective_evidence_comparison.py`,
  `test_objective_evidence_extraction.py`, and
  `test_objective_evidence_routing.py` cover confirmed-objective analysis.
- `test_objective_analysis_workflow.py` covers persistence and model-failure
  fallbacks.

Reusable Objective service builders and model doubles live under `support/`;
test modules should not import helpers from other test modules.
