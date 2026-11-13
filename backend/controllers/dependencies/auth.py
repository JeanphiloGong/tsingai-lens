from fastapi import HTTPException, Request
from infra.identity import client as identity
from infra.identity.client import SESSION_COOKIE_NAME, SessionNotFoundError, IdentityUnavailableError
from utils.logger import bind_user_id


async def get_current_user_id(request: Request) -> str:
    try:
        user = await identity.Client.resolve_session(
            request.cookies.get(SESSION_COOKIE_NAME)
        )
    except SessionNotFoundError as exc:
        raise HTTPException(401, detail={"code": "authentication_required"}) from exc
    except IdentityUnavailableError as exc:
        raise HTTPException(503, detail={"code": "identity_unavailable"}) from exc
    request.state.current_user = user
    request.state.user_id = user["user_id"]
    bind_user_id(user["user_id"])
    return user["user_id"]
