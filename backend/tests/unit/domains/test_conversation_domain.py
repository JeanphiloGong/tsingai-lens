import pytest

from conversation.domain.models import ConversationPath, Message, path_to


def test_path_to_returns_the_selected_branch_from_root_to_tip() -> None:
    messages = {
        "question": Message("question", "conversation-1", None, "user", "Compare papers."),
        "first-answer": Message(
            "first-answer", "conversation-1", "question", "assistant", "First answer."
        ),
        "retry-answer": Message(
            "retry-answer", "conversation-1", "question", "assistant", "Retry answer."
        ),
    }

    path = path_to(messages, "retry-answer")

    assert path == ConversationPath(
        items=(messages["question"], messages["retry-answer"]),
        tip_message_id="retry-answer",
    )


def test_path_to_returns_an_empty_path_without_a_tip() -> None:
    path = path_to({}, None)

    assert path == ConversationPath(items=(), tip_message_id=None)


@pytest.mark.parametrize(
    ("tip_id", "message_id", "parent_message_id", "error"),
    [
        ("missing", "question", None, "message path is missing or cyclic"),
        ("question", "question", "missing", "message path is missing or cyclic"),
    ],
)
def test_path_to_rejects_missing_messages_or_parents(
    tip_id: str, message_id: str, parent_message_id: str | None, error: str
) -> None:
    messages = {
        message_id: Message(
            message_id,
            "conversation-1",
            parent_message_id,
            "user",
            "Question.",
        )
    }

    with pytest.raises(ValueError, match=error):
        path_to(messages, tip_id)


def test_path_to_rejects_a_cycle() -> None:
    messages = {
        "first": Message("first", "conversation-1", "second", "user", "First."),
        "second": Message("second", "conversation-1", "first", "assistant", "Second."),
    }

    with pytest.raises(ValueError, match="message path is missing or cyclic"):
        path_to(messages, "first")


def test_path_to_rejects_a_cross_conversation_parent_chain() -> None:
    messages = {
        "question": Message("question", "conversation-1", None, "user", "Question."),
        "answer": Message("answer", "conversation-2", "question", "assistant", "Answer."),
    }

    with pytest.raises(ValueError, match="message path crosses conversations"):
        path_to(messages, "answer")


def test_user_messages_cannot_be_produced_by_a_task() -> None:
    with pytest.raises(ValueError, match="user message cannot be produced by a task"):
        Message(
            "question",
            "conversation-1",
            None,
            "user",
            "Question.",
            produced_by_task_id="task-1",
        )


def test_conversation_path_tip_must_match_the_last_item() -> None:
    message = Message("question", "conversation-1", None, "user", "Question.")

    with pytest.raises(ValueError, match="path tip must be the last message"):
        ConversationPath(items=(message,), tip_message_id="other")


def test_empty_conversation_path_cannot_have_a_tip() -> None:
    with pytest.raises(ValueError, match="empty path cannot have a tip message"):
        ConversationPath(items=(), tip_message_id="message-1")
