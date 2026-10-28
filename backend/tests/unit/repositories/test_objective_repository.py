from __future__ import annotations

import pytest

from domain.core import ResearchObjective
from domain.core.research_objective import build_research_objective_id
from repositories.objective_repository import ObjectiveRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _authored_objective() -> ResearchObjective:
    return ResearchObjective(
        collection_id="col-1",
        objective_id=build_research_objective_id(
            question="How does laser power affect tensile strength?",
            material_scope=("Ti-6Al-4V",),
            variables=("laser power",),
            outcomes=("tensile strength",),
            mechanisms=(),
            constraints=(),
            requested_comparator=None,
        ),
        question="How does laser power affect tensile strength?",
        material_scope=("Ti-6Al-4V",),
        variables=("laser power",),
        outcomes=("tensile strength",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=("paper-1",),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        origin="chat_assisted",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-create",
    )


async def test_authored_candidate_does_not_require_objective_discovery(*, postgres_session_factory) -> None:
    repository = ObjectiveRepository()
    objective = _authored_objective()

    created = await repository.create_authored_candidate(
        objective,
        created_by_user_id="user-1",
        created_by_tool_call_id="call-create",
    )

    assert created.rank == 1
    assert await repository.list_objectives("col-1") == (created,)
    assert (await repository.read("col-1")).research_objectives_ready is False
    assert not hasattr(created, "created_at")
    assert not hasattr(created, "updated_at")

    record = await repository.read_objective_record("col-1", created.objective_id)
    assert record is not None
    assert record.objective == created
    assert record.created_at
    assert record.updated_at
    assert (await repository.list_objective_records("col-1")) == (record,)


@pytest.fixture(autouse=True)
async def research_records(postgres_session_factory, anyio_backend):
    from tests.support.postgres import seed_collection

    await seed_collection(postgres_session_factory, "col-1", document_ids=("paper-1",))
