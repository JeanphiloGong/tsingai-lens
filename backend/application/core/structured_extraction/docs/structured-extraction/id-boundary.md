# Core LLM Structured Extraction ID Boundary

## Status

Implemented.

## Decision

The LLM boundary is semantic. Persistent identity and Source locator ownership
remain deterministic backend responsibilities.

Model input may contain human-readable paper text, headings, table content,
and bounded nearby context. Model output may contain semantic facts and quoted
evidence. It must not create persistence IDs or Source artifact IDs.

## Backend Ownership

The backend owns:

- persistent fact and evidence IDs;
- extraction-scope identity;
- quote-to-scope validation;
- stable evidence references;
- deduplication and relationship resolution.

After extraction, the backend attaches an evidence anchor to its known Source
scope using:

```text
document_id + source_kind + source_ref
```

For a text scope, `source_kind` is `block` and `source_ref` is the stable block
ID. Table, table-row, cell, and figure scopes use their corresponding artifact
kind and stable ID.

## Model Boundary

Allowed model input includes:

- document title and coarse profile when useful;
- bounded text or table contents;
- human-readable heading context;
- nearby semantic context needed to interpret a row or result.

Allowed model output includes:

- methods, samples, conditions, baselines, and results;
- quoted evidence text;
- human-readable labels and normalized properties;
- optional page numbers as reader context.

Disallowed input or output includes:

- database primary keys and storage paths;
- model-generated backend IDs;
- model-generated Source artifact IDs;
- coordinate or character-range locators;
- a compatibility payload for removed locator fields.

## Materialization Rule

The extraction caller knows the active Source scope before invoking the model.
It validates returned quotes against that scope and materializes facts and
anchors with backend-owned identity. A response cannot redirect evidence to a
different Source artifact by returning an ID.

If semantic output cannot be grounded in the active scope, materialization
rejects or marks it unresolved. It does not recover identity by searching the
whole paper for a similar quote.

## Structured Extraction Package Boundary

`application/core/structured_extraction/` owns only shared JSON normalization
at the untrusted model-output boundary. Prompts, schemas, completion policy,
repair, semantic validation, and Source materialization stay in their owning
`document_profiles/`, `paper_facts/`, or `objectives/` module.

## Verification

Focused tests assert that:

- model schemas do not expose backend locator fields;
- materialized Evidence uses stable Source references;
- cross-scope or ungrounded model output is rejected;
- serialized HTTP and persistence records contain no coordinate or
  character-range locator payload.

## Related Docs

- [`hard-cutover.md`](hard-cutover.md)
- [`../../../../../docs/architecture/goal-core-source-layering.md`](../../../../../docs/architecture/goal-core-source-layering.md)
- [`../../../../../../docs/decisions/rfc-pdf-backed-document-workbench.md`](../../../../../../docs/decisions/rfc-pdf-backed-document-workbench.md)
