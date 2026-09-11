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
```

## Boundary

Keep only benchmark and probe utilities here. Do not turn this directory into a
second generic scripts bucket for unrelated operational helpers.
