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
- seed document IDs identifying where the question came from;
- explicit document exclusions;
- candidate/confirmed state;
- active and published analysis-version pointers.

It does not own execution progress, errors, complete document content, or
embedded child arrays.

Candidate discovery and analysis never infer all Collection papers. Their
commands receive an explicit non-empty ready `document_ids` selection.
After a candidate exists, deterministic Objective scope screening evaluates
every current Collection Paper Map. Seed papers do not define the recommended
analysis scope.

### PreparedDocumentInput

Identity: `document_id + preparation_fingerprint` within one discovery or
analysis record.

The fingerprint binds current document bytes, parser version, and
document-analysis version. Discovery records the inputs used to form current
candidates. Every ObjectiveAnalysis freezes its own selected inputs and checks
that they still match ready Documents before Source is read. A mismatch is
stale input and blocks analysis; it is never repaired by silently switching to
new Source.

### ObjectiveAnalysis

Identity: `(collection_id, objective_id, analysis_version)`.

Owns one reproducible execution attempt:

- immutable selected PreparedDocumentInputs plus pipeline, model, and prompt
  versions;
- `queued | running | succeeded | failed` status;
- phase, current document, processed/total document counts, and user-readable
  progress;
- terminal error code/message and timestamps.

System analysis has `origin=system_generated`. A deliberate researcher Finding
or evidence-abstention decision publishes a new `human_authored | hybrid`
analysis version with `source_analysis_version` and authenticated
`created_by_user_id`. A user-approved analysis written by the Research Agent
uses `origin=agent_authored`, authenticated `created_by_user_id`, and
`created_by_tool_call_id`; an initial Agent analysis has no source analysis
version. An authored abstention additionally records one bounded
`abstention_reason` and explanation. It remains a successful scientific
decision, not a failed model run.

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

It also records authorship lineage. `origin=human_authored` identifies a new
researcher conclusion over existing Evidence. `origin=hybrid` additionally
requires a `parent_finding_id` from the immutable source version.
`origin=agent_authored` identifies a conclusion proposed by the Agent and
published only after exact user approval.
`source_analysis_version`, authenticated `created_by_user_id`, and
`created_at` preserve who made the decision and which published Evidence they
reviewed; Agent-authored records also preserve `created_by_tool_call_id`.
System, human, Agent, and hybrid Findings therefore share one canonical
scientific model and one versioned identity.

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

- `POST /objective-discovery`
- `GET /objectives`
- `GET /objectives/{objective_id}/scope`
- `POST /objectives/{objective_id}/analysis`
- `GET /objectives/{objective_id}/analysis`

Discovery and analysis POST bodies are:

```json
{"document_ids": ["doc_a", "doc_b"]}
```

Every selected Document must be current and ready. Processing and failed papers
do not block research over another explicitly selected ready subset.

`GET .../scope` returns a complete, read-only classification of current
Collection Paper Maps for one Objective:

- `likely_relevant`: mapped material, variables, and outcome establish that the
  paper should enter deep inspection;
- `needs_inspection`: the map is incomplete or only partially/broadly/citation
  related, so a researcher must decide;
- `confidently_out_of_scope`: the sufficient map conflicts or has no matching
  research scope, including an explicit Objective exclusion.

Its `recommended_document_ids` contain only `likely_relevant` papers.
`review_document_ids` are visible but unselected by default. Every decision
retains its Paper Map reason and whether it was a seed paper.
`support_is_evidence=false` is invariant: screening decides what deserves
inspection and cannot establish a scientific result.

The analysis-state and command responses contain `objective`,
`active_analysis`, `published_analysis`, and warnings. They never embed all
Findings or Evidence.

`POST .../analysis` is the single approval-and-analysis command. For a
candidate Objective, it atomically freezes the accepted definition as
`confirmed`, freezes the selected PreparedDocumentInputs, and queues analysis
version 1. For an already confirmed Objective, it creates or reuses the
appropriate active version. There is no separate confirmation command.
The browser uses complete scope-screening recommendations by default, lets the
researcher edit that Objective-local set, and never treats seed papers as a
fallback recommendation. Retry reuses the failed version's frozen IDs.

### Agent-authored analysis

Direct Agent analysis is a parallel Chat capability, not a replacement for the
Objective analysis endpoint. When the researcher asks the Agent itself to
analyze an Objective, the Agent first reads canonical Sources for the approved
paper scope over one or more conversation turns. It may propose publication
only after every included ready Document has one paper summary and at least one
exact Source-grounded Evidence draft.

The exact-argument approval confirms a candidate Objective in the same queue
transition used by automatic analysis. Before that transition, the backend
validates ownership, document readiness and preparation fingerprints, complete
paper-summary coverage, Source locators, complete-content SHA-256 digests,
normalized excerpt containment, and the structured Evidence contract. Invalid
input creates no analysis version. A failure after queueing marks that version
failed.

Successful publication creates one `agent_authored` ObjectiveAnalysis with
PaperContributions and Evidence and no Finding. Evidence identity, page,
provenance, and contribution accounting are backend-derived. The Agent's model
name, prompt version, authenticated user, and approved tool-call identity are
durable lineage. A conclusion is a separate Evidence-to-Finding decision and
requires a later exact approval through the existing Finding authoring path.
The automatic Source extraction and Finding synthesis path remains unchanged.

### Published result reads

