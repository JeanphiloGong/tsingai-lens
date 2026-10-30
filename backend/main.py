import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter

from application.auth import session_service as auth_session_service
from application.chat import AgentRunLimits, CapabilityRegistry, ResearchAgentRunner
from application.chat.capabilities import (
    AssessObjectiveQualityCapability,
    BrowseCollectionPapersCapability,
    ConfirmObjectiveCapability,
    CreateFindingDraftCapability,
    CreateFindingVersionCapability,
    CreateObjectiveCandidateCapability,
    CreatePaperExperimentRevisionCapability,
    CreateResearchPlanCapability,
    CurateFindingCapability,
    DeriveObjectiveCapability,
    GetCollectionContextCapability,
    InspectDocumentSourcesCapability,
    InspectObjectiveAnalysisCapability,
    InspectPublishedFindingCapability,
    InspectResearchPlansCapability,
    InspectResearchProcessCapability,
    InspectTableCapability,
    PreviewResearchScopeCapability,
    ProposeObjectiveDraftsCapability,
    ProposePaperExperimentDraftCapability,
    ProposeResearchPlanCapability,
    QueryPublishedFindingsCapability,
    ReadSourceCapability,
    RecordFindingFeedbackCapability,
    ReviseResearchPlanCapability,
    SearchSourcesCapability,
    StartObjectiveAnalysisCapability,
    StartResearchProcessCapability,
)
from application.chat.session_service import ChatSessionService
from application.core.objectives.objective_discovery_service import ObjectiveDiscoveryService
from application.core.objectives import analysis_service as objective_analysis_service
from application.core.objectives.analysis_service import ObjectiveAnalysisService
from application.core.objectives import (
    finding_authoring_service,
    objective_authoring_service,
    paper_experiment_authoring_service,
)
from application.evaluation import finding_feedback_service
from application.feedback import (
    CorrectionSignalAnalysisHandler,
    CorrectionSignalAnalysisWorker,
    DatasetSampleBuildWorker,
    EvaluationSampleBuilder,
    FeedbackAnalysisHandler,
    FeedbackAnalysisWorker,
    PreferenceSampleBuilder,
    SftSampleBuilder,
    ToolFailureAnalysisHandler,
    ToolFailureAnalysisWorker,
)
from application.goal import experiment_plan_service
from application.pipeline import pipeline_run_service
from application.source import collection_service
from application.source.document_preparation_service import DocumentPreparationService
from config import DATA_DIR
from controllers import auth_routes as auth
from controllers import feedback_case_routes as feedback_cases
from controllers.chat import chat_session_routes as chat_sessions
from controllers.core import document_routes as documents
from controllers.core import finding_review_routes as finding_review
from controllers.core import paper_experiment_routes as paper_experiments
from controllers.core import research_objective_routes as research_objectives
from controllers.exception_router import (
    general_exception_handler,
    http_exception_handler,
    project_exception_handler,
    request_validation_handler,
)
from controllers.feedback import feedback_dataset_routes as task_datasets
from controllers.goal import experiment_plan_routes as experiment_plans
from controllers.goal import goal_routes as goals
from controllers.source import collection_routes as collections
from controllers.source import pipeline_run_routes as pipeline_runs
from controllers.source import reference_routes as references
from exceptions import ProjectException
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from infra.llm.chat_model import OpenAIChatModel
from infra.llm.correction_signal_analysis import OpenAICorrectionSignalAnalysisEngine
from infra.llm.feedback_sample_generator import OpenAIFeedbackSampleGenerator
from infra.persistence.database import (
    AsyncSessionLocal,
    DatabaseSettings,
    build_database_engine,
)
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.exceptions import HTTPException as StarletteHTTPException
from utils.logger import (
    REQUEST_ID_HEADER,
    bind_request_id,
    bind_user_id,
    clear_request_id,
    clear_user_id,
    resolve_request_id,
    setup_logger,
)
from utils.response import ApiResponse

logger = setup_logger("lens")

PUBLIC_API_PREFIX = "/api"
PUBLIC_API_V1_PREFIX = f"{PUBLIC_API_PREFIX}/v1"


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
        "max_model_retries": "LENS_AGENT_MAX_MODEL_RETRIES",
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
            if raw == "0" and field_name in {
                "max_elapsed_seconds",
                "max_tool_calls",
                "max_model_tokens",
                "emergency_max_model_cycles",
            }:
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


