from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)


def test_objective_discovery_stages_have_direct_owners() -> None:
    assert "build_collection_paper_skims" in PaperSkimService.__dict__
    assert "discover_candidates" in ObjectiveCandidateService.__dict__

    assert "_build_objective_candidate_inputs" not in ResearchObjectiveService.__dict__
    assert "_build_paper_skim_payload" not in ResearchObjectiveService.__dict__
    assert "_build_objective_discovery_skim" not in ResearchObjectiveService.__dict__
