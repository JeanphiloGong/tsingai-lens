# Feedback dataset offline protocol

This directory consumes the immutable detail JSON returned by P5:

```bash
python backend/scripts/evaluation/feedback_dataset/prepare.py \
  /tmp/dataset-snapshot.json \
  /tmp/feedback-experiment \
  --revision "$(git -C backend rev-parse HEAD)" \
  --seed 7
```

`prepare.py` verifies the snapshot and writes `snapshot.json`, `prepared.json`,
`train.jsonl`, and `eval.jsonl`. It checks the manifest, provenance and content
digests, row digests, dataset-specific fields, and train/eval isolation by paper
family and session tree. `prepared.json` also carries a digest over its revision,
seed, tokenizer, counts, and file names; changing those values makes the
directory unusable until it is prepared again. Context overflow is an error;
Source or target text is never silently truncated. The token accounting format is
`lens-whitespace-v1`; it documents prompt/target loss masks but is not a model
tokenizer or a claim that training has happened.

An external model runtime may produce one JSON object per evaluation row with a
`row_id` and `prediction` (or `choice` for preference data). Compare two such
artifacts on the exact same frozen eval set:

```bash
python backend/scripts/evaluation/feedback_dataset/experiment.py \
  /tmp/feedback-experiment \
  /tmp/feedback-experiment/report.json \
  --baseline-predictions /tmp/baseline.jsonl \
  --experiment-predictions /tmp/candidate.jsonl \
  --weights-manifest /tmp/weights.json
```

The report records the snapshot digests, the prepared directory digest, source
revision, seed, evaluation row set, baseline/candidate metrics, weight
provenance and deployment status. It also contains a
`feedback-offline-run-manifest.v1` `run_manifest`. Its deterministic `run_id`
is derived from the validated protocol and the byte digests of the prediction
and weight-manifest inputs, so moving the same files to another directory does
not create a different run identity. Each provided prediction artifact records
its SHA-256, byte size and non-empty JSONL record count; a weight manifest
records its SHA-256 and byte size. Absolute paths remain only in the detailed
branch report for diagnosis and are excluded from `run_id`.

Both baseline and candidate prediction artifacts are required before the report
is marked `completed`; a partial run remains `not_run` with its completed branch
preserved for diagnosis. The manifest is an audit ledger, not evidence that a
training framework loaded weights. If a prediction or model artifact is
unavailable, training and deployment remain outside this protocol, and the
script never changes online Chat behavior.
