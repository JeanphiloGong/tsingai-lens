from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.capabilities.published_findings import InspectPublishedFindingCapability
from application.chat.capabilities.contracts import CapabilityExecutionContext


def _context() -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        session_id="session-1",
        user_id="user-1",
        collection_id="col-1",
        tool_call_id="call-1",
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_child_empty_feedback_does_not_erase_parent_review():
    async def detail(collection, objective, finding, *, analysis_version):
        return {"analysis_version": analysis_version, "finding": {
            "finding_id": finding, "parent_finding_id": "parent" if finding == "child" else None,
        }}

    async def feedback(**key):
        return [SimpleNamespace(to_record=lambda: {"note": "Original overclaim"})] if key["finding_id"] == "parent" else []

    capability = InspectPublishedFindingCapability(
        collection_service=SimpleNamespace(get_collection_for_user=AsyncMock()),
        objective_analysis_service=SimpleNamespace(
            get_finding=detail, list_evidence=AsyncMock(return_value={"items": [], "total": 0}),
        ),
        finding_feedback_service=SimpleNamespace(list_feedback=feedback, list_curations=AsyncMock(return_value=[])),
    )
    child = await capability.execute(_context(), capability.spec.input_model(
        objective_id="objective-1", finding_id="child", analysis_version=3,
    ))
    parent = await capability.execute(_context(), capability.spec.input_model(
        objective_id="objective-1", finding_id="parent", analysis_version=1,
    ))
    assert child.data["feedback_records"] == []
    assert child.data["review_scope"] == {
        "collection_id": "col-1", "objective_id": "objective-1", "analysis_version": 3,
        "finding_id": "child", "includes_ancestor_reviews": False,
    }
    assert parent.data["feedback_records"] == [{"note": "Original overclaim"}]
    assert parent.data["review_scope"]["analysis_version"] == 1
