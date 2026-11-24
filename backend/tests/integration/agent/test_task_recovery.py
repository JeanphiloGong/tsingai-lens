from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from agent.application.runner import DurableRunner
from agent.application.task_execution import TaskExecution
from agent.domain.models import Operation
from agent.repositories.task_repository import TaskRepository
from infra.persistence.postgres.models.chat import AgentOperationORM, AgentTaskORM
from infra.persistence.postgres.models.workspace import WorkspaceORM
from infra.persistence.postgres.models.conversation import ConversationORM, MessageORM


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class ExecutionInterrupted(RuntimeError):
    pass


class InterruptingTaskRepository(TaskRepository):
    interrupt_after_first_bundle = True

    async def write_checkpoint_bundle(self, **kwargs):
        revision = await super().write_checkpoint_bundle(**kwargs)
        if self.interrupt_after_first_bundle:
            self.interrupt_after_first_bundle = False
            raise ExecutionInterrupted()
        return revision


async def test_recovery_reuses_committed_operation(
    postgres_session_factory, identity_subjects
):
    owner = await identity_subjects.create_subject(email="agent-v3-owner@example.test")
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(
            WorkspaceORM(
                workspace_id="agent-v3-workspace",
                owner_user_id=owner["user_id"],
                name="Agent V3",
                status="idle",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ConversationORM(
                conversation_id="agent-v3-conversation",
                user_id=owner["user_id"],
                workspace_id="agent-v3-workspace",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            MessageORM(
                message_id="agent-v3-question",
                conversation_id="agent-v3-conversation",
                position=0,
                role="user",
                content="Inspect Source.",
                created_at=now,
            )
        )

    repository = InterruptingTaskRepository()
    async with postgres_session_factory.begin() as db:
        await repository.insert_accepted_task(
            db,
            task_id="agent-v3-task",
            conversation_id="agent-v3-conversation",
            trigger_message_id="agent-v3-question",
        )

    operation = Operation(
        "agent-v3-operation",
        "agent-v3-task",
        "read_source",
        "a" * 64,
        "requested",
    )
    assert (
        await repository.save_checkpoint(
            task_id="agent-v3-task",
            expected_revision=0,
            checkpoint={
                "operations": [asdict(operation)],
                "steps": [],
                "messages": [],
            },
            status="running",
        )
        == 1
    )

    attempts = 0

    async def capability(_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        return {"hold_time_minutes": 30}

    source_runner = DurableRunner(capability=capability, checkpoint=lambda _: None)
    first = TaskExecution(repository, source_runner)
    with pytest.raises(ExecutionInterrupted):
        await first.run_task(
            task_id="agent-v3-task",
            user_id=owner["user_id"],
            request="inspect Source",
        )
    assert attempts == 1

    second = TaskExecution(repository, source_runner)
    assert (
        await second.run_task(
            task_id="agent-v3-task",
            user_id=owner["user_id"],
            request="inspect Source",
        )
        == "completed"
    )
    assert attempts == 1

    async with postgres_session_factory() as db:
        task = await db.get(AgentTaskORM, "agent-v3-task")
        operations = (
            await db.scalars(
                select(AgentOperationORM).where(
                    AgentOperationORM.task_id == "agent-v3-task",
                    AgentOperationORM.status == "succeeded",
                )
            )
        ).all()
        messages = (
            await db.scalars(
                select(MessageORM).where(
                    MessageORM.produced_by_task_id == "agent-v3-task",
                    MessageORM.role == "assistant",
                )
            )
        ).all()

    assert task is not None
    assert task.status == "completed"
    assert task.finished_at is not None
    assert task.final_message_id == messages[0].message_id
    assert len(operations) == 1
    assert operations[0].result == {"hold_time_minutes": 30}
    assert len(messages) == 1
