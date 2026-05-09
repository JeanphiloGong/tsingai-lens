# Goal Application Layer

This package currently owns the collection-bound short conversation path inside
the backend application layer.

The active runtime path is a lightweight session over one collection:

1. create a goal session bound to `collection_id`
2. accept plain natural-language messages
3. read existing Core or Core-derived artifacts when grounded context is allowed
4. label the answer source as collection-grounded, collection-limited, general
   fallback, or general-only

Structured Goal Brief data is optional context for this path. It is not a
precondition for starting a conversation.

- `session_service.py`
  Primary current conversation service. It persists session context, retrieves
  collection artifacts before grounded answers, and labels general fallback
  separately from collection evidence.
- `brief_service.py`
  Optional goal-first collection-seeding path. It shapes a thin research brief
  and registers a `seed_collection` handoff into Source, but it is not required
  for normal collection-bound chat.

Future Goal Consumer capabilities such as final coverage assessment, gap
detection, clue ranking, and next-step decision support should be added in a
separate wave that consumes Core artifacts without creating a parallel fact
model.
