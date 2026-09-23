# Chat Model Calls

Lens stores one `chat_model_calls` row for every provider submission made by a
Research Agent Chat session. The row is created immediately before the
OpenAI-compatible SDK call, so `request` is the exact JSON request sent to the
provider, including the final messages, tool schemas, choice settings, and
stream options. Credentials, authorization headers, environment variables,
and raw exception text are never stored.

`purpose` identifies the real execution step: `decision` asks what the agent
should do next, `compaction` preserves bounded working notes, and
`finalization` writes the answer from the evidence already read. `status`
describes provider execution and is separate from the scientific answer or
research completion state. A recorded request may therefore have no response
message, or may finish as `provider_failed`, `response_invalid`, or
`cancelled`.

Authenticated owners can read the metadata list and one exact request through:

```text
GET /api/v1/chat-sessions/{session_id}/model-calls
GET /api/v1/chat-sessions/{session_id}/model-calls/{call_id}
```

The session service checks both the Chat owner and Collection access before
reading. An old message without a captured call remains unavailable; Lens does
not reconstruct a request from the visible trajectory. A response message ID
is an association hint for locating the call beside an answer, while the
request digest lets a reviewer detect mutation of the stored snapshot.
