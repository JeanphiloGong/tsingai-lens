"""Business tools registered for the research Task runner."""

from agent.tools.workspace import (
    BrowseWorkspacePapersCapability,
    GetWorkspaceContextCapability,
)
from agent.tools.document import (
    InspectDocumentSourcesCapability,
    InspectTableCapability,
    ListDocumentProfilesCapability,
    ReadSourceCapability,
    SearchSourcesCapability,
)
from agent.capabilities.finding_review import (
    CurateFindingCapability,
    RecordFindingFeedbackCapability,
)
from agent.capabilities.finding_authoring import (
    CreateFindingDraftCapability,
    CreateFindingVersionCapability,
)
from agent.capabilities.paper_experiment_authoring import (
    CreatePaperExperimentRevisionCapability,
    ProposePaperExperimentDraftCapability,
)
from agent.capabilities.objective_proposal import (
    ProposeObjectiveDraftsCapability,
)
from agent.tools.objective import (
    CreateObjectiveCandidateCapability,
)
from agent.capabilities.objective_derivation import (
    DeriveObjectiveCapability,
)
from agent.capabilities.objective_analysis import (
    AssessObjectiveQualityCapability,
    ConfirmObjectiveCapability,
    InspectObjectiveAnalysisCapability,
    StartObjectiveAnalysisCapability,
)
from agent.capabilities.published_findings import (
    InspectPublishedFindingCapability,
    QueryPublishedFindingsCapability,
)
from agent.capabilities.research_process import (
    InspectResearchProcessCapability,
)
from agent.capabilities.research_process_start import (
    StartResearchProcessCapability,
)
from agent.capabilities.research_planning import (
    CreateResearchPlanCapability,
    InspectResearchPlansCapability,
    ProposeResearchPlanCapability,
    ReviseResearchPlanCapability,
)
from agent.capabilities.research_scope import (
    PreviewResearchScopeCapability,
)
from agent.tools.registry import CapabilityRegistry


registry = CapabilityRegistry(tuple(
    capability.spec
    for capability in (
        BrowseWorkspacePapersCapability(),
        GetWorkspaceContextCapability(),
        InspectDocumentSourcesCapability(),
        InspectTableCapability(),
        ListDocumentProfilesCapability(),
        ReadSourceCapability(),
        SearchSourcesCapability(),
        CurateFindingCapability(),
        RecordFindingFeedbackCapability(),
        CreateFindingDraftCapability(),
        CreateFindingVersionCapability(),
        CreatePaperExperimentRevisionCapability(),
        ProposePaperExperimentDraftCapability(),
        ProposeObjectiveDraftsCapability(),
        CreateObjectiveCandidateCapability(),
        DeriveObjectiveCapability(),
        AssessObjectiveQualityCapability(),
        ConfirmObjectiveCapability(),
        InspectObjectiveAnalysisCapability(),
        StartObjectiveAnalysisCapability(),
        InspectPublishedFindingCapability(),
        QueryPublishedFindingsCapability(),
        InspectResearchProcessCapability(),
        StartResearchProcessCapability(),
        CreateResearchPlanCapability(),
        InspectResearchPlansCapability(),
        ProposeResearchPlanCapability(),
        ReviseResearchPlanCapability(),
        PreviewResearchScopeCapability(),
    )
))
