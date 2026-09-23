# Chat Correction Cases

The Assistant correction panel lets the signed-in collection owner select an
existing final answer, the later user challenge, and an optional corrected
answer. It calls the same `/api/v1/chat-sessions/.../correction-cases` API as
the rest of the conversation and leaves the message timeline unchanged.

The server validates message order and the associated successful P1 model
calls. Saving without a corrected answer records an unresolved case; the panel
does not infer links from thumbs-down feedback and does not approve a
scientific claim. P3 owns review and support decisions.
