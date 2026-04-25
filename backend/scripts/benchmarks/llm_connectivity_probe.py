#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from _common import (
    add_runtime_arguments,
    build_openai_client,
    display_base_url,
    resolve_runtime,
    summarize_timings,
    write_json_output,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark provider connectivity and minimal chat latency without importing "
            "backend application modules."
        )
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Number of repeated calls per enabled benchmark.",
    )
    parser.add_argument(
        "--skip-models",
        action="store_true",
        help="Skip the `models.list` benchmark.",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Skip the minimal `chat.completions.create` benchmark.",
    )
    parser.add_argument(
        "--message",
        default="Reply with exactly OK.",
        help="User message used for the minimal chat benchmark.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional JSON file path for the final benchmark summary.",
    )
    add_runtime_arguments(
        parser,
        default_temperature=0.0,
        include_max_completion_tokens=True,
        default_max_completion_tokens=8,
    )
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be greater than 0")
    if args.skip_models and args.skip_chat:
        parser.error("At least one benchmark must be enabled.")
    return args


def benchmark_models(client: Any, repeat: int) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    timings: list[float] = []
    for run in range(1, repeat + 1):
        started_at = perf_counter()
        response = client.models.list()
        elapsed_s = perf_counter() - started_at
        timings.append(elapsed_s)
        runs.append(
            {
                "run": run,
                "elapsed_s": round(elapsed_s, 6),
                "model_count": len(getattr(response, "data", []) or []),
            }
        )
    return {
        "runs": runs,
        "timing": summarize_timings(timings),
    }


def benchmark_chat(
    client: Any,
    *,
    repeat: int,
    model: str,
    message: str,
    temperature: float,
    max_completion_tokens: int | None,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    timings: list[float] = []
    request_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": "Reply with exactly OK."},
            {"role": "user", "content": message},
        ],
    }
    if max_completion_tokens is not None:
        request_kwargs["max_completion_tokens"] = max_completion_tokens

    for run in range(1, repeat + 1):
        started_at = perf_counter()
        response = client.chat.completions.create(**request_kwargs)
        elapsed_s = perf_counter() - started_at
        timings.append(elapsed_s)
        content = ""
        finish_reason = None
        if response.choices:
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            content = str(choice.message.content or "").strip()
        runs.append(
            {
                "run": run,
                "elapsed_s": round(elapsed_s, 6),
                "finish_reason": finish_reason,
                "content": content,
            }
        )
    return {
        "message": message,
        "runs": runs,
        "timing": summarize_timings(timings),
    }


def main() -> int:
    args = parse_args()
    runtime = resolve_runtime(args)
    client = build_openai_client(runtime)

    summary: dict[str, Any] = {
        "script": "llm_connectivity_probe.py",
        "backend_root": str(runtime.backend_root),
        "env_file": str(runtime.env_file) if runtime.env_file else None,
        "runtime": {
            "model": runtime.model,
            "base_url": display_base_url(runtime.base_url),
            "temperature": runtime.temperature,
            "max_completion_tokens": runtime.max_completion_tokens,
            "timeout_s": runtime.timeout_s,
        },
        "repeat": args.repeat,
        "models": None,
        "chat": None,
    }

    if not args.skip_models:
        summary["models"] = benchmark_models(client, args.repeat)
    if not args.skip_chat:
        summary["chat"] = benchmark_chat(
            client,
            repeat=args.repeat,
            model=runtime.model,
            message=args.message,
            temperature=runtime.temperature,
            max_completion_tokens=runtime.max_completion_tokens,
        )

    write_json_output(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
