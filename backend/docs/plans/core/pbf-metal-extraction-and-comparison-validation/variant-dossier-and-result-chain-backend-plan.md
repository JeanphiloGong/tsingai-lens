# Variant Dossier And Result Chain Backend Plan

## Purpose

This document records the backend-local plan for supporting the frontend
reading model built around:

- `variant dossier`
- `result chain`
- `result series`

It narrows one specific backend job inside the broader PBF-metal validation
wave:

- how Core should expose enough semantic thickness for document and result
  drilldown without changing the backbone order

This plan does not redefine the shared Lens v1 product hierarchy and does not
replace the broader execution plan in [`implementation-plan.md`](implementation-plan.md).

## Why This Needs A Separate Backend Plan

The current Core backbone is already pointed in the right direction:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection`

The remaining problem is not that the backend still thinks in summaries.
The remaining problem is that the extracted fact model and read projections are
still too thin for a researcher who needs to reconstruct an experimental
evidence chain.

For the frontend to read a paper as:

- one paper
- several variant dossiers
- several result chains under each dossier
- several result-series rows when only a test-side axis varies

the backend has to do four narrower things better:

1. persist thicker process and test context
2. preserve value provenance and missingness honestly
3. evaluate comparability with PBF-metal review rules instead of only generic
   row readiness
4. expose grouped document and result drilldown payloads without inventing a
   new semantic substrate

## Keep The Backbone Fixed

This plan should not introduce a new permanent top-level artifact family such
as:

- `variant_dossiers.parquet`
- `result_chains.parquet`
- `result_series.parquet`

The first delivery wave should keep the durable Core truth in the existing
artifact family:

- `sample_variants`
- `measurement_results`
- `test_conditions`
- `baseline_references`
- `structure_features`
- `characterization_observations`
- `comparable_results`
- `collection_comparable_results`

The new reading units should be assembled as additive projections over those
artifacts, not as a second semantic backbone.

## Projection Model

### Variant Dossier

The backend should treat a variant dossier as a read projection over one
`SampleVariant` plus its shared linked context.

The dossier should be keyed by `variant_id` and summarize:

- normalized variant label
- material identity
- shared process or sample state
- shared structure evidence when clearly linked
- shared missingness that affects all child chains

### Result Chain

A result chain should be a read projection centered on one
`MeasurementResult`, enriched with:

- parent `variant_id`
- test condition
- baseline
- structure or characterization support
- value provenance
- collection-scoped comparability overlay when available
- source anchors

The first wave should not create a second permanent chain id. The projection
should reuse existing identities:

- `source_result_id` from `measurement_results`
- collection-facing `result_id` that already maps to the current
  `ComparableResult`-backed product contract

### Result Series

A result series should be a grouping over sibling result-chain projections.

The grouping should only happen when:

- `variant_id` is fixed
- property family is fixed
- test family is fixed
- one explicit test-side axis varies

Good first-wave series axes include:

- `test_temperature_c`
- `strain_rate_s-1`
- `hold_time`

The backend should not group rows into one series when the apparent axis is
actually a process or sample-state change.

## Fact Thickening Required For The Projection

The current generic schema is not enough for the dossier and chain read model.
Core needs thicker fields in the owning fact records before grouped drilldown
will be trustworthy.

### Process And Sample State

`SampleVariant.process_context` and related method payloads should grow to
carry the Level 1 PBF-metal fields that affect review and comparison, including
at minimum:

- `laser_power_w`
- `scan_speed_mm_s`
- `layer_thickness_um`
- `hatch_spacing_um`
- `spot_size_um`
- `energy_density_j_mm3`
- `energy_density_origin`
- `scan_strategy`
- `build_orientation`
- `preheat_temperature_c`
- `shielding_gas`
- `oxygen_level_ppm`
- `powder_size_distribution_um`
- `post_treatment_summary`

These fields should remain traceable to anchors. They should not collapse back
into one generic text blob when explicit evidence exists.

### Test Condition

`TestCondition` payloads should carry the fields needed to decide whether two
mechanical results are responsibly comparable, including at minimum:

- `test_method`
- `test_temperature_c`
- `strain_rate_s-1`
- `loading_direction`
- `sample_orientation`
- `environment`
- `frequency_hz`
- `specimen_geometry`
- `surface_state`

The text-window builder should consume mention types such as `rate` and
`direction` instead of discarding them.

### Structure And Observation Context

The chain projection should keep linked structure and characterization support
explicit rather than flattening it into one summary string.

First-wave support should surface:

- porosity or density observations
- residual stress observations
- grain size and texture observations
- phase-state observations
- fracture or failure-surface observations

When an observation was made under a characterization temperature, that
temperature belongs with the observation condition, not with process history
and not with the main mechanical test condition.

### Value Provenance

`MeasurementResult.value_payload` and the stored record shape should preserve
enough provenance for evidence-chain review:

- `value_origin`
  - `reported`
  - `derived`
  - `estimated`
- `source_value_text`
- `source_unit_text`
- `derivation_formula`
- `derivation_inputs`

This is especially important for values such as energy density, where the user
must be able to distinguish:

- author-reported value
- system-derived value from reported parameters
- weakly inferred value that should not drive comparison

## Comparability Policy Upgrades

The current generic comparability policy should be tightened with PBF-metal
review rules that operate on the thicker facts above.

The first wave should add explicit missingness and warning rules for:

- missing `build_orientation` on orientation-sensitive properties
- missing `strain_rate_s-1` on tensile-style properties
- missing test direction on tensile or residual-stress results
- missing or unresolved baseline on improvement-style claims
- mixed heat-treatment states treated as if they were one variant
- derived energy density without enough source parameters to verify the
  derivation
- value-origin mismatches where a display row would otherwise hide that the
  number is derived

The policy should continue to respect the current rule that only
`claim_scope == current_work` enters the default `ComparableResult` path.

## Document And Result Drilldown Contract

The first wave should support the new frontend reading model through additive
projection fields, not through a breaking route rewrite.

### Document Comparison Semantics

`GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`
should remain the document-first semantic inspection route.

The additive plan for this route is:

- keep the existing `items` list intact
- add optional grouped projections when requested

Suggested additive payload shape:

```json
{
  "collection_id": "col_x",
  "document_id": "doc_x",
  "count": 6,
  "items": [],
  "variant_dossiers": [
    {
      "variant_id": "var_x",
      "variant_label": "optimized VED + HIP",
      "material": {},
      "shared_process_state": {},
      "shared_missingness": [],
      "series": [
        {
          "series_key": "tensile:test_temperature_c",
          "property_family": "tensile",
          "test_family": "tensile",
          "varying_axis": {
            "axis_name": "test_temperature_c",
            "axis_unit": "C"
          },
          "chains": [
            {
              "source_result_id": "mr_x",
              "result_id": "cmp_x",
              "measurement": {},
              "test_condition": {},
              "baseline": {},
              "assessment": {},
              "value_provenance": {},
              "evidence": {}
            }
          ]
        }
      ]
    }
  ]
}
```

This grouped view should be derived from the same underlying semantic facts as
the flat `items` list. The frontend should not receive two conflicting truths.
The naming and field boundary for this additive payload should follow the
shared contract freeze in
`docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`.

### Result Detail

`GET /api/v1/collections/{collection_id}/results/{result_id}` should remain the
product-facing result contract.

The additive plan for this route is to enrich the existing detail projection
with:

- parent variant dossier summary
- chain-local test condition
- explicit baseline detail
- explicit value provenance
- linked structure support summary
- sibling result-series navigation when the same variant has other chains in
  the same property and test family

This keeps the public product model intact:

`comparison row -> result -> document`

while making the result page readable as one evidence chain instead of one
isolated measurement card.

## Delivery Slices

### Slice 1: Fact Thickening

Goal:

- make `sample_variants`, `test_conditions`, and `measurement_results` thick
  enough to express a PBF-metal evidence chain

Owned file areas:

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/llm/prompts.py`
- `domain/core/evidence_backbone.py`
- `application/core/semantic_build/paper_facts_service.py`
- `tests/unit/services/test_paper_facts_services.py`

