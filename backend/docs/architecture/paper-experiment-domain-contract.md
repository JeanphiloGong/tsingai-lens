# PaperExperiment Domain Contract

This document is the backend implementation boundary for the paper-experiment
refactor. It complements the research design document outside this repository;
it does not change the current HTTP contract.

## Target chain

```text
prepared Source
  -> PaperExperimentDraft
  -> PaperExperiment revision
  -> ObjectiveExperimentSelection
  -> optional ComparisonGroup
  -> Finding
```

`PaperExperiment` is reusable paper state. It is not owned by an Objective or
Collection. An Objective selects experiment content through
`ObjectiveExperimentSelection`.

## Required invariants

- A measurement references only objects and test conditions in the same
  experiment revision.
- A selection fixes an experiment identity and version; it never means
  "latest".
- Reported values remain separate from derived differences or trends.
- Unknown conditions and source conflicts remain explicit; defaults cannot fill
  them.
- A comparison group does not store another copy of measurement values.
- A Finding can be traced through its selections to a fixed experiment revision
  and Source.
- Existing `/api/*` and `/api/v1/*` paths, request parameters, authentication,
  task states, and existing response semantics remain compatible unless a
  separate API change is approved.

## Persistence boundary

The target database uses one `paper_experiment` table for stable identity and
multiple `experiment_version` rows. The database primary key is `id`; domain
keys inside one experiment version use `variant_key`, `test_key`,
`measurement_key`, and `comparison_key`.

The target persistence tables are introduced incrementally. The old
`ObjectiveEvidence` path is removed only after the new read/write path and its
public-contract regression tests are complete.

## Checkpoint rule

Each implementation version must have a focused test and a real-scenario
boundary test before it is committed. A passing parser or ORM import is not a
scientific checkpoint. Technical provider failure, unresolved source support,
and non-comparable evidence remain distinct outcomes.
