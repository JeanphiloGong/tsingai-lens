from __future__ import annotations

import json

import pytest

from conversation.application.title_service import ConversationTitleService
from conversation.prompts import CONVERSATION_TITLE_SYSTEM_PROMPT


class FakeTitleModel:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_input: str,
        max_output_tokens: int,
    ) -> str:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_input": user_input,
            "max_output_tokens": max_output_tokens,
        })
        return self.value


class FakeConversationRepository:
    def __init__(self) -> None:
        self.saved: tuple[str, str, str] | None = None

    async def update_title(self, *, conversation_id: str, user_id: str, title: str) -> None:
        self.saved = (conversation_id, user_id, title)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_title_service_sends_bounded_json_and_saves_validated_title() -> None:
    model = FakeTitleModel("IN718 Methods")
    repository = FakeConversationRepository()
    service = ConversationTitleService(model=model, repository=repository)

    assert await service.generate_and_save(
        conversation_id="conv_1",
        user_id="user_1",
        question="Q" * 5000,
        answer="A" * 3000,
    ) == "IN718 Methods"

    assert model.calls == [{
        "system_prompt": CONVERSATION_TITLE_SYSTEM_PROMPT,
        "user_input": json.dumps(
            {"question": "Q" * 4000, "answer": "A" * 2000},
            ensure_ascii=False,
        ),
        "max_output_tokens": 128,
    }]
    assert repository.saved == ("conv_1", "user_1", "IN718 Methods")


@pytest.mark.parametrize(
    "value",
    ["", "x" * 61, "Title\nExplanation", "<tool_call>rename()</tool_call>"],
)
async def test_title_service_rejects_invalid_output_without_saving(value: str) -> None:
    repository = FakeConversationRepository()
    service = ConversationTitleService(
        model=FakeTitleModel(value),
        repository=repository,
    )

    with pytest.raises(ValueError, match="invalid conversation title"):
        await service.generate_and_save(
            conversation_id="conv_1",
            user_id="user_1",
            question="Compare IN718",
            answer="Check tensile conditions.",
        )
    assert repository.saved is None
