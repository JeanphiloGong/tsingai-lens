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
- A fully bound measurement references objects and test conditions in the same
  experiment revision and carries both its `variant_key` and `test_key`.
  `exact` is allowed only when both edges have result-level binding evidence:
  the Draft supplies `variant_binding_source_labels` and
  `test_binding_source_labels`
  (one source may support both when it actually states both relationships),
  and the resolver can resolve those labels to `SourceReference` records. A
  numeric-value source, an entity-definition source, a category-level test
  source, or a model-local key alone does not prove that this result belongs
  to that concrete variant and protocol. A partial revision may retain a real
  reported measurement with one or both keys null when the source only gives a
  broad sample/test scope. It must keep the verbatim reported labels,
  candidate references, binding evidence (when present), and an unresolved
  issue; it must not create an `unknown` pseudo-entity merely to satisfy a
  foreign key.
- A selection fixes an experiment identity and version; it never means
  "latest".
- Reported values remain separate from derived differences or trends.
- Unknown conditions and source conflicts remain explicit; defaults cannot fill
  them.
- Test identity and protocol coverage are separate. `tensile`, `XRD`, or
  `mechanical test` can be a category-level fact while missing method
  identity keeps the measurement out of a protocol-sensitive comparison. A
  category-level test can therefore be retained for search and audit, but it
  cannot provide an `exact` test edge. A concrete, outcome-applicable identity
  with result-level binding evidence is sufficient for an exact edge;
  `protocol_completeness=partial|unknown` remains recorded limitation metadata
  and does not by itself block a Selection.
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

Formal identity allocation has an explicit application handoff:
`PaperExperimentModelOutput -> ReconciledPaperExperimentOutput -> revision`.
`bind_model_output` accepts only the service-owned reconciled wrapper. The
wrapper contains the accepted local scopes and any reconciliation audit issues;
a raw model envelope cannot receive formal IDs directly. This is a code-level
guard against assigning one experiment identity per `boundary-first` proposal.

Identity allocation is downstream of boundary reconciliation. A low-level
source/identity adapter must receive reconciled Drafts only; it must not assign
one formal experiment identity per raw boundary proposal. Any caller that has
not run the parent-first reconciliation step must stop before writing a
revision.

Draft-only scope details such as `reported_sample_label`,
`reported_test_label`, `candidate_variant_keys`, `candidate_test_keys`, and
`unresolved_issues` must survive that boundary. The write adapter maps them to
the revision's `measurement_scope`/notes and embedded unresolved-issue records (and
resolves source labels to `SourceReference` values); it must not discard them
because the formal `variant_key` or `test_key` is null. If the target revision
schema cannot represent one of these details yet, the adapter refuses the
revision rather than silently dropping the evidence.

### Reported scope is not a binding

The provider must not solve source reading and exact entity binding in one
step. A non-table observation is first represented by its reported scope: the
paper's wording, outcome, value, statistics, and source labels. It may say
`as-SLM`, `sample`, or `mechanical test` and have no local variant/test key.
That is a valid source fact, not a failed database entity.

The application resolver then uses table row identity, captions, footnotes,
and applicable Methods to decide whether the observation can be attached to a
concrete `ExperimentalVariant` and `ExperimentTestCondition`:

```text
reported scope / table row
  -> canonical source fact
  -> resolver candidate set
  -> exact | partial | ambiguous | unbound
  -> selection gate for the current Objective
```

Only an `exact` edge is eligible for a strict comparison. For the other
states, the revision keeps the verbatim labels, candidate references, and a
targeted unresolved issue; it does not create a generic pseudo-variant or
pseudo-test merely to satisfy a foreign key. A partial revision can therefore
contain exact measurements and broad observations together. Whether the exact
subset answers an Objective is decided by `ObjectiveExperimentSelection`, not
by unrelated observations in the same paper.

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
distinguishable process levels or concrete protocols. The extraction contract has
three explicit layers:

```text
SourceFact / ReportedScope
  what the paper reports, including broad labels and unresolved ranges
      -> BindingStatus
  exact | partial | ambiguous | unbound, computed by the service
      -> Selection/analysis readiness
  whether the records selected for this Objective have compatible identity,
  test protocol, outcome, and source coverage
```

If a measurement cannot be bound uniquely, its local key is left empty and a
targeted unresolved issue points to the missing row, caption, footnote, or
Methods scope. The result may be written to a partial revision and revisited by
a later bounded reread; it cannot silently become a bound revision. A category-level test
identity may be stored for search and audit, while `protocol_completeness` and
`missing_parameters` remain source-coverage metadata. An explicit outcome-scope
mismatch or missing result-level binding still blocks that measurement from a
Selection.

Table extraction is intentionally narrower: the model returns complete table
rows (row identity, headers, values, units, and source labels). The service
derives row-local variants and measurements. Methods/context extraction supplies
test protocol facts. This avoids asking one table call to invent global sample
and condition objects or exact sample--test edges.

`reported interpretation extraction` is the single bounded stage that follows
fact and table reconciliation. It records an author's explicit comparison,
mechanistic statement, or limitation and links it to local candidate
measurements or comparisons. It does not repair missing bindings, invent a
causal explanation, or replace the deterministic binding and integrity gates.

