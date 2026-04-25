# Evidence-Chain Product Surface Backend Implementation Plan

## Summary

This plan records the backend-owned implementation wave for turning the
current paper-facts and comparable-result backbone into dossier-, chain-, and
series-ready read models.

It is the backend implementation companion to the shared evidence-chain
roadmap and contract freeze. It does not replace those shared docs.

## Authority Boundary

- [`../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md`](../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md)
  owns the shared delivery order and acceptance ladder
- [`../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`](../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md)
  owns the shared additive contract for document and result drilldown
- [`../../../specs/api.md`](../../../specs/api.md) remains the long-lived
  backend API authority after the routes land
- this page owns backend file changes, backend verification, and backend-local
  doc sync for the wave

## Purpose

The backend should make one narrow vertical readable as:

- one document with several variant dossiers
- one dossier with several result chains or result-series rows
- one result detail payload that explains one full evidence chain

The first proving slice remains the current narrow PBF-metal direction.

## Read This With

- [`../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md`](../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md)
- [`../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`](../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md)
- [`../../core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../../specs/api.md`](../../../specs/api.md)
- [`../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)

## Non-Goals

This backend wave should not:

- add `variant_dossiers.parquet`, `result_chains.parquet`, or
  `result_series.parquet`
- introduce a second semantic backbone
- make the frontend the owner of semantic grouping rules
- broaden the first delivery wave beyond the narrow proving vertical
- treat downstream experiment-planning generation as trustworthy before
  evidence-chain reconstruction is stable

## Delivery Rule

The backend implementation order is strict:

1. thicken backend facts
2. tighten backend comparability and grouped drilldown semantics
3. sync backend-owned API and plan docs to the landed contract

Frontend should consume additive grouped payloads only after these backend
phases make the semantics explicit.

## Phase 1: Backend Fact Thickening

### Goal

Make `sample_variants`, `test_conditions`, and `measurement_results` thick
enough to support one stable evidence chain.

### Files To Change

Backend Core extraction and persistence:

- `backend/application/core/semantic_build/llm/schemas.py`
- `backend/application/core/semantic_build/llm/prompts.py`
- `backend/application/core/semantic_build/paper_facts_service.py`
- `backend/domain/core/evidence_backbone.py`

Backend extraction test support:

- `backend/tests/support/fake_core_llm_extractor.py`
- `backend/tests/unit/services/test_core_llm_extractor.py`
- `backend/tests/unit/services/test_paper_facts_services.py`

### Expected Changes

`schemas.py`

- expand `ProcessContextPayload`
- expand `TestConditionPayloadModel`
- add value-provenance fields to measurement payloads
- keep condition types such as `rate` and `direction` representable and
  consumable

`prompts.py`

- tighten extraction instructions so process temperature, test temperature, and
  characterization temperature are not merged
- ask for provenance fields only when evidence supports them

`paper_facts_service.py`

- bind condition mentions such as `rate` and `direction`
- materialize thicker process and test payloads
- preserve value origin, source text, unit text, and derivation details

`evidence_backbone.py`

- persist the new fact thickness without adding a new top-level artifact
  family

### Minimum Field Additions

Process and sample state:

- `laser_power_w`
- `scan_speed_mm_s`
- `layer_thickness_um`
- `hatch_spacing_um`
- `energy_density_j_mm3`
- `energy_density_origin`
- `scan_strategy`
- `build_orientation`
- `preheat_temperature_c`
- `shielding_gas`
- `oxygen_level_ppm`
- `powder_size_distribution_um`
- `post_treatment_summary`

Test condition:

- `test_temperature_c`
- `strain_rate_s-1`
- `loading_direction`
- `sample_orientation`
- `environment`
- `frequency_hz`
- `specimen_geometry`
- `surface_state`

Value provenance:

- `value_origin`
- `source_value_text`
- `source_unit_text`
- `derivation_formula`
- `derivation_inputs`

### Verification

```bash
cd backend
uv run pytest tests/unit/services/test_core_llm_extractor.py
uv run pytest tests/unit/services/test_paper_facts_services.py
```

### Exit Criteria

- process, test, and characterization temperature are clearly separated
- current-work measurement results persist provenance fields
- missing rate, direction, and provenance fields stay missing instead of being
  guessed

## Phase 2: Backend Comparability And Public Drilldown

### Goal

Teach the comparable-result layer how to use the thicker facts and carry them
into product-facing read models.

### Files To Change

Backend comparison semantics:

- `backend/domain/core/comparison.py`
- `backend/application/core/comparison_assembly.py`
- `backend/application/core/comparison_service.py`

Backend public schemas and controllers:

- `backend/controllers/schemas/core/documents.py`
- `backend/controllers/schemas/core/results.py`
- `backend/controllers/core/documents.py`
- `backend/controllers/core/results.py`

Backend verification:

- `backend/tests/unit/domains/test_comparison_domain.py`
- `backend/tests/unit/services/test_paper_facts_services.py`
- `backend/tests/integration/test_app_layer_api.py`

### Expected Changes

`comparison.py`

- add PBF-metal missingness rules for orientation, strain rate, baseline type,
  and derived-value provenance

`comparison_assembly.py`

- carry thicker variant, test, and provenance context into
  `ComparableResult`
- keep `claim_scope == current_work` as the default gate for comparison-ready
  paths

`comparison_service.py`

- build grouped document drilldown projections from existing semantic truth
- enrich result detail with parent dossier and chain context

`controllers/schemas/core/documents.py`

- add additive grouped dossier, series, and chain response models
- keep the existing flat `items` list intact

`controllers/schemas/core/results.py`

- add additive result-chain fields such as dossier summary, chain context,
  provenance, and sibling-series navigation

`controllers/core/documents.py`

- expose grouped document comparison semantics through additive query or
  payload fields without breaking the current route

`controllers/core/results.py`

- expose the enriched result detail contract without changing the route family

### Verification

```bash
cd backend
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/integration/test_app_layer_api.py
```

### Exit Criteria

- document drilldown can return grouped dossier and series structure
- result detail can explain one full chain in one payload
- comparability warnings reflect orientation, strain-rate, baseline, and
  provenance gaps

## Phase 3: Backend Contract And Doc Sync

### Goal

Update backend-owned docs once the additive grouped drilldown payloads land.

### Files To Change

- `backend/docs/specs/api.md`
- `backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`
- this family `README.md` and `backend-implementation-plan.md` if ownership or
  reading-path wording changed during delivery

### Expected Changes

- freeze the additive document and result payload in the backend API spec
- keep the narrow PBF-metal plan aligned with the landed backend payload shape
- keep this backend-wide family aligned with the current ownership boundary and
  reading path

### Verification

```bash
python3 scripts/check_docs_governance.py
```

### Exit Criteria

- backend API spec points to the landed additive payload
- backend-local topic docs point back to the shared authorities instead of
  duplicating them

## File Order

The recommended backend implementation order is:

1. `backend/application/core/semantic_build/llm/schemas.py`
2. `backend/application/core/semantic_build/llm/prompts.py`
3. `backend/application/core/semantic_build/paper_facts_service.py`
4. `backend/domain/core/evidence_backbone.py`
5. `backend/domain/core/comparison.py`
6. `backend/application/core/comparison_assembly.py`
7. `backend/application/core/comparison_service.py`
8. `backend/controllers/schemas/core/documents.py`
9. `backend/controllers/schemas/core/results.py`
10. `backend/controllers/core/documents.py`
11. `backend/controllers/core/results.py`
12. `backend/docs/specs/api.md`
13. `backend/docs/plans/core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`
14. backend-wide family docs if the reader path changed during delivery

This order keeps the backend truth ahead of frontend consumption and keeps the
backend doc sync at the end of the code cut.

## Acceptance Checklist

The wave should be considered complete only when all of the following are
true.

- one paper can be projected into stable variant dossiers and result chains
- grouped drilldown can distinguish process temperature, test temperature, and
  characterization temperature
- result detail exposes provenance for reported versus derived values
- comparability warnings reflect orientation, strain-rate, baseline, and
  provenance missingness
- backend document detail and result detail both preserve one-click source
  recovery through anchors
- backend API spec reflects the additive grouped drilldown contract
- no new permanent dossier or chain artifact family was added

## Related Docs

- [`../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md`](../../../../../docs/decisions/rfc-evidence-chain-product-surface-delivery-roadmap.md)
- [`../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`](../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md)
- [`../../core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md`](../../core/pbf-metal-extraction-and-comparison-validation/variant-dossier-and-result-chain-backend-plan.md)
- [`../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md`](../../../../../frontend/src/routes/collections/document-result-evidence-chain-proposal.md)
- [`../../../specs/api.md`](../../../specs/api.md)
