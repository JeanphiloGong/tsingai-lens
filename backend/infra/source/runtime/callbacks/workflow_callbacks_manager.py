# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Workflow callback registry for the Source runtime."""

from infra.source.runtime.callbacks.workflow_callbacks import WorkflowCallbacks
from infra.source.runtime.progress import Progress
from infra.source.runtime.typing.pipeline_run_result import PipelineRunResult


class WorkflowCallbacksManager(WorkflowCallbacks):
    """A registry of workflow callbacks."""

    _callbacks: list[WorkflowCallbacks]

    def __init__(self):
        self._callbacks = []

    def register(self, callbacks: WorkflowCallbacks) -> None:
        """Register a new callback handler."""
        self._callbacks.append(callbacks)

    def pipeline_start(self, names: list[str]) -> None:
        for callback in self._callbacks:
            if hasattr(callback, "pipeline_start"):
                callback.pipeline_start(names)

    def pipeline_end(self, results: list[PipelineRunResult]) -> None:
        for callback in self._callbacks:
            if hasattr(callback, "pipeline_end"):
                callback.pipeline_end(results)

    def workflow_start(self, name: str, instance: object) -> None:
        for callback in self._callbacks:
            if hasattr(callback, "workflow_start"):
                callback.workflow_start(name, instance)

    def workflow_end(self, name: str, instance: object) -> None:
        for callback in self._callbacks:
            if hasattr(callback, "workflow_end"):
                callback.workflow_end(name, instance)

    def progress(self, progress: Progress) -> None:
        for callback in self._callbacks:
            if hasattr(callback, "progress"):
                callback.progress(progress)
