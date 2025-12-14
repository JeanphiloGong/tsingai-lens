
from retrieval.callbacks.workflow_callbacks import WorkflowCallbacks


class WorkflowCallbacksManager(WorkflowCallbacks):
    """
    a registry of WorkflowCallbacks
    """

    _callbacks: list[WorkflowCallbacks]

    def __init__(self):
        """
        create a new instance of WorkflowCallbacksRegistry
        """
        self._callbacks = []

    def register(self, callbacks: WorkflowCallbacks) -> None:
        """register a new WorkflowCallbacks type"""
        self._callbacks.append(callbacks)
