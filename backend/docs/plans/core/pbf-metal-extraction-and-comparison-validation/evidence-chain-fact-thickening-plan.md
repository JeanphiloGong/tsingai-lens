# Evidence-Chain Fact Thickening Plan

## Summary

This plan records the next backend Core implementation wave after the
document/result evidence-chain read projection.

The read projection now gives the frontend additive fields such as:

- `variant_dossiers`
- `series`
- `chains`
- `test_condition_detail`
- `baseline_detail`
- `structure_support`
- `value_provenance`
- `series_navigation`

The remaining backend problem is upstream fact quality. The projection can
read PBF-metal fields, but the current extraction schema, prompts,
normalization, and comparability policy do not yet produce those fields
reliably.

The goal of this page is to turn the next backend work into an executable
PBF-metal fact-thickening plan.

## Scope

This wave is intentionally narrow. It targets PBF-metal literature, especially
LPBF, SLM, PBF-LB/M, and closely related metal powder-bed fusion papers.

This wave should not make Lens a PBF-only product. It should add PBF-metal
thickness inside the existing Core fact records so the evidence-chain
projection can become stable enough for researcher review.

The durable backbone remains:

```text
document_profiles
-> paper facts family
-> comparable_results
-> collection_comparable_results
-> row projection
```

This wave must not add a new permanent artifact family such as:

- `variant_dossiers.parquet`
- `result_chains.parquet`
- `result_series.parquet`

## Current Backend State

The current read projection can already assemble dossier and chain payloads
from existing artifacts.

What is still too thin:

- `ProcessContextPayload` mostly carries generic `temperatures_c`,
  `durations`, and `atmosphere`.
- `TestConditionPayloadModel` mostly carries generic method, temperature,
  duration, and atmosphere fields.
- `MeasurementValuePayload` does not preserve enough value provenance for
  evidence-chain review.
- `ComparisonAssembler` can summarize generic process and test condition
  payloads, but it does not yet normalize PBF-metal context into stable
  comparison identities and readable summaries.
- `evaluate_comparison_assessment()` still uses generic missingness rules
  instead of PBF-metal review rules.

The next backend work should thicken those facts before adding broader
collection aggregation.

## PBF-Metal Field Boundary

### Process And Sample State

Add these fields to the process/sample-state payload carried by
`SampleVariant.process_context` and related method payloads:

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

These fields belong to the variant or process state. They should appear in
`variant_dossier.shared_process_state` when extracted and linked.

### Test Condition

Add these fields to the test-condition payload carried by
`TestCondition.condition_payload`:

- `test_method`
- `test_temperature_c`
- `strain_rate_s-1`
- `loading_direction`
- `sample_orientation`
- `environment`
- `frequency_hz`
- `specimen_geometry`
- `surface_state`

The Python model should use a legal internal field name for strain rate, such
as `strain_rate_s_1`, with a Pydantic alias of `strain_rate_s-1` where needed.
The API-facing evidence-chain contract should continue using the frozen
`strain_rate_s-1` key.

### Value Provenance

Add these fields to `MeasurementResult.value_payload`:

- `value_origin`
- `source_value_text`
- `source_unit_text`
- `derivation_formula`
- `derivation_inputs`

Allowed `value_origin` values for this wave:

- `reported`
- `derived`
- `estimated`

This distinction is required for values such as volumetric energy density,
where the reviewer needs to know whether the number was author-reported,
system-derived from reported inputs, or weakly estimated.

## Temperature Ownership Rules

Temperature fields must remain separated by scientific role:

- `preheat_temperature_c` belongs in process state.
- `test_temperature_c` belongs in test condition.
- characterization temperature belongs with the characterization observation
  condition and must not be copied into process state or mechanical test
  condition.

This separation is necessary for stable series grouping. A tensile temperature
series should group result chains under the same variant. A changed preheat or
post-treatment state should split the variant dossier instead.

## Delivery Slices

### Slice 1: PBF Fact Schema Thickening

Goal:

Make the extraction schema legally accept the PBF-metal fields needed by the
evidence-chain projection.

