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

## Check Runtime Goal Readiness

For the local six-goal 316L validation collection, run the two read-only
runtime checks against a running frontend/API origin:

```bash
LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
python3 scripts/evaluation/expert_gold/check_goal_findings_projection.py \
  --api-base-url http://localhost:5173

LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --api-base-url http://localhost:5173
```

`check_goal_findings_projection.py` verifies the expert-facing finding rows,
evidence roles, boundaries, and source traceback. `check_goal_dataset_quality.py`
verifies the dataset preparation side: each confirmed goal has at least one
active sample for review or training, no failed or unavailable trace warnings,
text input blocks, and traceable training evidence. `training_ready` is reserved
for curated or accepted samples with an explicit non-AI reviewer id. AI-authored
or anonymous feedback/curation remains `silver` and `review_candidate` until a
human expert confirms it.

To print a compact expert review packet with each pending candidate finding,
its variables/outcomes/direction, evidence quote, source link, and direct
frontend finding review entry, run:

```bash
python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format review-packet
```

This packet is read-only. It is meant to help a human expert decide whether to
accept, reject, or correct each candidate in the goal review UI; it does not
promote any sample to `training_ready`.
For batch handoff to an independent reviewer or review agent, emit one pending
candidate per line:

```bash
python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format review-jsonl

python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format decision-template \
  > reviewed-findings.jsonl
```

Use `review-jsonl` when the reviewer needs the full candidate payload and
evidence records. Use `decision-template` when the reviewer needs a compact
editable import file. Each decision-template row also carries `acceptance_gate`
with `accept_allowed`, `blocking_missing`, and expert `review_checks`, plus an
`evidence` summary with `evidence_ref_id`, source label, page, quote, and
source-open link so the reviewer can audit the row before changing the action.
Each exported row defaults to `"action": "skip"`. The reviewer changes only rows they have checked
to `accept`, `reject`, or `correct`; unchanged rows stay skipped and are not
written as labels. `reject` rows need an `issue_type` such as `wrong_variable`,
`wrong_direction`, or `insufficient_evidence`. `correct` rows need a corrected
`suggested_target.statement` and at least one `evidence_ref_id`. Rows with
`acceptance_gate.accept_allowed=false` or `protocol_readiness.blocking_missing`
cannot be imported as `accept`; change them to `correct` after filling the
missing fields/evidence, `reject`, or leave them as `skip`. Validate first,
then import with a human reviewer id:

```bash
python3 scripts/evaluation/expert_gold/import_goal_review_decisions.py \
  reviewed-findings.jsonl \
  --reviewer materials-expert@example.com \
  --dry-run \
  --fail-on-warnings

python3 scripts/evaluation/expert_gold/import_goal_review_decisions.py \
  reviewed-findings.jsonl \
  --reviewer materials-expert@example.com
```

The import writes only explicit human expert decisions. It rejects AI/agent
reviewer ids and does not promote unreviewed AI suggestions to gold labels.
Dry-run validation also checks that each reviewed `finding_id` still exists in
the current goal dataset, that an exported `claim_id` still matches that
finding, and that corrected `evidence_ref_id` values belong to that finding, so
stale or hand-edited rows fail before any label is written.
Dry-run and import summaries may include `warnings` for accepted or corrected
rows that were originally paper-level, table-row, mechanism, or cross-paper
confirmation candidates. These warnings do not block import; they tell the
expert which promoted rows deserve one more look before training export. Add
`--fail-on-warnings` during dry-run to make those warnings block until the
expert changes the row to `correct`, `reject`, or leaves it as `skip`.
If every row is still `skip`, dry-run reports a `no_actionable_decisions`
warning because no expert labels will be written; with `--fail-on-warnings`,
that unchanged template fails validation.
Every dry-run and import summary includes `review_progress`, which reports how
many rows are actionable, how many remain skipped, whether the file is ready to
write, and the next steps needed before import.
Successful non-dry-run imports include `affected_goals` with the resulting
`training_ready`, training-message, protocol-ready, review-candidate, and
rejected counts so reviewers can immediately see whether the goal is ready for
training export or protocol drafting. Each affected goal also lists up to 10
`readiness_issues` for training-ready samples that still lack fine-tuning
messages or protocol inputs.
Dataset quality summaries also include top diagnostic lists for error
categories, issue types, review reasons, and system warnings. Use these counts
after imports to identify whether the model is mostly failing on variables,
directions, evidence grounding, or risky review promotions before changing
prompts or building fine-tuning data.

