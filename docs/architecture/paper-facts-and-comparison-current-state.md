# Paper Facts And Comparison Current State

## Purpose

This note explains the current model hierarchy behind Objective analysis. It
prevents every dataclass from being mistaken for an equally important domain
entity and records where paper facts, comparison decisions, persisted Evidence,
and execution checkpoints belong.

Lens v1 remains a traceable cross-paper comparison product. The implementation
must reconstruct enough of each paper to compare it honestly, but it does not
need a permanent top-level entity for every extracted field.

## Current Research Chain

For a researcher asking whether platform preheating changes 316L elongation,
the current chain is:

```text
confirmed Objective + prepared papers
  -> inspect exact Sources
  -> SourceObservation[]
  -> PaperExperiment
       - SampleVariant[]
       - TestCondition[]
       - MeasurementResult[]
  -> ObjectiveEvidence[] + PaperContribution[]
  -> Finding[]
```

The Sources may be distributed across Methods, a result table, and prose. Each
fact retains its own Source support. `PaperExperiment` binds facts only within
one paper. Cross-paper synthesis begins only after formal Evidence exists.

## Model Hierarchy

### Core Research Records

These objects carry the main analysis meaning:

| Object | Responsibility | Persistence |
| --- | --- | --- |
| `ObjectiveAnalysis` | Owns one versioned analysis run and its scientific or technical outcome | Stored in the Objective analysis payload |
| `PaperContribution` | Accounts for one selected paper, including coverage, exclusion, failure, and Evidence disposition | Stored with the analysis |
| `ObjectiveEvidence` | Formal Source-grounded evidence used by Finding and review workflows | Stored with the analysis |
| `SourceObservation` | Holds one exact Source-local fact before formal Evidence materialization | Per-execution reconstruction state |
| `PaperExperiment` | Binds same-paper observations, samples, conditions, and measurements | Per-execution reconstruction state |

`SourceObservation` and `PaperExperiment` are scientifically meaningful even
though they are not separate database tables. Persistence alone does not decide
whether a model is a domain object.

### Component Values

These types are parts of a larger record, not separate product concepts:

- `SampleVariant`, `TestCondition`, and `MeasurementResult` belong to a
  `PaperExperiment`.
- `ObjectiveEvidenceAttribute`, `ObjectiveEvidenceVariable`,
  `ObjectiveEvidenceComparison`, `ObjectiveEvidenceResult`, and
  `ObjectiveEvidenceContext` describe parts of one `ObjectiveEvidence`.
- `InspectedObjectiveSourceRef` records which canonical Sources were inspected
  while accounting for one `PaperContribution`.

They remain typed because their invariants matter, but the UI, API, and design
language should not present them as independent workflow stages.

### Execution Checkpoints

`ObjectiveDocumentEvidence` is a reusable single-paper execution checkpoint. It
stores an input fingerprint, status, contribution, Evidence records, and
technical failure details so an analysis can resume safely. It is not an
additional scientific conclusion or a sixth core research object.

### Specialized Paper-Map Values

`ReviewKnowledgeItem` and `ReviewSynthesisMap` apply to review-paper mapping
before Objective analysis. They preserve review-author synthesis, disputes,
gaps, and citation leads without pretending that each cited study has been
reconstructed. They are not part of the experimental Evidence backbone.

## Comparison Semantics

A baseline is a role inside a particular Source-supported comparison, not a
standalone paper entity.

- `SourceObservation.comparison` retains baseline and target labels plus the
  Source-supported comparability statement.
- `SourceObservation.changed_variables` retains the corresponding variable
  levels.
- `MeasurementResult` retains each measured outcome without declaring that it
  is permanently a baseline or target.
- `PaperExperiment.comparison_status()` checks two measurement identities and
  returns `comparable`, `non_comparable`, or `insufficient_context` for internal
  diagnostics.
- `ObjectiveEvidenceComparison` carries the formal comparison content that can
  enter downstream Evidence and Finding decisions.

The internal status check is deliberately not another persisted
`ExperimentComparison` object. Source lineage already lives on observations,
and formal comparison content already lives on Evidence.

## Methods And Context

Methods information remains necessary, but the current runtime does not need an
independent `MethodFact` family. A Methods Source first enters as a
`SourceObservation`. Its supported details then bind to the scientific object
that consumes them:

- sample preparation and process state -> `SampleVariant` or Evidence process
  context;
- test setup and environment -> `TestCondition` or Evidence test context;
- characterization context -> Source-grounded Evidence context;
- unresolved narrative -> retained observation or explicit uncertainty.

This avoids maintaining an unused parallel method record while preserving the
actual paper content and provenance. A dedicated method entity should return
only if a real workflow needs independent method identity, lifecycle, or
cross-result reuse.

## Runtime And Persistence Boundaries

The runtime sequence is:

1. document preparation exposes stable text, table, figure, block, and section
   Sources;
2. screening and routing select Sources relevant to the confirmed Objective;
3. extraction creates `SourceObservation` records and validation immediately
   checks each observation against its exact Source;
4. reconstruction binds accepted same-paper facts into `PaperExperiment`;
5. materialization creates `ObjectiveEvidence` and `PaperContribution`;
6. a per-document `ObjectiveDocumentEvidence` checkpoint supports safe reuse;
7. Finding synthesis consumes published Evidence and contribution accounting.

`ObjectiveAnalysis`, checkpoints, contributions, Evidence, and Findings share
the versioned Objective analysis payload. This does not make them the same kind
of model and does not require every intermediate object to have a table.

## Invariants

- A relevant Source is not automatically Evidence.
- A measurement is not comparable merely because it has a number.
- Facts from different papers cannot be bound into one `PaperExperiment`.
- Missing Methods or test context remains missing; it is not inferred from a
  result table.
- Baseline and target roles require a Source-supported comparison.
- Technical failure is not scientific absence.
- A paper with no accepted Evidence still needs an explicit contribution or
  failure disposition.
- Finding synthesis consumes formal Evidence, not raw model output.

## Removed Redundant Models

- `BaselineReference` was removed because it duplicated a role already carried
  by Source-supported comparison data.
- `MethodFact` was removed because the active chain never produced or consumed
  it; Methods information remains Source-grounded and binds to the actual sample,
  condition, result, or Evidence context.
- `ExperimentComparison` was removed because its object fields were consumed
  only to count an internal status. `PaperExperiment.comparison_status()` keeps
  the judgment without introducing another public or persisted research object.

Legacy JSON fields are ignored at the domain read boundary and are not emitted
again. Historical migrations remain migration history and do not define the
current runtime contract.

## Open Boundary

The current `PaperExperiment` is an execution-time reconstruction rather than a
durable user-editable experiment record. Promote more of it into persistence
only when a concrete researcher workflow needs to inspect, correct, or reuse
that structure independently of formal Evidence. Do not add a new domain family
only because an extraction prompt can return another JSON section.

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Objective Scientific Analysis](../../backend/application/core/objectives/analysis/docs/scientific-analysis.md)
- [RFC Paper-Facts Primary Domain Model](../decisions/rfc-paper-facts-primary-domain-model.md)
