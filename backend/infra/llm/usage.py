from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any

from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage


class LLMUsageCollector:
    """Collect provider-reported usage for one pipeline node or analysis run."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._usage_by_model: dict[str, list[TokenUsage | None]] = {}
        self._prompt_versions: dict[str, str] = {}

    def record_completion(self, completion: Any, *, requested_model: str) -> None:
        model_name = str(
            getattr(completion, "model", None) or requested_model
        ).strip()
        if not model_name:
            return
        token_usage = _provider_token_usage(
            getattr(completion, "usage", None) if completion is not None else None
        )
        with self._lock:
            self._usage_by_model.setdefault(model_name, []).append(token_usage)

    def record_prompt_version(self, task_type: str, prompt_version: str) -> None:
        normalized_task = str(task_type or "").strip()
        normalized_version = str(prompt_version or "").strip()
        if not normalized_task or not normalized_version:
            return
        with self._lock:
            previous = self._prompt_versions.get(normalized_task)
            if previous is not None and previous != normalized_version:
                raise ValueError(
                    f"multiple prompt versions recorded for {normalized_task}: "
                    f"{previous}, {normalized_version}"
                )
            self._prompt_versions[normalized_task] = normalized_version

    @property
    def model_name(self) -> str | None:
        with self._lock:
            model_names = tuple(sorted(self._usage_by_model))
        return model_names[0] if len(model_names) == 1 else None

    @property
    def prompt_versions(self) -> dict[str, str]:
        with self._lock:
            return dict(sorted(self._prompt_versions.items()))

    def execution_stats(self, *, duration_ms: int | None = None) -> ExecutionStats:
        with self._lock:
            usage_by_model = {
                model_name: tuple(usages)
                for model_name, usages in self._usage_by_model.items()
            }
        return ExecutionStats(
            duration_ms=duration_ms,
            model_usage=tuple(
                ModelUsage(
                    model_name=model_name,
                    request_count=len(usages),
                    token_usage=TokenUsage.sum(usages),
                    unreported_request_count=sum(
                        token_usage is None for token_usage in usages
                    ),
                )
                for model_name, usages in sorted(usage_by_model.items())
            ),
            prompt_versions=self.prompt_versions,
        )


_ACTIVE_USAGE_COLLECTOR: ContextVar[LLMUsageCollector | None] = ContextVar(
    "active_llm_usage_collector",
    default=None,
)


@contextmanager
def capture_llm_usage() -> Iterator[LLMUsageCollector]:
    collector = LLMUsageCollector()
    token = _ACTIVE_USAGE_COLLECTOR.set(collector)
    try:
        yield collector
    finally:
        _ACTIVE_USAGE_COLLECTOR.reset(token)


def record_llm_completion(completion: Any, *, requested_model: str) -> None:
    collector = _ACTIVE_USAGE_COLLECTOR.get()
    if collector is not None:
        collector.record_completion(completion, requested_model=requested_model)


def record_llm_prompt_version(task_type: str, prompt_version: str) -> None:
    collector = _ACTIVE_USAGE_COLLECTOR.get()
    if collector is not None:
        collector.record_prompt_version(task_type, prompt_version)


def _provider_token_usage(payload: Any) -> TokenUsage | None:
    input_tokens = _usage_value(payload, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(payload, "output_tokens", "completion_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    total_tokens = _usage_value(payload, "total_tokens")
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=(
            total_tokens
            if total_tokens is not None
            else input_tokens + output_tokens
        ),
    )


def _usage_value(payload: Any, *names: str) -> int | None:
    for name in names:
        value = (
            payload.get(name)
            if isinstance(payload, Mapping)
            else getattr(payload, name, None)
        )
        if value is not None:
            return int(value)
    return None


__all__ = [
    "LLMUsageCollector",
    "capture_llm_usage",
    "record_llm_completion",
    "record_llm_prompt_version",
]
