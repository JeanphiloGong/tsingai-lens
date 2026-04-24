# PBF-Metal Extraction And Comparison Validation Proposal

## Summary

This document records the next Core child execution wave for validating the
Lens comparison backbone on a narrow PBF-metal corpus while reducing the
current extraction latency and semantic drift.

The target loop for this wave is:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection`

The goal is not to add another architecture layer.

The goal is to make the current Core backbone fast enough, narrow enough, and
domain-specific enough to support trustworthy PBF-metal comparison work.

This child plan belongs to the Core plan family because the owned work is
primarily:

- Core fact extraction behavior
- Core comparison-semantic assembly
- Core comparability policy
- Core evaluation and regression coverage

It does include a small shared-doc cleanup so the repository stops presenting
multiple competing semantic backbones, but that documentation alignment is a
companion update rather than the main owning scope.

Read this plan after:

- [`README.md`](README.md)
- [`implementation-plan.md`](implementation-plan.md)
- [`../core-parsing-quality-hardening-plan.md`](../core-parsing-quality-hardening-plan.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
- [`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
- [`../../backend-wide/materials-comparison-v2-plan.md`](../../backend-wide/materials-comparison-v2-plan.md)

## Why This Wave Exists

The current backend direction is broadly correct:

- `paper_facts` has replaced claim cards as the primary research object layer
- `comparable_results` and `collection_comparable_results` now carry the
  comparison-semantic truth
- `comparison_rows` is already a projection rather than the semantic source of
  truth

But the current runtime still has three concrete problems.

### The repository still describes more than one semantic center

Current backend and shared docs still mix old and new language:

- older pages still describe the backbone as
  `document_profiles -> evidence_cards -> comparison_rows`
- newer pages describe the implemented backbone as
  `document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection`

That mismatch makes it harder to extend the right objects and easier to
reintroduce row-first or card-first logic by accident.

### The current extraction path is too slow for real collections

Recent runtime and standalone probe work showed that the main bottleneck is
not PDF parsing and not local row projection.

The main bottleneck is the current serial Core extraction path:

- one 2 MB collection input spent hours in `paper_facts` extraction
- the slow path was `221` serial structured LLM calls over text windows and
  table rows
- observed structured-output calls were often tens of seconds each
- the same prompt shape without provider-native strict structured output was
  materially faster in standalone probes

This means the next wave should reduce unnecessary extraction units and stop
depending on provider-side strict structured-output enforcement for every Core
call.

### The current schema is still too generic for the target PBF-metal job

The current `paper_facts` family is more realistic than a claim-card-only
backbone, but the active target job is not generic materials summarization.

The near-term user job is PBF-metal comparison:

- process parameters
- post-processing history
- test conditions
- baseline relationships
- property outcomes
- evidence-backed comparability limits

Without explicit support for those PBF-specific facts, the system falls back to
generic text payloads and weak normalization, which makes downstream
comparability judgments unstable.

## Decision

The next Core execution wave should do four things together rather than as
isolated follow-up tasks:

1. align repository language around one semantic center
2. reduce extraction cost before broadening the schema again
3. add a narrow PBF-metal semantic extension to the current Core fact objects
4. validate the end-to-end comparison loop on a small gold corpus

This plan rejects three common failure modes:

- continuing to expand generic schema breadth without narrowing the target
  vertical
- keeping provider-native strict structured output on every extraction call
  just because the backend model is structured
- continuing to tune comparison quality only by anecdote instead of a fixed
  benchmark corpus

## Target Outcome

At the end of this wave, the backend should support one reviewable and
measurable workflow:

1. upload about 30 PBF-metal papers
2. extract `paper_facts`
3. assemble `comparable_results`
4. assess collection overlays
5. project comparison rows
6. inspect each result through anchors back to source text or tables

That workflow should answer five practical questions for the researcher:

- which results are comparable
- why some results are only limited or insufficient
- which parameters are missing
- which studies are closest to the target process window
- where the evidence lives in the source paper

## Scope

This child plan covers:

- semantic-center wording alignment across backend and shared docs
- candidate pruning for Core fact extraction units
- table-first and result-first extraction narrowing for PBF-metal papers
- replacing provider-native strict structured output with local schema
  validation over JSON text responses
- bounded extraction concurrency before deterministic Core materialization
- a PBF-metal vertical payload extension inside existing Core fact objects
- `claim_scope` and `value_origin` support in Core facts and comparison
  semantics
- PBF-specific normalization and comparability rules
- a 30-paper PBF-metal gold corpus and repeatable benchmark checks

This child plan does not cover:

- a new `materials` subdomain package in the first implementation wave
- graph, report, or protocol surface redesign
- frontend IA or review-workflow redesign
- image-native figure understanding
- a repository-wide documentation refactor beyond the minimum semantic-center
  alignment needed by this wave

## Semantic Center To Preserve

