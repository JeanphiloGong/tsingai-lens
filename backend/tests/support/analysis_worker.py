"""Explicit worker driver for deterministic analysis business fixtures."""

from datetime import timedelta
from application.core.objectives import analysis_service
from application.core.objectives.analysis.source_screening import (
    ObjectiveSourceScreener,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    PaperExperimentExtractor,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
)


class AnalysisWorkerFixture:
    def __init__(self, *, client):
        self.client = client

    async def execute_queued_analysis(
        self, collection_id, objective_id, analysis_version
    ):
        job = await analysis_service.ObjectiveRepo.claim_next_objective_analysis_job(
            worker_id="test-worker", lease_duration=timedelta(seconds=300)
        )
        if job is None:
            return await analysis_service.get_analysis_state(
                collection_id, objective_id, user_id="user-1"
            )
        assert job.analysis.key == (collection_id, objective_id, analysis_version)
        return await analysis_service.execute_objective_analysis_job(
            job,
            response_client=self.client,
            source_screener=ObjectiveSourceScreener(self.client),
            paper_map_extractor=PaperResearchMapExtractor(self.client),
            paper_experiment_extractor=PaperExperimentExtractor(self.client),
        )

    async def close(self):
        self.client.client.close()
