# Research Objective Domain Model Plan

## Summary

This plan records the first backend implementation step for the
research-objective-first direction: fix the Core domain model before adding new
LLM services, parquet artifacts, APIs, or frontend routes.

The immediate goal is narrow:

- add pure Core domain objects for research objectives, paper skims,
  objective-paper frames, and evidence routes
- keep those models independent from pandas, parquet, FastAPI, and LLM schema
  classes
- give later application services one stable domain center instead of putting
  objective semantics directly into another large service

This is a backend Core domain-model plan. It does not implement objective
discovery, objective-scoped fact extraction, API routes, or frontend changes.

Read this with:

- [`../minimal-core-domain-backfill-plan.md`](../minimal-core-domain-backfill-plan.md)
- [`target-centric-collection-extraction-plan.md`](target-centric-collection-extraction-plan.md)
- [`objective-context-targeted-extraction-plan.md`](objective-context-targeted-extraction-plan.md)
- [`../../../../../docs/decisions/rfc-research-objective-first-product-flow.md`](../../../../../docs/decisions/rfc-research-objective-first-product-flow.md)

## Why This Step Comes First

The current Core backbone already has useful domain objects under
`backend/domain/core/`, but much of the active business meaning still lives in
application services. The largest pressure points are:

- paper-fact extraction orchestration and semantic filtering in
  `application/core/semantic_build/paper_facts_service.py`
- comparison semantics and row projection in
  `application/core/comparison_service.py`
- research-view aggregation shape in
  `application/core/research_view_aggregation_service.py`

If objective-first extraction starts by adding another application service, the
new path will repeat the same problem. The service will own LLM calls,
persistence, extraction state, and the business model at the same time.

The first step should therefore define the domain vocabulary in
`backend/domain/core/` before adding the service that reads Source artifacts and
calls the model.

## Scope

This plan covers:

- one new domain module:
  `backend/domain/core/research_objective.py`
- exports from `backend/domain/core/__init__.py`
- focused domain unit tests under `backend/tests/unit/domains/`

This plan does not cover:

- LLM prompt or schema changes
- `paper_skims.parquet` or `research_objectives.parquet`
- objective discovery services
- `paper_facts_service.py` changes
- comparison-service changes
- backend API route changes
- frontend route or UI changes

## Domain Objects

The new module should define four initial records.

### PaperSkim

`PaperSkim` is a coarse reading map for one paper. It is not a final fact
container.

Recommended fields:

- `document_id`
- `title`
- `source_filename`
- `doc_role`
- `candidate_materials`
- `candidate_processes`
- `candidate_properties`
- `changed_variables`
- `possible_objectives`
- `evidence_density`
- `confidence`
- `warnings`

### ResearchObjective

`ResearchObjective` is the objective-shaped analysis unit that should later
replace material as the top-level workspace object.

Recommended fields:

- `objective_id`
- `question`
- `material_scope`
- `process_axes`
- `property_axes`
- `comparison_intent`
- `seed_document_ids`
- `excluded_document_ids`
- `confidence`
- `reason`

The objective must be question-shaped. A bare material name such as
`316L stainless steel` is not a valid objective by itself.

### ObjectivePaperFrame

`ObjectivePaperFrame` describes how one paper relates to one objective.

Recommended fields:

- `frame_id`
- `objective_id`
- `document_id`
- `relevance`
- `paper_role`
- `background`
- `material_match`
- `changed_variables`
- `measured_property_scope`
- `test_environment_scope`
- `relevant_sections`
- `relevant_tables`
- `excluded_tables`

This object is still coarse extraction. It decides where final fact extraction
may run; it does not contain final measurement facts.

### ObjectiveEvidenceRoute

`ObjectiveEvidenceRoute` describes whether a source unit should be extracted
for one objective.

Recommended fields:

- `route_id`
- `objective_id`
- `document_id`
- `source_kind`
- `source_ref`
- `role`
- `extractable`
- `reason`
- `table_schema`
- `column_roles`
- `join_keys`
- `join_plan`
- `confidence`

