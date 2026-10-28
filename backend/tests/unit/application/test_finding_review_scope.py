from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from domain.evaluation import FindingFeedback

import pytest

from application.chat.capabilities.published_findings import InspectPublishedFindingCapability
from application.chat.capabilities.contracts import CapabilityExecutionContext
from dataclasses import replace
from application.chat.context_builder import ChatContextBuilder
import json


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
        return [FindingFeedback(feedback_id="feedback-1", collection_id="col-1", objective_id="objective-1", analysis_version=1, finding_id="parent", review_status="incorrect", issue_type="overclaim", note="Original overclaim", reviewer="user-1", created_at="2026-09-06T00:00:00+00:00")] if key["finding_id"] == "parent" else []

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
    assert len(parent.data["feedback_records"]) == 1
    assert parent.data["feedback_records"][0]["note"] == "Original overclaim"
    assert parent.data["review_scope"]["analysis_version"] == 1


@pytest.mark.anyio
async def test_large_finding_evidence_is_paged_without_losing_complete_records():
    items = [{"evidence_id": f"ev-{i}", "document_id": "paper-1",
              "source_excerpt": "拉伸结果来源" * 200} for i in range(10)]
    async def evidence(*args, offset, limit, **kwargs):
        return {"items": items[offset:offset + limit], "total": len(items)}
    finding = {"finding_id": "finding-1", "selection_ids": ["selection-1"]}
    capability = InspectPublishedFindingCapability(
        collection_service=SimpleNamespace(get_collection_for_user=AsyncMock()),
        objective_analysis_service=SimpleNamespace(
            get_finding=AsyncMock(return_value={"analysis_version": 1, "finding": finding}),
            list_evidence=evidence),
        finding_feedback_service=SimpleNamespace(
            list_feedback=AsyncMock(return_value=[]), list_curations=AsyncMock(return_value=[])),
    )
    collected = []
    offset = 0
    while offset is not None:
        result = await capability.execute(_context(), capability.spec.input_model(
            objective_id="objective-1", finding_id="finding-1", evidence_offset=offset))
        assert result.status.value == "succeeded"
        assert result.data["finding"] == finding
        assert ChatContextBuilder.estimate_tokens({
            "role": "tool", "tool_call_id": result.tool_call_id,
            "content": json.dumps({
                "tool_call_id": result.tool_call_id,
                "status": result.status.value,
                "data": deepcopy(dict(result.data)),
                "resource_refs": [
                    {
                        "resource_type": item.resource_type,
                        "resource_id": item.resource_id,
                        "href": item.href,
                    }
                    for item in result.resource_refs
                ],
                "warnings": list(result.warnings),
                "error_code": result.error_code,
                "error_message": result.error_message,
            }, ensure_ascii=True, separators=(",", ":")),
        }) <= _context().max_result_tokens
        collected.extend(result.data["evidence"])
        next_offset = result.data["next_evidence_offset"]
        assert next_offset is None or next_offset > offset
        offset = next_offset
    assert collected == items
    oversized = replace(_context(), max_result_tokens=500)
    result = await capability.execute(oversized, capability.spec.input_model(
        objective_id="objective-1", finding_id="finding-1"))
    assert result.error_code == "finding_read_exceeds_budget"
    assert not result.data
