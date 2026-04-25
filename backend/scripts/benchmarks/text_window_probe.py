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
    build_schema_anchored_user_prompt,
    coerce_message_text,
    display_base_url,
    ensure_backend_root_on_path,
    extract_json_object,
    load_json_payload,
    resolve_runtime,
    summarize_timings,
    write_json_output,
)


_MODE_CONNECTIVITY = "connectivity"
_MODE_RAW_TEXT = "raw_text"
_MODE_RAW_TEXT_PLUS_VALIDATE = "raw_text_plus_validate"
_MODE_PROVIDER_STRUCTURED_PARSE = "provider_structured_parse"
_BENCHMARK_JSON_GUIDANCE = """
Benchmark-specific JSON compliance rules for this run:
- Use exactly the schema keys and no others. Do not add keys like `keywords`, `notes`, or `warnings`.
- Arrays must be arrays. When empty, use `[]`. Never use `null` for arrays such as `temperatures_c`, `durations`, `methods`, or any top-level list.
- Required nested objects must stay objects. Never use `null` for `method_payload`, `process_context`, `condition_payload`, or `value_payload`.
- Put nullable scalars inside those required objects instead of nulling the whole object.
- `unit` belongs at `measurement_results[*].unit`, never inside `value_payload`.
- `host_material_system` may be `null`, but `process_context` may not be `null`.
- If you are uncertain, return the valid empty-shape object with null scalar leaves and empty arrays.

Valid nested object examples:
```json
{
  "method_payload": {
    "temperatures_c": [],
    "durations": [],
    "atmosphere": null,
    "methods": [],
    "details": null
  },
  "process_context": {
    "temperatures_c": [],
    "durations": [],
    "atmosphere": null
  },
  "condition_payload": {
    "method": null,
    "methods": [],
    "temperatures_c": [],
    "durations": [],
    "atmosphere": null
  },
  "value_payload": {
    "value": null,
    "min": null,
    "max": null,
    "retention_percent": null,
    "direction": null,
    "statement": null
  }
}
```

Valid measurement result example:
```json
{
  "claim_text": "Residual stress was reduced by over 90%.",
  "property_normalized": "residual stress",
  "result_type": "measurement",
  "value_payload": {
    "value": 90,
    "min": null,
    "max": null,
    "retention_percent": null,
    "direction": null,
    "statement": null
  },
  "unit": null,
  "variant_label": null,
  "baseline_label": null,
  "anchors": [
    {
      "quote": "reduce residual stress during LPBF by over 90%",
      "source_type": "text",
      "page": 1
    }
  ],
  "confidence": 0.0
}
```

Invalid counterexamples. Do not copy these shapes:
```json
{
  "keywords": ["Residual stress"],
  "method_facts": [],
  "sample_variants": [],
  "test_conditions": [],
  "baseline_references": [],
  "measurement_results": []
}
```

```json
{
  "method_payload": {
    "temperatures_c": null,
    "durations": null
  },
  "process_context": null,
  "condition_payload": {
    "methods": null
  },
  "value_payload": null
}
```

```json
{
  "value_payload": {
    "value": 120,
    "unit": "°C"
  }
}
```
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark one text-window prompt path under connectivity, raw text, local "
            "validation, and provider-native structured parse modes."
        )
    )
    parser.add_argument(
        "--mode",
        choices=(
            _MODE_CONNECTIVITY,
            _MODE_RAW_TEXT,
            _MODE_RAW_TEXT_PLUS_VALIDATE,
            _MODE_PROVIDER_STRUCTURED_PARSE,
        ),
        default=_MODE_RAW_TEXT_PLUS_VALIDATE,
        help="Benchmark mode.",
    )
    parser.add_argument(
        "--payload-file",
        type=Path,
        help="Optional JSON payload file. Defaults to the built-in sample text window.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of repeated benchmark runs.",
    )
    parser.add_argument(
        "--connectivity-message",
        default="Reply with exactly OK.",
        help="Minimal connectivity message used only when `--mode connectivity` is selected.",
    )
    parser.add_argument(
        "--show-payload",
        action="store_true",
        help="Print the exact payload JSON before running.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the resolved system prompt and user prompt before running.",
    )
    parser.add_argument(
        "--show-response",
        action="store_true",
        help="Print the captured response for each run.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional JSON file path for the final benchmark summary.",
    )
    parser.add_argument(
        "--response-output",
        type=Path,
        help="Optional JSON file path for captured raw and parsed responses.",
    )
    add_runtime_arguments(parser, default_temperature=0.0, include_max_completion_tokens=True)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be greater than 0")
    return args


def load_text_window_components(
    backend_root: Path,
) -> tuple[Any, type[Any]]:
    ensure_backend_root_on_path(backend_root)
    from application.core.semantic_build.llm.prompts import build_text_window_extraction_prompt
    from application.core.semantic_build.llm.schemas import StructuredExtractionBundle

    return build_text_window_extraction_prompt, StructuredExtractionBundle


def bundle_counts(bundle: Any) -> dict[str, int]:
    return {
        "method_facts": len(getattr(bundle, "method_facts", [])),
        "sample_variants": len(getattr(bundle, "sample_variants", [])),
        "test_conditions": len(getattr(bundle, "test_conditions", [])),
        "baseline_references": len(getattr(bundle, "baseline_references", [])),
        "measurement_results": len(getattr(bundle, "measurement_results", [])),
    }


def build_request_kwargs(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_completion_tokens: int | None,
) -> dict[str, Any]:
    request_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if max_completion_tokens is not None:
        request_kwargs["max_completion_tokens"] = max_completion_tokens
    return request_kwargs


def build_benchmark_user_prompt(
    *,
    base_user_prompt: str,
    response_model: type[Any],
) -> tuple[str, str]:
    benchmark_user_prompt = (
        f"{base_user_prompt}\n\n"
        f"{_BENCHMARK_JSON_GUIDANCE}"
    )
    return build_schema_anchored_user_prompt(
        user_prompt=benchmark_user_prompt,
        response_model=response_model,
    )


def run_connectivity_mode(
    client: Any,
    *,
    repeat: int,
    model: str,
    message: str,
    temperature: float,
    max_completion_tokens: int | None,
    show_response: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    timings: list[float] = []
    request_kwargs = build_request_kwargs(
        model=model,
        system_prompt="Reply with exactly OK.",
        user_prompt=message,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens or 8,
    )
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
        run_record = {
            "run": run,
            "elapsed_s": round(elapsed_s, 6),
            "finish_reason": finish_reason,
            "response_chars": len(content),
        }
        runs.append(run_record)
        capture = {
            "run": run,
            "content": content,
        }
        captures.append(capture)
        if show_response:
            print(json.dumps(capture, ensure_ascii=False, indent=2))
    return (
        {
            "mode": _MODE_CONNECTIVITY,
            "runs": runs,
            "timing": summarize_timings(timings),
        },
        captures,
    )


def run_raw_text_mode(
    client: Any,
    *,
    request_kwargs: dict[str, Any],
    response_model: type[Any],
    repeat: int,
    validate_response: bool,
    show_response: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    request_timings: list[float] = []
    validation_timings: list[float] = []
    total_timings: list[float] = []

    for run in range(1, repeat + 1):
        request_started_at = perf_counter()
        response = client.chat.completions.create(**request_kwargs)
        request_elapsed_s = perf_counter() - request_started_at
        request_timings.append(request_elapsed_s)

        choice = response.choices[0] if response.choices else None
        finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
        raw_text = coerce_message_text(choice.message.content if choice is not None else None)
        if not raw_text:
            raise RuntimeError("text-window probe returned empty response content")

        bundle = None
        validation_elapsed_s = 0.0
        if validate_response:
            validation_started_at = perf_counter()
            bundle = response_model.model_validate_json(extract_json_object(raw_text))
            validation_elapsed_s = perf_counter() - validation_started_at
            validation_timings.append(validation_elapsed_s)

        total_elapsed_s = request_elapsed_s + validation_elapsed_s
        total_timings.append(total_elapsed_s)
        run_record: dict[str, Any] = {
            "run": run,
            "request_elapsed_s": round(request_elapsed_s, 6),
            "validation_elapsed_s": round(validation_elapsed_s, 6),
            "total_elapsed_s": round(total_elapsed_s, 6),
            "finish_reason": finish_reason,
            "response_chars": len(raw_text),
        }
        capture: dict[str, Any] = {
            "run": run,
            "raw_text": raw_text,
        }
        if bundle is not None:
            counts = bundle_counts(bundle)
            run_record["counts"] = counts
            capture["parsed"] = bundle.model_dump(mode="json")
        runs.append(run_record)
        captures.append(capture)
        if show_response:
            print(json.dumps(capture, ensure_ascii=False, indent=2))

    summary: dict[str, Any] = {
        "mode": _MODE_RAW_TEXT_PLUS_VALIDATE if validate_response else _MODE_RAW_TEXT,
        "runs": runs,
        "request_timing": summarize_timings(request_timings),
        "total_timing": summarize_timings(total_timings),
    }
    if validate_response:
        summary["validation_timing"] = summarize_timings(validation_timings)
    return summary, captures


def run_provider_structured_parse_mode(
    client: Any,
    *,
    request_kwargs: dict[str, Any],
    response_model: type[Any],
    repeat: int,
    show_response: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    timings: list[float] = []

    for run in range(1, repeat + 1):
        started_at = perf_counter()
        completion = client.beta.chat.completions.parse(
            **request_kwargs,
            response_format=response_model,
        )
        elapsed_s = perf_counter() - started_at
        timings.append(elapsed_s)

        choice = completion.choices[0] if completion.choices else None
        finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
        message = choice.message if choice is not None else None
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            raise RuntimeError("provider structured parse returned no parsed payload")
        raw_text = coerce_message_text(getattr(message, "content", None))
        counts = bundle_counts(parsed)
        run_record = {
            "run": run,
            "elapsed_s": round(elapsed_s, 6),
            "finish_reason": finish_reason,
            "response_chars": len(raw_text),
            "counts": counts,
        }
        capture = {
            "run": run,
            "raw_text": raw_text,
            "parsed": parsed.model_dump(mode="json"),
        }
        runs.append(run_record)
        captures.append(capture)
        if show_response:
            print(json.dumps(capture, ensure_ascii=False, indent=2))

    return (
        {
            "mode": _MODE_PROVIDER_STRUCTURED_PARSE,
            "runs": runs,
            "timing": summarize_timings(timings),
        },
        captures,
    )


def main() -> int:
    args = parse_args()
    runtime = resolve_runtime(args)
    build_text_window_extraction_prompt, structured_extraction_bundle = (
        load_text_window_components(runtime.backend_root)
    )
    payload = load_json_payload(args.payload_file)
    system_prompt, base_user_prompt = build_text_window_extraction_prompt(payload)
    final_user_prompt, schema_json = build_benchmark_user_prompt(
        base_user_prompt=base_user_prompt,
        response_model=structured_extraction_bundle,
    )
    request_kwargs = build_request_kwargs(
        model=runtime.model,
        system_prompt=system_prompt,
        user_prompt=final_user_prompt,
        temperature=runtime.temperature,
        max_completion_tokens=runtime.max_completion_tokens,
    )
    client = build_openai_client(runtime)

    if args.show_payload:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.show_prompt:
        print("SYSTEM_PROMPT:")
        print(system_prompt)
        print("USER_PROMPT:")
        print(final_user_prompt)

    if args.mode == _MODE_CONNECTIVITY:
        result, captures = run_connectivity_mode(
            client,
            repeat=args.repeat,
            model=runtime.model,
            message=args.connectivity_message,
            temperature=runtime.temperature,
            max_completion_tokens=runtime.max_completion_tokens,
            show_response=args.show_response,
        )
    elif args.mode == _MODE_RAW_TEXT:
        result, captures = run_raw_text_mode(
            client,
            request_kwargs=request_kwargs,
            response_model=structured_extraction_bundle,
            repeat=args.repeat,
            validate_response=False,
            show_response=args.show_response,
        )
    elif args.mode == _MODE_RAW_TEXT_PLUS_VALIDATE:
        result, captures = run_raw_text_mode(
            client,
            request_kwargs=request_kwargs,
            response_model=structured_extraction_bundle,
            repeat=args.repeat,
            validate_response=True,
            show_response=args.show_response,
        )
    else:
        result, captures = run_provider_structured_parse_mode(
            client,
            request_kwargs=request_kwargs,
            response_model=structured_extraction_bundle,
            repeat=args.repeat,
            show_response=args.show_response,
        )

    summary: dict[str, Any] = {
        "script": "text_window_probe.py",
        "mode": args.mode,
        "backend_root": str(runtime.backend_root),
        "env_file": str(runtime.env_file) if runtime.env_file else None,
        "runtime": {
            "model": runtime.model,
            "base_url": display_base_url(runtime.base_url),
            "temperature": runtime.temperature,
            "max_completion_tokens": runtime.max_completion_tokens,
            "timeout_s": runtime.timeout_s,
        },
        "payload": {
            "payload_file": str(args.payload_file.expanduser().resolve()) if args.payload_file else None,
            "payload_chars": len(json.dumps(payload, ensure_ascii=False)),
            "text_window_chars": len(str((payload.get("text_window") or {}).get("text") or "")),
        },
        "prompts": {
            "system_prompt_chars": len(system_prompt),
            "base_user_prompt_chars": len(base_user_prompt),
            "final_user_prompt_chars": len(final_user_prompt),
            "schema_chars": len(schema_json),
        },
        "result": result,
        "response_output": str(args.response_output.expanduser().resolve()) if args.response_output else None,
    }

    response_output_payload = {
        "script": "text_window_probe.py",
        "mode": args.mode,
        "captures": captures,
    }
    write_json_output(args.response_output, response_output_payload)
    write_json_output(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
