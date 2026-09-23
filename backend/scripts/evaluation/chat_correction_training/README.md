# Offline Chat correction training

This directory is an offline experiment boundary for P4 Chat correction
exports. It does not run from the Lens server, change an online model, or
publish a model. The input must be the JSONL returned by the P4 dataset export
endpoint and must remain immutable for the duration of an experiment.

## Prepare an export

Validate the export without installing training dependencies:

```bash
cd backend
.venv/bin/python scripts/evaluation/chat_correction_training/prepare.py \
  /path/to/chat-dataset.jsonl /tmp/chat-prepared \
  --validate-only
```

Create tokenized partitions in a separate training environment. The tokenizer
revision is pinned together with the model revision; the script preserves the
full P1 request, tool observations, reviewed target, Source references, review
digests, and P4 exclusions in the resulting JSONL.

```bash
uv venv /tmp/lens-chat-training
uv pip install --python /tmp/lens-chat-training/bin/python \
  'torch==2.7.*' 'transformers==4.53.*'

/tmp/lens-chat-training/bin/python \
  backend/scripts/evaluation/chat_correction_training/prepare.py \
  /path/to/chat-dataset.jsonl /tmp/chat-prepared \
  --tokenizer /path/to/model \
  --revision <tokenizer-revision> \
  --max-length 4096 \
  --local-files-only
```

`prepare.py` refuses an invalid manifest, an empty partition, a paper-family
or session-tree overlap, missing Source lineage, or a context overflow. It
does not truncate a reviewed example. Every prompt token receives label
`-100`; only the final reviewed target (plus EOS) contributes to the loss.

## Run the bounded comparison

Training requires an explicit authorization record that names the exact
dataset digest:

```json
{
  "scope": "chat_correction_training",
  "dataset_digest": "<P4 manifest digest>",
  "approved_by": "research-owner",
  "approved_at": "2026-09-23T00:00:00+00:00"
}
```

Run with a fixed model revision and a new output directory:

```bash
/tmp/lens-chat-training/bin/python \
  backend/scripts/evaluation/chat_correction_training/experiment.py \
  /tmp/chat-prepared /tmp/chat-experiment \
  --model /path/to/model \
  --revision <model-revision> \
  --authorization-file /path/to/authorization.json \
  --seed 17 \
  --max-steps 24 \
  --learning-rate 0.001 \
  --device cpu \
  --allow-download
```

The experiment evaluates the unchanged model on the eval partition, performs
the bounded update on train, evaluates the same eval rows again, saves the
model and tokenizer under `model/`, and reloads them once. `report.json` has a
self-checking digest and records model/tokenizer revision, seed, data and
manifest digests, baseline/after losses and generations, reload status, review
digests, exact Source references, and every P4 exclusion reason.

If authorization is missing, the revision is not fixed, or the isolated model
environment cannot load the requested model, the command writes a report with
`status: "not_run"` and an explicit reason. That is an expected outcome when
production data has not been authorized or the model is not available. No
online learning, deployment, automatic review, or scientific improvement claim
is made. Loss and generated text are engineering diagnostics; a researcher
must inspect the linked Source evidence and review decisions.

The repository's online `pyproject.toml`, Docker files, workflows, and release
paths are intentionally untouched. Keep the training environment disposable
and outside the Lens runtime environment.
