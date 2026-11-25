# Feedback API

Each user rates a saved answer by its Message ID.

The message path returns eligibility in `items[].can_rate` and the current
user's rating in `items[].my_feedback`. [Conversation API](conversation-api.md#2-read-the-current-message-path)

## 1. Create or Update Feedback

### `PUT /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

The target must be a visible assistant Message with content. Its producing Task
must be completed, belong to the same Conversation, and reference that Message
as its `final_message_id`. Migration restores historical Task ownership when the
old records establish it and reports unresolved ownership.

Fork copies return `can_rate: false` and `my_feedback: null`. The original rating
stays with the source answer. A completed Task in the new Conversation can produce
its own eligible answer. [Tree API](tree-api.md#3-explicit-fork)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `rating` | string | yes | `helpful` or `not_helpful` |
| `reason` | string / null | no | `incorrect`, `incomplete`, `unclear`, or `other`, only for `not_helpful` |
| `comment` | string / null | no | Additional user comment, trimmed to at most 2000 characters |

HTTP `200` returns the saved feedback in `data`. Repeating a submission with the
same content preserves its identity and timestamps. The server stores the
`response_digest` at submission time. If the Message content later changes, the
feedback stays bound to the original answer digest.

## 2. Delete Feedback

### `DELETE /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

Withdraw the authenticated user's rating from an eligible answer. Repeating the
delete for the same eligible answer returns HTTP `204`. The message path then
returns `my_feedback: null`.

The feedback relationship follows these rules:

- `message_id` must reference a Message whose `role` is `assistant`.
- Each assistant Message has at most one feedback row for the current user.
- The current user's feedback is returned as `my_feedback` in the current path.

## 3. Errors

| `error_code` | Description |
| --- | --- |
| `feedback_message_not_found` | HTTP `404` when the Message is missing or invisible to the caller |
| `feedback_message_not_assistant` | HTTP `422` when the Message is ineligible, including intermediate tool requests and Fork copies |
| `feedback_rating_invalid` | The rating is outside the allowed values |
| `feedback_reason_invalid` | The reason is outside the allowed values |