The semantic order for this wave should be treated as fixed:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> comparison_rows / evidence_cards / graph / report projections`

Within that order:

- `paper_facts` remains the primary research object layer
- `comparable_results` remains the reusable result-semantic layer
- `collection_comparable_results` remains the collection-scoped assessment
  layer
- `comparison_rows` remains a projection or cache
- `evidence_cards` remains a reader-facing and traceback-facing projection

No new implementation in this wave should treat `comparison_rows` or
`evidence_cards` as the only semantic source of truth.

## Workstream 1: Align Repository Language

### Goal

Make the repository describe one semantic backbone consistently enough that the
next implementation wave extends the right objects.

### Primary changes

- update shared and backend docs that still present
  `document_profiles -> evidence_cards -> comparison_rows` as the core
  backbone
- make `evidence_cards` explicitly reader-facing and traceback-facing
- make `comparison_rows` explicitly projection or cache semantics
- keep `comparable_results` and `collection_comparable_results` as the
  comparison-semantic truth in backend-local docs and API docs

### Expected file areas

- `README.md`
- `docs/contracts/lens-v1-definition.md`
- `docs/contracts/lens-core-artifact-contracts.md`
- `backend/docs/architecture/overview.md`
- `backend/docs/architecture/core-comparison/current-state.md`
- `backend/docs/specs/api.md`

### Exit criteria

- the repository no longer advertises multiple competing semantic backbones
- new backend work can reference one authoritative semantic order

## Workstream 2: Reduce Extraction Cost Before Adding More Schema

### Goal

Reduce Core extraction time by shrinking the number of LLM calls and removing
provider-side structured-output overhead where it is not buying enough value.

### Current implementation pressure point

The current extraction loop sends one LLM request per text window and one per
table row, then materializes each returned bundle:

- text-window extraction loop in
  `application/core/semantic_build/paper_facts_service.py`
- table-row extraction loop in the same module
- extraction payloads built from `_build_text_window_extraction_payload()` and
  `_build_table_row_extraction_payload()`

### Primary changes

- add deterministic candidate pruning before any LLM call
- skip obviously low-value blocks such as references, acknowledgements, and
  most introduction-only history blocks
- move to a table-first, result-first extraction policy for PBF-metal papers
- keep text windows as supporting context rather than the primary parameter
  source
- replace provider-native strict structured-output calls with JSON-text output
  plus local schema validation
- run extraction calls with bounded concurrency, then keep bundle
  materialization deterministic and ordered

### Expected file areas

- `application/core/semantic_build/llm/extractor.py`
- `application/core/semantic_build/llm/prompts.py`
- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/paper_facts_service.py`
- `tests/support/fake_core_llm_extractor.py`
- `tests/unit/services/test_paper_facts_services.py`

### Exit criteria

- one representative PBF-metal document no longer triggers exhaustive
  low-value text-window extraction
- extraction unit count drops materially on the known slow collection
- one extraction call returns on a seconds-scale path rather than a
  tens-of-seconds structured-output path

## Workstream 3: Add A Narrow PBF-Metal Extension To Core Facts

### Goal

Support the real target comparison job without turning the generic Core
backbone into a one-vertical-only schema.

### Primary design rule

The first implementation wave should stay inside existing Core objects rather
than introducing a new material-specific package tree.

The narrow extension should use the current `domain_profile` seam plus
additional structured payload fields in owned Core fact objects.

### PBF-metal process parameters

The extension should explicitly support:

- `laser_power_w`
- `scan_speed_mm_s`
- `layer_thickness_um`
- `hatch_spacing_um`
- `spot_size_um`
- `energy_density_j_mm3`
- `scan_strategy`
- `build_orientation`
- `preheat_temperature_c`
- `shielding_gas`
- `oxygen_level_ppm`
- `powder_size_distribution_um`

### PBF-metal result properties

The extension should explicitly support normalized result/property identities
for:

- `relative_density_percent`
- `porosity_percent`
- `residual_stress_mpa`
- `yield_strength_mpa`
- `ultimate_tensile_strength_mpa`
- `elongation_percent`
- `hardness_hv`
- `surface_roughness_ra_um`

