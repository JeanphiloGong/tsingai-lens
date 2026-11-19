"""Model administration HTTP routes."""
from datetime import datetime
from typing import Annotated
import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from application import model_connection_service as service
from controllers.dependencies.authz import ModelManager, require_model_manager
from repositories.model_connection_repository import ModelConnectionRepo, ModelKind
from utils.response import make_api_response

PositiveInt = Annotated[int, Field(gt=0, le=2147483647)]
Version = Annotated[int, Field(gt=0, le=9223372036854775807)]


class CreateConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    display_name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    kind: ModelKind = "chat"
    api_key: str | None = None
    priority: int = Field(default=0, ge=-2147483648, le=2147483647)
    context_window_tokens: PositiveInt | None = None
    max_output_tokens: PositiveInt | None = None
    request_timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("display_name", "model", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("base_url")
    @classmethod
    def validate_address(cls, value):
        try:
            url = httpx.URL(value)
            if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment or any(char.isspace() for char in value):
                raise ValueError("invalid base URL")
        except httpx.InvalidURL:
            raise ValueError("invalid base URL") from None
        return value

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value):
        if value is not None and (not 1 <= len(value.encode()) <= 8192 or "\r" in value or "\n" in value):
            raise ValueError("invalid provider credential")
        return value


class UpdateConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    expected_version: Version
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=-2147483648, le=2147483647)
    context_window_tokens: PositiveInt | None = None
    max_output_tokens: PositiveInt | None = None
    request_timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    api_key: str | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    validate_key = field_validator("api_key")(CreateConnectionRequest.validate_key.__func__)

    @model_validator(mode="after")
    def check_changes(self):
        changes = self.model_fields_set - {"expected_version"}
        if not changes or any(getattr(self, field) is None for field in changes & {"display_name","enabled","priority"}):
            raise ValueError("at least one valid change is required")
        return self


class TestConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    expected_version: Version


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    connection_id: str
    display_name: str
    base_url: str
    model: str
    kind: ModelKind
    api_key_configured: bool
    enabled: bool
    priority: int
    context_window_tokens: int | None
    max_output_tokens: int | None
    request_timeout_seconds: float | None
    version: int
    created_at: datetime
    updated_at: datetime


class ConnectionListResponse(BaseModel):
    items: list[ConnectionResponse]
    total: int
    limit: int
    offset: int


class ConnectionTestResponse(BaseModel):
    connection_id: str
    tested_version: int
    success: bool
    latency_ms: int
    reason: str | None


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    connection_id: str
    actor_id: str
    actor_display_name: str | None
    action: str
    version: int
    changes: dict
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditResponse]
    total: int
    limit: int
    offset: int


admin_model_router = APIRouter(
    prefix="/admin",
    tags=["admin-models"],
    dependencies=[Depends(require_model_manager)],
)


@admin_model_router.get("/model-connection-audit")
async def list_audit(
    connection_id: str | None = Query(None, min_length=1, max_length=64),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = await ModelConnectionRepo.list_audit(
        connection_id=connection_id, limit=limit, offset=offset
    )
    data = AuditListResponse(
        items=[AuditResponse.model_validate(item) for item in items],
        total=total, limit=limit, offset=offset,
    )
    return make_api_response(data=data.model_dump(mode="json"))


@admin_model_router.get("/model-connections")
async def list_connections(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    items, total = await ModelConnectionRepo.list_admin(limit=limit, offset=offset)
    return make_api_response(data=ConnectionListResponse(items=[ConnectionResponse.model_validate(item) for item in items], total=total,limit=limit,offset=offset).model_dump(mode="json"))


@admin_model_router.get("/model-connections/{connection_id}")
async def read_connection(connection_id: str):
    return make_api_response(data=ConnectionResponse.model_validate(await ModelConnectionRepo.read_admin(connection_id)).model_dump(mode="json"))


@admin_model_router.post("/model-connections")
async def create_connection(payload: CreateConnectionRequest, actor: ModelManager):
    saved = await service.create_connection(
        actor["user_id"], actor_display_name=actor.get("display_name", "").strip() or None,
        **payload.model_dump(),
    )
    return make_api_response(data=ConnectionResponse.model_validate(saved).model_dump(mode="json"))


@admin_model_router.patch("/model-connections/{connection_id}")
async def update_connection(connection_id: str, payload: UpdateConnectionRequest, actor: ModelManager):
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    saved = await service.update_connection(
        actor["user_id"], connection_id, payload.expected_version, changes,
        actor_display_name=actor.get("display_name", "").strip() or None,
    )
    return make_api_response(data=ConnectionResponse.model_validate(saved).model_dump(mode="json"))


@admin_model_router.post("/model-connections/{connection_id}/test")
async def test_connection(connection_id: str, payload: TestConnectionRequest):
    return make_api_response(data=ConnectionTestResponse(**await service.test_connection(connection_id, payload.expected_version)).model_dump(mode="json"))
