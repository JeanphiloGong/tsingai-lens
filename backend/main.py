import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from application.auth import AuthSessionService, SessionNotFoundError
from application.chat import (
    CapabilityRegistry,
    ChatSessionService,
    ResearchAgentRunner,
    AgentRunLimits,
)
from application.chat.session_service import RepositoryModelCallObserver
from application.chat.capabilities import (
    AssessObjectiveQualityCapability,
    BrowseCollectionPapersCapability,
    ConfirmObjectiveCapability,
    CreateEvidenceDraftCapability,
    CreateFindingDraftCapability,
    CreateFindingVersionCapability,
    CreateEvidenceVersionCapability,
    CreateObjectiveCandidateCapability,
    CreateResearchPlanCapability,
    CurateFindingCapability,
    DeriveObjectiveCapability,
    GetCollectionContextCapability,
    InspectDocumentSourcesCapability,
    InspectTableCapability,
    ReadSourceCapability,
    InspectObjectiveAnalysisCapability,
    InspectPublishedFindingCapability,
    InspectResearchProcessCapability,
    InspectResearchPlansCapability,
    PreviewResearchScopeCapability,
    ProposeObjectiveDraftsCapability,
    ProposeResearchPlanCapability,
    PublishAgentObjectiveAnalysisCapability,
    QueryPublishedFindingsCapability,
    ReviseResearchPlanCapability,
    RecordFindingFeedbackCapability,
    SearchSourcesCapability,
    StartObjectiveAnalysisCapability,
    StartResearchProcessCapability,
)
from application.chat.model import RESEARCH_AGENT_PROMPT_VERSION
from application.core.document_profiles.service import (
    DocumentProfileService,
)
from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
)
from application.core.objectives.analysis.experiment_compatibility_projection import (
    ExperimentCompatibilityProjection,
)
from application.core.objectives.analysis.experiment_finding_publisher import (
    ExperimentFindingPublisher,
)
from application.core.objectives.analysis.experiment_query_service import (
    ExperimentQueryService,
)
from application.core.objectives.analysis_service import ObjectiveAnalysisService
from application.core.objectives.agent_analysis_service import (
    AgentObjectiveAnalysisService,
)
from application.core.objectives.evidence_authoring_service import (
    EvidenceAuthoringService,
)
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.objective_discovery_service import (
    ObjectiveDiscoveryService,
)
from application.core.objectives.objective_authoring_service import (
    ObjectiveAuthoringService,
)
from application.core.objectives.objective_input_service import ObjectiveInputService
from application.core.objectives.paper_research_map_service import PaperResearchMapService
from application.core.objectives.objective_analysis_service import (
    ObjectiveExperimentAnalysisService,
)
from application.pipeline import PipelineRunService
from application.evaluation import (
    FindingFeedbackService,
)
from application.feedback import FeedbackAnalysisHandler, FeedbackAnalysisWorker
from application.feedback.dataset_snapshot_service import DatasetSnapshotService
from application.feedback.feedback_case_service import FeedbackCaseService
from application.goal.brief_service import GoalService
from application.goal.experiment_plan_service import ExperimentPlanService
from application.source.collection_service import CollectionService
from application.source.document_preparation_service import DocumentPreparationService
from application.source.document_markdown_service import DocumentMarkdownService
from application.source.reference_workflow_service import SourceReferenceWorkflowService
from application.source.source_archive_service import SourceArchiveService
from application.source.source_import_service import SourceImportService
from config import DATA_DIR
from controllers import auth
from controllers.chat import sessions as chat_sessions
from controllers import feedback_cases
from controllers.feedback import datasets as feedback_datasets
from controllers.core import (
    documents,
    finding_review,
    paper_experiments,
    research_objectives,
)
from controllers.goal import experiment_plans
from controllers.goal import intake as goals
from controllers.source import collections, pipeline_runs, references
from application.repositories.finding_review_repository import FindingReviewRepository
from application.repositories.paper_map_repository import PaperMapRepository
from application.repositories.document_profile_repository import (
    DocumentProfileRepository,
)
from application.repositories.source_artifact_repository import SourceArtifactRepository
from application.repositories.experiment_plan_repository import ExperimentPlanRepository
from application.repositories.chat_repository import ChatRepository
from application.repositories.analysis_job_repository import AnalysisJobRepository
from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.repositories.dataset_snapshot_repository import DatasetSnapshotRepository
from application.repositories.objective_repository import ObjectiveRepository
from application.repositories.paper_experiment_repository import PaperExperimentRepository
from application.repositories.objective_experiment_selection_repository import (
    ObjectiveExperimentSelectionRepository,
)
from application.repositories.comparison_group_repository import ComparisonGroupRepository
from application.repositories.experiment_finding_repository import ExperimentFindingRepository
from infra.llm.chat_model import OpenAIChatModel
from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.analysis_job_repository import (
    PostgresAnalysisJobRepository,
)
from infra.persistence.postgres.feedback_case_repository import (
    PostgresFeedbackCaseRepository,
)
from infra.persistence.postgres.dataset_snapshot_repository import (
    PostgresDatasetSnapshotRepository,
)
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from infra.persistence.postgres.document_profile_repository import (
    PostgresDocumentProfileRepository,
)
from infra.persistence.postgres.objective_repository import (
    PostgresObjectiveRepository,
)
from infra.persistence.postgres.experiment_plan_repository import (
    PostgresExperimentPlanRepository,
)
from infra.persistence.postgres.paper_map_repository import PostgresPaperMapRepository
from infra.persistence.postgres.paper_experiment_repository import (
    PostgresPaperExperimentRepository,
)
from infra.persistence.postgres.objective_experiment_selection_repository import (
    PostgresObjectiveExperimentSelectionRepository,
)
from infra.persistence.postgres.comparison_group_repository import (
    PostgresComparisonGroupRepository,
)
from infra.persistence.postgres.experiment_finding_repository import (
    PostgresExperimentFindingRepository,
)
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from infra.persistence.postgres.pipeline_run_repository import (
    PostgresPipelineRunRepository,
)
from utils.logger import (
    REQUEST_ID_HEADER,
    bind_request_id,
    bind_user_id,
    clear_request_id,
    clear_user_id,
    resolve_request_id,
    setup_logger,
)

