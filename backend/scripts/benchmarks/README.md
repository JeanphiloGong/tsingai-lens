# Benchmark Scripts

This directory owns backend-local benchmark scripts for Core LLM connectivity,
single-unit extraction latency, and collection-level paper-facts extraction
cost.

These scripts should be the canonical repo-local benchmark entrypoints. They
should replace ad hoc date-folder probes that depend on brittle `../backend`
path assumptions or a fixed `backend/.env` location.

## Canonical Script Surface

- `llm_connectivity_probe.py`
  Minimal provider connectivity and small chat latency checks
- `text_window_probe.py`
  One prompt, one payload, multiple execution modes for comparing raw text,
  local validation, and provider-native structured parsing
- `paper_facts_collection_benchmark.py`
  Collection-level extraction cost benchmark with window-pruning and
  table-row accounting
- `_common.py`
  Shared runtime resolution, env-file precedence, JSON summary helpers, and
  response-text utilities used by the benchmark entrypoints

## Runtime Contract

Scripts in this directory should follow these rules:

- do not assume the caller's working directory
- do not assume a sibling `../backend` path
- accept explicit overrides for `--backend-root`, `--env-file`, `--base-url`,
  `--model`, and `--api-key`
- prefer CLI arguments over environment variables, and environment variables
  over optional env-file loading
- write machine-readable JSON summaries so before/after runs can be compared
  without reformatting shell output

## Current Text-Window Modes

`text_window_probe.py` currently exposes these modes:

- `connectivity`
  Minimal small-chat latency check
- `raw_text`
  `chat.completions.create` with the canonical text-window prompt, no local
  validation
- `raw_text_plus_validate`
  Same request as `raw_text`, followed by local
  `StructuredExtractionBundle.model_validate_json(...)`
- `provider_structured_parse`
  Same prompt path as `raw_text`, plus provider-native
  `beta.chat.completions.parse(...)` for diagnostic comparison

## Example Usage

```bash
cd backend
python scripts/benchmarks/llm_connectivity_probe.py --help
python scripts/benchmarks/text_window_probe.py --help
python scripts/benchmarks/paper_facts_collection_benchmark.py --help
```

## Boundary

Keep only benchmark and probe utilities here. Do not turn this directory into a
second generic scripts bucket for unrelated operational helpers.
