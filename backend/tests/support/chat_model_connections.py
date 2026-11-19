"""Keep existing scripted-runner scenarios independent of provider configuration."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.session_service import ChatSessionService


def make_scripted_chat_service(runner):
    service = ChatSessionService(
        capabilities=runner.capabilities,
        limits=runner.limits,
        context_builder=runner.context_builder,
    )
    service.scripted_runner = runner
    return service


@pytest.fixture
def scripted_chat_runner(monkeypatch):
    connection = SimpleNamespace(
        connection_id="scripted-test", display_name="Scripted model", model="scripted-test"
    )
    monkeypatch.setattr(ChatSessionService, "_resolve_model_connection", AsyncMock(return_value=connection))

    @asynccontextmanager
    async def use_scripted_runner(service, selected_connection):
        yield service.scripted_runner

    monkeypatch.setattr(ChatSessionService, "_runner_for_connection", use_scripted_runner)
