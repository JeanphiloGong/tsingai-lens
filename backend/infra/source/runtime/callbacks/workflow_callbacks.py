# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Workflow callback protocol for the Source runtime."""

from typing import Protocol

from infra.source.runtime.progress import Progress
from infra.source.runtime.typing.pipeline_run_result import PipelineRunResult


class WorkflowCallbacks(Protocol):
    """Callbacks used to observe Source workflow execution."""

    def pipeline_start(self, names: list[str]) -> None:
        ...

    def pipeline_end(self, results: list[PipelineRunResult]) -> None:
        ...

    def workflow_start(self, name: str, instance: object) -> None:
        ...

    def workflow_end(self, name: str, instance: object) -> None:
        ...

    def progress(self, progress: Progress) -> None:
        ...