The initial source kinds should be simple:

- `text_window`
- `table`
- `figure`

The initial roles should be enough to support routing:

- `current_experimental_evidence`
- `process_or_treatment`
- `test_condition`
- `composition_or_background`
- `characterization`
- `literature_comparison`
- `modeling_or_prediction`
- `low_value_or_irrelevant`

### ObjectiveEvidenceUnit

`ObjectiveEvidenceUnit` stores one resolved target-scoped evidence item after
routing and extraction.

Recommended fields:

- `evidence_unit_id`
- `objective_id`
- `document_id`
- `unit_kind`
- `property_normalized`
- `material_system`
- `sample_context`
- `process_context`
- `resolved_condition`
- `test_condition`
- `value_payload`
- `unit`
- `baseline_context`
- `interpretation`
- `source_refs`
- `evidence_anchor_ids`
- `join_keys`
- `resolution_status`
- `confidence`

### ObjectiveLogicChain

`ObjectiveLogicChain` stores the assembled research logic chain for one
objective at paper or cross-paper scope.

Recommended fields:

- `logic_chain_id`
- `objective_id`
- `chain_scope`
- `document_id`
- `question`
- `evidence_unit_ids`
- `chain_payload`
- `summary`
- `confidence`

## Domain Helpers

The same module should include only small pure helpers:

- `build_research_objective_id(question: str) -> str`
- `normalize_objective_terms(value: Any) -> tuple[str, ...]`
- `normalize_objective_confidence(value: Any) -> float`
- `is_question_shaped_objective(objective: ResearchObjective) -> bool`

The objective id should be deterministic and derived from the normalized
question, not random runtime state.

## Boundaries

The domain module must not import:

- pandas
- FastAPI
- parquet or filesystem helpers
- LLM schema classes
- application services
- infra modules

Each domain record should provide:

- `from_mapping(...)`
- `to_record(...)`

Those methods are mapping boundaries only. They should normalize primitive
payloads into domain records and produce plain dictionaries for later
application-level persistence.

## Implementation

Implement the first slice in this order:

1. Add `backend/domain/core/research_objective.py`.
2. Define the objective-first dataclasses and the pure helper functions.
3. Export the new objects and helpers from `backend/domain/core/__init__.py`.
4. Add `backend/tests/unit/domains/test_research_objective_domain.py`.
5. Verify that domain tests pass before adding any LLM or application service.

The implementation should not add wrappers, adapters, or compatibility layers.
Callers should use the domain objects directly when later services are added.

## Verification

Domain tests should cover:

- objective ids are deterministic for the same question
- `ResearchObjective.from_mapping(...).to_record()` preserves normalized
  fields
- `PaperSkim` normalizes `None`, empty strings, repeated strings, and missing
  list fields
- `is_question_shaped_objective(...)` rejects a bare material name and accepts
  a comparison question
- `ObjectivePaperFrame` can represent `high`, `low`, and `irrelevant`
  relevance states
- `ObjectiveEvidenceRoute` can represent extractable and skipped routes for text,
  table, and figure units
- `ObjectiveEvidenceUnit` can preserve resolved evidence payloads
- `ObjectiveLogicChain` can preserve assembled chain payloads

Run:

```bash
cd backend
./.venv/bin/python -m pytest tests/unit/domains/test_research_objective_domain.py
```

Also run from the repository root:

```bash
git diff --check
```

## Exit Criteria

This slice is complete when:

- `backend/domain/core/research_objective.py` exists and has no application,
  LLM, pandas, parquet, or FastAPI dependency
- the new domain objects are exported from `backend/domain/core/__init__.py`
- focused domain tests pass
- no public API, frontend, Source runtime, or paper-facts behavior has changed

After this slice, the next implementation wave can add
`ResearchObjectiveService` and the LLM schemas/prompts that produce
`PaperSkim` and `ResearchObjective` records.
