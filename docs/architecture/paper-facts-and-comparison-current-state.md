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
  -> persisted PaperExperiment revision
  -> ObjectiveExperimentSelection[]
  -> optional ComparisonGroup[]
  -> Finding[]

Existing Objective/Evidence response shapes are read-only projections of this
graph. Human- or Agent-authored analysis versions keep their own immutable
snapshot payload.
```

The Sources may be distributed across Methods, a result table, and prose. Each
fact retains its own Source support. `PaperExperiment` binds facts only within
one paper. Cross-paper synthesis begins only after fixed Objective selections
have established compatible measurements; the user-facing Evidence shape is a
read-only projection of those selections for automatic analyses.

## Model Hierarchy

### Core Research Records

These objects carry the main analysis meaning:

| Object | Responsibility | Persistence |
| --- | --- | --- |
| `ObjectiveAnalysis` | Owns one versioned analysis run and its scientific or technical outcome | Stored as lifecycle metadata; authored snapshots remain in its payload |
| `PaperContribution` | Accounts for one selected paper, including coverage, exclusion, failure, and selection disposition | Stored as analysis metadata or a compatibility projection |
| `ObjectiveEvidence` | Compatibility/read model for Source-grounded experiment facts and authored Evidence | Projected from fixed selections for automatic analyses; stored in authored snapshots |
| `SourceObservation` | Holds one exact Source-local fact while a revision is assembled | Per-execution reconstruction state |
| `PaperExperiment` | Binds same-paper observations, samples, conditions, and measurements | Immutable revision rows |

`SourceObservation` is transient Source-local evidence used while assembling a
revision. `PaperExperiment` is the durable scientific record; its revision is
what later Selections and Findings reference. Persistence is therefore part of
the current model contract, not an implementation detail to infer from a prompt.

### Component Values

These types are parts of a larger record, not separate product concepts:

- `SampleVariant`, `TestCondition`, and `MeasurementResult` belong to a
  `PaperExperiment`.
- `ScientificAttribute`, `ScientificVariable`, `ScientificComparison`,
  `ScientificResult`, and `ScientificContext` are shared source-fact value
  objects used while building a revision and its compatibility projection.
  They do not constitute a second Evidence lifecycle.
- `InspectedObjectiveSourceRef` records which canonical Sources were inspected
  while accounting for one `PaperContribution`.

They remain typed because their invariants matter, but the UI, API, and design
language should not present them as independent workflow stages.

### Historical Checkpoints

The former `ObjectiveDocumentEvidence` payload was a per-document execution
checkpoint. It is no longer read or written by the automatic runtime. Migration
`20260924_0075` removes embedded checkpoint maps from analysis snapshots while
retaining a payload hash and `manual_review_required` row for historical audit.
Retries write successor experiment revisions instead of reusing that checkpoint.

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
- `ScientificComparison` carries the source-supported comparison content that
  can enter a revision, selection, and Finding decision.

The internal status check is deliberately not another persisted
`ExperimentComparison` workflow object. Source lineage lives on observations,
the comparison row lives inside the immutable experiment revision, and the
selection decides whether it can support a Finding.

## Methods And Context

Methods information remains necessary, but the current runtime does not need an
independent `MethodFact` family. A Methods Source first enters as a
`SourceObservation`. Its supported details then bind to the scientific object
that consumes them:

- sample preparation and process state -> `SampleVariant` or a revision's
  source-grounded context;
- test setup and environment -> `TestCondition` or a revision's test context;
- characterization context -> source-grounded revision context;
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
4. reconstruction binds accepted same-paper facts into a `PaperExperiment` draft;
5. `ExperimentAnalysisWriter` persists an immutable revision and Objective
   selections, then creates an optional comparison group and Finding;
6. compatibility queries project the requested revision into the existing
   Objective/Evidence response shape.

Automatic revisions, selections, groups, and Findings have independent
identities and foreign keys. Authored Evidence/Finding snapshots remain inside
their versioned Objective analysis payload and are not mixed with the automatic
graph.

## Invariants

- A relevant Source is not automatically Evidence.
- A measurement is not comparable merely because it has a number.
- Facts from different papers cannot be bound into one `PaperExperiment`.
- Missing Methods or test context remains missing; it is not inferred from a
  result table.
- Baseline and target roles require a Source-supported comparison.
- Technical failure is not scientific absence.
- A paper with no selected experiment still needs an explicit contribution or
  failure disposition.
- Finding synthesis consumes fixed experiment selections, not raw model output
  or a compatibility projection assembled from the latest revision.

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

The current `PaperExperiment` revision is durable but is not yet a general
user-editable experiment workspace. Add authoring or correction commands only
when a concrete researcher workflow needs them; do not mutate a revision that a
Finding already references. Do not add a new domain family only because an
extraction prompt can return another JSON section.

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Objective Scientific Analysis](../../backend/application/core/objectives/analysis/docs/scientific-analysis.md)
- [RFC Paper-Facts Primary Domain Model](../decisions/rfc-paper-facts-primary-domain-model.md)
