# Expert Gold Evaluation Scripts

This directory contains offline utilities for validating and preparing
expert-filled PBF-metal annotation tables.

The first supported steps are CSV validation and conversion into an internal
gold bundle. These scripts check that the expert tables are structurally usable
before any system extraction output is compared against them.

## Validate Expert CSV

Run from the backend directory:

```bash
uv run python scripts/evaluation/expert_gold/validate_expert_gold.py \
  --input tests/fixtures/local_expert_gold
```

The validator reads the human-facing CSV tables with `utf-8-sig` so files
exported from spreadsheet tools with a UTF-8 BOM keep the expected first
column name.

It checks:

- required files and headers
- required identifier columns
- duplicate paper, sample, condition, result, comparison, observation,
  evidence, and uncertainty ids
- references from results to samples and test conditions
- references from comparisons and observations to samples
- evidence id references when a cell contains values such as `E001`

The ignored local data path is:

```text
backend/tests/fixtures/local_expert_gold/
```

Do not commit expert CSV exports, source PDFs, generated gold bundles, or
evaluation reports from that directory.

## Convert Expert CSV To Gold Bundle

After validation passes, convert the CSV files into one traceable JSON bundle:

```bash
python3 scripts/evaluation/expert_gold/convert_expert_gold.py \
  --input tests/fixtures/local_expert_gold
```

The default output is:

```text
tests/fixtures/local_expert_gold/generated/gold_bundle.json
```

The bundle keeps expert-facing content while adding stable internal keys,
source table and row references, evidence id lists, sample id lists, and basic
enum normalization such as:

- `本文实验` -> `current_work`
- `前人文献` -> `prior_work`
- `综述总结` -> `literature_summary`

This conversion format is for offline evaluation only. It is not a runtime API
contract and should not be exposed as a frontend or product schema.

## Export System Output To Prediction Bundle

After the target papers have been processed by the normal collection build,
export the system-side Source/Core repository records into a prediction bundle:

```bash
python3 scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --collection-id <collection_id>
```

For a direct artifact folder:

```bash
python3 scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --output-dir data/collections/<collection_id>/output
```

The default output is:

```text
tests/fixtures/local_expert_gold/generated/prediction_bundle.json
```

The script is read-only against collection artifacts. It does not rebuild the
collection and it does not change runtime trace behavior. Missing repository
record families are represented as zero-row artifact counts and empty lists so
the later evaluator can report coverage gaps explicitly.

The prediction bundle uses the same primary families as the gold bundle where
possible:

- `papers`
- `samples`
- `process_parameters`
- `test_conditions`
- `measurement_results`
- `comparisons`
- `observations`
- `evidence`

It also preserves system-specific raw families such as `comparison_rows`,
`pairwise_comparison_relations`, `comparable_results`, `baseline_references`,
and `structure_features` with artifact row references for later debugging.

When Core pairwise comparison relations are available, the exported
`comparisons` family is built from those relations so expert-style sample vs.
baseline comparisons can be evaluated directly. Legacy `comparison_rows` are
kept as raw debugging records.

## Evaluate Gold Versus Prediction

After both bundles exist, generate the first-pass evaluation report:

```bash
python3 scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py
```

The default inputs are:

```text
tests/fixtures/local_expert_gold/generated/gold_bundle.json
tests/fixtures/local_expert_gold/generated/prediction_bundle.json
```

The default output is:

```text
tests/fixtures/local_expert_gold/generated/evaluation_report.json
```

For a single paper:

```bash
python3 scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py \
  --gold-paper-id P001
```

The report is a structural first pass. It measures paper mapping, sample
recall, core measurement value matching, test-condition family coverage,
evidence coverage, extra predictions, and duplicate predictions. Expert-style
pairwise comparison matching is active when the prediction bundle contains
pairwise comparison relations. A pairwise comparison match requires compatible
current sample, baseline sample, metric, unit, and numeric values within the
configured tolerance.

## Run Objective-First Benchmark

After a collection has been built with objective evidence units, run the
objective-first benchmark:

```bash
python3 scripts/evaluation/expert_gold/run_objective_gold_benchmark.py \
  --collection-id <collection_id>
```

For a single paper gate such as P001:

```bash
python3 scripts/evaluation/expert_gold/run_objective_gold_benchmark.py \
  --collection-id <collection_id> \
  --gold-paper-id P001
```

The runner converts the expert CSVs, exports an objective-first prediction
bundle with `--fact-source objective_first`, evaluates it, and prints a compact
summary. It reads an already-built collection; it does not rebuild PDFs or call
the extraction pipeline.

The runner also projects the exported objective-first prediction bundle into
the collection-level research-objective target shape and writes a target report
so row-level extraction gaps and research-chain coverage can be inspected from
the same benchmark run.

Default outputs are written under:

```text
tests/fixtures/local_expert_gold/generated/objective_first/
```

The generated files include:

```text
gold_bundle.json
objective_prediction_bundle.json
objective_evaluation_report.json
research_objective_target_prediction.json
research_objective_target_report.json
```

Do not commit generated benchmark bundles or reports.

## Evaluate Research Objective Target

The objective-first benchmark checks extracted rows against expert tables. The
research-objective target evaluator checks whether a collection-level
research-chain prediction covers the expert target claims, paper
contributions, limitations, and forbidden overclaims.

The committed target and reference prediction are:

```text
tests/fixtures/research_objective_targets/lpbf_slm_316l_collection_target.json
tests/fixtures/research_objective_targets/lpbf_slm_316l_reference_prediction.json
```

Run from the backend directory:

```bash
python3 scripts/evaluation/expert_gold/evaluate_research_objective_target.py \
  --prediction tests/fixtures/research_objective_targets/lpbf_slm_316l_reference_prediction.json \
  --report /tmp/research_objective_target_report.json \
  --quality-gate
```

The evaluator is offline and read-only. It does not call LLMs, rebuild PDFs, or
change collection state. Natural language is scored through required claims,
numbers, paper ids, mechanism-chain phrases, limitations, and forbidden
overclaim checks rather than exact paragraph matching.
