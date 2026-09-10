from __future__ import annotations

import pytest

from application.core.objectives.analysis_records import (
    list_all_evidence,
    list_all_findings,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Repository:
    def __init__(self) -> None:
        self.evidence_pages = [(["evidence-1"], 2), (["evidence-2"], 2)]
        self.finding_pages = [(["finding-1"], 2), (["finding-2"], 2)]

    async def list_evidence(self, *args, offset: int, limit: int):
        del args, limit
        page, total = self.evidence_pages[offset]
        return page, total

    async def list_findings(self, *args, offset: int, limit: int):
        del args, limit
        page, total = self.finding_pages[offset]
        return page, total


async def test_analysis_record_helpers_collect_all_pages() -> None:
    repository = _Repository()

    assert await list_all_evidence(repository, "col-1", "obj-1", 1) == (
        "evidence-1",
        "evidence-2",
    )
    assert await list_all_findings(repository, "col-1", "obj-1", 1) == (
        "finding-1",
        "finding-2",
    )


async def test_analysis_record_helper_rejects_a_stalled_page() -> None:
    repository = _Repository()
    repository.evidence_pages = [([], 1)]

    with pytest.raises(
        RuntimeError,
        match="objective Evidence pagination did not advance",
    ):
        await list_all_evidence(repository, "col-1", "obj-1", 1)


async def test_analysis_record_helper_keeps_callers_error_contract() -> None:
    repository = _Repository()
    repository.finding_pages = [([], 1)]

    with pytest.raises(
        RuntimeError,
        match="Finding pagination ended before total",
    ):
        await list_all_findings(
            repository,
            "col-1",
            "obj-1",
            1,
            error_message="Finding pagination ended before total",
        )
