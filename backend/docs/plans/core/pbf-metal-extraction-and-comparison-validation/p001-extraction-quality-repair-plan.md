# P001 Extraction Quality Repair Plan

## Summary

This plan records the first repair wave after running the expert gold evaluator
on P001, the 316L SLM paper about energy density, scanning strategy,
densification, microstructure, and mechanical properties.

The current evaluation result is useful because it separates two very different
quality signals:

| Signal | Current P001 result |
| --- | ---: |
| Sample recall | 16 / 16 |
| Core measurement recall | 80 / 80 |
| Core measurement precision | 80 / 176 |
| Extra core measurements | 96 |
| Duplicate prediction groups | 70 |

The system is finding the core samples and core property values, but it is
not yet producing a clean fact layer. The next backend work should improve
precision and binding quality while protecting the current recall.

## Repair Goal

The first repair goal is to keep the P001 gold-set coverage high while reducing
noise in the Core facts that feed comparison rows.

Target after this wave:

| Capability | Target |
| --- | ---: |
| Sample recall | 95% or higher |
| Core measurement recall | 95% or higher |
| Core measurement precision | 80% or higher |
| Prediction samples | close to 16 for P001 |
| Unresolved test conditions | materially reduced |
| Process parameter certainty | no obvious column-shifted values in certain fields |

These targets are first-pass gates for P001. They should not be treated as the
final PBF-metal product quality bar.

## Observed Failure Modes

### Duplicate Property Results

The largest precision loss is repeated measurement facts. A single table value
is often emitted two or three times with slightly different generated
statements or anchors.

Examples from P001:

| Sample | Property | Value | Symptom |
| --- | --- | ---: | --- |
| 1 | density | 95.4% | two rows with paraphrased statements |
| 1 | yield strength | 236.65 MPa | two rows from the same table value |
| 5 | yield strength | 302.24 MPa | duplicate rows with the same evidence quote |
| 13 | yield strength | 186.46 MPa | three rows from one value |

The extra results are mostly not new facts. They are duplicate renderings of
already matched facts.

### Weak Unit Normalization

Some duplicate facts differ only because one row carries the unit and another
does not. This shows up most often for density, hardness, and elongation.

Examples:

| Sample | Property | Value | Unit state |
| --- | --- | ---: | --- |
| 2 | density | 97.7 | one row has `%`, one row has no unit |
| 1 | hardness | 215.65 | one row has `HV`, one row has no unit |
| 13 | hardness | 188.05 | mixed empty and `HV` unit rows |

The evaluator is tolerant enough to match the gold facts, but the production
fact layer should not rely on tolerant matching to remove duplicates.

### Spurious Measurement Values

Some values are likely table artifacts, standard deviations, or neighboring
columns that were assigned to a core property.

Examples:

| Sample | Property | Value | Why it is suspicious |
| --- | --- | ---: | --- |
| 10 | hardness | 9.7 | too small for an HV hardness result |
| 16 | hardness | 11.4 | too small for an HV hardness result |

These should either be classified as the correct statistic, excluded from
core scalar measurement results, or retained as uncertain non-comparison facts.

### Over-Broad Sample Variants

The system correctly extracted sample labels 1 through 16, but it also emitted
conceptual entities as sample variants.

Examples that should not be standalone variants:

- `316L stainless steel`
- `iron-based alloys`
- `water atomized samples`
- `scanning strategies A, B, or C`
- `scanning strategy A`
- `scanning strategy B`

Those concepts should become material, powder, process, or variable context.
They should not become comparison-ready sample variants unless they are bound
to a concrete experiment group.

### Missing Variant Axis Context

The correct numeric sample variants are present, but their comparison axes are
thin:

```text
variable_axis_type = None
variable_value = null
```

For P001, the useful variant axes include scanning strategy, scan speed,
energy density, and hatch spacing. Those axes need to be represented in the
sample/process state so comparison rows can explain why one sample differs
from another.

### Process Parameter Column Shifts

Some `process_context` values show likely table column misbinding.

Examples:

| Sample | Field | Extracted value | Expected direction |
| --- | --- | ---: | --- |
| 5 | `scan_speed_mm_s` | 12.0 | should be near 0.12 |
| 6 | `scan_speed_mm_s` | 150.0 | looks like energy density |
| 8 | `scan_speed_mm_s` | 70.0 | looks like energy density |
| 13 | `scan_speed_mm_s` | 100.0 | looks like energy density |

The system should not write these values as certain scan-speed facts. If
column binding is uncertain, the value should stay in raw or uncertain payload
instead of becoming normalized process state.

### Fragmented Test Conditions

The expert gold set has three P001 test-condition families:

- tensile testing
- microhardness testing
- density, porosity, and microstructure characterization

The prediction bundle produced eight conditions, six of which were unresolved.
The missing family in the evaluator report is hardness. The system is still
creating condition rows from properties rather than stable test methods.

## Repair Sequence

### 1. Deduplicate Measurement Results

Add canonical deduplication before `measurement_results.parquet` is written.
The dedupe key should use normalized fact identity rather than statement text.

Recommended key:

```text
document_id
variant_id
property_normalized
result_type
claim_scope
numeric_value
normalized_unit
source_table_or_figure
```

Merge behavior:

- keep one stable result row
- merge `evidence_anchor_ids`
- merge structure and characterization support ids
- keep the more complete unit and value payload
- prefer a concrete table anchor over a weaker paraphrase when both support
  the same scalar value
