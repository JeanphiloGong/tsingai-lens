"""PostgreSQL reads and query results for shared model connections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from exceptions import ResourceConflictException, ResourceNotFoundException, ServiceUnavailableException
from infra.persistence.database import AsyncSessionLocal

from infra.persistence.postgres.models.model_connection import (
    ModelAssignmentORM,
    ModelConnectionAuditORM,
    ModelConnectionORM,
)


ModelPurpose = Literal["document_profile", "research_analysis", "embedding"]
ModelKind = Literal["chat", "embedding"]


@dataclass(frozen=True)
class ModelConnectionRecord:
    connection_id: str
    display_name: str
    base_url: str
    model: str
    api_key_ciphertext: bytes | None
    enabled: bool
    context_window_tokens: int | None
    max_output_tokens: int | None
    request_timeout_seconds: float | None
    created_at: datetime
    updated_at: datetime
    priority: int = 0
    version: int = 1
    kind: str = "chat"


@dataclass(frozen=True)
class AdminConnection:
    connection_id: str
    display_name: str
    base_url: str
    model: str
    api_key_configured: bool
    enabled: bool
    priority: int
    context_window_tokens: int | None
    max_output_tokens: int | None
    request_timeout_seconds: float | None
    version: int
    created_at: datetime
    updated_at: datetime
    kind: str


@dataclass(frozen=True)
class ModelAssignment:
    connection_id: str
    version: int


@dataclass(frozen=True)
class AuditRecord:
    connection_id: str
    actor_id: str
    actor_display_name: str | None
    action: str
    version: int
    changes: dict
    created_at: datetime


INITIAL_AUDIT_FIELDS = (
    "display_name", "base_url", "model", "kind", "enabled", "priority",
    "context_window_tokens", "max_output_tokens", "request_timeout_seconds",
)


admin_query = select(
    ModelConnectionORM.connection_id, ModelConnectionORM.display_name,
    ModelConnectionORM.base_url, ModelConnectionORM.model,
    ModelConnectionORM.api_key_ciphertext.is_not(None).label("api_key_configured"),
    ModelConnectionORM.enabled, ModelConnectionORM.priority,
    ModelConnectionORM.context_window_tokens, ModelConnectionORM.max_output_tokens,
    ModelConnectionORM.request_timeout_seconds, ModelConnectionORM.version,
    ModelConnectionORM.created_at, ModelConnectionORM.updated_at, ModelConnectionORM.kind,
)


class ModelConnectionRepository:
    async def read_assigned_connection(self, purpose: ModelPurpose) -> ModelConnectionORM:
        async with AsyncSessionLocal() as database:
            connection = await database.scalar(
                select(ModelConnectionORM)
                .join(ModelAssignmentORM, ModelAssignmentORM.connection_id == ModelConnectionORM.connection_id)
                .where(ModelAssignmentORM.purpose == purpose)
            )
            if connection is None:
                raise ServiceUnavailableException(
                    "Ask an administrator to assign a processing model.",
                    data={"code": "processing_model_unassigned", "purpose": purpose},
                )
            return connection

    async def read_assignment(self, purpose: str) -> ModelAssignment | None:
        async with AsyncSessionLocal() as database:
            row = await database.get(ModelAssignmentORM, purpose)
            return ModelAssignment(row.connection_id, row.version) if row else None

    async def assign(
        self, purpose: str, connection_id: str, expected_version: int, actor_id: str
    ) -> ModelAssignment:
        async with AsyncSessionLocal.begin() as database:
            # Use the same connection-row lock as the enable/disable operation.
            connection = await database.get(ModelConnectionORM, connection_id, with_for_update=True)
            required_kind = "embedding" if purpose == "embedding" else "chat"
            if connection is None or not connection.enabled or connection.kind != required_kind:
                raise ResourceConflictException(
                    "Select an enabled model connection of the required type.",
                    data={"code": "processing_model_unavailable"},
                )
            if expected_version == 0:
                statement = (
                    insert(ModelAssignmentORM)
                    .values(
                        purpose=purpose,
                        connection_id=connection_id,
                        version=1,
                        updated_by=actor_id,
                        updated_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(index_elements=["purpose"])
                    .returning(ModelAssignmentORM.connection_id, ModelAssignmentORM.version)
                )
                row = (await database.execute(statement)).one_or_none()
                if row is not None:
                    return ModelAssignment(row.connection_id, row.version)
            else:
                current = await database.get(ModelAssignmentORM, purpose, with_for_update=True)
                if current is not None and current.version == expected_version:
                    if current.connection_id != connection_id:
                        current.connection_id = connection_id
                        current.version += 1
                        current.updated_by = actor_id
                        current.updated_at = datetime.now(timezone.utc)
                    return ModelAssignment(current.connection_id, current.version)
            raise ResourceConflictException(
                "Assignment changed. Reload before saving.",
                data={"code": "model_assignment_version_conflict"},
            )

    async def list_enabled(self, kind: ModelKind = "chat") -> tuple[ModelConnectionRecord, ...]:
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(ModelConnectionORM)
                .where(ModelConnectionORM.enabled.is_(True), ModelConnectionORM.kind == kind)
                .order_by(
                    ModelConnectionORM.priority.desc(),
                    ModelConnectionORM.display_name, ModelConnectionORM.connection_id,
                )
            )
            return tuple(
                ModelConnectionRecord(
                    connection_id=row.connection_id,
                    display_name=row.display_name,
                    base_url=row.base_url,
                    model=row.model,
                    api_key_ciphertext=row.api_key_ciphertext,
                    enabled=row.enabled,
                    context_window_tokens=row.context_window_tokens,
                    max_output_tokens=row.max_output_tokens,
                    request_timeout_seconds=row.request_timeout_seconds,
                    created_at=row.created_at,
                    updated_at=row.updated_at, priority=row.priority, version=row.version,
                    kind=row.kind,
                )
                for row in rows
            )

    async def read_enabled(self, connection_id: str) -> ModelConnectionRecord | None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ModelConnectionORM).where(
                    ModelConnectionORM.connection_id == connection_id,
                    ModelConnectionORM.enabled.is_(True),
                    ModelConnectionORM.kind == "chat",
                )
            )
            if row is None:
                return None
            return ModelConnectionRecord(
                connection_id=row.connection_id,
                display_name=row.display_name,
                base_url=row.base_url,
                model=row.model,
                api_key_ciphertext=row.api_key_ciphertext,
                enabled=row.enabled,
                context_window_tokens=row.context_window_tokens,
                max_output_tokens=row.max_output_tokens,
                request_timeout_seconds=row.request_timeout_seconds,
                created_at=row.created_at,
                updated_at=row.updated_at, priority=row.priority, version=row.version,
                kind=row.kind,
            )

    async def read(self, connection_id: str) -> ModelConnectionRecord | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(ModelConnectionORM, connection_id)
            if row is None:
                return None
            return ModelConnectionRecord(
                connection_id=row.connection_id,
                display_name=row.display_name,
                base_url=row.base_url,
                model=row.model,
                api_key_ciphertext=row.api_key_ciphertext,
                enabled=row.enabled,
                context_window_tokens=row.context_window_tokens,
                max_output_tokens=row.max_output_tokens,
                request_timeout_seconds=row.request_timeout_seconds,
                created_at=row.created_at,
                updated_at=row.updated_at, priority=row.priority, version=row.version,
                kind=row.kind,
            )


    async def list_admin(self, *, limit: int, offset: int) -> tuple[tuple[AdminConnection, ...], int]:
        async with AsyncSessionLocal() as database, database.begin():
            await database.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            total = await database.scalar(select(func.count()).select_from(ModelConnectionORM))
            rows = (await database.execute(admin_query.order_by(
                ModelConnectionORM.priority.desc(), ModelConnectionORM.display_name,
                ModelConnectionORM.connection_id,
            ).limit(limit).offset(offset))).all()
            return tuple(AdminConnection(*row) for row in rows), total

    async def read_admin(self, connection_id: str) -> AdminConnection:
        async with AsyncSessionLocal() as database:
            row = (await database.execute(admin_query.where(ModelConnectionORM.connection_id == connection_id))).first()
            if row is None:
                raise ResourceNotFoundException("Model connection not found.", data={"code": "model_connection_not_found"})
            return AdminConnection(*row)

    async def list_audit(
        self, *, connection_id: str | None, limit: int, offset: int
    ) -> tuple[tuple[AuditRecord, ...], int]:
        audit = ModelConnectionAuditORM
        query = select(
            audit.connection_id, audit.actor_id, audit.actor_display_name,
            audit.action, audit.version, audit.changes, audit.created_at,
        )
        count = select(func.count()).select_from(audit)
        if connection_id is not None:
            query = query.where(audit.connection_id == connection_id)
            count = count.where(audit.connection_id == connection_id)
        async with AsyncSessionLocal() as database, database.begin():
            await database.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            total = (await database.execute(count)).scalar_one()
            if offset >= total:
                return (), total
            rows = await database.execute(
                query.order_by(audit.created_at.desc(), audit.id.desc()).limit(limit).offset(offset)
            )
            return tuple(AuditRecord(*row) for row in rows), total

    async def create(
        self, actor_id: str, connection_id: str, values: dict, *, actor_display_name: str | None
    ) -> AdminConnection:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal.begin() as database:
            connection = ModelConnectionORM(
                connection_id=connection_id, **values,
                enabled=False, version=1, created_at=now, updated_at=now,
            )
            database.add(connection)
            await database.flush()
            audit_changes = {
                field: {"before": None, "after": getattr(connection, field)}
                for field in INITIAL_AUDIT_FIELDS
            }
            if connection.api_key_ciphertext is not None:
                audit_changes["api_key"] = {
                    "before": "unconfigured", "after": "configured", "operation": "set",
                }
            database.add(ModelConnectionAuditORM(
                connection_id=connection_id, actor_id=actor_id, actor_display_name=actor_display_name,
                action="create", version=1, changes=audit_changes, created_at=now,
            ))
            await database.flush()
            row = (await database.execute(admin_query.where(ModelConnectionORM.connection_id == connection_id))).one()
            return AdminConnection(*row)

    async def update(
        self, actor_id: str, connection_id: str, expected_version: int, changes: dict,
        *, actor_display_name: str | None,
    ) -> AdminConnection:
        async with AsyncSessionLocal.begin() as database:
            row = await database.scalar(select(ModelConnectionORM).where(
                ModelConnectionORM.connection_id == connection_id,
            ).with_for_update())
            if row is None:
                raise ResourceNotFoundException("Model connection not found.", data={"code": "model_connection_not_found"})
            if row.version != expected_version:
                raise ResourceConflictException("Configuration changed; reload before saving.", data={"code": "model_connection_version_conflict"})
            if changes.get("enabled") is False and await database.scalar(
                select(ModelAssignmentORM.purpose)
                .where(ModelAssignmentORM.connection_id == connection_id)
                .limit(1)
            ) is not None:
                raise ResourceConflictException(
                    "Reassign processing tasks before disabling this model.",
                    data={"code": "model_connection_assigned"},
                )
            audit_changes = {}
            for field, value in changes.items():
                before = getattr(row, field)
                if field == "api_key_ciphertext":
                    if value is None:
                        if before is None:
                            continue
                        key_operation = "clear"
                    else:
                        key_operation = "set" if before is None else "replace"
                    audit_changes["api_key"] = {
                        "before": "unconfigured" if before is None else "configured",
                        "after": "unconfigured" if value is None else "configured",
                        "operation": key_operation,
                    }
                elif before != value:
                    audit_changes[field] = {"before": before, "after": value}
                else:
                    continue
                setattr(row, field, value)
            if audit_changes:
                row.version += 1
                row.updated_at = datetime.now(timezone.utc)
                database.add(ModelConnectionAuditORM(
                    connection_id=connection_id, actor_id=actor_id, actor_display_name=actor_display_name,
                    action="update", version=row.version, changes=audit_changes, created_at=row.updated_at,
                ))
                await database.flush()
            result = (await database.execute(admin_query.where(ModelConnectionORM.connection_id == connection_id))).one()
            return AdminConnection(*result)


ModelConnectionRepo = ModelConnectionRepository()