### Expected file areas

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/llm/prompts.py`
- `domain/core/evidence_backbone.py`
- `application/core/semantic_build/paper_facts_service.py`

### Exit criteria

- PBF-metal process parameters no longer collapse into generic free-text
  `details` payloads when strong evidence is present
- downstream comparison assembly can distinguish process context from result
  values using explicit fields

## Workstream 4: Add Claim Scope And Value Origin

### Goal

Stop prior-work text and derived values from silently entering the reusable
comparison substrate as if they were direct current-work results.

### Claim scope

At minimum, `measurement_results` should support:

- `current_work`
- `prior_work`
- `literature_summary`
- `review_summary`
- `unclear`

Only `current_work` should be eligible for `comparable_results` in the default
path.

### Value origin

At minimum, measurement values should support:

- `reported`
- `derived`
- `normalized`
- `inferred`

Supporting fields should also preserve:

- `source_value_text`
- `source_unit_text`
- `derivation_formula`

This is especially important for volumetric energy density so the backend can
distinguish:

- a value directly reported by the paper
- a value derived locally from power, speed, hatch spacing, and layer
  thickness

### Expected file areas

- `application/core/semantic_build/llm/schemas.py`
- `application/core/semantic_build/llm/prompts.py`
- `domain/core/evidence_backbone.py`
- `application/core/semantic_build/paper_facts_service.py`
- `application/core/comparison_assembly.py`
- `domain/core/comparison.py`

### Exit criteria

- prior-work and review-summary result statements no longer enter the default
  comparable-result substrate
- derived numeric facts are distinguishable from reported ones during review
  and assessment

## Workstream 5: Add Narrow PBF Comparability Rules

### Goal

Make comparability assessment more faithful to PBF-metal result review without
replacing expert judgment.

### Primary changes

Extend the current `evaluate_comparison_assessment()` logic so it can account
for PBF-specific missingness and result provenance.

The first rule set should include:

- `claim_scope != current_work` -> `not_comparable`
- missing `build_orientation` for orientation-sensitive properties ->
  `limited`
- missing baseline on an improvement-style claim -> `insufficient`
- derived energy density with missing source parameters -> `insufficient`
- missing test orientation for tensile or residual-stress style results ->
  `limited`
- direct review-summary facts stay outside the default comparable-result path

### Expected file areas

- `domain/core/comparison.py`
- `application/core/comparison_assembly.py`
- `application/core/comparison_projection.py` only if row-facing warnings need
  new projection fields
- `tests/unit/domains/test_comparison_domain.py`
- `tests/unit/services/test_paper_facts_services.py`

### Exit criteria

- `comparable`, `limited`, `insufficient`, and `not_comparable` outcomes track
  obvious PBF review constraints more closely
- warning text explains missing process or test context in domain-meaningful
  terms

## Workstream 6: Build A PBF-Metal Gold Corpus

### Goal

Stop tuning Core extraction and comparability rules purely from individual
manual examples.

### Initial corpus shape

The first gold corpus should use about 30 papers:

- 10 LPBF 316L papers
- 10 LPBF Ti-6Al-4V papers
- 10 LPBF AlSi10Mg or Inconel 718 papers

### Minimum annotation fields

- material system and alloy
- powder state or distribution when reported
- process parameters
- post-processing history
- target property, value, and unit
- baseline relationship
- test condition
- `claim_scope`
- `value_origin`
- source anchors
- final comparability status

### Expected file areas

- `tests/fixtures/` or another owned backend-local test-data subtree
- `tests/unit/services/test_paper_facts_services.py`
- `tests/unit/domains/test_comparison_domain.py`
- one backend-local benchmark or evaluation entry point if a stable harness is
  needed

### Exit criteria

- Core changes are measured against a fixed narrow-domain corpus
- regressions in `claim_scope`, process-parameter capture, and comparability
  status become repeatable

## Execution Order

1. Align repository semantic-center language in shared and backend docs.
2. Add candidate pruning and extraction narrowing before changing the vertical
   schema.
3. Replace provider-native strict structured output with JSON text plus local
   schema validation.
4. Add bounded extraction concurrency while keeping deterministic bundle
   materialization.
5. Extend Core facts with the narrow PBF-metal payloads.
6. Add `claim_scope` and `value_origin`, then gate comparable-result assembly
   on those fields.
7. Add narrow PBF comparability rules.
8. Freeze the 30-paper gold corpus and benchmark checks.

## Verification

This wave should be considered complete only when all of the following checks
pass.

### Semantic-center checks

- shared and backend docs describe the same semantic backbone
- no active authority page still treats `evidence_cards` as the primary
  research object

### Performance checks

- extraction unit count drops on the known slow collection
- one representative text-window or table-row extraction call completes on a
  seconds-scale path
- whole-document extraction time improves materially relative to the current
  serial structured-output path

### Semantic checks

- process parameters are captured into explicit PBF fields when present
- `current_work` and `prior_work` style statements are separated correctly
- `reported` and `derived` values are distinguishable in stored facts
- comparison assessment changes when critical PBF context is missing

### Gold-corpus checks

- key process-parameter recall is measured on the fixed PBF corpus
- `claim_scope` precision is tracked
- false-comparable rate is tracked
- row-to-anchor traceback remains reviewable

## Risks And Deferrals

- the first wave can still overfit to LPBF-style papers if the corpus is too
  narrow; the gold set should stay narrow on purpose, but the extension should
  remain optional and domain-scoped
- local JSON validation still needs careful prompt discipline; dropping
  provider-native strict structured output does not justify free-form outputs
- the first wave should not expand into a full ontology registry or a generic
  materials knowledge graph
- the first wave should not introduce a second permanent Core extraction path

## Related Docs

- [`README.md`](README.md)
- [`implementation-plan.md`](implementation-plan.md)
- [`../core-parsing-quality-hardening-plan.md`](../core-parsing-quality-hardening-plan.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
- [`../document-profile-lightweight-triage-plan.md`](../document-profile-lightweight-triage-plan.md)
- [`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
- [`../../backend-wide/materials-comparison-v2-plan.md`](../../backend-wide/materials-comparison-v2-plan.md)
