from typing import Any, Generic, TypeVar

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

ResponseData = TypeVar("ResponseData")


class ApiResponse(BaseModel, Generic[ResponseData]):
    """The public JSON envelope, including an empty data object for no result."""

    code: int = 200
    message: str = "success"
    data: ResponseData | dict[str, Any]
    meta: dict[str, Any] | None = None


def make_api_response(
    code: int = 200,
    message: str = "success",
    data: Any = None,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=jsonable_encoder(
            {
                "code": code,
                "message": message,
                "data": {} if data is None else data,
                "meta": meta,
            }
        ),
    )
