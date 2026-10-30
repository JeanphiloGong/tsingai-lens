"""PostgreSQL reads and query results for shared model connection revisions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from infra.persistence.database import AsyncSessionLocal

from infra.persistence.postgres.models.model_connection import ModelConnectionRow


@dataclass(frozen=True)
class ModelConnectionRecord:
    connection_id: str
    revision: int
    display_name: str
    base_url: str
    model: str
    api_key_ref: str | None
    enabled: bool
    context_window_tokens: int | None
    max_output_tokens: int | None
    request_timeout_seconds: float | None
    created_at: datetime
    updated_at: datetime


class ModelConnectionRepository:
    async def list_enabled(self) -> tuple[ModelConnectionRecord, ...]:
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(ModelConnectionRow)
                .where(ModelConnectionRow.enabled.is_(True))
                .order_by(ModelConnectionRow.display_name, ModelConnectionRow.connection_id)
            )
            return tuple(
                ModelConnectionRecord(
                    connection_id=row.connection_id,
                    revision=row.revision,
                    display_name=row.display_name,
                    base_url=row.base_url,
                    model=row.model,
                    api_key_ref=row.api_key_ref,
                    enabled=row.enabled,
                    context_window_tokens=row.context_window_tokens,
                    max_output_tokens=row.max_output_tokens,
                    request_timeout_seconds=row.request_timeout_seconds,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            )

    async def read_enabled(self, connection_id: str) -> ModelConnectionRecord | None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ModelConnectionRow).where(
                    ModelConnectionRow.connection_id == connection_id,
                    ModelConnectionRow.enabled.is_(True),
                )
            )
            if row is None:
                return None
            return ModelConnectionRecord(
                connection_id=row.connection_id,
                revision=row.revision,
                display_name=row.display_name,
                base_url=row.base_url,
                model=row.model,
                api_key_ref=row.api_key_ref,
                enabled=row.enabled,
                context_window_tokens=row.context_window_tokens,
                max_output_tokens=row.max_output_tokens,
                request_timeout_seconds=row.request_timeout_seconds,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def read(self, connection_id: str, revision: int) -> ModelConnectionRecord | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ModelConnectionRow, (connection_id, revision))
            if row is None:
                return None
            return ModelConnectionRecord(
                connection_id=row.connection_id,
                revision=row.revision,
                display_name=row.display_name,
                base_url=row.base_url,
                model=row.model,
                api_key_ref=row.api_key_ref,
                enabled=row.enabled,
                context_window_tokens=row.context_window_tokens,
                max_output_tokens=row.max_output_tokens,
                request_timeout_seconds=row.request_timeout_seconds,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )


ModelConnectionRepo = ModelConnectionRepository()
