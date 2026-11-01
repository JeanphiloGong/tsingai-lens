# Objective LLM Boundary

This package owns only the technical boundary shared by Objective model
judgments.

`structured_response.py` sends schema-bearing requests, selects provider-parse
or JSON-text mode, performs bounded JSON repair requested by the calling
judgment, records usage and prompt versions, estimates complete prompt tokens,
and exposes the last call trace within the current execution context so
concurrent Objective analyses cannot overwrite each other's trace.

Named JSON-schema requests use the installed OpenAI SDK's strict-schema
conversion, not ordinary `model_json_schema()` output. Strict requests require
every object property (including nested ones) and disallow extra properties;
unknown values still use the response contract's nullable fields or empty
lists. This changes request encoding, not scientific validation or domain
models. Ordinary JSON-object mode and provider-parse mode remain unchanged.
The SDK helper is internal, so the real extraction-contract regression tests
guard its behavior when upgrading the locked SDK dependency. See the provider's
[Structured Outputs requirements](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas).

Scientific responsibilities do not live here. Each module under `discovery/`
or `analysis/` owns its task model, prompt, response schema, semantic
validation, repair instruction, token budget, prompt version, and decision to
call the model. Provider failures and JSON retries are technical execution
outcomes; they do not define a research state.

Only malformed JSON, response-model validation failures, explicit
`StructuredOutputError` rejections, and the existing output-saturation policy
can enter bounded output repair. Provider refusals, HTTP/transport failures, and
unexpected postprocessing errors propagate without another repair request.
When a caller supplies `before_request`, every request applies its remaining
timeout with SDK retries disabled; output repairs recheck that deadline.

There is one shared `StructuredResponseClient`. Do not add task dispatch,
prompt registries, compatibility exports, or a second JSON parser to this
package.
