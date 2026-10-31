"""Stable input errors shared by feedback workers."""

class AnalysisInputError(ValueError):
    """The feedback version cannot be analysed without inventing context."""

class FeedbackVersionSupersededError(AnalysisInputError):
    """A newer persisted feedback version superseded this job."""
