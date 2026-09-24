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
family and session tree. Context overflow is an error; Source or target text is
never silently truncated. The token accounting format is
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

The report records the snapshot digests, source revision, seed, evaluation row
set, baseline/candidate metrics, weight provenance and deployment status. If a
prediction or model artifact is unavailable, the report stays `not_run`; this
protocol never deploys weights or changes online Chat behavior.
