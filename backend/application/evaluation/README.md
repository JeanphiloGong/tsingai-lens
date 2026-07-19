# Evaluation Application Layer

This package owns collection-bound quality evaluation over existing Lens
artifacts.

## Scope

- registering gold answers for a collection
- exporting research-understanding curation drafts before gold registration
- freezing Core artifacts into prediction snapshots
- scoring Core and future Goal outputs against gold answers
- producing summary scores and failure records that can guide parser, prompt,
  schema, model, or reasoning improvements

## Boundaries

- This package does not parse source documents or rebuild collections.
- This package does not own HTTP routes or response schemas.
- Source artifacts are diagnostic inputs only; the user-facing evaluation
  target is Core or Goal output.
- Persistence details belong under `infra/persistence/`.

## Current Services

- `gold_service.py`
  Registers a versioned gold set for one collection.
- `prediction_snapshot_service.py`
  Creates Core prediction snapshots from already-persisted facts.
- `core_evaluation_service.py`
  Compares materials Core gold answers with prediction snapshots and records
  metrics plus failures.
- `research_understanding_feedback_service.py`
  Persists finding-level expert feedback and curation records, exports
  curation-derived `research_understanding_findings` gold drafts, and exports
  read-only research-understanding dataset samples plus quality summaries for
  evaluation or fine-tuning preparation. The summary separates
  `training_ready_sample_count` from `training_message_sample_count` so review
  UIs can show whether confirmed findings actually have message rows available
  for export, and from `protocol_ready_sample_count` so Goal Copilot only
  drafts experiments from actionable, traceable reviewed findings. Dataset
  messages include the persisted research objective, paper/cross-paper Finding
  level, and explicit evidence IDs with document and page provenance. JSONL
  training exports omit rows that fail the message diagnostic even when their
  Finding is otherwise marked `training_ready`. Dataset
  export also exposes editable review JSONL templates for human accept/reject/
  correct review. Each dataset sample carries an `acceptance_gate` and
  `review_decision_hint` so API, UI, and review-packet exports share the same
  accept/reject/correct guidance; training message exports remain limited to
  `training_ready` samples. Quality summaries include sorted top diagnostics
  for error categories, issue types, review reasons, and system warnings so
  expert labels can directly guide evaluation, prompt repair, or fine-tuning
  data selection. Feedback and curation records bind to the exact reviewed
  Finding fingerprint; when statement, research axes, evidence binding, or
  review risks change, the historical record remains auditable but no longer
  contributes gold, training-ready, or protocol-ready state.
- `research_understanding_review_import_service.py`
  Validates and imports expert review decision rows into feedback or curation
  records. CLI and future API entry points should call this service so
  accept/reject/correct rules, stale finding checks, evidence-ref validation,
  acceptance-gate enforcement, warning handling, and review-progress summaries
  remain consistent. Dry-run responses include the current readiness counts for
  affected goals, plus pending accept/reject/correct counts, so experts can see
  whether a batch of decisions will move the dataset toward training export or
  protocol drafting before writing labels.
