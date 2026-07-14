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
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_findings_projection.py \
  --api-base-url http://localhost:5173

LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
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
./.venv/bin/python scripts/evaluation/expert_gold/prepare_goal_review_workspace.py \
  --collection-id <collection_id>
```

This creates one read-only handoff directory with `review-packet.txt`,
`review-candidates.jsonl`, `reviewed-findings.template.jsonl`,
`agent-review-prompts.jsonl`, `review-dashboard.md`,
`review-priority.md`, `expert-decision-board.tsv`, `review-checklist.md`,
`review-unlock-plan.md`,
`dataset-readiness.md`, `expert-satisfaction.md`, `training-ready.messages.jsonl`,
`training-ready.dataset.jsonl`, `optimization-summary.md`,
`review-commands.sh`, `dataset-quality-summary.json`, `manifest.json`, and
`README.txt`. It does not
import labels or mutate collection data; it only packages the current Findings
review queue, current training-ready exports, and error/risk statistics so an
expert can inspect source links, see which goals are not yet training-ready,
and fill explicit decisions.
Use `review-priority.md` to decide which candidates to inspect first, then use
`expert-decision-board.tsv` when the reviewer wants a spreadsheet-style board
with priority, allowed actions, required checks, source quote, and open links.
The board includes empty `expert_action`, `issue_type`, `expert_note`, and
`corrected_*` columns for human input. It is not imported directly; merge it
back into the JSONL template first:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/merge_expert_decision_board.py \
  reviewed-findings.template.jsonl \
  expert-decision-board.tsv \
  --output-path reviewed-findings.from-board.jsonl
```

Use `review-unlock-plan.md` to see which decision unlocks training export or
protocol inputs. Run `review-commands.sh` from the workspace directory for the
matching TSV merge, dry-run, gate, and export commands. The real import command
in that script is commented out and must be enabled only after a human expert
approves the dry-run.
By default, the script creates a unique directory under `/tmp`; pass
`--output-dir <empty_dir>` only when a fixed destination is required.

To print the packet directly instead of preparing a workspace, run:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format review-packet
```

This packet is read-only. It is meant to help a human expert decide whether to
accept, reject, or correct each candidate in the goal review UI; it does not
promote any sample to `training_ready`.
For batch handoff to an independent reviewer or review agent, emit one pending
candidate per line:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format review-jsonl

./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format decision-template \
  > reviewed-findings.jsonl
```

Use `review-jsonl` when the reviewer needs the full candidate payload and
evidence records. Use `decision-template` when the reviewer needs a compact
editable import file. Each decision-template row also carries `acceptance_gate`
with `accept_allowed`, `blocking_missing`, and expert `review_checks`, plus an
expert-facing `review_decision_hint` that summarizes whether direct accept is
allowed, which actions remain valid, and why accept is blocked when correction
is required. It also includes a compact `review_work_order` with the
recommended decision path, allowed/blocked actions, required checks, and
whether an accepted or corrected row can unlock training export and protocol
inputs. The `evidence` summary carries `evidence_ref_id`, source label, page,
quote, and source-open link so the reviewer can audit the row before changing
the action.
Each exported row defaults to `"action": "skip"`. The reviewer changes only rows they have checked
to `accept`, `reject`, or `correct`; unchanged rows stay skipped and are not
written as labels. `reject` rows need an `issue_type` such as `wrong_variable`,
`wrong_direction`, or `insufficient_evidence`. `correct` rows need a corrected
`suggested_target.statement` and at least one `evidence_ref_id`. Rows with
`acceptance_gate.accept_allowed=false` or `protocol_readiness.blocking_missing`
cannot be imported as `accept`; change them to `correct` after filling the
missing fields/evidence, `reject`, or leave them as `skip`. Validate first,
then import with a human reviewer id:

If the reviewer used `expert-decision-board.tsv`, run
`merge_expert_decision_board.py` first and use the merged
`reviewed-findings.from-board.jsonl` in the dry-run/import commands below.
The merge step refuses blocked accepts, rejects without `issue_type`, and
corrections without corrected statement and evidence refs before the stricter
import validation runs.

For agent-assisted review, keep every exported row at `"action": "skip"` and
write the agent's suggestion under `agent_review` instead. To prepare a safe
draft file for the agent to fill, run:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format agent-review-prompt-jsonl \
  > agent-review-prompts.jsonl
```

`agent-review-prompt-jsonl` is the structured review input for an independent
review agent. Each row contains the finding fields, acceptance gate, protocol
readiness, evidence quotes and source links, suggested target, and the expected
`agent_review` output schema. It intentionally does not include a top-level
`action` field and does not set `human_confirmed`; it is a prompt/input packet,
not an import file.
After the agent writes one `agent_review` result per `finding_id`, merge those
results back into the decision-template rows without making them importable:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/merge_agent_review_results.py \
  reviewed-findings.jsonl \
  agent-review-results.jsonl \
  --output-path agent-reviewed-findings.jsonl
```

The merge output keeps every row at `action=skip` and forces
`agent_review.human_confirmed=false`. It is still only a review draft until a
human expert confirms individual rows.
After the agent reviews the source evidence, it may change only
`agent_review.recommendation`, `agent_review.issue_type`,
`agent_review.note`, and `agent_review.suggested_target`. Example:

```json
{
  "action": "skip",
  "agent_review": {
    "reviewer": "ai-reviewer-codex",
    "recommendation": "correct",
    "issue_type": "wrong_outcome",
    "note": "The quote supports ductility, not generic mechanical properties.",
    "suggested_target": {
      "statement": "Preheating increased ductility by 14%.",
      "evidence_ref_ids": ["evref_..."]
    }
  }
}
```

Check the draft before giving it to a human expert:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_agent_review_draft.py \
  agent-reviewed-findings.jsonl \
  --format text
```

This checker never writes labels. It fails if an agent draft changes `action`
away from `skip`, if an agent reviewer does not use an `ai-reviewer*` or
`agent-*` id, or if an agent recommends `accept` while `acceptance_gate` blocks
direct acceptance. A human expert must verify the `agent_review` suggestions and
set `agent_review.human_confirmed=true` only on rows they approve. Then convert
those confirmed suggestions into an importable decision file:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/confirm_agent_review_decisions.py \
  agent-reviewed-findings.jsonl \
  --output-path human-confirmed-findings.jsonl
```

Rows without `agent_review.human_confirmed=true` stay at `action=skip`.
Confirmed `unclear` or `skip` recommendations also remain skipped. Confirmed
`accept`, `reject`, or `correct` recommendations become normal import actions;
blocked accepts still fail and must be corrected, rejected, or left skipped.

```bash
./.venv/bin/python scripts/evaluation/expert_gold/import_goal_review_decisions.py \
  human-confirmed-findings.jsonl \
  --reviewer materials-expert@example.com \
  --dry-run \
  --fail-on-warnings \
  --format text

./.venv/bin/python scripts/evaluation/expert_gold/import_goal_review_decisions.py \
  human-confirmed-findings.jsonl \
  --reviewer materials-expert@example.com \
  --format text
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
Use `--format text` for the pre-import expert loop when you want a compact
readiness report instead of the full JSON payload. The text output shows the
current goal counts, pending accept/correct/reject decisions, projected
`training_ready`, projected training-message and protocol-ready counts, remaining
review candidates, rejected counts, and the first readiness issues that still
block fine-tuning messages or protocol inputs.
When skipped template rows include `review_work_order`, the text output also
shows the next skipped finding's recommended decision path, whether direct
accept is allowed, and the checks that should be completed before changing the
row away from `skip`.
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
The same summary also includes `optimization_breakdown` and top lists grouped
by variable, outcome, direction, and evidence role. Use these grouped counts to
decide whether the next optimization should target, for example, table-row
evidence handling, a recurring variable confusion, or direction classification.

After expert acceptance or curation creates `training_ready` samples, export the
fine-tuning-compatible message rows with:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --format messages-jsonl \
  --require-training-ready
```

For evaluation, audit, or dataset registry import, use `training-jsonl` to keep
the same `messages` payload plus `collection_id`, `goal_id`, `finding_id`,
`claim_id`, reviewer/status fields, and `evidence_ref_ids` metadata:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
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
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_expert_loop.py
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
running API exposes the goal-session routes and the goal-scoped
experiment-plan list, create, and update routes required by the Goal Copilot
to draft and save traceable protocol plans. This default runtime check is
read-only: it inspects the running OpenAPI contract but does not create a
session, message, or plan.
If the source app exposes those routes but the running API does not, the text
summary reports `running_api_not_current_backend`; restart or update the
backend process, or point `--api-base-url` at the current Lens app before
validating protocol-draft saving.
To prove that the running API can actually create and edit goal-scoped plans,
run an explicit write smoke check with an authenticated operator account:

```bash
LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --api-base-url http://localhost:5173 \
  --runtime-write-check
```

`--runtime-write-check` creates a small manual smoke experiment-plan draft for
the first checked goal and immediately updates it to `archived`. It proves the
running API can persist editable goal-scoped plans, but it does not call the
LLM or create a Goal Copilot source message. The stricter Goal Copilot save
contract is enforced in application code and tests: a saved plan with
`source_message_id` must come from a collection-grounded assistant message with
`review_gate=protocol_ready_findings`, auditable source links, used evidence
ids, and protocol-draft structure. Use the runtime write check only when
writing runtime test data is acceptable.
For a human-readable queue instead of the full JSON payload, run:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --require-complete \
  --format text
```

By default `check_goal_dataset_quality.py` is a reviewability gate: a goal may
pass with only `review_candidate` samples. To require samples that can be used
for training export, add:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py \
  --require-training-ready

./.venv/bin/python scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --require-all-training-ready
```

That stricter mode fails until every checked goal has at least one
`training_ready` sample. Both scripts are read-only and do not rebuild
collections or mutate feedback.

For final acceptance of the full expert loop, use the expert satisfaction gate:

```bash
LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
./.venv/bin/python scripts/evaluation/expert_gold/check_goal_expert_loop.py \
  --api-base-url http://localhost:5173 \
  --expert-satisfaction-gate \
  --format text
```

This mode fails unless every checked goal has a training-ready sample, valid
training messages, protocol-ready experiment inputs, zero remaining review
candidates, a running API that exposes the Goal Copilot and experiment-plan
routes, and a running API that can create/update a goal-scoped manual
experiment-plan smoke draft. It is intentionally stricter than the default
diagnostic check, which may report `pass (incomplete)` while there is still
review work left.

The evaluator is offline and read-only. It does not call LLMs, rebuild PDFs, or
change collection state. Natural language is scored through required claims,
numbers, paper ids, mechanism-chain phrases, limitations, and forbidden
overclaim checks rather than exact paragraph matching.
