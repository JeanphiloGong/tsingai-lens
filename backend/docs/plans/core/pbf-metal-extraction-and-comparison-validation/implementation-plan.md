# PBF-Metal Extraction And Comparison Validation Implementation Plan

## Summary

This document turns the PBF-metal validation proposal into an executable Core
delivery plan.

The plan keeps one rule fixed throughout execution:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection`

This wave should not expand the architecture. It should tighten the current
Core path until it is fast enough and precise enough to support PBF-metal
comparison work on a small fixed corpus.

Read this plan with:

- [`README.md`](README.md)
- [`proposal.md`](proposal.md)
- [`../core-parsing-quality-hardening-plan.md`](../core-parsing-quality-hardening-plan.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)

## Delivery Shape

This wave should ship in four implementation slices plus one acceptance slice.

1. Freeze the semantic center and benchmark baseline.
2. Reduce extraction cost on the current Core path.
3. Add the narrow PBF-metal semantic extension.
4. Tighten comparable-result assembly and comparability rules.
5. Lock the wave against the fixed PBF-metal gold corpus.

Each slice should be independently reviewable and verifiable.

## Slice 1: Baseline And Semantic-Center Freeze

### Goal

Start the wave from one fixed semantic contract and one measurable extraction
baseline.

### Changes

- align shared and backend docs so they describe the same semantic backbone
- preserve the current known-slow collection as a benchmark reference
- define the initial PBF-metal corpus manifest and failure taxonomy
- identify which extraction units are currently being sent to the model on the
  known slow path

### Owned file areas

- `README.md`
- `docs/contracts/lens-v1-definition.md`
- `docs/contracts/lens-core-artifact-contracts.md`
- `backend/docs/architecture/overview.md`
- `backend/docs/architecture/core-comparison/current-state.md`
- `backend/docs/specs/api.md`
- `backend/tests/fixtures/` or a nearby backend-local fixture subtree for the
  PBF-metal corpus manifest
- `tests/unit/services/test_paper_facts_services.py`

### Verification

Run:

```bash
cd backend
python3 ../scripts/check_docs_governance.py
uv run pytest tests/unit/services/test_paper_facts_services.py
```

Record before-change measurements for:

- extraction unit count per document
- average text-window call time
- average table-row call time
- whole-document extraction time on the known slow collection

### Exit criteria

- active docs point to one semantic center
- the benchmark corpus and failure taxonomy are fixed enough to compare later
  slices
- current latency and call-count numbers are written down before changing the
  extraction path

## Slice 2: Extraction Cost Reduction

### Goal

Cut the number and cost of Core extraction calls before adding more vertical
schema detail.

### Changes

- add deterministic candidate pruning in
  `application/core/semantic_build/paper_facts_service.py`
- skip clearly low-value blocks such as references, acknowledgements, and
  most introduction-only history windows
- make table rows the default parameter-first extraction unit for PBF-metal
  papers
- reduce text windows to supporting context for method or result enrichment
- replace provider-native strict structured output with JSON text plus local
  Pydantic validation in `application/core/semantic_build/llm/extractor.py`
- add bounded concurrency for extraction calls while keeping
  `_materialize_bundle()` ordered and deterministic

### Owned file areas

- `application/core/semantic_build/llm/extractor.py`
- `application/core/semantic_build/llm/prompts.py`
- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/paper_facts_service.py`
- `tests/support/fake_core_llm_extractor.py`
- `tests/unit/services/test_paper_facts_services.py`

### Verification

Run:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/integration/services/test_task_runner.py
```

Then rerun the benchmark collection and compare:

- extraction unit count
- average call time
- whole-document extraction time

### Exit criteria

- the known slow collection no longer sends exhaustive low-value windows to the
  model
- the per-call path returns on a seconds-scale budget rather than the current
  tens-of-seconds structured-output path
- ordered materialization still produces stable artifact shapes

## Slice 3: Narrow PBF-Metal Semantic Extension

### Goal

Add only the PBF-metal fields needed for reliable comparison, without creating
another permanent module tree yet.

### Changes

- extend `MethodFact`, `SampleVariant`, `TestCondition`, or
  `MeasurementResult` payloads only where PBF-metal structure is needed
- add explicit support for process parameters such as:
  - `laser_power_w`
  - `scan_speed_mm_s`
  - `layer_thickness_um`
  - `hatch_spacing_um`
  - `spot_size_um`
  - `energy_density_j_mm3`
  - `scan_strategy`
  - `build_orientation`
  - `preheat_temperature_c`
  - `shielding_gas`
  - `oxygen_level_ppm`
  - `powder_size_distribution_um`
- normalize PBF-metal result/property identities for:
  - `relative_density_percent`
  - `porosity_percent`
  - `residual_stress_mpa`
  - `yield_strength_mpa`
  - `ultimate_tensile_strength_mpa`
  - `elongation_percent`
  - `hardness_hv`
  - `surface_roughness_ra_um`
- add `claim_scope` and `value_origin` support to `measurement_results`
- preserve `source_value_text`, `source_unit_text`, and `derivation_formula`
  when a value is not directly reported

### Owned file areas

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/llm/prompts.py`
- `domain/core/evidence_backbone.py`
- `application/core/semantic_build/paper_facts_service.py`
- `tests/support/fake_core_llm_extractor.py`
- `tests/unit/services/test_paper_facts_services.py`

