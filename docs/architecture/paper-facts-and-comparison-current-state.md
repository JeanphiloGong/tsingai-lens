# Paper Facts And Comparison Current State

## Purpose

This document records the current shared design tension between the paper-facts
layer that Lens needs for trustworthy reading of one paper and the
comparison-first backbone that Lens uses as its primary collection-facing
surface.

It exists to support discussion before further backend or frontend changes make
the object-model split harder to repair.

This is a current-state architecture note, not a final decision record.

## Scope

This document covers:

- the shared product need for both single-paper facts and cross-paper
  comparison
- the current object-model split visible in shared docs and backend runtime
- the main conflicts this split introduces for artifact design and UI design
- the questions that need explicit design review

This document does not define:

- the final replacement schema
- the final route payloads
- the implementation sequence for the next cutover wave

## Shared Product Need

Lens v1 is correctly defined as a collection comparison product rather than a
single-paper summary product. The primary job remains evidence-backed,
traceable, cross-paper comparison.

That product goal still requires a strong paper-facts layer.

In practical terms, Lens needs both of the following:

1. a single-paper facts surface that lets a user see what one paper says about
   material or sample, method, property, condition, baseline, and supporting
   evidence
2. a collection comparison surface that lets a user inspect which results can
   be compared, why they can be compared, and where the evidence or missing
   context sits

The second surface depends on the first. If the system cannot represent one
paper's material, methods, properties, results, and conditions clearly, the
comparison workspace cannot remain trustworthy.

## Current Shared Definitions

The repository currently preserves two different backbone interpretations.

### Shared Lens V1 Contract Path

The shared v1 product definition and shared artifact contracts still describe a
main business flow centered on:

- `document_profiles`
- `evidence_cards`
- `comparison_rows`

In that model:

- `document_profiles` is the gating layer
- `evidence_cards` is the core research object layer
- `comparison_rows` is the primary collection-facing view

This keeps Lens explicitly evidence-first and comparison-first, but it remains
claim-centered in its main shared artifact language.

### Materials Comparison Path

The materials comparison direction has already shifted toward a more explicit
research-object model:

- `sample_variants`
- `characterization_observations`
- `structure_features`
- `test_conditions`
- `baseline_references`
- `measurement_results`

That direction also states that materials comparison is not only a
`sample -> result` problem but a
`sample -> structure/characterization -> condition -> result -> baseline ->
comparability support` problem.

This is a stronger fit for the actual materials workflow, but it does not yet
fully replace the older claim-centered shared contracts.

## Current Runtime Shape

The backend runtime currently behaves like a hybrid of the two models.

1. Source prepares `documents`, `text_units`, `sections`, and `table_cells`.
2. `document_profile_service` uses LLM structured output for coarse document
   typing and protocol suitability.
3. `evidence_card_service` uses LLM structured extraction for a mixed bundle of:
   - `evidence_cards`
   - `sample_variants`
   - `test_conditions`
   - `baseline_references`
   - `measurement_results`
4. `evidence_card_service` then materializes those bundle outputs into multiple
   artifact tables and also regenerates property-flavored `evidence_cards` from
   extracted `measurement_results`.
5. `characterization_observations` and `structure_features` are derived later
   rather than treated as first-pass extracted objects.
6. `comparison_service` no longer performs LLM extraction. It deterministically
   assembles `comparison_rows` from:
   - `sample_variants`
   - `measurement_results`
   - `test_conditions`
   - `baseline_references`
   - `evidence_cards`

This means the current runtime is already partly sample/result-backed while the
shared contract language is still largely claim/evidence-card-backed.

## Main Conflicts

### Two Competing Primary Object Models

The repository currently has two different candidates for "primary research
object":

- claim-centered `evidence_cards`
- sample/result-centered material comparison objects

Those two models are related, but they are not interchangeable. The current
system often behaves as if both are primary at the same time.

### Single-Paper Facts Are Required But Not Explicitly First-Class

The product needs a paper-facts layer to support both reading and comparison,
but the current shared backbone does not cleanly expose a first-class
single-paper facts model.

Instead, paper-level facts are partially spread across:

- `evidence_cards`
- `sample_variants`
- `test_conditions`
- `measurement_results`
- traceback anchors

That makes it harder to build a clean paper-facts surface from one coherent
object family.

### `evidence_cards` Is Overloaded

`evidence_cards` currently acts like several things at once:

