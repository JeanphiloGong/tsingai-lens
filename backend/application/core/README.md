# Core Application Layer

This package owns the evidence-first research model built from normalized
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

- `document_profiles/`
  Classifies Source documents and owns bounded collection profile summaries.
- `paper_facts/`
  Extracts reusable document-scoped facts for comparison and research views.
- `objectives/`
  Discovers candidate Objectives and owns confirmed, versioned analysis through
  atomic Finding publication.
- `structured_extraction/`
  Owns only domain-neutral message-content and JSON normalization. Domain
  packages own their prompts, response schemas, provider calls, retries, and
  model-specific validation.
- `comparison_service.py`
  Builds deterministic comparable-result and comparison projections.
- `research_view_aggregation_service.py`
  Aggregates paper facts and comparison projections for collection, material,
  and document views. It does not own Objective Findings.
- `workspace_overview_service.py`
  Builds the collection overview from Source and Core readiness.

There is no second persisted Objective result graph. Selection, traversal, and
intermediate synthesis state stay inside the analysis pipeline.
