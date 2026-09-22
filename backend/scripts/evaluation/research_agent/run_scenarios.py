"""Replay explicit research conversations through the production session service.

Run from backend: python -m scripts.evaluation.research_agent.run_scenarios --help
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


def validate_fixture(fixture):
    from domain.chat.permissions import AUTO_ACTIONS

    cases = fixture.get("scenarios", [])
    ids = [case["id"] for case in cases]
    if len(ids) != 21 or set(ids) != {f"S{i:02}" for i in range(1, 22)}:
        raise ValueError("fixture must contain S01-S21 exactly once")
    collections = [case["collection_id"] for case in cases]
    if len(set(collections)) != 21:
        raise ValueError("each scenario requires its own isolated collection")
    for case in cases:
        if "REPLACE" in json.dumps(case, ensure_ascii=False):
            raise ValueError("replace template identities and scope before replay")
        if not case["turns"] or not case["scientific_rubric"]:
            raise ValueError("each scenario requires turns and a scientific rubric")
        automatic_actions = set(case.get("automatic_actions", []))
        allowed_actions = set(case.get("allowed_approval_actions", []))
        if not automatic_actions <= allowed_actions:
            raise ValueError("automatic actions must be within the scenario approval scope")
        if not automatic_actions <= AUTO_ACTIONS:
            raise ValueError("automatic action is not supported by session permissions")
        for turn in case["turns"]:
            if not turn.get("message") or not turn.get("expected_statuses"):
                raise ValueError("each turn requires a message and expected statuses")
            if set(turn.get("approve", [])) - set(case.get("allowed_approval_actions", [])):
                raise ValueError("approval action is outside scenario scope")
            if len(turn.get("approve", [])) != len(set(turn.get("approve", []))):
                raise ValueError("approval actions must be unique within a turn")


def database_url():
    from sqlalchemy.engine import make_url
    url = make_url(os.environ["LENS_TEST_DATABASE_URL"])
    if url.drivername != "postgresql+psycopg" or url.host not in {"localhost", "127.0.0.1"} or not str(url.database).endswith("_test"):
        raise ValueError("replay requires a localhost PostgreSQL *_test database")
    return url


def scientific_snapshot(url):
    from sqlalchemy import create_engine, text
    engine = create_engine(url)
    result = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            for table in ("documents", "document_preparations", "research_objectives",
                          "objective_analyses", "finding_feedback_records", "finding_curation_records"):
                rows = connection.execute(text(f"SELECT md5(to_jsonb(t)::text) FROM {table} t ORDER BY 1")).scalars().all()
                result[table] = {"count": len(rows), "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
    finally:
        engine.dispose()
    return result


def save(path, value):
    def encode(item):
        if hasattr(item, "to_record"):
            return item.to_record()
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n", encoding="utf-8")


async def replay_case(service, case, mode):
    result = {"scenario_id": case["id"], "session_id": None, "permission_mode": mode,
              "turns": [], "failures": [], "scientific_review": "incomplete",
              "scientific_rubric": case["scientific_rubric"], "approval_and_persistence": "incomplete",
              "recall": "incomplete"}
    try:
        session = await service.create_session(collection_id=case["collection_id"], user_id=case["user_id"])
        result["session_id"] = session.session_id
        if mode != "confirm":
            await service.repository.set_permission(session.session_id, case["user_id"], mode=mode,
                actions=case.get("automatic_actions", []) if mode == "auto" else [],
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat() if mode == "auto" else None,
                expected_revision=0)
        automatic_authorization_active = mode == "auto"
        for instruction in case["turns"]:
            if instruction.get("new_session"):
                session = await service.create_session(collection_id=case["collection_id"], user_id=case["user_id"])
                automatic_authorization_active = False
            if instruction.get("revoke"):
                permission = await service.repository.read_permission(session.session_id, case["user_id"])
                await service.repository.set_permission(session.session_id, case["user_id"], mode="confirm",
                    actions=[], expires_at=None, expected_revision=permission["revision"])
                automatic_authorization_active = False
            previous = await service.get_trajectory_for_user(session.session_id, case["user_id"])
            previous_call_ids = {
                request.tool_call_id
                for message in previous["messages"]
                for request in message.tool_calls
            }
            turn = await service.post_message_for_user(session.session_id, case["user_id"], message=instruction["message"])
            record = {"session_id": session.session_id, "message": instruction["message"], "response": turn,
                      "automatic_authorization_active": automatic_authorization_active, "decisions": []}
            result["turns"].append(record)
            # Only exact explicitly listed fixture actions are approved, once per entry.
            for name in instruction.get("approve", []):
                if automatic_authorization_active and name in case.get("automatic_actions", []):
                    continue
                pending = turn.get("pending_approval")
                if pending is None or pending.name != name:
                    result["failures"].append(f"expected approval for {name}")
                    break
                turn = await service.decide_tool_call_for_user(session.session_id, pending.tool_call_id,
                    case["user_id"], arguments_digest=pending.arguments_digest, decision="approved")
                record["decisions"].append({"tool_call_id": pending.tool_call_id, "arguments_digest": pending.arguments_digest,
                                             "name": name, "response": turn})
            if turn["status"] not in instruction["expected_statuses"]:
                result["failures"].append(f"unexpected status: {turn['status']}")
            if turn.get("completion_reason") not in {None, "model_answer"}:
                result["failures"].append(f"incomplete termination: {turn['completion_reason']}")
            record["trajectory"] = await service.get_trajectory_for_user(session.session_id, case["user_id"])
            requests = [request for message in record["trajectory"]["messages"] for request in message.tool_calls]
            calls = [
                await service.repository.read_tool_call(request.tool_call_id)
                for request in requests
                if request.tool_call_id not in previous_call_ids
            ]
            record["calls"] = calls
            successful_calls = [
                call for call in calls
                if call is not None and call.status.value == "succeeded"
            ]
            succeeded = {call.name for call in successful_calls}
            for required in instruction.get("required_tools", []):
                if required not in succeeded:
                    result["failures"].append(f"required successful observation missing: {required}")
            successful_counts = Counter(call.name for call in successful_calls)
            for approved in instruction.get("approve", []):
                if successful_counts[approved] != 1:
                    result["failures"].append(
                        f"approved action must succeed exactly once: {approved}"
                    )
                    continue
                call = next(call for call in successful_calls if call.name == approved)
                expected_basis = (
                    "scope_grant"
                    if automatic_authorization_active and approved in case.get("automatic_actions", [])
                    else "explicit"
                )
                if call.decision_basis != expected_basis:
                    result["failures"].append(
                        f"unexpected authorization basis for {approved}: {call.decision_basis}"
                    )
            if instruction.get("no_tools") and calls:
                result["failures"].append("unexpected tool use")
            if instruction.get("no_writes") and any(call is not None and call.risk.value == "write"
                                                       and call.status.value == "succeeded" for call in calls):
                result["failures"].append("unexpected scientific write")
            if (turn.get("pending_approval") or turn["status"] == "failed") and instruction is not case["turns"][-1]:
                break
        if len(result["turns"]) != len(case["turns"]):
            result["failures"].append("conversation not completed")
    except Exception as exc:
        result["failures"].append(f"exception_type:{type(exc).__name__}")
    result["technical_result"] = "failed" if result["failures"] else "passed"
    return result


async def run(args):
    fixture_bytes = args.fixture.read_bytes()
    fixture = json.loads(fixture_bytes)
    validate_fixture(fixture)
    url = database_url()
    if args.output.exists():
        raise ValueError("output already exists")
    os.environ["LENS_DATABASE_URL"] = url.render_as_string(hide_password=False)
    before = scientific_snapshot(url)
    if fixture.get("expected_snapshot") != before:
        raise ValueError("fixture scientific snapshot differs; verify imported data first")
    # Import composition only after selecting the isolated database.
    from main import ApplicationOverrides, build_application_runtime
    from application.chat.model import RESEARCH_AGENT_PROMPT_VERSION
    runtime = await build_application_runtime(ApplicationOverrides())
    try:
        report = {"implementation_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  "diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD", "--", "backend"])).hexdigest(),
                  "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(), "database_name": url.database,
                  "model": getattr(runtime.chat_session_service.runner.model, "model", "unknown"),
                  "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
                  "limits": asdict(runtime.chat_session_service.runner.limits),
                  "before": before, "scenarios": []}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        save(args.output, report)
        for case in fixture["scenarios"]:
            if args.scenario and case["id"] != args.scenario:
                continue
            report["scenarios"].append(await replay_case(runtime.chat_session_service, case, args.mode))
            report["after"] = scientific_snapshot(url)
            save(args.output, report)
            print(case["id"], report["scenarios"][-1]["technical_result"], flush=True)
        return int(any(case["failures"] for case in report["scenarios"]))
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", action="store_true", help="read-only fingerprint of prepared isolated fixtures")
    parser.add_argument("--scenario", choices=[f"S{i:02d}" for i in range(1, 22)])
    parser.add_argument("--mode", choices=["confirm", "read_only", "auto"], default="confirm")
    args = parser.parse_args()
    if args.snapshot:
        if args.output.exists():
            parser.error("output already exists")
        save(args.output, scientific_snapshot(database_url()))
        return 0
    if not args.fixture:
        parser.error("--fixture is required for replay")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
