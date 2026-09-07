# Agent Behavior Promotion Gate

This directory owns the offline gate for deciding whether one generalized
Research Agent behavior has enough evidence to enter Fast Path code review. It
does not modify prompts, rules, pipeline code, or persisted research records.

## Research Scenario

A researcher may use Deep Path to resolve an exception that the batch pipeline
missed. For example, an Agent can find an undefined experiment-group label in a
Results table, inspect the same paper's Methods section, and bind the definition
and result as two source-local facts. The reusable candidate is that research
action, not the paper's particular label definition.

Before maintainers may implement that action in Fast Path, the candidate must
follow this sequence:

1. Preserve the originating trajectory's ToolCalls, Sources, Evidence, and
   judgments.
2. Describe the generalized research action, its scientific invariant, and the
   paper-specific shortcuts that must remain forbidden.
3. Have a research lead approve recall, scientific-error, technical-failure,
   token, and model-call bounds before either evaluation begins.
4. Replay the same implementation revision on an expert Gold set that was
   frozen before the originating behavior was observed.
5. Evaluate it on a separately sealed fresh-paper set that shares no papers
   with Gold or behavior development.
6. Obtain an identified human expert review of both result sets.
7. Run the deterministic gate. A passing result permits maintainer review; it
   never promotes or deploys the behavior automatically.

This ordering prevents a successful one-paper maneuver, a threshold selected
after seeing results, or a relabelled Gold paper from becoming a general
scientific rule.

## Record And Evidence

`agent_behavior_promotion.v1` is the input record. Generate its complete JSON
Schema with:

```bash
cd backend
./.venv/bin/python \
  scripts/evaluation/agent_behavior_promotion/validate_promotion_record.py \
  --print-schema
```

Keep the record and all referenced artifacts in one review directory. Artifact
paths are relative to that directory and each reference carries a SHA-256
digest. Absolute paths, parent traversal, missing files, changed files, and
symbolic links that resolve outside the review directory are rejected or block
the gate.

A review directory should contain, at minimum:

```text
behavior-review/
  promotion-record.json
  origin-trajectory.json
  gold-dataset.json
  gold-trajectory.json
  gold-evaluation-report.json
  gold-expert-review.json
  fresh-dataset.json
  fresh-trajectory.json
  fresh-evaluation-report.json
  fresh-expert-review.json
```

The record requires non-empty ToolCall, Source, Evidence, and judgment
references for the origin trajectory. Each evaluation identifies the exact
implementation revision, model, runtime contract fingerprint, sealed dataset,
paper content fingerprints, trajectory, evaluator report, human review, and raw
metric counts. The runtime contract fingerprints the prompt, capability,
handler, and relevant model settings so Gold and fresh papers replay the same
behavior. Existing Expert Gold utilities under `../expert_gold/` remain the
canonical source for Gold prediction and scientific evaluation reports.

The gate derives these values from raw counts rather than accepting a supplied
rate or verdict:

```text
recall = recalled relevant items / expected relevant items
scientific error rate = expert-confirmed scientific errors / evaluated decisions
technical failure rate = technically failed papers / evaluated papers
tokens per paper = (input tokens + output tokens) / evaluated papers
model calls per paper = model calls / evaluated papers
```

Every provider call must report token usage. Any unreported call blocks the cost
gate. Scientific errors are expert-confirmed wrong research judgments; provider,
parsing, timeout, and execution failures belong only in technical failures.

## Run The Gate

```bash
cd backend
./.venv/bin/python \
  scripts/evaluation/agent_behavior_promotion/validate_promotion_record.py \
  path/to/behavior-review/promotion-record.json \
  --output path/to/behavior-review/promotion-evaluation.json
```

Exit status `0` means `eligible_for_maintainer_review`. Exit status `1` means
one or more evidence or boundary checks blocked review. Exit status `2` means
the record itself is invalid and cannot be scored.

The output always contains `promotion_applied: false`. Maintainers must still
review the generalized behavior, production implementation, regression tests,
and rollback boundary. Passing evidence cannot write a paper-specific alias or
other local fact into production code.

## Boundaries

- This is an evaluation artifact and deterministic validator, not a production
  domain object or database model.
- It does not add an API, migration, Agent capability, compatibility layer, or
  automatic Fast Path mutation.
- It does not replace expert review or the existing Gold evaluator.
- It checks that declared artifacts and raw counts are complete, locked, and
  within pre-registered bounds. The evaluator report and human review remain
  responsible for establishing which items are relevant and which judgments
  are scientifically wrong.
- A blocked candidate remains a Deep Path trajectory that researchers may
  inspect; it does not become a scientific absence or failed Finding.
