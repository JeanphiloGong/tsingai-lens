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
        "review-checklist.md",
        "dataset-readiness.md",
        "training-ready.messages.jsonl",
        "training-ready.dataset.jsonl",
        "optimization-summary.md",
        "README.txt",
        "manifest.json",
    ]
    assert json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))[
        "next_steps"
    ] == [
        "review review-packet.txt and source links",
        "fill reviewed-findings.template.jsonl with human-confirmed decisions",
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
    readiness = (workspace / "dataset-readiness.md").read_text(encoding="utf-8")
    assert "pending review candidates: 1" in readiness
    assert (
        "| How does preheating affect ductility? (goal-1) | 0 | 0 | 0 | 1 | "
        "accept as paper-level |"
    ) in readiness
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
    assert json.loads(
        (workspace / "reviewed-findings.template.jsonl").read_text(encoding="utf-8")
    ) == {"finding_id": "finding-1", "action": "skip"}
    readme = (workspace / "README.txt").read_text(encoding="utf-8")
    assert "This workspace has not written expert labels." in readme
    assert "training_ready is created only by explicit human expert decisions." in readme


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
    assert "- review-packet.txt (10 lines)" in text
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
    assert "- [ ] Evidence quote directly supports the finding." in checklist
    assert "- [ ] Scope/context is narrow enough for downstream experiment design." in checklist


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
