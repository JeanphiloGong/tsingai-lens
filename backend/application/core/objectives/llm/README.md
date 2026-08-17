# Objective LLM Boundary

This package owns only the technical boundary shared by Objective model
judgments.

`structured_response.py` sends schema-bearing requests, selects provider-parse
or JSON-text mode, performs bounded JSON repair requested by the calling
judgment, records usage and prompt versions, estimates complete prompt tokens,
and exposes the last call trace.

Scientific responsibilities do not live here. Each module under `discovery/`
or `analysis/` owns its task model, prompt, response schema, semantic
validation, repair instruction, token budget, prompt version, and decision to
call the model. Provider failures and JSON retries are technical execution
outcomes; they do not define a research state.

There is one shared `StructuredResponseClient`. Do not add task dispatch,
prompt registries, compatibility exports, or a second JSON parser to this
package.