- a core claim-centered research object
- a paper-review artifact
- a traceback entry point
- comparison support evidence
- a secondary projection regenerated from `measurement_results`

That overload makes it unclear whether a card is supposed to be a durable
domain object or a reader-facing evidence view.

### `document_profiles` Has Contract Drift Risk

The shared contract expects `document_profiles` to remain a strict coarse
gating layer with explicit enum-like states.

The current runtime path allows free-form model output to leak into fields that
downstream logic expects to behave more like controlled values. That creates a
risk that the profile stage drifts from routing and warning semantics into
open-ended summary semantics.

### Source Is Not Fully Neutral

The newer materials comparison direction assumes Core owns research-fact
semantics, but Source still pre-shapes the handoff through heuristic section
types such as `methods` and `characterization`.

That is useful operationally, but it means the system does not yet have a clean
boundary between:

- Source as neutral structured handoff
- Core as the owner of research-fact meaning

### `comparison_rows` Depends On New Objects More Than The Shared Contracts Admit

The current backend comparison flow is already closer to the new materials
comparison model than to the older claim-card projection model.

`comparison_rows` now depends primarily on extracted result and context objects,
not only on a direct projection from `evidence_cards`.

This creates a split where:

- shared contracts still explain comparison in evidence-card terms
- runtime comparison assembly already behaves in sample/result terms

## Why This Matters

This split is not just a naming problem.

It affects three product-critical questions:

1. What should a user see on a single-paper facts page?
2. What should a user compare across papers?
3. Which objects are durable enough to support traceback, warnings, and future
   derived views without constant remapping?

If these questions keep different answers in different parts of the repository,
the system risks:

- paper facts that are hard to inspect directly
- comparison rows that are difficult to trust or explain
- repeated backend remapping between cards, results, and condition objects
- frontend surfaces that cannot tell whether they should present cards,
  material facts, or result rows as the real unit of meaning

## Design Review Questions

The next design discussion should answer these questions explicitly.

### 1. What Is The Primary Paper-Facts Layer?

Should the single-paper facts surface be modeled directly around:

- sample or material
- method
- property or result
- condition
- baseline
- evidence anchor

If yes, those objects need a clearer first-class status in shared architecture,
not only in backend-local plans.

### 2. What Is The Primary Comparison Backbone?

Should comparison remain conceptually derived from:

- claim-centered evidence cards

or should it be explicitly derived from:

- sample variants
- measurement results
- test conditions
- baselines
- related structure or characterization context

### 3. What Is `evidence_cards` After The Materials Shift?

One explicit answer is needed:

- keep `evidence_cards` as the primary domain object
- downgrade `evidence_cards` into a reader-facing evidence or traceback view
- retain `evidence_cards` only for narrow claim-centered inspection while the
  sample/result objects become primary for comparison

### 4. What Should Source Hand Off To Core?

Should Source hand off:

- neutral chunks, spans, and table rows

or:

- partially semantic sections such as `methods` and `characterization`

The answer changes where ownership of semantic errors and parser complexity
should live.

### 5. Is `structure_features` Phase-1 Backbone Or Phase-2 Enrichment?

`structure_features` is useful for materials comparison, but it is not obvious
that it should sit on the critical path ahead of a stable sample/result model.

The team should decide whether it is:

- required phase-1 comparison context
- optional enrichment once the paper-facts and comparison backbone is stable

## Near-Term Guardrails

Until the design is reconciled, changes should preserve these guardrails:

- do not treat single-paper facts and cross-paper comparison as competing
  product goals; the comparison surface depends on a trustworthy paper-facts
  layer
- do not silently let `document_profiles` drift from coarse routing and warning
  semantics into open-ended summary output
- do not add more permanent surfaces that assume `evidence_cards` is
  unambiguously the only core research object until the object-model question
  is settled
- do not let comparison implementation regress back into a direct
  evidence-card-only projection when the runtime already depends on result and
  condition objects

## Related Docs

- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens Core Artifact Contracts](../contracts/lens-core-artifact-contracts.md)
- [Lens V1 Architecture Boundary](lens-v1-architecture-boundary.md)
- [RFC Paper-Facts Primary Domain Model and Derived Comparison Views](../decisions/rfc-paper-facts-primary-domain-model.md)
- [Lens Mission and Positioning](../overview/lens-mission-positioning.md)
- [Materials Comparison V2 Plan](../../backend/docs/plans/backend-wide/materials-comparison-v2-plan.md)
