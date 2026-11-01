from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.objective_analysis import (
    ConfirmObjectiveCapability,
    ConfirmObjectiveToolRequest,
)
from application.chat.capabilities.objective_candidate import (
    CreateObjectiveCandidateCapability,
    CreateObjectiveCandidateToolRequest,
)
from application.core.objectives import objective_authoring_service
from domain.chat import ToolResultStatus
from exceptions import RequestInvalidException, ResourceConflictException, ResourceNotFoundException

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["confirm", "create"])
def objective_action(request):
    if request.param == "confirm":
        return (
            ConfirmObjectiveCapability(),
            ConfirmObjectiveToolRequest(objective_id="obj-1"),
            "confirm_objective",
            "objective_confirmation_rejected",
        )
    return (
        CreateObjectiveCandidateCapability(),
        CreateObjectiveCandidateToolRequest(
            question="How does laser power affect porosity?",
            variables=["laser power"],
            outcomes=["porosity"],
        ),
        "create_chat_assisted_candidate",
        "objective_candidate_rejected",
    )


@pytest.mark.parametrize(
    "exception_type",
    [RequestInvalidException, ResourceConflictException, ResourceNotFoundException],
)
async def test_objective_tool_preserves_rejection_and_repair_reason(
    monkeypatch, objective_action, exception_type,
):
    capability, arguments, operation, rejection_code = objective_action
    error = exception_type(
        "The approved Objective basis is unavailable; inspect the current version.",
        data={"code": "objective_basis_unavailable", "objective_id": "obj-1"},
    )
    monkeypatch.setattr(objective_authoring_service, operation, AsyncMock(side_effect=error))

    result = await capability.execute(
        CapabilityExecutionContext(
            session_id="chat-1", user_id="user-1", collection_id="col-1", tool_call_id="call-1",
        ),
        arguments,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code == rejection_code
    assert error.message in result.error_message
    assert result.data == error.data


@pytest.mark.parametrize("exception_type", [ValueError, FileNotFoundError, RuntimeError])
async def test_objective_tool_does_not_disguise_internal_faults(
    monkeypatch, objective_action, exception_type,
):
    capability, arguments, operation, _ = objective_action
    monkeypatch.setattr(
        objective_authoring_service, operation,
        AsyncMock(side_effect=exception_type("private implementation failure")),
    )

    with pytest.raises(exception_type, match="private implementation failure"):
        await capability.execute(
            CapabilityExecutionContext(
                session_id="chat-1", user_id="user-1", collection_id="col-1", tool_call_id="call-1",
            ),
            arguments,
        )


async def test_confirm_missing_objective_is_rejected_without_writing(
    monkeypatch, postgres_session_factory,
):
    from repositories.objective_repository import ObjectiveRepository

    monkeypatch.setattr(objective_authoring_service, "ObjectiveRepo", ObjectiveRepository())
    monkeypatch.setattr(
        objective_authoring_service, "collection_service",
        SimpleNamespace(get_collection_for_user=AsyncMock()),
    )

    result = await ConfirmObjectiveCapability().execute(
        CapabilityExecutionContext(
            session_id="chat-1", user_id="local-user", collection_id="missing-col", tool_call_id="call-1",
        ),
        ConfirmObjectiveToolRequest(objective_id="missing-objective"),
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code == "objective_confirmation_rejected"
    assert result.data["code"] == "objective_not_found"
    assert await objective_authoring_service.ObjectiveRepo.read_objective(
        "missing-col", "missing-objective",
    ) is None
