# Source Text-Unit Retrieval Decision

## Status

Accepted: stop.

## Date

2026-07-20

## Issue

GitHub issue [#243](https://github.com/JeanphiloGong/tsingai-lens/issues/243).

## Context

Lens may add a rebuildable `pgvector` index only when measured Source
text-unit retrieval quality justifies the extra persistence and runtime path.
PostgreSQL Source records remain the evidence authority regardless of this
decision.

The benchmark used the reviewed LPBF 316L fixture, all six document filters,
and the active build of collection `col_a39df172e56f`:

- 989 canonical Source text units
- four evidence-retrieval questions
- top-10 recall and traceability for both methods
- TF-IDF keyword ranking
- `sentence-transformers/all-MiniLM-L6-v2` embedding ranking

The configured remote embedding endpoint was unavailable because its account
balance was insufficient. The measured embedding run therefore used the same
OpenAI-compatible script contract against a temporary local endpoint backed by
the already cached MiniLM model. No local endpoint or benchmark output is a
runtime dependency or persistence authority.

## Results

| Method | Mean recall@10 | Mean traceability@10 |
|---|---:|---:|
| TF-IDF | 0.625 | 1.000 |
| MiniLM embedding | 0.500 | 1.000 |

Per-query recall@10:

| Query | TF-IDF | Embedding |
|---|---:|---:|
| controlled scan-speed effect | 1.0 | 1.0 |
| scan-strategy densification | 1.0 | 0.0 |
| constant-energy-density porosity | 0.0 | 0.0 |
| VED defect density | 0.5 | 1.0 |

The accepted vector-usefulness threshold is recall@10 of at least 0.90. Neither
method reached it, and embedding retrieval did not outperform the keyword
baseline.

## Manual Review

All 80 presented candidates resolved to a canonical text-unit ID, document ID,
block ID, and page locator.

- For the controlled scan-speed question, the direct evidence ranked first for
  TF-IDF and second for embedding. Other candidates discussed related process
  parameters but did not answer the controlled causal question.
- For scan-strategy densification, TF-IDF found the direct conclusion at rank
  four. Embedding missed it and prioritized figure captions and nearby
  microstructure passages.
- Both methods missed the two gold passages for the constant-energy-density
  question. Their candidates discussed energy density generally or reported
  different experiments without the requested three density values and
  conclusion.
- For VED defect density, embedding placed both direct passages at ranks one
  and two. TF-IDF found the density passage only at rank ten and missed the
  lack-of-fusion conclusion.

The false positives are mostly titles, figure captions, background citations,
or topically related passages without the requested answer. The misses show
that text-unit-only ranking is not yet reliable for multi-part and
cross-passage evidence questions.

## Recommendation

Record `stop` for the pgvector implementation. The current evidence does not
justify a vector schema, dependency, indexing lifecycle, or runtime retrieval
service. Improving the query decomposition or Source text-unit representation
should be evaluated separately before repeating this gate.

## Human Decision

`stop`: the human operator chose not to implement pgvector. The conditional
pgvector slice is skipped, and PostgreSQL Source records remain the only
retrieval evidence authority.

`proceed` is valid only after an accepted benchmark reaches recall@10 of at
least 0.90. `stop` keeps the current PostgreSQL Source authority and adds no
vector runtime or dependency.

## Reproduction

From `backend/`, with `LENS_DATABASE_URL` and an OpenAI-compatible embedding
endpoint configured:

```bash
.venv/bin/python scripts/benchmarks/source_text_unit_retrieval.py \
  --collection-id col_a39df172e56f \
  --fixture tests/fixtures/source_text_unit_retrieval/lpbf_316l.json \
  --k 10 \
  --output /tmp/lens-source-text-unit-retrieval.json
```

The JSON output must retain `decision_status=awaiting_human_decision`; the CLI
does not make the architecture decision.
