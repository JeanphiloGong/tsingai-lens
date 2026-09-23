# Model Call Inspector

The assistant answer actions include a request inspection control. It loads
the call whose recorded response message matches that answer, then fetches
the full saved JSON on demand. The inspector shows the purpose, provider
status, model, digest, and exact messages and tool schemas used for that
submission.

Historical answers created before the `chat_model_calls` migration remain
explicitly unavailable. The browser does not infer a request from the visible
messages. Loading and retry requests are cancelled when the session, account,
or collection changes.
