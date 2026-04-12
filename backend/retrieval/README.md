# Retrieval Engine

This package is the indexing and query engine surface used by the backend.

## Scope

- indexing workflows and artifact generation
- query-time context building and search
- prompt, model, tokenizer, storage, and vector-store support code

## Key Child Nodes

- [`index/README.md`](index/README.md)
  Index-time workflows and transformations
- [`query/README.md`](query/README.md)
  Query-time retrieval and answer-building flow

## Boundary Rule

`retrieval/` is a large engine package. Prefer reaching it through explicit
application-owned or infrastructure-owned boundaries rather than from unrelated
HTTP code.
