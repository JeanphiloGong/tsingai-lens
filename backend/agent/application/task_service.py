from __future__ import annotations

from collections.abc import AsyncIterator
import json
import logging

from agent.repositories.task_repository import TaskRepository


logger = logging.getLogger(__name__)


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    async def read_task(
        self, *, conversation_id: str, task_id: str, user_id: str
    ) -> dict[str, object]:
        return await self.repository.read_task(
            conversation_id=conversation_id,
            task_id=task_id,
            user_id=user_id,
        )

    async def list_tasks(
        self,
        *,
        conversation_id: str,
        user_id: str,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[dict[str, object], ...]:
        return await self.repository.list_tasks(
            conversation_id=conversation_id,
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def stop(
        self, *, conversation_id: str, task_id: str, user_id: str, request_id: str
    ) -> None:
        logger.info(
            "task stop requested",
            extra={"request_id": request_id, "task_id": task_id},
        )
        await self.repository.stop_task(
            conversation_id=conversation_id,
            task_id=task_id,
            user_id=user_id,
        )

    async def resume(
        self,
        *,
        conversation_id: str,
        task_id: str,
        user_id: str,
        request_id: str,
        expected_checkpoint_revision: int,
    ) -> dict[str, object]:
        logger.info(
            "task resume requested",
            extra={"request_id": request_id, "task_id": task_id},
        )
        return await self.repository.resume_task(
            conversation_id=conversation_id,
            task_id=task_id,
            user_id=user_id,
            expected_checkpoint_revision=expected_checkpoint_revision,
        )

    async def decide(
        self,
        *,
        conversation_id: str,
        task_id: str,
        operation_id: str,
        user_id: str,
        decision: str,
        arguments_digest: str,
        request_id: str,
    ) -> None:
        logger.info(
            "operation decision requested",
            extra={
                "request_id": request_id,
                "task_id": task_id,
                "operation_id": operation_id,
            },
        )
        await self.repository.decide_operation(
            conversation_id=conversation_id,
            task_id=task_id,
            operation_id=operation_id,
            user_id=user_id,
            decision=decision,
            arguments_digest=arguments_digest,
        )

    async def events(
        self,
        *,
        conversation_id: str,
        task_id: str,
        user_id: str,
        after_revision: int,
    ) -> AsyncIterator[str]:
        snapshot = await self.read_task(
            conversation_id=conversation_id,
            task_id=task_id,
            user_id=user_id,
        )
        revision = snapshot["checkpoint_revision"]
        if isinstance(revision, int) and revision > after_revision:
            yield "event: task.snapshot\n"
            yield (
                "data: "
                + json.dumps(
                    {
                        "task_id": task_id,
                        "revision": revision,
                        "status": snapshot["status"],
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )


__all__ = ["TaskService"]
