from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_workspace_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "prepare_goal_review_workspace.py"
    )
    spec = importlib.util.spec_from_file_location(
        "prepare_goal_review_workspace",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _summary():
    return {
        "status": "pass",
        "collection_id": "col-1",
        "goal_count": 1,
        "goals": [
            {
                "goal_id": "goal-1",
                "training_ready_count": 0,
                "training_message_ready_count": 0,
                "protocol_ready_count": 0,
                "review_candidate_count": 1,
                "next_review_action": {"label": "accept as paper-level"},
                "top_issue_types": [{"name": "wrong_variable", "count": 1}],
                "top_review_reasons": [
                    {"name": "single_paper_evidence", "count": 1}
                ],
                "top_system_warnings": [
                    {"name": "table_row_alignment_uncertain", "count": 1}
                ],
                "optimization_breakdown": {
                    "by_variable": {
                        "preheating": {
                            "issue_type": {"wrong_variable": 1},
                            "error_category": {"variable_error": 1},
                            "review_candidate_reason": {"single_paper_evidence": 1},
                            "system_warning": {"table_row_alignment_uncertain": 1},
                        }
                    }
                },
                "review_packet": {
                    "goal_id": "goal-1",
                    "candidates": [
                        {
                            "finding_id": "finding-1",
                            "statement": "Preheating increased ductility.",
                            "recommended_action_code": "accept_as_paper_level",
                            "recommended_action": "accept as paper-level",
                            "open_url": "/collections/col-1/goals/goal-1?finding_id=finding-1",
                            "acceptance_gate": {"accept_allowed": False},
                            "review_decision_hint": {
                                "why_accept_blocked": ["table row alignment"]
                            },
                            "evidence": [
                                {
                                    "label": "Paper A / p. 4",
                                    "href": "/collections/col-1/documents/doc-1",
                                    "quote": "Preheating increased ductility by 14%.",
                                    "table_audit": {
                                        "columns": ["Temperature", "Ductility"],
                                        "relevant_rows": [
                                            {
                                                "cells": ["150 C", "+14%"],
                                                "aligned": True,
                                            },
                                            {
                                                "cells": ["room temperature", "baseline"],
                                                "aligned": False,
                                            },
                                        ],
                                    },
                                }
                            ],
                        }
                    ],
                    "review_url": "/collections/col-1/goals/goal-1?review=queue",
                    "risk_summary": {
                        "reason:single_paper_evidence": 1,
                        "warning:table_row_alignment_uncertain": 1,
                    },
                },
            }
        ],
    }


def _dataset_module(summary):
    return SimpleNamespace(
        check_goal_dataset_quality=lambda **_kwargs: summary,
        render_review_packet_summary=lambda _summary: "review packet\n",
        render_review_jsonl_summary=lambda _summary: (
            json.dumps({"finding_id": "finding-1"}) + "\n"
        ),
        render_decision_template_summary=lambda _summary: (
            json.dumps({"finding_id": "finding-1", "action": "skip"}) + "\n"
        ),
        render_agent_review_prompt_jsonl_summary=lambda _summary: (
            json.dumps(
                {
                    "task": "review_lens_research_finding",
                    "finding_id": "finding-1",
                }
            )
            + "\n"
        ),
        render_messages_jsonl_summary=lambda _summary: (
            json.dumps({"messages": [{"role": "user", "content": "extract"}]}) + "\n"
        ),
        render_training_jsonl_summary=lambda _summary: (
            json.dumps({"metadata": {"finding_id": "finding-1"}}) + "\n"
        ),
    )


def _findings_module():
    return SimpleNamespace(
        check_goal_findings_projection=lambda **_kwargs: {
            "goals": [
                {
                    "goal_id": "goal-1",
                    "question": "How does preheating affect ductility?",
                }
            ]
        }
    )


def test_prepare_goal_review_workspace_writes_review_files(tmp_path, monkeypatch):
    module = _load_workspace_module()
    summary = _summary()
    monkeypatch.setattr(
        module,
        "_load_dataset_quality_module",
        lambda: _dataset_module(summary),
    )
    monkeypatch.setattr(
        module,
        "_load_findings_projection_module",
        _findings_module,
    )

    result = module.prepare_goal_review_workspace(
        collection_id="col-1",
        goal_ids=("goal-1",),
        output_dir=tmp_path / "workspace",
    )

    workspace = tmp_path / "workspace"
    assert result["status"] == "pass"
    assert result["review_candidate_count"] == 1
    assert [file_info["filename"] for file_info in result["files"]] == [
        "dataset-quality-summary.json",
        "review-packet.txt",
        "review-candidates.jsonl",
        "reviewed-findings.template.jsonl",
        "agent-review-prompts.jsonl",
        "review-dashboard.md",
        "review-priority.md",
        "expert-decision-board.tsv",
        "review-checklist.md",
        "review-unlock-plan.md",
        "dataset-readiness.md",
        "expert-satisfaction.md",
        "training-ready.messages.jsonl",
        "training-ready.dataset.jsonl",
        "optimization-summary.md",
        "review-commands.sh",
        "README.txt",
        "manifest.json",
    ]
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["training_message_ready_count"] == 0
    assert manifest["next_steps"] == [
        "review review-packet.txt and source links",
        "fill expert-decision-board.tsv or reviewed-findings.template.jsonl with human-confirmed decisions",
        "merge expert-decision-board.tsv into reviewed-findings.from-board.jsonl if using the board",
        "dry-run import_goal_review_decisions.py before writing labels",
    ]
    assert (workspace / "review-packet.txt").read_text(encoding="utf-8") == (
        "review packet\n\n"
    )
    dashboard = (workspace / "review-dashboard.md").read_text(encoding="utf-8")
    assert "### How does preheating affect ductility? (goal-1)" in dashboard
    assert "Direct accept blocked: 1" in dashboard
    assert "| Finding | Gate | Action | Note required | Evidence | Open |" in dashboard
    assert "accept blocked: table row alignment" in dashboard
    assert "Required: explain accepted paper-level scope." in dashboard
    priority = (workspace / "review-priority.md").read_text(encoding="utf-8")
    assert "# Lens Review Priority Queue" in priority
    assert "P1 correct/reject: accept blocked" in priority
    assert "How does preheating affect ductility? (goal-1)" in priority
    assert "Preheating increased ductility." in priority
    assert "accept as paper-level" in priority
    decision_board = (workspace / "expert-decision-board.tsv").read_text(
        encoding="utf-8"
    )
    decision_rows = decision_board.splitlines()
    assert decision_rows[0].split("\t") == [
        "expert_action",
        "issue_type",
        "expert_note",
        "corrected_statement",
        "corrected_variables",
        "corrected_mediators",
        "corrected_outcomes",
        "corrected_direction",
        "corrected_scope_summary",
        "corrected_support_grade",
        "corrected_evidence_ref_ids",
        "collection_id",
        "priority",
        "goal_id",
        "goal",
        "finding_id",
        "finding",
        "recommended_action",
        "accept_allowed",
        "allowed_actions",
        "blocked_actions",
        "required_checks",
        "training_unlock",
        "protocol_unlock",
        "evidence",
        "quote",
        "open_finding",
        "source_open",
    ]
    assert decision_rows[1].split("\t") == [
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "col-1",
        "P1 correct/reject: accept blocked",
        "goal-1",
        "How does preheating affect ductility? (goal-1)",
        "finding-1",
        "Preheating increased ductility.",
        "accept as paper-level",
        "no",
        "accept; reject; correct; skip",
        "",
        "",
        "correct/reject first",
        "blocked: table row alignment",
        "Paper A / p. 4",
        "Preheating increased ductility by 14%.",
        "/collections/col-1/goals/goal-1?finding_id=finding-1",
        "/collections/col-1/documents/doc-1",
    ]
    checklist = (workspace / "review-checklist.md").read_text(encoding="utf-8")
    assert "# Lens Expert Review Checklist" in checklist
    assert "### How does preheating affect ductility? (goal-1)" in checklist
    assert (
        "- `accept`: finding, variables, outcome, direction, scope, and cited "
        "evidence all match."
    ) in checklist
    assert "Training unlock: one accepted or corrected finding" in checklist
    assert "Finding id: `finding-1`" in checklist
    assert "[open finding](/collections/col-1/goals/goal-1?finding_id=finding-1)" in checklist
    assert "- [ ] Source link opens the cited paper/table/block." in checklist
    assert "- [ ] Direction matches the cited result." in checklist
    unlock_plan = (workspace / "review-unlock-plan.md").read_text(encoding="utf-8")
    assert "# Lens Review Unlock Plan" in unlock_plan
    assert "Preheating increased ductility." in unlock_plan
    assert "accept as paper-level" in unlock_plan
    assert "correct/reject first" in unlock_plan
    assert "blocked: table row alignment" in unlock_plan
    assert "accept is rejected while acceptance_gate.accept_allowed=false" in unlock_plan
    readiness = (workspace / "dataset-readiness.md").read_text(encoding="utf-8")
    assert "pending review candidates: 1" in readiness
    assert (
        "| How does preheating affect ductility? (goal-1) | 0 | 0 | 0 | 1 | "
        "accept as paper-level |"
    ) in readiness
    satisfaction = (workspace / "expert-satisfaction.md").read_text(encoding="utf-8")
    assert "# Lens Expert Satisfaction Gate" in satisfaction
    assert "Overall: blocked" in satisfaction
    assert (
        "| Expert review usable | satisfied | 1 candidate(s) are reviewable "
        "with source links and accept/reject/correct actions."
    ) in satisfaction
    assert "| Dataset accumulation usable | blocked | 1 goal(s) lack training-ready samples;" in satisfaction
    assert "| Experiment design usable | blocked | 1 goal(s) lack protocol-ready inputs." in satisfaction
    assert "the code path is usable but real expert labels are still missing" in satisfaction
    assert json.loads(
        (workspace / "training-ready.messages.jsonl").read_text(encoding="utf-8")
    ) == {"messages": [{"role": "user", "content": "extract"}]}
    assert json.loads(
        (workspace / "training-ready.dataset.jsonl").read_text(encoding="utf-8")
    ) == {"metadata": {"finding_id": "finding-1"}}
    optimization = (workspace / "optimization-summary.md").read_text(
        encoding="utf-8"
    )
    assert "wrong_variable: 1" in optimization
    assert "by_variable:preheating" in optimization
    commands = (workspace / "review-commands.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in commands
    assert 'REVIEW_FILE=${REVIEW_FILE:-reviewed-findings.template.jsonl}' in commands
    assert 'DECISION_BOARD=${DECISION_BOARD:-expert-decision-board.tsv}' in commands
    assert (
        'MERGED_REVIEW_FILE=${MERGED_REVIEW_FILE:-reviewed-findings.from-board.jsonl}'
        in commands
    )
    assert "API_BASE_URL=${API_BASE_URL:-}" in commands
    assert (
        '"$SCRIPTS/merge_expert_decision_board.py" "$REVIEW_FILE" "$DECISION_BOARD" '
        '--output-path "$MERGED_REVIEW_FILE"'
    ) in commands
    assert '"$SCRIPTS/import_goal_review_decisions.py" "$MERGED_REVIEW_FILE"' in commands
    assert "--dry-run --fail-on-warnings --format text" in commands
    assert (
        '# "$PYTHON" "$SCRIPTS/import_goal_review_decisions.py" "$MERGED_REVIEW_FILE"'
        in commands
    )
    assert (
        '"$SCRIPTS/check_goal_expert_loop.py" --collection-id '
        "'col-1' --goal-id 'goal-1' --format text"
    ) in commands
    assert "if [ -n \"$API_BASE_URL\" ]; then" in commands
    assert "--api-base-url \"$API_BASE_URL\" --format text" in commands
    assert "# Optional write smoke after expert approval" in commands
    assert "--runtime-write-check --format text" in commands
    assert (
        '"$SCRIPTS/check_goal_dataset_quality.py" --collection-id '
        "'col-1' --goal-id 'goal-1' --format training-jsonl "
        "--require-training-ready"
    ) in commands
    assert json.loads(
        (workspace / "reviewed-findings.template.jsonl").read_text(encoding="utf-8")
    ) == {"finding_id": "finding-1", "action": "skip"}
    readme = (workspace / "README.txt").read_text(encoding="utf-8")
    assert "Expert satisfaction: blocked" in readme
    assert "This workspace has not written expert labels." in readme
    assert "expert-decision-board.tsv is a spreadsheet aid" in readme
    assert "training_ready is created only by explicit human expert decisions." in readme
    assert "Or run the matching command from review-commands.sh." in readme
    assert "review-commands.sh leaves the real import command commented out." in readme
    assert "Use review-unlock-plan.md to see what each decision unlocks." in readme


def test_prepare_goal_review_workspace_refuses_non_empty_output_dir(tmp_path):
    module = _load_workspace_module()
    output_dir = tmp_path / "workspace"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")

    try:
        module.prepare_goal_review_workspace(
            collection_id="col-1",
            goal_ids=("goal-1",),
            output_dir=output_dir,
        )
    except ValueError as exc:
        assert str(exc) == f"output dir must be empty: {output_dir}"
    else:
        raise AssertionError("expected non-empty output dir to fail")


def test_default_output_dir_uses_unique_tmp_path(tmp_path, monkeypatch):
    module = _load_workspace_module()
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))

    class FixedUuid:
        hex = "abcdef1234567890"

    monkeypatch.setattr(module, "uuid4", lambda: FixedUuid())

    output_dir = module._default_output_dir("col:1/with spaces")

    assert output_dir == tmp_path / "lens-goal-review-col_1_with_spaces-abcdef12"


