# Objective Analysis Verification

These checks exercise the scientific responsibilities described in the [analysis module](../application/core/objectives/analysis/README.md).

## Repeatable Scenarios

Run from `backend/`:

```bash
.venv/bin/python -m pytest -q tests/integration/test_four_paper_research_flow.py
.venv/bin/python -m pytest -q tests/integration/test_deep_path_research_flow.py
.venv/bin/python -m pytest -q tests/unit/application/test_objective_evidence_extraction.py -k 'p004 or table_repair'
```

The four-paper HTTP case covers uploads, preparation, candidate discovery,
confirmation, analysis, publication, and exact Evidence inspection. It separates
as-built and stress-relieved specimens and a review paper. Its controlled model
responses make software regression repeatable; they do not prove live-provider
extraction quality.

The deep-path case uses the real P002 Source fixture under `fixtures/agent_p002/`
and PostgreSQL repositories. It follows non-preheated versus 150 C preheated
steel, including elongation values of 72% and 82%, through exact Source reads,
approved Objective and Evidence authoring, a published Finding, expert review,
a derived Objective, and a research plan. It reloads immutable lineage from the
database. The model is scripted, not a live model-quality evaluation. See
[database prerequisites](README.md#run-a-focused-check) before running it.

The P004 table regressions cover the retained Table 3/4 values and structural
repair, including rejection of invented labels, reordered values, and lost
uncertainties. These fixed matrices isolate the recovery contract; they do not
replace replaying the original PDF parser when parsing itself changes.

For a structural refactor, compare serialized records and request payloads
against the same pre-refactor inputs and recorded model responses. Keep random
IDs, timestamps, and run IDs fixed or explicitly separate them from the
scientific comparison. Also check OpenAPI, failure responses, and repository
round trips. A passing unit suite alone does not prove the complete chain.

The extraction suite tests a single reading batch through
`_extract_source_round()` and the complete adaptive reading loop through
`extract_and_validate_source_facts()`. Keep both gates: a single batch cannot
prove that subsequent context reads stop correctly or preserve result anchors.
Analysis lifecycle tests separately cover safe historical failure messages,
internal failure locations, retry versions, and retained published results.

## Researcher-Parity Acceptance

Repository ownership is also checked by
`tests/unit/repositories/test_repository_contracts.py`. Collection and Pipeline
PostgreSQL tests verify bounded summary queries independently of their unchanged
detail and write paths. Objective tests keep persistence timestamps outside the
scientific payload, and Evidence/Plan tests ensure state changes do not serialize
existing objects. Run these checks together with the two complete scenarios above
when changing repository result types or domain transitions.

The acceptance question is not whether the model produced fluent prose or
valid JSON. Given the same papers and the same confirmed Objective, a researcher
must be able to reach a conclusion in the same scientific direction and scope
from the published Lens result. The run is acceptable only when all of these
conditions hold:

1. **Recall:** every paper-local Source that explicitly reports an Objective
   variable, condition, or outcome is inspected, even when framing relevance is
   wrong or only medium. A Source with no such signal is recorded as out of
   scope; it is not silently lost.
2. **Fact completeness:** each reported result keeps its exact Source excerpt,
   locator, values, units, condition labels, and any jointly varied factors.
   Missing material, sample, method, or control context is represented as
   `needs_context`, `descriptive`, or `association_only`, never filled from
   general knowledge.
3. **Within-paper binding:** Methods, Results, tables, figures, and captions
   may complete one another only inside the same document and only through
   explicit sample or condition identities. A paper-level map is navigation,
   not experimental proof.
4. **Comparison discipline:** Findings compare only context-compatible
   Evidence. Different material states, processes, test conditions, or outcomes
   remain separate or `non_comparable`; coupled factors remain visible as an
   `association_only` stratum and never become a convenient pooled causal
   average.
5. **Calibrated conclusion:** a Finding cannot be stronger than its Evidence.
   Controlled one-factor comparisons may support an isolated effect; otherwise
   the result remains associative or descriptive. An empty Finding means
   grounded scientific abstention only when the Evidence and paper dispositions
   explain the gap.
6. **Failure visibility:** provider, parsing, and technical failures remain
   `extraction_failed` with trace and contribution warning. They cannot be
   presented as scientific absence or as a positive/negative result.

Verification uses an expert-reviewed paper bundle, not a synthetic model-only
fixture. The bundle must check Source recall, measurement and comparison recall,
source-locator correctness, context compatibility, and conclusion direction;
the four-paper integration fixture is the minimum regression gate for review
paper separation and sample-state stratification.