Owned file areas:

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/paper_facts_service.py`
- `tests/unit/services/test_paper_facts_services.py`

Implementation notes:

- Extend `ProcessContextPayload` with PBF process/sample-state fields.
- Extend `TestConditionPayloadModel` with mechanical and physical test fields.
- Extend `MeasurementValuePayload` with value provenance fields.
- Keep strict model validation. Unknown extras should still be rejected.
- Preserve storage and restore behavior through existing paper-facts artifact
  columns.

Verification:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
```

Exit criteria:

- PBF process fields survive model validation and artifact normalization.
- PBF test fields survive model validation and artifact normalization.
- value provenance fields survive model validation and artifact normalization.
- Existing generic extraction tests remain green.

### Slice 2: Prompt And JSON Guidance

Goal:

Teach the extractor where PBF-metal facts belong without encouraging
ungrounded numeric extraction.

Owned file areas:

- `application/core/semantic_build/llm/prompts.py`
- `application/core/semantic_build/llm/schemas.py`
- `tests/unit/services/test_core_llm_extractor.py`
- `tests/unit/services/test_paper_facts_services.py`

Implementation notes:

- Update valid JSON examples to include PBF process fields.
- Add examples for tensile test condition fields.
- Add examples for `value_origin`, `source_value_text`, and
  `source_unit_text`.
- Keep the rule that `unit` belongs at `measurement_results[*].unit`, not
  inside `value_payload`.
- Explicitly separate process temperature, test temperature, and
  characterization temperature.
- Tell the model to omit weakly grounded fields rather than infer missing
  values.

Verification:

```bash
cd backend
uv run pytest tests/unit/services/test_core_llm_extractor.py
uv run pytest tests/unit/services/test_paper_facts_services.py
```

Exit criteria:

- Prompt examples match the schema.
- Invalid examples still reject non-schema keys and misplaced units.
- The extractor can emit PBF process/test/provenance fields without schema
  errors.

### Slice 3: Assembly And Normalization

Goal:

Make extracted PBF fields affect comparable-result identity, readable
summaries, and evidence-chain grouping correctly.

Owned file areas:

- `application/core/comparison_assembly.py`
- `domain/core/comparison.py` only if identity payloads or normalized context
  types need domain support
- `tests/unit/services/test_paper_facts_services.py`
- `tests/unit/domains/test_comparison_domain.py`

Implementation notes:

- Update `normalize_process()` so PBF parameters produce readable process
  summaries, for example:

```text
LPBF, P=280 W, v=1200 mm/s, h=100 um, t=30 um, HIP
```

- Update `summarize_test_condition()` so tensile and fatigue fields produce
  readable test summaries, for example:

```text
tensile, 25 C, strain_rate=0.001 s^-1, vertical
```

- Ensure process-side changes stay in variant/process identity.
- Ensure test-side changes stay in test-condition identity.
- Ensure value provenance is preserved and available to result detail.

Verification:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/unit/domains/test_comparison_domain.py
```

Exit criteria:

- Different `test_temperature_c` values do not create different variant
  dossiers by themselves.
- Different `post_treatment_summary` or other process-state changes are not
  collapsed into one process state.
- `strain_rate_s-1` and loading/sample directions remain test-side context.
- `value_origin` and source-value fields are not lost during comparison
  assembly.

### Slice 4: PBF Comparability Policy

Goal:

Make collection-scoped assessment reflect PBF-metal review limits instead of
only generic row readiness.

Owned file areas:

- `domain/core/comparison.py`
- `application/core/comparison_assembly.py`
- `tests/unit/domains/test_comparison_domain.py`
- `tests/unit/services/test_paper_facts_services.py`

First rules:

- tensile-style results missing `strain_rate_s-1` should be `limited`
- tensile-style results missing `loading_direction` should be `limited`
- tensile-style results missing `sample_orientation` should be `limited`
- orientation-sensitive results missing `build_orientation` should be
  `limited`
- improvement-style claims missing a resolved baseline should not be marked
  fully comparable
- `energy_density_origin == "derived"` should create a warning
- `energy_density_origin == "estimated"` should require expert review
- mixed heat-treatment state under one variant should create a warning when
  detected

These rules should populate:

- `assessment.missing_critical_context`
- `assessment.comparability_warnings`
- `assessment.comparability_basis`
- `assessment.requires_expert_review`
- `assessment.comparability_status`

Verification:

```bash
cd backend
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/unit/services/test_paper_facts_services.py
```

Exit criteria:

- Missing strain rate no longer yields a fully comparable tensile result.
- Missing loading direction or sample orientation is visible to callers.
- baseline gaps are explicit.
- reported, derived, and estimated values are distinguishable in assessment
  output.

### Slice 5: PBF Acceptance Fixture

Goal:

Lock the fact-thickening work against one minimal PBF-metal evidence-chain
fixture.

Owned file areas:

- `tests/unit/services/test_paper_facts_services.py`
- `tests/unit/domains/test_comparison_domain.py`
- `tests/unit/routers/test_documents_api.py`
- `tests/unit/routers/test_results_api.py`
- a backend-local fixture path if the fixture becomes too large for inline
  tests

Fixture shape:

```text
Material:
Ti-6Al-4V

