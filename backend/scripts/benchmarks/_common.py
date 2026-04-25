from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

from dotenv import dotenv_values
from openai import OpenAI
from pydantic import BaseModel


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_S = 180.0
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


DEFAULT_TEXT_WINDOW_PAYLOAD: dict[str, Any] = {
    "document_profile": {
        "doc_type": "experimental",
        "protocol_extractable": "yes",
    },
    "document_title": (
        "9a72157535fe48449b93c7b989764f12_Residual stress analysis of in situ surface "
        "layer heating effects on laser powder bed fusion of 316L stainless steel.pdf"
    ),
    "source_filename": (
        "Residual stress analysis of in situ surface layer heating effects on laser powder "
        "bed fusion of 316L stainless steel.pdf"
    ),
    "text_window": {
        "heading": "1. Introduction",
        "heading_path": "1. Introduction",
        "page": 1,
        "text": (
            "Fabricating  parts  using  laser  powder  bed  fusion  (LPBF)  is  of  growing  "
            "interest  to  many  fields,  ranging  from medical to aerospace, but this process "
            "is often plagued with residual stresses that can reach magnitudes as high as the "
            "yield strength of the material. Previous work has demonstrated the ability to "
            "reduce residual stress during LPBF by over 90% using an in situ annealing method "
            "that makes use of large area, shaped light illumination from a set of laser "
            "diodes. In this work, an in-depth analysis of the effectiveness of this in situ "
            "residual stress reduction technique is presented. A custom LPBF system was used "
            "to fabricate 316L stainless steel parts, and the stresses of these  parts  were  "
            "analyzed  using  the  contour  method  and  neutron  diffraction  on  various  "
            "planes  within  the samples. These spatial measurements revealed stress reductions "
            "near the edges and base of the samples in each of the three measured orthogonal "
            "stress directions, in addition to an overall reduction in stress owing to in situ "
            "application of laser diode heating. The experimental results were found to be in "
            "excellent agreement with numerical thermomechanical simulations that captured the "
            "effects of various processing parameters. Furthermore, in cases where the annealing "
            "was only performed once every 5 layers, the residual stress was similarly reduced, "
            "which indicates that further optimization might be achieved to limit additional "
            "processing time during the builds while still relieving equivalent amounts of stress."
        ),
    },
}


@dataclass(frozen=True)
class ResolvedRuntime:
    backend_root: Path
    env_file: Path | None
    model: str
    base_url: str | None
    api_key: str
    temperature: float
    max_completion_tokens: int | None
    timeout_s: float


def add_runtime_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_temperature: bool = True,
    default_temperature: float = 0.0,
    default_timeout_s: float = DEFAULT_TIMEOUT_S,
    include_max_completion_tokens: bool = True,
    default_max_completion_tokens: int | None = None,
) -> None:
    parser.add_argument(
        "--backend-root",
        type=Path,
        help="Optional backend root override. Defaults to the repo-local backend root.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help=(
            "Optional env-file override. When omitted, the script will load "
            "<backend-root>/.env only if it exists."
        ),
    )
    parser.add_argument(
        "--base-url",
        help="Optional LLM base URL override. Precedence is CLI > env > env-file.",
    )
    parser.add_argument(
        "--model",
        help="Optional LLM model override. Precedence is CLI > env > env-file.",
    )
    parser.add_argument(
        "--api-key",
        help="Optional LLM API key override. Precedence is CLI > env > env-file.",
    )
    if include_temperature:
        parser.add_argument(
            "--temperature",
            type=float,
            default=default_temperature,
            help=f"Sampling temperature. Defaults to {default_temperature}.",
        )
    if include_max_completion_tokens:
        parser.add_argument(
            "--max-completion-tokens",
            type=int,
            default=default_max_completion_tokens,
            help=(
                "Optional max completion tokens override. Leave unset to use the provider default."
            ),
        )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=default_timeout_s,
        help=f"HTTP timeout in seconds. Defaults to {default_timeout_s}.",
    )


