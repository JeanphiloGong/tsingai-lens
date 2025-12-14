"""
a module containing the pipeline class
"""

from collections.abc import Generator

from retrieval.index.typing.workflow import Workflow


class Pipeline:
    """
    encapsulates running workflows.
    """

    def __init__(self, workflows: list[Workflow]):
        self.workflows = workflows
