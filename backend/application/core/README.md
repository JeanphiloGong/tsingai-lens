# Core Application Layer

This package turns normalized Source artifacts into traceable research facts,
cross-paper comparisons, and Objective Findings. It owns research-facing
application logic; HTTP handling and persistence implementations live outside
this package.

## Overall Flow

Core has two Objective phases separated by a researcher decision.

### 1. Discover Candidate Objectives During Collection Build

```text
Source documents + document trees + document profiles
  -> inspect bounded Source windows within each paper
  -> reconstruct studies, variables, outcomes, and relationships
  -> reconcile compatible signals found in different windows
  -> build one PaperSkim for each paper
  -> normalize only equivalent research-axis labels
  -> group compatible relationships across papers
  -> persist candidate ResearchObjectives for researcher review
```

The main entry point is
`ResearchObjectiveService.discover_and_replace_objective_candidates()`.
`PaperSkim` is a paper-level map used to propose questions; it is not Evidence
and does not establish that a paper answers a candidate Objective. The backend,
not the model, owns Source identity, relationship membership, candidate lineage,
and the final Objective question.

### 2. Analyze a Researcher-Confirmed Objective

```text
confirmed ResearchObjective + immutable Source build
  -> screen which Source units require inspection
  -> route each selected Source for the likely inspection task
  -> extract source-local facts
  -> validate every extracted field against that exact Source
  -> reconstruct experiments within each paper
  -> materialize ObjectiveEvidence and PaperContribution records
  -> compare compatible Evidence across papers
  -> atomically publish versioned Findings
```

The orchestration entry point is
`ResearchObjectiveService.generate_objective_analysis_artifacts()`;
`ObjectiveAnalysisService` owns queueing, progress, failure, versioning, and
atomic publication. Screening and routing are inspection decisions, not
scientific Evidence. A model-authored fact becomes durable Evidence only after
Source-local validation and same-paper experiment reconstruction.

`ResearchObjective` is the business aggregate root. Published analysis output
is addressed by `(collection_id, objective_id, analysis_version)`, and a
Finding by `(collection_id, objective_id, analysis_version, finding_id)`.

## Package Responsibilities

- `document_profiles/`
  Classifies each Source document and summarizes what research content is
  available. Profiles guide later work but do not discover Objectives or prove
  Evidence.
- `paper_facts/`
  Extracts reusable document-scoped facts such as methods, samples, test
  conditions, measurements, and observations for comparison and research
  views.
- `objectives/discovery/`
  Owns bounded pre-confirmation model judgments: study-window extraction,
  within-paper signal reconciliation, and exact axis-equivalence decisions.
- `objectives/paper_skim_service.py`
  Batches every eligible Source unit, retains successful partial results,
  reconciles window outputs, and builds one complete `PaperSkim` per document.
- `objectives/objective_candidate_service.py`
  Deterministically promotes compatible cross-paper study relationships into
  candidate `ResearchObjective` records and records rejected relationships.
- `objectives/analysis/`
  Owns the confirmed-Objective scientific sequence from Source screening
  through Source validation, within-paper reconstruction, Evidence
  materialization, and Finding synthesis.
- `objectives/llm/`
  Owns only shared provider invocation, structured JSON handling, prompt-token
  estimation, trace capture, and usage accounting. It does not own scientific
  prompts, judgments, or domain states.
- `objectives/research_objective_service.py`
  Loads one immutable Source build and coordinates the discovery and analysis
  owners in their required order.
- `objectives/analysis_service.py`
  Manages analysis runtime state and publishes a complete version only after
  contributions, Evidence, and Findings are all valid.
- `structured_extraction/`
  Provides domain-neutral message-content and JSON normalization used outside
  the Objective-specific structured response boundary.
- `comparison_service.py`
  Builds deterministic comparable-result and comparison projections.
- `research_view_aggregation_service.py`
  Aggregates paper facts and comparison projections for collection, material,
  and document views. It does not own Objective Findings.
- `workspace_overview_service.py`
  Builds the collection overview from Source and Core readiness.

## Reading Order

For candidate discovery, read:

1. `objectives/discovery/README.md`
2. `objectives/paper_skim_service.py`
3. `objectives/objective_candidate_service.py`
4. `objectives/research_objective_service.py`

For confirmed Objective analysis, read:

1. `objectives/analysis/README.md`
2. `objectives/research_objective_service.py`
3. `objectives/analysis_service.py`
4. `objectives/llm/README.md`

The child README files describe the detailed owner and failure boundary for
each stage. There is no second persisted Objective result graph: routing,
screening, and intermediate synthesis records remain transient analysis state.