from repositories.analysis_job_repository import AnalysisJobRepo
from repositories.chat_repository import ChatRepo
from repositories.document_profile_repository import DocumentProfileRepo
from repositories.feedback_case_repository import FeedbackCaseRepo
from repositories.feedback_dataset_repository import FeedbackDatasetRepo
from repositories.feedback_dataset_sample_repository import FeedbackDatasetSampleRepo
from repositories.objective_repository import ObjectiveRepo
from repositories.paper_map_repository import PaperMapRepo
from repositories.source_artifact_repository import SourceArtifactRepo


@dataclass(frozen=True)
class ApplicationRuntime:
    """Database and worker resources owned by one running process."""

    database_engine: AsyncEngine
    collection_workspace: FileCollectionWorkspace
    object_store: FileObjectStore
    objective_discovery_service: ObjectiveDiscoveryService
    document_preparation_service: DocumentPreparationService
    objective_analysis_service: ObjectiveAnalysisService
    chat_session_service: ChatSessionService
    feedback_analysis_worker: FeedbackAnalysisWorker
    correction_signal_analysis_worker: CorrectionSignalAnalysisWorker
    tool_failure_analysis_worker: ToolFailureAnalysisWorker
    dataset_sample_build_worker: DatasetSampleBuildWorker

    async def close(self) -> None:
        await self.chat_session_service.close()
        await self.objective_discovery_service.close()
        await self.document_preparation_service.close()
        await self.objective_analysis_service.close()
        await self.database_engine.dispose()