def resolve_runtime(
    args: argparse.Namespace,
    *,
    allow_placeholder_api_key: bool = True,
    default_model: str = DEFAULT_MODEL,
) -> ResolvedRuntime:
    backend_root = _resolve_backend_root(getattr(args, "backend_root", None))
    env_file = _resolve_env_file(
        backend_root=backend_root,
        env_file=getattr(args, "env_file", None),
    )
    env_values = _read_env_file(env_file)

    model = _pick_first_non_empty(
        getattr(args, "model", None),
        os.getenv("LLM_MODEL"),
        env_values.get("LLM_MODEL"),
        default_model,
    )
    base_url = _pick_first_non_empty(
        getattr(args, "base_url", None),
        os.getenv("LLM_BASE_URL"),
        env_values.get("LLM_BASE_URL"),
        None,
    )
    if base_url:
        base_url = base_url.rstrip("/")

    api_key = _pick_first_non_empty(
        getattr(args, "api_key", None),
        os.getenv("LLM_API_KEY"),
        env_values.get("LLM_API_KEY"),
        None,
    )
    if not api_key and allow_placeholder_api_key and base_url:
        api_key = "not-needed"
    if not api_key:
        raise SystemExit(
            "LLM_API_KEY is unresolved. Pass --api-key, export LLM_API_KEY, or use "
            "--env-file. A placeholder key is applied only when --base-url/LLM_BASE_URL is set."
        )

    temperature = float(getattr(args, "temperature", 0.0))
    max_completion_tokens = getattr(args, "max_completion_tokens", None)
    if max_completion_tokens is not None and int(max_completion_tokens) <= 0:
        raise SystemExit("--max-completion-tokens must be greater than 0")
    timeout_s = float(getattr(args, "timeout_s", DEFAULT_TIMEOUT_S))
    if timeout_s <= 0:
        raise SystemExit("--timeout-s must be greater than 0")

    return ResolvedRuntime(
        backend_root=backend_root,
        env_file=env_file,
        model=str(model or default_model).strip() or default_model,
        base_url=base_url,
        api_key=str(api_key).strip(),
        temperature=temperature,
        max_completion_tokens=(
            int(max_completion_tokens) if max_completion_tokens is not None else None
        ),
        timeout_s=timeout_s,
    )


def ensure_backend_root_on_path(backend_root: Path) -> None:
    backend_root_text = str(backend_root)
    if backend_root_text not in sys.path:
        sys.path.insert(0, backend_root_text)


def build_openai_client(runtime: ResolvedRuntime) -> OpenAI:
    return OpenAI(
        api_key=runtime.api_key,
        base_url=runtime.base_url or None,
        timeout=runtime.timeout_s,
    )


def load_json_payload(payload_file: Path | None) -> dict[str, Any]:
    if payload_file is None:
        return json.loads(json.dumps(DEFAULT_TEXT_WINDOW_PAYLOAD))
    resolved = payload_file.expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def build_schema_anchored_user_prompt(
    *,
    user_prompt: str,
    response_model: type[BaseModel],
) -> tuple[str, str]:
    schema_json = json.dumps(
        response_model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    final_user_prompt = (
        f"{user_prompt}\n\n"
        "Return exactly one JSON object that matches this schema. "
        "Do not include markdown fences or commentary.\n"
        f"JSON schema:\n{schema_json}"
    )
    return final_user_prompt, schema_json


def coerce_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return str(content or "").strip()

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            text = item
        else:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def extract_json_object(response_text: str) -> str:
    text = str(response_text or "").strip()
    if not text:
        raise RuntimeError("response returned empty JSON text")

    fenced_match = _JSON_FENCE_PATTERN.search(text)
    if fenced_match is not None:
        return fenced_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("response returned no JSON object")
    return text[start : end + 1]


def stable_json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(value: Any) -> str:
    return hashlib.sha256(stable_json_dumps(value).encode("utf-8")).hexdigest()


def summarize_timings(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {
            "count": 0,
            "total_s": 0.0,
            "min_s": 0.0,
            "p50_s": 0.0,
            "p95_s": 0.0,
            "max_s": 0.0,
            "avg_s": 0.0,
        }

    return {
        "count": len(samples),
        "total_s": _round(sum(samples)),
        "min_s": _round(min(samples)),
        "p50_s": _round(_percentile(samples, 0.50)),
        "p95_s": _round(_percentile(samples, 0.95)),
        "max_s": _round(max(samples)),
        "avg_s": _round(sum(samples) / len(samples)),
    }


def write_json_output(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def display_base_url(base_url: str | None) -> str:
    return base_url or "<openai-default>"


def _resolve_backend_root(backend_root: Path | None) -> Path:
    if backend_root is None:
        return DEFAULT_BACKEND_ROOT
    return backend_root.expanduser().resolve()


def _resolve_env_file(*, backend_root: Path, env_file: Path | None) -> Path | None:
    if env_file is not None:
        resolved = env_file.expanduser().resolve()
        if not resolved.is_file():
            raise SystemExit(f"env file not found: {resolved}")
        return resolved

    default_env_file = backend_root / ".env"
    if default_env_file.is_file():
        return default_env_file
    return None


def _read_env_file(env_file: Path | None) -> dict[str, str]:
    if env_file is None:
        return {}
    return {
        str(key): str(value)
        for key, value in dotenv_values(env_file).items()
        if key and value is not None
    }


def _pick_first_non_empty(*candidates: Any) -> str | None:
    for value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _percentile(samples: list[float], percentile: float) -> float:
    if len(samples) == 1:
        return samples[0]
    ordered = sorted(samples)
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    lower_value = ordered[lower]
    upper_value = ordered[upper]
    return lower_value + (upper_value - lower_value) * (position - lower)


def _round(value: float) -> float:
    return round(float(value), 6)
