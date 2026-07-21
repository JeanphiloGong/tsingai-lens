from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_merge_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "merge_expert_decision_board.py"
    )
    spec = importlib.util.spec_from_file_location(
        "merge_expert_decision_board",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _template_row(**overrides):
    row = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "action": "skip",
        "issue_type": "",
        "expert_note": "",
        "statement": "Preheating improved ductility.",
        "variables": ["preheating"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "support_grade": "partial",
        "acceptance_gate": {
            "accept_allowed": True,
            "requires_correction": False,
            "accept_blockers": [],
        },
        "protocol_blocking_missing": [],
        "curated_evidence_ref_ids": ["ev-1"],
        "suggested_target": {
            "statement": "Preheating improved ductility.",
            "variables": ["preheating"],
            "outcomes": ["ductility"],
            "direction": "increase",
            "support_grade": "partial",
            "evidence_ref_ids": ["ev-1"],
        },
    }
    row.update(overrides)
    return row


def _board_row(**overrides):
    row = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "finding_id": "finding-1",
        "expert_action": "",
        "issue_type": "",
        "expert_note": "",
        "corrected_statement": "",
        "corrected_variables": "",
        "corrected_mediators": "",
        "corrected_outcomes": "",
        "corrected_direction": "",
        "corrected_scope_summary": "",
        "corrected_support_grade": "",
        "corrected_evidence_ref_ids": "",
        "accept_allowed": "yes",
    }
    row.update(overrides)
    return row


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    header = list(rows[0])
    lines = ["\t".join(header)]
    for row in rows:
        lines.append("\t".join(row.get(key, "") for key in header))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_merge_expert_decision_board_keeps_blank_actions_skipped():
    module = _load_merge_module()

    rows = module.merge_expert_decision_board(
        template_rows=[_template_row()],
        board_rows=[_board_row()],
    )

    assert rows[0]["action"] == "skip"
    assert rows[0]["expert_note"] == ""


def test_merge_expert_decision_board_applies_accept_reject_and_correct():
    module = _load_merge_module()

    rows = module.merge_expert_decision_board(
        template_rows=[
            _template_row(finding_id="finding-accept"),
            _template_row(finding_id="finding-reject"),
            _template_row(finding_id="finding-correct"),
        ],
        board_rows=[
            _board_row(
                finding_id="finding-accept",
                expert_action="accept",
                expert_note="Confirmed against the source quote.",
            ),
            _board_row(
                finding_id="finding-reject",
                expert_action="reject",
                issue_type="wrong_direction",
                expert_note="The quote supports a decrease.",
            ),
            _board_row(
                finding_id="finding-correct",
                expert_action="correct",
                expert_note="Use the measured ductility result.",
                corrected_statement="Preheating increased ductility by 14%.",
                corrected_variables="preheating; build plate temperature",
                corrected_mediators="homogenized microstructure",
                corrected_outcomes="ductility",
                corrected_direction="increase",
                corrected_scope_summary="LPBF 316L",
                corrected_support_grade="partial",
                corrected_evidence_ref_ids="ev-1",
            ),
        ],
    )

    assert [row["action"] for row in rows] == ["accept", "reject", "correct"]
    assert rows[0]["expert_note"] == "Confirmed against the source quote."
    assert rows[1]["issue_type"] == "wrong_direction"
    assert rows[2]["suggested_target"] == {
        "statement": "Preheating increased ductility by 14%.",
        "variables": ["preheating", "build plate temperature"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "support_grade": "partial",
        "evidence_ref_ids": ["ev-1"],
        "mediators": ["homogenized microstructure"],
        "scope_summary": "LPBF 316L",
    }
    assert rows[2]["curated_evidence_ref_ids"] == ["ev-1"]


def test_merge_expert_decision_board_rejects_blocked_accept():
    module = _load_merge_module()

    try:
        module.merge_expert_decision_board(
            template_rows=[
                _template_row(
                    acceptance_gate={
                        "accept_allowed": False,
                        "requires_correction": True,
                        "accept_blockers": ["verify_table_rows"],
                    }
                )
            ],
            board_rows=[_board_row(expert_action="accept", accept_allowed="no")],
        )
    except ValueError as exc:
        assert str(exc) == "line 2: accept is blocked; use correct or reject"
    else:
        raise AssertionError("expected blocked accept to fail")


def test_merge_expert_decision_board_requires_corrected_target():
    module = _load_merge_module()

    try:
        module.merge_expert_decision_board(
            template_rows=[_template_row()],
            board_rows=[_board_row(expert_action="correct")],
        )
    except ValueError as exc:
        assert str(exc) == (
            "line 2: correct requires corrected_statement\n"
            "line 2: correct requires corrected_evidence_ref_ids"
        )
    else:
        raise AssertionError("expected incomplete correction to fail")


def test_merge_expert_decision_board_cli_writes_jsonl(tmp_path):
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "merge_expert_decision_board.py"
    )
    template_path = tmp_path / "reviewed-findings.template.jsonl"
    board_path = tmp_path / "expert-decision-board.tsv"
    output_path = tmp_path / "reviewed-findings.from-board.jsonl"
    _write_jsonl(template_path, [_template_row()])
    _write_tsv(
        board_path,
        [
            _board_row(
                expert_action="accept",
                expert_note="Confirmed against the source quote.",
            )
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            str(template_path),
            str(board_path),
            "--output-path",
            str(output_path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["action"] == "accept"
    assert rows[0]["expert_note"] == "Confirmed against the source quote."
