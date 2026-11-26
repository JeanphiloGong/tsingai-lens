"""Conversation-owned title generation and output validation."""

from __future__ import annotations

import json

from agent.application.model import ChatModel
from conversation.prompts import CONVERSATION_TITLE_SYSTEM_PROMPT
from conversation.repositories.conversation_repository import ConversationRepository


def validate_generated_title(value: str) -> str:
    title = value.strip()
    if not title or len(title) > 60:
        raise ValueError("model returned an invalid conversation title")
    if any(char in title for char in "\x00\r\n<>"):
        raise ValueError("model returned an invalid conversation title")
    return title


class ConversationTitleService:
    def __init__(self, *, model: ChatModel, repository: ConversationRepository) -> None:
        self.model = model
        self.repository = repository

    async def generate(self, *, question: str, answer: str) -> str:
        generated = await self.model.complete_text(
            system_prompt=CONVERSATION_TITLE_SYSTEM_PROMPT,
            user_input=json.dumps(
                {"question": question[:4000], "answer": answer[:2000]},
                ensure_ascii=False,
            ),
            max_output_tokens=128,
        )
        return validate_generated_title(generated)

    async def generate_and_save(
        self,
        *,
        conversation_id: str,
        user_id: str,
        question: str,
        answer: str,
    ) -> str:
        title = await self.generate(question=question, answer=answer)
        await self.repository.update_title(
            conversation_id=conversation_id,
            user_id=user_id,
            title=title,
        )
        return title


__all__ = ["ConversationTitleService", "validate_generated_title"]