logger = setup_logger("lens")

PUBLIC_API_PREFIX = "/api"
PUBLIC_API_V1_PREFIX = f"{PUBLIC_API_PREFIX}/v1"
_AUTH_EXEMPT_PATHS = {
    f"{PUBLIC_API_V1_PREFIX}/auth/login",
    f"{PUBLIC_API_V1_PREFIX}/auth/logout",
}


def _parse_cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _parse_agent_run_limits() -> AgentRunLimits:
    from math import isfinite

    defaults = AgentRunLimits()
    values = {}
    for field_name, env_name in {
        "max_elapsed_seconds": "LENS_AGENT_MAX_TURN_SECONDS",
        "max_tool_calls": "LENS_AGENT_MAX_TOOL_CALLS",
        "max_model_tokens": "LENS_AGENT_MAX_MODEL_TOKENS",
        "max_consecutive_no_progress": "LENS_AGENT_NO_PROGRESS_LIMIT",
        "emergency_max_model_cycles": "LENS_AGENT_EMERGENCY_MAX_CYCLES",
        "max_request_seconds": "LENS_AGENT_MAX_REQUEST_SECONDS",
        "max_context_tokens": "LENS_AGENT_CONTEXT_TOKENS",
        "max_parallel_reads": "LENS_AGENT_MAX_PARALLEL_READS",
        "max_model_output_tokens": "LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS",
        "max_finalization_seconds": "LENS_AGENT_MAX_FINALIZATION_SECONDS",
        "max_finalization_output_tokens": "LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS",
    }.items():
        default = getattr(defaults, field_name)
        try:
            raw = os.getenv(env_name, "").strip()
            if default is None and (not raw or raw == "0"):
                values[field_name] = None
                continue
            parser = float if field_name.endswith("_seconds") else int
            value = parser(raw) if raw else default
            if value <= 0 or not isfinite(value):
                raise ValueError("non-positive or non-finite limit")
        except (ValueError, OverflowError):
            logger.warning("Invalid %s; using default=%s", env_name, default)
            value = default
        values[field_name] = value
    return AgentRunLimits(**values)


AppLifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass(frozen=True)
class ApplicationOverrides:
    """Dependencies supplied by tests or alternate application hosts."""

    auth_session_service: AuthSessionService | None = None
    collection_service: CollectionService | None = None
    pipeline_run_service: PipelineRunService | None = None
    source_artifact_repository: SourceArtifactRepository | None = None
    document_profile_repository: DocumentProfileRepository | None = None
    paper_map_repository: PaperMapRepository | None = None
    objective_repository: ObjectiveRepository | None = None
    finding_review_repository: FindingReviewRepository | None = None
    experiment_plan_repository: ExperimentPlanRepository | None = None
    chat_repository: ChatRepository | None = None
    chat_session_service: ChatSessionService | None = None
    analysis_job_repository: AnalysisJobRepository | None = None
    feedback_case_repository: FeedbackCaseRepository | None = None
    feedback_case_service: FeedbackCaseService | None = None
    feedback_analysis_worker: FeedbackAnalysisWorker | None = None
    dataset_snapshot_repository: DatasetSnapshotRepository | None = None
    dataset_snapshot_service: DatasetSnapshotService | None = None
    paper_experiment_repository: PaperExperimentRepository | None = None
    objective_experiment_selection_repository: (
        ObjectiveExperimentSelectionRepository | None
    ) = None
    comparison_group_repository: ComparisonGroupRepository | None = None
    experiment_finding_repository: ExperimentFindingRepository | None = None
    experiment_analysis_writer: ExperimentAnalysisWriter | None = None
    experiment_compatibility_projection: ExperimentCompatibilityProjection | None = None

    def requires_database(self) -> bool:
        required_dependencies = (
            self.auth_session_service,
            self.collection_service,
            self.pipeline_run_service,
            self.source_artifact_repository,
            self.document_profile_repository,
            self.paper_map_repository,
            self.objective_repository,
            self.finding_review_repository,
            self.experiment_plan_repository,
        )
        return any(value is None for value in required_dependencies) or (
            self.chat_session_service is None and self.chat_repository is None
        )


