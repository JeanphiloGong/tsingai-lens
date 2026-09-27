# Objective Analysis

This package answers one confirmed research question using the paper Sources
that were prepared for that question. A relevant Source is a reason to inspect
the paper; it is not Evidence until its reported content and attribution have
been checked. Technical failure is not a scientific conclusion.

## Runtime Chain

The automatic path follows the order in which a researcher would work. A model
does not own the database graph or the final scientific status.

```text
confirmed Objective + prepared Documents
  -> screen Sources for recall
  -> route bounded Source inspection work
  -> extract PaperExperiment Draft content
  -> reconcile boundaries and local references in the service
  -> resolve Source labels and binding states
  -> write an immutable PaperExperiment revision
  -> create an ObjectiveExperimentSelection only for a ready slice
  -> optionally synthesize a cross-paper ComparisonGroup and Finding
```

`PaperExperimentDraft` is a candidate content graph. It may contain broad or
unknown sample/test facts, local keys, Source labels, and unresolved issues.
That is useful archive content, but it is not an exact binding. The service
must preserve the value and mark the affected measurement or revision
`partial`/`uncertain`; it must not infer a sample or test from a generic label.
Only a ready, source-grounded selection can enter Finding synthesis.

## Responsibilities

| Stage | Owning code | Input -> output | Model calls | Durable writes |
|---|---|---|---|---|
| Screen | `source_screening.screen_sources` | Objective and paper Sources -> transient frames | Bounded | None |
| Route | `evidence_routing.route_sources` | Frames and Source tree -> deterministic inspection routes | None | None |
| Extract | `PaperExperimentExtractor.extract` in [`paper_experiment_extraction.py`](paper_experiment_extraction.py) | Routed Source bundle -> `PaperExperimentModelOutput`/Draft | Bounded extraction and targeted retries | None |
| Prepare | `prepare_model_output` in [`paper_experiment_contract.py`](paper_experiment_contract.py) | Raw response -> validated local keys, source-label use, candidate direction and audit issues | None | None |
| Reconcile | `reconcile_model_output` | Candidate scopes -> service-owned accepted scopes | None | None |
| Bind | `bind_model_output` | Reconciled Draft -> formal Source references and `PaperExperimentRevision` | None | None |
| Write/select | `ExperimentAnalysisWriter.write_experiment_analysis` | Revisions -> immutable revisions and Objective selections | None | Revisions and selections |
| Synthesize | `ExperimentFindingSynthesisService` | Ready selections -> optional groups and Findings | Optional assertion annotation | Groups/Findings |
| Project | `ExperimentCompatibilityProjection` | Fixed experiment graph -> existing Objective/Evidence/Finding response shapes | None | None |

`source_extraction.py` remains the Source-local fact reader used by the
screening/routing path. It does not allocate experiment identities. The old
`paper_experiment.py` assembly and revision-converter path is retired; do not
add new callers or documentation links to it.

## Candidate Contract and Scientific Gates

The model receives service-created `Sxxx` labels, not database IDs. Its output
contains only:

- one or more bounded Drafts with response-local `series_key`, `variant_key`,
  `test_key`, `measurement_key`, and `comparison_key` values;
- reported sample/condition/test/result content and candidate local edges;
- the supplied Source labels used by each fact or binding edge; and
- unresolved boundary, conflict, or attribution issues.

The model must not emit formal IDs, collection/objective ownership, revision
numbers, `SourceReference` records, or final `binding_status`, `direction`,
`basis`, or attribution decisions. The service supplies those values after
validation. A model-provided `identity_specificity=exact` or
`protocol_completeness=complete` is advisory and cannot promote a broad label.

The gates are intentionally separate:

1. **Content gate:** a reported result has a value/text and a reviewable Source.
2. **Binding gate:** the result has a source-backed sample edge and test edge;
   the sample identity is concrete and the test protocol is applicable.
3. **Boundary gate:** an independent experiment split has positive
   Source-backed evidence. A section, table, outcome, or model response order
   is not a split by itself. Overlapping scopes are retained as views of a
   parent, not silently promoted to new experiments.
4. **Conflict gate:** competing reports remain separate measurements with an
   unresolved issue. The service never chooses a value merely because it was
   returned first.
5. **Objective gate:** only measurements/comparisons needed by the current
   Objective and satisfying the preceding gates create a Selection.

Paper-native identifiers are content, not Lens identities. To keep the Draft
contract usable across research fields, names such as `stimulus_id` or
`condition_id` may be preserved only inside an explicit
`population_scope.reported_identifiers` or
`measurement_scope.reported_identifiers` map. Lens-owned identities and every
other `*_id`/`*_ids` field remain prohibited outside those maps; the service
still allocates all formal IDs after the source and boundary gates.

Failure at a gate is visible. The revision can retain an auditable partial
archive, but it cannot create a strict selection or Finding from the blocked
content. A provider or parser failure is recorded as a technical failure and is
retryable; it is never converted into scientific absence.

## Handling Known Extraction Failures

Live extraction has exposed three distinct problems, and they require different
responses:

| Observation | Correct response |
|---|---|
| `sample`/`condition`/`test` is too broad to bind a result | Keep the reported value and Source; add candidate keys or an unresolved issue; set the binding to partial/uncertain. Read the specific Methods row, caption, or footnote before retrying. |
| `boundary-first` creates too many experiments | Treat boundary proposals as advisory. Do not allocate identity from a section/table boundary. Reconcile only explicit parent scopes, selected strata with a matching selector, or physical splits with positive Source evidence. |
| `fact-first`/`hybrid` merge independent work or drop conflicts | Merge only same-local-key complementary facts with overlapping Source lineage and no conflicting scalar report. Preserve conflicting values as separate measurements and run a targeted follow-up for the missing relation. |

The next attempt is therefore a bounded repair request, not an unconstrained
second reading of the paper. It names the missing binding edge, boundary
evidence, conflicting Source pair, or omitted result rows. If the repair cannot
close that item, keep the revision partial and stop; do not fill it from general
knowledge or from another paper.

## Tests and Verification

See [Objective Analysis Verification](../../../../tests/objective-analysis-verification.md)
for the end-to-end scenario and commands. Focused regression tests are:

- `tests/unit/application/test_paper_experiment_extraction.py`
- `tests/unit/application/test_paper_experiment_authoring_contract.py`
- `tests/unit/application/test_experiment_analysis_writer.py`
- `tests/unit/application/test_experiment_compatibility_projection.py`
- `tests/unit/application/test_objective_analysis_service.py`

The live benchmark is evidence about a particular model, prompt, Source bundle,
and endpoint. Report raw model recall separately from deterministic
canonicalization. A JSON response or a high measurement count is not a pass:
boundary precision/recall, result-level Source traceability, conflict recall,
and exact binding must be checked before claiming strict analysis.

## Changing This Module

Change the owner of the failed decision and its focused regression test. For
Source layout, start with `table_repair.py`; for fact acceptance or binding,
start with `source_validation.py` or `paper_experiment_contract.py`; for
boundary reconciliation, start with the contract and writer tests; for
cross-paper eligibility, start with `experiment_finding_synthesis.py`.

Do not add a second fact ledger, a compatibility wrapper, or a new public API to
hide an extraction failure. Preserve descriptive, associative, unresolved, and
non-comparable outcomes, and remove obsolete assembly/converter references when
the owning implementation changes.
