# Material Profile Aggregation Repair Plan

## Summary

The `col_ed3ea76e79c3` PBF-metal validation collection can complete its build
and produce the expected Core artifacts, but the collection material profile
does not yet preserve the intended six-paper 316L view.

The failed surface is the collection-scoped material aggregation endpoint:

```text
GET /api/v1/collections/{collection_id}/materials/{material_id}/research-view
```

For the current six-paper fixture, `mat-316l-stainless-steel` should be the
primary material profile. Instead, the profile is partial, covers only three
papers, and exposes `argon` as a separate material. The repair should first
fix backend aggregation tolerance over existing artifacts, then use expert
gold evaluation to decide whether a second extraction-quality wave is needed.

## Observed Failure

The reference collection is:

```text
col_ed3ea76e79c3
```

It contains the expected P001-P006 PDFs and completed without build errors.
The output directory contains ready Source/Core artifacts including
`document_profiles.parquet`, `sample_variants.parquet`,
`measurement_results.parquet`, `evidence_anchors.parquet`,
`evidence_cards.parquet`, and `comparison_rows.parquet`.

The material aggregation result is still incomplete:

- `mat-316l-stainless-steel` covers only P001, P003, and P004.
- P002 contributes a separate `mat-argon` material profile.
- P005 and P006 have measurement and evidence artifacts, but do not enter the
  316L material profile because their sample rows are filtered out.
- P003 enters the 316L profile but is reported with no material-scoped
  measurement results.

The expert-gold comparison confirms that the collection maps all six papers,
but sample and measurement recall are low:

```text
papers_evaluated: 6
mapped_papers: 6
sample_recall: 0.2388
measurement_recall: 0.3738
measurement_precision: 0.8511
gold_sample_count: 67
matched_sample_count: 16
gold_core_measurement_count: 214
prediction_core_measurement_count: 94
matched_core_measurement_count: 80
```

P001 remains the known-good control: all 16 expert samples and all 80 core
measurements match.

## Cause

The failure is not a missing-artifact problem. It is a material and sample
binding problem amplified by aggregation rules.

The extraction output contains useful facts, but some bindings are weak:

- P002 assigns `argon` to `host_material_system` for process-atmosphere
  samples. That is a shielding/process medium, not the studied material.
- P005 and P006 produce sample labels and measurements, but their material is
  often `unspecified material system`.
- Several measurements are extracted with values and metrics, but cannot be
  counted as core gold matches because their `sample_id` binding is missing
  or maps to a different sample label than the expert table.

The aggregation service then drops or misroutes these facts:

- `_material_key_from_variant` trusts a non-generic host material before using
  the document-level material fallback.
- `_single_material_key_by_document` refuses a fallback when a document has
  multiple candidate materials, so P002 does not get the 316L fallback because
  `argon` appears as a candidate.
- `_is_real_sample_variant` treats some useful rows as non-real when they have
  no process payload or variable value and the material is unspecified.
- `_filter_frames_for_material_key` selects measurements only through selected
  sample variant ids, so filtered sample rows also remove material-scoped
  measurement rows.

## Repair

Repair the backend aggregation layer first. This should use the existing
parquet artifacts and should not introduce an adapter or compatibility layer.

### Material Canonicalization

Extend the material canonicalization path in
`backend/application/core/research_view_aggregation_service.py` so process
media do not become collection material profiles.

The first blocked labels should include process-atmosphere terms observed in
the fixture, starting with:

```text
argon
```

The filter should apply only to material-profile grouping. It should not erase
raw artifact values or evidence references.

Expected behavior:

- `argon` does not create `mat-argon`.
- a process medium does not override a document-level 316L fallback.
- source facts remain available through debug and evidence paths.

### Document-Level Material Fallback

Keep using document profile fields and source filenames to infer stable
document-level material keys. For this fixture, any P001-P006 source filename
containing `316L` should provide a `316l-stainless-steel` fallback.

The fallback should apply when a sample variant has no reliable material key.
It should not override an explicit, trusted material for genuinely
multi-material papers.

Expected behavior:

- P001, P003, P004, P005, and P006 receive the 316L document fallback.
- P002 also receives the 316L document fallback after `argon` is excluded as a
  material-profile candidate.