@dataclass(frozen=True)
class ApplicationRuntime:
    """Resolved services and resources owned by one FastAPI app instance."""

    database_engine: AsyncEngine | None
    auth_session_service: AuthSessionService
    collection_service: CollectionService
    source_archive_service: SourceArchiveService
    source_import_service: SourceImportService
    pipeline_run_service: PipelineRunService
    document_profile_repository: DocumentProfileRepository
    paper_map_repository: PaperMapRepository
    objective_repository: ObjectiveRepository
    finding_review_repository: FindingReviewRepository
    finding_feedback_service: FindingFeedbackService
    finding_authoring_service: FindingAuthoringService
    evidence_authoring_service: EvidenceAuthoringService
    document_profile_service: DocumentProfileService
    document_preparation_service: DocumentPreparationService
    document_markdown_service: DocumentMarkdownService
    reference_workflow_service: SourceReferenceWorkflowService
    experiment_analysis_service: ObjectiveExperimentAnalysisService
    objective_discovery_service: ObjectiveDiscoveryService
    objective_authoring_service: ObjectiveAuthoringService
    goal_service: GoalService
    chat_session_service: ChatSessionService
    analysis_job_repository: AnalysisJobRepository | None
    feedback_case_repository: FeedbackCaseRepository | None
    feedback_case_service: FeedbackCaseService | None
    feedback_analysis_worker: FeedbackAnalysisWorker | None
    dataset_snapshot_repository: DatasetSnapshotRepository | None
    dataset_snapshot_service: DatasetSnapshotService | None
    experiment_plan_service: ExperimentPlanService
    objective_analysis_service: ObjectiveAnalysisService
    experiment_analysis_writer: ExperimentAnalysisWriter | None
    experiment_compatibility_projection: ExperimentCompatibilityProjection | None
    experiment_query_service: ExperimentQueryService | None

    async def close(self) -> None:
        if self.database_engine is not None:
            await self.database_engine.dispose()