def test_render_text_summary_lists_next_review_steps(tmp_path):
    module = _load_workspace_module()

    text = module.render_text_summary(
        {
            "status": "pass",
            "collection_id": "col-1",
            "goal_count": 1,
            "review_candidate_count": 2,
            "output_dir": str(tmp_path),
            "files": [
                {
                    "filename": "review-packet.txt",
                    "line_count": 10,
                }
            ],
        }
    )

    assert "Review candidates: 2" in text
    assert "Expert satisfaction: blocked" in text
    assert "- review-packet.txt (10 lines)" in text
    assert (
        "- Fill expert-decision-board.tsv or reviewed-findings.template.jsonl "
        "with human-confirmed decisions."
    ) in text
    assert (
        "- Merge expert-decision-board.tsv into reviewed-findings.from-board.jsonl "
        "if using the board."
    ) in text
    assert "- Dry-run import_goal_review_decisions.py before writing labels." in text


def test_render_review_dashboard_summarizes_goal_risks():
    module = _load_workspace_module()
    summary = _summary()
    summary["goals"][0]["question"] = "How does preheating affect ductility?"

    dashboard = module.render_review_dashboard(summary)

    assert "# Lens Goal Review Dashboard" in dashboard
    assert "Review candidates: 1" in dashboard
    assert "### How does preheating affect ductility? (goal-1)" in dashboard
    assert "Direct accept blocked: 1" in dashboard
    assert (
        "Top risks: reason:single_paper_evidence=1, "
        "warning:table_row_alignment_uncertain=1"
    ) in dashboard
    assert (
        "| Preheating increased ductility. | accept blocked: table row alignment | "
        "accept as paper-level | Required: explain accepted paper-level scope. | "
        "Paper A / p. 4 | [open](/collections/col-1/goals/goal-1?finding_id=finding-1) |"
    ) in dashboard


