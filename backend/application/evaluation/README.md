# Evaluation Application Layer

This package evaluates and reviews already-persisted Lens outputs. It does not
prepare Source documents, discover Objectives, or run Objective analyses.

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
Curation stores one complete canonical `curated_finding`. Its identity and all
Evidence/PaperContribution bindings must belong to the same published Finding
version. No partial correction or alternate conclusion ID is accepted.

## Dataset Contract

`objective_finding_dataset.v2` contains one sample per published Finding. Each
sample includes:

- the research question and exact versioned Finding identity;
- canonical `system_prediction`, optional `expert_target`, and resolved
  `training_target`;
- all selected Evidence with `document_id`, typed locator, page numbers, and
  exact `source_excerpt`;
- deterministic Finding and Evidence fingerprints;
- training messages generated from that same Evidence;
- label and dataset-use status.

`training_jsonl` emits only `{messages, metadata}` rows with non-empty training
messages. IDs alone are never used as model input. The newest feedback or
curation event controls label and training readiness for the exact Finding
version; an older acceptance cannot override a newer rejection or correction.

Persistence details belong to `infra/persistence/`; HTTP request and response
schemas belong to `controllers/schemas/`.
