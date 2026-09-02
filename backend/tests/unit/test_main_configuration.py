import pytest

from main import _parse_agent_max_model_steps


def test_agent_step_limit_defaults_to_six_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LENS_AGENT_MAX_MODEL_STEPS", raising=False)

    assert _parse_agent_max_model_steps() == 6


def test_agent_step_limit_accepts_a_valid_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LENS_AGENT_MAX_MODEL_STEPS", "12")

    assert _parse_agent_max_model_steps() == 12


@pytest.mark.parametrize("value", ["not-a-number", "0", "33"])
def test_agent_step_limit_falls_back_for_invalid_or_unsafe_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("LENS_AGENT_MAX_MODEL_STEPS", value)

    assert _parse_agent_max_model_steps() == 6
