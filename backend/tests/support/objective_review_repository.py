from __future__ import annotations

from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback


class InMemoryObjectiveReviewRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.feedback: dict[str, ResearchUnderstandingFeedback] = {}
        self.curations: dict[str, ResearchUnderstandingCuration] = {}

    def upsert_feedback(self, feedback: ResearchUnderstandingFeedback):
        self.feedback[feedback.feedback_id] = feedback
        return feedback

    def list_feedback(self, collection_id, objective_id=None, finding_id=None, claim_id=None):
        return tuple(
            item
            for item in self.feedback.values()
            if item.collection_id == collection_id
            and (objective_id is None or item.objective_id == objective_id)
            and (finding_id is None or item.finding_id == finding_id)
            and (claim_id is None or item.claim_id == claim_id)
        )

    def upsert_curation(self, curation: ResearchUnderstandingCuration):
        self.curations[curation.curation_id] = curation
        return curation

    def list_curations(self, collection_id, objective_id=None, finding_id=None, claim_id=None):
        return tuple(
            item
            for item in self.curations.values()
            if item.collection_id == collection_id
            and (objective_id is None or item.objective_id == objective_id)
            and (finding_id is None or item.finding_id == finding_id)
            and (claim_id is None or item.claim_id == claim_id)
        )
