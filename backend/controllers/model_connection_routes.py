"""Authenticated read-only model connection directory."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from controllers.dependencies.auth import get_current_user_id
from repositories.model_connection_repository import ModelConnectionRepo
from utils.response import ApiResponse, make_api_response


class ModelConnectionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str
    display_name: str
    model: str


class ModelConnectionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ModelConnectionChoice]


model_connection_router = APIRouter(prefix="/model-connections", tags=["model-connections"])


@model_connection_router.get("", response_model=ApiResponse[ModelConnectionListResponse])
async def list_model_connections(user_id: Annotated[str, Depends(get_current_user_id)]):
    items = await ModelConnectionRepo.list_enabled()
    return make_api_response(data=ModelConnectionListResponse(items=[
        ModelConnectionChoice(
            connection_id=item.connection_id, display_name=item.display_name, model=item.model
        ) for item in items
    ]))
