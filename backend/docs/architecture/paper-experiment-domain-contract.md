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
