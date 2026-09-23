from __future__ import annotations

import pytest

from application.evaluation.chat_correction_candidate_service import (
    ChatCorrectionCandidateService,
)
from application.core.objectives.llm.structured_response import StructuredOutputSaturatedError
from tests.support.chat_correction_candidate import MemoryChatCorrectionCandidateRepository
from tests.unit.application.test_chat_correction_review import _setup


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeResponseClient:
    model = "candidate-test-model"

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []
        self.trace = {
            "raw_output": "{\"outcome\":\"candidate\"}",
            "attempts": [{"finish_reason": "stop"}],
        }

    def estimate_prompt_tokens(self, **kwargs):
        return 42

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response

    def complete_json(self, **kwargs):  # pragma: no cover - bound into complete()
        return self.response, self.trace["raw_output"]

    def peek_last_trace(self):
        return self.trace


async def _service(response=None, error=None):
    _chat, chat_service, review_service, _reviews, _case = await _setup()
    client = _FakeResponseClient(response=response, error=error)
    repository = MemoryChatCorrectionCandidateRepository()
    service = ChatCorrectionCandidateService(
        chat_session_service=chat_service,
        repository=repository,
        review_service=review_service,
        response_client=client,
    )
    return service, repository, client, chat_service


async def test_valid_proposal_is_needs_review_and_selection_enters_p2_p3() -> None:
    service, repository, client, chat_service = await _service(
        {
            "outcome": "candidate",
            "original_message_id": "msg-original",
            "challenge_message_id": "msg-feedback",
            "corrected_message_id": "msg-corrected",
            "rationale": "The challenge is followed by a source-backed correction.",
        }
    )

    candidate = await service.propose_for_user(
        "chat-review", "researcher", challenge_message_id="msg-feedback"
    )

    assert candidate.status == "needs_review"
    assert candidate.raw_response
    assert candidate.finish_reason == "stop"
    assert candidate.model_call_ids == ("call-original", "call-corrected")
    assert client.calls[0]["user_prompt"]
    assert '"request":' not in client.calls[0]["user_prompt"]

    selected = await service.select_for_user(
        "chat-review", candidate.candidate_id, "researcher"
    )
    assert selected.selected_case_id
    assert selected.selected_sample_id
    assert await chat_service.repository.read_correction_cases("chat-review")
    assert await repository.read_candidate_for_user(
        "chat-review", candidate.candidate_id, "researcher"
    ) == selected


@pytest.mark.parametrize(
    ("response", "status"),
    [
        ({"outcome": "none", "rationale": "ordinary follow-up"}, "no_candidate"),
        ({"outcome": "ambiguous", "rationale": "two possible answers"}, "ambiguous"),
    ],
)
async def test_provider_abstentions_are_persisted_separately(response, status) -> None:
    service, _repository, _client, _chat_service = await _service(response)

    candidate = await service.propose_for_user(
        "chat-review", "researcher", challenge_message_id="msg-feedback"
    )

    assert candidate.status == status
    assert candidate.error_code is None


async def test_fake_ids_are_invalid_and_cannot_be_selected() -> None:
    service, _repository, _client, _chat_service = await _service(
        {
            "outcome": "candidate",
            "original_message_id": "not-a-message",
            "challenge_message_id": "msg-feedback",
            "corrected_message_id": "msg-corrected",
        }
    )

    candidate = await service.propose_for_user(
        "chat-review", "researcher", challenge_message_id="msg-feedback"
    )

    assert candidate.status == "invalid_proposal"
    with pytest.raises(ValueError, match="needs_review"):
        await service.select_for_user("chat-review", candidate.candidate_id, "researcher")


async def test_truncation_is_invalid_and_provider_failure_is_not_no_candidate() -> None:
    service, _repository, client, _chat_service = await _service(
        error=StructuredOutputSaturatedError("limit")
    )
    client.trace = {
        "raw_output": '{"outcome":"candidate"}',
        "attempts": [{"finish_reason": "length"}],
    }
    truncated = await service.propose_for_user(
        "chat-review", "researcher", challenge_message_id="msg-feedback"
    )
    assert truncated.status == "invalid_proposal"
    assert truncated.error_code == "candidate_output_truncated"

    service, _repository, _client, _chat_service = await _service(
        error=TimeoutError("provider timed out")
    )
    failed = await service.propose_for_user(
        "chat-review", "researcher", challenge_message_id="msg-feedback"
    )
    assert failed.status == "provider_failed"
    assert failed.status != "no_candidate"


async def test_selection_is_owner_scoped() -> None:
    service, _repository, _client, _chat_service = await _service(
        {
            "outcome": "candidate",
            "original_message_id": "msg-original",
            "challenge_message_id": "msg-feedback",
            "corrected_message_id": "msg-corrected",
        }
    )
    candidate = await service.propose_for_user(
        "chat-review", "researcher", challenge_message_id="msg-feedback"
    )
    with pytest.raises(FileNotFoundError):
        await service.select_for_user("chat-review", candidate.candidate_id, "other-user")
