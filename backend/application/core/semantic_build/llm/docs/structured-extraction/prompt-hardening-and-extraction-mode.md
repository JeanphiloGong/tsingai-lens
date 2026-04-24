# Core LLM Prompt Hardening And Extraction Mode Plan

## Summary

This document records a focused Core child implementation plan for stabilizing
production LLM extraction after the benchmark-script cutover.

The immediate target is narrow:

- move the benchmark-proven JSON compliance guidance into the production Core
  extraction prompts
- keep one Core extractor while allowing one temporary provider-mode switch
  between text JSON validation and provider-native structured parsing
- measure both modes through the same prompt, payload, and schema path before
  making a permanent cutover decision

This is a Core child plan under the active parsing-quality wave. It does not
introduce a new runtime layer and it does not justify two parallel extractor
implementations.

For the parent quality wave, read
[`../../../../../../docs/plans/core/core-parsing-quality-hardening-plan.md`](../../../../../../docs/plans/core/core-parsing-quality-hardening-plan.md).
For the earlier structured-extraction cutover direction, read
[`hard-cutover.md`](hard-cutover.md).
For the canonical benchmark surface used to justify this wave, read
[`../../../../../../docs/plans/core/core-benchmark-script-consolidation-plan.md`](../../../../../../docs/plans/core/core-benchmark-script-consolidation-plan.md).

## Why This Child Plan Exists

The new benchmark surface made one production problem explicit:

the current provider is reachable and fast enough for single-call work, but the
production prompt and response contract still allow too many schema-invalid
outputs to reach `StructuredExtractionBundle.model_validate_json(...)`.

The benchmark evidence collected on April 24, 2026 showed:

- provider connectivity stayed normal at sub-second latency
- the same text-window payload returned in about 8.66 seconds in plain
  `raw_text` mode
- the same payload returned in about 43.64 seconds in
  `provider_structured_parse` mode
- the original `raw_text_plus_validate` benchmark failed on schema-invalid
  shapes such as:
  - list fields returned as `null`
  - required nested objects returned as `null`
  - extra top-level keys such as `keywords`
  - misplaced `unit` fields inside `value_payload`

After adding explicit JSON compliance rules and positive and negative examples
to the benchmark prompt, the same sample text window improved materially:

- `raw_text_plus_validate` passed in about 6.69 seconds
- `provider_structured_parse` still passed in about 39.26 seconds

That result is strong enough to justify a production child wave focused on
prompt hardening first, with a tightly bounded temporary mode switch for
measuring the production tradeoff.

## Decision

Production Core extraction should keep one extractor implementation and one
shared prompt path, but allow one temporary extraction-mode switch through an
environment variable.

The mode switch should be narrow:

- one extractor class
- one prompt builder family
- one payload shape
- one response schema
- one branch point inside the Core extractor response path

The temporary mode values should be:

- `json_text`
- `provider_parse`

The default should remain `json_text` until production collection benchmarks
show that `provider_parse` is worth the latency cost.

This plan explicitly rejects:

- a second extractor service or client layer
- separate prompt families for different modes
- compatibility wrappers around the current Core extractor
- silently relaxing the production schema just to accept bad shapes

## Scope

This child plan covers:

- production prompt hardening for text-window and table-row extraction
- one environment-variable switch for the two extraction modes
- targeted extractor logging so mode-specific failures are attributable
- unit tests for the production prompt and extractor mode branch
- production benchmark reruns against one real collection after the change

This child plan does not cover:

- changing the public API
- changing Source structural artifacts
- adding a second production extraction service
- committing to provider-native structured parsing as the permanent default
- broad schema redesign

## Proposed Change

### Shared Prompt Hardening

Move the benchmark-proven JSON compliance guidance into
`application/core/semantic_build/llm/prompts.py` for:

- `build_text_window_extraction_prompt(...)`
- `build_table_row_extraction_prompt(...)`

The production prompt guidance should explicitly state:

- output must use exactly the schema keys and no extras
- array fields must stay arrays and use `[]` when empty
- required nested objects must stay objects and must not be `null`
- `unit` belongs at `measurement_results[*].unit`
- uncertainty should resolve to empty arrays and null scalar leaves, not to
  invalid object shapes

