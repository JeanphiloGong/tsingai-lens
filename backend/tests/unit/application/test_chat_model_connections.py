"""Run the real session/runner chain with scripted model decisions."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone

import httpx
from openai import AsyncOpenAI
import pytest

from application.chat import AgentContext, CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.context_builder import ChatModelContext
from application.chat import session_service as session_service_module
from application.chat.session_service import ChatSessionService, RepositoryModelCallObserver
from repositories.model_connection_repository import ModelConnectionRepo
from exceptions import ProjectException, ResourceConflictException, TokenInvalidException
from repositories.model_connection_repository import ModelConnectionRecord
from controllers.chat.chat_session_routes import chat_session_router as chat_router
from controllers.model_connection_routes import model_connection_router as model_router
from domain.chat import ChatMessage, ChatSession
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from controllers.dependencies.auth import get_current_user_id
from controllers.exception_router import project_exception_handler, request_validation_handler
from application.source import collection_service
from infra.llm.chat_model import OpenAIChatModel
from infra.llm import chat_model as provider_module
from repositories.chat_repository import ChatRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from repositories.model_connection_repository import ModelConnectionRepository
from infra.persistence.postgres.models.model_connection import ModelConnectionORM
from sqlalchemy import update
from tests.support.postgres import seed_collection
from tests.unit.application.test_chat_session_service import _WriteCapability
from tests.unit.application.test_research_agent_runner import _Model

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def connection(name="lab-a", *, enabled=True):
    now = datetime.now(timezone.utc)
    return ModelConnectionRecord(
        name, name.upper(), f"https://{name}.example.invalid/v1", f"model-{name}",
        f"env:LENS_MODEL_KEY_{name.upper().replace('-', '_')}", enabled,
        65536, 8192, 30.0, now, now,
    )


@pytest.fixture(autouse=True)
async def researchers(postgres_session_factory, monkeypatch):
    monkeypatch.setattr(session_service_module, "collection_service", collection_service)
    monkeypatch.setattr(session_service_module, "ChatRepo", ChatRepository())
    monkeypatch.setattr(session_service_module, "SourceArtifactRepo", SourceArtifactRepository())
    monkeypatch.setattr(session_service_module, "ModelConnectionRepo", ModelConnectionRepository())
    monkeypatch.setattr(provider_module, "OpenAIChatModel", OpenAIChatModel)
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_A", "synthetic-test-value")
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_B", "synthetic-test-value")
    for user in ("alice", "bob"):
        await seed_collection(postgres_session_factory, f"col-{user}", user_id=user)


async def configured(session_factory, *records):
    async with session_factory.begin() as database:
        database.add_all(ModelConnectionORM(**asdict(record)) for record in records)
    return ModelConnectionRepository()




class ClosableModel(_Model):
    closed = False

    async def aclose(self):
        self.closed = True


def service(repository, model_builder=None, chat_repository=None, *capabilities):
    session_service_module.ModelConnectionRepo = repository
    session_service_module.ChatRepo = chat_repository if chat_repository is not None else ChatRepository()
    provider_module.OpenAIChatModel = model_builder or OpenAIChatModel
    return ChatSessionService(
        runner=ResearchAgentRunner(model=_Model(), capabilities=CapabilityRegistry(capabilities)),
    )


async def test_concurrent_researchers_bind_distinct_connections_and_close_clients(postgres_session_factory):
    created = []

    def factory(*, model, **options):
        client = ClosableModel(ModelTurn(content=f"Answer from {model}"))
        created.append((model, client))
        return client

    runtime = service(await configured(postgres_session_factory, connection(), connection("lab-b")), factory)
    sessions = [await runtime.create_session(collection_id=f"col-{user}", user_id=user)
                for user in ("alice", "bob")]
    await asyncio.gather(*[
        runtime.send_message(session.session_id, user, message="Explain evidence uncertainty without tools.",
                                      model_connection_id=choice)
        for session, user, choice in zip(sessions, ("alice", "bob"), ("lab-a", "lab-b"))
    ])
    for session, choice in zip(sessions, ("lab-a", "lab-b")):
        snapshot = await session_service_module.ChatRepo.read_response_snapshot(session.session_id)
        assert snapshot.model_connection_id == choice
    assert {name for name, _ in created} == {"model-lab-a", "model-lab-b"}
    assert all(model.closed for _, model in created)


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_approval_reads_disabled_original_connection_on_another_service(decision, postgres_session_factory):
    repository = await configured(postgres_session_factory, connection())
    created = []
    write = _WriteCapability()

    def factory(*, model, **options):
        turns = ([ModelTurn(tool_calls=(ModelToolCall(
            "create_objective_candidate", {"question": "Compare LPBF evidence"},
        ),))] if not created else [ModelTurn(content="The research decision remains traceable.")])
        client = ClosableModel(*turns)
        created.append((model, client))
        return client

    first = service(repository, factory, None, write)
    session = await first.create_session(collection_id="col-alice", user_id="alice")
    turn = await first.send_message(session.session_id, "alice", message="Save the research objective.",
                                             model_connection_id="lab-a")
    call = turn["pending_approval"]
    assert call is not None and write.executed == []
    async with postgres_session_factory.begin() as database:
        await database.execute(update(ModelConnectionORM).where(
            ModelConnectionORM.connection_id == "lab-a",
        ).values(enabled=False))
        database.add(ModelConnectionORM(**asdict(connection("lab-b"))))
    second = service(repository, factory, session_service_module.ChatRepo, write)
    result = await second.decide_tool_call_for_user(
        session.session_id, call.tool_call_id, "alice",
        arguments_digest=call.arguments_digest, decision=decision,
    )
    await asyncio.gather(*second._title_tasks.values())
    assert result["status"] == "completed"
    # Two research clients and the independent background naming client retain
    # the original binding, including after the connection was disabled.
    assert [model_name for model_name, _ in created] == ["model-lab-a"] * 3
    assert len(write.executed) == (1 if decision == "approved" else 0)
    assert all(model.closed for _, model in created)


async def test_unknown_connection_does_not_append_question_and_sse_keeps_error_code(postgres_session_factory):
    runtime = service(await configured(postgres_session_factory, connection(enabled=False)), lambda **_: pytest.fail("provider called"))
    session = await runtime.create_session(collection_id="col-alice", user_id="alice")
    with pytest.raises(ProjectException) as captured:
        await runtime.send_message(session.session_id, "alice", message="Compare papers", model_connection_id="lab-a")
    assert captured.value.data["code"] == "model_connection_unavailable"
    assert await session_service_module.ChatRepo.read_messages(session.session_id) == ()
    events = await runtime.send_message_stream(session.session_id, "alice", message="Compare papers", model_connection_id="lab-a")
    errors = [event async for event in events]
    assert errors[0]["error"]["code"] == "model_connection_unavailable"


async def test_directory_requires_login_and_never_exposes_private_fields(postgres_session_factory, monkeypatch):
    app = FastAPI()
    app.include_router(model_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    runtime = service(
        await configured(postgres_session_factory, connection(), replace(connection("lab-b"), request_timeout_seconds=0)),
        lambda **_: ClosableModel(ModelTurn(content="Ready.")),
    )
    monkeypatch.setattr(session_service_module, "ChatService", runtime, raising=False)
    logged_in = False

    async def current_user():
        if not logged_in:
            raise TokenInvalidException()
        return "alice"

    app.dependency_overrides[get_current_user_id] = current_user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        anonymous = (await client.get("/api/v1/model-connections")).json()
        assert anonymous["code"] == 200301
        logged_in = True
        response = await client.get("/api/v1/model-connections")
        assert response.json() == {"code": 200, "message": "success", "meta": None, "data": {"items": [
            {"connection_id": "lab-a", "display_name": "LAB-A", "model": "model-lab-a"},
            {"connection_id": "lab-b", "display_name": "LAB-B", "model": "model-lab-b"},
        ]}}
        session = await runtime.create_session(collection_id="col-alice", user_id="alice")
        path = f"/api/v1/chat-sessions/{session.session_id}/messages"
        for unknown in ("missing", "LAB A"):
            response = await client.post(path, json={"message": "Explain uncertainty", "model_connection_id": unknown})
            assert response.status_code == 200
            assert response.json()["code"] == 200204
            assert response.json()["data"]["code"] == "model_connection_unavailable"
        response = await client.post(path, json={"message": "Explain uncertainty", "model_connection_id": "x" * 65})
        assert response.status_code == 200 and response.json()["code"] == 200100
        response = await client.post(path, json={"message": "Explain uncertainty", "model_connection_id": "lab-a"})
        assert response.status_code == 200 and response.json()["data"]["status"] == "completed"


async def test_real_sdk_records_binding_without_recording_key(monkeypatch, postgres_session_factory):
    record = connection()
    token = "synthetic-test-value"
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_A", token)
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "completion-1", "object": "chat.completion", "created": 1, "model": record.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Uncertainty remains."}, "finish_reason": "stop"}],
        })

    def build_client(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))

    monkeypatch.setattr("infra.llm.chat_model.AsyncOpenAI", build_client)
    repository = ChatRepository()
    await repository.add_session(ChatSession.create(
        session_id="s1", user_id="alice", collection_id="col-alice",
        created_at="2026-10-25T00:00:00+00:00",
    ))
    runtime = ChatSessionService(runner=ResearchAgentRunner(
        model=_Model(), capabilities=CapabilityRegistry(()),
    ))
    message = ChatMessage.user(message_id="m1", session_id="s1", content="Explain uncertainty", created_at="2026-10-25T00:00:00+00:00")
    async with runtime._runner_for_connection(record) as runner:
        model = runner.model
        await model.respond(context=ChatModelContext(
            (message,), model_call_session_id="s1", active_user_message_id="m1",
            model_call_observer=RepositoryModelCallObserver(model_connection_id=record.connection_id),
        ), tool_specs=())
    assert model.client.is_closed()
    assert requests[0].headers["authorization"] == f"Bearer {token}"
    saved = (await repository.read_model_calls("s1"))[0]
    assert saved.model_connection_id == "lab-a"
    assert saved.request["reasoning_effort"] == "high"
    assert json.loads(requests[0].content)["reasoning_effort"] == "high"
    assert token not in str(saved) and record.api_key_ref not in str(saved)


@pytest.mark.parametrize("failure", ["cancel", "snapshot"])
async def test_client_closes_if_response_is_cancelled_or_snapshot_save_fails(failure, postgres_session_factory):
    ready = asyncio.Event()

    class Paused(ClosableModel):
        async def respond(self, **kwargs):
            ready.set()
            await asyncio.Event().wait()

    model = Paused()
    runtime = service(await configured(postgres_session_factory, connection()), lambda **_: model)
    session = await runtime.create_session(collection_id="col-alice", user_id="alice")
    if failure == "snapshot":
        async def failed_save(*args):
            raise RuntimeError("snapshot-write-failed")
        session_service_module.ChatRepo.save_response_snapshot = failed_save
        with pytest.raises(RuntimeError, match="snapshot-write-failed"):
            await runtime.send_message(session.session_id, "alice", message="Explain uncertainty", model_connection_id="lab-a")
    else:
        task = asyncio.create_task(runtime.send_message(session.session_id, "alice", message="Explain uncertainty", model_connection_id="lab-a"))
        await asyncio.wait_for(ready.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert model.closed


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_missing_key_keeps_a_saved_decision_visible_and_retryable(decision, monkeypatch, postgres_session_factory):
    write = _WriteCapability()
    first_model = ClosableModel(ModelTurn(tool_calls=(ModelToolCall(
        "create_objective_candidate", {"question": "Compare LPBF evidence"},
    ),)))
    repository = await configured(postgres_session_factory, connection())
    runtime = service(repository, lambda **_: first_model, None, write)
    session = await runtime.create_session(collection_id="col-alice", user_id="alice")
    turn = await runtime.send_message(session.session_id, "alice", message="Save the objective.",
                                               model_connection_id="lab-a")
    pending = turn["pending_approval"]
    monkeypatch.delenv("LENS_MODEL_KEY_LAB_A", raising=False)
    with pytest.raises(ProjectException) as captured:
        await runtime.decide_tool_call_for_user(session.session_id, pending.tool_call_id, "alice",
            arguments_digest=pending.arguments_digest, decision=decision)
    assert captured.value.data["code"] == "model_connection_key_unavailable"
    saved = await session_service_module.ChatRepo.read_tool_call(pending.tool_call_id)
    trajectory = await runtime.get_trajectory_for_user(session.session_id, "alice")
    assert saved.status.value == decision and write.executed == []
    assert trajectory["pending_approval"] is None
    assert trajectory["retryable_decision"] == saved
    from controllers.chat.chat_session_routes import _trajectory_response
    wire = _trajectory_response(trajectory).model_dump(mode="json")
    assert wire["pending_approval"] is None
    assert wire["retryable_decision"]["status"] == decision
    assert wire["retryable_decision"]["arguments_digest"] == pending.arguments_digest
    assert not trajectory["running"]
    with pytest.raises(ResourceConflictException):
        await runtime.send_message(session.session_id, "alice", message="Continue with another question.",
                                             model_connection_id="lab-a")

    # A different enabled choice must not replace the saved connection on retry.
    async with postgres_session_factory.begin() as database:
        await database.execute(update(ModelConnectionORM).where(
            ModelConnectionORM.connection_id == "lab-a",
        ).values(enabled=False))
        database.add(ModelConnectionORM(**asdict(connection("lab-b"))))
    selected = []
    resumed = ClosableModel(ModelTurn(content="The recorded decision remains traceable."))
    def restored(*, model, **options):
        selected.append(model)
        return resumed
    provider_module.OpenAIChatModel = restored
    monkeypatch.setenv("LENS_MODEL_KEY_LAB_A", "synthetic-restored-key")
    result = await runtime.decide_tool_call_for_user(session.session_id, pending.tool_call_id, "alice",
        arguments_digest=pending.arguments_digest, decision=decision)
    await asyncio.gather(*runtime._title_tasks.values())
    assert result["status"] == "completed" and resumed.closed
    assert selected == ["model-lab-a"] * 2 and len(write.executed) == (1 if decision == "approved" else 0)
    messages = await session_service_module.ChatRepo.read_messages(session.session_id)
    assert sum(item.tool_result is not None and item.tool_result.tool_call_id == pending.tool_call_id
               for item in messages) == 1
    trajectory = await runtime.get_trajectory_for_user(session.session_id, "alice")
    assert trajectory["retryable_decision"] is None
    assert trajectory["response"].status == "completed"
    await runtime.decide_tool_call_for_user(session.session_id, pending.tool_call_id, "alice",
        arguments_digest=pending.arguments_digest, decision=decision)
    assert selected == ["model-lab-a"] * 2 and len(write.executed) == (1 if decision == "approved" else 0)


async def test_omission_uses_the_first_available_model_and_tracks_priority_changes(postgres_session_factory):
    repository = await configured(postgres_session_factory, connection(), connection("lab-b"))
    async with postgres_session_factory.begin() as database:
        await database.execute(update(ModelConnectionORM).where(
            ModelConnectionORM.connection_id == "lab-b",
        ).values(priority=100))
    selected = []

    def build_model(*, model, **options):
        selected.append(model)
        return ClosableModel(ModelTurn(content="Check the Source conditions."))

    runtime = service(repository, build_model)
    app = FastAPI()
    app.include_router(model_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_id] = lambda: "alice"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        directory = (await client.get("/api/v1/model-connections")).json()["data"]["items"]
    assert [item["connection_id"] for item in directory] == ["lab-b", "lab-a"]
    assert all(set(item) == {"connection_id", "display_name", "model"} for item in directory)
    session = await runtime.create_session(collection_id="col-alice", user_id="alice")
    await runtime.set_session_title_for_user(session.session_id, "alice", title="Compare conditions")
    await runtime.send_message(session.session_id, "alice", message="Compare papers")
    snapshot = await session_service_module.ChatRepo.read_response_snapshot(session.session_id)
    assert snapshot.model_connection_id == "lab-b"
    async with postgres_session_factory.begin() as database:
        await database.execute(update(ModelConnectionORM).where(
            ModelConnectionORM.connection_id == "lab-a",
        ).values(priority=200))
    # An existing response keeps its recorded choice after the directory changes.
    assert (await session_service_module.ChatRepo.read_response_snapshot(session.session_id)).model_connection_id == "lab-b"
    await runtime.send_message(session.session_id, "alice", message="Compare another outcome")
    assert (await session_service_module.ChatRepo.read_response_snapshot(session.session_id)).model_connection_id == "lab-a"
    assert selected == ["model-lab-b", "model-lab-a"]
    await runtime.send_message(session.session_id, "alice", message="Use my explicit choice", model_connection_id="lab-b")
    assert (await session_service_module.ChatRepo.read_response_snapshot(session.session_id)).model_connection_id == "lab-b"
    assert selected[-1] == "model-lab-b"


async def test_omission_with_no_enabled_models_does_not_append_a_question(postgres_session_factory):
    runtime = service(await configured(postgres_session_factory, connection(enabled=False)), lambda **_: pytest.fail("provider called"))
    session = await runtime.create_session(collection_id="col-alice", user_id="alice")
    with pytest.raises(ProjectException) as captured:
        await runtime.send_message(session.session_id, "alice", message="Compare papers")
    assert captured.value.data["code"] == "model_connection_default_unavailable"
    assert await session_service_module.ChatRepo.read_messages(session.session_id) == ()


async def test_unbound_old_approval_refuses_to_guess_the_enabled_default(postgres_session_factory):
    write = _WriteCapability()
    model = ClosableModel(ModelTurn(tool_calls=(ModelToolCall(
        "create_objective_candidate", {"question": "Compare LPBF evidence"},
    ),)))
    runtime = service(await configured(postgres_session_factory, connection()), lambda **_: model, None, write)
    session = await runtime.create_session(collection_id="col-alice", user_id="alice")
    result = await runtime.send_message(session.session_id, "alice", message="Save the objective.", model_connection_id="lab-a")
    pending = result["pending_approval"]
    snapshot = await session_service_module.ChatRepo.read_response_snapshot(session.session_id)
    await session_service_module.ChatRepo.save_response_snapshot(session.session_id, replace(snapshot,
        sequence=snapshot.sequence + 1, model_connection_id=None))
    with pytest.raises(ProjectException) as captured:
        await runtime.decide_tool_call_for_user(session.session_id, pending.tool_call_id, "alice",
            arguments_digest=pending.arguments_digest, decision="approved")
    assert captured.value.data["code"] == "model_connection_binding_missing"
    assert write.executed == []

@pytest.mark.parametrize(
    "row_limits, global_values, expected",
    [
        ((None, None, None), {}, (200000, 16384, 8192, 180.0, 180.0)),
        ((32768, 65536, 30.0), {}, (32768, 16384, 8192, 30.0, 30.0)),
        ((None, None, None), {
            "LENS_AGENT_CONTEXT_TOKENS": "98304",
            "LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS": "8192",
            "LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS": "4096",
            "LENS_AGENT_MAX_REQUEST_SECONDS": "90",
            "LLM_REQUEST_TIMEOUT_SECONDS": "40",
        }, (98304, 8192, 4096, 90.0, 40.0)),
        ((32768, 2048, 20.0), {
            "LENS_AGENT_CONTEXT_TOKENS": "98304",
            "LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS": "8192",
            "LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS": "4096",
            "LENS_AGENT_MAX_REQUEST_SECONDS": "90",
            "LLM_REQUEST_TIMEOUT_SECONDS": "40",
        }, (32768, 2048, 2048, 20.0, 20.0)),
        ((196608, 16384, 180.0), {
            "LENS_AGENT_CONTEXT_TOKENS": "98304",
            "LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS": "8192",
            "LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS": "4096",
            "LENS_AGENT_MAX_REQUEST_SECONDS": "90",
            "LLM_REQUEST_TIMEOUT_SECONDS": "40",
        }, (98304, 8192, 4096, 90.0, 90.0)),
    ],
    ids=["built-in-defaults", "effective-budget", "environment-fallback", "connection-tightens", "global-cap"],
)
async def test_connection_limits_fall_back_and_reach_sdk(
    row_limits, global_values, expected, monkeypatch, postgres_session_factory,
):
    from main import _parse_agent_run_limits

    for name in (
        "LENS_AGENT_CONTEXT_TOKENS", "LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS",
        "LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS", "LENS_AGENT_MAX_REQUEST_SECONDS",
        "LLM_REQUEST_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in global_values.items():
        monkeypatch.setenv(name, value)
    record = replace(
        connection(), api_key_ref=None, context_window_tokens=row_limits[0],
        max_output_tokens=row_limits[1], request_timeout_seconds=row_limits[2],
    )
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "limits-1", "object": "chat.completion", "created": 1,
            "model": record.model,
            "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "Uncertainty remains.",
            }, "finish_reason": "stop"}],
        })

    def build_client(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
        ))

    monkeypatch.setattr("infra.llm.chat_model.AsyncOpenAI", build_client)
    runtime = service(
        await configured(postgres_session_factory, record),
    )
    runtime.runner.limits = _parse_agent_run_limits()
    original_limits = runtime.runner.limits
    bound = await ModelConnectionRepo.read_enabled(record.connection_id)
    async with runtime._runner_for_connection(bound) as runner:
        limits = runner.limits
        assert (
            limits.max_context_tokens, limits.max_model_output_tokens,
            limits.max_finalization_output_tokens, limits.max_request_seconds,
        ) == expected[:4]
        message = ChatMessage.user(
            message_id="limits-m1", session_id="limits-s1", content="Explain uncertainty",
            created_at="2026-10-25T00:00:00+00:00",
        )
        result = await runner.run_turn(
            context=AgentContext("limits-s1", "col-alice", "alice"),
            previous_messages=(), user_message=message.content,
        )
        assert result.status.value == "completed"
        model = runner.model
    assert runtime.runner.limits is original_limits
    assert model.client.is_closed()
    assert json.loads(requests[0].content)["max_completion_tokens"] == expected[1]
    assert requests[0].extensions["timeout"]["read"] == expected[4]


@pytest.mark.parametrize("change", [
    {"base_url": "https://name:synthetic@model.example.invalid/v1"},
    {"base_url": "https://model.example.invalid/v1?key=synthetic"},
    {"base_url": "file:///tmp/model"},
    {"base_url": "https://model.example.invalid:bad/v1"},
    {"api_key_ref": "synthetic-inline-key"},
    {"api_key_ref": "env:"},
    {"model": ""},
    {"model": "   "},
    {"request_timeout_seconds": 0},
    {"request_timeout_seconds": float("nan")},
])
async def test_invalid_connection_use_fails_without_creating_client(change, monkeypatch):
    monkeypatch.setattr("infra.llm.chat_model.AsyncOpenAI", lambda **kwargs: pytest.fail("client created"))
    with pytest.raises(ProjectException) as captured:
        runtime = ChatSessionService(runner=ResearchAgentRunner(
            model=_Model(), capabilities=CapabilityRegistry(()),
        ))
        async with runtime._runner_for_connection(replace(replace(connection(), api_key_ref=None), **change)):
            pytest.fail("invalid configuration reached Runner")
    assert captured.value.code == 200205
    assert captured.value.data["code"] == "model_connection_invalid_configuration"


async def test_environment_key_reference_has_no_project_naming_rule(monkeypatch):
    monkeypatch.setenv("LAB_PROVIDER_TOKEN", "synthetic-test-value")
    runtime = ChatSessionService(runner=ResearchAgentRunner(
        model=_Model(), capabilities=CapabilityRegistry(()),
    ))
    async with runtime._runner_for_connection(replace(connection(), api_key_ref="env:LAB_PROVIDER_TOKEN")) as runner:
        assert runner.model.client.api_key == "synthetic-test-value"
    assert runner.model.client.is_closed()


@pytest.mark.parametrize("field", ["context_window_tokens", "max_output_tokens"])
@pytest.mark.parametrize("value", [0, -1])
async def test_nonpositive_token_limit_stops_before_model_request(field, value, postgres_session_factory):
    runtime = service(
        await configured(postgres_session_factory, replace(connection(), **{field: value})),
        lambda **_: pytest.fail("invalid limits created a client"),
    )
    selected = await ModelConnectionRepo.read_enabled("lab-a")
    with pytest.raises(ProjectException) as captured:
        async with runtime._runner_for_connection(selected):
            pytest.fail("invalid limits reached Runner")
    assert captured.value.data["code"] == "model_connection_invalid_configuration"
