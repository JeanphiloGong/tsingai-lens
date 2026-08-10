# Research Objective And Finding Contract

## Status

This is the current shared frontend/backend contract for confirmed research
Objectives and their published scientific Findings. It replaces all former
parallel Objective result and intermediate traversal contracts.

## Product Boundary

A user creates or confirms one research Objective. Lens analyzes selected
collection papers and publishes evidence-calibrated Findings. The Objective
page presents a Finding list; selecting a Finding reveals its atomic result,
mechanism explanation, scientific context, paper contributions, exact source
Evidence, and review action.

The Objective is a user-visible research identity. Analysis versions are
runtime lineage, not a second user concept.

## Domain Model

```text
ResearchObjective
  -> ObjectiveAnalysis
     -> PaperContribution
     -> ObjectiveEvidence
     -> Finding
        -> FindingMechanismRelation
        -> ObjectiveEvidenceContext
        -> FindingPaperContribution
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
- evidence role, selection/extraction state, confidence, and
  `attribution_scope`;
- `changed_variables`, each with a name and reported baseline/target value;
- one `comparison` with baseline/target labels, every changed axis,
  comparability, and explicit incomparability reasons;
- at most one `reported_result`, containing one outcome, reported value/unit,
  direction, and bounded result text;
- `scientific_context`, containing typed material, sample, process, and test
  name/value/unit attributes that stayed fixed in the comparison.

The Evidence lifecycle is:

```text
candidate -> selected -> extracted | rejected | failed
```

Only eligible extracted Evidence may support a Finding. Condition, mechanism,
baseline, comparison, and background context cannot alone establish a direct
result. Direct and contradictory results must contain an explicit outcome in
both the source excerpt and structured content.

`attribution_scope` is `isolated_effect | joint_effect | association_only |
descriptive_only | not_attributable`. An isolated effect requires exactly one
changed variable and a comparable baseline/target comparison over the same
axis. A joint effect requires at least two changed variables and retains every
changed axis. Incomparable groups require reasons and are always
`not_attributable`.

Extraction state carries only prior role/outcome coverage and Source positions
between blocks of the same document; scientific values and context are not
copied into later extraction prompts. It is reset at every document boundary
and cannot cross an Objective or analysis version. The service binds provider
output back to the selected Source locator and never fills missing variables or
outcomes from the Objective or PaperContribution. Deterministic table Evidence
also retains row, column, and header coordinates for the reported cell; a
pairwise result cites both source rows.

### Finding

Identity: analysis identity plus `finding_id`.

Finding is the only conclusion identity. It owns:

- one complete changed-factor tuple and exactly one outcome;
- statement, direction, assertion strength, and attribution scope;
- evidence-derived synthesis status and certainty;
- display rank, subordinate mechanisms, common scientific context, and
  deterministic analysis limitations;
- one FindingPaperContribution binding for every PaperContribution in the
  Objective analysis.

Result sets use exact normalized `(factor tuple, outcome)` identity. Jointly
changed factors remain one tuple. A causal statement requires exactly one
factor and supporting isolated-effect Evidence.

The backend derives synthesis status from validated direct Evidence:

- `agreement`: at least two papers support the result without contradiction or
  an explicit condition boundary;
- `conflict`: direct Evidence from at least two papers includes a contradiction;
- `condition_dependent`: cited Evidence establishes an explicit condition
  boundary;
- `insufficient_confirmation`: fewer than two papers provide direct Evidence.

Certainty is the minimum confidence of linked direct Evidence and is capped at
`0.5` for insufficient confirmation. Paper count and paper/cross-paper scope
are computed from bindings rather than persisted as independent declarations.
System-produced limitations are derived from validated factor coupling,
direct-Evidence coverage, contradiction, condition boundaries, and attribution
scope. Provider-authored free text is not published as an analysis limitation.

### FindingMechanismRelation

Identity: Finding identity plus `relation_order`.

Represents a subordinate `source_term -> relation_type -> target_term`
mechanism, optional direction, assertion strength, and mechanism-context
Evidence IDs. It cannot replace or redefine the Finding's factors, outcome, or
main direction.

### Scientific Context

Finding reuses `ObjectiveEvidenceContext`. It contains the exact intersection
of material, sample, process, and test attributes present in every supporting
direct Evidence record. Differences remain in source Evidence and explicit
limitations; they are never silently merged.

### FindingPaperContribution

Every PaperContribution in the Objective analysis appears exactly once,
including excluded, failed, and analyzed papers without a direct result. Each
binding preserves that paper's supporting, contradicting, context, and
condition-boundary Evidence IDs. Excluded or failed papers cannot bind Finding
Evidence.

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
exact Evidence excerpts and provenance, not IDs alone. Curation accepts one
complete canonical `curated_finding`; it cannot store a partial field patch or
cite Evidence outside the published Finding version.

`objective_finding_dataset.v2` exposes the canonical `system_prediction`, an
optional validated `expert_target`, the resolved `training_target`, exact
Evidence, and deterministic Finding/Evidence fingerprints. The latest feedback
or curation event controls review and training status.

## Frontend States

- `candidate`: show confirmation action.
- `confirmed` with no active version: show start-analysis action.
- `queued | running`: poll and display phase/document progress.
- `failed` without a published version: show retry as primary action.
- `failed` with a published version: show retry while keeping the prior
  published Findings readable.
- `succeeded`: show the published Finding list and selected detail.

The first Finding is selected deterministically when no selection exists.
Selecting another Finding loads that Finding detail and Evidence page together;
stale rapid-selection responses are discarded. Source links open the owning
document with Evidence identity, `source_ref`, exact quote, and page context.

## Invariants

- Every child shares the same collection, Objective, and analysis version.
- Findings reference only role-eligible Evidence from their own version and
  bind every PaperContribution in that version.
- Every eligible direct result in an atomic result set is assigned exactly once
  as supporting or contradicting.
- Published Finding graphs are immutable.
- Internal IDs are retained for requests and audit but are not used as visible
  scientific labels.
- Empty, failed, stale, or scientifically unsupported output is not reported as
  successful expert analysis.
- The frontend and downstream assistant consume published Findings directly;
  they do not rebuild another conclusion graph.