- `POST /objectives/{objective_id}/findings`
- `POST /objectives/{objective_id}/evidence`
- `GET /objectives/{objective_id}/findings`
- `GET /objectives/{objective_id}/findings/{finding_id}`
- `GET /objectives/{objective_id}/evidence`

Finding and Evidence lists are paginated. `analysis_version` is explicit in
every response and may be supplied as a query parameter. Evidence may be
filtered by `finding_id`.

The Findings POST command is the researcher-approved Evidence-to-Finding decision
boundary. The browser or Research Agent submits the current published
`source_analysis_version`, one statement and assertion strength, selected
support/contradiction/context Evidence IDs, optional boundary IDs and
limitations, and an optional parent Finding. An Agent request remains paused
until the authenticated researcher approves those exact arguments. The backend
accepts only eligible Evidence from that exact version and derives the
Finding's factors, outcome, direction, attribution, certainty, synthesis, paper
coverage, target version, creator, and Source bindings.

Publication clones the complete source-version PaperContribution, Evidence,
and Finding snapshot into the next immutable version before appending the new
Finding. The source analysis and parent Finding do not change. A stale version
or concurrent analysis is a conflict, never a silent rebase. A researcher may
instead record `no_comparable_evidence`, `no_grounded_evidence`, or
`insufficient_evidence` with an explanation; that publishes analysis metadata
without manufacturing a Finding.

The Evidence POST command is the Source-to-Evidence decision boundary. It
accepts one current published analysis version, one prepared Document and
Source locator, a verbatim Source excerpt, an Evidence role, and the structured
variables, comparison, reported result, attribution, and scientific context
that the researcher confirms. The backend verifies collection ownership,
analysis scope, exact Source identity, and normalized excerpt containment. It
derives the Evidence identity, page, confidence, and authenticated creator;
the request cannot move a Source from another collection or analysis version.

Creating a correction with `supersedes_evidence_id` publishes a new immutable
analysis snapshot. The prior Evidence and any Finding that cites it remain
unchanged, while the new record records `origin=human_revised` and explicit
supersession lineage. A new Source-grounded record uses
`origin=human_authored` when the researcher authors it directly, or
`origin=agent_authored` when the Agent proposes it and the researcher approves
the exact write. An Agent-assisted correction remains `human_revised` and is
distinguished by `created_by_tool_call_id`. An Agent uses the same command only
after exact-argument approval and supplies the `source_digest` obtained from
`inspect_document_sources`. Invalid excerpts, stale or out-of-scope Sources,
concurrent analysis, and attempts to revise a superseded record are conflicts;
they never create a partial record.

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

- `candidate`: show confirm-and-analyze action.
- `confirmed` with no active version: show start-analysis action.
- `queued | running`: poll and display phase/document progress.
- `failed` without a published version: show retry as primary action.
- `failed` with a published version: show retry while keeping the prior
  published Findings readable.
- `succeeded`: show the published Finding list and selected detail.
- `succeeded` with authoring open: load all eligible Evidence from that exact
  published version, preserve Source links while roles are assigned, then
  reload and select the new versioned Finding after publication.
- `succeeded` with authored abstention: display the researcher's evidence
  decision even when the published Finding set is empty.

The Collection page allows upload and independent prepare/retry while other
papers run. Objective discovery and analysis controls expose ready-paper
selection; disabled processing or failed papers do not create a global lock.
The Objective list labels seed papers as question sources. Starting a new
analysis fetches the complete recommended scope; adjusting scope distinguishes
system recommendations, papers requiring human inspection, and current
exclusions without exposing internal matching terms.

The first Finding is selected deterministically when no selection exists.
Selecting another Finding loads that Finding detail and Evidence page together;
stale rapid-selection responses are discarded. Source links open the owning
document with Evidence identity, `source_ref`, exact quote, and page context.

## Invariants

- Every child shares the same collection, Objective, and analysis version.
- Every analysis has at least one unique PreparedDocumentInput, and each paper
  contribution belongs to that frozen selection.
- Source, DocumentProfile, and PaperMap are current Document-owned records, not
  collection-build snapshots.
- Findings reference only role-eligible Evidence from their own version and
  bind every PaperContribution in that version.
- Every eligible direct result in an atomic result set is assigned exactly once
  as supporting or contradicting.
- Published Finding graphs are immutable.
- Researcher-approved authorship, whether entered in the workbench or proposed
  by the Agent, always creates a new published analysis version; it never edits
  a published Finding or Evidence record in place.
- The browser cannot declare creator identity, target version, paper coverage,
  factors, outcome, direction, certainty, attribution, synthesis, or Source
  text. These are deterministic backend responsibilities.
- Internal IDs are retained for requests and audit but are not used as visible
  scientific labels.
- A completed inspection with no grounded Evidence publishes an empty Finding
  set as a scientific abstention, not as an expert conclusion. A run whose
  relevant papers all fail technical extraction remains failed and retryable;
  stale or technically failed output is never reported as successful analysis.
- The frontend and downstream assistant consume published Findings directly;
  they do not rebuild another conclusion graph.

The Finding workbench currently starts from existing published Evidence.
Source-grounded Evidence can be recorded through the HTTP command or the
approved Agent capability; direct selection of arbitrary raw document text,
tables, or figures inside the document reader remains owned by #191.
Objective-local paper-scope review remains owned by #340.
