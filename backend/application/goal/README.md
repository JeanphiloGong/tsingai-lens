# Goal Application Layer

This package currently owns the collection-bound short conversation path inside
the backend application layer.

The active runtime path is a lightweight session over one collection:

1. create a goal session bound to `collection_id`
2. accept plain natural-language messages
3. read existing Core or Core-derived artifacts when grounded context is allowed
4. prefer actionable expert-curated `training_ready` research-understanding
   Findings when the session is focused on an Objective
5. save human-editable experiment plan drafts from Objective-focused chat answers
6. label the answer source as collection-grounded, collection-limited, general
   fallback, or general-only

Structured Goal Brief data is optional context for this path. It is not a
precondition for starting a conversation.

The conversation domain model lives in `domain/goal/session.py`. It owns the
core chat records and source-boundary rules for `GoalSessionRecord`,
`GoalMessageRecord`, and `GoalSourceLink`. This package remains responsible for
orchestration: reading Core artifacts, calling the LLM, and persisting the
domain records through the Goal session repository port. Persistence is owned
by `infra/persistence/`; this package does not own database connections, SQL,
schema initialization, or row encoding.

- `session_service.py`
  Primary current conversation service. It persists session context, retrieves
  collection artifacts before grounded answers, prioritizes actionable curated
  Findings for Objective-focused experiment or protocol questions, filters out
  unsupported/conflicted/insufficient reviewed findings as protocol sources,
  limits cited protocol sources to curated Findings when they are available,
  preserves each Finding's paper-level or cross-paper generalization boundary
  in the prompt context, and labels general fallback separately from collection
  evidence.
- `experiment_plan_service.py`
  Persists Objective-scoped experiment plan drafts generated from chat answers.
  When a draft references a chat message, the service verifies that the message
  is a same-user, same-Objective, collection-grounded assistant answer with auditable
  evidence links, exact protocol-source Finding fingerprints, and no
  review-blocking warnings. Plan reads compare those fingerprints with the
  current Objective dataset; stale or unverified Copilot drafts remain auditable but
  cannot enter `ready_for_review`. These drafts are
  human-editable Goal Consumer outputs, not replacements for the conditional
  Protocol browsing branch.
- `protocol_contract.py`
  Enforces the operational VED design rule shared by chat generation and plan
  persistence: at least one constituent parameter must change, every other
  constituent must be explicitly changed or fixed, and no constituent may be
  both changed and fixed. A constituent-controlled design is represented as
  that constituent-mediated path, not as an isolated universal VED effect or
  as an experiment intended to confirm a VED-only effect.
  Proposed design choices cannot contain unattributed numeric, material,
  equipment, or method-acronym details; unsupported generated details are
  dropped in favor of an explicit expert-selection placeholder.
  Structured model output is limited to variable manipulations and design
  risks. Measurements come from source-backed Finding outcomes, while controls
  come from the variable matrix and explicit expert-selection placeholders.
  If every generated VED manipulation is unsafe or incomplete, rendering falls
  back to a validated laser-power path with the other VED constituents fixed
  and leaves level selection to the expert. Other domains do not use this
  fallback.
  Existing Copilot drafts that violate either rule are reported as stale
  instead of being promoted for review.
- `brief_service.py`
  Optional goal-first collection-seeding path. It shapes a thin research brief
  and registers a `seed_collection` handoff into Source, but it is not required
  for normal collection-bound chat.

Future Goal Consumer capabilities such as final coverage assessment, gap
detection, clue ranking, and next-step decision support should be added in a
separate wave that consumes Core artifacts without creating a parallel fact
model.
