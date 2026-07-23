# Core Application Layer

This package owns the evidence-first semantic model built from normalized
Source artifacts.

## Primary Flow

```text
ResearchObjective
  -> ObjectiveAnalysis (versioned execution)
  -> PaperContribution + ObjectiveEvidence
  -> Finding
     -> FindingRelation + FindingContext + FindingDerivation
```

`ResearchObjective` is the only business aggregate root. Analysis output is
addressed by `(collection_id, objective_id, analysis_version)`, and every
reviewable result uses the complete Finding identity
`(collection_id, objective_id, analysis_version, finding_id)`.

## Owners

- `objective_analysis_service.py`
  Queues, runs, fails, and atomically publishes one analysis version.
- `finding_synthesis_service.py`
  Builds evidence-calibrated paper and cross-paper Findings.
- `semantic_build/`
  Discovers candidate Objectives, traverses selected Source content, extracts
  Objective Evidence, and produces typed analysis artifacts.
- `comparison_service.py`
  Builds deterministic comparable-result and comparison projections.
- `research_view_aggregation_service.py`
  Aggregates paper facts and comparison projections for collection, material,
  and document views. It does not own Objective Findings.
- `workspace_overview_service.py`
  Builds the collection overview from Source and Core readiness.

There is no second persisted Objective result graph. Selection, traversal, and
intermediate synthesis state stay inside the analysis pipeline.
