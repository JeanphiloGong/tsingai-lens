# Goal Application Layer

This package owns Goal intake and Objective-scoped experiment plans. It does not
own assistant conversation state. Collection-bound conversation, capability
execution, structured results, and write approval live in `application/chat/`
and `domain/chat/`.

- `experiment_plan_service.py`
  Persists manually authored Objective-scoped drafts. New plans have no Chat
  message provenance because ordinary Agent prose is not a scientifically
  validated experiment-plan contract. Historical plans that already reference
  a migrated Chat message remain readable and auditable. Their stored Finding
  fingerprints are checked against the current Objective dataset before they
  can return to `ready_for_review`.
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
  Historical grounded drafts that violate either rule are reported as stale
  instead of being promoted for review.
- `brief_service.py`
  Optional goal-first collection-seeding path. It shapes a thin research brief
  and creates an empty `Collection` directly. Papers become `Document` members
  only when the user uploads or imports them; Goal owns no handoff record.

Future research-assistant capabilities belong in `application/chat/` and must
consume Core artifacts without creating a parallel fact model.
