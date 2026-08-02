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
  records containing exact excerpts and typed Source locators. Discovery,
  framing, routing, and extraction consume the persisted ResearchObjective
  variables, outcomes, mechanisms, constraints, and requested comparator
  directly. Table-selection hints remain transient service values.
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

Each extracted Evidence record binds one exact Source excerpt to an explicit
scientific attribution contract:

- `changed_variables` retains every changed factor with baseline and target
  values;
- `comparison` records both groups, all comparison axes, and whether the
  groups are scientifically comparable;
- `reported_result` contains exactly one measured outcome for result Evidence;
- `attribution_scope` distinguishes an isolated effect, joint effect,
  association, description, or non-attributable comparison;
- `scientific_context` stores fixed material, sample, process, and test
  attributes as typed name/value/unit entries.

Transient extraction state is scoped to one Objective, analysis version, and
document. It carries only prior role/outcome coverage and Source positions
between blocks, never prior scientific values or context. It is reset before
the next document and never supplies a missing changed variable or outcome.

Deterministic table Evidence retains row and result-column coordinates in its
related Source locators. Pairwise table results include both source rows, retain
material differences, reject sparse comparison axes as non-attributable, and
are bounded per Objective/document.

Finding synthesis uses eligible direct-result Evidence plus bounded condition
and mechanism context. A paper Finding remains `paper_level_only`; a
cross-paper Finding requires comparable direct results from at least two
distinct papers. Coupled variables may be represented as associations or
limitations, not isolated causal effects.
