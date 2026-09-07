from __future__ import annotations

import asyncio

import pytest

from domain.core import ResearchObjective
from domain.goal import (
    ExperimentPlanRecord,
    ExperimentPlanRevisionConflictError,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.experiment_plan_repository import (
    PostgresExperimentPlanRepository,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from tests.integration.persistence.test_postgres_source_artifacts import COLLECTION_ID


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

OBJECTIVE_ID = "objective-plan-revisions"


@pytest.fixture
async def experiment_plan_repository(source_repository):
    objective = ResearchObjective.from_mapping(
        {
            "collection_id": COLLECTION_ID,
            "objective_id": OBJECTIVE_ID,
            "question": "How does laser power affect porosity?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
            "seed_document_ids": ["doc_a"],
            "confidence": 0,
            "origin": "chat_assisted",
            "created_by_user_id": "user_source",
            "created_by_tool_call_id": "call-plan-objective",
        }
    )
    await PostgresObjectiveRepository(
        source_repository.session_factory
    ).create_authored_candidate(
        objective,
        created_by_user_id="user_source",
        created_by_tool_call_id="call-plan-objective",
    )
    await PostgresAuthRepository(source_repository.session_factory).add_user(
        {
            "user_id": "user_reviewer",
            "email": "reviewer@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": "2026-09-07T00:30:00+00:00",
        }
    )
    return PostgresExperimentPlanRepository(source_repository.session_factory)


def _plan(**overrides) -> ExperimentPlanRecord:
    payload = {
        "plan_id": "plan-v1",
        "collection_id": COLLECTION_ID,
        "objective_id": OBJECTIVE_ID,
        "title": "Initial plan",
        "content": "Initial approved plan.",
        "status": "draft",
        "source_message_id": None,
        "source_links": [],
        "metadata": {"source": "manual"},
        "created_by": "user_source",
        "created_at": "2026-09-07T00:00:00+00:00",
        "updated_at": "2026-09-07T00:00:00+00:00",
        "updated_by": "user_source",
        "structured_plan": {
            "hypothesis": "Higher laser power may reduce porosity.",
            "measurements": [{"outcome": "porosity", "unit": "%"}],
        },
    }
    payload.update(overrides)
    return ExperimentPlanRecord.from_mapping(payload)


async def test_postgres_round_trips_structured_plan_and_revision_lineage(
    experiment_plan_repository,
) -> None:
    parent = _plan()
    child = _plan(
        plan_id="plan-v2",
        plan_version=2,
        parent_plan_id=parent.plan_id,
        title="Expert-reviewed plan",
        structured_plan={
            "hypothesis": "Higher laser power may reduce porosity.",
            "measurements": [
                {"outcome": "porosity", "method": "image analysis", "unit": "%"}
            ],
            "replicates": 3,
        },
        updated_by="user_reviewer",
        updated_at="2026-09-07T01:00:00+00:00",
    )

    await experiment_plan_repository.upsert_plan(parent)
    stored = await experiment_plan_repository.append_plan_revision(child)

    assert stored == child
    assert (
        await experiment_plan_repository.read_plan(
            COLLECTION_ID, OBJECTIVE_ID, parent.plan_id
        )
        == parent
    )
    assert await experiment_plan_repository.list_plans(
        COLLECTION_ID, OBJECTIVE_ID
    ) == (child,)


async def test_postgres_allows_only_one_concurrent_successor(
    experiment_plan_repository,
) -> None:
    parent = _plan()
    await experiment_plan_repository.upsert_plan(parent)
    candidates = (
        _plan(
            plan_id="plan-v2-a",
            plan_version=2,
            parent_plan_id=parent.plan_id,
            updated_by="user_reviewer",
            updated_at="2026-09-07T01:00:00+00:00",
        ),
        _plan(
            plan_id="plan-v2-b",
            plan_version=2,
            parent_plan_id=parent.plan_id,
            updated_by="user_source",
            updated_at="2026-09-07T01:00:01+00:00",
        ),
    )

    outcomes = await asyncio.gather(
        *(experiment_plan_repository.append_plan_revision(item) for item in candidates),
        return_exceptions=True,
    )

    assert sum(isinstance(item, ExperimentPlanRecord) for item in outcomes) == 1
    assert sum(
        isinstance(item, ExperimentPlanRevisionConflictError) for item in outcomes
    ) == 1
    leaves = await experiment_plan_repository.list_plans(COLLECTION_ID, OBJECTIVE_ID)
    assert len(leaves) == 1
    assert leaves[0].parent_plan_id == parent.plan_id
