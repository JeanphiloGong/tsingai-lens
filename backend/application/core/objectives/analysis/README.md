# Objective Analysis

This package answers one confirmed research question using exact paper Sources.
Navigation hints may guide reading, but only Source-grounded facts become
Evidence. Technical failure is not a scientific conclusion.

## Start Here

`ObjectiveEvidenceAnalysisService.generate_objective_analysis_artifacts()` in
[`../objective_analysis_service.py`](../objective_analysis_service.py) coordinates
the selected papers and their reusable checkpoints. Read
`_generate_document_evidence()` there for the single-paper scientific sequence.
[`../analysis_service.py`](../analysis_service.py) separately owns scheduling,
analysis versions, progress, and atomic publication.

```text
confirmed Objective + exact prepared papers
  -> screen and route Sources for one paper
  -> extract one Source -> validate that Source immediately
     -> read missing same-paper context when needed
  -> reconstruct same-paper experiments
  -> materialize Evidence and checkpoint the paper
  -> compare the selected paper outcomes
  -> return Findings for publication
```

For example, a tensile table may contain elongation values while Methods
identifies the preheated specimens. Inspect and validate both Sources before
binding them. A review mentioning the same outcome is not a second primary
measurement. Different sample states must not be pooled into one comparison.
The control and treated specimens are baseline/target roles in that comparison;
they are not promoted into standalone `BaselineReference` records.

## Responsibilities

| Step | Direct entry | Input and output | Model calls | Writes |
|---|---|---|---|---|
| Screen | `source_screening.screen_sources` | Objective and paper Sources -> frames | Yes, bounded batches | None |
| Route | `evidence_routing.route_sources` | Screened frames and Source tree -> deterministic inspection tasks | No (screening owns semantic relevance) | None |
| Extract | `source_extraction.extract_and_validate_source_facts` | Routes and Sources -> source observations | When deterministic extraction is insufficient | None |
| Ground | `source_validation.validate_source_fact` | One source observation and its exact Source -> validated, uncertain, or rejected observation | No | None |
| Bind | `paper_experiment.reconstruct_paper_experiments` / `assemble_paper_experiments` | Same-paper facts -> scoped `PaperExperiment` records with measurement links and derived-observation lineage | No | None |
| Materialize | `evidence_materialization.materialize_evidence` | `PaperExperiment` Source observations plus application `SourceReadAudit` records -> Evidence and contribution records | No | None; caller stores records |
| Compare | `finding_synthesis.FindingSynthesisService.synthesize` | Paper contributions and Evidence -> Findings | Optional assertion judge | None; caller publishes |

Extraction and grounding alternate per Source, not as two collection-wide
passes. The next Source sees only already accepted facts. Missing conditions
remain missing unless an inspected Source in the same paper supports them.
The detailed rules are in [Scientific Analysis](docs/scientific-analysis.md).

Within `source_extraction.py`, start with
`extract_and_validate_source_facts()` for the reading loop, then
`_extract_source_round()` for one batch's immediate extraction and validation.
The loop reuses that batch operation without recursive execution modes.
`_build_adaptive_context_routes()` coordinates missing-result anchors, candidate
collection, result-local matching, and next-read selection. Its private
`_ContextSourceCandidate` names navigation scores and Source identities; it is
not a persisted record or grounded Evidence.

## Technical Support

- [`table_repair.py`](table_repair.py): `repair_table_source()` restores a
  parser-fragmented table, with unchanged row-label, token, and numeric-sequence
  checks. It returns the original or verified Source and any repair error.
  Its optional model call is layout recovery, not scientific fact extraction.
- [`source_text.py`](source_text.py): numeric text parsing shared by table
  checks and Source inspection; no model or persistence.
- [`../llm/structured_response.py`](../llm/structured_response.py): provider
  invocation, structured response recovery, usage, and traces.
- [`diagnostics.py`](diagnostics.py): internal analysis observations; diagnostics
  never fill an Evidence field. Failure records retain exception types and
  frame locations without provider exception text, source code, or locals.

## Changing This Module

Modify the owner of the decision, then its existing regression test. For a
table-layout problem, begin with `table_repair.py`; for an unsupported field,
begin with `source_validation.py`; for incorrect cross-paper grouping, begin
with `finding_synthesis.py`. Do not change all three to accommodate one result.
Adding a scientific stage also requires the coordinator, checkpoint version,
and scenario tests to acknowledge it; moving code does not change a version.

Preserve comparable, associative, descriptive, unresolved, and non-comparable
outcomes. A completed inspection can yield no Finding. Provider or parsing
failure remains retryable; partial technical failure remains visible in paper
contributions and traces. Publication never exposes incomplete checkpoint work.

## Tests

See [Objective Analysis Verification](../../../../tests/objective-analysis-verification.md)
for the real-paper cases, fixture limits, and commands. The nearest focused
tests are `test_objective_evidence_extraction.py`,
`test_objective_evidence_comparison.py`, and
`test_objective_evidence_materialization.py` under `tests/unit/application/`.
