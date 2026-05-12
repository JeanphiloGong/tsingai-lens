# Objective Evidence Unit Cutover Plan

## Summary

Core should cut the objective-first flow over to `ObjectiveEvidenceUnit` as the
authoritative semantic fact layer.

The target flow is:

```text
Source artifacts
  -> ResearchObjective / ObjectivePaperFrame / ObjectiveEvidenceRoute
  -> ObjectiveEvidenceUnit
  -> ObjectiveLogicChain
  -> comparison, evidence-card, report, and workspace projections
```

This is not a compatibility projection from old paper-wide facts into a new
shape. The old `measurement_results`, `sample_variants`, `test_conditions`,
`characterization_observations`, and pairwise-comparison records may be used as
implementation reference while cutting over, but they should not remain the
long-term Core semantic fact surface.

The cutover must preserve the already-proven P001 table result behavior:

- 80 table measurement facts exactly match the expert gold set.
- 3 method-family test conditions are present.
- 8 characterization observations are present.
- 19 pairwise comparison relations are present.

The new acceptance target is that those facts are represented directly as
objective-scoped evidence units with traceable source references and join keys.

Read this with:

- [`target-centric-collection-extraction-plan.md`](target-centric-collection-extraction-plan.md)
- [`research-objective-domain-model-plan.md`](research-objective-domain-model-plan.md)
- [`objective-context-targeted-extraction-plan.md`](objective-context-targeted-extraction-plan.md)
- [`p001-remaining-gold-gap-repair-plan.md`](p001-remaining-gold-gap-repair-plan.md)

## Why This Cutover Is Needed

The current Core fact extraction path can already extract important P001
facts, including the 80 table measurement results. That path is still
paper-wide in its final data ownership: downstream services consume
paper-level fact families and then infer their relevance to comparison or
workspace views.

The objective-first plan changes the ownership center. The system should not
only know that a paper contains a measurement. It should know which research
objective that measurement supports, which route admitted it, which source
table or text window it came from, which sample and process context it joins
to, and how it participates in a research logic chain.

Without this cutover, the repository would carry two semantic centers:

- old paper-fact families that downstream services still treat as primary
- new objective records that route evidence but do not own final evidence

That split would preserve the same ambiguity the objective-first flow is meant
to remove.

## Target Data Shape

`ObjectiveEvidenceUnit` becomes the primary Core fact record.

The first complete unit kinds are:

- `sample_context`
- `process_context`
- `test_condition`
- `measurement`
- `characterization`
- `comparison`
- `interpretation`

Every unit should carry:

- `objective_id`
- `document_id`
- `unit_kind`
- `property_normalized` when applicable
- `sample_context`
- `process_context`
- `resolved_condition`
- `test_condition`
- `value_payload`
- `baseline_context`
- `source_refs`
- `evidence_anchor_ids`
- `join_keys`
- `resolution_status`

`ObjectiveLogicChain` then assembles paper-level and cross-paper reasoning over
these units. Comparison rows, evidence cards, report sections, and workspace
payloads are projections from units and chains.

## Delivery Slices

### 1. Objective-Scoped Evidence Builder

Add a Core semantic-build step that runs after objective routing.

Inputs:

- `ResearchObjective`
- `ObjectiveContext`
- `ObjectivePaperFrame`
- `ObjectiveEvidenceRoute`
- Source blocks, tables, table rows, and table cells

Rules:

- Process only routes with `extractable=True`.
- Skip `low_value_or_irrelevant` routes.
- Use route `source_kind` and `source_ref` as the source boundary.
- Emit `ObjectiveEvidenceUnit` directly.
- Do not write old paper-fact rows as the final output of this step.

Expected owning files:

- `backend/application/core/semantic_build/research_objective_service.py`
- `backend/application/core/semantic_build/llm/prompts.py`
- `backend/application/core/semantic_build/llm/schemas.py`
- `backend/application/core/semantic_build/llm/extractor.py`
- `backend/domain/core/research_objective.py`
- `backend/infra/persistence/sqlite/core_fact_repository.py`

### 2. P001 Table Evidence Units

Move the proven P001 table extraction behavior into objective evidence units.

Table 1 should produce:

- 16 `sample_context` units
- 16 `process_context` units
- 16 `measurement` units for relative density

Table 2 should produce:

- 64 `measurement` units for yield strength, ultimate tensile strength,
  elongation, and microhardness

The builder should join Table 1 and Table 2 with `Condition number` and
`Sample number`. Each measurement unit should preserve source table, sample,
condition, property, value, unit, and evidence anchors.

Acceptance:

- P001 produces 80 table measurement units.
- The 80 table measurement units match the expert gold values exactly.
- The previous 80/80 table result validation does not regress while the cutover
  is in progress.

