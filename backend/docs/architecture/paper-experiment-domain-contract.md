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

- `ExperimentalVariant` (called `SampleVariant` in the materials-science
  vocabulary) stores one object or object/processing combination. This is one
  model, not a second sample entity. Processing attributes such as laser power,
  scan speed, or heat treatment belong there; they are not a generic test
  `condition`.
- `ExperimentTestCondition` stores a test or characterization protocol and its
  operating parameters. A single variant may be measured under several test
  conditions, and one test condition may apply to several variants.
- A measurement references only objects and test conditions in the same
  experiment revision; an ordinary object-level measurement carries both its
  `variant_key` and `test_key`.
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

## Model authoring boundary

The provider returns content only. Its Draft may use local
`variant_key`, `test_key`, `measurement_key`, and `comparison_key` values to
refer to records within that one response. It must not return formal
`experiment_id`, component/database `id` values, `experiment_version`,
`collection_id`, `objective_id`, any final `measurement_id`/`result_id`/
`comparison_id` (including plural ID lists or other formal `*_id` fields),
source-reference records, or
`identity_status`/`binding_status`/`relation_status`.

The application supplies the document and source context, resolves source
labels, assigns or matches formal identities, creates database relations and
unique constraints, computes or verifies statuses, and only then writes a
`PaperExperiment` revision. A model response that contains one of these
service-owned fields is rejected; it is never silently copied into a formal
record.

## Extraction and reconciliation boundary

The model is not the final experiment assembler. The implementation follows
this order:

```text
Source-local facts
  -> deterministic canonicalization
  -> boundary proposal and reconciliation
  -> deterministic table-row comparisons
  -> reported interpretation extraction
  -> binding/integrity gate
  -> PaperExperiment revision
```

`SampleVariant`/`ExperimentalVariant` and `TestCondition` are source-supported
candidates, not permission to guess a relationship. A label such as `as-SLM`,
`sample`, or `mechanical test` is insufficient when the same source contains
distinguishable process levels or concrete protocols. If a measurement cannot be
bound uniquely, its local key is left empty and a targeted unresolved issue points
to the missing row, caption, footnote, or Methods scope. The result may remain in
a partial Draft, but it cannot silently become a bound revision.

Boundary proposals are advisory. A different table, outcome, or test does not by
itself create a new experiment. Reconciliation may split only when the sources
support a different object population, intervention assignment, or experimental
design; shared variants and tests may belong to more than one proposed series.
Conversely, a proposal that omits a measurement whose variant and concrete test
are already explicit is completed deterministically. A measurement with either
binding missing remains unresolved rather than being attached by proximity.

Repeated source-local records are merged by a conservative semantic signature.
When the same resolved variant/test/outcome/unit has different reported values,
the revision retains one conflict record with both reports and their sources; it
does not select a preferred value. Comparisons generated from enumerable table
rows are bounded candidates and are admitted only when both sides reference
existing measurements. Invalid or one-sided comparison proposals are rejected
with an audit issue, not persisted as scientific relationships.

These rules explain why a valid JSON response or a high source-traceability score
is not sufficient for a revision. The minimum gate must also cover experiment
membership, concrete bindings, conflict preservation, and comparison integrity.

## HTTP compatibility matrix

The experiment migration is an internal replacement of the scientific state
behind the existing Objective endpoints. Until a separately approved API
change is documented, the following are frozen:

| Surface | Rule during V0--V9 |
| :--- | :--- |
| Existing path and method | Keep the same path, HTTP method, operation identity, and authentication dependency. |
| Existing request | Keep parameter names, required/optional status, validation limits, and task-control semantics. |
| Existing response | Keep the fields and meanings consumed by current clients; a query projection may obtain them from the new records. |
| Internal application/repository calls | May change to pass experiment revisions, selections, or groups; these are not public HTTP parameters. |
| New experiment detail/export capability | Add a new route and schema; do not overload an existing request or silently change its response. |

The implementation check is deliberately mechanical: the migration commits
must not edit `backend/controllers/` or the existing controller schemas unless
the chapter explicitly declares an approved API addition, and the final
checkpoint runs the existing router/schema tests. A database column or domain
field added for traceability is not by itself an HTTP contract change.

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
