# Core Semantic Build

This package consumes normalized Source artifacts and produces typed Core
semantic records.

## Responsibilities

- `document_profile_service.py`
  Classifies each document and produces a bounded collection summary.
- `research_objective_service.py`
  Discovers Objective candidates and runs confirmed Objective analysis. It
  traverses Source document trees with bounded transient state, emits one
  `PaperContribution` per included document, and emits `ObjectiveEvidence`
  records containing exact excerpts and typed Source locators.
- `paper_facts_service.py`
  Extracts reusable evidence anchors, methods, sample variants, test
  conditions, baselines, measurements, and characterization observations.
- `core_semantic_version.py`
  Owns semantic-version invalidation for rebuildable Core artifacts.
- [`llm/README.md`](llm/README.md)
  Owns prompt, schema, provider-call, and structured-response contracts.

## Objective Boundary

Candidate discovery is part of collection build. Deep analysis begins only
after the user confirms an Objective. Each run receives one immutable Source
build, allocates a new `analysis_version`, and returns:

- `PaperContribution[]`
- `ObjectiveEvidence[]`
- `Finding[]`

Source selection and extraction are one persisted Evidence lifecycle:
`candidate -> selected -> extracted | rejected | failed`. Selection decisions
may be transient, but only `ObjectiveEvidence` is durable.

Finding synthesis uses eligible direct-result Evidence plus bounded condition
and mechanism context. A paper Finding remains `paper_level_only`; a
cross-paper Finding requires comparable direct results from at least two
distinct papers. Coupled variables may be represented as associations or
limitations, not isolated causal effects.
