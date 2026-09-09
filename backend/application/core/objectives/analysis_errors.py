"""Public wording for Objective analysis failures, independent of provider text."""

_ANALYSIS_ERROR_MESSAGES = {
    "provider_timeout": "The analysis request timed out. Retry the analysis.",
    "invalid_analysis_artifact": (
        "The analysis returned an invalid result. Retry the analysis."
    ),
    "analysis_dispatch_failed": (
        "Objective analysis could not be scheduled. Retry the analysis."
    ),
    "analysis_interrupted": "Objective analysis was interrupted. Retry the analysis.",
    "agent_analysis_extraction_failed": (
        "Agent analysis failed to extract every relevant paper."
    ),
    "agent_analysis_publish_failed": (
        "The approved analysis could not be published. Retry the analysis."
    ),
    "document_evidence_extraction_failed": (
        "Evidence could not be extracted from this paper. Retry the analysis."
    ),
}


def analysis_error_message(error_code: str | None) -> str:
    """Unknown historical codes get safe wording without rewriting stored data."""
    return _ANALYSIS_ERROR_MESSAGES.get(
        error_code or "",
        "Objective analysis could not be completed. Retry the analysis.",
    )
