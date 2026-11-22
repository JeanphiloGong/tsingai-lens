import pytest

from agent.domain.models import AgentTask, Operation, digest_arguments


def test_task_can_resume_after_interruption_and_checkpoint_is_continuous():
    task = AgentTask("task-1", "conv-1", "msg-1", "accepted")
    task = (
        task.transition("running")
        .checkpoint(1)
        .transition("interrupted")
        .transition("running")
    )
    assert task.status == "running"
    with pytest.raises(ValueError, match="increase by one"):
        task.checkpoint(3)


def test_operation_binds_approval_to_exact_arguments():
    digest = digest_arguments({"path": "Source.pdf"})
    operation = Operation("op-1", "task-1", "read_source", digest, "approval_required")
    approved = operation.decide("approved", digest)
    assert approved.retry_identity() == "op-1"
    with pytest.raises(ValueError, match="digest mismatch"):
        operation.decide("approved", "0" * 64)


def test_terminal_task_cannot_resume():
    with pytest.raises(ValueError):
        AgentTask("task-1", "conv-1", None, "completed").transition("running")


def test_uncertain_operation_requires_reconciliation_before_replay():
    operation = Operation("op-1", "task-1", "write_result", "a" * 64, "running")
    reconciled = operation.reconcile()
    assert reconciled.status == "needs_reconciliation"
    with pytest.raises(ValueError, match="uncertain execution"):
        reconciled.reconcile()
