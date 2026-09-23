# Chat Correction Review Contract

P3 turns a linked `ChatCorrectionCase` into an immutable review sample. The
sample is rebuilt from the owner-scoped trajectory and the P1 successful
`ChatModelCall`; it stores the exact provider request, ordered messages and
tool observations, the final corrected assistant text, and every Source
reference present in that trace. A canonical SHA-256 digest covers those
fields. Rebuilding with a different target, request, or Source reference makes
the stored sample `stale` and cannot silently update it.

Review decisions are append-only: `accept`, `reject`, `insufficient`, and
`withdraw`. Accept, reject, and insufficient decisions require support message
IDs from the sampled trace. Accept also requires at least one Source
reference. Reject, insufficient, and withdraw require a reason. A withdrawal
remains effective over historical decisions and is terminal for that sample.
The reviewer is always the authenticated Chat session owner; no separate
review-role system is introduced.

Endpoints:

- `POST /api/v1/chat-sessions/{session_id}/correction-cases/{case_id}/sample`
- `GET /api/v1/chat-sessions/{session_id}/correction-samples`
- `GET /api/v1/chat-sessions/{session_id}/correction-samples/{sample_id}`
- `GET /api/v1/chat-sessions/{session_id}/correction-samples/{sample_id}/reviews`
- `POST /api/v1/chat-sessions/{session_id}/correction-samples/{sample_id}/reviews`
- `GET /api/v1/chat-sessions/{session_id}/correction-samples/{sample_id}/review-status`

Unresolved P2 cases, failed or missing model calls, missing support, stale
digests, and cross-owner requests are rejected. Chat usefulness feedback and
Finding review records remain separate contracts.
