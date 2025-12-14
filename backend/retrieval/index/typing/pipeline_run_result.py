"""
a module containing the PipelineRunResult class
"""

from dataclasses import dataclass
from typing import Any

from retrieval.index.typing import workflow
from retrieval.index.typing.state import PipelineState

@dataclass
class PipelineRunResult:
    """
    pipeline run result class definition.
    """
    workflow: str
    """the name of the workflow that was executed."""
    result: Any | None
    """ the result of the workflwo function, this can be anything - we use it only for loggin downstream, and expect each workflwo functioh ot write offical output to the provided storage"""
    state: PipelineState
    """ongoing pipeline context state object"""
    errors: list[BaseException] | None