async def build_application_runtime(
    overrides: ApplicationOverrides,
) -> ApplicationRuntime:
    """Compose the explicit repository and application-service dependency graph."""

    database_engine: AsyncEngine | None = None
    try:
        # Resolve persistence dependencies before composing their consumers.
        session_factory = None
        if overrides.requires_database():
            database_engine = build_database_engine(DatabaseSettings())
            session_factory = build_session_factory(database_engine)

        if overrides.auth_session_service is None:
            auth_session_service = AuthSessionService(
                PostgresAuthRepository(session_factory)
            )
        else:
            auth_session_service = overrides.auth_session_service
        await auth_session_service.ensure_bootstrap_user()

        collection_service = overrides.collection_service or CollectionService(
            repository=PostgresCollectionRepository(session_factory),
            workspace=FileCollectionWorkspace(),
        )
        source_archive_service = SourceArchiveService(
            repository=collection_service.repository,
            object_store=collection_service.object_store,
        )
        source_import_service = SourceImportService(
            repository=collection_service.repository,
            object_store=collection_service.object_store,
        )
        pipeline_run_service = overrides.pipeline_run_service or PipelineRunService(
            PostgresPipelineRunRepository(session_factory)
        )
        source_artifact_repository = (
            overrides.source_artifact_repository
            or PostgresSourceArtifactRepository(session_factory)
        )
        document_profile_repository = (
            overrides.document_profile_repository
            or PostgresDocumentProfileRepository(session_factory)
        )
        paper_map_repository = (
            overrides.paper_map_repository
            or PostgresPaperMapRepository(session_factory)
        )
        objective_repository = (
            overrides.objective_repository
            or PostgresObjectiveRepository(session_factory)
        )
        paper_experiment_repository = overrides.paper_experiment_repository
        objective_experiment_selection_repository = (
            overrides.objective_experiment_selection_repository
        )
        comparison_group_repository = overrides.comparison_group_repository
        experiment_finding_repository = overrides.experiment_finding_repository
        if session_factory is not None:
            paper_experiment_repository = (
                paper_experiment_repository
                or PostgresPaperExperimentRepository(session_factory)
            )
            objective_experiment_selection_repository = (
                objective_experiment_selection_repository
                or PostgresObjectiveExperimentSelectionRepository(session_factory)
            )
            comparison_group_repository = (
                comparison_group_repository
                or PostgresComparisonGroupRepository(session_factory)
            )
            experiment_finding_repository = (
                experiment_finding_repository
                or PostgresExperimentFindingRepository(session_factory)
            )

        experiment_analysis_writer = overrides.experiment_analysis_writer
        if (
            experiment_analysis_writer is None
            and paper_experiment_repository is not None
            and objective_experiment_selection_repository is not None
            and comparison_group_repository is not None
            and experiment_finding_repository is not None
        ):
            experiment_analysis_writer = ExperimentAnalysisWriter(
                paper_experiment_repository=paper_experiment_repository,
                selection_repository=objective_experiment_selection_repository,
                group_repository=comparison_group_repository,
                finding_publisher=ExperimentFindingPublisher(
                    selection_repository=objective_experiment_selection_repository,
                    group_repository=comparison_group_repository,
                    finding_repository=experiment_finding_repository,
                ),
                finding_repository=experiment_finding_repository,
            )
        experiment_compatibility_projection = overrides.experiment_compatibility_projection
        if (
            experiment_compatibility_projection is None
            and paper_experiment_repository is not None
            and objective_experiment_selection_repository is not None
            and comparison_group_repository is not None
            and experiment_finding_repository is not None
        ):
            experiment_compatibility_projection = ExperimentCompatibilityProjection(
                paper_experiment_repository=paper_experiment_repository,
                selection_repository=objective_experiment_selection_repository,
                group_repository=comparison_group_repository,
                finding_repository=experiment_finding_repository,
                objective_repository=objective_repository,
            )
        if session_factory is not None and (
            experiment_analysis_writer is None
            or experiment_compatibility_projection is None
        ):
            raise RuntimeError(
                "database-backed runtime requires the PaperExperiment writer "
                "and query projection"
            )
        finding_review_repository = (
            overrides.finding_review_repository
            or PostgresFindingReviewRepository(session_factory)
        )
        experiment_plan_repository = (
            overrides.experiment_plan_repository
            or PostgresExperimentPlanRepository(session_factory)
        )
        chat_repository = overrides.chat_repository or (
            PostgresChatRepository(session_factory)
            if overrides.chat_session_service is None
            else None
        )
        analysis_job_repository = overrides.analysis_job_repository
        feedback_case_repository = overrides.feedback_case_repository
        dataset_snapshot_repository = overrides.dataset_snapshot_repository
        if session_factory is not None:
            analysis_job_repository = (
                analysis_job_repository
                or PostgresAnalysisJobRepository(session_factory)
            )
            feedback_case_repository = (
                feedback_case_repository
                or PostgresFeedbackCaseRepository(session_factory)
            )
            dataset_snapshot_repository = (
                dataset_snapshot_repository
                or PostgresDatasetSnapshotRepository(session_factory)
            )

        feedback_analysis_worker = overrides.feedback_analysis_worker
        if (
            feedback_analysis_worker is None
            and analysis_job_repository is not None
            and feedback_case_repository is not None
            and chat_repository is not None
        ):
            feedback_analysis_worker = FeedbackAnalysisWorker(
                job_repository=analysis_job_repository,
                case_repository=feedback_case_repository,
                handler=FeedbackAnalysisHandler(chat_repository=chat_repository),
            )

        feedback_case_service = overrides.feedback_case_service
        if (
            feedback_case_service is None
            and feedback_case_repository is not None
            and chat_repository is not None
        ):
            feedback_case_service = FeedbackCaseService(
                case_repository=feedback_case_repository,
                chat_repository=chat_repository,
                collection_service=collection_service,
            )

        dataset_snapshot_service = overrides.dataset_snapshot_service
        if (
            dataset_snapshot_service is None
            and dataset_snapshot_repository is not None
            and feedback_case_repository is not None
            and chat_repository is not None
        ):
            dataset_snapshot_service = DatasetSnapshotService(
                repository=dataset_snapshot_repository,
                case_repository=feedback_case_repository,
                chat_repository=chat_repository,
                collection_service=collection_service,
            )

        # Services share the resolved objects above; no service locator is used.
        document_profile_service = DocumentProfileService(
            collection_service=collection_service,
            source_artifact_repository=source_artifact_repository,
            document_profile_repository=document_profile_repository,
        )
        paper_map_service = PaperResearchMapService()
        objective_candidate_service = ObjectiveCandidateService()
        objective_input_service = ObjectiveInputService(
            collection_service=collection_service,
            source_artifact_repository=source_artifact_repository,
            paper_map_repository=paper_map_repository,
            document_profile_service=document_profile_service,
            paper_map_service=paper_map_service,
        )
        objective_discovery_service = ObjectiveDiscoveryService(
            objective_input_service=objective_input_service,
            objective_candidate_service=objective_candidate_service,
            objective_repository=objective_repository,
            pipeline_run_service=pipeline_run_service,
        )
        objective_authoring_service = ObjectiveAuthoringService(
            collection_service=collection_service,
            objective_repository=objective_repository,
            experiment_projection=experiment_compatibility_projection,
        )
        document_preparation_service = DocumentPreparationService(
            collection_service=collection_service,
            pipeline_run_service=pipeline_run_service,
            source_artifact_repository=source_artifact_repository,
            document_profile_service=document_profile_service,
        )
        finding_feedback_service = FindingFeedbackService(
            review_repository=finding_review_repository,
            objective_repository=objective_repository,
            experiment_projection=experiment_compatibility_projection,
        )
        experiment_plan_service = ExperimentPlanService(
            repository=experiment_plan_repository,
            finding_feedback_service=finding_feedback_service,
        )
        finding_authoring_service = FindingAuthoringService(
            collection_service=collection_service,
            objective_repository=objective_repository,
        )
        evidence_authoring_service = EvidenceAuthoringService(
            collection_service=collection_service,
            objective_repository=objective_repository,
            source_artifact_repository=source_artifact_repository,
        )
        agent_analysis_service = AgentObjectiveAnalysisService(
            collection_service=collection_service,
            objective_repository=objective_repository,
            source_artifact_repository=source_artifact_repository,
        )
        experiment_analysis_service = ObjectiveExperimentAnalysisService(
            collection_service=collection_service,
            paper_map_repository=paper_map_repository,
            objective_repository=objective_repository,
            objective_input_service=objective_input_service,
        )
        document_markdown_service = DocumentMarkdownService(
            collection_service=collection_service,
            source_artifact_repository=source_artifact_repository,
        )
        reference_workflow_service = SourceReferenceWorkflowService(
            source_artifact_repository=source_artifact_repository,
        )
        goal_service = GoalService(collection_service)
        objective_analysis_service = ObjectiveAnalysisService(
            objective_repository=objective_repository,
            experiment_analysis_service=experiment_analysis_service,
            objective_input_service=objective_input_service,
            document_profile_service=document_profile_service,
            experiment_analysis_writer=experiment_analysis_writer,
            experiment_compatibility_projection=experiment_compatibility_projection,
        )
        experiment_query_service = None
        if (
            paper_experiment_repository is not None
            and objective_experiment_selection_repository is not None
            and comparison_group_repository is not None
            and experiment_finding_repository is not None
        ):
            experiment_query_service = ExperimentQueryService(
                paper_experiment_repository=paper_experiment_repository,
                selection_repository=objective_experiment_selection_repository,
                group_repository=comparison_group_repository,
                finding_repository=experiment_finding_repository,
            )

        if overrides.chat_session_service is None:
            chat_model = OpenAIChatModel()
            chat_session_service = ChatSessionService(
                collection_service=collection_service,
                source_artifact_repository=source_artifact_repository,
                repository=chat_repository,
                analysis_job_repository=analysis_job_repository,
                model_call_observer=(
                    RepositoryModelCallObserver(chat_repository)
                    if chat_repository is not None
                    else None
                ),
                runner=ResearchAgentRunner(
                    model=chat_model,
                    limits=_parse_agent_run_limits(),
                    capabilities=CapabilityRegistry(
                        (
                            GetCollectionContextCapability(
                                collection_service=collection_service,
                                objective_repository=objective_repository,
                            ),
                            BrowseCollectionPapersCapability(
                                collection_service=collection_service,
                                document_profile_repository=document_profile_repository,
                                paper_map_repository=paper_map_repository,
                                source_artifact_repository=source_artifact_repository,
                            ),
                            InspectDocumentSourcesCapability(
                                collection_service=collection_service,
                                source_artifact_repository=source_artifact_repository,
                            ),
                            SearchSourcesCapability(
                                collection_service=collection_service,
                                source_artifact_repository=source_artifact_repository,
                            ),
                            InspectTableCapability(
                                collection_service=collection_service,
                                source_artifact_repository=source_artifact_repository,
                            ),
                            ReadSourceCapability(
                                collection_service=collection_service,
                                source_artifact_repository=source_artifact_repository,
                            ),
                            InspectResearchProcessCapability(
                                collection_service=collection_service,
                                pipeline_run_service=pipeline_run_service,
                            ),
                            StartResearchProcessCapability(
                                collection_service=collection_service,
                                document_preparation_service=(
                                    document_preparation_service
                                ),
                            ),
                            QueryPublishedFindingsCapability(
                                collection_service=collection_service,
                                objective_repository=objective_repository,
                                objective_analysis_service=objective_analysis_service,
                            ),
                            InspectPublishedFindingCapability(
                                collection_service=collection_service,
                                objective_analysis_service=objective_analysis_service,
                                finding_feedback_service=finding_feedback_service,
                            ),
                            RecordFindingFeedbackCapability(
                                collection_service=collection_service,
                                finding_feedback_service=finding_feedback_service,
                            ),
                            CurateFindingCapability(
                                collection_service=collection_service,
                                finding_feedback_service=finding_feedback_service,
                            ),
                            CreateFindingDraftCapability(),
                            CreateFindingVersionCapability(
                                finding_authoring_service=finding_authoring_service,
                            ),
                            CreateEvidenceDraftCapability(
                                collection_service=collection_service,
                                source_artifact_repository=source_artifact_repository,
                            ),
                            CreateEvidenceVersionCapability(
                                evidence_authoring_service=evidence_authoring_service,
                            ),
                            PublishAgentObjectiveAnalysisCapability(
                                agent_analysis_service=agent_analysis_service,
                                model_name=chat_model.model,
                                prompt_version=RESEARCH_AGENT_PROMPT_VERSION,
                            ),
                            ProposeObjectiveDraftsCapability(
                                collection_service=collection_service,
                                objective_repository=objective_repository,
                                paper_map_repository=paper_map_repository,
                            ),
                            PreviewResearchScopeCapability(
                                collection_service=collection_service,
                                paper_map_repository=paper_map_repository,
                            ),
                            CreateObjectiveCandidateCapability(
                                objective_authoring_service=objective_authoring_service,
                            ),
                            ConfirmObjectiveCapability(
                                objective_authoring_service=objective_authoring_service,
                            ),
                            StartObjectiveAnalysisCapability(
                                collection_service=collection_service,
                                objective_repository=objective_repository,
                                objective_analysis_service=objective_analysis_service,
                            ),
                            InspectObjectiveAnalysisCapability(
                                collection_service=collection_service,
                                objective_analysis_service=objective_analysis_service,
                            ),
                            AssessObjectiveQualityCapability(
                                collection_service=collection_service,
                                objective_analysis_service=objective_analysis_service,
                            ),
                            DeriveObjectiveCapability(
                                collection_service=collection_service,
                                objective_analysis_service=objective_analysis_service,
                            ),
                            ProposeResearchPlanCapability(
                                collection_service=collection_service,
                                finding_feedback_service=finding_feedback_service,
                            ),
                            CreateResearchPlanCapability(
                                collection_service=collection_service,
                                finding_feedback_service=finding_feedback_service,
                                experiment_plan_service=experiment_plan_service,
                            ),
                            InspectResearchPlansCapability(
                                collection_service=collection_service,
                                experiment_plan_service=experiment_plan_service,
                            ),
                            ReviseResearchPlanCapability(
                                collection_service=collection_service,
                                finding_feedback_service=finding_feedback_service,
                                experiment_plan_service=experiment_plan_service,
                            ),
                        )
                    ),
                ),
            )
        else:
            chat_session_service = overrides.chat_session_service

        return ApplicationRuntime(
            database_engine=database_engine,
            auth_session_service=auth_session_service,
            collection_service=collection_service,
            source_archive_service=source_archive_service,
            source_import_service=source_import_service,
            pipeline_run_service=pipeline_run_service,
            document_profile_repository=document_profile_repository,
            paper_map_repository=paper_map_repository,
            objective_repository=objective_repository,
            finding_review_repository=finding_review_repository,
            finding_feedback_service=finding_feedback_service,
            finding_authoring_service=finding_authoring_service,
            evidence_authoring_service=evidence_authoring_service,
            document_profile_service=document_profile_service,
            document_preparation_service=document_preparation_service,
            document_markdown_service=document_markdown_service,
            reference_workflow_service=reference_workflow_service,
            experiment_analysis_service=experiment_analysis_service,
            objective_discovery_service=objective_discovery_service,
            objective_authoring_service=objective_authoring_service,
            goal_service=goal_service,
            chat_session_service=chat_session_service,
            analysis_job_repository=analysis_job_repository,
            feedback_case_repository=feedback_case_repository,
            feedback_case_service=feedback_case_service,
            feedback_analysis_worker=feedback_analysis_worker,
            dataset_snapshot_repository=dataset_snapshot_repository,
            dataset_snapshot_service=dataset_snapshot_service,
            experiment_plan_service=experiment_plan_service,
            objective_analysis_service=objective_analysis_service,
            experiment_analysis_writer=experiment_analysis_writer,
            experiment_compatibility_projection=experiment_compatibility_projection,
            experiment_query_service=experiment_query_service,
        )
    except BaseException:
        if database_engine is not None:
            await database_engine.dispose()
        raise


