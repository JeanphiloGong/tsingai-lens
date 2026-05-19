# Objective Context Targeted Extraction Plan

## Summary

`ObjectiveContext` already exists as a persisted Core record. The next slice is
to make it an active control surface for paper-fact extraction so the Core
pipeline reads each paper through the right research question, not through one
shared paper-wide prompt.

The intended flow is:

```text
paper skim
  -> research objective discovery
  -> objective context build
  -> objective-aware paper scan
  -> objective-aware table routing
  -> deterministic fact binding
```

This plan stays inside Core semantic build. It does not change public API
routes, frontend behavior, or Source artifact production.

Read this with:

- [`target-centric-collection-extraction-plan.md`](target-centric-collection-extraction-plan.md)
- [`research-objective-domain-model-plan.md`](research-objective-domain-model-plan.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/semantic-routing-targeted-extraction-plan.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/semantic-routing-targeted-extraction-plan.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/table-first-extraction-plan.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/table-first-extraction-plan.md)

## Why This Slice Exists

The domain and persistence layer now record objective context, and the P001
validation run already shows the shape we want:

- one structural objective for densification and microstructure
- one mechanical objective for yield strength, tensile strength, elongation,
  and microhardness
- Table 1 used as the structural result table
- Table 1 used as condition context for the mechanical objective
- Table 2 used as the mechanical result table

What is still missing is downstream usage. The current paper-facts path still
scans windows and table batches with a shared extraction frame. That is enough
to gather evidence, but not enough to keep different research questions
separated.

This slice closes that gap by feeding objective context into the extraction
payloads themselves.

## What Changes

### 1. Thread Objective Context Into Paper Facts

`PaperFactsService` should read `objective_contexts` from the Core fact
repository and attach the relevant objective context to the text-window and
table-batch payloads it sends into the extractor.

The objective payload should expose:

- `focus`
- `variable_process_axes`
- `process_context_axes`
- `target_property_axes`
- `excluded_property_axes`
- `routing_hints`
- `extraction_guidance`

### 2. Make Prompt Builders Target-Aware

`build_text_window_extraction_prompt(...)` and
`build_table_batch_mentions_prompt(...)` should accept `objective_context` and
surface it to the model.

The prompt should tell the model to:

- treat `Selective Laser Melting` or similar process labels as context when
  they are background, not changed variables
- keep process variables separate from target properties
- prefer the table route implied by the objective hints
- ignore unrelated properties outside the current objective scope

### 3. Keep Routing And Binding Deterministic

Objective context should guide extraction, not replace backend binding.

`PaperFactsService` should still own:

- quote matching
- sample and variant binding
- condition binding
- baseline binding
- measurement-result materialization

The objective context only decides what should be treated as the current lens.

### 4. Preserve The Existing Public Surface

This slice should not introduce:

- new frontend requirements
- new public API fields
- a second extraction service
- a dual-path compatibility layer

## Implementation Slices

1. `backend/application/core/semantic_build/research_objective_service.py`
   - keep persisting objective contexts
   - expose the contexts in a way `PaperFactsService` can consume

2. `backend/application/core/semantic_build/paper_facts_service.py`
   - load objective contexts for the collection
   - select the relevant objective context for each objective-specific scan
   - attach the context to the text-window and table-batch payloads
   - keep table routing and measurement binding deterministic

3. `backend/application/core/semantic_build/llm/prompts.py`
   - add objective-context fields to the prompt builders
   - carry the target lens into text-window and table-batch extraction

4. `backend/application/core/semantic_build/llm/schemas.py`
   - widen payload models only if the prompt needs extra structured guidance
   - keep the model-facing contract narrow and schema-bound

5. `backend/tests/unit/services/`
   - verify prompt payloads include objective context
   - verify P001 still routes Table 1 and Table 2 correctly
   - verify table measurements remain aligned with the gold counts

## Verification

Use the P001 gold corpus as the first acceptance slice.

Checks:

- objective-context preview still passes the local gold validation
- full single-paper extraction still yields the expected table-result counts
- objective-aware routing still separates structural and mechanical targets
- unit tests for the Core semantic-build and extractor boundary still pass

Recommended commands:

```bash
cd backend
./.venv/bin/python -m pytest
./.venv/bin/python -m ruff check application/core/semantic_build
python3 ../scripts/check_docs_governance.py
```

## Exit Criteria

This slice is complete when:

- objective context is present in the payloads used by Core paper-fact
  extraction
- P001 still routes Table 1 and Table 2 correctly per objective
- table-result counts remain aligned with the gold corpus
- the first implementation wave does not require frontend or public API
  changes

## Related Docs

- [`target-centric-collection-extraction-plan.md`](target-centric-collection-extraction-plan.md)
- [`research-objective-domain-model-plan.md`](research-objective-domain-model-plan.md)
- [`../../../../application/core/semantic_build/README.md`](../../../../application/core/semantic_build/README.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/README.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/README.md)
