from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from infra.persistence.postgres.models.model_connection import ModelConnectionRow
from repositories.model_connection_repository import (
    ModelConnectionRepository,
)

pytestmark = pytest.mark.anyio


async def _insert(session_factory, *, connection_id: str, revision: int, enabled: bool):
    now = datetime.now(timezone.utc)
    async with session_factory.begin() as database:
        database.add(
            ModelConnectionRow(
                connection_id=connection_id,
                revision=revision,
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


async def test_directory_hides_disabled_revisions_and_keeps_history(postgres_session_factory):
    await _insert(postgres_session_factory, connection_id="lab-a", revision=1, enabled=False)
    await _insert(postgres_session_factory, connection_id="lab-a", revision=2, enabled=True)
    repository = ModelConnectionRepository()

    enabled = await repository.list_enabled()
    old = await repository.read("lab-a", 1)
    current = await repository.read_enabled("lab-a")

    assert [(item.connection_id, item.revision) for item in enabled] == [("lab-a", 2)]
    assert old is not None and old.enabled is False
    assert current is not None and current.revision == 2


async def test_postgres_partial_unique_index_rejects_two_enabled_revisions(postgres_session_factory):
    await _insert(postgres_session_factory, connection_id="lab-a", revision=1, enabled=True)
    with pytest.raises(IntegrityError):
        await _insert(postgres_session_factory, connection_id="lab-a", revision=2, enabled=True)

    repository = ModelConnectionRepository()
    current = await repository.read_enabled("lab-a")
    assert current is not None and current.revision == 1
    assert await repository.read("lab-a", 2) is None


async def test_missing_and_disabled_connections_are_not_selectable(postgres_session_factory):
    repository = ModelConnectionRepository()
    assert await repository.list_enabled() == ()
    assert await repository.read_enabled("missing") is None
    assert await repository.read("missing", 1) is None

    await _insert(postgres_session_factory, connection_id="lab-a", revision=1, enabled=False)
    assert await repository.list_enabled() == ()
    assert await repository.read_enabled("lab-a") is None
    assert await repository.read("lab-a", 1) is not None
    assert await repository.read("lab-a", 2) is None


@pytest.mark.parametrize("revision", [0, -1])
async def test_postgres_rejects_nonpositive_revisions(postgres_session_factory, revision):
    with pytest.raises(IntegrityError):
        await _insert(
            postgres_session_factory, connection_id="lab-a", revision=revision, enabled=True
        )
    assert await ModelConnectionRepository().list_enabled() == ()
