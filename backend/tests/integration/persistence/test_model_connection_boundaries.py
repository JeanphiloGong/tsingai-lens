from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from infra.persistence.postgres.models.model_connection import ModelConnectionORM
from repositories.model_connection_repository import (
    ModelConnectionRepository,
)

pytestmark = pytest.mark.anyio


async def _insert(session_factory, *, connection_id: str, enabled: bool):
    now = datetime.now(timezone.utc)
    async with session_factory.begin() as database:
        database.add(
            ModelConnectionORM(
                connection_id=connection_id,
                display_name=connection_id,
                base_url="https://model.example.invalid/v1",
                model=f"model-{connection_id}",
                api_key_ref=f"env:LENS_MODEL_KEY_{connection_id.upper().replace('-', '_')}",
                enabled=enabled,
                context_window_tokens=65536,
                max_output_tokens=8192,
                request_timeout_seconds=30,
                created_at=now,
                updated_at=now,
            )
        )


async def test_same_provider_can_offer_multiple_models(postgres_session_factory):
    await _insert(postgres_session_factory, connection_id="lab-b", enabled=True)
    await _insert(postgres_session_factory, connection_id="lab-a", enabled=True)
    repository = ModelConnectionRepository()

    enabled = await repository.list_enabled()
    assert [item.connection_id for item in enabled] == ["lab-a", "lab-b"]
    assert enabled[0].base_url == enabled[1].base_url
    assert [item.model for item in enabled] == ["model-lab-a", "model-lab-b"]
    assert await repository.read("lab-a") == enabled[0]
    assert await repository.read_enabled("lab-b") == enabled[1]


@pytest.mark.parametrize("enabled", [True, False])
async def test_connection_id_is_unique_regardless_of_enabled(
    postgres_session_factory, enabled
):
    await _insert(postgres_session_factory, connection_id="lab-a", enabled=enabled)
    with pytest.raises(IntegrityError):
        await _insert(postgres_session_factory, connection_id="lab-a", enabled=not enabled)

    repository = ModelConnectionRepository()
    current = await repository.read("lab-a")
    assert current is not None and current.enabled is enabled


async def test_missing_and_disabled_connections_are_not_selectable(postgres_session_factory):
    repository = ModelConnectionRepository()
    assert await repository.list_enabled() == ()
    assert await repository.read_enabled("missing") is None
    assert await repository.read("missing") is None

    await _insert(postgres_session_factory, connection_id="lab-a", enabled=False)
    assert await repository.list_enabled() == ()
    assert await repository.read_enabled("lab-a") is None
    disabled = await repository.read("lab-a")
    assert disabled is not None and disabled.enabled is False