After expert acceptance or curation creates `training_ready` samples, export the
fine-tuning-compatible message rows with:

```bash
python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format messages-jsonl \
  --require-training-ready
```

For evaluation, audit, or dataset registry import, use `training-jsonl` to keep
the same `messages` payload plus `collection_id`, `goal_id`, `finding_id`,
`claim_id`, reviewer/status fields, and `evidence_ref_ids` metadata:

```bash
python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format training-jsonl \
  --require-training-ready
```

The dataset quality summary also reports `protocol_ready_count`. A sample is
protocol-ready only when it is `training_ready`, has valid fine-tuning messages,
contains a statement plus variable/outcome/direction-or-scope fields, and keeps
traceable training evidence. This is the stricter subset that Goal Copilot can
use as grounded input for experiment protocol drafts.

To run the combined three-layer gate for expert review, dataset accumulation,
and experiment-planning readiness:

```bash
python3 scripts/evaluation/expert_gold/check_goal_expert_loop.py
```

The combined check passes only when the expert-facing Findings are reviewable,
the dataset exports active samples, and at least one goal has a
`training_ready` sample with protocol-ready inputs that Goal Copilot can use
for traceable protocol drafting. Its `completion_status` can still be
`incomplete`; use `remaining_work` to see how many review candidates and
goal-level training, message, and protocol-input gaps remain before calling the
full expert loop finished.
`remaining_work.pending_goals` is the human review queue for the next expert
loop: each row includes the research question, review candidate count, the next
action, and a frontend `href` that opens the goal review queue or
training-ready export view.
When `--api-base-url` is provided, the combined check also verifies that the
running API exposes the goal-scoped experiment-plan list, create, and update
routes required to save traceable protocol drafts. This default runtime check
is read-only: it inspects the running OpenAPI contract but does not create a
plan.
If the source app exposes those routes but the running API does not, the text
summary reports `running_api_not_current_backend`; restart or update the
backend process, or point `--api-base-url` at the current Lens app before
validating protocol-draft saving.
To prove that the running API can actually create and edit goal-scoped plans,
run an explicit write smoke check with an authenticated operator account:

```bash
LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
python3 scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --api-base-url http://localhost:5173 \
  --runtime-write-check
```

`--runtime-write-check` creates a small smoke experiment-plan draft for the
first checked goal and immediately updates it to `archived`. Use it only when
writing runtime test data is acceptable.
For a human-readable queue instead of the full JSON payload, run:

```bash
python3 scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --require-complete \
  --format text
```

By default `check_goal_dataset_quality.py` is a reviewability gate: a goal may
pass with only `review_candidate` samples. To require samples that can be used
for training export, add:

```bash
python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --require-training-ready

python3 scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --require-all-training-ready
```

That stricter mode fails until every checked goal has at least one
`training_ready` sample. Both scripts are read-only and do not rebuild
collections or mutate feedback.

For final acceptance of the full expert loop, use:

```bash
python3 scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --require-complete
```

This mode fails unless every checked goal has a training-ready sample, valid
training messages, and zero remaining review candidates.

The evaluator is offline and read-only. It does not call LLMs, rebuild PDFs, or
change collection state. Natural language is scored through required claims,
numbers, paper ids, mechanism-chain phrases, limitations, and forbidden
overclaim checks rather than exact paragraph matching.
