import json
import logging

from exceptions import (
    MethodNotAllowedException,
    PermissionDeniedException,
    ProjectException,
    RequestInvalidException,
    ResourceNotFoundException,
    ServerException,
    TokenInvalidException,
)
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from utils.logger import bind_request_id, bind_user_id, clear_request_id, clear_user_id
from utils.response import make_api_response

logger = logging.getLogger(__name__)


async def project_exception_handler(
    request: Request, exc: ProjectException
) -> JSONResponse:
    request.state.business_code = exc.code
    logger.warning(
        "Request rejected method=%s path=%s code=%s reason=%s",
        request.method,
        request.url.path,
        exc.code,
        json.dumps(exc.message[:500], ensure_ascii=False),
        extra={"business_code": exc.code},
    )
    response = make_api_response(code=exc.code, message=exc.message, data=exc.data)
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if exc.status_code == 404:
        error = ResourceNotFoundException()
    elif exc.status_code == 405:
        error = MethodNotAllowedException()
    elif exc.status_code == 403:
        error = PermissionDeniedException()
    elif exc.status_code == 401:
        error = TokenInvalidException()
    else:
        error = ServerException()
    return await project_exception_handler(request, error)


async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return await project_exception_handler(
        request,
        RequestInvalidException(data={"errors": exc.errors()}),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_token = bind_request_id(getattr(request.state, "request_id", None))
    user_token = bind_user_id(getattr(request.state, "user_id", ""))
    try:
        logger.exception(
            "Unhandled request failure method=%s path=%s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return await project_exception_handler(request, ServerException())
    finally:
        clear_user_id(user_token)
        clear_request_id(request_token)
