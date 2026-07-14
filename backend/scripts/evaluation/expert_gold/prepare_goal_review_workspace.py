#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
from uuid import uuid4


DEFAULT_COLLECTION_ID = "col_0cc5013fdb3c"
DEFAULT_GOAL_IDS = (
    "goal_0914003ad572",
    "goal_1a7a26d850b9",
    "goal_399171646354",
    "goal_061c9c049e69",
    "goal_6bf7d2c1030e",
    "goal_3037e425673a",
)
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
EXPERT_NOTE_PROMPTS = {
    "accept_as_paper_level": "Required: explain accepted paper-level scope.",
    "review_table_rows": "Required: explain checked table rows and values.",
    "verify_table_rows": "Required: explain parsed table-row alignment.",
    "review_table_variables": "Required: explain why selected variable is valid.",
    "check_mechanism_requirement": "Required: explain mechanism requirement.",
    "resolve_conflict": "Required: explain conflict resolution.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a read-only Lens goal review workspace with review packets, "
            "decision templates, and agent-review prompts."
        )
    )
    parser.add_argument(
        "--collection-id",
        default=DEFAULT_COLLECTION_ID,
        help="Collection id to prepare.",
    )
    parser.add_argument(
        "--goal-id",
        action="append",
        dest="goal_ids",
        help="Goal id to prepare. May repeat. Defaults to the local 6-goal 316L set.",
    )
    parser.add_argument(
        "--api-base-url",
        help=(
            "Optional running Lens API or frontend origin to read, for example "
            "http://localhost:5173. Set LENS_CHECK_EMAIL and "
            "LENS_CHECK_PASSWORD when login is required."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Empty directory where review workspace files will be written. "
            "Defaults to a unique directory under /tmp."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = prepare_goal_review_workspace(
        collection_id=args.collection_id,
        goal_ids=tuple(args.goal_ids or DEFAULT_GOAL_IDS),
        api_base_url=args.api_base_url,
        output_dir=(
            Path(args.output_dir)
            if args.output_dir
            else _default_output_dir(args.collection_id)
        ),
    )
    print(render_text_summary(result))
    if result["status"] == "fail":
        raise SystemExit(1)


def prepare_goal_review_workspace(
    *,
    collection_id: str,
    goal_ids: tuple[str, ...] = DEFAULT_GOAL_IDS,
    output_dir: Path,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    _ensure_empty_output_dir(output_dir)
    dataset_module = _load_dataset_quality_module()
    summary = dataset_module.check_goal_dataset_quality(
        collection_id=collection_id,
        goal_ids=goal_ids,
        api_base_url=api_base_url,
        include_review_packet=True,
        include_training_export=True,
        include_training_metadata=True,
    )
    _enrich_goal_questions(
        summary,
        collection_id=collection_id,
        goal_ids=goal_ids,
        api_base_url=api_base_url,
    )
    files = _write_workspace_files(
        output_dir=output_dir,
        summary=summary,
        dataset_module=dataset_module,
    )
    manifest_path = output_dir / "manifest.json"
    files.append(
        {
            "filename": "manifest.json",
            "path": str(manifest_path),
            "description": "Machine-readable workspace manifest.",
            "line_count": 0,
        }
    )
    manifest = _workspace_manifest(summary, output_dir=output_dir, files=files)
    manifest["files"][-1]["line_count"] = _line_count(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _write_workspace_files(
    *,
    output_dir: Path,
    summary: dict[str, Any],
    dataset_module: Any,
) -> list[dict[str, Any]]:
    rendered = [
        (
            "dataset-quality-summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            "Full machine-readable dataset quality summary.",
        ),
        (
            "review-packet.txt",
            dataset_module.render_review_packet_summary(summary) + "\n",
            "Human-readable findings, gates, evidence quotes, and source links.",
        ),
        (
            "review-candidates.jsonl",
            dataset_module.render_review_jsonl_summary(summary),
            "One full review candidate per line.",
        ),
        (
            "reviewed-findings.template.jsonl",
            dataset_module.render_decision_template_summary(summary),
            "Editable human decision template; rows default to action=skip.",
        ),
        (
            "agent-review-prompts.jsonl",
            dataset_module.render_agent_review_prompt_jsonl_summary(summary),
            "Independent reviewer prompt rows; not importable expert decisions.",
        ),
        (
            "review-dashboard.md",
            render_review_dashboard(summary),
            "Short goal-by-goal review queue with risks and source links.",
        ),
        (
            "review-priority.md",
            render_review_priority_report(summary),
            "Cross-goal expert work order sorted by review risk.",
        ),
        (
            "review-checklist.md",
            render_review_checklist(summary),
            "Expert checklist for deciding accept, reject, correct, or skip.",
        ),
        (
            "dataset-readiness.md",
            render_dataset_readiness_report(summary),
            "Training export and protocol readiness by goal.",
        ),
        (
            "expert-satisfaction.md",
            render_expert_satisfaction_report(summary),
            "Three-layer expert satisfaction gate status and next actions.",
        ),
        (
            "training-ready.messages.jsonl",
            dataset_module.render_messages_jsonl_summary(summary),
            "Fine-tuning-compatible messages for current training-ready findings.",
        ),
        (
            "training-ready.dataset.jsonl",
            dataset_module.render_training_jsonl_summary(summary),
            "Training messages plus traceable sample metadata.",
        ),
        (
            "optimization-summary.md",
            render_optimization_summary(summary),
            "Error, review-risk, and optimization statistics.",
        ),
        (
            "review-commands.sh",
            render_review_commands(summary),
            "Copyable dry-run, import, export, and gate-check commands.",
        ),
    ]
    files: list[dict[str, Any]] = []
    for filename, content, description in rendered:
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        files.append(
            {
                "filename": filename,
                "path": str(path),
                "description": description,
                "line_count": _line_count(content),
            }
        )

    readme_path = output_dir / "README.txt"
    readme_content = render_workspace_readme(summary, files=files)
    readme_path.write_text(readme_content, encoding="utf-8")
    files.append(
        {
            "filename": "README.txt",
            "path": str(readme_path),
            "description": "Review workflow instructions and safety notes.",
            "line_count": _line_count(readme_content),
        }
    )
    return files


def render_workspace_readme(
    summary: dict[str, Any],
    *,
    files: list[dict[str, Any]],
) -> str:
    collection_id = _text(summary.get("collection_id"))
    candidate_count = _candidate_count(summary)
    lines = [
        "Lens Goal Review Workspace",
        "==========================",
        "",
        f"Collection: {collection_id or 'n/a'}",
        f"Status: {_text(summary.get('status')) or 'n/a'}",
        f"Expert satisfaction: {_expert_satisfaction_status(summary)}",
        f"Goal count: {int(summary.get('goal_count') or 0)}",
        f"Review candidates: {candidate_count}",
        "",
        "Files",
        "-----",
    ]
    question_warning = _text(summary.get("goal_question_warning"))
    if question_warning:
        lines.extend(["Goal question warning", "---------------------", question_warning, ""])
    for file_info in files:
        lines.append(
            f"- {file_info['filename']}: {file_info['description']}"
        )
    lines.extend(
        [
            "",
            "Review steps",
            "------------",
            "1. Read review-packet.txt and open the source links for each finding.",
            "   Use review-priority.md first when many candidates remain.",
            (
                "2. Edit reviewed-findings.template.jsonl only for rows a human "
                "expert has checked."
            ),
            (
                "3. Keep unchecked rows at action=skip; use accept, reject, or "
                "correct only with an expert note when required."
            ),
            "4. Validate before writing labels:",
            (
                "   ./.venv/bin/python "
                "scripts/evaluation/expert_gold/import_goal_review_decisions.py "
                "reviewed-findings.template.jsonl "
                "--reviewer materials-expert@example.com "
                "--dry-run --fail-on-warnings --format text"
            ),
            "   Or run the matching command from review-commands.sh.",
            "5. Import only after the dry-run passes and the reviewer approves it:",
            (
                "   ./.venv/bin/python "
                "scripts/evaluation/expert_gold/import_goal_review_decisions.py "
                "reviewed-findings.template.jsonl "
                "--reviewer materials-expert@example.com --format text"
            ),
            "",
            "Safety",
            "------",
            "- This workspace has not written expert labels.",
            "- Agent-review prompts are input packets, not importable decisions.",
            "- training_ready is created only by explicit human expert decisions.",
            "- review-commands.sh leaves the real import command commented out.",
            "",
        ]
    )
    return "\n".join(lines)


def render_review_commands(summary: dict[str, Any]) -> str:
    collection_id = _text(summary.get("collection_id")) or DEFAULT_COLLECTION_ID
    goal_args = " ".join(
        f"--goal-id {_shell_quote(_text(goal.get('goal_id')))}"
        for goal in _mapping_list(summary.get("goals"))
        if _text(goal.get("goal_id"))
    )
    prepare_goal_args = f" {goal_args}" if goal_args else ""
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            f"BACKEND_DIR=${{BACKEND_DIR:-{_shell_quote(str(DEFAULT_BACKEND_ROOT))}}}",
            'PYTHON="$BACKEND_DIR/.venv/bin/python"',
            'SCRIPTS="$BACKEND_DIR/scripts/evaluation/expert_gold"',
            "REVIEW_FILE=${REVIEW_FILE:-reviewed-findings.template.jsonl}",
            "REVIEWER=${REVIEWER:-materials-expert@example.com}",
            "",
            "# Run with this review workspace as the current directory.",
            "# Example:",
            "#   (cd /tmp/lens-goal-review-... && bash review-commands.sh)",
            "",
            "echo '1. Validate human-reviewed decisions without writing labels'",
            (
                '"$PYTHON" "$SCRIPTS/import_goal_review_decisions.py" "$REVIEW_FILE" '
                "--reviewer \"$REVIEWER\" --dry-run --fail-on-warnings --format text"
            ),
            "",
            "echo '2. Import only after a human reviewer approves the dry-run output'",
            (
                '# "$PYTHON" "$SCRIPTS/import_goal_review_decisions.py" "$REVIEW_FILE" '
                "--reviewer \"$REVIEWER\" --format text"
            ),
            "",
            "echo '3. Check the three-layer expert loop after import'",
            (
                '"$PYTHON" "$SCRIPTS/check_goal_expert_loop.py" --collection-id '
                f"{_shell_quote(collection_id)}{prepare_goal_args} --format text"
            ),
            "",
            "echo '4. Export training messages once labels are training-ready'",
            (
                '"$PYTHON" "$SCRIPTS/check_goal_dataset_quality.py" --collection-id '
                f"{_shell_quote(collection_id)}{prepare_goal_args} "
                "--format messages-jsonl --require-training-ready"
            ),
            "",
            "echo '5. Export traceable training JSONL once labels are training-ready'",
            (
                '"$PYTHON" "$SCRIPTS/check_goal_dataset_quality.py" --collection-id '
                f"{_shell_quote(collection_id)}{prepare_goal_args} "
                "--format training-jsonl --require-training-ready"
            ),
            "",
        ]
    )


def render_review_dashboard(summary: dict[str, Any]) -> str:
    lines = [
        "# Lens Goal Review Dashboard",
        "",
        f"Collection: {_text(summary.get('collection_id')) or 'n/a'}",
        f"Review candidates: {_candidate_count(summary)}",
        "",
        "## Goal Queue",
        "",
    ]
    goals = _mapping_list(summary.get("goals"))
    if not goals:
        lines.append("No goals found.")
        return "\n".join(lines) + "\n"
    for goal in goals:
        packet = _mapping(goal.get("review_packet"))
        candidates = _mapping_list(packet.get("candidates"))
        if not candidates:
            continue
        goal_id = _text(packet.get("goal_id")) or _text(goal.get("goal_id"))
        question = _text(goal.get("question"))
        review_url = _text(packet.get("review_url"))
        lines.extend(
            [
                f"### {_goal_heading(goal_id, question)}",
                "",
                f"- Candidates: {len(candidates)}",
                f"- Open review queue: {review_url or 'n/a'}",
            ]
        )
        risks = _top_risks(_mapping(packet.get("risk_summary")))
        if risks:
            lines.append(f"- Top risks: {', '.join(risks)}")
        blocked_count = sum(
            1
            for candidate in candidates
            if not bool(_mapping(candidate.get("acceptance_gate")).get("accept_allowed"))
        )
        if blocked_count:
            lines.append(f"- Direct accept blocked: {blocked_count}")
        lines.extend(
            [
                "",
                "| Finding | Gate | Action | Note required | Evidence | Open |",
                "|---|---|---|---|---|---|",
            ]
        )
        for candidate in candidates:
            lines.append(
                "| "
                f"{_markdown_cell(_text(candidate.get('statement')), 140)} | "
                f"{_markdown_cell(_candidate_gate_text(candidate), 70)} | "
                f"{_markdown_cell(_text(candidate.get('recommended_action')), 90)} | "
                f"{_markdown_cell(_candidate_note_prompt(candidate), 80)} | "
                f"{_markdown_cell(_evidence_label(candidate), 100)} | "
                f"{_markdown_link('open', _text(candidate.get('open_url')) or review_url)} |"
            )
        lines.append("")
    if len(lines) == 6:
        lines.append("No review candidates found.")
    return "\n".join(lines) + "\n"


def render_review_priority_report(summary: dict[str, Any]) -> str:
    ranked = _ranked_review_candidates(summary)
    lines = [
        "# Lens Review Priority Queue",
        "",
        f"Collection: {_text(summary.get('collection_id')) or 'n/a'}",
        f"Review candidates: {len(ranked)}",
        "",
        "## Work Order",
        "",
        "1. Resolve findings where direct accept is blocked.",
        "2. Verify table rows, table variables, and alignment warnings.",
        "3. Decide whether missing mechanism evidence changes the final label.",
        "4. Confirm paper-level scope for otherwise grounded single-paper findings.",
        "",
        "## Priority Queue",
        "",
        "| Priority | Goal | Finding | Action | Evidence | Open |",
        "|---|---|---|---|---|---|",
    ]
    if not ranked:
        lines.append("| n/a | n/a | No review candidates found. | n/a | n/a | n/a |")
        return "\n".join(lines) + "\n"
    for row in ranked:
        lines.append(
            "| "
            f"{_markdown_cell(row['priority'], 80)} | "
            f"{_markdown_cell(row['goal'], 100)} | "
            f"{_markdown_cell(row['finding'], 140)} | "
            f"{_markdown_cell(row['action'], 100)} | "
            f"{_markdown_cell(row['evidence'], 100)} | "
            f"{_markdown_link('open', row['open_url'])} |"
        )
    lines.extend(["", "## Priority Counts", ""])
    for label, count in _priority_counts(ranked):
        lines.append(f"- {label}: {count}")
    return "\n".join(lines) + "\n"


def render_review_checklist(summary: dict[str, Any]) -> str:
    lines = [
        "# Lens Expert Review Checklist",
        "",
        f"Collection: {_text(summary.get('collection_id')) or 'n/a'}",
        f"Review candidates: {_candidate_count(summary)}",
        "",
        "## Decision Rules",
        "",
        "- `accept`: finding, variables, outcome, direction, scope, and cited evidence all match.",
        "- `reject`: evidence does not support the finding; set a concrete `issue_type`.",
        "- `correct`: finding is partly right; fill `suggested_target.statement` and evidence refs.",
        "- `skip`: row has not been checked by a human expert yet.",
        "",
        "## Review Queue",
        "",
    ]
    goals = _mapping_list(summary.get("goals"))
    if not goals:
        lines.append("No goals found.")
        return "\n".join(lines) + "\n"
    has_candidates = False
    for goal in goals:
        packet = _mapping(goal.get("review_packet"))
        candidates = _mapping_list(packet.get("candidates"))
        if not candidates:
            continue
        has_candidates = True
        goal_id = _text(packet.get("goal_id")) or _text(goal.get("goal_id"))
        question = _text(goal.get("question"))
        review_url = _text(packet.get("review_url"))
        lines.extend(
            [
                f"### {_goal_heading(goal_id, question)}",
                "",
                f"- Open goal review: {_markdown_link('open goal', review_url)}",
                (
                    "- Training unlock: one accepted or corrected finding with "
                    "valid evidence can become a training-ready sample and a "
                    "protocol design input."
                ),
                "",
            ]
        )
        for index, candidate in enumerate(candidates, start=1):
            lines.extend(_candidate_checklist_lines(index, candidate, review_url))
            lines.append("")
    if not has_candidates:
        lines.append("No review candidates found.")
    return "\n".join(lines) + "\n"


def render_dataset_readiness_report(summary: dict[str, Any]) -> str:
    goals = _mapping_list(summary.get("goals"))
    total_training = _sum_goal_int(summary, "training_ready_count")
    total_messages = _sum_goal_int(summary, "training_message_ready_count")
    total_protocol = _sum_goal_int(summary, "protocol_ready_count")
    total_review = _sum_goal_int(summary, "review_candidate_count")
    lines = [
        "# Lens Dataset Readiness",
        "",
        f"Collection: {_text(summary.get('collection_id')) or 'n/a'}",
        f"Status: {_text(summary.get('status')) or 'n/a'}",
        "",
        "## Totals",
        "",
        f"- training_ready findings: {total_training}",
        f"- training-message-ready findings: {total_messages}",
        f"- protocol-ready findings: {total_protocol}",
        f"- pending review candidates: {total_review}",
        "",
        "## Goal Readiness",
        "",
        (
            "| Goal | Training ready | Messages | Protocol inputs | "
            "Review candidates | Next action |"
        ),
        "|---|---:|---:|---:|---:|---|",
    ]
    for goal in goals:
        goal_id = _text(goal.get("goal_id"))
        question = _text(goal.get("question"))
        next_action = _text(_mapping(goal.get("next_review_action")).get("label"))
        if not next_action:
            next_action = _readiness_next_action(goal)
        lines.append(
            "| "
            f"{_markdown_cell(_goal_heading(goal_id, question), 120)} | "
            f"{int(goal.get('training_ready_count') or 0)} | "
            f"{int(goal.get('training_message_ready_count') or 0)} | "
            f"{int(goal.get('protocol_ready_count') or 0)} | "
            f"{int(goal.get('review_candidate_count') or 0)} | "
            f"{_markdown_cell(next_action, 120)} |"
        )
    lines.extend(
        [
            "",
            "## Export Rule",
            "",
            (
                "- `training-jsonl --require-training-ready` should be treated as "
                "complete only after every target goal has at least one "
                "training-ready sample."
            ),
            (
                "- Existing training-ready rows may still be emitted while the "
                "overall command fails for unreviewed goals; use this report to "
                "find the remaining goals."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_expert_satisfaction_report(summary: dict[str, Any]) -> str:
    goals = _mapping_list(summary.get("goals"))
    review_candidate_count = _sum_goal_int(summary, "review_candidate_count")
    missing_training = [
        _text(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("training_ready_count") or 0) == 0
    ]
    missing_messages = [
        _text(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("training_message_ready_count") or 0) == 0
    ]
    missing_protocol = [
        _text(goal.get("goal_id"))
        for goal in goals
        if int(goal.get("protocol_ready_count") or 0) == 0
    ]
    criteria = [
        {
            "title": "Expert review usable",
            "status": "blocked" if review_candidate_count else "satisfied",
            "evidence": f"{review_candidate_count} review candidate(s) remain.",
            "next": (
                "Review candidates in review-checklist.md, then fill accept/reject/correct decisions."
                if review_candidate_count
                else "No review candidates remain."
            ),
        },
        {
            "title": "Dataset accumulation usable",
            "status": "blocked" if missing_training or missing_messages else "satisfied",
            "evidence": (
                f"{len(missing_training)} goal(s) lack training-ready samples; "
                f"{len(missing_messages)} goal(s) lack training messages."
            ),
            "next": (
                "Dry-run and import human-confirmed decisions, then export messages/training JSONL."
                if missing_training or missing_messages
                else "Training-ready exports are available."
            ),
        },
        {
            "title": "Experiment design usable",
            "status": "blocked" if missing_protocol else "satisfied",
            "evidence": f"{len(missing_protocol)} goal(s) lack protocol-ready inputs.",
            "next": (
                "Correct variables, outcomes, direction, scope, or evidence refs until protocol inputs are ready."
                if missing_protocol
                else "Goal Copilot has protocol-ready curated Findings."
            ),
        },
    ]
    overall = "satisfied" if all(item["status"] == "satisfied" for item in criteria) else "blocked"
    lines = [
        "# Lens Expert Satisfaction Gate",
        "",
        f"Collection: {_text(summary.get('collection_id')) or 'n/a'}",
        f"Overall: {overall}",
        "",
        "| Layer | Status | Evidence | Next action |",
        "|---|---|---|---|",
    ]
    for item in criteria:
        lines.append(
            "| "
            f"{_markdown_cell(item['title'], 80)} | "
            f"{item['status']} | "
            f"{_markdown_cell(item['evidence'], 120)} | "
            f"{_markdown_cell(item['next'], 140)} |"
        )
    lines.extend(
        [
            "",
            "## Gate Rule",
            "",
            (
                "- This gate is satisfied only when expert review is clear, every "
                "target goal has exportable training-ready samples, and protocol "
                "inputs are available for experiment design."
            ),
            (
                "- If this report is blocked while the CLI says `pass "
                "(incomplete)`, the code path is usable but real expert labels "
                "are still missing."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_optimization_summary(summary: dict[str, Any]) -> str:
    aggregate = _aggregate_goal_stats(summary)
    lines = [
        "# Lens Optimization Summary",
        "",
        f"Collection: {_text(summary.get('collection_id')) or 'n/a'}",
        "",
        "## Current Error Types",
        "",
    ]
    lines.extend(_stats_lines(aggregate["issue_types"], empty="- No issue types yet."))
    lines.extend(["", "## Review Risk Types", ""])
    lines.extend(_stats_lines(aggregate["review_reasons"], empty="- No review risks."))
    lines.extend(["", "## System Warnings", ""])
    lines.extend(_stats_lines(aggregate["system_warnings"], empty="- No system warnings."))
    lines.extend(["", "## Optimization Hotspots", ""])
    hotspot_lines = _hotspot_lines(aggregate["hotspots"])
    lines.extend(hotspot_lines or ["- No grouped hotspots yet."])
    lines.extend(
        [
            "",
            "## How To Use",
            "",
            (
                "- If issue types dominate, improve labels or prompts for the "
                "specific error category."
            ),
            (
                "- If review risks dominate, finish expert review before tuning; "
                "unconfirmed risks are not model-quality failures yet."
            ),
            (
                "- If system warnings dominate, inspect the corresponding parser "
                "or evidence construction path before fine-tuning."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_text_summary(result: dict[str, Any]) -> str:
    lines = [
        f"Prepared Lens goal review workspace: {result['output_dir']}",
        f"Status: {result['status']}",
        f"Expert satisfaction: {_expert_satisfaction_status(result)}",
        f"Collection: {result['collection_id']}",
        f"Goals: {result['goal_count']}",
        f"Review candidates: {result['review_candidate_count']}",
        "Files:",
    ]
    for file_info in result["files"]:
        lines.append(f"- {file_info['filename']} ({file_info['line_count']} lines)")
    lines.extend(
        [
            "Next:",
            "- Review review-packet.txt and source links.",
            "- Fill reviewed-findings.template.jsonl with human-confirmed decisions.",
            "- Dry-run import_goal_review_decisions.py before writing labels.",
        ]
    )
    return "\n".join(lines)


def _expert_satisfaction_status(summary: dict[str, Any]) -> str:
    goals = _mapping_list(summary.get("goals"))
    if _candidate_count(summary) or int(summary.get("review_candidate_count") or 0):
        return "blocked"
    if goals:
        if any(int(goal.get("training_ready_count") or 0) == 0 for goal in goals):
            return "blocked"
        if any(int(goal.get("training_message_ready_count") or 0) == 0 for goal in goals):
            return "blocked"
        if any(int(goal.get("protocol_ready_count") or 0) == 0 for goal in goals):
            return "blocked"
    goal_count = int(summary.get("goal_count") or 0)
    if goal_count:
        if int(summary.get("training_ready_count") or 0) < goal_count:
            return "blocked"
        if int(summary.get("training_message_ready_count") or 0) < goal_count:
            return "blocked"
        if int(summary.get("protocol_ready_count") or 0) < goal_count:
            return "blocked"
    return "satisfied"


def _workspace_manifest(
    summary: dict[str, Any],
    *,
    output_dir: Path,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": _text(summary.get("status")) or "unknown",
        "collection_id": _text(summary.get("collection_id")),
        "goal_count": int(summary.get("goal_count") or 0),
        "review_candidate_count": _candidate_count(summary),
        "training_ready_count": _sum_goal_int(summary, "training_ready_count"),
        "training_message_ready_count": _sum_goal_int(
            summary,
            "training_message_ready_count",
        ),
        "protocol_ready_count": _sum_goal_int(summary, "protocol_ready_count"),
        "output_dir": str(output_dir),
        "files": files,
        "next_steps": [
            "review review-packet.txt and source links",
            "fill reviewed-findings.template.jsonl with human-confirmed decisions",
            "dry-run import_goal_review_decisions.py before writing labels",
        ],
    }


def _ensure_empty_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output dir must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _default_output_dir(collection_id: str) -> Path:
    safe_collection_id = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in collection_id
    )[:48]
    return (
        Path(tempfile.gettempdir())
        / f"lens-goal-review-{safe_collection_id or 'collection'}-{uuid4().hex[:8]}"
    )


def _load_dataset_quality_module():
    return _load_sibling_module("check_goal_dataset_quality.py", "check_goal_dataset_quality")


def _load_findings_projection_module():
    return _load_sibling_module(
        "check_goal_findings_projection.py",
        "check_goal_findings_projection",
    )


def _load_sibling_module(filename: str, module_name: str):
    script_path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(
        module_name,
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _enrich_goal_questions(
    summary: dict[str, Any],
    *,
    collection_id: str,
    goal_ids: tuple[str, ...],
    api_base_url: str | None,
) -> None:
    try:
        findings_module = _load_findings_projection_module()
        findings_summary = findings_module.check_goal_findings_projection(
            collection_id=collection_id,
            goal_ids=goal_ids,
            api_base_url=api_base_url,
        )
    except Exception as exc:  # noqa: BLE001
        summary["goal_question_warning"] = f"goal question lookup failed: {exc}"
        return
    questions = {
        _text(goal.get("goal_id")): _text(goal.get("question"))
        for goal in _mapping_list(findings_summary.get("goals"))
    }
    for goal in _mapping_list(summary.get("goals")):
        goal_id = _text(goal.get("goal_id"))
        question = questions.get(goal_id)
        if question:
            goal["question"] = question


def _candidate_count(summary: dict[str, Any]) -> int:
    total = 0
    for goal in _mapping_list(summary.get("goals")):
        packet = _mapping(goal.get("review_packet"))
        total += len(_mapping_list(packet.get("candidates")))
    return total


def _sum_goal_int(summary: dict[str, Any], key: str) -> int:
    return sum(int(goal.get(key) or 0) for goal in _mapping_list(summary.get("goals")))


def _top_risks(risk_summary: dict[str, Any]) -> list[str]:
    ranked = sorted(
        risk_summary.items(),
        key=lambda item: (-int(item[1] or 0), str(item[0])),
    )
    return [f"{key}={value}" for key, value in ranked[:5]]


def _evidence_label(candidate: dict[str, Any]) -> str:
    evidence = _mapping_list(candidate.get("evidence"))
    if not evidence:
        return "n/a"
    first = evidence[0]
    label = _text(first.get("label")) or _text(first.get("source_ref")) or "evidence"
    if len(evidence) > 1:
        return f"{label} (+{len(evidence) - 1})"
    return label


def _candidate_gate_text(candidate: dict[str, Any]) -> str:
    gate = _mapping(candidate.get("acceptance_gate"))
    hint = _mapping(candidate.get("review_decision_hint"))
    accept_allowed = bool(gate.get("accept_allowed"))
    if not accept_allowed:
        blockers = _text_list(hint.get("why_accept_blocked")) or _text_list(
            gate.get("blocking_missing")
        )
        suffix = f": {', '.join(blockers)}" if blockers else ""
        return f"accept blocked{suffix}"
    status = _text(gate.get("status"))
    if status:
        return status
    return "accept after checks"


def _candidate_note_prompt(candidate: dict[str, Any]) -> str:
    if not bool(candidate.get("expert_note_required")):
        action_code = _text(candidate.get("recommended_action_code"))
        prompt = EXPERT_NOTE_PROMPTS.get(action_code)
        return prompt or "optional"
    return _text(candidate.get("expert_note_prompt")) or "required"


def _ranked_review_candidates(summary: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for goal in _mapping_list(summary.get("goals")):
        packet = _mapping(goal.get("review_packet"))
        goal_id = _text(packet.get("goal_id")) or _text(goal.get("goal_id"))
        question = _text(goal.get("question"))
        review_url = _text(packet.get("review_url"))
        for candidate in _mapping_list(packet.get("candidates")):
            rank, priority = _review_priority(candidate)
            open_url = _text(candidate.get("open_url")) or review_url
            rows.append(
                {
                    "rank": f"{rank:02d}",
                    "priority": priority,
                    "goal": _goal_heading(goal_id, question),
                    "finding": _text(candidate.get("statement")),
                    "action": _text(candidate.get("recommended_action")) or "review",
                    "evidence": _evidence_label(candidate),
                    "open_url": open_url,
                }
            )
    rows.sort(key=lambda row: (row["rank"], row["goal"], row["finding"]))
    return rows


def _review_priority(candidate: dict[str, Any]) -> tuple[int, str]:
    action_code = _text(candidate.get("recommended_action_code"))
    gate = _mapping(candidate.get("acceptance_gate"))
    hint = _mapping(candidate.get("review_decision_hint"))
    review_terms = {
        action_code,
        *_text_list(candidate.get("review_reasons")),
        *_text_list(candidate.get("warnings")),
    }
    if not bool(gate.get("accept_allowed")) or _text_list(hint.get("blocked_actions")):
        return 1, "P1 correct/reject: accept blocked"
    if "table_row_alignment_uncertain" in review_terms or action_code == "verify_table_rows":
        return 1, "P1 verify table alignment"
    if action_code in {"review_table_rows", "review_table_variables"}:
        return 2, "P2 verify table rows or variables"
    if "missing_mechanism_evidence" in review_terms or action_code == "check_mechanism_requirement":
        return 3, "P3 decide mechanism requirement"
    if action_code == "accept_as_paper_level":
        return 4, "P4 confirm paper-level scope"
    return 5, "P5 general expert review"


def _priority_counts(rows: list[dict[str, str]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        priority = row["priority"]
        counts[priority] = counts.get(priority, 0) + 1
    return sorted(counts.items())


def _candidate_checklist_lines(
    index: int,
    candidate: dict[str, Any],
    review_url: str,
) -> list[str]:
    open_url = _text(candidate.get("open_url")) or review_url
    lines = [
        f"#### {index}. {_markdown_cell(_text(candidate.get('statement')), 180)}",
        "",
        f"- Finding id: `{_text(candidate.get('finding_id')) or 'n/a'}`",
        f"- Open finding: {_markdown_link('open finding', open_url)}",
        f"- Gate: {_candidate_gate_text(candidate)}",
        f"- Recommended action: {_text(candidate.get('recommended_action')) or 'n/a'}",
        f"- Note: {_candidate_note_prompt(candidate)}",
        (
            "- Fields: "
            f"variables={_join_text_list(candidate.get('variables'))}; "
            f"outcomes={_join_text_list(candidate.get('outcomes'))}; "
            f"direction={_text(candidate.get('direction')) or 'n/a'}"
        ),
        f"- Scope: {_markdown_cell(_text(candidate.get('scope_summary')), 180)}",
        f"- Evidence: {_evidence_label(candidate)}",
    ]
    lines.extend(_candidate_evidence_audit_lines(candidate))
    review_reasons = _text_list(candidate.get("review_reasons"))
    warnings = _text_list(candidate.get("warnings"))
    if review_reasons:
        lines.append(f"- Review reasons: {_join_text_list(review_reasons)}")
    if warnings:
        lines.append(f"- Warnings: {_join_text_list(warnings)}")
    lines.extend(
        [
            "- Checks:",
            "  - [ ] Source link opens the cited paper/table/block.",
            "  - [ ] Evidence quote directly supports the finding.",
            "  - [ ] Variable and outcome are not swapped or over-generalized.",
            "  - [ ] Direction matches the cited result.",
            "  - [ ] Scope/context is narrow enough for downstream experiment design.",
        ]
    )
    return lines


def _candidate_evidence_audit_lines(candidate: dict[str, Any]) -> list[str]:
    evidence_records = _mapping_list(candidate.get("evidence"))
    if not evidence_records:
        return ["- Evidence audit: no evidence records exported."]
    lines = ["- Evidence audit:"]
    for index, record in enumerate(evidence_records, start=1):
        label = _text(record.get("label")) or _text(record.get("source_ref"))
        lines.append(f"  - Evidence {index}: {_markdown_cell(label, 160)}")
        source_href = _text(record.get("href")) or _text(record.get("open"))
        if source_href:
            lines.append(f"    - Open source: {_markdown_link('open source', source_href)}")
        quote = _text(record.get("quote"))
        if quote:
            lines.append(f"    - Quote: {_markdown_cell(quote, 260)}")
        table_audit = _mapping(record.get("table_audit"))
        columns = _text_list(table_audit.get("columns"))
        if columns:
            lines.append(f"    - Table columns: {_join_text_list(columns)}")
        for row_index, row in enumerate(
            _mapping_list(table_audit.get("relevant_rows")),
            start=1,
        ):
            row_text = _table_row_text(row, columns)
            if row_text:
                aligned = row.get("aligned")
                suffix = " (alignment uncertain)" if aligned is False else ""
                lines.append(
                    f"    - Table row {row_index}{suffix}: "
                    f"{_markdown_cell(row_text, 260)}"
                )
    return lines


def _table_row_text(row: dict[str, Any], columns: list[str]) -> str:
    cells_value = row.get("cells")
    cells = _mapping(cells_value)
    if cells:
        return "; ".join(
            f"{key}: {value}"
            for key, value in cells.items()
            if _text(key) and _text(value)
        )
    if isinstance(cells_value, list):
        values = _text_list(cells_value)
        if values:
            return "; ".join(
                f"{columns[index] if index < len(columns) else f'cell {index + 1}'}: {value}"
                for index, value in enumerate(values)
                if value
            )
    return "; ".join(
        f"{key}: {value}"
        for key, value in row.items()
        if key != "cells" and _text(key) and _text(value)
    )


def _goal_heading(goal_id: str, question: str) -> str:
    if question:
        return f"{question} ({goal_id})"
    return goal_id or "n/a"


def _markdown_cell(value: str, limit: int) -> str:
    text = value.replace("|", "\\|").replace("\n", " ").strip()
    if len(text) <= limit:
        return text or "n/a"
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _markdown_link(label: str, href: str) -> str:
    if not href:
        return "n/a"
    return f"[{label}]({href})"


def _readiness_next_action(goal: dict[str, Any]) -> str:
    if int(goal.get("review_candidate_count") or 0) > 0:
        return "review pending candidates"
    if int(goal.get("training_ready_count") or 0) == 0:
        return "add or confirm at least one expert label"
    if int(goal.get("training_message_ready_count") or 0) == 0:
        return "repair training message fields"
    if int(goal.get("protocol_ready_count") or 0) == 0:
        return "repair protocol input fields"
    return "ready for training export and protocol drafting"


def _aggregate_goal_stats(summary: dict[str, Any]) -> dict[str, Any]:
    issue_types: dict[str, int] = {}
    review_reasons: dict[str, int] = {}
    system_warnings: dict[str, int] = {}
    hotspots: dict[str, dict[str, int]] = {}
    for goal in _mapping_list(summary.get("goals")):
        _merge_top_counts(issue_types, goal.get("top_issue_types"))
        _merge_top_counts(review_reasons, goal.get("top_review_reasons"))
        _merge_top_counts(system_warnings, goal.get("top_system_warnings"))
        for group_key, group in _mapping(
            goal.get("optimization_breakdown")
        ).items():
            for name, metrics in _mapping(group).items():
                hotspot = hotspots.setdefault(f"{group_key}:{name}", {})
                for metric_group in (
                    "issue_type",
                    "error_category",
                    "review_candidate_reason",
                    "system_warning",
                ):
                    for metric, count in _mapping(
                        _mapping(metrics).get(metric_group)
                    ).items():
                        if _text(metric) == "none":
                            continue
                        key = f"{metric_group}:{metric}"
                        hotspot[key] = hotspot.get(key, 0) + int(count or 0)
    return {
        "issue_types": issue_types,
        "review_reasons": review_reasons,
        "system_warnings": system_warnings,
        "hotspots": hotspots,
    }


def _merge_top_counts(target: dict[str, int], rows: Any) -> None:
    for row in _mapping_list(rows):
        name = _text(row.get("name"))
        if name and name != "none":
            target[name] = target.get(name, 0) + int(row.get("count") or 0)


def _stats_lines(stats: dict[str, int], *, empty: str) -> list[str]:
    ranked = _ranked_counts(stats)
    if not ranked:
        return [empty]
    return [f"- {name}: {count}" for name, count in ranked[:10]]


def _hotspot_lines(hotspots: dict[str, dict[str, int]]) -> list[str]:
    scored = []
    for name, metrics in hotspots.items():
        score = sum(metrics.values())
        if score:
            scored.append((name, score, metrics))
    scored.sort(key=lambda item: (-item[1], item[0]))
    lines = []
    for name, _score, metrics in scored[:10]:
        top_metrics = ", ".join(
            f"{metric}={count}" for metric, count in _ranked_counts(metrics)[:3]
        )
        lines.append(f"- {name}: {top_metrics}")
    return lines


def _ranked_counts(stats: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(stats.items(), key=lambda item: (-int(item[1] or 0), item[0]))


def _line_count(value: str) -> int:
    if not value:
        return 0
    return len(value.splitlines())


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _text_list(value: Any) -> list[str]:
    return (
        [_text(item) for item in value if _text(item)]
        if isinstance(value, list)
        else []
    )


def _join_text_list(value: Any) -> str:
    values = _text_list(value)
    return ", ".join(values) if values else "n/a"


if __name__ == "__main__":
    main()
