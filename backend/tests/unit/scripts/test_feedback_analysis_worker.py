from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib
import pytest

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend(): return "asyncio"

@pytest.mark.parametrize("name", ["feedback_analysis_worker", "correction_signal_analysis_worker", "tool_failure_analysis_worker", "dataset_sample_worker"])
async def test_worker_initializes_only_its_resources_and_disposes_on_cancel(monkeypatch, name):
    module = importlib.import_module("scripts."+name)
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(module, "DatabaseSettings", lambda: object())
    monkeypatch.setattr(module, "build_database_engine", lambda _: engine)
    monkeypatch.setattr(module, "AsyncSessionLocal", SimpleNamespace(configure=lambda **_: None))
    monkeypatch.setattr(module.AnalysisJobRepo, "recover_expired_jobs", AsyncMock())
    kind = {"feedback_analysis_worker":"feedback_analysis", "correction_signal_analysis_worker":"correction_signal_analysis", "tool_failure_analysis_worker":"tool_failure_analysis", "dataset_sample_worker":"dataset_sample_build"}[name]
    monkeypatch.setattr(module.AnalysisJobRepo, "claim_next_"+kind+"_job", AsyncMock(side_effect=asyncio.CancelledError()))
    if name=="dataset_sample_worker":
        monkeypatch.setattr(module.FeedbackDatasetSampleRepo, "backfill_existing_cases", AsyncMock())
    closed=[]
    if hasattr(module,"AsyncOpenAI"):
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*_):closed.append(True)
        monkeypatch.setattr(module,"AsyncOpenAI",lambda **_:Client())
    with pytest.raises(asyncio.CancelledError): await module.run_loop(2)
    engine.dispose.assert_awaited_once()
    if hasattr(module,"AsyncOpenAI"): assert closed == [True]

import asyncio

async def test_requeue_uses_only_database_and_closes(monkeypatch):
    from scripts import feedback_analysis_worker as module
    engine=SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(module,"DatabaseSettings",lambda:object())
    monkeypatch.setattr(module,"build_database_engine",lambda _:engine)
    monkeypatch.setattr(module,"AsyncSessionLocal",SimpleNamespace(configure=lambda **_:None))
    requeue=AsyncMock(return_value=SimpleNamespace(status="pending"))
    monkeypatch.setattr(module.AnalysisJobRepo,"requeue_failed_feedback_analysis_job",requeue)
    assert await module.requeue_failed_job("job-1") == "pending"
    assert requeue.call_args.kwargs["job_id"] == "job-1"
    engine.dispose.assert_awaited_once()
