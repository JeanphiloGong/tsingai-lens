# P001 Remaining Gold Gap Repair Plan

## Summary

The latest P001 run has reached the first clean table-result milestone:

| Check | Current result |
| --- | ---: |
| Objective contexts | 2 / 2, unchanged from baseline |
| Table sample variants | 16 / 16 |
| Table process context | 16 / 16 exact matches |
| Table performance results | 80 / 80 exact matches |
| Missing table results | 0 |
| Extra table results | 0 |
| Value or unit mismatches | 0 |

The original remaining P001 gold gaps were no longer table-value extraction
failures. They were missing higher-level Core semantics:

| Gold area | Pre-repair result | Current checked result | Gold target |
| --- | ---: | ---: | ---: |
| Test conditions | 0 | 3 | 3 |
| Pairwise comparison relations | 0 | 19 | 19 |
| Characterization observations | 1 | 8 | 8 |

This plan records the next three repair stages for the research-objective-first
flow after objective-scoped table extraction has reached parity with the P001
gold set. It stays inside the Core semantic-build and comparison-evidence
backbone. It does not change public API routes, frontend contracts, Source
artifact production, or the already-clean table result extraction path.

## Implementation Status

Implemented on 2026-05-12 in the backend Core fact and comparison pipeline.

The implementation keeps the public API unchanged and adds only internal Core
fact behavior:

- `PaperFactsService` now materializes three document-level method-family test
  conditions and binds table measurements to those families.
- `ComparableResultAssembler` now builds persisted pairwise sample-comparison
  relations for the P001-style PBF table matrix without overloading
  `BaselineReference`.
- `PaperFactsService` now derives dedicated characterization observations from
  clean table evidence and targeted characterization/discussion text.

Latest P001 probe:

- collection: `col_0b8eea606c28`
- run dir:
  `/home/chenhm/.application/date/2026/may/week3/12,Tue/full_single_paper_runs/20260512-170419-P001-Effect-of-energy-density-and-scanning-strategy-on-densification-microstruct-2155717a`
- table performance results: 80 / 80 exact against
  `05_性能结果表.csv`
- table measurement test-condition bindings: 80 / 80
- pairwise comparison relations: 19 / 19 exact against
  `06_对照比较关系表.csv`
- characterization observations: 8 categories aligned with
  `07_组织缺陷表征观察表.csv`

The total `measurement_results` count is higher than 80 because text-derived
trend and scalar claims are still kept as separate evidence records. The table
acceptance check remains scoped to `result_source_type=table`.

Read this with:

- [`objective-context-targeted-extraction-plan.md`](objective-context-targeted-extraction-plan.md)
- [`../pbf-metal-extraction-and-comparison-validation/p001-extraction-quality-repair-plan.md`](../pbf-metal-extraction-and-comparison-validation/p001-extraction-quality-repair-plan.md)
- [`../pbf-metal-extraction-and-comparison-validation/expert-gold-set-evaluation-plan.md`](../pbf-metal-extraction-and-comparison-validation/expert-gold-set-evaluation-plan.md)

## Stage 1: Method-Family Test Conditions

The test-condition gap should be fixed before comparison and observation work.
P001 gold has three document-level method families:

- tensile testing
  - ASTM E8M
  - INSTRON mechanical testing machine
  - 0.02 mm/min quasi-static rate
  - three tensile specimens per condition
- microhardness testing
  - Vickers microhardness tester
  - 10 N load
  - 15 s holding time
  - 20 readings per sample
- density, porosity, and microstructure characterization
  - SEM and ImageJ thresholding
  - horizontal and vertical sections
  - polishing steps
  - 100x to 10000x magnification

These records should be extracted at document level from methods,
experimental, characterization, and measurement-method windows. They should not
be generated per table row or per property.

Implementation should add a method-family test-condition pass in
`application/core/semantic_build/paper_facts_service.py`:

1. Select method-bearing text windows from the document.
2. Ask the structured extractor for method-family test-condition mentions or
   derive them from existing method mentions when the information is already
   present.
3. Materialize one stable `TestCondition` row per family.
4. Bind table measurements deterministically by property family:
   - `yield_strength`, `tensile_strength`, and `elongation` bind to tensile.
   - `hardness` binds to microhardness.
   - `density`, `porosity`, `grain_size`, and `microstructure` bind to
     SEM/ImageJ characterization.

Stage 1 is complete when:

- P001 produces three test-condition rows.
- All 80 table measurements have a `test_condition_id`.
- The 80 / 80 exact table-result match remains unchanged.
- The method-family rows carry available standard, instrument, loading,
  specimen, surface, and orientation details without inventing missing fields.

## Stage 2: Pairwise Comparison Relations

P001 gold comparison rows are sample-to-sample relations. They are not the same
thing as the current `BaselineReference` rows.

Examples include:

- `S001` versus `S002` under the same scan speed and energy density, comparing
  scanning strategy for yield strength, tensile strength, and elongation
- `S001` versus `S008` under the same energy density and strategy, comparing
  scan speed
- `S014` versus `S005` under the same energy density and strategy, comparing
  relative density

This should not be forced into `baseline_references`. It should become a Core
comparison-relation layer derived from clean sample variants and clean
measurement results.

Implementation should add a deterministic relation builder after sample,
process-context, test-condition, and measurement materialization:

1. Group sample variants by objective context and comparable process context.
2. Find sample pairs where one comparison axis changes and the remaining
   context is equivalent enough for comparison.
3. For each shared measured property, compare current and reference values.
4. Emit a comparison-relation record with current sample, comparison sample,
   comparison axis, property, values, direction, unit, and table evidence.

The first implementation should target the P001 relation shape directly and
avoid broad graph/report changes. API and frontend exposure can wait until the
relation layer is stable.

Stage 2 is complete when:

- P001 produces 19 pairwise comparison relations or a clearly explained subset
  that maps to the same gold logic.
- Every relation traces to Table 1 or Table 2 evidence.
- Existing `BaselineReference` semantics are not overloaded with sample-pair
  comparisons.
- Existing comparable-result projection still passes its tests.

## Stage 3: Characterization Observations

The observation gap is mostly qualitative and aggregate. P001 gold observations
come from SEM/ImageJ methods, figure captions, result discussion, and table
summaries.

The target observation families are:

- SEM/ImageJ density and porosity observation across all 16 samples
- horizontal and vertical section SEM observation
- scanning strategy A behavior
- scanning strategy B defect behavior
- scanning strategy C behavior
- dendrite or cellular structure size trend
- Sample 14 highest-density observation
- low-energy, overheating, balling, and pore-defect interpretation

This should be a dedicated characterization-observation extraction pass, not a
side effect of `method_facts`.

Implementation should combine two sources:

1. LLM extraction from objective-aware characterization and discussion windows,
   plus figure captions when available.
2. Deterministic aggregate observations derived from clean table results, such
   as the maximum-density Sample 14 observation.

The observation output should stay separate from `measurement_results`. It can
reference sample groups, table anchors, figure captions, and method evidence,
but it should not duplicate the 80 table scalar measurements.

Stage 3 is complete when:

- P001 produces about eight characterization observations aligned with the gold
  categories.
- Each observation has traceable evidence.
- Qualitative observations do not create extra scalar measurement results.
- Aggregate observations derived from tables are marked as derived from clean
  table evidence, not as LLM-only claims.

## Verification

Run the P001 single-paper probe after every stage:

```bash
cd backend
./.venv/bin/python /home/chenhm/.application/date/2026/may/week3/11,Mon/probe_single_paper_extraction.py \
  "/home/chenhm/ai_project/lens/backend/tests/fixtures/local_expert_gold/P001-Effect of energy density and scanning strategy on densification, microstructure and mechanical properties of 316L stainless steel processed via selective laser melting.pdf" \
  --backend-root /home/chenhm/ai_project/lens/backend \
  --run-root /home/chenhm/.application/date/2026/may/week3/12,Tue/full_single_paper_runs \
  --max-items 200
```

Then compare against the local expert gold CSVs:

- `04_测试条件表.csv`
- `06_对照比较关系表.csv`
- `07_组织缺陷表征观察表.csv`

Each stage must also preserve the already-clean table facts:

- 16 sample variants
- 16 exact process-context matches
- 80 exact table performance-result matches
- no missing, extra, or mismatched table values

Recommended backend checks:

```bash
cd backend
./.venv/bin/python -m pytest
./.venv/bin/python -m ruff check application/core/semantic_build
python3 ../scripts/check_docs_governance.py
```

## Exit Criteria

The P001 remaining-gap repair is complete when:

- table extraction remains exact against the 80 gold table performance results
- three method-family test conditions exist and bind to table results
- pairwise comparison relations represent the 19 gold comparison rows without
  abusing `baseline_references`
- characterization observations cover the eight gold observation categories
- text-derived measurement claims are either merged as supporting evidence or
  clearly separated from table scalar measurements
