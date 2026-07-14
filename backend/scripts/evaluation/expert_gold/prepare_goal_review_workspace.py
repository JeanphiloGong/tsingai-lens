#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_COLLECTION_ID = "col_0cc5013fdb3c"
DEFAULT_GOAL_IDS = (
    "goal_0914003ad572",
    "goal_1a7a26d850b9",
    "goal_399171646354",
    "goal_061c9c049e69",
    "goal_6bf7d2c1030e",
    "goal_3037e425673a",
)


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
        required=True,
        help="Empty directory where review workspace files will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = prepare_goal_review_workspace(
        collection_id=args.collection_id,
        goal_ids=tuple(args.goal_ids or DEFAULT_GOAL_IDS),
        api_base_url=args.api_base_url,
        output_dir=Path(args.output_dir),
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
            "dataset-readiness.md",
            render_dataset_readiness_report(summary),
            "Training export and protocol readiness by goal.",
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
        f"Goal count: {int(summary.get('goal_count') or 0)}",
        f"Review candidates: {candidate_count}",
        "",
        "Files",
        "-----",
    ]
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
            "",
        ]
    )
    return "\n".join(lines)


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
        review_url = _text(packet.get("review_url"))
        lines.extend(
            [
                f"### {goal_id}",
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
        lines.extend(["", "| Finding | Action | Evidence | Open |", "|---|---|---|---|"])
        for candidate in candidates:
            lines.append(
                "| "
                f"{_markdown_cell(_text(candidate.get('statement')), 140)} | "
                f"{_markdown_cell(_text(candidate.get('recommended_action')), 90)} | "
                f"{_markdown_cell(_evidence_label(candidate), 100)} | "
                f"{_markdown_link('open', _text(candidate.get('open_url')) or review_url)} |"
            )
        lines.append("")
    if len(lines) == 6:
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
        next_action = _text(_mapping(goal.get("next_review_action")).get("label"))
        if not next_action:
            next_action = _readiness_next_action(goal)
        lines.append(
            "| "
            f"{_markdown_cell(goal_id, 80)} | "
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


def _load_dataset_quality_module():
    script_path = Path(__file__).resolve().with_name("check_goal_dataset_quality.py")
    spec = importlib.util.spec_from_file_location(
        "check_goal_dataset_quality",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


if __name__ == "__main__":
    main()
