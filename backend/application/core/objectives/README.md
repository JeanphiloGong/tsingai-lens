# Research Objectives

## Purpose

This package owns two different research activities:

1. form candidate questions from lightweight maps of explicitly selected papers;
2. answer one confirmed question by extracting, grounding, binding, and
   comparing Evidence from explicitly selected papers.

The two activities share paper inputs but not scientific authority. A Paper Map
can suggest what to inspect; only Objective analysis can publish Evidence and
Findings.

## Start Here

Use the following entry points when modifying the Core workflow:

| Task | Entry point | Result |
|---|---|---|
| Resolve selected ready papers | `ObjectiveInputService.resolve_prepared_document_inputs()` | frozen input set; no parsing |
| Discover candidates | `ObjectiveDiscoveryService.start_objective_discovery()` | queued discovery run |
| Form candidates | `ObjectiveCandidateService.discover_candidate_facts()` | candidate Objectives |
| Create/confirm a candidate | `ObjectiveAuthoringService.create_chat_assisted_candidate()` / `confirm_objective()` | persisted Objective |
| Queue analysis | `ObjectiveAnalysisService.start_analysis()` | queued versioned analysis |
| Generate analysis artifacts | `ObjectiveEvidenceAnalysisService.generate_objective_analysis_artifacts()` | per-paper Evidence and Finding inputs |
| Publish/read analysis | `ObjectiveAnalysisService.execute_queued_analysis()` / read methods | immutable published snapshot |

Paper Map construction is intentionally split by responsibility:

- `paper_research_map_service.py` coordinates the document-level sequence;
- `paper_map_sources.py` owns Source selection and window payloads;
- `paper_map_extraction.py` owns model extraction, structured-output recovery,
  and window-result normalization;
- `paper_map_aggregation.py` owns window consolidation, study identity merging,
  unresolved-signal reconciliation, and final status assessment.

The coordinator must remain the only place that orders these steps. Moving a
helper does not authorize changing Source order, recovery budgets, or map
status semantics.

`ObjectiveInputService.load_or_build_paper_maps()` may call the model and store
a refreshed map. Its other input reads do not create Objectives or Evidence.
Discovery stores candidate Objectives; authoring stores only the explicitly
requested creation or confirmation. Scientific analysis returns records and
stores reusable per-paper checkpoints; `ObjectiveAnalysisService` controls the
complete version's publication. Both HTTP and Agent callers use these owners.

The analysis runtime receives `ObjectiveInputService` and
`DocumentProfileService` directly at construction. It does not reach through
the scientific engine to discover those dependencies.

## Changing This Package

| Change | First owner | Focused test under `tests/unit/application/` |
|---|---|---|
| Which prepared papers may enter research | `objective_input_service.py` | `test_objective_discovery_service_ownership.py` |
| Discovery admission or restart recovery | `objective_discovery_service.py` | `test_objective_discovery_service_ownership.py` |
| Candidate question formation | `objective_candidate_service.py` | `test_objective_candidate_service.py` |
| Approved creation, confirmation, or derivation | `objective_authoring_service.py` | `test_objective_derivation_persistence.py` |
| Initial or expanded Paper Map reading scope | `paper_map_sources.py` | `test_paper_research_map_service.py` |
| Map extraction and technical recovery | `paper_map_extraction.py` | `test_paper_research_map_service.py` |
| Map merging, reconciliation, or status | `paper_map_aggregation.py` | `test_tc4_paper_map_policy.py` |
| One paper's scientific Evidence flow | `objective_analysis_service.py` | `test_objective_analysis_workflow.py` |
| Analysis versions, progress, and publication | `analysis_service.py` | `test_objective_analysis_service.py` |

For a scientific stage, continue to [`analysis/README.md`](analysis/README.md).
For cross-module verification, use the commands in
[`../../../tests/objective-analysis-verification.md`](../../../tests/objective-analysis-verification.md).
Do not change the persisted record or HTTP schema merely to move a helper.

The scientific order is always the source of truth:

```text
Paper Map -> candidate Objective -> confirmed Objective
  -> framing -> routing -> Source extraction -> grounding
  -> paper experiment binding -> cross-paper Finding
```

Paper Maps and routes are navigation inputs. Only grounded Source facts may
become Evidence, and only compatible Evidence may become a Finding.

## Document-Level Paper Map

`PaperResearchMapService.build_document_paper_map()` receives one prepared
`SourceDocument`, its `DocumentProfile`, and its document tree. It:

1. selects bounded overview, abstract, conclusion, table, and figure Sources;
2. asks `PaperResearchMapExtractor` for paper role, material and process themes,
   variable-to-outcome research axes, review synthesis, gaps, and citation leads;
3. consolidates the window outputs into one `PaperResearchMap`/Paper Map;
4. expands only when unresolved signals need more reading, prioritizing concrete
   metric terms and explicit condition or group values; selection stops when the
   smallest candidate set covers the unresolved map fields or when no remaining
   Source can add coverage;
5. reconciles unresolved signals without inventing Source facts;
6. records map status and limitations.

This is lightweight preparation for scope decisions. It does not reconstruct
experiments or create `ObjectiveEvidence`. Its contract cannot represent sample
context, test context, comparators, fixed conditions, parameter levels, or
measurements.

A mapped relationship may use a factor only when the supplied Source states
that the paper varied it, compared groups defined by it, or modeled it as an
independent axis. Fixed settings, generic parameter lists, background context,
and uncertain roles remain unresolved map signals with Source lineage; neither
the reconciliation model nor Objective discovery may promote them to
`varied_factors`.

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