Variant S2:
optimized VED, no HIP

Variant S3:
optimized VED + HIP

Process:
P=280 W
v=1200 mm/s
h=100 um
t=30 um
VED=78 J/mm3
energy_density_origin=reported
build_orientation=vertical

Tests:
tensile at 25 C
tensile at 200 C
strain_rate=1e-3 s^-1
loading_direction=vertical
sample_orientation=vertical

Structure:
porosity=0.1%
residual stress lower

Results:
YS=940 MPa at 25 C
YS=820 MPa at 200 C
EL=15%

Baseline:
S2 optimized VED without HIP
```

Acceptance assertions:

- S3 becomes one `variant_dossier`.
- 25 C and 200 C tensile results become one result series.
- `series_key == "yield_strength:test_temperature_c"`.
- process fields appear in `shared_process_state`.
- test fields appear in `test_condition_detail`.
- porosity appears in `structure_support`.
- reported values appear in `value_provenance`.
- S2 appears in `baseline_detail`.
- missing strain rate triggers limited comparability.

Verification:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/unit/routers/test_documents_api.py
uv run pytest tests/unit/routers/test_results_api.py
```

Exit criteria:

- The backend can reconstruct a single-paper PBF evidence chain without
  frontend inference.
- Missingness and provenance are visible in the API payloads.
- The fixture can distinguish process variation from test-condition variation.

## Suggested Commit Sequence

The work should be split into reviewable backend commits:

```text
feat(core): thicken PBF fact schema
feat(core): normalize PBF comparison context
feat(core): add PBF comparability acceptance
```

The first commit should focus on schema and prompt legality. The second should
make assembly and projection consume the new fields. The third should add
assessment behavior and acceptance coverage.

## Non-Goals

This wave should not:

- add a new top-level browser resource
- add a permanent PBF-only artifact family
- build collection-level material synthesis
- redesign graph, report, or protocol surfaces
- turn the parameter registry into a wide UI table
- generalize the field set to all materials domains

## Verification Summary

For the full wave, run:

```bash
cd backend
uv run pytest tests/unit/services/test_core_llm_extractor.py
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/unit/routers/test_documents_api.py
uv run pytest tests/unit/routers/test_results_api.py
python3 ../scripts/check_docs_governance.py
```

## Related Docs

- [`README.md`](README.md)
  Topic-family reading order for the PBF-metal validation wave
- [`implementation-plan.md`](implementation-plan.md)
  Broader executable implementation plan for the whole PBF-metal validation
  wave
- [`variant-dossier-and-result-chain-backend-plan.md`](variant-dossier-and-result-chain-backend-plan.md)
  Backend-local plan for dossier, chain, and series read projections
- [`parameter-registry-and-variant-report-scope.md`](parameter-registry-and-variant-report-scope.md)
  First-version PBF parameter boundary and variant report scope
- [`../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md`](../../../../../docs/decisions/rfc-document-result-evidence-chain-contract-freeze.md)
  Shared additive contract freeze for document and result drilldown
