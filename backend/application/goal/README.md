# Goal Application Layer

This package currently owns the collection-bound short conversation path inside
the backend application layer.

The active runtime path is a lightweight session over one collection:

1. create a goal session bound to `collection_id`
2. accept plain natural-language messages
3. read existing Core or Core-derived artifacts when grounded context is allowed
4. prefer expert-curated `training_ready` research-understanding Findings when
   the session is focused on a confirmed goal or objective
5. label the answer source as collection-grounded, collection-limited, general
   fallback, or general-only

Structured Goal Brief data is optional context for this path. It is not a
precondition for starting a conversation.

The conversation domain model lives in `domain/goal/session.py`. It owns the
core chat records and source-boundary rules for `GoalSessionRecord`,
`GoalMessageRecord`, and `GoalSourceLink`. This package remains responsible for
orchestration: reading Core artifacts, calling the LLM, and persisting the
domain records through the Goal session repository port. The default SQLite
storage engine is owned by `infra/persistence/sqlite/`; this package does not
own database connections, SQL, schema initialization, or row encoding.

- `session_service.py`
  Primary current conversation service. It persists session context, retrieves
  collection artifacts before grounded answers, prioritizes curated Findings
  for goal-focused experiment or protocol questions, and labels general
  fallback separately from collection evidence.
- `brief_service.py`
  Optional goal-first collection-seeding path. It shapes a thin research brief
  and registers a `seed_collection` handoff into Source, but it is not required
  for normal collection-bound chat.

Future Goal Consumer capabilities such as final coverage assessment, gap
detection, clue ranking, and next-step decision support should be added in a
separate wave that consumes Core artifacts without creating a parallel fact
model.
