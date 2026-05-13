# Objective Extraction Quality Benchmark Plan

## Summary

The objective-first extraction path should be judged against the local expert
gold set, not only against single-run probe counts.

The benchmark flow is:

```text
expert CSV/PDF gold set
-> gold bundle
-> already-built collection SQLite records
-> objective-first prediction bundle
-> gold-vs-prediction evaluation report
-> categorized repair work
```

This plan is the acceptance frame for the next extraction-quality iterations.
It does not restore the old paper-fact-to-objective compatibility path.
`ObjectiveEvidenceUnit` and `ObjectiveLogicChain` remain the authoritative
objective-first Core records.

## Benchmark Commands

Run the objective-first benchmark for an existing collection:

```bash
cd backend
./.venv/bin/python scripts/evaluation/expert_gold/run_objective_gold_benchmark.py \
  --collection-id <collection_id>
```

Run only P001:

```bash
cd backend
./.venv/bin/python scripts/evaluation/expert_gold/run_objective_gold_benchmark.py \
  --collection-id <collection_id> \
  --gold-paper-id P001
```

The default generated outputs are under:

```text
backend/tests/fixtures/local_expert_gold/generated/objective_first/
```

These generated bundles and reports are local evaluation artifacts and should
not be committed.

## Success Criteria

### P001 Hard Gate

P001 should be the first parity gate because it has already exposed the main
table, route, unit, and logic-chain failure modes.

The objective-first path should produce gold-aligned evidence for:

- 80 table-backed measurement results
- 3 method-family test conditions
- 8 characterization observations
- 19 sample-pair comparison relations

Every projected row should trace back to objective evidence-unit source
references or evidence anchors.

### Full Gold Set Diagnostic Gate

The P001-P006 run should produce an evaluation report that shows, per paper:

- paper mapping status
- sample recall
- measurement recall and precision
- test-condition family coverage
- comparison recall and precision
- observation coverage
- missing and extra prediction summaries

The first full run does not need to be green. It must be diagnosable enough to
decide whether the highest-impact gap is in Source parsing, objective
discovery, routing, evidence-unit extraction, resolution, or prediction-bundle
projection.

## Repair Loop

Each extraction-quality repair should follow this order:

1. Run the benchmark and capture the current gap.
2. Pick one gap class.
3. Add a focused unit test for the deterministic behavior where possible.
4. Change the owning objective-first implementation directly.
5. Re-run the benchmark and confirm the gap shrank without regressing P001.

Real LLM benchmark runs stay out of normal unit tests. Deterministic exporters,
projection helpers, gap classifiers, and objective service helpers should have
unit coverage.

## Boundaries

- Always: keep objective evidence units and logic chains as the authoritative
  objective-first records.
- Always: keep generated benchmark artifacts out of committed source.
- Ask first: changing public backend APIs, SQLite schema, or frontend
  navigation.
- Never: reintroduce a production path that rebuilds objective units from old
  paper-fact families.
