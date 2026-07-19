from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.persistence.capture_baseline import capture_baseline, measure_capture


BACKEND_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "persistence_revision"
SCENARIO_PATH = FIXTURE_DIR / "scenario.json"
EXPECTED_PATH = FIXTURE_DIR / "expected-baseline.json"
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "persistence" / "capture_baseline.py"


def test_capture_baseline_matches_reviewed_golden() -> None:
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))

    assert capture_baseline(scenario) == expected


def test_capture_baseline_rejects_missing_required_family() -> None:
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    scenario["records"].pop("feedback")

    with pytest.raises(ValueError, match="missing required record family: feedback"):
        capture_baseline(scenario)


def test_capture_baseline_rejects_orphaned_evidence_anchor() -> None:
    scenario = deepcopy(json.loads(SCENARIO_PATH.read_text(encoding="utf-8")))
    scenario["records"]["research_understandings"][0]["evidence_refs"][0][
        "anchor_ids"
    ] = ["anchor_missing"]

    with pytest.raises(ValueError, match="unresolved evidence anchor: anchor_missing"):
        capture_baseline(scenario)


def test_capture_baseline_cli_writes_deterministic_and_timing_reports(tmp_path) -> None:
    output_path = tmp_path / "baseline.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--fixture",
            str(SCENARIO_PATH),
            "--output",
            str(output_path),
            "--iterations",
            "5",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    assert payload["baseline"] == expected
    assert payload["performance"]["iterations"] == 5
    assert payload["performance"]["p95_ms"] >= 0

    direct_measurement = measure_capture(
        json.loads(SCENARIO_PATH.read_text(encoding="utf-8")),
        iterations=5,
    )
    assert direct_measurement["iterations"] == 5
    assert direct_measurement["median_ms"] >= 0
