# Core Semantic Build LLM

This package owns Core prompt text, response schemas, and provider-call
orchestration.

## Local Components

- `prompts.py`
  Builds document-profile, Objective candidate, paper-contribution, Evidence
  extraction, paper-fact, and Finding synthesis prompts.
- `schemas.py`
  Defines strict Pydantic response models for each model call.
- `extractor.py`
  Executes provider structured parsing or the explicitly selected JSON-text
  path, validates responses, records traces, and applies bounded completion
  budgets.

## Objective Calls

The Objective path performs three model-owned decisions:

1. classify one paper's contribution to the confirmed Objective;
2. extract structured Evidence from bounded Source windows, tables, or figures;
3. synthesize Findings from eligible direct results and bounded context.

The model never assigns database ownership. Backend code binds collection,
Objective, analysis version, document, Source locator, and deterministic IDs.
Prompts return `extractions` for Evidence extraction and Findings for final
synthesis; they do not return persisted route, unit, logic-chain, Claim, or
workspace identities.

The Finding response must preserve:

- variables, mediators, outcomes, and direction;
- paper or cross-paper level;
- applicability context and limitations;
- supporting and contradicting Evidence references;
- agreement, conflict, condition dependence, or insufficient confirmation.

Model output is always validated against the version-local Evidence set.
Causal relations additionally require direct Evidence that marks the asserted
variable as isolated.

## Boundary

This package does not own Source parsing, persistence, HTTP schemas, feedback,
curation, dataset export, or frontend presentation.