def test_render_review_priority_report_orders_accept_blockers_first():
    module = _load_workspace_module()
    summary = _summary()
    summary["goals"][0]["question"] = "How does preheating affect ductility?"
    summary["goals"][0]["review_packet"]["candidates"].append(
        {
            "finding_id": "finding-2",
            "statement": "Preheating needs paper-level confirmation.",
            "recommended_action_code": "accept_as_paper_level",
            "recommended_action": "accept as paper-level",
            "open_url": "/collections/col-1/goals/goal-1?finding_id=finding-2",
            "acceptance_gate": {"accept_allowed": True},
            "review_reasons": ["single_paper_evidence"],
            "evidence": [{"label": "Paper B / p. 2"}],
        }
    )

    report = module.render_review_priority_report(summary)

    assert "# Lens Review Priority Queue" in report
    assert "1. Resolve findings where direct accept is blocked." in report
    assert (
        "| P1 correct/reject: accept blocked | How does preheating affect ductility? "
        "(goal-1) | Preheating increased ductility. | accept as paper-level | "
        "Paper A / p. 4 |"
    ) in report
    assert (
        "| P4 confirm paper-level scope | How does preheating affect ductility? "
        "(goal-1) | Preheating needs paper-level confirmation. | "
        "accept as paper-level | Paper B / p. 2 |"
    ) in report
    assert report.index("P1 correct/reject") < report.index("P4 confirm")
    assert "- P1 correct/reject: accept blocked: 1" in report
    assert "- P4 confirm paper-level scope: 1" in report


