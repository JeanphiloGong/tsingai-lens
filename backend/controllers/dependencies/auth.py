from application.auth import session_service
from application.auth.session_service import SESSION_COOKIE_NAME
from fastapi import Request
from utils.logger import bind_user_id


async def get_current_user_id(request: Request) -> str:
    user = await session_service.resolve_session(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    request.state.current_user = user
    request.state.user_id = user["user_id"]
    bind_user_id(user["user_id"])
    return user["user_id"]


__all__ = ["get_current_user_id"]
