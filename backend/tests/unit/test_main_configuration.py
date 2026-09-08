import pytest

from application.chat import AgentRunLimits
from main import _parse_agent_run_limits


def test_agent_limits_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert _parse_agent_run_limits() == AgentRunLimits()


def test_agent_limits_accept_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LENS_AGENT_MAX_TOOL_CALLS", "12")
    monkeypatch.setenv("LENS_AGENT_MAX_TURN_SECONDS", "12.5")
    assert _parse_agent_run_limits().max_tool_calls == 12
    assert _parse_agent_run_limits().max_elapsed_seconds == 12.5


ENV_NAMES = (
    "LENS_AGENT_MAX_TURN_SECONDS", "LENS_AGENT_MAX_TOOL_CALLS",
    "LENS_AGENT_MAX_MODEL_TOKENS", "LENS_AGENT_NO_PROGRESS_LIMIT",
    "LENS_AGENT_EMERGENCY_MAX_CYCLES", "LENS_AGENT_MAX_PARALLEL_READS",
)


@pytest.mark.parametrize("value", ["not-a-number", "0", "-1", "nan", "inf"])
def test_agent_limits_fall_back_for_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    for name in ENV_NAMES:
        monkeypatch.setenv(name, value)
    assert _parse_agent_run_limits() == AgentRunLimits()