def test_render_expert_decision_board_exports_spreadsheet_rows():
    module = _load_workspace_module()
    summary = _summary()
    summary["goals"][0]["question"] = "How does preheating affect ductility?"
    candidate = summary["goals"][0]["review_packet"]["candidates"][0]
    candidate["review_work_order"] = {
        "allowed_actions": ["reject", "correct", "skip"],
        "blocked_actions": ["accept"],
        "required_checks": ["Check\ttable rows", "Inspect\nquote"],
        "training_unlock": "correct creates a training-ready target",
        "protocol_unlock": "blocked: accept_blockers=verify_table_rows, table_row_alignment_uncertain",
    }

    board = module.render_expert_decision_board(summary)
    rows = board.splitlines()

    assert len(rows) == 2
    header = rows[0].split("\t")
    assert header[:4] == [
        "expert_action",
        "issue_type",
        "expert_note",
        "corrected_statement",
    ]
    assert header[11:16] == [
        "collection_id",
        "priority",
        "goal_id",
        "goal",
        "finding_id",
    ]
    values = rows[1].split("\t")
    row = dict(zip(header, values, strict=True))
    assert row["expert_action"] == ""
    assert row["collection_id"] == "col-1"
    assert row["priority"] == "P1 correct/reject: accept blocked"
    assert row["goal_id"] == "goal-1"
    assert row["finding_id"] == "finding-1"
    assert row["accept_allowed"] == "no"
    assert row["allowed_actions"] == "reject; correct; skip"
    assert row["blocked_actions"] == "accept"
    assert row["required_checks"] == "Check table rows; Inspect quote"
    assert row["training_unlock"] == "correct creates a training-ready target"
    assert row["protocol_unlock"] == (
        "blocked: accept blockers: verify parsed table rows, "
        "table row alignment uncertain"
    )
    assert row["quote"] == "Preheating increased ductility by 14%."


