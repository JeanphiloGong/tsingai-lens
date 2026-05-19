# Expert Gold-Set Evaluation Plan

## Summary

This plan records how the PBF-metal validation wave should use expert-filled
annotation tables to improve the Core extraction and comparison backbone.

The expert-facing artifact should stay simple: material experts fill human
readable spreadsheet templates such as paper metadata, sample groups, process
parameters, test conditions, property results, baselines, characterization
observations, evidence locations, and uncertainty notes.

The backend work is to convert those tables into a gold set, compare that gold
set with the system's extracted Core facts, classify the differences, and use
the results to harden extraction, normalization, binding, evidence traceback,
and comparability policy.

This plan does not ask experts to understand Core artifact names. Internal
objects such as sample variants, measurement results, test conditions, evidence
anchors, and comparable results remain backend concepts used after the expert
tables are collected.

## Why This Matters

The PBF-metal comparison path depends on more than extracting isolated numeric
values. A trustworthy row must preserve:

- which sample or experimental group a result belongs to
- which process, treatment, or powder context produced that sample
- which test condition constrained the result
- whether the result comes from current work, prior work, or a review summary
- which baseline or control the result is compared with
- where the source evidence lives
- which missing context should limit comparability

Without expert gold data, Core quality work risks optimizing against local
examples rather than measurable research-review behavior.

## Scope

This plan belongs to the narrow PBF-metal validation family. It supports LPBF,
SLM, PBF-LB/M, EB-PBF, and closely related metal powder-bed-fusion papers.

The first pass should focus on a small corpus before broadening the domain:

- 5 papers for table usability and evaluator design
- 10-20 papers for first quality hardening
- 30 papers for the fixed acceptance corpus used by the wider PBF-metal wave

This plan should not:

- turn Lens into a PBF-only product
- make the expert spreadsheet format the runtime API contract
- expose internal artifact names to experts
- start with fine-tuning before parser, prompt, normalization, and binding
  failures are understood
- create a separate permanent comparison path for expert-labeled data

## Expert-Facing Tables

The expert-facing package should contain one short filling guide and CSV
templates with human-readable table names.

Required first-pass tables:

1. Paper metadata
2. Sample or experimental groups
3. Preparation, treatment, and process parameters
4. Test conditions
5. Property or performance results
6. Baseline and comparison relationships
7. Microstructure, defect, and characterization observations
8. Evidence locations
9. Missing or uncertain information

The guide should emphasize that experts only need to record paper facts. They
should not be asked to reason about backend schemas, artifact families, or row
projection mechanics.

## Internal Mapping

The backend should convert expert CSV data into one normalized gold bundle
before comparing it with system output.

| Expert table | Internal comparison target |
| --- | --- |
| Paper metadata | `document_profiles` |
| Sample or experimental groups | `sample_variants` |
| Preparation, treatment, and process parameters | `method_facts` and process context |
| Test conditions | `test_conditions` |
| Property or performance results | `measurement_results` |
| Baseline and comparison relationships | `baseline_references` and comparison support |
| Microstructure, defect, and characterization observations | `characterization_observations` and optional structure support |
| Evidence locations | `evidence_anchors` |
| Missing or uncertain information | uncertainty and comparability warnings |

The mapping layer exists for evaluation only. It should not become a
compatibility surface or an alternate runtime contract.

## Workflow

### 1. Pilot Expert Fill

Start with one or two papers and ask experts to fill the human-readable CSV
templates.

Use the pilot to answer:

- whether the table names and columns are understandable
- whether sample names are easy to record once and reference by sample number
- whether experts can distinguish preparation temperature from test
  temperature
- whether evidence locations are practical to fill
- whether uncertainty is being recorded instead of guessed away

After the pilot, revise only the expert guide and CSV templates that are
actually confusing.

### 2. Build The First Gold Set

Collect five expert-annotated papers and freeze them as the first evaluation
set.

The first gold set should cover:

- at least two straightforward experimental papers
- at least one table-heavy paper
- at least one paper with several sample groups or treatments
- at least one paper with prior-work or review-style comparison values
- at least one paper with missing test condition or baseline context

The initial goal is not exhaustive coverage. The goal is to standardize the
core chain:

```text
sample group
-> preparation or treatment context
-> test condition
-> property result
-> baseline
-> evidence
-> uncertainty
```

### 3. Convert Expert CSV To Gold Records

Add a backend-local offline converter that:

- loads the expert CSV folder
- validates required columns and reference IDs
- normalizes common metric names and units
- preserves the expert-facing source text
- emits a gold JSON or parquet bundle that matches Core evaluation needs

The converter should reject broken references such as a result that points to
an unknown sample number. It should warn, not invent a value, when optional
links such as test condition or baseline are missing.

### 4. Run System Extraction On The Same Papers

Run the normal backend pipeline on the same PDF set:

```text
source artifacts
-> document profiles
-> paper facts family
-> comparable results
-> collection comparable results
-> row projection
```

Export the system prediction bundle from the same internal object families
used by production code. The evaluator should not compare against a special
debug-only extraction path.

### 5. Align Gold And Prediction

Before scoring, normalize only the comparisons that need tolerant matching:

