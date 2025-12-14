"""
pipeline workflow types
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


from retrieval.config.models.
from retrieval.config.models.graph_rag_config import GraphRagConfig
from retrieval.index.typing.context import PipelineRunContext

@dataclass
class WorkflowFunctionOutput:
    """
    data container for workflow function results.
    """
    result: Any | None
    """
    the result of the workflow function. thsi can be anythind - we use it only for loggin downstream and expect each workflow function to write official outpus to the provided storage.
    """
    stop: bool = False
    """
    flag to indicate if the workflow should stop after this function. this should only be used when continuation could cause an unstable failure
    """


WorkflowFunction = Callable[
        [GraphRagConfig, PipelineRunContext],
        Awaitable[WorkflowFunctionOutput],
        ]

Workflow = tuple[str, WorkflowFunction]
