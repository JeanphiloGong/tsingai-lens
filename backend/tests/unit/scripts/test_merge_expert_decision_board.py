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
        "analysis_version": 2,
        "finding_id": "finding-1",
        "action": "skip",
        "issue_type": "",
        "expert_note": "",
        "statement": "Preheating improved ductility.",
        "factors": ["preheating"],
        "outcome": "ductility",
        "direction": "increase",
        "acceptance_gate": {
            "accept_allowed": True,
            "requires_correction": False,
            "accept_blockers": [],
        },
        "protocol_blocking_missing": [],
    }
    row.update(overrides)
    return row


def _board_row(**overrides):
    row = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": "2",
        "finding_id": "finding-1",
        "expert_action": "",
        "issue_type": "",
        "expert_note": "",
        "curated_status": "",
        "curated_finding_json": "",
        "accept_allowed": "yes",
    }
    row.update(overrides)
    return row


def _curated_finding(**overrides):
    row = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
        "statement": "Preheating increased ductility by 14%.",
        "factors": ["preheating", "build plate temperature"],
        "outcome": "ductility",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": "isolated_effect",
        "synthesis_status": "insufficient_confirmation",
        "certainty": 0.9,
        "display_rank": 0,
        "mechanisms": [
            {
                "source_term": "preheating",
                "relation_type": "associated_with",
                "target_term": "homogenized microstructure",
                "direction": "increase",
                "assertion_strength": "associative",
                "supporting_evidence_ids": ["ev-1"],
            }
        ],
        "scientific_context": {
            "material": [{"name": "alloy", "value": "316L", "unit": None}],
            "sample": [],
            "process": [],
            "test": [],
        },
        "limitations": ["One directly contributing paper."],
        "paper_contributions": [
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["ev-1"],
                "contradicting_evidence_ids": [],
                "context_evidence_ids": [],
                "condition_boundary_evidence_ids": [],
            }
        ],
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
    assert "expert_note" not in rows[0]


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
                curated_status="limited",
                curated_finding_json=json.dumps(
                    _curated_finding(finding_id="finding-correct")
                ),
            ),
        ],
    )

    assert [row["action"] for row in rows] == ["accept", "reject", "correct"]
    assert rows[0]["note"] == "Confirmed against the source quote."
    assert rows[1]["issue_type"] == "wrong_direction"
    assert rows[2]["curated_finding"] == _curated_finding(finding_id="finding-correct")
    assert rows[2]["curated_status"] == "limited"


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
            "line 2: correct requires one complete curated_finding_json"
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
    assert rows[0]["note"] == "Confirmed against the source quote."
