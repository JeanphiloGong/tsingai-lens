"""
collection of callbacks that can be used to monitor the workflow execution
"""

from typing import Protocol

from retrieval.index.typing.pipeline_run_result import PipelineRunResult
from retrieval.logger.progress import Progress


class WorkflowCallbacks(Protocol):
    """
    a collection of callback that can ve used to monitor the workflow execution

    this base class is a "noop" implementation so that clients may implement just the call backs they need
    """
    def pipeline_start(self, names: list[str]) -> None:
        """
        execute this callback to signal when the entire pipeline starts
        """
        ...

    def pipeline_end(self, results: list[PipelineRunResult]) -> None:
        """
        execute this callback to signal when the entire pipeline ends
        """
        ...

    def workflow_start(self, name: str, instance: object) -> None:
        """
        execute this callback when a workflow starts
        """
        ...

    def workflow_end(self, name: str, instance: object) -> None:
        """
        execute this callback when a workflow ends.
        """
        ...

    def progress(self, progress: Progress) -> None:
        """handle when progress occurs."""
        ...

