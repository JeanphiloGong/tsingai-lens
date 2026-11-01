"""Keep existing scripted-runner scenarios independent of provider configuration."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.session_service import ChatSessionService


@pytest.fixture
def scripted_chat_runner(monkeypatch):
    connection = SimpleNamespace(connection_id="scripted-test", display_name="Scripted model")
    monkeypatch.setattr(ChatSessionService, "_resolve_model_connection", AsyncMock(return_value=connection))

    @asynccontextmanager
    async def use_scripted_runner(service, selected_connection):
        yield service.runner

    monkeypatch.setattr(ChatSessionService, "_runner_for_connection", use_scripted_runner)
