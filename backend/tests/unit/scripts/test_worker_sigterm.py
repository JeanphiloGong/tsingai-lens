"""Real process termination must drain work before closing owned resources."""

from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize(
    "name,has_client",
    [
        ("run_document_preparation", True),
        ("run_objective_discovery", True),
        ("run_objective_analysis", True),
        ("feedback_analysis_worker", False),
        ("correction_signal_analysis_worker", True),
        ("tool_failure_analysis_worker", False),
        ("dataset_sample_worker", True),
    ],
)
def test_sigterm_drains_work_and_closes_resources(tmp_path, name, has_client):
    output = tmp_path / "events"
    script = """
import asyncio
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

module = importlib.import_module("scripts." + sys.argv[1])
output = Path(sys.argv[2])

def event(value):
    with output.open("a") as stream:
        stream.write(value + "\\n")

async def wait_for_shutdown(*args, **kwargs):
    event("started")
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.sleep(0)
        event("drained")

async def dispose():
    event("database_closed")

class Client:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        self.close()
    def close(self):
        event("client_closed")

module.DatabaseSettings = lambda: object()
module.build_database_engine = lambda _: SimpleNamespace(dispose=dispose)
module.AsyncSessionLocal = SimpleNamespace(configure=lambda **_: None)
if sys.argv[1].startswith("run_"):
    resource = SimpleNamespace(client=Client())
    if sys.argv[1] == "run_document_preparation":
        module.build_default_document_profile_extractor = lambda: resource
        module.FileCollectionWorkspace = lambda _: SimpleNamespace(root_dir=output.parent)
        module.FileObjectStore = lambda _: object()
    else:
        module.build_default_structured_response_client = lambda: resource
    module.run_forever = wait_for_shutdown
else:
    module.AnalysisJobRepo.recover_expired_jobs = AsyncMock()
    kind = {
        "feedback_analysis_worker": "feedback_analysis",
        "correction_signal_analysis_worker": "correction_signal_analysis",
        "tool_failure_analysis_worker": "tool_failure_analysis",
        "dataset_sample_worker": "dataset_sample_build",
    }[sys.argv[1]]
    setattr(module.AnalysisJobRepo, "claim_next_" + kind + "_job", wait_for_shutdown)
    if hasattr(module, "AsyncOpenAI"):
        module.AsyncOpenAI = lambda **_: Client()
    if sys.argv[1] == "dataset_sample_worker":
        module.FeedbackDatasetSampleRepo.backfill_existing_cases = AsyncMock()
sys.argv = ["worker", "--once"]
module.main()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, name, str(output)],
        cwd=Path(__file__).resolve().parents[3],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not output.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                pytest.fail("Worker did not start")
            time.sleep(0.02)
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"Worker exited before termination: {stdout} {stderr}")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        assert output.read_text().splitlines() == [
            "started",
            "drained",
            *(["client_closed"] if has_client else []),
            "database_closed",
        ]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
