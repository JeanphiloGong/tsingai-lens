from __future__ import annotations

from types import SimpleNamespace

from domain.pipeline import ModelUsage, TokenUsage
from infra.llm.usage import (
    capture_llm_usage,
    record_llm_completion,
    record_llm_prompt_version,
)


def _completion(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


def test_capture_llm_usage_aggregates_each_provider_response() -> None:
    with capture_llm_usage() as usage:
        record_llm_prompt_version("paper_framing", "paper_framing.v1")
        record_llm_completion(
            _completion(model="model-a", input_tokens=100, output_tokens=20),
            requested_model="configured-model",
        )
        record_llm_completion(
            _completion(model="model-a", input_tokens=80, output_tokens=10),
            requested_model="configured-model",
        )

    assert usage.execution_stats().model_usage == (
        ModelUsage(
            model_name="model-a",
            request_count=2,
            token_usage=TokenUsage(
                input_tokens=180,
                output_tokens=30,
                total_tokens=210,
            ),
        ),
    )
    assert usage.model_name == "model-a"
    assert usage.prompt_versions == {"paper_framing": "paper_framing.v1"}
    assert usage.execution_stats().prompt_versions == {
        "paper_framing": "paper_framing.v1"
    }


def test_capture_llm_usage_counts_response_without_provider_token_details() -> None:
    with capture_llm_usage() as usage:
        record_llm_completion(None, requested_model="model-a")

    assert usage.execution_stats().model_usage == (
        ModelUsage(
            model_name="model-a",
            request_count=1,
            token_usage=None,
            unreported_request_count=1,
        ),
    )


def test_capture_llm_usage_keeps_reported_tokens_when_one_call_is_missing_usage() -> None:
    with capture_llm_usage() as usage:
        record_llm_completion(
            _completion(model="model-a", input_tokens=100, output_tokens=20),
            requested_model="model-a",
        )
        record_llm_completion(None, requested_model="model-a")

    assert usage.execution_stats().model_usage == (
        ModelUsage(
            model_name="model-a",
            request_count=2,
            token_usage=TokenUsage(100, 20, 120),
            unreported_request_count=1,
        ),
    )
    assert usage.execution_stats().token_usage == TokenUsage(100, 20, 120)
    assert usage.execution_stats().unreported_request_count == 1
