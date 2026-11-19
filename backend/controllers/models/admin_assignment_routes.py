"""Model assignment HTTP routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from controllers.dependencies.authz import ModelManager, require_model_manager
from repositories.model_connection_repository import ModelConnectionRepo, ModelKind, ModelPurpose
from utils.response import make_api_response


admin_assignment_router = APIRouter(
    prefix="/admin/model-assignments",
    tags=["admin-models"],
    dependencies=[Depends(require_model_manager)],
)


class SetAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=0, le=9223372036854775807)


class AssignmentResponse(BaseModel):
    connection_id: str | None
    version: int


@admin_assignment_router.get("/choices")
async def assignment_choices(kind: ModelKind):
    connections = await ModelConnectionRepo.list_enabled(kind)
    return make_api_response(data={"items": [
        {"connection_id": connection.connection_id, "display_name": connection.display_name,
         "model": connection.model}
        for connection in connections
    ]})


@admin_assignment_router.get("/{purpose}")
async def read_assignment(purpose: ModelPurpose):
    saved = await ModelConnectionRepo.read_assignment(purpose)
    data = (AssignmentResponse(connection_id=saved.connection_id, version=saved.version)
            if saved else AssignmentResponse(connection_id=None, version=0))
    return make_api_response(data=data)


@admin_assignment_router.put("/{purpose}")
async def save_assignment(
    purpose: ModelPurpose, payload: SetAssignmentRequest, actor: ModelManager
):
    saved = await ModelConnectionRepo.assign(
        purpose, payload.connection_id, payload.expected_version, actor["user_id"]
    )
    return make_api_response(
        data=AssignmentResponse(connection_id=saved.connection_id, version=saved.version)
    )
