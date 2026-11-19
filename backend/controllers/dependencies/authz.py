import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from controllers.dependencies.auth import CurrentUser
from exceptions import ServiceUnavailableException
from infra.identity import client as identity
from infra.identity.client import SESSION_COOKIE_NAME, IdentityUnavailableError, SessionNotFoundError


async def require_model_manager(request: Request, user: CurrentUser) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    try:
        allowed = await identity.Client.check(token, "models.manage")
    except SessionNotFoundError as exc:
        raise HTTPException(401, detail={"code": "authentication_required"}) from exc
    except IdentityUnavailableError as exc:
        raise HTTPException(503, detail={"code": "identity_unavailable"}) from exc
    if not allowed:
        raise HTTPException(403, detail={"code": "permission_denied"})

    if request.method != "GET":
        expected_origin = os.environ.get("BROWSER_ORIGIN")
        if not expected_origin:
            raise ServiceUnavailableException(
                "Model configuration is unavailable.",
                data={"code": "model_configuration_unavailable"},
            )
        if request.headers.get("origin") != expected_origin:
            raise HTTPException(403, detail={"code": "permission_denied"})
    return user


ModelManager = Annotated[dict[str, str], Depends(require_model_manager)]