def test_render_review_checklist_gives_expert_decision_steps():
    module = _load_workspace_module()
    summary = _summary()
    summary["goals"][0]["question"] = "How does preheating affect ductility?"

    checklist = module.render_review_checklist(summary)

    assert "# Lens Expert Review Checklist" in checklist
    assert "Review candidates: 1" in checklist
    assert "- `reject`: evidence does not support the finding; set a concrete `issue_type`." in checklist
    assert "### How does preheating affect ductility? (goal-1)" in checklist
    assert "Training unlock: one accepted or corrected finding" in checklist
    assert "#### 1. Preheating increased ductility." in checklist
    assert "Finding id: `finding-1`" in checklist
    assert "Gate: accept blocked: table row alignment" in checklist
    assert "Recommended action: accept as paper-level" in checklist
    assert "Note: Required: explain accepted paper-level scope." in checklist
    assert "Evidence: Paper A / p. 4" in checklist
    assert "Evidence audit:" in checklist
    assert "Open source: [open source](/collections/col-1/documents/doc-1)" in checklist
    assert "Quote: Preheating increased ductility by 14%." in checklist
    assert "Table columns: Temperature, Ductility" in checklist
    assert "Table row 1: Temperature: 150 C; Ductility: +14%" in checklist
    assert (
        "Table row 2 (alignment uncertain): Temperature: room temperature; "
        "Ductility: baseline"
    ) in checklist
    assert "- [ ] Evidence quote directly supports the finding." in checklist
    assert "- [ ] Scope/context is narrow enough for downstream experiment design." in checklist


