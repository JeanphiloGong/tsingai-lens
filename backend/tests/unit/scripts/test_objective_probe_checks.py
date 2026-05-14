from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_probe_checks_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "objective_probe_checks.py"
    )
    spec = importlib.util.spec_from_file_location(
        "objective_probe_checks",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_requires_cross_table_context_join_when_context_table_is_distinct():
    checks = _load_probe_checks_module()

    assert checks.requires_cross_table_context_join(
        [
            _route(
                role="current_experimental_evidence",
                source_ref="table-results",
                column_roles={"yield strength": "yield_strength"},
            ),
            _route(
                role="process_or_treatment",
                source_ref="table-process",
                column_roles={"scan speed": "process_parameter"},
            ),
        ]
    )


def test_does_not_require_cross_table_context_join_for_same_result_table():
    checks = _load_probe_checks_module()

    assert not checks.requires_cross_table_context_join(
        [
            _route(
                role="current_experimental_evidence",
                source_ref="table-results",
                column_roles={"yield strength": "yield_strength"},
            ),
            _route(
                role="process_or_treatment",
                source_ref="table-results",
                column_roles={"scan speed": "process_parameter"},
            ),
        ]
    )


def test_does_not_require_cross_table_context_join_without_context_route():
    checks = _load_probe_checks_module()

    assert not checks.requires_cross_table_context_join(
        [
            _route(
                role="current_experimental_evidence",
                source_ref="table-results",
                column_roles={"yield strength": "yield_strength"},
            ),
        ]
    )


def test_build_cross_table_context_join_check_fails_only_when_required():
    checks = _load_probe_checks_module()

    required_check = checks.build_cross_table_context_join_check(
        routes=[
            _route(role="current_experimental_evidence", source_ref="table-results"),
            _route(role="test_condition", source_ref="table-conditions"),
        ],
        measurement_units_with_context_join=0,
    )
    not_required_check = checks.build_cross_table_context_join_check(
        routes=[
            _route(role="current_experimental_evidence", source_ref="table-results"),
            _route(role="test_condition", source_ref="table-results"),
        ],
        measurement_units_with_context_join=0,
    )

    assert required_check["status"] == "fail"
    assert required_check["detail"] == "value=0; structural_requirement=required"
    assert not_required_check["status"] == "pass"
    assert not_required_check["detail"] == (
        "value=0; structural_requirement=not_required"
    )


def test_build_cross_table_context_join_check_warns_when_context_is_resolved():
    checks = _load_probe_checks_module()

    resolved_context_check = checks.build_cross_table_context_join_check(
        routes=[
            _route(role="current_experimental_evidence", source_ref="table-results"),
            _route(role="test_condition", source_ref="table-conditions"),
        ],
        measurement_units_with_context_join=0,
        measurement_units_with_process_context=3,
    )

    assert resolved_context_check["status"] == "warn"
    assert resolved_context_check["detail"] == (
        "value=0; structural_requirement=required; process_context_value=3"
    )


def _route(
    *,
    role: str,
    source_ref: str,
    column_roles: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "objective_id": "obj-1",
        "document_id": "doc-1",
        "source_kind": "table",
        "source_ref": source_ref,
        "role": role,
        "extractable": True,
        "column_roles": column_roles or {"condition": "test_condition"},
    }
