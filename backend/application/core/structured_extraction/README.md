# Structured Extraction Support

This package owns only pure normalization used at the untrusted model-output
boundary.

## Local Component

- `json_support.py`
  Coerces provider message content, selects the last complete JSON object,
  tolerates trailing commas, and bounds trace values.

## Boundary

This package does not call providers and does not own prompts, response
schemas, completion limits, retries, repair policy, or domain validation.
Those responsibilities belong directly to `document_profiles/`,
`paper_facts/`, and `objectives/`.
