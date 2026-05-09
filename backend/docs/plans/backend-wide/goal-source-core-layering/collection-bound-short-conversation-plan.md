# Collection-Bound Short Conversation Plan

## Summary

The current Goal layer should be implemented as a simple collection-bound
conversation surface.

The primary user flow is:

1. bind a conversation session to one collection
2. accept a natural-language user question
3. inspect the current collection's Core artifacts when the mode allows it
4. answer with an explicit source boundary

This plan deliberately keeps structured goal workflows, gap detection, ranking,
and decision support out of the current implementation wave. Those capabilities
can be added later once the short conversation path is stable and the Core
artifacts are strong enough to support them.

## Context

The existing five-layer architecture separates Goal Brief, Source & Collection
Builder, Core, Goal Consumer, and Derived Views. That architecture remains the
longer-term direction, but the immediate product need is narrower.

For the current wave, users do not need a full goal-structuring workflow before
they can talk to the system. They need a bounded conversation over a collection
that can say whether an answer came from collection evidence or from general
background.

The existing `goal-sessions` route family already matches this shape better
than `goals/intake`. `goals/intake` should remain an optional collection-seeding
entry point, not the main conversation path.

## Current Boundary

The current Goal layer owns:

- collection-bound session creation
- natural-language user messages
- optional session context such as `goal_text`, focused material, focused paper,
  and answer mode
- retrieval of existing Core or Core-derived artifacts for grounded answers
- answer source labeling through `source_mode`
- conversation message persistence

The current Goal layer does not own:

- mandatory structured Goal Brief creation
- final coverage assessment
- gap detection
- clue ranking
- next-step decision support
- alternate evidence objects or a second fact model
- direct creation of document profiles, evidence cards, comparison rows, or
  other Core artifacts

## Backend Shape

The active backend path should center on:

- `controllers/goal/sessions.py`
- `controllers/schemas/goal/session.py`
- `application/goal/session_service.py`
- `tests/unit/services/test_goal_session_service.py`
- `tests/unit/routers/test_goal_sessions_api.py`

`application/goal/brief_service.py` and `controllers/goal/intake.py` stay in
place, but they should be described as an optional goal-first collection
seeding path. They should not be required for normal collection-bound chat.

No adapter, wrapper, bridge, facade, or compatibility layer is needed for this
wave. The implementation should keep the current route family and simplify the
documented expectations around it.

## Conversation Contract

Session creation should require only a collection binding. The caller may pass
`goal_text`, focus fields, or `answer_mode`, but structured goal data is not a
precondition for chat.

The minimal creation request remains:

```json
{
  "collection_id": "col_xxx",
  "answer_mode": "hybrid"
}
```

A richer request may include a natural-language goal:

```json
{
  "collection_id": "col_xxx",
  "goal_text": "Compare LPBF 316L strength and ductility.",
  "answer_mode": "hybrid"
}
```

Messages remain plain natural-language turns with optional page context:

```json
{
  "message": "What does this collection say about energy density and strength?",
  "page_context": {
    "material_id": "optional",
    "paper_id": "optional"
  }
}
```

Responses must continue to expose:

- `answer`
- `source_mode`
- `used_evidence_ids`
- `warnings`
- `links`

The source modes stay intentionally small:

- `collection_grounded`
- `collection_limited`
- `general_fallback`
- `general_only`

## Implementation Slices

### 1. Reframe the public docs

Update `backend/docs/specs/api.md` so the recommended Goal path is
`goal-sessions` for collection-bound conversation.

Keep `goals/intake` documented as optional goal-first collection seeding. The
API doc should explicitly say that `goal_brief_json` is optional metadata for
sessions, not a prerequisite for conversation.

Verify:

- the API doc no longer implies that structured Goal Brief is the main chat
  entry
- `goals/intake` is still described as pre-Core collection handoff only
- `goal-sessions` still requires answer source boundaries

### 2. Tighten the goal application entry page

Update `backend/application/goal/README.md` so readers see the current runtime
shape first:

- `session_service.py` is the primary current conversation path
- `brief_service.py` is an optional collection-seeding path
- future decision-layer capabilities are explicitly outside the current package
  behavior

Verify:

- the README explains what the package does before pointing to deeper docs
- it does not present Goal Brief or Goal Consumer as required chat steps

### 3. Preserve the existing route contract

Keep the existing `goal-sessions` endpoints:

- `POST /api/v1/goal-sessions`
- `GET /api/v1/goal-sessions/{session_id}`
- `PATCH /api/v1/goal-sessions/{session_id}`
- `POST /api/v1/goal-sessions/{session_id}/messages`
- `GET /api/v1/goal-sessions/{session_id}/messages`

Avoid public breaking changes. The main contract clarification is semantic:
`goal_brief_json` remains optional and should not control whether chat can
start.

Verify:

- a session can be created with only `collection_id`
- a session can answer a message without structured goal data
- updating `goal_text`, focus fields, or `answer_mode` remains possible

### 4. Keep answer boundaries enforceable

The current `answer_mode` behavior should stay:

- `grounded` refuses to answer from general background when collection evidence
  is unavailable
- `hybrid` uses collection evidence first and falls back to clearly labeled
  general background
- `general` avoids collection-evidence claims

The service should continue to collect Core context from existing collection
artifacts before calling the LLM in grounded or hybrid modes. Any future
improvement to evidence citation checking should strengthen this path without
turning it into a new decision layer.

Verify:

- grounded mode with no collection context returns `collection_limited`
- hybrid mode with no collection context returns `general_fallback`
- general fallback text is clearly labeled as not collection-supported
- collection-grounded answers expose evidence ids from the retrieved context

### 5. Defer decision-layer features

Do not add Goal Consumer outputs in this wave. In particular, do not add:

- grounded coverage assessment
- gap detection
- ranked clues
- next-step decision support
- goal-specific fact storage
- goal-specific evidence objects

Those capabilities should be introduced later as a separate Goal Consumer wave
that consumes Core artifacts without replacing them.

Verify:

- no new persisted goal fact model appears
- no route returns goal-owned research facts parallel to Core
- future work remains documented as future work

## Verification

Run the smallest checks that cover the documented behavior:

```bash
cd backend
./.venv/bin/python -m pytest \
  tests/unit/services/test_goal_session_service.py \
  tests/unit/routers/test_goal_sessions_api.py
```

When the implementation also changes `goals/intake` wording or behavior, add:

```bash
cd backend
./.venv/bin/python -m pytest \
  tests/unit/services/test_goal_service.py \
  tests/unit/routers/test_goals_api.py
```

When governed docs or node-local README pages change, run:

```bash
python3 scripts/check_docs_governance.py
```

from the repository root, or the backend-local equivalent described in
`backend/AGENTS.md`.

## Risks

- If `goal_brief_json` becomes required by convention, the short conversation
  path will drift back into a structured workflow.
- If general fallback is not labeled strongly, users may treat background
  knowledge as collection evidence.
- If future gap detection or ranking is added inside `session_service.py`
  directly, the service can become a hidden Goal Consumer without a clear
  contract.
- If `goals/intake` is promoted as the main chat entry, the frontend workflow
  will add unnecessary steps before a user can ask a collection-bound question.

## Related Docs

- [`README.md`](README.md)
- [`implementation-plan.md`](implementation-plan.md)
- [`contract-follow-up.md`](contract-follow-up.md)
- [`../../../specs/api.md`](../../../specs/api.md)
- [`../../../architecture/goal-core-source-layering.md`](../../../architecture/goal-core-source-layering.md)
