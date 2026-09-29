# Feedback dataset offline protocol

This directory is the offline boundary for the maintained feedback dataset
workflow. It consumes one immutable `DatasetExport` bundle and never reads the
legacy `DatasetSnapshot` shape or writes back to online Chat, samples, or
reviews.

## Input bundle

The online export contains three files:

```text
manifest.json       feedback-dataset-export-manifest.v1
data.jsonl          task-specific model-facing rows
provenance.jsonl    one trace record for each data row
```

`data.jsonl` contains readable document titles and source text in `context` or
`evidence`. It does not contain `case_id`, `session_id`, message IDs,
`source_ref`, document IDs, locators, review identities, or database digests.
Those fields remain in the provenance sidecar. The two JSONL files are aligned
by `row_key`, and the manifest binds them with content, provenance, and
manifest digests.

An old P5 snapshot JSON, an isolated JSONL file without its sidecars, or a
bundle with mismatched digests is rejected. The Python function
`prepare_snapshot()` remains only as an internal name for callers that have not
renamed their import; it delegates to `prepare_export()` and does not accept a
legacy snapshot payload.

## Prepare an experiment directory

```bash
python backend/scripts/evaluation/feedback_dataset/prepare.py \
  /tmp/export-bundle \
  /tmp/feedback-experiment \
  --revision "$(git -C backend rev-parse HEAD)" \
  --seed 7
```

`prepare_export()` validates the manifest schema and task type, file names,
row/provenance alignment, all three digests, task-specific fields, readable
evidence, and the absence of internal identity fields from model rows. It also
checks an optional experiment plan for source grouping and `train`/`eval`
isolation. A missing or uncertain source relationship is rejected instead of
being guessed from a document ID.

Without an experiment plan, preparation uses `evaluation_only` and puts all
selected rows in `eval`; this says nothing about isolation from a model's
external training history. For a train/eval run, pass a reviewed plan bound to
the manifest digest:

```json
{
  "schema_version": "feedback-experiment-plan.v1",
  "export_manifest_digest": "<manifest digest>",
  "mode": "train_eval",
  "rows": [
    {"row_digest": "<row digest>", "split": "train", "input_document_ids": ["document-a"], "source_review_reason": "Checked the complete input scope."},
    {"row_digest": "<row digest>", "split": "eval", "input_document_ids": ["document-b"], "source_review_reason": "Checked paper identity and version."}
  ],
  "document_groups": {"document-a": "paper-a", "document-b": "paper-b"}
}
```

The prepared directory contains a copy of the export sidecars, the plan,
`prepared.json`, and `train.jsonl`/`eval.jsonl`. Only this private directory
gets generated `row_id` values for prediction alignment; those IDs are not
added to the user-facing export.

`prepared.json` fixes the export digests, source revision, seed,
tokenizer/template name, split counts, plan digest, file names, and a prepared
digest. `load_prepared()` revalidates those values and rematerializes rows
before an experiment consumes them. Context overflow is an error; source,
target, and evidence text is never silently truncated.

## Compare predictions

An external runtime can write one JSON object per eval row:

```json
{"row_id":"row_abc","prediction":"model output"}
```

Preference predictions may use `{"row_id":"row_abc","choice":"chosen"}`.
Run:

```bash
python backend/scripts/evaluation/feedback_dataset/experiment.py \
  /tmp/feedback-experiment \
  /tmp/feedback-experiment/report.json \
  --baseline-predictions /tmp/baseline.jsonl \
  --experiment-predictions /tmp/candidate.jsonl \
  --weights-manifest /tmp/weights.json
```

The baseline and candidate must cover exactly the same eval row IDs. A partial
artifact leaves the overall report `not_run`, while preserving the completed
branch for diagnosis. Weight metadata, when supplied, must match the export
manifest digest, source revision, and seed. The report records protocol
digests, row-set digest, metrics, artifact byte digests, and
`deployment.status=not_run`; it is not evidence that a training framework
loaded weights or that an online model changed.

## Verification

```bash
cd backend
./.venv/bin/python -m pytest -q \
  tests/unit/scripts/test_feedback_dataset_offline.py \
  tests/unit/feedback/test_task_dataset_export.py
./.venv/bin/python -m compileall -q scripts/evaluation/feedback_dataset
git diff --check
```
