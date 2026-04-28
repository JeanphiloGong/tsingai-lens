# Backend Scripts

This directory owns backend-local utility scripts that support development,
debugging, and validation workflows.

Benchmark and probe scripts live under [`benchmarks/`](benchmarks/). Keep
general local debugging helpers at this level instead of adding them to the
benchmark-only directory.

## Extraction Trace Export

Use `export_extraction_trace.py` when you want to inspect the concrete Source
and Core extraction artifacts for one built collection.

The script is read-only against collection artifacts. It reads parquet files
from a collection output directory and writes normalized JSON, CSV, and
Markdown review files under `backend/data/traces/`.

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
  Human-readable Source table context from `tables.parquet`, with row anchors
  from `table_rows.parquet`.
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
`tables.parquet` existed will show:

```text
No `tables.parquet` rows found.
```

Rebuild the collection first when you need to inspect newly added artifact
families.