### 3. Method and Characterization Units

Create objective-scoped units for method-family conditions and qualitative
observations.

P001 target units:

- 3 `test_condition` units
  - tensile testing
  - microhardness testing
  - density, porosity, and microstructure characterization
- 8 `characterization` units aligned with the current P001 gold categories

The characterization units should combine route-scoped text and table-derived
facts. They should not create duplicate scalar measurement units for narrative
claims.

Acceptance:

- P001 produces 3 test-condition units.
- P001 produces 8 characterization units.
- The units carry source references to the relevant text windows, figures, or
  tables.

### 4. Comparison Units

Generate pairwise comparisons directly from objective evidence units.

Comparison units should include:

- current sample
- comparison sample
- changed process axis
- held process context
- property
- current and comparison values
- direction
- source references

The first implementation should preserve the P001 shape:

- same-speed and same-energy-density scan-strategy comparisons
- same-energy-density and same-strategy scan-speed comparisons
- relative-density and mechanical-property comparisons

Acceptance:

- P001 produces 19 comparison units.
- Existing `BaselineReference` semantics are not reused for sample-pair
  comparisons.
- Every comparison unit traces back to table evidence.

### 5. Logic Chain Assembly

Build `ObjectiveLogicChain` from the evidence units.

The first chain should be paper scoped:

```text
objective
  -> sample and process context
  -> measurement units
  -> method and characterization units
  -> comparison units
  -> summary claim with evidence_unit_ids
```

Acceptance:

- Each P001 objective has at least one paper-scoped logic chain.
- Logic chains reference objective evidence unit ids, not old paper-fact ids as
  their primary evidence set.
- The summary remains traceable to concrete units.

### 6. Downstream Cutover

After the vertical slice is stable, downstream services should read objective
units and chains directly.

Services to update:

- `backend/application/core/comparison_service.py`
- `backend/application/core/research_view_aggregation_service.py`
- `backend/application/core/workspace_overview_service.py`
- `backend/application/derived/core_fact_projection.py`
- export and evaluation scripts under `backend/scripts/evaluation/`
- API tests and fixtures that currently seed old fact families

The new flow should not keep a long-term fallback where downstream services
try old paper facts first and objective units second. During the transition,
tests may keep old fixtures as comparison references, but production code
should converge on objective units and chains as the direct input.

## Retiring Old Fact Families

Once downstream services no longer read the old families as primary inputs,
remove the old semantic fact surface rather than leaving a parallel contract.

Retirement targets:

- `core_measurement_results`
- `core_sample_variants`
- `core_test_conditions`
- `core_baseline_references`
- `core_characterization_observations`
- `core_pairwise_comparison_relations`

Retirement should include:

- repository table specs and persistence round-trip tests
- domain exports no longer used by production paths
- artifact readiness flags that describe old families as primary outputs
- fixtures and tests that assert old fact rows as the final product
- docs that describe old paper-fact families as the current authoritative
  semantic layer

Historical plans may keep the old names as lineage, but current architecture
and implementation docs should point to objective evidence units and logic
chains.

## Verification

Use P001 as the first non-negotiable vertical slice.

Minimum checks:

- objective discovery still produces the two P001 objectives
- evidence routing includes the two P001 tables and relevant method or
  characterization windows
- objective evidence units include:
  - 16 sample-context units
  - 16 process-context units
  - 3 test-condition units
  - 80 table measurement units
  - 8 characterization units
  - 19 comparison units
- the 80 measurement units match expert gold exactly
- each unit has `objective_id`, `document_id`, `source_refs`, and usable
  `join_keys`
- logic chains reference unit ids and remain traceable to Source artifacts

Use the existing single-paper probe and expert-gold regression results as the
baseline evidence for parity:

- `/home/chenhm/.application/date/2026/may/week3/12,Tue/full_single_paper_runs/20260512-170419-P001-Effect-of-energy-density-and-scanning-strategy-on-densification-microstruct-2155717a/single_paper_extraction_probe.md`
- `/home/chenhm/.application/date/2026/may/week3/12,Tue/full_gold_regression_runs/20260512-184706-P001-P006-full-gold-regression/evaluation_report.json`

The cutover is complete only when production code no longer consumes the old
paper-fact families as the authoritative semantic fact layer.

## Risks

The main risk is mistaking the old P001 table success for proof that the new
objective layer is unnecessary. The old extraction proves that Source table
parsing and table fact extraction can work. It does not provide objective
ownership, route-scoped evidence admission, or logic-chain assembly.

The second risk is leaving both systems alive. A dual semantic surface would
make downstream behavior hard to reason about and would let future fixes land
in the wrong layer. The migration may use old outputs as regression references,
but the implemented end state should be one objective-centric Core fact path.
