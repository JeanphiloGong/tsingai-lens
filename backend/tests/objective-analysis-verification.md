# Objective Analysis Verification

These checks exercise the scientific responsibilities described in the
[analysis module](../application/core/objectives/analysis/README.md). The
acceptance target is a real research chain, not a model-only JSON check.

## Focused commands

Run from backend:

    .venv/bin/python -m pytest -q tests/unit/application/test_paper_experiment_extraction.py
    .venv/bin/python -m pytest -q tests/unit/application/test_paper_experiment_authoring_contract.py
    .venv/bin/python -m pytest -q tests/unit/application/test_experiment_analysis_writer.py
    .venv/bin/python -m pytest -q tests/unit/application/test_objective_analysis_service.py
    .venv/bin/python -m pytest -q tests/integration/test_four_paper_research_flow.py
    .venv/bin/python -m pytest -q tests/integration/test_deep_path_research_flow.py

The two integration scenarios require their documented fixture and database
prerequisites. If they cannot run in the current environment, report that
explicitly; a passing focused unit test is not evidence that the complete
research chain works.

## What the tests must cover

The runtime sequence is:

1. Source screening preserves recall for paper-local objective signals.
2. Routing selects bounded Source reads and records technical omissions.
3. Draft extraction returns only content, local keys, Source labels, and
   unresolved issues.
4. Preparation rejects formal IDs and invalid local references while retaining
   reportable values.
5. Reconciliation treats model boundary proposals as advisory. A physical
   split needs positive Source evidence; an overlapping scope needs a matching
   parent and selector.
6. Binding resolves Source labels and computes exact/partial/ambiguous result
   edges. Generic sample or test categories cannot self-certify as exact.
7. The writer persists immutable revisions. A partial revision is retained for
   audit but does not create an Objective selection.
8. A ready selection may feed single-paper synthesis. A cross-paper group is
   optional and must not repair an unresolved binding.
9. The compatibility projection is read-only and does not create a second fact
   ledger.

## Failure-focused regression cases

The focused suite should keep these cases explicit:

- a broad sample or test label preserves its value and Source but yields a
  partial or uncertain binding;
- a missing result-level sample/test edge blocks strict selection;
- a model-provided exact/completed flag cannot promote a generic label;
- a conflicting report is retained as a separate measurement and blocks
  comparison direction until resolved;
- an unknown or section-derived boundary cannot receive an identity merely
  because it appeared first;
- a selected stratum must hit a concrete parent fact;
- independent scopes require Source-backed split evidence;
- multiple complementary reads merge only through the same local key and
  compatible Source lineage;
- a provider or parser failure remains technical/retryable and is not reported
  as scientific absence.

## Researcher-parity acceptance

Use a fixture reviewed by an expert, not only a synthetic model response. The
fixture should include at least one result table whose sample definitions and
test protocol occur in different Sources, one repeated or conflicting report,
and two candidate experiment series that share an outcome but are not the same
physical population.

The acceptance question is whether a researcher can reach the same defensible
decision from the Lens result. Check all of the following:

1. **Source recall:** every Source with an explicit objective variable, condition,
   or outcome is inspected or recorded as a bounded omission.
2. **Fact completeness:** each retained report has its value/text, unit or
   unknown unit, local condition labels, report scope, and Source labels.
3. **Binding honesty:** exact status requires both result-level binding edges and
   a concrete applicable protocol. Broad facts remain visible but are not
   treated as exact.
4. **Boundary honesty:** tables, sections, outcomes, and response ordering do not
   define physical experiments without positive evidence. Independent
   populations are not merged for convenience.
5. **Conflict preservation:** different source reports are visible as different
   observations with reasons; no first-value wins rule is allowed.
6. **Comparison discipline:** coupled factors, incompatible context, and
   unresolved protocol details remain associative, descriptive, or
   non-comparable.
7. **Calibrated publication:** only a ready selection can support a Finding, and
   the Finding cannot be stronger than its selected revisions.
8. **Failure visibility:** technical failures remain technical failures with
   traces and contribution warnings.

## Live-provider evaluation

Live runs are evidence about one model, endpoint, prompt version, Source bundle,
and budget. Preserve the raw provider response and the post-service candidate
separately. Do not count deterministic fixture canonicalization as model recall.

At minimum, record:

- boundary precision and recall;
- measurement and comparison recall;
- exact result-binding count and non-exact count;
- Source traceability and conflict recall;
- omitted Source references and technical failures;
- whether the result is partial-revision, selection-ready, or Finding-ready.

A partial revision means that auditable content was retained. It is not a
published conclusion and must not be used to claim that boundary-first,
fact-first, hybrid, or any other strategy has solved whole-paper extraction.

## Chain-level evidence

For a completed run, retain:

- the confirmed Objective and fixed analysis version;
- Source IDs/fingerprint and route dispositions;
- raw Draft attempts and service audit issues;
- immutable revision IDs and binding statuses;
- selection/group/Finding lineage, if any; and
- the final scientific abstention reason when no Finding is produced.

This evidence lets a reviewer distinguish a model omission, an intentional
partial archive, a binding blocker, a non-comparable study, and a technical
failure without re-running the provider.
