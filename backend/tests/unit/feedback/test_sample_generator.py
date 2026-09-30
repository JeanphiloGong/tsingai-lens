from types import SimpleNamespace
import json

import httpx
import pytest
from openai import AsyncOpenAI

from infra.llm.feedback_sample_generator import OpenAIFeedbackSampleGenerator


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_provider_receives_readable_evidence_and_returns_generated_content():
    async def respond(request):
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        assert payload["context"] == [{"document_title": "B", "text": "Preheated at 200 C."}]
        assert "source_ref" not in json.dumps(payload)
        assert payload["review_note"] == "Preserve the temperature."
        return httpx.Response(200, json={
            "id": "completion-test", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"target":"B was preheated at 200 C.","missing_reasons":[]}'}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        async with AsyncOpenAI(api_key="test-only", base_url="http://model.test/v1", http_client=http) as client:
            value = await OpenAIFeedbackSampleGenerator(client=client, model="test-model").generate(
                task_type="sft", question="What was the preheating?",
                context=({"document_title": "B", "text": "Preheated at 200 C."},),
                snapshot={"answer": "No preheating", "source_ref": "private-source"},
                construction_spec={"language": "en"}, review_note="Preserve the temperature.",
            )
    assert value["target"] == "B was preheated at 200 C."


async def test_generated_content_drops_internal_references_even_when_provider_copies_them():
    class Completions:
        async def create(self, **request):
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{ "target": "依据 blk_doc_abc_1，结果见 (Source：`tbl_doc_abc_2`)", "missing_reasons": [] }'),
            )])

    value = await OpenAIFeedbackSampleGenerator(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())), model="test-model"
    ).generate(
        task_type="sft", question="问题", context=({"document_title": "B", "text": "原文"},),
        snapshot={}, construction_spec={}
    )
    assert "blk_doc_" not in value["target"]
    assert "tbl_doc_" not in value["target"]


@pytest.mark.parametrize("content,finish_reason", [("not JSON", "stop"), ('{"target":"unfinished"}', "length")])
async def test_invalid_or_truncated_generation_is_a_technical_failure(content, finish_reason):
    class Completions:
        async def create(self, **request):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason,
                message=SimpleNamespace(content=content))])

    generator = OpenAIFeedbackSampleGenerator(
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())), model="test-model")
    with pytest.raises(ValueError, match="sample_generation_"):
        await generator.generate(task_type="evaluation", question="Question",
            context=({"document_title": "B", "text": "Source text"},), snapshot={}, construction_spec={})
