"""Explicit #399 replay using the current Web composition and an isolated corpus."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from scripts.evaluation.research_agent.run_scenarios import (
    database_url,
    scientific_snapshot,
    save,
)


def document_fingerprints(documents):
    return sorted(
        [
            {
                "document_id": doc.document_id,
                "source_document_sha256": hashlib.sha256(
                    json.dumps(asdict(doc), ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest(),
                "block_count": len(doc.blocks),
            }
            for doc in documents
        ],
        key=lambda item: item["document_id"],
    )


async def run(args):
    url = database_url()  # Reject remote databases and names without the _test suffix.
    if args.output.exists():
        raise ValueError("output already exists")
    os.environ["LENS_DATABASE_URL"] = url.render_as_string(hide_password=False)
    # Import composition only after choosing the isolated database.
    from main import lifespan
    from application.chat import session_service
    from application.chat.model import RESEARCH_AGENT_PROMPT_VERSION
    from application.source import collection_service
    from repositories.chat_repository import ChatRepo
    from repositories.source_artifact_repository import SourceArtifactRepo

    async with lifespan():
        service = session_service.ChatService
        await collection_service.get_collection_for_user(
            args.collection_id, args.user_id
        )
        documents = await SourceArtifactRepo.list_documents(args.collection_id)
        if len(documents) != 100:
            raise ValueError("this acceptance fixture requires 100 prepared documents")
        before = {
            "scientific": scientific_snapshot(url),
            "corpus": document_fingerprints(documents),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.snapshot:
            save(args.output, before)
            return 0
        if before != json.loads(args.expected_snapshot.read_text()):
            raise ValueError("prepared scientific data or Source content changed")
        raw = args.fixture.read_bytes()
        fixture = json.loads(raw)
        if fixture["issue"] != 399 or len(fixture["turns"]) != 4:
            raise ValueError("expected the frozen four-turn fixture")
        report = {
            "fixture_sha256": hashlib.sha256(raw).hexdigest(),
            "before": before,
            "revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "diff_sha256": hashlib.sha256(
                subprocess.check_output(["git", "diff", "HEAD", "--", "backend"])
            ).hexdigest(),
            "model": getattr(service.runner.model, "model", "unknown"),
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "limits": asdict(service.runner.limits),
            "turns": [],
            "technical_result": "incomplete",
            "scientific_review": "not_reviewed",
        }
        save(args.output, report)
        try:
            session = await service.create_session(
                collection_id=args.collection_id, user_id=args.user_id
            )
            report["session_id"] = session.session_id
            await ChatRepo.set_permission(
                session.session_id,
                args.user_id,
                mode="read_only",
                actions=[],
                expires_at=None,
                expected_revision=0,
            )
            seen_calls = set()
            for number, prompt in enumerate(fixture["turns"], 1):
                response = await service.send_message(
                    session.session_id, args.user_id, message=prompt
                )
                trajectory = await service.get_trajectory_for_user(
                    session.session_id, args.user_id
                )
                calls = [
                    await ChatRepo.read_tool_call(call.tool_call_id)
                    for message in trajectory["messages"]
                    for call in message.tool_calls
                ]
                new_calls = [
                    call
                    for call in calls
                    if call is not None and call.tool_call_id not in seen_calls
                ]
                seen_calls.update(call.tool_call_id for call in new_calls)
                snapshot = await ChatRepo.read_response_snapshot(session.session_id)
                audits = await ChatRepo.read_model_calls(session_id=session.session_id)
                report["turns"].append(
                    {
                        "number": number,
                        "response": response,
                        "trajectory": trajectory,
                        "calls": new_calls,
                        "model_calls": [
                            {
                                "call_id": call.call_id,
                                "purpose": call.purpose,
                                "status": call.status,
                                "error_code": call.error_code,
                                "prompt_tokens": call.prompt_tokens,
                                "completion_tokens": call.completion_tokens,
                                "total_tokens": call.total_tokens,
                            }
                            for call in audits
                        ],
                        "progress": snapshot.progress if snapshot is not None else None,
                    }
                )
                save(args.output, report)
                if response["status"] != "completed" or response.get(
                    "completion_reason"
                ) not in (None, "model_answer"):
                    break
        finally:
            report["after"] = {
                "scientific": scientific_snapshot(url),
                "corpus": document_fingerprints(
                    await SourceArtifactRepo.list_documents(args.collection_id)
                ),
            }
            report["scientific_data_unchanged"] = before == report["after"]
            report["technical_result"] = (
                "passed"
                if (
                    len(report["turns"]) == 4
                    and report["scientific_data_unchanged"]
                    and all(
                        turn["response"]["status"] == "completed"
                        and turn["response"].get("completion_reason")
                        in (None, "model_answer")
                        for turn in report["turns"]
                    )
                )
                else "failed"
            )
            save(args.output, report)
        return int(report["technical_result"] != "passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/chat/inconel718_four_turns.json"),
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="freeze scientific rows and Source content without calling the model",
    )
    parser.add_argument("--expected-snapshot", type=Path)
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.snapshot and args.expected_snapshot is None:
        parser.error("--expected-snapshot is required for replay")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