### Verification

Run:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/unit/services/test_workspace_service.py
```

Manual acceptance should confirm:

- table-derived LPBF parameters land in explicit structured fields
- introduction or prior-work text no longer produces comparison-ready current
  results
- derived energy density can be distinguished from a reported energy density

### Exit criteria

- process parameters are not collapsing into generic free-text payloads when
  strong evidence exists
- `claim_scope` and `value_origin` survive storage and restore paths

## Slice 4: Comparable-Result Assembly And PBF Comparability Rules

### Goal

Make comparable-result assembly and collection overlays reflect PBF-metal
missingness and provenance rather than only generic row readiness.

### Changes

- gate comparable-result assembly on `claim_scope == current_work`
- keep prior-work and review-summary measurements outside the default
  comparable-result path
- extend `evaluate_comparison_assessment()` with narrow PBF rules:
  - missing `build_orientation` for orientation-sensitive properties ->
    `limited`
  - missing baseline on improvement-style claims -> `insufficient`
  - derived energy density with missing source parameters -> `insufficient`
  - missing test orientation for tensile or residual-stress style results ->
    `limited`
- update row-facing warnings only when the extra fields are needed in
  comparison displays

### Owned file areas

- `application/core/comparison_assembly.py`
- `domain/core/comparison.py`
- `application/core/comparison_projection.py` only if projection payloads need
  new warnings
- `tests/unit/domains/test_comparison_domain.py`
- `tests/unit/services/test_paper_facts_services.py`
- `tests/integration/test_app_layer_api.py`

### Verification

Run:

```bash
cd backend
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/integration/test_app_layer_api.py
```

### Exit criteria

- `comparable`, `limited`, `insufficient`, and `not_comparable` track the
  obvious PBF review constraints better than the generic baseline
- collection-facing rows still project cleanly from semantic and scope
  artifacts

## Slice 5: Gold-Corpus Lock And Acceptance

### Goal

Finish the wave with repeatable evidence, not only local examples.

### Changes

- freeze the first 30-paper PBF-metal corpus
- annotate the minimum fields needed by this wave:
  - alloy and material system
  - powder condition when reported
  - process parameters
  - post-processing history
  - target property, value, and unit
  - baseline relationship
  - test condition
  - `claim_scope`
  - `value_origin`
  - source anchors
  - final comparability status
- extend existing Core tests to assert against the fixed corpus
- record benchmark deltas against the slice-1 baseline

### Owned file areas

- `tests/fixtures/` or another owned backend-local test-data subtree
- `tests/unit/services/test_paper_facts_services.py`
- `tests/unit/domains/test_comparison_domain.py`
- `tests/integration/test_app_layer_api.py`

### Verification

Run:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
uv run pytest tests/unit/domains/test_comparison_domain.py
uv run pytest tests/integration/test_app_layer_api.py
```

Acceptance metrics should include:

- key process-parameter recall
- `claim_scope` precision
- false-comparable rate
- row-to-anchor traceback reviewability
- whole-document extraction time improvement relative to the slice-1 baseline

### Exit criteria

- the wave can show both semantic-quality gains and runtime gains on the fixed
  PBF-metal corpus
- the backend can explain where a comparison result came from and why it is or
  is not comparable

## Pull Request Sequence

### PR 1: Semantic-Center Freeze And Corpus Baseline

Include:

- doc wording alignment
- corpus manifest and failure taxonomy
- baseline benchmark notes

Keep this PR doc-heavy and low-risk.

### PR 2: Extraction Cost Reduction

Include:

- candidate pruning
- JSON-text extraction cutover
- bounded extraction concurrency

Keep this PR focused on latency and extraction-unit reduction.

### PR 3: PBF Semantic Extension

Include:

- explicit PBF process parameters
- `claim_scope`
- `value_origin`
- storage and restore support

Keep this PR focused on fact semantics rather than policy.

### PR 4: Comparability Rules And Gold-Corpus Lock

Include:

- comparable-result gating
- PBF comparability rules
- fixed corpus assertions
- benchmark deltas

Keep this PR focused on assessment behavior and acceptance evidence.

## Non-Goals During This Wave

Do not use this wave to:

- add a new permanent `backend/domain/materials/*` tree
- redesign graph, report, or protocol surfaces
- build a generic materials ontology platform
- create a second permanent Core extraction path
- expand the corpus beyond what is needed to validate the PBF-metal loop

## Acceptance Standard

This wave is done only when all of the following are true:

- the repository describes one semantic center
- extraction latency is materially lower on the known slow collection
- PBF process parameters and result provenance are explicitly represented
- comparable-result assembly excludes prior-work and review-summary leakage
- collection overlays express PBF-specific comparability limits
- the fixed gold corpus shows measurable improvement against the baseline

## Related Docs

- [`README.md`](README.md)
- [`proposal.md`](proposal.md)
- [`../core-parsing-quality-hardening-plan.md`](../core-parsing-quality-hardening-plan.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
