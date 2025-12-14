from dataclasses import dataclass

@dataclass
class Progress:
    """
    a class representing the progress of a task
    """
    description: str | None = None
    """description of the progress"""

    total_items: int | None = None 
    """total number of items"""

    completed_items: int | None = None
    """number of items completed"""
