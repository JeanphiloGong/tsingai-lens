"""#399 transport/persistence checks; scripted answers are not scientific evidence."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from application.chat import (
    CapabilityRegistry,
    ModelTurn,
    ModelToolCall,
    ModelResponseError,
    ResearchAgentRunner,
)
from application.chat.capabilities.document_sources import ReadSourceCapability
from application.chat.session_service import (
    ChatSessionService,
    ChatSessionNotFoundError,
)
from domain.source import SourceDocument, SourceBlock
from repositories.chat_repository import ChatRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from application.chat import session_service
from tests.support.postgres import seed_collection
from tests.unit.application.test_research_agent_runner import _Model
from tests.support.chat_model_connections import scripted_chat_runner

FIXTURE = Path(__file__).parents[1] / "fixtures/chat/inconel718_four_turns.json"
TURNS = json.loads(FIXTURE.read_text())["turns"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_all_48_energy_descriptors_and_rotation_pairs():
    rows = {}
    for line in TURNS[2].splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not re.fullmatch(r"[AB]\d{2}", cells[0]):
            continue
        key = cells[0]
        assert key not in rows
        values = tuple(Decimal(cell) for cell in cells[1:])
        p, v, h, t, angle, el, es, ev = values
        calculated = (p / v, p / (v * h / 1000), p / (v * h * t / 1000000))
        for given, exact in zip((el, es, ev), calculated):
            tolerance = Decimal(5).scaleb(given.as_tuple().exponent - 1)
            assert abs(given - exact) <= tolerance, (key, given, exact)
        rows[key] = values
    assert set(rows) == {f"{prefix}{i:02}" for prefix in "AB" for i in range(1, 25)}
    for i in range(1, 25):
        a, b = rows[f"A{i:02}"], rows[f"B{i:02}"]
        assert a[:4] == b[:4] and a[5:] == b[5:]
        assert a[4] == 90 and b[4] == 67


@pytest.mark.anyio
@pytest.mark.parametrize("interrupt", [False, True])
async def test_four_turns_keep_original_table_sources_and_user_scope(
    postgres_session_factory, collection_service, object_store, monkeypatch,
    scripted_chat_runner, interrupt
):
    await seed_collection(
        postgres_session_factory, "col-399", document_ids=("doc-399",)
    )
    sources = SourceArtifactRepository()
    await sources.replace_document(
        "col-399",
        SourceDocument(
            document_id="doc-399",
            document_order=0,
            title="Synthetic conditions fixture",
            text="",
            blocks=(
                SourceBlock(
                    block_id="methods",
                    document_id="doc-399",
                    block_type="paragraph",
                    text="Synthetic fixture only: as-built; tensile orientation unknown.",
                    block_order=0,
                    page=1,
                    heading_path="Methods",
                ),
            ),
        ),
    )
    model = _Model(
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name="read_source",
                    arguments={
                        "document_id": "doc-399",
                        "source_kind": "text_window",
                        "source_ref": "methods",
                    },
                ),
            )
        ),
        ModelTurn(content="Source doc-399/methods retained; orientation unknown."),
        ModelTurn(
            content="As-built; orientation unknown. No directly comparable measurement."
        ),
        ModelTurn(content="48 candidates received; no validated elongation ranking."),
        ModelTurn(content="A–H: evidence insufficient; no invented elongation."),
    )
    repository = ChatRepository()
    monkeypatch.setattr(session_service, "ChatRepo", repository)
    monkeypatch.setattr(session_service, "SourceArtifactRepo", sources)
    service = ChatSessionService(
        runner=ResearchAgentRunner(
            model=model, capabilities=CapabilityRegistry((ReadSourceCapability(),))
        )
    )
    session = await service.create_session(collection_id="col-399", user_id="user-1")
    await repository.set_permission(
        session.session_id,
        "user-1",
        mode="read_only",
        actions=[],
        expires_at=None,
        expected_revision=0,
    )
    for index, prompt in enumerate(TURNS):
        if interrupt and index == 3:
            model.turns.appendleft(
                ModelResponseError(
                    "synthetic unavailable",
                    reason="provider_unavailable",
                    retryable=False,
                )
            )
            failed = await service.send_message(
                session.session_id, "user-1", message="Continue the decision card"
            )
            assert failed["status"] != "completed"
        response = await service.send_message(
            session.session_id, "user-1", message=prompt
        )
        assert response["status"] == "completed", (index + 1, response)
    last_context = model.contexts[-1]
    assert any(m.content == TURNS[2] for m in last_context)
    persisted = await service.list_messages_for_user(session.session_id, "user-1")
    for prompt in TURNS:
        assert any(m.content == prompt for m in persisted)
    source_results = [
        m.tool_result
        for m in persisted
        if m.tool_result and m.tool_result.status == "succeeded"
    ]
    assert any(
        "orientation unknown" in json.dumps(r.data) and "methods" in json.dumps(r.data)
        for r in source_results
    )
    with pytest.raises(ChatSessionNotFoundError):
        await service.get_session_for_user(session.session_id, "user-2")


def test_original_four_turn_inputs_fit_without_numeric_loss():
    from application.chat import ChatContextBuilder
    from domain.chat import ChatMessage

    messages = tuple(
        ChatMessage.user(
            message_id=f"u{i}",
            session_id="chat-399",
            content=prompt,
            created_at="2026-10-29T00:00:00+00:00",
        )
        for i, prompt in enumerate(TURNS)
    )
    context = ChatContextBuilder().for_model(
        messages, active_user_message_id="u3", max_input_tokens=20000
    )
    assert [message.content for message in context.messages] == [
        prompt for prompt in TURNS
    ]
