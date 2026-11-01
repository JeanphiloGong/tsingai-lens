from application.chat.capabilities import finding_authoring
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.finding_authoring import (
    CreateFindingDraftCapability,
    CreateFindingDraftToolRequest,
    CreateFindingVersionCapability,
    CreateFindingVersionToolRequest,
)
from application.core.objectives import finding_authoring_service
from domain.chat import ToolResultStatus
from exceptions import ResourceNotFoundException, ServerException

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["draft", "version"])
def finding_call(request):
    context = CapabilityExecutionContext(
        session_id="chat-1",
        user_id="researcher-1",
        collection_id="col-1",
        tool_call_id="finding-1",
    )
    arguments = dict(
        objective_id="objective-1",
        source_analysis_version=1,
        selection_ids=["selection-1"],
    )
    if request.param == "draft":
        finding_authoring.finding_authoring_service = finding_authoring_service
        capability = CreateFindingDraftCapability()
        payload = CreateFindingDraftToolRequest(draft_id="draft-1", **arguments)
        expected_code = "finding_selection_rejected"
    else:
        finding_authoring.finding_authoring_service = finding_authoring_service
        capability = CreateFindingVersionCapability()
        payload = CreateFindingVersionToolRequest(**arguments)
        expected_code = "finding_version_rejected"
    return capability, context, payload, expected_code


@pytest.mark.parametrize(
    "rejection",
    [
        "stale_analysis",
        "missing_objective",
        "missing_collection",
        "unknown_selection",
        "unknown_group",
    ],
)
async def test_finding_business_rejection_returns_tool_result_without_writing(
    finding_call,
    rejection,
    monkeypatch,
):
    capability, context, payload, expected_code = finding_call
    authorize = AsyncMock(return_value={"collection_id": "col-1"})
    if rejection == "missing_collection":
        authorize.side_effect = ResourceNotFoundException("Collection is unavailable.")
    monkeypatch.setattr(
        finding_authoring_service.collection_service,
        "get_collection_for_user",
        authorize,
    )
    objective = SimpleNamespace(
        active_analysis_version=2 if rejection == "stale_analysis" else 1,
    )
    queue = AsyncMock()
    monkeypatch.setattr(
        finding_authoring_service,
        "ObjectiveRepo",
        SimpleNamespace(
            read_objective=AsyncMock(
                return_value=None if rejection == "missing_objective" else objective,
            ),
            read_analysis=AsyncMock(return_value=SimpleNamespace(status="succeeded")),
            queue_analysis=queue,
        ),
    )
    monkeypatch.setattr(
        finding_authoring_service.experiment_query_service,
        "read_analysis_bundle",
        AsyncMock(return_value=SimpleNamespace(groups=(), selections=())),
    )
    if rejection == "unknown_group":
        payload = payload.model_copy(update={"comparison_group_ids": ["missing-group"]})

    result = await capability.execute(context, payload)

    assert result.status is ToolResultStatus.FAILED
    assert result.error_code == expected_code
    assert result.tool_call_id == context.tool_call_id
    assert "published analysis" in result.error_message
    assert not result.data
    queue.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("storage fault"),
        FileNotFoundError("storage fault"),
        RuntimeError("storage fault"),
        ServerException(),
    ],
)
async def test_finding_unexpected_fault_propagates_to_runner(
    finding_call,
    error,
    monkeypatch,
):
    capability, context, payload, _expected_code = finding_call
    monkeypatch.setattr(
        finding_authoring_service.collection_service,
        "get_collection_for_user",
        AsyncMock(side_effect=error),
    )

    with pytest.raises(type(error)) as caught:
        await capability.execute(context, payload)

    assert caught.value is error
