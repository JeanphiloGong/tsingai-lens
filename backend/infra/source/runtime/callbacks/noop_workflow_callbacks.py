# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""No-op workflow callbacks for the Source runtime."""

from infra.source.runtime.callbacks.workflow_callbacks import WorkflowCallbacks
from infra.source.runtime.progress import Progress
from infra.source.runtime.typing.pipeline_run_result import PipelineRunResult


class NoopWorkflowCallbacks(WorkflowCallbacks):
    """A no-op implementation of Source workflow callbacks."""

    def pipeline_start(self, names: list[str]) -> None:
        """Signal that the pipeline has started."""

    def pipeline_end(self, results: list[PipelineRunResult]) -> None:
        """Signal that the pipeline has ended."""

    def workflow_start(self, name: str, instance: object) -> None:
        """Signal that a workflow has started."""

    def workflow_end(self, name: str, instance: object) -> None:
        """Signal that a workflow has ended."""

    def progress(self, progress: Progress) -> None:
        """Signal workflow progress."""
