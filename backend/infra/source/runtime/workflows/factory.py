# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Encapsulates pipeline construction and selection."""

import logging
from typing import ClassVar

from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.config.source_runtime_config import GraphRagConfig
from infra.source.runtime.typing.pipeline import Pipeline
from infra.source.runtime.typing.workflow import WorkflowFunction

logger = logging.getLogger(__name__)


class PipelineFactory:
    """A factory class for workflow pipelines."""

    workflows: ClassVar[dict[str, WorkflowFunction]] = {}
    pipelines: ClassVar[dict[str, list[str]]] = {}

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
    def register_pipeline(cls, name: str, workflows: list[str]):
        """Register a new pipeline method as a list of workflow names."""
        cls.pipelines[name] = workflows

    @classmethod
    def create_pipeline(
        cls,
        config: GraphRagConfig,
        method: IndexingMethod | str = IndexingMethod.Standard,
    ) -> Pipeline:
        """Create a pipeline generator."""
        workflows = config.workflows or cls.pipelines.get(method, [])
        logger.info("Creating pipeline with workflows: %s", workflows)
        return Pipeline([(name, cls.workflows[name]) for name in workflows])


# --- Register default implementations ---
_source_handoff_workflows = [
    "create_base_text_units",
    "create_final_documents",
    "create_final_text_units",
    "create_sections",
    "create_table_cells",
]
PipelineFactory.register_pipeline(
    IndexingMethod.Standard, ["load_input_documents", *_source_handoff_workflows]
)
PipelineFactory.register_pipeline(
    IndexingMethod.Fast, ["load_input_documents", *_source_handoff_workflows]
)
