from types import SimpleNamespace
import json

import pytest

from domain.feedback import CorrectionSignal, EvidenceCoverage
from infra.llm.correction_signal_analysis import OpenAICorrectionSignalAnalysisEngine
from tests.unit.feedback.test_correction_signal import _messages


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("relation", ["same_task", "different_task", "uncertain"])
async def test_scope_analysis_receives_original_task_and_preserves_decision(relation):
    messages = _messages(trigger_text="不对，只总结 B。")
    signal = CorrectionSignal.from_message(
        session_id="session-1", anchor_message_id=messages[1].message_id,
        trigger_message_id=messages[2].message_id, content=messages[2].content,
        created_at=messages[2].created_at,
    )

    class Completions:
        async def create(self, **request):
            payload = json.loads(request["messages"][1]["content"])
            assert payload == {
                "original_question": "比较文献 A 和 B。",
                "original_answer": "文献 B 没有预热信息。", "followup": "不对，只总结 B。",
            }
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=json.dumps({
                    "task_relation": relation, "reason": "Task scope assessment.",
                })),
            )])

    engine = OpenAICorrectionSignalAnalysisEngine(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())), model="test-model",
    )
    result = await engine.analyze(
        signal=signal, session=None, anchor=messages[1], trigger=messages[2],
        messages=messages, coverage=EvidenceCoverage(),
    )
    assert result.task_relation == relation
    assert result.suggested_target is None


@pytest.mark.parametrize("content,finish_reason", [
    ('{"task_relation":"yes","reason":"looks similar"}', "stop"),
    ('{"task_relation":"same_task"}', "stop"),
    ('{"task_relation":"same_task","reason":"same comparison"}', "length"),
    ("not json", "stop"),
])
async def test_invalid_scope_decisions_cannot_form_a_pair(content, finish_reason):
    class Completions:
        async def create(self, **request):
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason=finish_reason, message=SimpleNamespace(content=content),
            )])

    messages = _messages()
    engine = OpenAICorrectionSignalAnalysisEngine(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())), model="test-model",
    )
    with pytest.raises(ValueError, match="correction_scope_response_"):
        await engine.analyze(
            signal=None, session=None, anchor=messages[1], trigger=messages[2],
            messages=messages, coverage=EvidenceCoverage(),
        )