def install_application_runtime(
    application: FastAPI,
    runtime: ApplicationRuntime,
) -> None:
    """Expose resolved controller dependencies through FastAPI state."""

    application.state.auth_session_service = runtime.auth_session_service
    application.state.collection_service = runtime.collection_service
    application.state.source_archive_service = runtime.source_archive_service
    application.state.source_import_service = runtime.source_import_service
    application.state.pipeline_run_service = runtime.pipeline_run_service
    application.state.document_profile_repository = runtime.document_profile_repository
    application.state.paper_map_repository = runtime.paper_map_repository
    application.state.objective_repository = runtime.objective_repository
    application.state.finding_review_repository = runtime.finding_review_repository
    application.state.finding_feedback_service = runtime.finding_feedback_service
    application.state.finding_authoring_service = runtime.finding_authoring_service
    application.state.evidence_authoring_service = runtime.evidence_authoring_service
    application.state.document_profile_service = runtime.document_profile_service
    application.state.document_preparation_service = runtime.document_preparation_service
    application.state.document_markdown_service = runtime.document_markdown_service
    application.state.reference_workflow_service = runtime.reference_workflow_service
    application.state.experiment_analysis_service = runtime.experiment_analysis_service
    application.state.objective_discovery_service = runtime.objective_discovery_service
    application.state.objective_authoring_service = runtime.objective_authoring_service
    application.state.goal_service = runtime.goal_service
    application.state.chat_session_service = runtime.chat_session_service
    application.state.analysis_job_repository = runtime.analysis_job_repository
    application.state.feedback_case_repository = runtime.feedback_case_repository
    application.state.feedback_case_service = runtime.feedback_case_service
    application.state.feedback_analysis_worker = runtime.feedback_analysis_worker
    application.state.dataset_snapshot_repository = runtime.dataset_snapshot_repository
    application.state.dataset_snapshot_service = runtime.dataset_snapshot_service
    application.state.experiment_plan_service = runtime.experiment_plan_service
    application.state.objective_analysis_service = runtime.objective_analysis_service
    application.state.experiment_analysis_writer = runtime.experiment_analysis_writer
    application.state.experiment_compatibility_projection = (
        runtime.experiment_compatibility_projection
    )
    application.state.experiment_query_service = runtime.experiment_query_service


