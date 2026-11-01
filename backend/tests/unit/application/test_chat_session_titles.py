"""Automatic navigation titles never change research messages or manual names."""

import asyncio

import pytest

from application.chat import ModelResponseError, ModelTurn
from repositories.chat_repository import ChatRepository
from tests.unit.application.test_chat_session_service import _service
from tests.unit.application.test_research_agent_runner import _Model
from tests.support.chat_model_connections import scripted_chat_runner  # noqa: F401

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("scripted_chat_runner")]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def collection(postgres_session_factory):
    from tests.support.postgres import seed_collection

    await seed_collection(postgres_session_factory, "col-1", document_ids=())


class TitleModel(_Model):
    def __init__(self, *turns):
        super().__init__(*turns)
        self.title_inputs = []

    async def generate_title(self, *, question, answer):
        self.title_inputs.append((question, answer))
        return "IN718 工艺与延伸率"


async def test_first_answer_names_the_session_once_and_manual_rename_survives():
    repo = ChatRepository()
    model = TitleModel(
        ModelTurn(content="需要分别核对密度和拉伸条件。"),
        ModelTurn(content="继续比较扫描策略。"),
        ModelTurn(content="后续测量仍需验证。"),
    )
    service = _service(model, repo)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    first = await service.send_message(
        session.session_id, "user-1", message="IN718 怎样兼顾致密度和延伸率？"
    )
    await asyncio.gather(*service._title_tasks.values())
    assert first["status"] == "completed"
    assert model.title_inputs == [
        ("IN718 怎样兼顾致密度和延伸率？", "需要分别核对密度和拉伸条件。")
    ]
    assert (await service.get_session_for_user(session.session_id, "user-1")).title == "IN718 工艺与延伸率"
    assert (await service.list_sessions_for_user(collection_id="col-1", user_id="user-1"))[0].title == "IN718 工艺与延伸率"
    await service.send_message(session.session_id, "user-1", message="继续比较")
    await service.set_session_title_for_user(session.session_id, "user-1", title="我的实验讨论")
    await service.send_message(session.session_id, "user-1", message="记录待测项目")
    assert len(model.title_inputs) == 1
    assert (await service.get_session_for_user(session.session_id, "user-1")).title == "我的实验讨论"
    messages = await repo.read_messages(session.session_id)
    assert len(messages) == 6
    assert all("IN718 工艺与延伸率" != message.content for message in messages)


async def test_manual_rename_while_title_is_generating_wins():
    started, finish = asyncio.Event(), asyncio.Event()

    class PausedTitle(TitleModel):
        async def generate_title(self, **kwargs):
            started.set()
            await finish.wait()
            return await super().generate_title(**kwargs)

    repo = ChatRepository()
    service = _service(PausedTitle(ModelTurn(content="还需检查拉伸条件。")), repo)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    pending = asyncio.create_task(service.send_message(session.session_id, "user-1", message="比较 IN718"))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await service.set_session_title_for_user(session.session_id, "user-1", title="手动实验标题")
    finally:
        finish.set()
        await pending
        await asyncio.gather(*service._title_tasks.values())
    assert (await repo.read_session(session.session_id)).title == "手动实验标题"


async def test_slow_title_does_not_hold_the_response_or_next_turn_and_closes_on_shutdown():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowTitle(TitleModel):
        async def generate_title(self, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    repo = ChatRepository()
    model = SlowTitle(ModelTurn(content="First answer."), ModelTurn(content="Next answer."))
    service = _service(model, repo)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    try:
        first = await asyncio.wait_for(service.send_message(session.session_id, "user-1", message="Compare IN718"), timeout=5)
        await asyncio.wait_for(started.wait(), timeout=5)
        assert first["status"] == "completed"
        assert (await repo.read_response_snapshot(session.session_id)).status == "completed"
        assert not await repo.is_session_running(session.session_id)
        second = await asyncio.wait_for(service.send_message(session.session_id, "user-1", message="Continue"), timeout=5)
        assert second["messages"][-1].content == "Next answer."
        assert len(service._title_tasks) == 1
    finally:
        await service.close()
    assert cancelled.is_set()


async def test_title_failure_preserves_streamed_answer_and_question_fallback():
    class FailedTitle(TitleModel):
        async def generate_title(self, **kwargs):
            raise TimeoutError("title service timed out")

    repo = ChatRepository()
    service = _service(FailedTitle(ModelTurn(content="仍需原文中的拉伸测量。")), repo)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    stream = await service.send_message_stream(session.session_id, "user-1", message="比较 IN718")
    events = [event async for event in stream]
    await asyncio.gather(*service._title_tasks.values())
    turn = next(event["turn"] for event in events if event["type"] == "turn")
    assert turn["status"] == "completed" and turn["error_code"] is None
    assert turn["messages"][-1].content == "仍需原文中的拉伸测量。"
    assert (await repo.read_response_snapshot(session.session_id)).status == "completed"
    assert (await repo.list_sessions(user_id="user-1", collection_id="col-1"))[0].title == "比较 IN718"


async def test_failed_research_is_not_summarized_as_a_successful_topic():
    model = TitleModel(ModelResponseError("Unavailable", reason="model_unavailable", retryable=False))
    service = _service(model, ChatRepository())
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    turn = await service.send_message(session.session_id, "user-1", message="比较 IN718")
    assert turn["status"] == "failed"
    assert model.title_inputs == []


async def test_generated_title_write_cannot_change_another_users_session():
    repo = ChatRepository()
    service = _service(TitleModel(), repo)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    await repo.set_generated_session_title(session_id=session.session_id, user_id="someone-else", title="Forbidden")
    assert (await repo.read_session(session.session_id)).title is None
