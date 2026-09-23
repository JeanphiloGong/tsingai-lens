# Chat Correction Cases

`ChatCorrectionCase` is an explicit reference over an existing Chat
trajectory. It does not copy messages, change the trajectory, or turn
usefulness feedback into a training decision.

An owner creates a case with an assistant final answer, the later user
challenge, and optionally a later assistant final answer. The service reloads
all three messages and the P1 `ChatModelCall` records before persisting the
link. The selected messages must belong to one session and appear in the order
`assistant final -> user -> assistant final`; tool-request messages, failed
provider calls, missing calls, and cross-session IDs are rejected.

An omitted corrected answer creates an `unresolved` case. A selected corrected
answer creates a `linked` case. The stored `trace_digest` covers the selected
trajectory slice and the exact model-call digests so later evaluation can
detect changed provenance. Cases are owner-scoped through the existing Chat
session authorization.

Endpoints:

- `POST /api/v1/chat-sessions/{session_id}/correction-cases`
- `GET /api/v1/chat-sessions/{session_id}/correction-cases`
- `GET /api/v1/chat-sessions/{session_id}/correction-cases/{case_id}`

The case is a prerequisite for the later review sample. P3 performs the
scientific/supporting-evidence review; P2 only establishes the exact human
selected relationship.
