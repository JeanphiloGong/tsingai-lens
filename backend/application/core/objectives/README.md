# Research Objectives

## Purpose

This package owns two different research activities:

1. form candidate questions from lightweight maps of explicitly selected papers;
2. answer one confirmed question by extracting, grounding, binding, and
   comparing Evidence from explicitly selected papers.

The two activities share paper inputs but not scientific authority. A Paper Map
can suggest what to inspect; only Objective analysis can publish Evidence and
Findings.

## Document-Level Paper Map

`PaperResearchMapService.build_document_paper_map()` receives one prepared
`SourceDocument`, its `DocumentProfile`, and its document tree. It:

1. selects bounded overview, abstract, conclusion, table, and figure Sources;
2. asks `PaperResearchMapExtractor` for paper role, material and process themes,
   variable-to-outcome research axes, review synthesis, gaps, and citation leads;
3. consolidates the window outputs into one `PaperResearchMap`/Paper Map;
4. spends a bounded 24-Source expansion budget when unresolved scientific
   signals require more reading, prioritizing concrete metric terms and stopping
   early when a round adds no new scope;
5. reconciles unresolved signals without inventing Source facts;
6. records map status and limitations.

This is lightweight preparation for scope decisions. It does not reconstruct
experiments or create `ObjectiveEvidence`. Its contract cannot represent sample
context, test context, comparators, fixed conditions, parameter levels, or
measurements.

## Candidate Discovery

```text
POST objective-discovery {document_ids}
  -> resolve ready Documents
  -> freeze PreparedDocumentInput values
  -> load Profiles and build or reuse matching Paper Maps
  -> form and rank Objective candidates
  -> replace current discovered candidates
```

`PreparedDocumentInput` contains `document_id` and the current
`preparation_fingerprint`. Empty, duplicate, unknown, non-ready, or stale inputs
are rejected. Discovery never falls back to all Collection papers.

Candidate formation identifies shared scientific themes while preserving each
paper's stated variables, outcomes, material scope, process theme, and Source
lineage. It must not infer experiment conditions or force unlike materials,
states, methods, or broad outcome families into a directly comparable question.

The resulting `seed_document_ids` record the papers whose mapped relationships
caused the question to be formed. They are question provenance, not the complete
set of papers that should enter deep Objective analysis.

## Objective Scope Screening

```text
GET objectives/{objective_id}/scope
  -> load the persisted Objective
  -> screen every current Collection Paper Map exactly once
  -> return likely-relevant, needs-inspection, and confidently-out-of-scope papers
```

`scope_screening.py` performs this read-only decision deterministically. It
does not call an LLM, inspect Sources, persist state, or create Evidence.
Explicit material/variable/outcome matches are `likely_relevant`. Incomplete
maps, partial matches, umbrella-variable uncertainty, and review citation leads
remain `needs_inspection`; they are never silently excluded or selected.
Sufficient maps with a specific material conflict or no mapped scope match are
`confidently_out_of_scope`. An Objective's explicit exclusions remain excluded.

The response includes every mapped paper decision and complete document-ID sets;
it is never truncated for analysis. Chat may render a bounded subset, but the
browser analysis command uses the complete `recommended_document_ids` and lets
the researcher review `review_document_ids` before changing the scope.

## Analysis Command

```text
POST objectives/{objective_id}/analysis {document_ids}
  -> resolve current ready inputs
  -> confirm candidate if needed
  -> freeze inputs on a new ObjectiveAnalysis version
  -> queue process-local execution
```

At most one version is queued or running for an Objective. Retry allocates the
next version. A failed retry never hides an earlier published version.

Before execution, the service resolves each frozen Document again and requires
the same preparation fingerprint. Re-preparing a paper therefore makes the old
input stale instead of silently changing the analysis.

## Scientific Analysis

For each selected paper:

```text
Objective + Profile + Paper Map navigation prior
  -> paper framing
  -> Source routing
  -> Source-local extraction
  -> deterministic grounding
  -> within-paper experiment binding
  -> persist a reusable document Evidence checkpoint
```

Then across papers:

```text
PaperContributions + grounded ObjectiveEvidence
  -> align material state, variables, methods, and outcomes
  -> preserve non-comparability and conflicts
  -> synthesize Findings
  -> publish one immutable analysis version
```

### Framing

Framing decides whether the paper should be inspected for this Objective and
what material, variables, outcomes, and methods matter. Relevance is an
inspection decision, not Evidence. The Paper Map may prioritize Sources and
report preliminary coverage gaps, but it cannot supply any scientific field to
Evidence.

### Routing

Routing selects likely Methods, Results, table, and figure Sources. A route role
is a hint; it cannot be copied into Evidence or fill missing facts.

### Extraction and grounding

Each extraction prompt receives one concrete Source plus the Objective context.
The model transcribes variables, baseline/target values, measured outcome,
scientific context, and result text. Deterministic grounding verifies that
source-local fields are supported by that Source. Invalid or incomplete output
is classified rather than repaired into a scientific claim.

The extraction disposition distinguishes:

- comparable Evidence;
- descriptive or otherwise non-comparable Evidence;
- no grounded outcome Evidence;
- technical extraction failure.

### Within-paper binding

Methods, Results, tables, and captions may describe different parts of one real
experiment. Binding joins them only when sample, process, varied conditions,
controls, measurement method, and outcome are supportable. Jointly changed
variables remain a joint effect. Missing context stays missing unless another
Source inspected for the confirmed Objective supports it; Paper Map values are
never used to fill an experiment draft.

### Cross-paper synthesis

Findings group only compatible atomic `(factor tuple, outcome)` result sets.
Material state, process context, test method, and conditions determine whether
results can be directly compared. Agreement, contradiction, condition
dependence, insufficient confirmation, and limitations are derived from linked
Evidence.

A succeeded analysis may publish zero Findings when inspection completed but no
defensible comparison survived. When all relevant papers fail technically, the
analysis remains failed and retryable.

Each document inspection is independently resumable. Its reuse fingerprint
covers the confirmed Objective's scientific intent, the exact prepared Document,
the extraction version, and model identity. A matching completed inspection is
reused on a later analysis version; failed or unfinished inspection reruns.
Cached contributions and Evidence are rebound to the current analysis version,
then the complete selected set enters Finding synthesis once. Publication remains
one atomic `ObjectiveAnalysis` snapshot and does not expose partial checkpoint
state through the public API.

## Main Owners

- `paper_research_map_service.py`: one Document's lightweight Paper Map.
- `objective_candidate_service.py`: candidate formation from selected maps.
- `scope_screening.py`: collection-wide deterministic scope for one Objective.
- `research_objective_service.py`: selected-input loading and scientific
  orchestration.
- `analysis_service.py`: versioning, dispatch, progress, retry, and publication.
- `analysis/paper_framing.py`: paper relevance and scope.
- `analysis/evidence_routing.py`: likely Source selection.
- `analysis/source_extraction.py`: Source-local extraction and grounding.
- `analysis/paper_experiment.py`: within-paper experiment binding.
- `analysis/finding_synthesis.py`: cross-paper Finding synthesis.
- `evidence_map.py`: read-only published Evidence graph projection.

## Consumer Boundary

The HTTP workspace and Research Agent call the same services. Agent write
capabilities pause for user approval before creating an Objective or starting
analysis. Neither consumer may maintain its own Objective, Evidence, Finding,
progress, or publication state.

The shared domain and browser contract is
[`../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../docs/contracts/research-objective-workspace-contract.md).
