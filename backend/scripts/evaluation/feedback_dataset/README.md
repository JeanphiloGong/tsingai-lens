# Feedback dataset offline protocol

This directory consumes the immutable detail JSON returned by P5:

New exports contain no paper-family inputs or train/eval assignments. With no
experiment plan, preparation selects all rows for evaluation only; it makes no
claim about isolation from a model's external training history. The saved
`experiment-plan.json` is bound into `prepared.json` and checked again before
each experiment. Historical v2 snapshots retain their frozen splits and
cannot be overridden by a new plan.

For a train/eval experiment, pass `--experiment-plan /tmp/plan.json`. The plan
uses full canonical row digests from the snapshot's private provenance:

```json
{
  "schema_version": "feedback-experiment-plan.v1",
  "snapshot_manifest_digest": "<snapshot manifest_digest>",
  "mode": "train_eval",
  "rows": [
    {"row_digest": "<first row_digest>", "split": "train", "input_document_ids": ["document-a"], "source_review_reason": "Checked the complete question and input sources."},
    {"row_digest": "<second row_digest>", "split": "eval", "input_document_ids": ["document-b"], "source_review_reason": "Checked version identity against the paper metadata."}
  ],
  "document_groups": {"document-a": "paper-a", "document-b": "paper-b"}
}
```

The experimenter reviews the entire input source scope, includes every known
document plus any missing input sources, and records the reason for the
grouping. Different versions of the same paper must share a group. Titles
alone do not establish identity. Missing groups, omitted known documents,
missing review reasons, or shared groups/session trees across train/eval are
rejected before writing output. Both splits must be nonempty for `train_eval`.
An explicit `evaluation_only` plan can select a subset using just row digests
and `split: "eval"`, with an empty `document_groups` object. Duplicate content
is selected and assigned together, not divided by case identity. The check
enforces the supplied grouping, not the scientific truth of that judgment.

```bash
python backend/scripts/evaluation/feedback_dataset/prepare.py \
  /tmp/dataset-snapshot.json \
  /tmp/feedback-experiment \
  --revision "$(git -C backend rev-parse HEAD)" \
  --seed 7
```

`prepare.py` verifies the snapshot and writes `snapshot.json`, `prepared.json`,
`train.jsonl`, and `eval.jsonl`. Snapshot rows are deliberately model-facing:
they contain the question/messages, target or preference pair, and readable
evidence (`document_title`, `quote`, and optional location fields). They do not
contain `case_id`, `session_id`, `source_ref`, `source_refs`, review digests, or
other storage identities. The private provenance ledger in `snapshot.json`
retains those identities for audit and later experiment preparation.

During preparation the script derives an experiment-only `row_id` from each
clean row's canonical digest. That identifier appears only in the prepared
`train.jsonl`/`eval.jsonl` files and prediction protocol; it is not part of the
downloaded dataset. The script checks the manifest, provenance and content
digests, dataset-specific fields, and experiment-plan isolation by source group
and session tree. `prepared.json` also carries a digest over its revision, seed,
tokenizer, counts, and file names; changing those values makes the directory
unusable until it is prepared again. Context overflow is an error; Source or
target text is never silently truncated. The token accounting format is
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

## Real-paper validation scenario

The feedback workbench was exercised against two open-access papers instead of
placeholder documents:

- Martin et al. (2019), *Dynamics of pore formation during laser powder bed
  fusion additive manufacturing*, DOI
  `10.1038/s41467-019-10009-2`,
  <https://www.nature.com/articles/s41467-019-10009-2.pdf>.
- Pham et al. (2020), *The role of side-branching in microstructure
  development in laser powder-bed fusion*, DOI
  `10.1038/s41467-020-14453-3`,
  <https://www.nature.com/articles/s41467-020-14453-3.pdf>.

The review question is whether scan-velocity and scan-strategy findings can be
compared across the two studies. The expected evidence boundary is concrete:
Martin studies Ti-6Al-4V keyhole pore formation near scan-velocity changes;
Pham studies FCC-alloy microstructure and side-branching under scan-strategy
changes. The workbench must preserve those material, process-variable, outcome,
page, DOI, and Source-quote differences instead of turning them into one
performance trend.

The live validation creates three internal candidate cases from the same conversation:
a negative answer rating, a later natural-language correction, and a failed
Source-read tool result. The first case was annotated and accepted for an
`evaluation` snapshot. Candidate analysis remains an internal workbench input;
it is not a user dataset export. Only the accepted snapshot is a dataset
release.
The PDF files are intentionally not committed to the repository. Re-download
the two public URLs when rebuilding this scenario, then verify the collection
contains two `ready` documents before inspecting feedback cases.
