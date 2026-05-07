# Goal Application Layer

This package owns Goal Brief intake and collection-bound goal sessions inside
the backend application layer.

- `brief_service.py`
  Goal intake, research brief shaping, coverage assessment, and
  `seed_collection` handoff registration into Source.
- `session_service.py`
  Collection-bound AI research copilot sessions that keep explicit context,
  retrieve Core artifacts before grounded answers, and label general fallback
  separately from collection evidence.