- weak or unknown material binding still appears as a warning when no document
  fallback exists.

### Real Sample Detection

Relax `_is_real_sample_variant` so useful sample labels are not discarded only
because their host material is unspecified.

Keep excluding generic material-only rows such as `stainless steel`, `steel`,
`sample`, `material`, or `powder`, but preserve labels that distinguish
experimental variants, including:

```text
P150
NP
375 W-2100 mm/s
255 W-1400 mm/s
135 W-750 mm/s
0
45
```

Expected behavior:

- P005 process-parameter sample labels enter the 316L material sample matrix.
- P006 angle sample labels enter the 316L material sample matrix.
- generic material aliases still do not become visible sample rows.

### Measurement Selection

Keep material-scoped measurement selection tied to selected sample variants.
Do not add a broad fallback that attaches every measurement in a 316L-titled
paper to the material profile.

Once useful sample variants survive filtering and inherit the document-level
316L fallback, their existing `variant_id` links should bring their
measurements into the material profile without changing measurement semantics.

Only consider measurement-side fallback in a later wave if gold evaluation
still shows that values are extracted but systematically lack `sample_id`
links.

## Tests

Add focused coverage in
`backend/tests/unit/services/test_research_view_aggregation_service.py`.

The tests should use direct service fixtures rather than rewriting local
runtime data under `backend/data/`.

Required scenarios:

- a P002-style document whose title contains `316L` and whose sample variants
  mention `argon` should produce only `mat-316l-stainless-steel`, not
  `mat-argon`
- a P005-style document with power/speed labels and unspecified material should
  retain real sample rows under the 316L material fallback
- a P006-style document with angle labels such as `0` and `45` should retain
  sample rows under the 316L material fallback
- the P001-style control should still produce the same 16 sample rows and
  matched core measurement cells

If router behavior changes, add only the minimal assertions needed in
`backend/tests/unit/routers/test_research_view_api.py`.

## Verification

Use the smallest checks that cover the changed surface:

```bash
cd backend
./.venv/bin/python -m pytest tests/unit/services/test_research_view_aggregation_service.py
```

Then verify the existing local collection without rewriting it:

```bash
cd backend
./.venv/bin/python - <<'PY'
from application.core.research_view_aggregation_service import ResearchViewAggregationService

service = ResearchViewAggregationService()
materials = service.list_collection_materials("col_ed3ea76e79c3")
profile = service.get_collection_material_research_view(
    "col_ed3ea76e79c3",
    "mat-316l-stainless-steel",
)

print(materials["materials"])
print(profile["overview"])
print([paper["source_filename"] for paper in profile["papers"]])
PY
```

Expected local collection checks:

- `mat-argon` is absent from the material list
- `mat-316l-stainless-steel` has six paper entries
- P001 remains ready with its 16-row sample matrix
- P005 and P006 contribute sample rows to the 316L profile
- warnings remain explicit for weak or missing sample/measurement binding

Finally rerun expert-gold evaluation with temporary output paths:

```bash
cd backend
./.venv/bin/python scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --collection-id col_ed3ea76e79c3 \
  --output /tmp/col_ed3ea76e79c3_prediction_bundle.json

./.venv/bin/python scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py \
  --gold tests/fixtures/local_expert_gold/generated/gold_bundle.json \
  --prediction /tmp/col_ed3ea76e79c3_prediction_bundle.json \
  --output /tmp/col_ed3ea76e79c3_evaluation_report.json
```

The repair is successful when `sample_recall` and `measurement_recall` improve
from the current six-paper baseline while P001 stays at full recall and
precision.

## Risks

The aggregation repair should not pretend that extraction is perfect. It only
prevents obvious material-profile misrouting and sample filtering loss.

Residual extraction-quality issues may remain after this repair:

- sample labels may still differ from expert labels
- some measurements may still lack `sample_id`
- range-valued measurements may still be excluded by strict scalar matching
- P006 may still report extra yield-strength predictions that do not map to
  current expert core-measurement rows

Those are prompt, schema, or evaluator-alignment issues and should be handled
as a separate Core extraction-quality wave after the aggregation repair is
verified.