Boundary proposals are advisory and member arrays are hints, not the final set.
The default is one parent study. A different table, outcome, or test does not by
itself create a new experiment. Reconciliation may retain a physical split only
when the sources support a different object population, intervention assignment,
or experimental design. `selected_stratum` and `follow_up` scopes may overlap
the parent, but they require an explicit selector; a `parent_series_key` alone is
not evidence for a second scope. Shared variants and tests may belong to more
than one proposed series.

If a boundary call returns several scope proposals but no explicit parent or
matrix proposal, the service creates a `synthetic_parent` as a service-derived,
uncertain ownership container. It records that the model did not establish a
paper-level parent; it does not claim that the paper reported a new physical
experiment, does not create scientific comparisons, and is not counted as an
additional experiment for boundary quality. The original proposals remain
available for selector validation and audit rather than one selected scope
being promoted to the whole paper.

`selected_stratum` and `follow_up` are retained only when their
`scope_selector` matches at least one canonical concrete variant or test. A
selector that names an outcome only, points to a nonexistent level, or is
supported only by `split_evidence` cannot establish membership. The service
merges that proposal back into the parent, removes its local selector from the
parent facts, and retains the original proposal and a targeted unresolved issue
in the audit. This deterministic check is what limits boundary-first
over-splitting; it also prevents a broad fact-first scope from silently
absorbing unrelated rows.
Conversely, a proposal that omits a measurement whose variant and concrete test
are already explicit is completed deterministically. A measurement with either
binding missing remains unresolved rather than being attached by proximity.

Older or weaker model calls may provide a useful scope label while omitting the
scope enum or selector. The reconciliation service may recover a narrow,
non-physical selector from an unambiguous label such as `selected 120 W / 100
mm/s` or `wear comparison`, and must record that this was deterministic label
normalization. It must not infer a split from a section name, table name,
outcome, or test alone. If the label is not sufficient to form a selector, the
proposal is collapsed into the parent and an unresolved audit item is retained.
This keeps boundary-first output diagnostic while allowing historical traces to
be replayed without asking the model to invent membership lists.

Repeated source-local records are merged by a conservative semantic signature.
When the same resolved variant/test/outcome/unit has different reported values,
the revision retains one conflict record with both reports and their sources; it
does not select a preferred value. Comparisons generated from enumerable table
rows are bounded candidates and are admitted only when both sides reference
existing measurements. Invalid or one-sided comparison proposals are rejected
with an audit issue, not persisted as scientific relationships.

These rules explain why a valid JSON response or a high source-traceability score
is not sufficient for a revision. The write gate distinguishes:

- `partial_revision_write_ready`: the source facts, provenance, and unresolved
  edges form an auditable revision;
- strict `revision_write_ready`: no unresolved sample/test edge remains for the
  revision being marked bound;
- Objective-level analysis readiness: only the selected measurements/comparisons
  need compatible exact identity and protocol. Unrelated partial observations do
  not invalidate a usable exact subset.

The minimum gate must cover experiment membership, concrete bindings for the
selected records, conflict preservation, and comparison integrity; it must not
force the extractor to delete real broad observations just to improve a compact
boundary F1 score.

`抽取失败` 不等于 `无法 exact 绑定`。这三个结果必须分别路由：

| 观察到的问题 | 正确状态 | 后续动作 |
| --- | --- | --- |
| 原文事实缺失或表格行遗漏 | `partial`，并记录缺口 | 针对指定表格、脚注或 Methods 定向补读 |
| 原文只给出宽泛 sample/test 范围 | `partial` / `unbound` | 保留原文范围、候选和未决项；不猜精确边 |
| boundary proposal 过拆或过合 | 服务协调问题 | parent-first 合并无证据 split；仅在独立群体、分配或设计证据存在时 split |

同一语义的不同数值不是“选一个最可信值”，而是 `conflict`：保留双方报告、
各自 Source 和统计口径。只有 resolver 产生 `exact` 的样品边和测试边后，记录才
能进入 strict revision、Objective Selection 或 Finding 的可比子集。这样模型可以
负责完整恢复事实，服务负责安全绑定；两者不再被一个召回率或一个布尔状态混在一起。

### Gate failure and bounded reread

A failed strict gate is a routing result, not a request to regenerate the whole
experiment. The service may persist a `partial` revision and creates a bounded
reread task for the smallest missing source context:

| Unresolved condition | Reread only | Success condition |
| :--- | :--- | :--- |
| Broad or ambiguous variant | The named row, headers, caption, footnote, or sample definition | One concrete variant candidate, or an explicit decision to remain unbound |
| Category or partial test | Applicable Methods, footnotes, and protocol parameters | One concrete protocol with source-supported applicability |
| Missing table row | The named table, continuation, and relevant columns | Every visible relevant row has a source-local record |
| Conflicting reports | The two reported passages and their statistical scope | Both values and each Source remain preserved as a conflict |
| Missing relationship | The relevant Results/Discussion passage | Only an author-stated relationship is added; no inferred causality |

The reread merges into the existing partial revision and reruns the same
canonicalization, reconciliation, and binding gates. It must not delete an
unresolved fact, rename a formal entity, or use a model guess to turn a broad
label into an exact edge. If bounded rereads remain inconclusive, the revision
stays `partial`; an Objective-level selection may still use an exact compatible
subset, while strict revision and Finding paths remain blocked for the
unresolved records. This single route handles boundary over-splitting, merged
experiments, and omitted conflicts without weakening the contract.

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
