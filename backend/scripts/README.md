# Backend Scripts

This directory owns backend-local utility scripts that support development,
debugging, and validation workflows.

Benchmark and probe scripts live under [`benchmarks/`](benchmarks/). Keep
general local debugging helpers at this level instead of adding them to the
benchmark-only directory.

## Feedback Analysis Worker

Run one feedback-analysis job:

```bash
cd backend
./.venv/bin/python scripts/feedback_analysis_worker.py --once
```

The worker does not retry failed jobs automatically. An operator can explicitly
return one failed, result-less `feedback_analysis` job to `pending`:

```bash
cd backend
./.venv/bin/python scripts/feedback_analysis_worker.py \
  --requeue-job <job_id>
```

The command clears the failed run's timestamps and error code, preserves the
job identity and idempotency key, and prints `pending`. It rejects succeeded,
running, cancelled, non-feedback, or already-resulted jobs. This is an
internal CLI operation; this checkpoint does not add an HTTP endpoint, RBAC, or
automatic retry policy.

## Correction Signal Analysis Worker

Run one message-derived correction-signal job:

```bash
cd backend
./.venv/bin/python scripts/correction_signal_analysis_worker.py --once
```

The worker only processes `correction_signal_analysis` jobs. A candidate is
cancelled when its adjacent challenge disappears or its durable content digest
changes; ordinary follow-up questions never enter this queue. It does not
modify Chat messages or create a training target. Use `--interval <seconds>`
for an explicit polling loop; no hidden FastAPI background task is started.

The PaperExperiment Draft path is exercised by the Objective analysis
application service, not by a standalone script in this directory. The service
builds a bounded Source bundle, calls the configured provider, reconciles
candidate boundaries, and writes an immutable revision only after deterministic
binding checks. Live-provider validation artifacts live outside the production
script surface; do not add a probe link here unless the script exists and its
input, model, and output contract are documented.

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

Export prediction output from a built collection:

```bash
cd backend
python3 scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --collection-id <collection_id>
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
and Core extraction artifacts for one built collection.

The script is read-only against collection artifacts. It reads Source/Core
records from the repository and writes normalized JSON, CSV, and Markdown
review files under `backend/data/traces/`.

Example:

```bash
cd backend
./.venv/bin/python scripts/export_extraction_trace.py \
  --collection-id col_1acbd377905b
```

For a direct output directory:

```bash
cd backend
./.venv/bin/python scripts/export_extraction_trace.py \
  --output-dir data/collections/col_1acbd377905b/output
```

Optional filters and naming:

```bash
cd backend
./.venv/bin/python scripts/export_extraction_trace.py \
  --collection-id col_1acbd377905b \
  --document-id <document_id> \
  --trace-name manual-review
```

## Trace Output

Each run writes a directory like:

```text
backend/data/traces/<collection-or-output-name>-<timestamp>/
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
contain source-paper text, extracted claims, and other collection-specific
content.

## Expected Inputs

The script exports whatever artifacts exist. It does not rebuild a collection.

If a collection was built before a newer Source/Core artifact existed, the
trace will show missing sections. For example, a collection built before
`tables` existed will show:

```text
No `tables` rows found.
```

Rebuild the collection first when you need to inspect newly added artifact
families.

## Source Table Split Preview

Use `export_source_tables.py` when you want to inspect only the Source table
split output. It can read existing artifacts or reparse collection input PDFs
with the current Source code without writing back to the collection.

```bash
cd backend
./.venv/bin/python scripts/export_source_tables.py \
  --collection-id col_ed3ea76e79c3 \
  --destination /tmp/source-table-preview \
  --reparse-inputs
```

For PaperExperiment quality, report raw model Draft counts separately from
service reconciliation and binding. A partial revision is an auditable archive,
not proof that the paper is ready for Objective selection or Finding synthesis.