- common property names such as `YS`, `yield strength`, and `yield_strength`
- material aliases such as `Ti64` and `Ti-6Al-4V`
- unit spelling such as `%`, `percent`, `MPa`, and `degC`
- small numeric tolerances for figure-derived or rounded values
- sample labels with clear aliases such as `Sample B` and `HIP-treated sample`

Keep the normalized match record inspectable. If matching required fuzzy logic,
the difference report should say so.

### 6. Produce Difference Reports

For each paper, produce a human-readable difference report with sections for:

- missed expert facts
- extra system facts not found in the gold set
- numeric or unit mismatches
- sample binding mismatches
- test-condition binding mismatches
- current-work versus prior-work mistakes
- baseline identification mistakes
- evidence location mistakes
- uncertainty or warning mismatches

The report should be useful to a developer deciding which part of the backend
to fix next.

## Evaluation Metrics

The first metrics should stay simple and behavior-oriented.

| Capability | Metric |
| --- | --- |
| Sample-group extraction | recall against expert sample groups |
| Property-result extraction | precision and recall against expert results |
| Result value correctness | exact or tolerance-aware numeric match |
| Result-to-sample binding | accuracy on matched results |
| Result-to-test-condition binding | accuracy on matched results |
| Current-work filtering | accuracy for current work, prior work, and review-summary labels |
| Baseline recognition | accuracy for baseline target and baseline type |
| Evidence traceback | whether the system evidence can support the matched fact |
| Uncertainty handling | whether missing context creates warnings instead of false confidence |

Reasonable first-pass targets:

| Capability | First target |
| --- | --- |
| Sample-group recall | 70% or higher |
| Property-result recall | 60% or higher |
| Property-result precision | 70% or higher |
| Result-to-sample binding accuracy | 70% or higher |
| Current-work filtering accuracy | 80% or higher |
| Evidence traceback support | 70% or higher |

These targets are calibration thresholds, not final product quality bars.

## Error Taxonomy

Every mismatch should be assigned one primary cause.

| Error class | Typical backend follow-up |
| --- | --- |
| Parser or table extraction failure | improve Source parser, table row, or cell handling |
| Missing sample group | harden sample extraction prompt and sample-state rules |
| Wrong sample meaning | improve variant interpretation and process-state binding |
| Missed result | improve result prompt, table handling, or candidate selection |
| Extra result | tighten current-work filtering and low-value section pruning |
| Wrong unit or value | improve unit normalization and value-provenance checks |
| Wrong result-to-sample binding | improve table header, caption, and local context binding |
| Missing test condition | improve methods-section condition extraction |
| Wrong baseline | improve baseline taxonomy and within-paper control detection |
| Weak evidence anchor | improve source anchor generation and traceback selection |
| Missing warning | improve comparability policy and missing-critical-context rules |

The taxonomy should be stored with each evaluation report so progress can be
tracked by failure mode rather than only by aggregate scores.

## Optimization Order

Use the reports to improve the backend in this order:

1. Source parsing and evidence anchors
2. Sample-group extraction and sample-state interpretation
3. Property-result extraction
4. Result-to-sample and result-to-condition binding
5. Current-work, prior-work, and review-summary filtering
6. Baseline recognition
7. PBF-metal comparability policy
8. Row projection display and downstream views

The comparison row layer should not be the first optimization target. It can
only become trustworthy after the paper-facts layer is sufficiently grounded.

## Regression Tests

Each fixed failure should become a regression test.

Recommended layers:

- unit tests for metric normalization, unit normalization, baseline type
  classification, and comparability policy
- service tests for turning text and table fixtures into expected paper facts
- gold-set evaluation tests for whole-paper extraction quality on the fixed
  PBF-metal corpus

The first gold-set test can be non-blocking or threshold-reporting while the
evaluation harness stabilizes. Once stable, it should become a quality gate for
the PBF-metal validation wave.

## Deliverables

This wave should produce:

- an expert-facing filling guide and CSV templates
- a fixed pilot gold set
- a CSV validation and conversion script
- a prediction export path from normal Core artifacts
- a gold-versus-prediction evaluator
- per-paper difference reports
- aggregate metrics and error-taxonomy summaries
- backend fixes prioritized by the observed errors
- regression tests that preserve each fixed behavior

## Acceptance

The plan is complete when the backend can:

- ingest a folder of expert CSV annotations
- validate and convert those annotations into gold records
- run the normal extraction path over the same papers
- compare gold and prediction with inspectable matching logic
- report metrics and categorized errors
- show measurable improvement on the fixed PBF-metal corpus after optimization
- keep prior-work and review-summary values out of default comparable results
- explain missing sample, condition, baseline, or evidence context in warnings

## Related Docs

- [`README.md`](README.md)
  Topic-family reading order for the PBF-metal validation wave
- [`implementation-plan.md`](implementation-plan.md)
  Broader executable implementation plan for the PBF-metal validation wave
- [`evidence-chain-fact-thickening-plan.md`](evidence-chain-fact-thickening-plan.md)
  Backend plan for improving the fact layer that this gold-set workflow
  evaluates
- [`parameter-registry-and-variant-report-scope.md`](parameter-registry-and-variant-report-scope.md)
  First-version PBF parameter boundary and variant report scope
