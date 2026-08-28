from __future__ import annotations

import pytest

from domain.core import ResearchObjective
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _authored_objective() -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col-1",
            "question": "How does laser power affect tensile strength?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["tensile strength"],
            "seed_document_ids": ["paper-1"],
            "confidence": 0,
            "origin": "chat_assisted",
            "created_by_user_id": "user-1",
            "created_by_tool_call_id": "call-create",
        }
    )


async def test_authored_candidate_does_not_require_objective_discovery() -> None:
    repository = MemoryObjectiveRepository()
    objective = _authored_objective()

    created = await repository.create_authored_candidate(
        objective,
        created_by_user_id="user-1",
        created_by_tool_call_id="call-create",
    )

    assert created.rank == 1
    assert await repository.list_objectives("col-1") == (created,)
    assert (await repository.read("col-1")).research_objectives_ready is False