- retain enough merge provenance for debug output

Expected P001 effect:

| Metric | Current | Target after dedupe |
| --- | ---: | ---: |
| Core prediction results | 176 | about 80 to 100 |
| Matched core results | 80 | 80 or close |
| Precision | 45.45% | 80% or higher |

### 2. Prefer Table Scalars Over Text Paraphrases

For current-work core scalar properties, table-derived values should dominate
text paraphrases of the same value. Text can remain supporting evidence, but
it should not create another scalar measurement when the same table value is
already present.

Covered core properties:

- density
- hardness
- yield strength
- tensile strength
- elongation

This rule should still allow text-only facts when no table scalar exists.

### 3. Filter Conceptual Sample Variants

Add quality rules before final sample-variant materialization.

Keep a variant when one of these is true:

- it has an explicit experiment-group label such as `Sample 1`, `1`, or `S001`
- it is directly referenced by one or more measurement results
- it has concrete process context and can be tied to a specific experiment
  group

Do not keep a standalone variant when it is only:

- a material name
- a powder source
- a scanning strategy name
- a generic method or condition phrase
- an unbound concept with no measurement result and no experiment-group label

Filtered concepts should be folded into material, powder, process, or variable
context where evidence supports that mapping.

### 4. Bind Table Columns Before Normalizing Process Context

Process parameters should use column-aware table binding, not just nearby
numeric extraction.

Column rules for P001-style tables:

| Header evidence | Target field |
| --- | --- |
| scanning speed, scan speed | `scan_speed_mm_s` |
| energy density, ED | `energy_density_j_mm3` |
| hatch spacing | `hatch_spacing_um` |
| layer thickness | `layer_thickness_um` |
| scanning strategy | `scan_strategy` |

Add range checks before writing certain fields:

| Field | P001 expected range |
| --- | ---: |
| `scan_speed_mm_s` | about 0.1 to 0.3 |
| `energy_density_j_mm3` | about 70 to 150 |
| `hatch_spacing_um` | about 110 to 120 |

Values outside the plausible range should be marked uncertain unless there is
strong source evidence that the unit or scale is different.

### 5. Aggregate Test Conditions By Method Family

Test conditions should be assembled from methods and result families rather
than generated per property.

Recommended family binding:

| Result properties | Test-condition family |
| --- | --- |
| yield strength, tensile strength, elongation | tensile |
| hardness | microhardness |
| density, porosity, grain size, microstructure | characterization |

The resulting condition rows should carry method details such as standard,
load, holding time, specimen geometry, surface state, and sample orientation
when available. If details are missing, the condition should still be a stable
family row with explicit missing fields, not an unresolved property row.

## Implemented First Slice

The first implementation slice now lands in
`application/core/semantic_build/paper_facts_service.py`.

Implemented behavior:

- measurement results are deduplicated before `measurement_results.parquet` is
  written
- duplicate scalar rows merge direct evidence anchors and prefer rows with
  stronger source and unit support
- common core-property units are normalized for density, hardness, yield
  strength, tensile strength, elongation, and retention when the source text or
  property shape supports the inference
- standard-deviation table values are excluded from core scalar measurement
  rows instead of being emitted as hardness or another core property
- table-row process context now binds from column headers before using LLM
  process mentions, so scan speed, energy density, hatch spacing, and scan
  strategy are not cross-filled from neighboring columns
- generic text-window variants are removed when the same document has
  table-row variants, and measurements that referenced removed generic
  variants are left unbound instead of pointing at a non-sample concept
- empty test-condition payloads are no longer materialized as unresolved
  property conditions

Read-only dry run on the existing P001 artifacts, without rewriting runtime
data, showed the intended direction:

| Check | Before | After first-slice cleanup |
| --- | ---: | ---: |
| Sample variants | 23 | 16 |
| Removed generic text variants | 0 | 7 |
| Measurement rows after statistic filtering | 188 | 94 |
| Core table/sample rows after dedupe direction | 180 | 86 |

The remaining extra core rows in that dry run are density text claims without
sample binding. They should not count as matched sample measurements after a
full rerun and evaluator export, but they remain useful evidence candidates
until the method-family and text/table support merge work is finished.

## Verification Loop

Use the expert gold evaluator as the regression loop for every repair slice.

Run the current P001 collection through the normal backend pipeline, then:

```bash
cd backend
python3 scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --collection-id col_919063439bb3
python3 scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py \
  --gold-paper-id P001
```

Review:

- `papers[0].measurements.precision`
- `papers[0].measurements.duplicate_prediction_groups`
- `papers[0].samples.extra_generic_prediction_samples`
- `papers[0].test_conditions.prediction_unresolved_count`
- process-context values in `sample_variants.parquet`

The report should keep exact examples of failures so backend fixes are tied to
observable P001 behavior rather than aggregate metrics only.

## Deferred Work

Do not start with pairwise comparison repair.

The expert comparison table records sample-to-sample relationships such as
`S001` versus `S002` or `S004` versus `S011`. The current prediction
`comparison_rows` are projected result rows, not expert-style pairwise
comparison facts. Pairwise matching depends on clean sample variants, deduped
measurement results, stable test conditions, and reliable process context.

Pairwise comparison evaluation should follow after this repair wave stabilizes
the underlying fact layer.
