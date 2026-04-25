# Core Benchmark Script Consolidation Plan

## Summary

This plan consolidates Core extraction benchmark work into repo-owned backend
scripts instead of ad hoc date-folder probes.

The immediate goal is not new extraction behavior. It is a stable benchmark
surface that can measure the current Core path without path-sensitive imports,
hard-coded env-file assumptions, or mode drift between scripts.

## Why This Wave Exists

Current benchmark scripts are useful for diagnosis, but they are not durable
enough to support repeatable before-and-after comparisons.

The current problems are structural:

- some scripts assume a sibling `../backend` path and fail outside one local
  directory layout
- some scripts default to loading one fixed `backend/.env` path and fail even
  when explicit runtime inputs are available
- raw text, local parse, and provider-native structured parsing are currently
  measured by different script implementations rather than one controlled
  benchmark surface
- collection-level extraction cost is still harder to compare than single-call
  latency

## Target Outcome

The backend should own one canonical benchmark directory:

- `scripts/benchmarks/`

That directory should expose three stable benchmark entrypoints:

- `llm_connectivity_probe.py`
- `text_window_probe.py`
- `paper_facts_collection_benchmark.py`

Together they should answer four distinct questions:

1. is the provider reachable and responsive at all
2. how long does one raw text response take for the exact prompt and payload
3. how much extra time comes from local JSON validation
4. how much extra time comes from provider-native structured parsing compared
   with the current Core path

## Benchmark Modes

The text-window benchmark should support one fixed payload and prompt path with
multiple execution modes:

- `connectivity`
  Minimal health and small chat-completion timing
- `raw_text`
  Plain `chat.completions.create` timing with raw text capture only
- `raw_text_plus_validate`
  Same request as `raw_text`, plus local `model_validate_json`
- `provider_structured_parse`
  Provider-native structured parsing kept only as a diagnostic baseline

The benchmark is valid only if these modes share the same:

- payload
- system prompt
- user prompt
- model
- base URL
- temperature
- token budget

## Runtime Contract

All benchmark scripts in this wave should use the same runtime rules:

- no implicit `../backend` import assumptions
- no required fixed `backend/.env` lookup
- support explicit CLI overrides for:
  - `--backend-root`
  - `--env-file`
  - `--base-url`
  - `--model`
  - `--api-key`
- resolve runtime inputs in this precedence order:
  - CLI argument
  - environment variable
  - optional env-file
  - bounded default only where safe

## Script Responsibilities

### `llm_connectivity_probe.py`

Own only provider connectivity and small chat latency.

It should not import backend application modules.

It should report:

- resolved model
- resolved base URL
- models-list timing when enabled
- minimal chat timing when enabled

### `text_window_probe.py`

Own one-payload prompt benchmarking for Core extraction prompts.

It should support:

- built-in sample payloads
- explicit `--payload-file`
- exact prompt echoing for debug work
- comparable output across all benchmark modes

It should report:

- selected mode
- prompt and payload metadata
- run count
- per-run elapsed time
- p50, p95, min, max, and average timing
- optional raw response capture path

### `paper_facts_collection_benchmark.py`

Own collection-level extraction cost measurement.

It should use the real Core build path so it can expose where time is spent.

It should report:

- document count
- raw text-window count
- selected text-window count
- raw table-row count
- selected table-row count
- per-unit timing aggregates
- whole-document and whole-collection elapsed time

## Delivery Slices

### Slice 1: Directory And Shared Runtime Contract

Create `scripts/benchmarks/` and define the shared runtime and output rules.

Owned file areas:

- `scripts/benchmarks/README.md`
- `scripts/benchmarks/_common.py` only if shared runtime parsing is needed by
  more than one script

Exit criteria:

- benchmark entrypoints no longer depend on a caller-specific directory layout
- explicit runtime overrides work without a fixed local env-file

### Slice 2: Connectivity Probe Cutover

Replace the current one-off connectivity benchmark with a repo-owned script.

Owned file areas:

- `scripts/benchmarks/llm_connectivity_probe.py`

Exit criteria:

- a user can benchmark provider connectivity from any working directory with
  explicit runtime inputs

### Slice 3: Text-Window Mode Unification

Replace separate raw/parse probes with one canonical text-window benchmark.

Owned file areas:

- `scripts/benchmarks/text_window_probe.py`

Exit criteria:

- `raw_text`, `raw_text_plus_validate`, and `provider_structured_parse` share
  one prompt and payload path
- timing deltas can be interpreted as mode cost rather than script drift

### Slice 4: Collection Benchmark Cutover

Create a collection benchmark that uses the actual Core extraction path.

Owned file areas:

- `scripts/benchmarks/paper_facts_collection_benchmark.py`

Exit criteria:

- the benchmark can show extraction unit counts and end-to-end document timing
  on one real collection

### Slice 5: External Probe Deprecation

Deprecate the date-folder scripts once the repo-owned scripts produce matching
or better diagnostic output.

Exit criteria:

- the repo has one canonical benchmark path
- operator guidance no longer points to the ad hoc local probes as the primary
  measurement surface

## Verification

This wave should verify both usability and measurement integrity.

Run checks like:

```bash
cd backend
python3 ../scripts/check_docs_governance.py
python scripts/benchmarks/llm_connectivity_probe.py --help
python scripts/benchmarks/text_window_probe.py --help
python scripts/benchmarks/paper_facts_collection_benchmark.py --help
```

Manual acceptance should confirm:

- the same payload can be benchmarked in `raw_text`,
  `raw_text_plus_validate`, and `provider_structured_parse`
- explicit `--base-url --model --api-key` inputs are enough to run the scripts
  without `backend/.env`
- collection-level benchmarks expose selected-versus-raw extraction-unit counts

## Non-Goals

Do not use this wave to:

- redesign Core extraction semantics
- add a second production extraction path
- keep adding one-off benchmark files outside the repository
- broaden `scripts/benchmarks/` into a generic operations directory

## Acceptance Standard

This wave is done only when:

- repo-owned benchmark scripts exist under `scripts/benchmarks/`
- text-window benchmarking can compare raw text, local validation, and
  provider-native structured parsing under one shared prompt path
- collection-level extraction cost can be measured without hand-editing local
  script paths
- operator guidance points to the repo-owned scripts as the canonical benchmark
  surface
