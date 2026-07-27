# Evaluation Application Layer

This package evaluates and reviews already-persisted Lens outputs. It does not
parse Source documents or run collection builds.

## Services

- `gold_service.py`
  Registers versioned collection gold sets.
- `prediction_snapshot_service.py`
  Freezes Core and published Objective outputs into prediction snapshots.
- `core_evaluation_service.py`
  Scores predictions against gold and records metrics and failures.
- `finding_feedback_service.py`
  Records feedback and curation for one published Finding version and exports
  Objective or collection Finding datasets.
- `finding_review_import_service.py`
  Validates human accept, reject, correct, or skip decisions and writes them
  through `FindingFeedbackService`.

## Identity Contract

Every Objective review record uses:

```text
(collection_id, objective_id, analysis_version, finding_id)
```

The service rejects missing, stale, unpublished, and cross-version Findings.
Curation Evidence IDs must belong to the same Finding and analysis version.
No alternate conclusion ID is accepted.

## Dataset Contract

`objective_finding_dataset.v1` contains one sample per published Finding. Each
sample includes:

- the research question and exact versioned Finding identity;
- system prediction and optional expert target;
- all selected Evidence with `document_id`, typed locator, page numbers, and
  exact `source_excerpt`;
- training messages generated from that same Evidence;
- label and dataset-use status.

`training_jsonl` emits only `{messages, metadata}` rows with non-empty training
messages. IDs alone are never used as model input. Gold and training readiness
come from current human review or curation of the exact Finding version.

Persistence details belong to `infra/persistence/`; HTTP request and response
schemas belong to `controllers/schemas/`.
