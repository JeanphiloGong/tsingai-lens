# Backend Documents Application Node

This node owns collection-scoped document profiling for the Lens v1 backbone.

## Scope

- `service.py`
- `input_service.py`
- `section_service.py`

## Responsibilities

- read or build `document_profiles.parquet`
- classify documents into `experimental | review | mixed | uncertain`
- decide protocol suitability as `yes | partial | no | uncertain`
- summarize document-level suitability into collection-facing rollups
- provide the gating layer that determines whether protocol remains a useful
  downstream branch

## Boundary

This node owns document profiling and suitability decisions.

It may depend on:

- `application/collections/`
- `application/workspace/`
- `application/documents/section_service.py`
- `application/documents/input_service.py`

It should not own:

- claim-centered evidence extraction
- collection comparison normalization
- SOP drafting or protocol search

## Important Files

- `service.py`
  Reads source protocol inputs, profiles documents, persists
  `document_profiles.parquet`, and produces collection-level summaries
- `input_service.py`
  Owns shared collection-input loading and document-record assembly
- `section_service.py`
  Owns shared section derivation used by documents, evidence, and protocol

## Upstream / Downstream

- upstream inputs:
  `documents.parquet`, text units, derived sections
- downstream artifact:
  `document_profiles.parquet`
- downstream consumers:
  workspace summary, evidence extraction, indexing protocol gating

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md)
- [`../../../docs/contracts/lens-core-artifact-contracts.md`](../../../docs/contracts/lens-core-artifact-contracts.md)
- [`../README.md`](../README.md)