`ObjectiveInputService` owns this input boundary for both Discovery and
Analysis. It also loads the matching Source documents, Profiles, document trees,
and reusable Paper Maps; it does not form scientific claims or persist
Objectives/Evidence.

`load_source_inputs()` returns `ObjectiveSourceInputs`, a typed dictionary of
the selected domain objects and their document indexes. Analysis adds only
`paper_maps` through `ObjectiveAnalysisInputs`. Model clients remain service
dependencies: reading prepared paper data neither initializes a client nor
passes one through the scientific input bundle.

A stored Paper Map is reusable only when its input fingerprint and policy
version match and its Source coverage contains no technical extraction failure.
Another requested workflow rebuilds a technically failed map once through the
normal bounded extraction path. Scientific insufficiency alone does not trigger
a rebuild; a completed inspection may legitimately leave scope unresolved.

Candidate formation identifies shared scientific themes while preserving each
paper's stated variables, outcomes, material scope, process theme, and Source
lineage. It must not infer experiment conditions or force unlike materials,
states, methods, or broad outcome families into a directly comparable question.

The discovered Objective list is a bounded human review set, not the complete
Paper Map. The map remains the discovery ledger: every emitted relationship,
unresolved signal, rejection, and relationship that was not surfaced in the
review set keeps its document and Source lineage. The review set is selected
with a minimum and maximum budget and first gives each selected paper room to
contribute concrete questions, then fills remaining slots by cross-paper
support, structured-result coverage, relationship count, and confidence. A
researcher can still create another Objective manually from any map
relationship; the bounded list only controls the first review surface.

Grouping compares the existing typed scopes and relationships from the
inventory. It serializes the resulting groups only after compatibility and
material-ambiguity decisions, without reparsing domain objects for every pair.

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

`processed_document_count` counts selected papers with completed Evidence
inspections, including reusable successful checkpoints and persisted failures.
Framing, routing, and individual Source reads do not increment it. A failed
inspection is finished work, not successful scientific evidence; its failure
remains visible in the contribution. Counts are unique and progress writes are
serialized across concurrent papers. Finding synthesis can still be running
after all selected paper inspections have finished.

`analysis_errors.py` owns user-facing wording for existing failure codes.
Analysis writes use those messages, and failed-analysis reads also apply them
to historical records without rewriting storage. HTTP and Agent consumers see
the same safe wording. Technical details remain in internal diagnostics, not in
the public error message; a scientific abstention remains a successful analysis.

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

When a result is missing material, sample, process, comparison, or test
context, the service performs an adaptive same-paper context expansion. It
prioritizes Sources with explicit condition values, group identities, and
Objective terms, then selects the smallest set that can cover the missing field
families. It does not extract every paper block merely because a heading is a
Methods or Results heading. If no remaining Source can close the gap, or a
technical execution budget ends the inspection, the omission is recorded in
the analysis diagnostic trace and the selected route explains that the scope
can be expanded later. An omitted Source is therefore an uninspected
uncertainty, never evidence that the paper lacks the fact.

### Within-paper binding

Methods, Results, tables, and captions may describe different parts of one real
experiment. Binding joins them only when sample, process, varied conditions,
controls, measurement method, and outcome are supportable. Explicitly reported
jointly changed variables may remain a joint effect; a deterministic
multi-factor row contrast is retained as an association only. Missing context
stays missing unless another
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

## Information-Parity Acceptance

The quality bar is not valid JSON or a fluent summary. Given the same papers,
the same confirmed question, and the same preparation snapshot, a researcher
must be able to recover the same decision-relevant material from the published
analysis: relevant papers, concrete variables and outcomes, sample/process/test
conditions, numerical values and units, comparison limits, and source
locators. Each item must be traceable to its Source. Missing or conflicting
material remains explicit as an uncertainty, non-comparable result, or
abstention; it cannot be silently filled from the Paper Map or another paper.

Acceptance therefore checks the chain end to end:

```text
same papers + confirmed Objective
  -> same relevant-paper and Source recall
  -> source-local facts with complete lineage
  -> within-paper experiment binding
  -> comparable / descriptive / abstained Evidence
  -> Finding, or an explicit no-defensible-comparison result
```

Technical failures such as provider timeouts, invalid JSON, token saturation,
and retry exhaustion are recorded separately as `extraction_failed`. They are
not converted into scientific absence and do not count as a valid conclusion.

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
- `objective_input_service.py`: selected prepared-paper inputs, Profiles, Source
  trees, and reusable Paper Maps.
- `objective_discovery_service.py`: discovery run lifecycle and candidate
  formation.
- `objective_authoring_service.py`: user-approved Objective creation,
  confirmation, and derivation.
- `objective_analysis_service.py`: source-grounded analysis orchestration.
- `analysis_service.py`: versioning, dispatch, progress, retry, and publication.
- `analysis/source_screening.py`: paper relevance and Source scope.
- `analysis/evidence_routing.py`: likely Source selection.
- `analysis/source_extraction.py`: Source-local extraction and grounding.
- `analysis/paper_experiment.py`: within-paper experiment binding.
- `analysis/finding_synthesis.py`: cross-paper Finding synthesis.
- `evidence_map.py`: read-only published Evidence graph projection.

## Consumer Boundary

The HTTP workspace and Research Agent call the same services. Agent write
capabilities pause for exact user approval before creating an Objective,
starting analysis, or publishing a researcher-authored Finding version from
eligible published Evidence. Neither consumer may maintain its own Objective,
Evidence, Finding, progress, or publication state.

The shared domain and browser contract is
[`../../../../docs/contracts/research-objective-workspace-contract.md`](../../../../docs/contracts/research-objective-workspace-contract.md).
