from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_projection_check_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "check_collection_frontend_projection.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_collection_frontend_projection",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_frontend_projection_payloads_passes_clean_projection():
    check = _load_projection_check_module()

    summary = check.evaluate_frontend_projection_payloads(
        collection_id="col-test",
        material_id="mat-316l-stainless-steel",
        objectives={
            "objectives": [
                {
                    "objective_id": "obj-1",
                    "process_axes": ["laser power", "scanning speed"],
                }
            ]
        },
        material_profile={
            "state": "ready",
            "measured_properties": [{"property": "elongation"}],
            "sample_matrix": {"rows": [{"sample_id": "S1"}]},
        },
    )

    assert summary["status"] == "pass"
    assert summary["objective_count"] == 1
    assert summary["max_process_axis_count"] == 2
    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_frontend_projection_payloads_fails_polluted_projection():
    check = _load_projection_check_module()

    summary = check.evaluate_frontend_projection_payloads(
        collection_id="col-test",
        material_id="mat-316l-stainless-steel",
        objectives={
            "objectives": [
                {
                    "objective_id": "obj-1",
                    "process_axes": [
                        "laser power",
                        "scanning speed",
                        "energy density",
                        "scan strategy",
                        "heat treatment",
                        "build orientation",
                        "shielding gas",
                    ],
                }
            ]
        },
        material_profile={
            "state": "ready",
            "measured_properties": [
                {
                    "property": "elongation",
                    "display_range": "135 W-750 mm/s sample increase ductility",
                }
            ],
            "sample_matrix": {"rows": []},
        },
    )

    failed_names = {
        item["name"] for item in summary["checks"] if item["status"] == "fail"
    }
    assert summary["status"] == "fail"
    assert "objective process axes stay display bounded" in failed_names
    assert "material sample matrix rows are available" in failed_names
    assert "material profile excludes forbidden term '135 W-750'" in failed_names
