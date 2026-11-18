"""Credential effects and a bounded saved-configuration probe."""
import asyncio
from time import perf_counter
from uuid import uuid4
import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError
from exceptions import ResourceConflictException, ResourceNotFoundException
from infra.llm.model_credentials import decrypt_api_key, encrypt_api_key, load_master_key
from repositories.model_connection_repository import ModelConnectionRepo


async def create_connection(
    actor_id: str, *, actor_display_name: str | None, api_key: str | None, **configuration
):
    connection_id = "model_" + uuid4().hex
    ciphertext = encrypt_api_key(load_master_key(), connection_id, api_key) if api_key is not None else None
    return await ModelConnectionRepo.create(actor_id, connection_id, {
        **configuration, "api_key_ciphertext": ciphertext,
    }, actor_display_name=actor_display_name)


async def update_connection(
    actor_id: str, connection_id: str, expected_version: int, changes: dict,
    *, actor_display_name: str | None,
):
    # Membership in changes preserves the distinction between omission and explicit null.
    if "api_key" in changes:
        key = changes.pop("api_key")
        changes["api_key_ciphertext"] = encrypt_api_key(load_master_key(), connection_id, key) if key is not None else None
    return await ModelConnectionRepo.update(
        actor_id, connection_id, expected_version, changes, actor_display_name=actor_display_name
    )


async def test_connection(connection_id: str, expected_version: int):
    saved = await ModelConnectionRepo.read(connection_id)
    if saved is None:
        raise ResourceNotFoundException("Model connection not found.", data={"code": "model_connection_not_found"})
    if saved.version != expected_version:
        raise ResourceConflictException("Configuration changed; reload before saving.", data={"code": "model_connection_version_conflict"})
    api_key = decrypt_api_key(load_master_key(), saved.connection_id, saved.api_key_ciphertext) if saved.api_key_ciphertext is not None else "not-needed"
    timeout = min(10.0, saved.request_timeout_seconds or 10.0)
    started = perf_counter()
    reason = None
    try:
        async with AsyncOpenAI(api_key=api_key, base_url=saved.base_url,
            timeout=timeout, max_retries=0,
            http_client=httpx.AsyncClient(follow_redirects=False),
        ) as client:
            completion = await asyncio.wait_for(client.chat.completions.create(
                model=saved.model, messages=[{"role":"user", "content":"Reply with OK."}],
                max_completion_tokens=min(128, saved.max_output_tokens or 128),
            ), timeout=timeout)
            if not completion.choices or not isinstance(completion.choices[0].message.content, str) or not completion.choices[0].message.content.strip():
                reason = "provider_response_invalid"
    except (APITimeoutError, asyncio.TimeoutError):
        reason = "provider_timeout"
    except APIStatusError as error:
        reason = ("provider_auth_failed" if error.status_code in {401,403} else
                  "provider_rate_limited" if error.status_code == 429 else "provider_rejected")
    except APIConnectionError:
        reason = "provider_unreachable"
    except (APIError, ValidationError, ValueError, TypeError, AttributeError):
        reason = "provider_response_invalid"
    return {"connection_id": saved.connection_id, "tested_version":saved.version,
        "success":reason is None, "latency_ms":max(0, int((perf_counter()-started)*1000)), "reason":reason}
