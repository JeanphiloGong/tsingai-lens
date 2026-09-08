"""PostgreSQL persistence for collection- and document-scoped pipeline runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.pipeline import PipelineRun
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.pipeline_run import PipelineRunRow


_ACTIVE_STATUSES = ("queued", "running")
_SUCCESS_STATUSES = ("completed", "partial_success")


class PostgresPipelineRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_run(self, run: PipelineRun) -> PipelineRun:
        async with self.session_factory.begin() as session:
            session.add(_run_row(run))
        return run

    async def get_or_create_collection_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]:
        if run.scope_type != "collection" or run.scope_id != run.collection_id:
            raise ValueError("collection run must use its collection as scope")
        async with self.session_factory.begin() as session:
            collection = await session.scalar(
                select(Collection)
                .where(Collection.collection_id == run.collection_id)
                .with_for_update()
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {run.collection_id}")
            active = await self._active_run(session, run)
            if active is not None:
                return _to_run(active), False
            session.add(_run_row(run))
            return run, True

    async def get_or_create_document_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]:
        if run.scope_type != "document" or run.input_fingerprint is None:
            raise ValueError("document run requires document scope and input fingerprint")
        async with self.session_factory.begin() as session:
            document = await session.scalar(
                select(Document)
                .where(
                    Document.collection_id == run.collection_id,
                    Document.document_id == run.scope_id,
                )
                .with_for_update()
            )
            if document is None:
                raise FileNotFoundError(
                    f"document not found: {run.collection_id}/{run.scope_id}"
                )
            active = await self._active_run(session, run)
            if active is not None:
                return _to_run(active), False
            completed = await session.scalar(
                select(PipelineRunRow)
                .where(
                    PipelineRunRow.pipeline_name == run.pipeline_name,
                    PipelineRunRow.scope_type == run.scope_type,
                    PipelineRunRow.scope_id == run.scope_id,
                    PipelineRunRow.input_fingerprint == run.input_fingerprint,
                    PipelineRunRow.status.in_(_SUCCESS_STATUSES),
                )
                .order_by(PipelineRunRow.updated_at.desc(), PipelineRunRow.run_id.desc())
                .limit(1)
            )
            if completed is not None:
                return _to_run(completed), False
            session.add(_run_row(run))
            return run, True

    async def read_run(self, run_id: str) -> PipelineRun | None:
        async with self.session_factory() as session:
            row = await session.get(PipelineRunRow, run_id)
            return _to_run(row) if row is not None else None

    async def list_runs(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[PipelineRun, ...]:
        statement = select(PipelineRunRow)
        if collection_id is not None:
            statement = statement.where(PipelineRunRow.collection_id == collection_id)
        if status is not None:
            statement = statement.where(PipelineRunRow.status == status)
        statement = statement.order_by(
            PipelineRunRow.updated_at.desc(),
            PipelineRunRow.run_id.desc(),
        )
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_to_run(row) for row in rows)

    async def update_run(self, run: PipelineRun) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(PipelineRunRow, run.run_id)
            if row is None:
                return False
            row.collection_id = run.collection_id
            row.pipeline_name = run.pipeline_name
            row.scope_type = run.scope_type
            row.scope_id = run.scope_id
            row.mode = run.mode
            row.input_fingerprint = run.input_fingerprint
            row.status = run.status.value
            row.record_json = run.to_record()
            row.updated_at = _datetime(
                run.timestamps.updated_at or datetime.now(timezone.utc)
            )
            return True

    @staticmethod
    async def _active_run(
        session: AsyncSession,
        run: PipelineRun,
    ) -> PipelineRunRow | None:
        return await session.scalar(
            select(PipelineRunRow)
            .where(
                PipelineRunRow.pipeline_name == run.pipeline_name,
                PipelineRunRow.scope_type == run.scope_type,
                PipelineRunRow.scope_id == run.scope_id,
                PipelineRunRow.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(PipelineRunRow.updated_at.desc(), PipelineRunRow.run_id.desc())
            .limit(1)
        )


def _run_row(run: PipelineRun) -> PipelineRunRow:
    created_at = run.timestamps.created_at
    if created_at is None:
        raise ValueError("persisted pipeline run requires created_at")
    created_timestamp = _datetime(created_at)
    updated_timestamp = _datetime(run.timestamps.updated_at or created_at)
    return PipelineRunRow(
        run_id=run.run_id,
        collection_id=run.collection_id,
        pipeline_name=run.pipeline_name,
        scope_type=run.scope_type,
        scope_id=run.scope_id,
        mode=run.mode,
        input_fingerprint=run.input_fingerprint,
        status=run.status.value,
        record_json=run.to_record(),
        created_at=created_timestamp,
        updated_at=updated_timestamp,
    )


def _to_run(row: PipelineRunRow) -> PipelineRun:
    payload = dict(row.record_json)
    payload.update(
        {
            "run_id": row.run_id,
            "collection_id": row.collection_id,
            "pipeline_name": row.pipeline_name,
            "scope_type": row.scope_type,
            "scope_id": row.scope_id,
            "mode": row.mode,
            "input_fingerprint": row.input_fingerprint,
            "status": row.status,
        }
    )
    timestamps = dict(payload.get("timestamps") or {})
    timestamps["created_at"] = _iso(row.created_at)
    timestamps["updated_at"] = _iso(row.updated_at)
    payload["timestamps"] = timestamps
    return PipelineRun.from_mapping(payload)


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = str(value)
        parsed = datetime.fromisoformat(
            f"{text_value[:-1]}+00:00" if text_value.endswith("Z") else text_value
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


__all__ = ["PostgresPipelineRunRepository"]
