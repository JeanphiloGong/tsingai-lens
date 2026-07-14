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
                "protocol_ready_count": 0,
                "review_packet": {
                    "goal_id": "goal-1",
                    "candidates": [
                        {
                            "finding_id": "finding-1",
                            "statement": "Preheating increased ductility.",
                            "recommended_action": "accept as paper-level",
                            "open_url": "/collections/col-1/goals/goal-1?finding_id=finding-1",
                            "acceptance_gate": {"accept_allowed": False},
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
    )


def test_prepare_goal_review_workspace_writes_review_files(tmp_path, monkeypatch):
    module = _load_workspace_module()
    summary = _summary()
    monkeypatch.setattr(
        module,
        "_load_dataset_quality_module",
        lambda: _dataset_module(summary),
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
    assert "### goal-1" in dashboard
    assert "Direct accept blocked: 1" in dashboard
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

    dashboard = module.render_review_dashboard(_summary())

    assert "# Lens Goal Review Dashboard" in dashboard
    assert "Review candidates: 1" in dashboard
    assert "### goal-1" in dashboard
    assert "Direct accept blocked: 1" in dashboard
    assert (
        "Top risks: reason:single_paper_evidence=1, "
        "warning:table_row_alignment_uncertain=1"
    ) in dashboard
    assert (
        "| Preheating increased ductility. | accept as paper-level | "
        "Paper A / p. 4 | [open](/collections/col-1/goals/goal-1?finding_id=finding-1) |"
    ) in dashboard
