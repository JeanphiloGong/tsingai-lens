# Backend Collections Application Node

This node owns collection lifecycle and file membership in the backend
application layer.

## Scope

- `service.py`

## Responsibilities

- create collection records and collection directory layout
- normalize collection metadata
- list, read, update, and delete collections
- manage collection file membership
- persist collection-scoped artifact readiness defaults at creation time
- convert uploaded PDFs into stored text inputs for downstream indexing

## Boundary

This node owns collection state and collection file ingestion, not downstream
analysis artifacts.

It may depend on:

- collection and artifact repositories
- ingestion adapters such as PDF-to-text conversion

It should not own:

- task orchestration
- workspace assembly
- document profiling
- evidence extraction
- comparison normalization
- protocol search or SOP generation

## Important Files

- `service.py`
  Main collection registry and file-ingestion service used by the backend HTTP
  layer

## Upstream / Downstream

- upstream inputs:
  create/delete collection requests, uploaded files
- downstream outputs:
  collection records, collection file lists, collection directory structure,
  default artifact registry entries, normalized text inputs for indexing
- downstream consumers:
  indexing, workspace, documents, evidence, comparisons, and protocol flows

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md)
- [`../../docs/architecture/domain-architecture.md`](../../docs/architecture/domain-architecture.md)
- [`../README.md`](../README.md)
