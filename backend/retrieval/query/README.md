# Retrieval Query Flows

This node owns query-time retrieval, context assembly, and answer-generation
support inside the retrieval engine.

## Scope

- `context_builder/`
- `input/`
- `llm/`
- `question_gen/`
- `structured_search/`
- `factory.py`
- `indexer_adapters.py`

## Responsibilities

- build query-time retrieval inputs
- assemble evidence context
- run structured search strategies
- prepare the engine outputs consumed by backend query and report flows