def test_render_review_unlock_plan_explains_decision_effects():
    module = _load_workspace_module()
    summary = _summary()
    summary["goals"][0]["question"] = "How does preheating affect ductility?"
    candidate = summary["goals"][0]["review_packet"]["candidates"][0]
    candidate["acceptance_gate"] = {
        "accept_allowed": False,
        "review_checks": ["Correct the direction or scope before import."],
    }
    candidate["review_decision_hint"] = {
        "summary": "Accept is blocked until direction or scope is corrected.",
        "required_checks": ["Correct the direction or scope before import."],
    }
    candidate["protocol_readiness"] = {
        "status": "missing_protocol_inputs",
        "ready_after_review": False,
        "missing": ["expert_review_decision", "direction_or_scope"],
        "blocking_missing": ["direction_or_scope"],
    }

    report = module.render_review_unlock_plan(summary)

    assert "# Lens Review Unlock Plan" in report
    assert "| How does preheating affect ductility? (goal-1) |" in report
    assert "correct/reject first" in report
    assert "blocked: direction or scope" in report
    assert "Correct the direction or scope before import." in report
    assert "accept is rejected while acceptance_gate.accept_allowed=false" in report


def test_render_dataset_readiness_report_explains_partial_exports():
    module = _load_workspace_module()
    summary = _summary()
    summary["goals"][0]["question"] = "How does preheating affect ductility?"

    report = module.render_dataset_readiness_report(summary)

    assert "# Lens Dataset Readiness" in report
    assert "training_ready findings: 0" in report
    assert "pending review candidates: 1" in report
    assert (
        "| How does preheating affect ductility? (goal-1) | 0 | 0 | 0 | 1 | "
        "accept as paper-level |"
    ) in report
    assert (
        "Existing training-ready rows may still be emitted while the overall command fails"
        in report
    )


def test_render_expert_satisfaction_report_maps_three_layers():
    module = _load_workspace_module()

    report = module.render_expert_satisfaction_report(_summary())

    assert "# Lens Expert Satisfaction Gate" in report
    assert "Overall: blocked" in report
    assert (
        "| Expert review usable | satisfied | 1 candidate(s) are reviewable "
        "with source links and accept/reject/correct actions."
    ) in report
    assert "| Dataset accumulation usable | blocked | 1 goal(s) lack training-ready samples;" in report
    assert "| Experiment design usable | blocked | 1 goal(s) lack protocol-ready inputs." in report
    assert "review-checklist.md" in report
    assert "pass (incomplete)" in report


def test_render_optimization_summary_lists_error_and_risk_stats():
    module = _load_workspace_module()

    report = module.render_optimization_summary(_summary())

    assert "# Lens Optimization Summary" in report
    assert "wrong_variable: 1" in report
    assert "single_paper_evidence: 1" in report
    assert "table_row_alignment_uncertain: 1" in report
    assert "by_variable:preheating" in report
    assert "issue_type:wrong_variable=1" in report


def test_enrich_goal_questions_adds_question_to_matching_goals(monkeypatch):
    module = _load_workspace_module()
    summary = _summary()
    monkeypatch.setattr(module, "_load_findings_projection_module", _findings_module)

    module._enrich_goal_questions(
        summary,
        collection_id="col-1",
        goal_ids=("goal-1",),
        api_base_url=None,
    )

    assert summary["goals"][0]["question"] == "How does preheating affect ductility?"
