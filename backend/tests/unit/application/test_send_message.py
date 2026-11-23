from unittest.mock import AsyncMock

import pytest

from conversation.application.conversation_service import AcceptedTask
from conversation.application.send_message import SendConversationMessage


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_send_conversation_message_delegates_to_conversation_service():
    service = AsyncMock()
    service.accept_message.return_value = AcceptedTask(
        task_id="task-1",
        trigger_message_id="message-1",
        status="accepted",
    )
    command = SendConversationMessage(service)

    result = await command(
        conversation_id="conversation-1",
        user_id="user-1",
        parent_message_id=None,
        content="Compare these Sources.",
        source_contexts=({"source_ref": "source-1"},),
    )

    assert result == AcceptedTask(
        task_id="task-1",
        trigger_message_id="message-1",
        status="accepted",
    )
    service.accept_message.assert_awaited_once_with(
        conversation_id="conversation-1",
        user_id="user-1",
        parent_message_id=None,
        content="Compare these Sources.",
        source_contexts=({"source_ref": "source-1"},),
    )
