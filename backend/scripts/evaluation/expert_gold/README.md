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
