# Chat Correction Cases

The Assistant correction panel lets the signed-in collection owner select an
existing final answer, the later user challenge, and an optional corrected
answer. It calls the same `/api/v1/chat-sessions/.../correction-cases` API as
the rest of the conversation and leaves the message timeline unchanged.

The server validates message order and the associated successful P1 model
calls. Saving without a corrected answer records an unresolved case; the panel
does not infer links from thumbs-down feedback and does not approve a
scientific claim. P3 owns review and support decisions.

## P3 review

For a linked case, choose **Review sample** to create an immutable snapshot of
the exact model input, ordered tool observations, corrected target, and Source
references. Select support messages and record `accept`, `reject`,
`insufficient`, or `withdraw`. The server rechecks the digest against the
current Chat trajectory before every decision. A changed target or Source
reference is shown as stale; a withdrawal remains effective over earlier
decisions. Unresolved cases cannot become review samples, and this control
does not alter usefulness feedback or Finding review.
