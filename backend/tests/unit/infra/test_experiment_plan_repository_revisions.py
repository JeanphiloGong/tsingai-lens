from __future__ import annotations

import pytest

from domain.goal import (
    ExperimentPlanRecord,
    ExperimentPlanRevisionConflictError,
)
from tests.support.experiment_plan_repository import (
    InMemoryExperimentPlanRepository,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _plan(**overrides) -> ExperimentPlanRecord:
    payload = {
        "plan_id": "plan-v1",
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "title": "Initial plan",
        "content": "Initial approved plan.",
        "status": "draft",
        "source_message_id": None,
        "source_links": [],
        "metadata": {"source": "manual"},
        "created_by": "researcher-1",
        "created_at": "2026-09-07T00:00:00+00:00",
        "updated_at": "2026-09-07T00:00:00+00:00",
        "updated_by": "researcher-1",
        "structured_plan": {"hypothesis": "Initial hypothesis"},
    }
    payload.update(overrides)
    return ExperimentPlanRecord.from_mapping(payload)


async def test_append_preserves_history_and_lists_only_the_leaf_revision() -> None:
    repository = InMemoryExperimentPlanRepository()
    parent = _plan()
    child = _plan(
        plan_id="plan-v2",
        plan_version=2,
        parent_plan_id=parent.plan_id,
        title="Reviewed plan",
        content="Reviewed and approved plan.",
        structured_plan={"hypothesis": "Reviewed hypothesis"},
        updated_by="researcher-2",
        updated_at="2026-09-07T01:00:00+00:00",
    )

    await repository.upsert_plan(parent)
    stored = await repository.append_plan_revision(child)

    assert stored == child
    assert await repository.read_plan("col-1", "objective-1", parent.plan_id) == parent
    assert await repository.list_plans("col-1", "objective-1") == (child,)


async def test_append_rejects_a_second_successor_of_the_same_revision() -> None:
    repository = InMemoryExperimentPlanRepository()
    parent = _plan()
    first_child = _plan(
        plan_id="plan-v2-a",
        plan_version=2,
        parent_plan_id=parent.plan_id,
        updated_by="researcher-2",
    )
    competing_child = _plan(
        plan_id="plan-v2-b",
        plan_version=2,
        parent_plan_id=parent.plan_id,
        updated_by="researcher-3",
    )
    await repository.upsert_plan(parent)
    await repository.append_plan_revision(first_child)

    with pytest.raises(ExperimentPlanRevisionConflictError):
        await repository.append_plan_revision(competing_child)

    assert await repository.list_plans("col-1", "objective-1") == (first_child,)


async def test_existing_revision_is_immutable() -> None:
    repository = InMemoryExperimentPlanRepository()
    original = _plan()
    await repository.upsert_plan(original)

    with pytest.raises(ExperimentPlanRevisionConflictError):
        await repository.upsert_plan(_plan(title="Silently overwritten"))

    assert await repository.read_plan("col-1", "objective-1", original.plan_id) == original
