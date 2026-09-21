from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_probe_module():
    script_dir = Path(__file__).resolve().parents[3] / "scripts" / "benchmarks"
    sys.path.insert(0, str(script_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "paper_experiment_chain_probe",
            script_dir / "paper_experiment_chain_probe.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(script_dir))


@pytest.fixture(scope="module")
def probe():
    return _load_probe_module()


def _execution_report() -> dict:
    tasks = (
        "document_profile",
        "paper_map",
        "objective_paper_frame",
        "objective_evidence_extraction",
        "finding_synthesis",
    )
    return {
        "runtime": {"model": "gpt-5.5"},
        "execution_stats": {
            "prompt_versions": {task: "v1" for task in tasks},
            "unreported_request_count": 0,
            "model_usage": [
                {
                    "model_name": "gpt-5.5",
                    "request_count": 6,
                    "unreported_request_count": 0,
                }
            ],
        },
        "model_traces": {
            "objective_pipeline": [
                {
                    "task_type": task,
                    "trace_status": "available",
                    "model": "gpt-5.5",
                    "raw_output": "recorded provider output",
                }
                for task in tasks
            ],
        },
    }


def test_probe_accepts_complete_execution_metadata_with_an_internal_retry(probe):
    report = _execution_report()

    check = probe._live_model_boundary_check(
        report=report, comparable_evidence_count=1
    )

    assert check["passed"] is True
    assert check["detail"]["request_count"] == 6
    assert check["detail"]["recorded_trace_count"] == 5


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda report: report["execution_stats"].update(unreported_request_count=1),
        lambda report: report["execution_stats"]["model_usage"][0].update(
            unreported_request_count=1
        ),
        lambda report: report["model_traces"]["objective_pipeline"].append(
            {
                "task_type": "paper_map",
                "trace_status": "failed",
                "model": "gpt-5.5",
                "raw_output": "failed attempt",
            }
        ),
        lambda report: report["model_traces"]["objective_pipeline"].append(
            {
                "task_type": "paper_map",
                "trace_status": "available",
                "model": "gpt-5.5",
                "raw_output": "   ",
            }
        ),
        lambda report: report["model_traces"]["objective_pipeline"].append(
            {
                "task_type": "paper_map",
                "trace_status": "available",
                "model": "unexpected-model",
                "raw_output": "recorded provider output",
            }
        ),
        lambda report: report["execution_stats"]["model_usage"][0].update(
            request_count=4
        ),
    ],
    ids=(
        "aggregate-unreported",
        "per-model-unreported",
        "failed-additional-trace",
        "empty-additional-trace",
        "wrong-model-additional-trace",
        "fewer-requests-than-traces",
    ),
)
def test_probe_rejects_incomplete_execution_metadata(probe, corrupt):
    report = _execution_report()
    corrupt(report)

    check = probe._live_model_boundary_check(
        report=report, comparable_evidence_count=1
    )

    assert check["passed"] is False


def test_probe_records_each_table_repair_trace(probe, monkeypatch):
    extractor = probe.RecordingPaperFactsExtractor.__new__(
        probe.RecordingPaperFactsExtractor
    )
    extractor.traces = []
    extractor.last_trace = None

    def repair(_self, payload):
        _self.last_trace = {
            "task_type": "paper_fact_table_matrix_repair",
            "trace_status": "available",
            "raw_output": payload["output"],
        }
        return payload["output"]

    monkeypatch.setattr(probe.PaperFactsExtractor, "repair_table_matrix", repair)

    assert extractor.repair_table_matrix({"output": "first"}) == "first"
    assert extractor.repair_table_matrix({"output": "second"}) == "second"
    assert [trace["raw_output"] for trace in extractor.traces] == [
        "first",
        "second",
    ]
