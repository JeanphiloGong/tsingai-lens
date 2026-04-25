# Core Text-Window Atomic Mentions Plan

## Summary

This document records a focused Core child implementation plan for replacing
the current text-window "one prompt emits the final bundle" extraction shape
with a narrower two-step design:

- the text-window LLM prompt emits observation-layer atomic mentions only
- deterministic backend code binds those mentions into the existing Core
  backbone artifacts

The immediate target is the text-window extraction slice in
`application/core/semantic_build/`. This is not a table-row redesign, not a
new compatibility layer, and not a second model-binding stage.

The narrow goal is to improve extraction precision where the current bundle
shape is still coupling too many jobs into one model response:

- methods, materials, variants, conditions, baselines, and results are still
  being extracted in one highly coupled pass
- the model still emits `anchors` even though anchor locator recovery already
  belongs to the backend
- prior-work or literature-summary claims can still contaminate
  `measurement_results`
- characterization methods can still be mistaken for `test_conditions`
- baselines can still be invented from treatment presence rather than explicit
  comparator language

This plan works under the existing Core extraction wave and should be read
with:

- [`../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/id-boundary.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/id-boundary.md)
- [`pbf-metal-extraction-and-comparison-validation/README.md`](pbf-metal-extraction-and-comparison-validation/README.md)

## Why This Child Plan Exists

The current text-window path still asks one schema-bound prompt to do too much
in one pass. The model is expected to emit final-domain objects such as:

- `method_facts`
- `sample_variants`
- `test_conditions`
- `baseline_references`
- `measurement_results`

That shape is brittle because some of those outputs are direct observations and
some are binding products that depend on other fields already being right.

In practice, that creates five recurring failure modes:

1. one window tries to do extraction, normalization, relation binding, and
   evidence packaging all at once
2. result objects can absorb background numbers such as prior-work summary
   percentages
3. characterization methods are easy to over-promote into test-condition
   payloads
4. baseline fields are easy to over-fill from implied control logic that the
   paper did not state explicitly
5. the model is still asked to emit `anchors` even though backend code already
   owns quote matching and locator reconstruction

The backend already contains the right permanent owner for the second half of
the job:

- anchor ids, locators, and `char_range` recovery are deterministic backend
  work
- result-to-variant, result-to-baseline, and result-to-condition linking is
  already handled locally
- final artifact materialization already happens in `paper_facts_service.py`

The missing change is to narrow what the text-window prompt is responsible for.

## Decision

The Core text-window extraction path should switch from final-bundle emission
to atomic mention extraction plus deterministic backend binding.

That means:

- the text-window LLM schema should emit observation-layer mentions rather than
  final paper-fact artifacts
- the model should emit exact `evidence_quote` values instead of `anchors`
- `claim_scope` should be explicit on every extracted result claim
- only `current_work` claims that are explicitly eligible should become
  `measurement_results`
- backend code should bind mentions into the existing Core artifact tables
  without adding a compatibility shim

This plan also fixes one naming decision for the backend:

- use the existing repo-level scope vocabulary
  `current_work | prior_work | literature_summary | review_summary | unclear`
  instead of introducing a second parallel enum such as `current_study`

This plan explicitly rejects:

- a new adapter between atomic mentions and the real Core artifacts
- a temporary dual-path text-window parser
- model-generated locators, ids, or backend-facing anchors
- moving table-row extraction into the same redesign wave by default
- introducing a second LLM stage before deterministic binding has been tried

## Scope

This plan covers:

- text-window LLM schema changes under
  `application/core/semantic_build/llm/schemas.py`
- text-window prompt changes under
  `application/core/semantic_build/llm/prompts.py`
- text-window parse entry changes under
  `application/core/semantic_build/llm/extractor.py`
- deterministic binding from atomic mentions into the existing Core artifact
  bundle inside `application/core/semantic_build/paper_facts_service.py`
- propagation of `claim_scope` into Core measurement-result materialization
- targeted fake-extractor and unit-test updates for the new text-window path

This plan does not cover:

- table-row schema redesign in the same change set
- replacing deterministic binding with a second model call
- renaming stored artifact filenames
- broad comparison-domain redesign beyond the minimum `claim_scope` gate
- doc-family reshaping for the existing Core structured-extraction plan lineage

## Target Shape

### Text-Window Model Output

The text-window prompt should return one observation-layer object with these
collections:

- `method_mentions`
- `material_mentions`
- `variant_mentions`
- `condition_mentions`
- `baseline_mentions`
- `result_claims`

The important boundary rule is that this stage records what the bounded text
window explicitly says, not the final database objects the backend hopes to
store.

### Evidence Boundary

The text-window model contract should stop emitting `anchors`.

Instead, each emitted mention or claim should carry one exact
`evidence_quote`, or multiple exact `evidence_quotes` if the field genuinely
needs more than one supporting span.

For text-window extraction, `evidence_quote` must satisfy all of these rules:

- copied exactly from `text_window.text`
- contiguous in the source text
- not paraphrased
- not shortened with ellipses
- not merged from multiple disjoint spans

The backend should remain the only owner of:

- `page`
- `source_type`
- `document_id`
- `section_id`
- `block_id`
- `snippet_id`
- `char_range`
- `bbox`
- `deep_link`

### Claim Scope And Result Eligibility

Every `result_claim` should carry:

- `claim_scope`
- `eligible_for_measurement_result`

The first extraction stage should classify claims into:

- `current_work`
- `prior_work`
- `literature_summary`
- `review_summary`
- `unclear`

Only `current_work` claims that remain explicitly eligible should become
`measurement_results` in the default backend path.

### Backend-Owned Binding

The backend should turn atomic mentions into the current stored artifacts:

- `method_facts`
- `sample_variants`
- `test_conditions`
- `baseline_references`
- `measurement_results`

Binding should follow narrow deterministic rules:

- bind only when the relation is explicit in the same evidence quote or is the
  single unambiguous local candidate
- do not invent baselines from treatment presence alone
- do not convert characterization methods into test conditions
- if relation binding is ambiguous, keep the field `null`

## Execution Slices

### Slice 1: Replace Text-Window Anchors With Exact Evidence Quotes

Update the text-window schema so the model emits exact evidence quotes instead
of `anchors`.

Primary changes:

- remove text-window `anchors` from the text-window LLM response model
- add exact `evidence_quote` fields to text-window mention and claim payloads
- update prompt rules so the model is told not to emit `anchors`
- keep local anchor materialization backend-owned by matching quotes back to
  the current text window

Expected file areas:

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/llm/prompts.py`
- `application/core/semantic_build/paper_facts_service.py`
- `tests/unit/services/test_paper_facts_services.py`
- `tests/support/fake_core_llm_extractor.py`

Acceptance:

- text-window prompts no longer ask the model for `anchors`
- quote matching still produces stored `evidence_anchors`
- traceback surfaces still recover `char_range` when the quote is found

### Slice 2: Introduce Observation-Layer Text-Window Mentions

Replace direct text-window final-bundle emission with an observation-layer
schema.

Primary changes:

- add a text-window mention schema with method, material, variant, condition,
  baseline, and result-claim collections
- keep the current final artifact names for stored Core tables
- make the prompt describe this stage as observation extraction rather than
  final object assembly
- require `claim_scope` on every result claim

Expected file areas:

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/llm/prompts.py`
- `application/core/semantic_build/llm/extractor.py`
- `tests/support/fake_core_llm_extractor.py`

Acceptance:

- text-window parse accepts only the new mention-level shape
- prompt examples no longer use `confidence: 0.0`
- prior-work result statements can be represented without becoming final
  `measurement_results`

### Slice 3: Bind Atomic Mentions Into Existing Core Artifacts

Add one deterministic backend binding pass that converts text-window mentions
into the current Core artifact bundle.

Primary changes:

- create a narrow backend helper inside `paper_facts_service.py` that binds the
  text-window mentions into the existing artifact payloads
- keep all binding backend-owned and local to the real materialization path
- avoid new wrapper classes or compatibility layers
- keep table-row extraction on the current path until it is handled in a later
  wave

Binding rules:

- `method_mentions` become `method_facts`
- `material_mentions` and `variant_mentions` are combined into
  `sample_variants` only when the relation is explicit or locally unique
- `condition_mentions` become `test_conditions` only when they describe a
  property-measurement environment, rate, temperature, duration, atmosphere,
  loading case, or comparison condition
- `baseline_mentions` become `baseline_references` only when comparator
  language is explicit
- `result_claims` become `measurement_results` only when they survive the
  scope gate and relation binding

Expected file areas:

- `application/core/semantic_build/paper_facts_service.py`
- `tests/unit/services/test_paper_facts_services.py`

Acceptance:

- text-window extraction no longer requires the model to emit final
  `measurement_results`
- variant, baseline, and condition fields are left empty rather than guessed
  when binding is ambiguous
- the current stored artifact filenames and read paths stay unchanged

### Slice 4: Carry Claim Scope Into Measurement Results And Comparison Gating

Preserve claim provenance after binding so downstream comparison logic can keep
background claims out of the default comparison substrate.

Primary changes:

- add `claim_scope` to the stored Core `measurement_results` record shape
- materialize the scope into the parquet output
- block non-`current_work` results from the default comparison path

Expected file areas:

- `domain/core/evidence_backbone.py`
- `application/core/semantic_build/paper_facts_service.py`
- `application/core/comparison_assembly.py`
- `tests/unit/services/test_paper_facts_services.py`

Acceptance:

- prior-work and literature-summary result claims no longer feed default
  comparison rows
- current-work claims keep the existing comparison flow when their other
  required context is present

### Slice 5: Leave Table-Row Redesign As A Follow-Up Wave

Do not merge text-window redesign and table-row redesign into one first pass.

The table-row path can stay on the current bundle shape in the first
implementation wave because:

- row cells already carry stronger local structure than text windows
- text-window failures are the current prompt-coupling hotspot
- splitting both paths at once would increase rollout risk and test churn

This follow-up should revisit:

- whether row extraction also moves from `anchors` to `evidence_quote`
- whether row extraction benefits from the same observation-layer schema
- whether any table-specific deterministic binder is needed

## Verification

When implementation begins, the minimum verification set should include:

- text-window quote matching still reconstructs stored evidence anchors
- prior-work claims do not become `measurement_results`
- characterization methods such as contour method or neutron diffraction do
  not become `test_conditions`
- treatment-only statements do not invent baselines without explicit
  comparator language
- locally ambiguous variant or baseline relations stay unbound

Targeted commands:

```bash
cd backend
uv run pytest tests/unit/services/test_paper_facts_services.py
```

If comparison gating changes in the same wave, add the smallest relevant
comparison test slice as well.

## File Areas

The first implementation wave should stay tightly scoped to:

- `backend/application/core/semantic_build/llm/schemas.py`
- `backend/application/core/semantic_build/llm/prompts.py`
- `backend/application/core/semantic_build/llm/extractor.py`
- `backend/application/core/semantic_build/paper_facts_service.py`
- `backend/domain/core/evidence_backbone.py`
- `backend/application/core/comparison_assembly.py` only if the
  `claim_scope` gate lands immediately
- `backend/tests/support/fake_core_llm_extractor.py`
- `backend/tests/unit/services/test_paper_facts_services.py`

## Related Docs

- [`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md)
  Parent Core quality wave
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
  Earlier Core extraction cutover plan
- [`../../../application/core/semantic_build/llm/docs/structured-extraction/id-boundary.md`](../../../application/core/semantic_build/llm/docs/structured-extraction/id-boundary.md)
  Prompt and schema boundary cleanup that this plan extends
- [`pbf-metal-extraction-and-comparison-validation/proposal.md`](pbf-metal-extraction-and-comparison-validation/proposal.md)
  Proposal page for the narrow PBF-metal validation wave that exposed the
  prompt-coupling and claim-scope problems more clearly
