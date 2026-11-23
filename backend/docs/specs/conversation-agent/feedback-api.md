# Feedback API

This document defines user feedback on saved assistant Messages. Feedback belongs
to a specific Message, not to a Task or the current path.

The `items[].my_feedback` projection in the message path is defined by the
[Conversation API](conversation-api.md#2-read-the-current-message-path). It is
`null` when no feedback exists, so the client does not need another feedback query.

## 1. Create or Update Feedback

### `PUT /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

The target must be a visible assistant Message with content and no tool requests.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `rating` | string | yes | `helpful` or `not_helpful` |
| `reason` | string / null | no | `incorrect`, `incomplete`, `unclear`, or `other`, only for `not_helpful` |
| `comment` | string / null | no | Additional user comment, trimmed to at most 2000 characters |

Success returns the saved feedback. Repeating a submission with the same content
preserves its identity and timestamps. The server stores the `response_digest` at
submission time. If the Message content later changes, the feedback remains bound
to the original answer digest and does not move to a new version.

## 2. Delete Feedback

### `DELETE /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

Delete the authenticated user's feedback for the assistant Message. If the target
is still visible, repeating the delete returns HTTP `204`. The answer Message
remains stored.

The feedback relationship follows these rules:

- `message_id` must reference a Message whose `role` is `assistant`.
- Each assistant Message has at most one feedback row for the current user.
- The current user's feedback is returned as `my_feedback` in the current path.

## 3. Errors

| `error_code` | Description |
| --- | --- |
| `feedback_message_not_found` | The Message does not exist or is not visible |
| `feedback_message_not_assistant` | The target is not an assistant Message |
| `feedback_rating_invalid` | The rating is outside the allowed values |
| `feedback_reason_invalid` | The reason is outside the allowed values |
