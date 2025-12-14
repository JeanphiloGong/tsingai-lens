from retrieval.callbacks.workflow_callbacks import WorkflowCallbacks
from retrieval.callbacks.workflow_callbacks_manager import WorkflowCallbacksManager


def create_callback_chain(
        callbacks: list[WorkflowCallbacks] | None,
        ) -> WorkflowCallbacks:
    """
    create a callback manager that encompasses multiple callbacs.
    """
    manager = WorkflowCallbacksManager()
    for callback in callbacks or []:
        manager.register(callback)
    return manager
