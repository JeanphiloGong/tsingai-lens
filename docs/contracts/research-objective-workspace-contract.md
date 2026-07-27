# Research Objective And Finding Contract

## Status

This is the current shared frontend/backend contract for confirmed research
Objectives and their published scientific Findings. It replaces all former
parallel Objective result and intermediate traversal contracts.

## Product Boundary

A user creates or confirms one research Objective. Lens analyzes selected
collection papers and publishes evidence-calibrated Findings. The Objective
page presents a Finding list; selecting a Finding reveals its relation,
applicability conditions, derivation, exact source Evidence, and review action.

The Objective is a user-visible research identity. Analysis versions are
runtime lineage, not a second user concept.

## Domain Model

```text
ResearchObjective
  -> ObjectiveAnalysis
     -> PaperContribution
     -> ObjectiveEvidence
     -> Finding
        -> FindingRelation
        -> FindingContext
        -> FindingDerivation
```

### ResearchObjective

Identity: `(collection_id, objective_id)`.

Owns:

- research question;
- material, process, property, and comparison scope;
- included and excluded document IDs;
- candidate/confirmed state;
- active and published analysis-version pointers.

It does not own execution progress, errors, complete document content, or
embedded child arrays.

### ObjectiveAnalysis

Identity: `(collection_id, objective_id, analysis_version)`.

Owns one reproducible execution attempt:

- immutable Source build, pipeline, model, and prompt versions;
- `queued | running | succeeded | failed` status;
- phase, current document, processed/total document counts, and user-readable
  progress;
- terminal error code/message and timestamps.

At most one version is queued or running for an Objective. Retry allocates the
next version. Successful publication and the Objective's published pointer are
committed atomically. Failed analysis never hides the previous published
version.

### PaperContribution

Identity: analysis identity plus `document_id`.

Records one included paper's relevance, scientific role, material match,
changed variables, measured outcomes, test scope, exclusion reason, warnings,
and confidence. It does not own Source selections.

### ObjectiveEvidence

Identity: analysis identity plus `evidence_id`.

Each record contains:

- `document_id` and one primary `source_ref`;
- `source_kind`: `text_window | table | figure`;
- exact bounded `source_excerpt`, page numbers, and related typed locators;
- evidence role, kind, selection/extraction state, and confidence;
- material, sample, process, test, baseline, value, interpretation, and join
  fields needed for scientific comparison.

The Evidence lifecycle is:

```text
candidate -> selected -> extracted | rejected | failed
```

Only eligible extracted Evidence may support a Finding. Condition, mechanism,
baseline, comparison, and background context cannot alone establish a direct
result. Direct and contradictory results must contain an explicit outcome in
both the source excerpt and structured content.

### Finding

Identity: analysis identity plus `finding_id`.

Finding is the only conclusion identity. It owns:

- paper or cross-paper level;
- statement, variables, mediators, outcomes, and direction;
- scope summary, evidence strength, generalization status, paper count,
  confidence, and display rank;
- ordered Relations, one Context, and one Derivation.

A paper Finding has direct-result support from exactly one paper and remains
`paper_level_only`. A cross-paper Finding requires comparable direct-result
Evidence from at least two distinct papers. `paper_count` equals the distinct
direct-result papers in Derivation.

### FindingRelation

Identity: Finding identity plus `relation_order`.

Represents `source_term -> relation_type -> target_term`, direction, assertion
strength, and supporting Evidence IDs. A causal assertion is valid only when
direct experimental Evidence identifies the asserted variable as isolated;
otherwise the relation must be associative, descriptive, or uncertain.

### FindingContext

One-to-one with Finding. Stores structured material system, process conditions,
sample state, test conditions, comparison baseline, limitations, and supporting
Evidence IDs. Conflicting conditions remain explicit limitations and are never
silently merged.

### FindingDerivation

One-to-one with Finding. Stores synthesis mode, comparison status, contributing
papers, supporting and contradicting Evidence IDs, and a bounded rationale.
Cross-paper comparison status is one of `agreement`, `conflict`,
`condition_dependent`, or `insufficient_confirmation`.

## API Contract

All routes are under `/api/v1/collections/{collection_id}`.

### Objective lifecycle

- `GET /objectives`
- `GET /objectives/{objective_id}`
- `POST /objectives/{objective_id}/confirm`
- `POST /objectives/{objective_id}/analysis`
- `GET /objectives/{objective_id}/analysis`

The detail/analysis response contains `objective`, `active_analysis`,
`published_analysis`, and warnings. It never embeds all Findings or Evidence.

### Published result reads

- `GET /objectives/{objective_id}/findings`
- `GET /objectives/{objective_id}/findings/{finding_id}`
- `GET /objectives/{objective_id}/evidence`

Finding and Evidence lists are paginated. `analysis_version` is explicit in
every response and may be supplied as a query parameter. Evidence may be
filtered by `finding_id`.

### Review and export

- `POST /objectives/{objective_id}/findings/{finding_id}/feedback`
- `GET /objectives/{objective_id}/findings/{finding_id}/feedback`
- `PUT /objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /objectives/{objective_id}/findings/{finding_id}/curation`
- `GET /objectives/{objective_id}/finding-dataset`
- `GET /finding-dataset`
- `GET /finding-gold-draft`

Feedback and curation require `analysis_version`. Review import and dataset
rows use the complete versioned Finding identity. Training samples include
exact Evidence excerpts and provenance, not IDs alone.

## Frontend States

- `candidate`: show confirmation action.
- `confirmed` with no active version: show start-analysis action.
- `queued | running`: poll and display phase/document progress.
- `failed` without a published version: show retry as primary action.
- `failed` with a published version: show retry while keeping the prior
  published Findings readable.
- `succeeded`: show the published Finding list and selected detail.

The first Finding is selected deterministically when no selection exists.
Selecting another Finding loads only that Finding's Evidence page. Source links
open the owning document with `source_ref` and page context.

## Invariants

- Every child shares the same collection, Objective, and analysis version.
- Findings reference only eligible Evidence from their own version.
- Published Finding graphs are immutable.
- Internal IDs are retained for requests and audit but are not used as visible
  scientific labels.
- Empty, failed, stale, or scientifically unsupported output is not reported as
  successful expert analysis.
- The frontend and downstream assistant consume published Findings directly;
  they do not rebuild another conclusion graph.
