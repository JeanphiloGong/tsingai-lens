# Benchmark Scripts

This directory owns backend-local benchmark scripts for Core LLM connectivity,
Paper Map prompts, Source parsing, and Source retrieval.

These scripts should be the canonical repo-local benchmark entrypoints. They
should replace ad hoc date-folder probes that depend on brittle `../backend`
path assumptions or a fixed `backend/.env` location.

## Canonical Script Surface

- `llm_connectivity_probe.py`
  Minimal provider connectivity and small chat latency checks
- `paper_map_prompt_probe.py`
  Offline token audit and optional live scientific-boundary A/B matrix for the
  current Paper Map prompt in JSON fallback and provider-native modes, compact
  JSON-object guidance, and compact provider-native structured parsing. Use
  `--scenario-file` to replay real Source payloads without adding production
  artifacts or paper text to the repository.
- `objective_question_probe.py`
  Offline input audit and opt-in live comparison of existing Objective discovery
  with the Core candidate service's context-based question proposals. Retains
  paper-specific reading scope, backend-bound original excerpts and model traces,
  without creating Objectives or running analysis. It does not invoke Agent
  tools or treat their exact-axis matcher as a reading-relevance check.
- `source_parser_benchmark.py`
  Offline Source parser benchmark for the active Docling path and optional
  MinerU CLI comparison without changing production parser behavior
- `_common.py`
  Shared runtime resolution, env-file precedence, JSON summary helpers, and
  response-text utilities used by the benchmark entrypoints

## Runtime Contract

Scripts in this directory should follow these rules:

- do not assume the caller's working directory
- do not assume a sibling `../backend` path
- accept explicit overrides for `--backend-root`
- LLM-backed scripts should also accept explicit overrides for `--env-file`,
  `--base-url`, `--model`, and `--api-key`
- prefer CLI arguments over environment variables, and environment variables
  over optional env-file loading
- write machine-readable JSON summaries so before/after runs can be compared
  without reformatting shell output

## Example Usage

```bash
cd backend
python scripts/benchmarks/llm_connectivity_probe.py --help
python scripts/benchmarks/paper_map_prompt_probe.py --execution offline
python scripts/benchmarks/paper_map_prompt_probe.py --execution both --repeat 1
python scripts/benchmarks/paper_map_prompt_probe.py \
  --execution both \
  --scenario-file /tmp/paper-map-scenarios.json \
  --variant current_provider_parse \
  --variant compact_provider_parse
python scripts/benchmarks/source_parser_benchmark.py --help
python scripts/benchmarks/objective_question_probe.py \
  --scenario-file /path/to/local/scenarios.json \
  --execution live --repeat 2 --output /path/to/local/results.json
python scripts/benchmarks/objective_question_probe.py \
  --scenario-file /path/to/local/scenarios.json \
  --scenario-id selected-case --ignore-interest \
  --execution live --repeat 1 --output /path/to/local/automatic-results.json
```

Question-probe scenario files contain `scenarios`, each with `scenario_id`,
`interest`, and `papers`. Each paper supplies `document_id`, `title`, `map_origin`,
a serialized `PaperResearchMap`, and `excerpts` with `source_ref` and `text`.
Alternatively, an excerpt can name a local PDF, one-based `page`, and exact
`start`/`end` markers; this requires `pdftotext`. Relative PDF paths resolve
against the scenario file. These locators are probe references, not newly
persisted canonical Sources. Optional `expectation` metadata stays out of model
input. `--ignore-interest` evaluates automatic exploration with no user interest;
interest-specific expectations then need human interpretation. Version 3 invokes
the owning Core implementation, replacing the former standalone prompt and
Agent draft check. Reference checks establish original text binding only, not
whether a scientific interpretation is correct. The baseline sees maps only,
while the proposal method also reads original excerpts; this is not an
equal-input algorithm comparison. Supplied map snapshots also mean the probe does not
measure upstream parsing or Paper Map extraction quality. Keep real paper text
and local reports under ignored `tests/fixtures/local_expert_gold/` or outside
the repository.

## Boundary

Keep only benchmark and probe utilities here. Do not turn this directory into a
second generic scripts bucket for unrelated operational helpers.
