# P004 Multi-Experiment Gold Candidate

This fixture is a compact, source-grounded annotation for Shin et al.,
“Heat treatment effect on the microstructure, mechanical properties, and wear
behaviors of stainless steel 316L prepared via selective laser melting”
(`10.1016/j.msea.2021.140805`). It is intended to test the real research
responsibility that follows a confirmed Objective:

```text
review the paper -> separate paper-local experiment series
                 -> bind samples, tests, outcomes and sources
                 -> preserve unknowns and scope limits
                 -> permit a human/Agent revision
                 -> emit a conditional Finding or abstain honestly
```

The paper is deliberately useful as a stress case. It has a 3 x 3 SLM
parameter matrix, three post-processing arms (`as-SLM`, furnace HT and HIP), a
cold-rolled control, several outcomes, and tests that cover only selected
conditions. The fixture therefore contains three paper-local series:

1. `P004:X01` — process parameter matrix, density and pore/microstructure
   observations;
2. `P004:X02` — heat-treatment comparison at the explicitly inspected
   120 W / 100 mm/s stratum, including several outcomes sharing the same
   tensile, hardness, XRD and microstructure context;
3. `P004:X03` — selected-condition pin-on-disk wear tests. This series must
   not be projected onto every row of Table 2.

These are paper-local **measurement/comparison series** over one parent study,
not claims that the authors ran three independent builds. A sample can appear
in more than one series when the same specimen family is measured by different
methods. The parent-study and sample-reuse semantics are explicit in
`experiments.json`; this distinction is important when mapping the annotation
to a `PaperExperiment` aggregate or when an Agent revises a binding.

`sources.json` keeps short exact excerpts and semantic page/table/figure
locators. `experiments.json` is the paper-local experiment archive, not a
Finding. `relations.json` adds relation-level provenance and attribution
scope. `expected_disposition.json` states when a conditional Finding is
allowed and when the correct scientific output is abstention or a coverage
warning. `revisions.json` records a split correction from an intentionally
over-merged draft while requiring all source provenance to survive.

The post-process factor keeps the treatment arms explicit: furnace HT is
reported as 1100 °C for 0.5 h, while HIP is 1100 °C, 100 MPa for 1.5 h. The
fixture does not infer a shared "temperature effect" and leaves the complete
gas/cooling history unknown.

The prose/Table 3 disagreement for the selected elongation values is kept as
one experiment-local conflict (`E021` and `M016`–`M018`). It does **not** create
three experiments: a source disagreement changes the measurement status and
the confidence of the Finding, while an experiment boundary changes only when
the sample, intervention, or test context is genuinely different.

The annotation is a **gold candidate**, not a substitute for final domain
expert sign-off. In particular, the exact replicate type is left unknown when
the paper only says that measurements were repeated and averaged. The source
PDF is not committed; use the SHA-256 in `manifest.json` and the local expert
gold directory described by `backend/tests/fixtures/README.md` for full replay.
The coverage ledger counts the 19 tracked source excerpts plus one referenced
but uninspected supplementary-material route (`S1`–`S4`).

## Mapping To The Domain Aggregate

This sidecar is deliberately a review-friendly gold format rather than a
runtime `PaperExperiment.to_record()` payload. The intended mapping is direct:

| Gold field | `PaperExperiment` concept |
| --- | --- |
| `series_id` | candidate `experiment_id` for one paper-local series |
| `source_ids` / relation `source_refs` | `source_observation_ids` and field/relation provenance |
| `samples` | `sample_variants` |
| `conditions` | `test_conditions` |
| `measurements` and `observations` | `measurements` plus source-grounded observations |
| `unknown_fields`, conflicts and coverage | `uncertainties` and an incomplete/partial status |
| `status` and expected disposition | bound/incomplete plus downstream Finding or abstention |

The fixture intentionally does not invent runtime `collection_id` or
`document_id` values. Those are supplied by the ingestion snapshot at replay
time; the DOI, PDF hash, snapshot IDs and semantic locators provide the stable
source identity.

The following remain explicitly unknown rather than filled from convention:
independent build-replicate count, specimen orientation, heat-treatment
ramp/pressure path, Archimedes medium and threshold details, the meaning of
reported error bars, wear run-in geometry, and raw/processed data (the paper
states that they are unavailable).

Validate it with:

```bash
cd backend
.venv/bin/python scripts/evaluation/expert_gold/validate_multi_experiment_gold.py \
  --input tests/fixtures/expert_gold/p004_multi_experiment --json
```
