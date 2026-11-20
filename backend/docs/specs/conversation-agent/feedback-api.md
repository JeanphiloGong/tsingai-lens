[[31mERROR[0m] - (starship::print): Under a 'dumb' terminal (TERM=dumb).
# Feedback API

本文档负责用户对已保存 assistant message 的评价。Feedback 属于具体消息，
不属于 Task 或当前路径。

消息路径中的 `items[].my_feedback` 由
[Conversation API](conversation-api.md#2-读取当前消息路径) 定义。没有反馈时
为 `null`，前端不需要额外查询反馈接口。

## 1. 创建或更新反馈

### `PUT /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

目标必须是当前用户可见的 assistant message。请求正文：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `rating` | string | 是 | `helpful` 或 `not_helpful` |
| `reason` | string / null | 否 | `incorrect`、`incomplete`、`unclear` 或 `other` |
| `comment` | string / null | 否 | 用户补充说明 |

服务端保存提交时的 `response_digest`。如果消息内容后来发生变化，反馈仍然
指向原回答摘要，不把反馈移动到新版本。

## 2. 删除反馈

### `DELETE /api/v1/conversations/{conversation_id}/messages/{message_id}/feedback`

删除当前用户对该 assistant message 的评价。它不会删除回答消息。

反馈关系满足以下约束：

- `message_id` 必须指向 `role = assistant` 的消息。
- 一条 assistant message 对当前用户最多有一条反馈。
- 当前消息路径中的 `my_feedback` 返回当前用户自己的反馈。

## 3. 错误

| `error_code` | 说明 |
| --- | --- |
| `feedback_message_not_found` | 消息不存在或不可见 |
| `feedback_message_not_assistant` | 目标消息不是 assistant message |
| `feedback_rating_invalid` | 评价值不在允许范围 |
| `feedback_reason_invalid` | 原因值不在允许范围 |
