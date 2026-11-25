# Backend Scripts

This directory owns backend-local utility scripts that support development,
debugging, and validation workflows.

Benchmark and probe scripts live under [`benchmarks/`](benchmarks/). Keep
general local debugging helpers at this level instead of adding them to the
benchmark-only directory.

## Research Workers

HTTP and Agent calls enqueue work; run these independent processes to execute it:

```bash
cd backend
./.venv/bin/python scripts/run_document_preparation.py
./.venv/bin/python scripts/run_objective_discovery.py
./.venv/bin/python scripts/run_objective_analysis.py
```

Use `--once` to claim at most one job. `--lease-seconds` defaults to 300 and
`--heartbeat-seconds` to 30; the heartbeat must be shorter than the lease.
Each process executes one job at a time. Start additional concrete processes
for concurrency. They need the same PostgreSQL database, model configuration
and shared `DATA_DIR` object directory as Web. No worker is started by FastAPI.
Stop old Web execution processes before applying migration `20261031_0090`, then
start the new Web and worker processes. Only expired running work is reclaimed;
failed jobs retain their existing explicit retry policy. A Web restart does not
mark live worker jobs interrupted. SIGTERM and Ctrl+C cancel and await the owned asyncio
tasks; synchronous parser/model threads finish within their actual call budgets.

## Expert Gold Evaluation

Use [`evaluation/expert_gold/`](evaluation/expert_gold/) for offline utilities
that validate expert-filled PBF-metal annotation tables before they are turned
into gold-set evaluation inputs and export system artifacts into comparable
prediction bundles.

Validate expert CSV tables:

```bash
cd backend
uv run python scripts/evaluation/expert_gold/validate_expert_gold.py \
  --input tests/fixtures/local_expert_gold
```

Convert validated expert CSV tables:

```bash
cd backend
python3 scripts/evaluation/expert_gold/convert_expert_gold.py \
  --input tests/fixtures/local_expert_gold
```

Export prediction output from a built workspace:

```bash
cd backend
python3 scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --workspace-id <workspace_id>
```

Evaluate the generated gold and prediction bundles:

```bash
cd backend
python3 scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py \
  --gold-paper-id P001
```

## Agent Behavior Promotion

Use [`evaluation/agent_behavior_promotion/`](evaluation/agent_behavior_promotion/)
to evaluate whether a generalized Deep Path research behavior has passed
pre-registered expert Gold, independent fresh-paper, scientific-error, runtime,
and cost boundaries. The gate only makes a behavior eligible for maintainer
review; it never modifies Fast Path automatically.

## Extraction Trace Export

Use `export_extraction_trace.py` when you want to inspect the concrete Source
and Core extraction artifacts for one built workspace.

The script is read-only against workspace artifacts. It reads Source/Core
records from the repository and writes normalized JSON, CSV, and Markdown
review files under `backend/data/traces/`.

Example:

```bash
cd backend
./.venv/bin/python scripts/export_extraction_trace.py \
  --workspace-id col_1acbd377905b
```

For a direct output directory:

```bash
cd backend
./.venv/bin/python scripts/export_extraction_trace.py \
  --output-dir data/workspaces/col_1acbd377905b/output
```

Optional filters and naming:

```bash
cd backend
./.venv/bin/python scripts/export_extraction_trace.py \
  --workspace-id col_1acbd377905b \
  --document-id <document_id> \
  --trace-name manual-review
```

## Trace Output

Each run writes a directory like:

```text
backend/data/traces/<workspace-or-output-name>-<timestamp>/
```

Important files:

- `README.md`
  Local summary with artifact row counts.
- `summary.json`
  Machine-readable artifact row counts and source paths.
- `source_tables.md`
  Human-readable Source table context from `tables`, with row anchors from
  `table_rows`.
- `extraction_trace.md`
  Human-readable Core extraction facts, evidence cards, measurement results,
  and evidence anchors.
- `artifacts/*.json`
  Normalized raw artifact records.
- `artifacts/*.csv`
  Spreadsheet-friendly artifact records.

`backend/data/traces/` is gitignored because it is local runtime output and may
contain source-paper text, extracted claims, and other workspace-specific
content.

## Expected Inputs

The script exports whatever artifacts exist. It does not rebuild a workspace.

If a workspace was built before a newer Source/Core artifact existed, the
trace will show missing sections. For example, a workspace built before
`tables` existed will show:

```text
No `tables` rows found.
```

Rebuild the workspace first when you need to inspect newly added artifact
families.

## Source Table Split Preview

Use `export_source_tables.py` when you want to inspect only the Source table
split output. It can read existing artifacts or reparse workspace input PDFs
with the current Source code without writing back to the workspace.

```bash
cd backend
./.venv/bin/python scripts/export_source_tables.py \
  --workspace-id col_ed3ea76e79c3 \
  --destination /tmp/source-table-preview \
  --reparse-inputs
```

For PaperExperiment quality, report raw model Draft counts separately from
service reconciliation and binding. A partial revision is an auditable archive,
not proof that the paper is ready for Objective selection or Finding synthesis.