def create_lifespan(overrides: ApplicationOverrides) -> AppLifespan:
    """Create the FastAPI lifecycle for one set of dependency overrides."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime = await build_application_runtime(overrides)
        try:
            install_application_runtime(application, runtime)
            await runtime.document_preparation_service.recover_interrupted_runs()
            await runtime.objective_discovery_service.recover_interrupted_discoveries()
            await runtime.objective_analysis_service.recover_interrupted_analyses()
            yield
        finally:
            await runtime.close()

    return lifespan


def configure_middleware(app: FastAPI) -> None:
    """Install CORS, request-correlation, and authentication middleware."""

    cors_allowed_origins = _parse_cors_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        # Same-origin deployment does not require wildcard cross-origin access.
        # Configure explicit origins via `CORS_ALLOWED_ORIGINS` when needed.
        allow_origins=cors_allowed_origins,
        allow_credentials=bool(cors_allowed_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        incoming_request_id = request.headers.get(REQUEST_ID_HEADER)
        request_id, reused_incoming_id = resolve_request_id(incoming_request_id)
        token = bind_request_id(request_id)
        request.state.request_id = request_id
        start_time = perf_counter()
        logger.info(
            "HTTP request started method=%s path=%s",
            request.method,
            request.url.path,
        )
        if incoming_request_id and not reused_incoming_id:
            logger.warning(
                "Invalid incoming request id replaced path=%s original_request_id=%r effective_request_id=%s",
                request.url.path,
                incoming_request_id,
                request_id,
            )

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "HTTP request failed method=%s path=%s",
                request.method,
                request.url.path,
            )
            raise
        else:
            duration_ms = (perf_counter() - start_time) * 1000
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "HTTP request finished method=%s path=%s status_code=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        finally:
            clear_request_id(token)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if not _requires_auth(request):
            return await call_next(request)

        try:
            user = await request.app.state.auth_session_service.resolve_session(
                request.cookies.get("lens_session")
            )
        except SessionNotFoundError:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "code": "authentication_required",
                        "message": "Authentication is required.",
                    }
                },
            )

        user_token = bind_user_id(str(user["user_id"]))
        try:
            request.state.current_user = user
            collection_id = _extract_collection_id(request.url.path)
            if collection_id and not await _user_owns_collection(
                request.app.state.collection_service,
                collection_id,
                user["user_id"],
            ):
                return JSONResponse(
                    status_code=404,
                    content={
                        "detail": {
                            "code": "collection_not_found",
                            "message": f"collection not found: {collection_id}",
                            "collection_id": collection_id,
                        }
                    },
                )
            return await call_next(request)
        finally:
            clear_user_id(user_token)


def register_routes(app: FastAPI) -> None:
    """Register the public Lens API routers."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.include_router(auth.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(collections.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(references.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(goals.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(experiment_plans.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(chat_sessions.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(feedback_cases.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(feedback_datasets.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(pipeline_runs.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(documents.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(research_objectives.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(finding_review.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(paper_experiments.router, prefix=PUBLIC_API_V1_PREFIX)