async def build_application_runtime() -> ApplicationRuntime:
    database_engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=database_engine)
    collection_workspace = FileCollectionWorkspace(DATA_DIR / "collections")
    object_store = FileObjectStore(collection_workspace.root_dir)
    preparation = DocumentPreparationService(
        workspace=collection_workspace, object_store=object_store,
    )
    analysis = ObjectiveAnalysisService()
    collection_service.configure_file_resources(collection_workspace.root_dir)
    try:
        await auth_session_service.ensure_bootstrap_user()
        chat_model = OpenAIChatModel()
        runner = ResearchAgentRunner(
            model=chat_model,
            limits=_parse_agent_run_limits(),
            capabilities=CapabilityRegistry(
                (
                    GetCollectionContextCapability(
                        collection_service=collection_service,
                        objective_repository=ObjectiveRepo,
                    ),
                    BrowseCollectionPapersCapability(
                        collection_service=collection_service,
                        document_profile_repository=DocumentProfileRepo,
                        paper_map_repository=PaperMapRepo,
                        source_artifact_repository=SourceArtifactRepo,
                    ),
                    InspectDocumentSourcesCapability(
                        collection_service=collection_service,
                        source_artifact_repository=SourceArtifactRepo,
                    ),
                    SearchSourcesCapability(
                        collection_service=collection_service,
                        source_artifact_repository=SourceArtifactRepo,
                    ),
                    InspectTableCapability(
                        collection_service=collection_service,
                        source_artifact_repository=SourceArtifactRepo,
                    ),
                    ReadSourceCapability(
                        collection_service=collection_service,
                        source_artifact_repository=SourceArtifactRepo,
                    ),
                    InspectResearchProcessCapability(
                        collection_service=collection_service,
                        pipeline_run_service=pipeline_run_service,
                    ),
                    StartResearchProcessCapability(
                        collection_service=collection_service,
                        document_preparation_service=preparation,
                    ),
                    QueryPublishedFindingsCapability(
                        collection_service=collection_service,
                        objective_repository=ObjectiveRepo,
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
                    CreateFindingDraftCapability(
                        finding_authoring_service=finding_authoring_service,
                    ),
                    CreateFindingVersionCapability(
                        finding_authoring_service=finding_authoring_service,
                    ),
                    ProposePaperExperimentDraftCapability(
                        authoring_service=paper_experiment_authoring_service,
                        chat_repository=ChatRepo,
                    ),
                    CreatePaperExperimentRevisionCapability(
                        authoring_service=paper_experiment_authoring_service,
                        chat_repository=ChatRepo,
                    ),
                    ProposeObjectiveDraftsCapability(
                        collection_service=collection_service,
                        objective_repository=ObjectiveRepo,
                        paper_map_repository=PaperMapRepo,
                    ),
                    PreviewResearchScopeCapability(
                        collection_service=collection_service,
                        paper_map_repository=PaperMapRepo,
                    ),
                    CreateObjectiveCandidateCapability(
                        objective_authoring_service=objective_authoring_service,
                    ),
                    ConfirmObjectiveCapability(
                        objective_authoring_service=objective_authoring_service,
                    ),
                    StartObjectiveAnalysisCapability(
                        collection_service=collection_service,
                        objective_repository=ObjectiveRepo,
                        objective_analysis_service=analysis,
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
        )
        correction_engine = OpenAICorrectionSignalAnalysisEngine()
        sample_generator = OpenAIFeedbackSampleGenerator()
        return ApplicationRuntime(
            database_engine=database_engine,
            collection_workspace=collection_workspace,
            object_store=object_store,
            objective_discovery_service=ObjectiveDiscoveryService(),
            document_preparation_service=preparation,
            objective_analysis_service=analysis,
            chat_session_service=ChatSessionService(runner=runner),
            feedback_analysis_worker=FeedbackAnalysisWorker(
                job_repository=AnalysisJobRepo,
                case_repository=FeedbackCaseRepo,
                handler=FeedbackAnalysisHandler(chat_repository=ChatRepo),
            ),
            correction_signal_analysis_worker=CorrectionSignalAnalysisWorker(
                job_repository=AnalysisJobRepo,
                case_repository=FeedbackCaseRepo,
                handler=CorrectionSignalAnalysisHandler(
                    chat_repository=ChatRepo,
                    engine=correction_engine,
                    model_name=correction_engine.model_name,
                ),
            ),
            tool_failure_analysis_worker=ToolFailureAnalysisWorker(
                job_repository=AnalysisJobRepo,
                case_repository=FeedbackCaseRepo,
                handler=ToolFailureAnalysisHandler(chat_repository=ChatRepo),
            ),
            dataset_sample_build_worker=DatasetSampleBuildWorker(
                job_repository=AnalysisJobRepo,
                dataset_repository=FeedbackDatasetRepo,
                sample_repository=FeedbackDatasetSampleRepo,
                case_repository=FeedbackCaseRepo,
                builders={
                    "sft": SftSampleBuilder(generator=sample_generator),
                    "preference": PreferenceSampleBuilder(generator=sample_generator),
                    "evaluation": EvaluationSampleBuilder(generator=sample_generator),
                },
            ),
        )
    except BaseException:
        await database_engine.dispose()
        raise


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    runtime = await build_application_runtime()
    application.state.runtime = runtime
    try:
        await runtime.document_preparation_service.recover_interrupted_runs()
        await runtime.objective_discovery_service.recover_interrupted_discoveries()
        await runtime.objective_analysis_service.recover_interrupted_analyses()
        yield
    finally:
        await runtime.close()


def configure_middleware(app: FastAPI) -> None:
    """Install CORS and request-correlation middleware."""

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
            bind_user_id(getattr(request.state, "user_id", ""))
            logger.info(
                "HTTP request finished method=%s path=%s status_code=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        finally:
            clear_user_id()
            clear_request_id(token)


def register_routes(app: FastAPI) -> None:
    """Register the public Lens API routers."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.include_router(auth.auth_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(collections.collection_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(references.reference_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(goals.goal_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(
        experiment_plans.experiment_plan_router, prefix=PUBLIC_API_V1_PREFIX
    )
    app.include_router(chat_sessions.chat_session_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(feedback_cases.feedback_case_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(
        task_datasets.feedback_dataset_router, prefix=PUBLIC_API_V1_PREFIX
    )
    app.include_router(pipeline_runs.pipeline_run_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(documents.document_router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(
        research_objectives.research_objective_router, prefix=PUBLIC_API_V1_PREFIX
    )
    app.include_router(
        finding_review.finding_review_router, prefix=PUBLIC_API_V1_PREFIX
    )
    app.include_router(
        paper_experiments.paper_experiment_router, prefix=PUBLIC_API_V1_PREFIX
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="TsingAI-Lens API",
        responses={
            "default": {
                "model": ApiResponse[dict],
                "description": "Business errors use the JSON envelope under HTTP 200.",
            }
        },
        version="0.13.7",
        docs_url=f"{PUBLIC_API_PREFIX}/docs",
        redoc_url=f"{PUBLIC_API_PREFIX}/redoc",
        openapi_url=f"{PUBLIC_API_PREFIX}/openapi.json",
        lifespan=lifespan,
    )
    configure_middleware(app)
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    register_routes(app)
    return app


app = create_app()