Verification:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
```

### Slice 2: Comparability Policy

Goal:

- teach `ComparableResult` assessment about PBF-metal missingness and value
  provenance

Owned file areas:

- `domain/core/comparison.py`
- `application/core/comparison_assembly.py`
- `tests/unit/domains/test_comparison_domain.py`
- `tests/unit/services/test_paper_facts_services.py`

Verification:

```bash
cd backend
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/unit/services/test_paper_facts_services.py
```

### Slice 3: Grouped Drilldown Projection

Goal:

- expose dossier, chain, and series projections from the existing semantic
  truth without creating a second artifact family

Owned file areas:

- `application/core/comparison_service.py`
- `controllers/core/documents.py`
- `application/core/result_service.py` if result detail projection needs
  additive chain context
- `backend/docs/specs/api.md`
- `tests/integration/test_app_layer_api.py`

Verification:

```bash
cd backend
uv run pytest tests/integration/test_app_layer_api.py
```

### Slice 4: Gold-Corpus Validation

Goal:

- prove that the backend can reconstruct stable evidence-chain projections on
  the narrow PBF-metal corpus before broader rollout

Checks:

- repeated runs keep the same dossier grouping for the same paper
- repeated runs keep the same current-work chain identity
- missing fields are marked as missing rather than hallucinated
- grouped drilldown can distinguish process temperature, test temperature, and
  characterization temperature
- comparable versus limited judgments reflect orientation, strain-rate, and
  baseline gaps

## Exit Criteria

This backend slice is done only when all of the following are true:

1. the persistent Core truth remains the current paper-facts and
   comparable-result backbone
2. no new permanent artifact family was added for dossier, chain, or series
3. one document can be projected into stable variant dossiers and result
   chains
4. one result detail response can explain the parent variant, test context,
   structure support, baseline, and provenance in one payload
5. missingness and value-origin warnings are explicit enough that the frontend
   does not need to guess

## Related Docs

- [`README.md`](README.md)
  Topic-family reading order for the PBF-metal validation wave
- [`proposal.md`](proposal.md)
  Why the narrow PBF-metal validation wave exists
- [`parameter-registry-and-variant-report-scope.md`](parameter-registry-and-variant-report-scope.md)
  First-wave field boundary for the variant-facing report surface
- [`implementation-plan.md`](implementation-plan.md)
  Broader executable implementation plan for the whole PBF-metal wave
- [`../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)
  Frontend-local reading model that this backend plan supports