def create_app(
    *,
    auth_session_service: AuthSessionService | None = None,
    collection_service: CollectionService | None = None,
    pipeline_run_service: PipelineRunService | None = None,
    source_artifact_repository: SourceArtifactRepository | None = None,
    document_profile_repository: DocumentProfileRepository | None = None,
    paper_map_repository: PaperMapRepository | None = None,
    objective_repository: ObjectiveRepository | None = None,
    finding_review_repository: FindingReviewRepository | None = None,
    experiment_plan_repository: ExperimentPlanRepository | None = None,
    chat_repository: ChatRepository | None = None,
    chat_session_service: ChatSessionService | None = None,
    analysis_job_repository: AnalysisJobRepository | None = None,
    feedback_case_repository: FeedbackCaseRepository | None = None,
    feedback_case_service: FeedbackCaseService | None = None,
    feedback_analysis_worker: FeedbackAnalysisWorker | None = None,
    dataset_snapshot_repository: DatasetSnapshotRepository | None = None,
    dataset_snapshot_service: DatasetSnapshotService | None = None,
    paper_experiment_repository: PaperExperimentRepository | None = None,
    objective_experiment_selection_repository: (
        ObjectiveExperimentSelectionRepository | None
    ) = None,
    comparison_group_repository: ComparisonGroupRepository | None = None,
    experiment_finding_repository: ExperimentFindingRepository | None = None,
    experiment_analysis_writer: ExperimentAnalysisWriter | None = None,
    experiment_compatibility_projection: ExperimentCompatibilityProjection | None = None,
) -> FastAPI:
    overrides = ApplicationOverrides(
        auth_session_service=auth_session_service,
        collection_service=collection_service,
        pipeline_run_service=pipeline_run_service,
        source_artifact_repository=source_artifact_repository,
        document_profile_repository=document_profile_repository,
        paper_map_repository=paper_map_repository,
        objective_repository=objective_repository,
        finding_review_repository=finding_review_repository,
        experiment_plan_repository=experiment_plan_repository,
        chat_repository=chat_repository,
        chat_session_service=chat_session_service,
        analysis_job_repository=analysis_job_repository,
        feedback_case_repository=feedback_case_repository,
        feedback_case_service=feedback_case_service,
        feedback_analysis_worker=feedback_analysis_worker,
        dataset_snapshot_repository=dataset_snapshot_repository,
        dataset_snapshot_service=dataset_snapshot_service,
        paper_experiment_repository=paper_experiment_repository,
        objective_experiment_selection_repository=objective_experiment_selection_repository,
        comparison_group_repository=comparison_group_repository,
        experiment_finding_repository=experiment_finding_repository,
        experiment_analysis_writer=experiment_analysis_writer,
        experiment_compatibility_projection=experiment_compatibility_projection,
    )
    app = FastAPI(
        title="TsingAI-Lens API",
        version="0.12.23",
        docs_url=f"{PUBLIC_API_PREFIX}/docs",
        redoc_url=f"{PUBLIC_API_PREFIX}/redoc",
        openapi_url=f"{PUBLIC_API_PREFIX}/openapi.json",
        lifespan=create_lifespan(overrides),
    )
    if auth_session_service is not None:
        app.state.auth_session_service = auth_session_service
    configure_middleware(app)
    register_routes(app)
    return app


def _requires_auth(request: Request) -> bool:
    path = request.url.path
    if not path.startswith(f"{PUBLIC_API_V1_PREFIX}/"):
        return False
    return path not in _AUTH_EXEMPT_PATHS


def _extract_collection_id(path: str) -> str | None:
    prefix = f"{PUBLIC_API_V1_PREFIX}/collections/"
    if not path.startswith(prefix):
        return None
    remainder = path[len(prefix) :]
    collection_id = remainder.split("/", 1)[0].strip()
    return collection_id or None


async def _user_owns_collection(
    collection_service: CollectionService,
    collection_id: str,
    user_id: str,
) -> bool:
    try:
        await collection_service.get_collection_for_user(collection_id, user_id)
    except FileNotFoundError:
        return False
    return True


app = create_app()