The production prompt should also include:

- one short valid example
- two or three short invalid counterexamples that mirror the real observed
  failure patterns

### One Extractor, Two Temporary Modes

Keep `CoreLLMStructuredExtractor` as the single production extractor in
`application/core/semantic_build/llm/extractor.py`.

Add one environment variable:

- `CORE_LLM_EXTRACTION_MODE`

Supported values:

- `json_text`
  - call `chat.completions.create(...)`
  - coerce message content into text
  - extract the JSON object
  - validate locally with `model_validate_json(...)`
- `provider_parse`
  - call `beta.chat.completions.parse(...)`
  - parse against the same response model
  - keep the same prompt, payload, and schema contract

The branch should live only inside the internal response-parsing path. Callers
such as `extract_text_window_bundle(...)` and `extract_table_row_bundle(...)`
should stay unchanged.

### Mode Invariants

The two temporary modes are valid only if they share the same:

- system prompt
- user prompt
- payload
- response model
- model name
- temperature

This plan should not allow mode-specific prompt drift.

### Logging And Attribution

The production extractor should log enough detail to compare the modes on real
collections:

- extraction mode
- model name
- response model
- elapsed seconds
- validation failure marker

That logging should stay at the extractor seam rather than being duplicated in
multiple callers.

## Execution Order

1. Move the JSON compliance guidance into production prompt builders.
2. Add the mode switch to the Core extractor with `json_text` as the default.
3. Add targeted unit coverage for the prompt content and extractor mode
   selection.
4. Rerun the canonical text-window benchmarks against both modes.
5. Rerun the collection benchmark against one real collection with both modes.
6. Decide whether prompt hardening alone is sufficient or whether one smaller
   follow-on sanitation wave is still needed.

## File Change Plan

### Primary Code Areas

- `application/core/semantic_build/llm/prompts.py`
- `application/core/semantic_build/llm/extractor.py`

### Primary Test Areas

- `tests/unit/services/test_core_llm_extractor.py`
- one new prompt-focused test file if that keeps prompt assertions clearer than
  extending the extractor test file

### Possible Companion Updates

- `.env.example` if the new environment variable is adopted
- `docs/runbooks/backend-ops.md` if the mode switch becomes an operator-facing
  runtime control

## Verification

### Focused Verification

Run at least:

```bash
cd backend
python3 -m py_compile application/core/semantic_build/llm/prompts.py application/core/semantic_build/llm/extractor.py
uv run pytest tests/unit/services/test_core_llm_extractor.py
python3 scripts/benchmarks/text_window_probe.py --mode raw_text_plus_validate --repeat 3
python3 scripts/benchmarks/text_window_probe.py --mode provider_structured_parse --repeat 3
```

### Collection Verification

Run the same real collection under both modes:

```bash
cd backend
CORE_LLM_EXTRACTION_MODE=json_text uv run python scripts/benchmarks/paper_facts_collection_benchmark.py --collection-id <collection_id>
CORE_LLM_EXTRACTION_MODE=provider_parse uv run python scripts/benchmarks/paper_facts_collection_benchmark.py --collection-id <collection_id>
```

Compare:

- success versus failure rate
- per-unit timing
- whole-collection timing
- failure taxonomy

## Deferred Fallback

If prompt hardening alone still leaves frequent schema-invalid responses on the
collection benchmark, the follow-on wave should be a very thin deterministic
sanitizer before local validation.

That fallback should remain bounded to mechanical repair only:

- `null` list fields to `[]`
- `null` required objects to empty default objects
- removal of known extra top-level fields
- relocation of misplaced `value_payload.unit` to outer `unit`

That sanitizer should be recorded and delivered as a separate wave so prompt
hardening and deterministic repair are measured independently.

## Exit Criteria

This child plan is done only when:

- production prompt builders include the JSON compliance guidance
- `CORE_LLM_EXTRACTION_MODE` switches the production extractor between the two
  temporary paths without changing callers
- the default mode remains explicit and documented
- production benchmark reruns can compare the two modes on the same collection
- the backend has enough evidence to decide whether the dual-mode period
  should continue or be closed
