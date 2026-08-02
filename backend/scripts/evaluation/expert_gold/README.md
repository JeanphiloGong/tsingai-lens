# Expert Gold Evaluation Scripts

These CLIs validate expert gold, export canonical Lens predictions, evaluate
published Objective Findings, and import human review decisions. They call the
maintained application and persistence contracts; they do not rebuild deleted
Objective result models.

Run commands from `backend/` with the project virtual environment.

## Gold Bundle Flow

Validate an expert CSV:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/validate_expert_gold.py \
  path/to/expert.csv
```

Convert it to the versioned gold bundle:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/convert_expert_gold.py \
  path/to/expert.csv \
  --output-path path/to/gold.json
```

Export current system output:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/export_prediction_bundle.py \
  --collection-id col_xxx \
  --output-path path/to/prediction.json
```

The Objective portion of the prediction bundle reads the published
`ObjectiveAnalysis`, Findings, and Finding-specific Evidence directly. It
includes exact Source excerpts and locators.

Evaluate prediction against gold:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/evaluate_gold_vs_prediction.py \
  path/to/gold.json \
  path/to/prediction.json \
  --output-path path/to/report.json
```

`validate_expert_gold.py`, `convert_expert_gold.py`,
`evaluate_gold_vs_prediction.py`, and `objective_probe_checks.py` remain the
generic Core evaluation utilities.

## Objective Finding Benchmark

Run the canonical Objective benchmark:

```bash
./.venv/bin/python scripts/evaluation/expert_gold/run_objective_gold_benchmark.py \
  --collection-id col_xxx \
  --output-dir path/to/output
```

The benchmark exports and evaluates published Findings. It does not construct
an intermediate target model.

For the maintained six-paper 316L source audit:

```bash
./.venv/bin/python \
  scripts/evaluation/expert_gold/check_objective_findings_projection.py
```

To check a running authenticated API instead of direct local repositories:

```bash
LENS_CHECK_EMAIL=lens-admin@example.com \
LENS_CHECK_PASSWORD=admin.. \
./.venv/bin/python \
  scripts/evaluation/expert_gold/check_objective_findings_projection.py \
  --api-base-url http://localhost:5173
```

The checker requires every selected Objective to be confirmed and to have a
succeeded published analysis with non-empty Findings. It validates:

- complete `(collection_id, objective_id, analysis_version, finding_id)`
  identity;
- non-empty factors, exactly one outcome, and synthesis status;
- direct paper bindings computed from PaperContributions;
- at least one supporting direct-result Evidence record;
- exact Evidence membership for each Finding;
- Source locator, excerpt, and page resolution;
- expected objective-specific materials-science concepts.

An empty Finding set, unresolved source location, or scientifically weak result
is a failed gate.

## Finding Review

The canonical review identity is:

```text
collection_id + objective_id + analysis_version + finding_id
```

Review decisions use `accept`, `reject`, `correct`, or `skip`. A correction
must provide one complete canonical `curated_finding` whose identity,
PaperContributions, and Evidence all belong to the same published version.

Import a JSONL decision file:

```bash
./.venv/bin/python \
  scripts/evaluation/expert_gold/import_finding_review_decisions.py \
  path/to/decisions.jsonl \
  --reviewer expert@example.com \
  --dry-run
```

Remove `--dry-run` only after validation succeeds. The importer rejects
non-human reviewer IDs, stale analysis versions, unknown Findings, and
cross-Finding Evidence.

Minimal accept row:

```json
{"collection_id":"col_xxx","objective_id":"obj_xxx","analysis_version":2,"finding_id":"finding_xxx","action":"accept","note":"Checked against the cited result table."}
```

Minimal correction row:

```json
{
  "collection_id": "col_xxx",
  "objective_id": "obj_xxx",
  "analysis_version": 2,
  "finding_id": "finding_xxx",
  "action": "correct",
  "curated_status": "limited",
  "curated_finding": {
    "collection_id": "col_xxx",
    "objective_id": "obj_xxx",
    "analysis_version": 2,
    "finding_id": "finding_xxx",
    "statement": "Under the reported LPBF conditions, preheating was associated with higher elongation.",
    "factors": ["preheating"],
    "outcome": "elongation",
    "direction": "increase",
    "assertion_strength": "associative",
    "attribution_scope": "isolated_effect",
    "synthesis_status": "insufficient_confirmation",
    "certainty": 0.5,
    "display_rank": 0,
    "mechanisms": [],
    "scientific_context": {"material": [], "sample": [], "process": [], "test": []},
    "limitations": ["One directly contributing paper."],
    "paper_contributions": [{"document_id": "paper_xxx", "analysis_status": "analyzed", "supporting_evidence_ids": ["evidence_xxx"], "contradicting_evidence_ids": [], "context_evidence_ids": [], "condition_boundary_evidence_ids": []}]
  }
}
```

For `merge_expert_decision_board.py`, the TSV carries the same complete object
as JSON text in `curated_finding_json`; scalar correction columns are not
supported.

## Independent Agent Drafts

The following tools prepare and validate advisory agent reviews while keeping
the final label human-owned:

- `prepare_agent_review_draft.py`
- `check_agent_review_draft.py`
- `merge_agent_review_results.py`
- `merge_expert_decision_board.py`

Agent drafts remain `action=skip` and `human_confirmed=false`. They are keyed by
`finding_id`; the surrounding decision template must also retain collection,
Objective, and analysis-version identity. A human converts an advisory row into
an explicit import action.

## Dataset Export

The maintained HTTP dataset routes are:

```text
GET /api/v1/collections/{collection_id}/objectives/{objective_id}/finding-dataset
GET /api/v1/collections/{collection_id}/finding-dataset
```

Use `format=training_jsonl` for fine-tuning rows. Each line contains:

```json
{
  "messages": [
    {"role": "user", "content": "Research objective plus exact Evidence excerpts and provenance"},
    {"role": "assistant", "content": "Structured Finding target"}
  ],
  "metadata": {
    "schema_version": "objective_finding_training.v2",
    "collection_id": "col_xxx",
    "objective_id": "obj_xxx",
    "analysis_version": 2,
    "finding_id": "finding_xxx",
    "evidence_ids": ["evidence_xxx"]
  }
}
```

Only `training_ready` samples produce JSONL rows. The model input contains
exact source text and scientific context. `evidence_ids` preserve audit
identity; they are never the only Evidence content supplied to training.
