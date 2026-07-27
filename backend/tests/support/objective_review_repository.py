from __future__ import annotations

from domain.evaluation import FindingCuration, FindingFeedback


class InMemoryObjectiveReviewRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.feedback: dict[str, FindingFeedback] = {}
        self.curations: dict[str, FindingCuration] = {}

    def upsert_feedback(self, feedback: FindingFeedback):
        self.feedback[feedback.feedback_id] = feedback
        return feedback

    def list_feedback(
        self,
        collection_id,
        objective_id=None,
        analysis_version=None,
        finding_id=None,
    ):
        return tuple(
            item
            for item in self.feedback.values()
            if item.collection_id == collection_id
            and (objective_id is None or item.objective_id == objective_id)
            and (
                analysis_version is None
                or item.analysis_version == analysis_version
            )
            and (finding_id is None or item.finding_id == finding_id)
        )

    def upsert_curation(self, curation: FindingCuration):
        self.curations[curation.curation_id] = curation
        return curation

    def list_curations(
        self,
        collection_id,
        objective_id=None,
        analysis_version=None,
        finding_id=None,
    ):
        return tuple(
            item
            for item in self.curations.values()
            if item.collection_id == collection_id
            and (objective_id is None or item.objective_id == objective_id)
            and (
                analysis_version is None
                or item.analysis_version == analysis_version
            )
            and (finding_id is None or item.finding_id == finding_id)
        )
