"""Database-independent execution usage value objects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    @classmethod
    def sum(cls, values: Iterable["TokenUsage | None"]) -> "TokenUsage | None":
        available = tuple(value for value in values if value is not None)
        if not available:
            return None
        return cls(
            input_tokens=sum(value.input_tokens for value in available),
            output_tokens=sum(value.output_tokens for value in available),
            total_tokens=sum(value.total_tokens for value in available),
        )


@dataclass(frozen=True)
class ModelUsage:
    model_name: str
    request_count: int
    token_usage: TokenUsage | None = None
    unreported_request_count: int = 0

    def __post_init__(self) -> None:
        if self.request_count < 0:
            raise ValueError("request_count cannot be negative")
        if not 0 <= self.unreported_request_count <= self.request_count:
            raise ValueError(
                "unreported_request_count must be between zero and request_count"
            )

    @classmethod
    def aggregate(cls, values: Iterable["ModelUsage"]) -> "ModelUsage":
        usages = tuple(values)
        if not usages:
            raise ValueError("cannot aggregate empty model usage")
        model_name = usages[0].model_name
        if any(usage.model_name != model_name for usage in usages):
            raise ValueError("cannot aggregate usage from different models")
        return cls(
            model_name=model_name,
            request_count=sum(usage.request_count for usage in usages),
            token_usage=TokenUsage.sum(usage.token_usage for usage in usages),
            unreported_request_count=sum(
                usage.unreported_request_count for usage in usages
            ),
        )


@dataclass(frozen=True)
class ExecutionStats:
    duration_ms: int | None = None
    model_usage: tuple[ModelUsage, ...] = ()
    prompt_versions: Mapping[str, str] = field(default_factory=dict)

    @property
    def token_usage(self) -> TokenUsage | None:
        return TokenUsage.sum(usage.token_usage for usage in self.model_usage)

    @property
    def unreported_request_count(self) -> int:
        return sum(usage.unreported_request_count for usage in self.model_usage)

    @classmethod
    def aggregate(
        cls,
        values: Iterable["ExecutionStats"],
        *,
        duration_ms: int | None = None,
    ) -> "ExecutionStats":
        stats = tuple(values)
        usage_by_model: dict[str, list[ModelUsage]] = {}
        prompt_versions: dict[str, str] = {}
        for item in stats:
            for model in item.model_usage:
                usage_by_model.setdefault(model.model_name, []).append(model)
            for task_type, version in item.prompt_versions.items():
                previous = prompt_versions.get(task_type)
                if previous is not None and previous != version:
                    raise ValueError(
                        f"multiple prompt versions recorded for {task_type}: "
                        f"{previous}, {version}"
                    )
                prompt_versions[task_type] = version
        return cls(
            duration_ms=duration_ms,
            model_usage=tuple(
                ModelUsage.aggregate(models) for models in usage_by_model.values()
            ),
            prompt_versions=prompt_versions,
        )


__all__ = ["TokenUsage", "ModelUsage", "ExecutionStats"]
