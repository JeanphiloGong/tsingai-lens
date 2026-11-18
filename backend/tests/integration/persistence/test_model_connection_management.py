"""Actual HTTP, PostgreSQL transactions and a local OpenAI transport."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import event, select, text
from openai import AsyncOpenAI
from application import model_connection_service as service
from controllers.dependencies.auth import get_current_user_id
from exceptions import ProjectException
from infra.identity.client import IdentityUnavailableError, SessionNotFoundError
from infra.llm.model_credentials import decrypt_api_key
from infra.persistence.postgres.models.model_connection import ModelConnectionAuditORM
from main import create_app
from repositories.model_connection_repository import ModelConnectionRepo

pytestmark = pytest.mark.anyio


class LocalIdentity:
    async def resolve_session(self, token):
        if token == "offline":
            raise IdentityUnavailableError()
        if token not in {"manager", "reader", "session_revoked", "check_offline"}:
            raise SessionNotFoundError()
        return {"user_id": token, "display_name": "Model operator"}

    async def check(self, token, permission_code):
        assert permission_code == "models.manage"
        if token == "session_revoked":
            raise SessionNotFoundError()
        if token == "check_offline":
            raise IdentityUnavailableError()
        return token == "manager"


@pytest.fixture
async def management(postgres_session_factory, monkeypatch):
    monkeypatch.setattr("infra.identity.client.Client", LocalIdentity(), raising=False)
    monkeypatch.setenv("BROWSER_ORIGIN", "http://testserver")
    app = create_app()
    async def user(): return "reader"
    app.dependency_overrides[get_current_user_id] = user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        headers={"Cookie":"lens_session=manager","Origin":"http://testserver"}) as client:
        yield client, postgres_session_factory


async def create(client, **overrides):
    body={"display_name":"Laboratory", "base_url":"http://127.0.0.1:9999/v1", "model":"local-chat", "api_key":"synthetic-initial"}
    response=await client.post("/api/v1/admin/model-connections",json={**body,**overrides})
    assert response.json()["code"] == 200,response.text
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-initial" not in response.text
    return response.json()["data"]


async def test_permissions_origin_and_secret_validation_precede_effects(management, monkeypatch):
    client,factory=management
    for token, status, reason in (
        ("", 401, "authentication_required"),
        ("reader", 403, "permission_denied"),
        ("offline", 503, "identity_unavailable"),
        ("session_revoked", 401, "authentication_required"),
        ("check_offline", 503, "identity_unavailable"),
    ):
        response=await client.post("/api/v1/admin/model-connections",json={"api_key":"synthetic-secret"},headers={"Cookie":"lens_session="+token})
        assert response.status_code == status
        assert response.json()["data"]["code"] == reason
        assert "synthetic-secret" not in response.text
        assert response.headers["cache-control"] == "no-store"
    denied=await client.post("/api/v1/admin/model-connections",json={},headers={"Origin":"http://other-origin"})
    assert denied.status_code == 403
    invalid=await client.post("/api/v1/admin/model-connections",json={"api_key":"synthetic-secret","unexpected":"synthetic-secret"})
    assert invalid.json()["data"]["code"] == "invalid_request"
    assert "synthetic-secret" not in invalid.text
    oversized=await client.post("/api/v1/admin/model-connections",content=b"x"*16385)
    assert oversized.json()["code"] == 200100
    assert oversized.headers["cache-control"] == "no-store"

    async def chunks():
        yield b"x" * 8192
        yield b"y" * 8193

    streamed = await client.post("/api/v1/admin/model-connections", content=chunks())
    assert streamed.json()["data"]["code"] == "invalid_request"
    malformed = await client.post(
        "/api/v1/admin/model-connections",
        content=b'{"api_key":"synthetic-secret",}',
        headers={"Content-Type": "application/json"},
    )
    assert malformed.json()["data"]["code"] == "invalid_request"
    assert "synthetic-secret" not in malformed.text
    async with factory() as database:
        assert (await database.execute(text("SELECT count(*) FROM model_connection_audit"))).scalar_one() == 0


async def test_combined_save_key_states_and_public_directory(management):
    client,factory=management
    saved=await create(client)
    path="/api/v1/admin/model-connections/"+saved["connection_id"]
    assert saved["enabled"] is False and saved["version"] == 1
    assert (await client.get("/api/v1/model-connections")).json()["data"]["items"] == []
    response=await client.patch(path,json={"expected_version":1,"enabled":True,"display_name":"Updated","api_key":"synthetic-replacement"})
    updated=response.json()["data"]
    assert updated["version"] == 2 and updated["display_name"] == "Updated"
    stored=await ModelConnectionRepo.read(saved["connection_id"])
    assert decrypt_api_key(bytes(range(32)),stored.connection_id,stored.api_key_ciphertext) == "synthetic-replacement"
    directory=(await client.get("/api/v1/model-connections")).json()["data"]["items"]
    assert set(directory[0]) == {"connection_id","display_name","model"}
    assert "base_url" not in directory[0] and "synthetic" not in response.text
    preserved=await client.patch(path,json={"expected_version":2,"priority":4})
    assert preserved.json()["data"]["version"] == 3
    assert (await ModelConnectionRepo.read(stored.connection_id)).api_key_ciphertext == stored.api_key_ciphertext
    stale=await client.patch(path,json={"expected_version":2,"display_name":"Stale","api_key":"discarded"})
    assert stale.json()["data"]["code"] == "model_connection_version_conflict"
    cleared=await client.patch(path,json={"expected_version":3,"api_key":None})
    assert cleared.json()["data"]["version"] == 4 and cleared.json()["data"]["api_key_configured"] is False
    noop=await client.patch(path,json={"expected_version":4,"api_key":None})
    assert noop.json()["data"]["version"] == 4
    async with factory() as database:
        audits=(await database.scalars(select(ModelConnectionAuditORM).order_by(ModelConnectionAuditORM.version))).all()
        assert [row.version for row in audits] == [1,2,3,4]
        assert audits[0].changes["enabled"] == {"before": None, "after": False}
        assert audits[0].changes["api_key"] == {
            "before": "unconfigured", "after": "configured", "operation": "set",
        }
        assert audits[1].action == "update" and audits[1].changes == {
            "display_name": {"before": "Laboratory", "after": "Updated"},
            "enabled": {"before": False, "after": True},
            "api_key": {"before": "configured", "after": "configured", "operation": "replace"},
        }
        assert audits[2].changes == {"priority": {"before": 0, "after": 4}}
        assert audits[3].changes["api_key"] == {
            "before": "configured", "after": "unconfigured", "operation": "clear",
        }
        assert "synthetic" not in str([row.changes for row in audits])
    page=(await client.get("/api/v1/admin/model-connections?offset=50")).json()["data"]
    assert page["items"] == [] and page["total"] == 1


async def test_audit_query_authorizes_filters_and_pages_successful_writes(management):
    client, factory = management
    endpoint = "/api/v1/admin/model-connection-audit"
    for token, status in (("", 401), ("reader", 403), ("offline", 503)):
        denied = await client.get(endpoint, headers={"Cookie": "lens_session=" + token})
        assert denied.status_code == status
        assert denied.headers["cache-control"] == "no-store"
    first = await create(client)
    second = await create(client, display_name="Second model", api_key=None)
    async with factory.begin() as database:
        await database.execute(text("UPDATE model_connection_audit SET created_at = '2026-11-14T08:00:00Z'"))

    response = await client.get(endpoint, params={"limit": 1})
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic" not in response.text and "api_key_ciphertext" not in response.text
    page = response.json()["data"]
    assert (page["total"], page["limit"], page["offset"]) == (2, 1, 0)
    assert page["items"][0]["connection_id"] == second["connection_id"]
    assert page["items"][0]["actor_display_name"] == "Model operator"
    assert "api_key" not in page["items"][0]["changes"]

    filtered = (await client.get(endpoint, params={"connection_id": first["connection_id"]})).json()["data"]
    assert filtered["total"] == 1 and filtered["items"][0]["connection_id"] == first["connection_id"]
    for offset in (2, 2**63):
        past_end = (await client.get(endpoint, params={"offset": offset})).json()["data"]
        assert past_end["items"] == [] and past_end["total"] == 2 and past_end["offset"] == offset
    empty = (await client.get(endpoint, params={"connection_id": "missing"})).json()["data"]
    assert empty["items"] == [] and empty["total"] == 0
    for params in ({"limit": 101}, {"offset": -1}, {"connection_id": ""}):
        assert (await client.get(endpoint, params=params)).json()["data"]["code"] == "invalid_request"


async def test_concurrent_edit_and_audit_failure_roll_back_all_fields(management):
    client,factory=management
    saved=await create(client)
    path="/api/v1/admin/model-connections/"+saved["connection_id"]
    responses=await asyncio.gather(*[client.patch(path,json={"expected_version":1,"display_name":name}) for name in ("First","Second")])
    assert sorted(response.json()["code"] for response in responses) == [200,200204]
    current=await ModelConnectionRepo.read_admin(saved["connection_id"])
    def reject_audit(*args): raise RuntimeError("synthetic audit rejection")
    event.listen(ModelConnectionAuditORM,"before_insert",reject_audit)
    try:
        failed=await client.patch(path,json={"expected_version":2,"display_name":"Never committed","api_key":"synthetic-no-save"})
        assert failed.json()["code"] == 200000
    finally:
        event.remove(ModelConnectionAuditORM,"before_insert",reject_audit)
    assert await ModelConnectionRepo.read_admin(saved["connection_id"]) == current
    async with factory() as database:
        assert (await database.execute(text("SELECT count(*) FROM model_connection_audit"))).scalar_one() == 2


@pytest.mark.parametrize("status,body,reason",[
    (200,{"id":"c","object":"chat.completion","created":1,"model":"local-chat","choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}]},None),
    (401,{"error":{"message":"synthetic-sensitive-provider-body"}},"provider_auth_failed"),
    (429,{"error":{"message":"synthetic-sensitive-provider-body"}},"provider_rate_limited"),
    (302,{},"provider_rejected"),
    (200,{"choices":[]},"provider_response_invalid"),
])
async def test_probe_is_one_fixed_call_and_never_mutates_configuration(management, monkeypatch,status,body,reason):
    client,factory=management
    saved=await create(client, max_output_tokens=32,request_timeout_seconds=1)
    requests=[];clients=[]
    async def provider(request):
        requests.append(request)
        return httpx.Response(status,json=body,headers={"Location":"http://other-host.invalid/v1"} if status==302 else {})
    def build_client(**options):
        options["http_client"]=httpx.AsyncClient(transport=httpx.MockTransport(provider),follow_redirects=False)
        instance=AsyncOpenAI(**options);clients.append(instance);return instance
    monkeypatch.setattr(service,"AsyncOpenAI",build_client)
    path="/api/v1/admin/model-connections/"+saved["connection_id"]
    result=(await client.post(path+"/test",json={"expected_version":1})).json()["data"]
    assert result["reason"] == reason and result["success"] == (reason is None)
    assert len(requests)==1 and all(instance.is_closed() for instance in clients)
    payload=json.loads(requests[0].content)
    assert payload["messages"] == [{"role":"user","content":"Reply with OK."}]
    assert payload["max_completion_tokens"] == 32 and "tools" not in payload
    assert requests[0].headers["Authorization"] == "Bearer synthetic-initial"
    assert "synthetic-sensitive" not in json.dumps(result)
    assert (await ModelConnectionRepo.read_admin(saved["connection_id"])).version == 1


@pytest.mark.parametrize("failure,expected", [("timeout","provider_timeout"),("unreachable","provider_unreachable"),("invalid_json","provider_response_invalid")])
async def test_probe_transport_failures_are_redacted_and_not_retried(management, monkeypatch, failure, expected):
    client,factory=management
    saved=await create(client,request_timeout_seconds=0.02)
    calls=[];clients=[]
    async def provider(request):
        calls.append(request)
        if failure == "timeout": await asyncio.sleep(0.1)
        if failure == "unreachable": raise httpx.ConnectError("synthetic-provider-secret",request=request)
        return httpx.Response(200,content=b"invalid-json",headers={"Content-Type":"application/json"})
    def build_client(**options):
        options["http_client"]=httpx.AsyncClient(transport=httpx.MockTransport(provider))
        instance=AsyncOpenAI(**options);clients.append(instance);return instance
    monkeypatch.setattr(service,"AsyncOpenAI",build_client)
    response=await client.post("/api/v1/admin/model-connections/"+saved["connection_id"]+"/test",json={"expected_version":1})
    assert response.json()["data"]["reason"] == expected
    assert len(calls) == 1 and all(instance.is_closed() for instance in clients)
    assert "synthetic-provider-secret" not in response.text
