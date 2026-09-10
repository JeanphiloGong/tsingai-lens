# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Encapsulates pipeline construction and selection."""

import logging
from typing import ClassVar

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.runtime.typing.pipeline import Pipeline
from infra.source.runtime.typing.workflow import WorkflowFunction

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE_WORKFLOWS = [
    "load_input_documents",
    "create_source_artifacts",
]


class PipelineFactory:
    """A factory class for workflow pipelines."""

    workflows: ClassVar[dict[str, WorkflowFunction]] = {}

    @classmethod
    def register(cls, name: str, workflow: WorkflowFunction):
        """Register a custom workflow function."""
        cls.workflows[name] = workflow

    @classmethod
    def register_all(cls, workflows: dict[str, WorkflowFunction]):
        """Register a dict of custom workflow functions."""
        for name, workflow in workflows.items():
            cls.register(name, workflow)

    @classmethod
    def create_pipeline(
        cls,
        config: SourceRuntimeConfig,
    ) -> Pipeline:
        """Create the configured or canonical Source pipeline."""
        workflows = config.workflows or _DEFAULT_SOURCE_WORKFLOWS
        logger.info("Creating pipeline with workflows: %s", workflows)
        return Pipeline([(name, cls.workflows[name]) for name in workflows])
