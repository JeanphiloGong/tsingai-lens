"""
a module containing the "PiprlineRunContext" models
"""

from dataclasses import dataclass


@dataclass
class PipelineRunContext:
    """
    provides the context for the crrent pipeline run.
    """
