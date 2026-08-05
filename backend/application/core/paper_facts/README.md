# Paper Facts

This package owns reusable, document-scoped facts extracted from normalized
Source artifacts.

## Owner

- `service.py`
  Builds and reads evidence anchors, methods, sample variants, test
  conditions, baselines, measurements, and characterization observations.
- `extraction.py`
  Calls the configured model provider for text windows and table batches and
  owns paper-fact completion limits, retry behavior, and extraction traces.
- `prompts.py` and `schemas.py`
  Define paper-fact prompts and their validated response contracts.

## Boundary

Paper facts are reusable inputs for comparison and research views. They do not
own Objective confirmation, versioned Objective analysis, Finding synthesis,
HTTP schemas, or persistence implementations.
