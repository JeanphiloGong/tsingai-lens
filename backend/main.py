import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from application.auth import AuthSessionService, SessionNotFoundError
from application.chat import (
    CapabilityRegistry,
    ChatSessionService,
    ResearchAgentRunner,
)
from application.chat.capabilities import (
    CreateObjectiveCandidateCapability,
    GetCollectionContextCapability,
    ProposeObjectiveDraftsCapability,
    QueryPublishedFindingsCapability,
)
from application.core.document_profiles.service import (
    DocumentProfileService,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis_service import ObjectiveAnalysisService
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from application.core.workspace_overview_service import WorkspaceService
from application.evaluation import (
    FindingFeedbackService,
)
from application.goal.brief_service import GoalService
from application.goal.experiment_plan_service import ExperimentPlanService
from application.pipeline.collection_build.service import CollectionBuildPipelineService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.document_markdown_service import DocumentMarkdownService
from application.source.reference_workflow_service import SourceReferenceWorkflowService
from application.source.task_service import TaskService
from config import DATA_DIR
from controllers import auth
from controllers.chat import sessions as chat_sessions
from controllers.core import (
    documents,
    finding_review,
    research_objectives,
    workspace,
)
from controllers.goal import experiment_plans
from controllers.goal import intake as goals
from controllers.source import collections, references, tasks
from domain.ports import (
    ChatRepository,
    ExperimentPlanRepository,
    FindingReviewRepository,
    ObjectiveRepository,
    PaperFactRepository,
    SourceArtifactRepository,
)
from infra.llm.chat_model import OpenAIChatModel
from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.finding_review_repository import (
    PostgresFindingReviewRepository,
)
from infra.persistence.postgres.objective_repository import (
    PostgresObjectiveRepository,
)
from infra.persistence.postgres.experiment_plan_repository import (
    PostgresExperimentPlanRepository,
)
from infra.persistence.postgres.paper_fact_repository import (
    PostgresPaperFactRepository,
)
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from utils.logger import (
    REQUEST_ID_HEADER,
    bind_request_id,
    clear_request_id,
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


def create_app(
    *,
    auth_session_service: AuthSessionService | None = None,
    collection_service: CollectionService | None = None,
    task_service: TaskService | None = None,
    source_artifact_repository: SourceArtifactRepository | None = None,
    paper_fact_repository: PaperFactRepository | None = None,
    objective_repository: ObjectiveRepository | None = None,
    finding_review_repository: (
        FindingReviewRepository | None
    ) = None,
    experiment_plan_repository: ExperimentPlanRepository | None = None,
    chat_repository: ChatRepository | None = None,
    chat_session_service: ChatSessionService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = None
        try:
            session_factory = None
            if (
                auth_session_service is None
                or collection_service is None
                or task_service is None
                or source_artifact_repository is None
                or paper_fact_repository is None
                or objective_repository is None
                or finding_review_repository is None
                or experiment_plan_repository is None
                or (chat_session_service is None and chat_repository is None)
            ):
                engine = build_database_engine(DatabaseSettings())
                session_factory = build_session_factory(engine)
            if auth_session_service is None:
                active_auth_session_service = AuthSessionService(
                    PostgresAuthRepository(session_factory)
                )
                application.state.auth_session_service = active_auth_session_service
                active_auth_session_service.ensure_bootstrap_user()

            active_collection_service = collection_service or CollectionService(
                repository=PostgresCollectionRepository(session_factory),
                workspace=FileCollectionWorkspace(),
            )
            active_task_service = task_service or TaskService(
                PostgresBuildRepository(session_factory)
            )
            active_source_artifact_repository = (
                source_artifact_repository
                or PostgresSourceArtifactRepository(session_factory)
            )
            active_paper_fact_repository = (
                paper_fact_repository or PostgresPaperFactRepository(session_factory)
            )
            active_objective_repository = (
                objective_repository or PostgresObjectiveRepository(session_factory)
            )
            active_review_repository = (
                finding_review_repository
                or PostgresFindingReviewRepository(session_factory)
            )
            active_experiment_plan_repository = (
                experiment_plan_repository
                or PostgresExperimentPlanRepository(session_factory)
            )
            active_chat_repository = (
                chat_repository
                or (
                    PostgresChatRepository(session_factory)
                    if chat_session_service is None
                    else None
                )
            )
            artifact_registry_service = ArtifactRegistryService(
                active_task_service.repository,
                active_source_artifact_repository,
            )
            document_profile_service = DocumentProfileService(
                collection_service=active_collection_service,
                source_artifact_repository=active_source_artifact_repository,
                paper_fact_repository=active_paper_fact_repository,
            )
            finding_synthesis_service = FindingSynthesisService()
            finding_feedback_service = (
                FindingFeedbackService(
                    review_repository=active_review_repository,
                    objective_repository=active_objective_repository,
                )
            )
            research_objective_service = ResearchObjectiveService(
                collection_service=active_collection_service,
                source_artifact_repository=active_source_artifact_repository,
                paper_fact_repository=active_paper_fact_repository,
                objective_repository=active_objective_repository,
                document_profile_service=document_profile_service,
                finding_synthesis_service=finding_synthesis_service,
                paper_skim_service=PaperSkimService(),
                objective_candidate_service=ObjectiveCandidateService(),
            )
            workspace_service = WorkspaceService(
                collection_service=active_collection_service,
                task_service=active_task_service,
                source_artifact_repository=active_source_artifact_repository,
                objective_repository=active_objective_repository,
                document_profile_service=document_profile_service,
            )
            application.state.collection_service = active_collection_service
            application.state.task_service = active_task_service
            application.state.paper_fact_repository = active_paper_fact_repository
            application.state.objective_repository = active_objective_repository
            application.state.finding_review_repository = active_review_repository
            application.state.finding_feedback_service = (
                finding_feedback_service
            )
            application.state.artifact_registry_service = artifact_registry_service
            application.state.document_profile_service = document_profile_service
            application.state.document_markdown_service = DocumentMarkdownService(
                collection_service=active_collection_service,
                source_artifact_repository=active_source_artifact_repository,
            )
            application.state.reference_workflow_service = (
                SourceReferenceWorkflowService(
                    source_artifact_repository=active_source_artifact_repository,
                )
            )
            application.state.research_objective_service = research_objective_service
            application.state.workspace_service = workspace_service
            application.state.build_pipeline_service = CollectionBuildPipelineService(
                collection_service=active_collection_service,
                task_service=active_task_service,
                artifact_registry_service=artifact_registry_service,
                source_artifact_repository=active_source_artifact_repository,
                document_profile_service=document_profile_service,
                research_objective_service=research_objective_service,
            )
            application.state.goal_service = GoalService(active_collection_service)
            objective_analysis_service = ObjectiveAnalysisService(
                objective_repository=active_objective_repository,
                research_objective_service=research_objective_service,
            )
            application.state.chat_session_service = (
                chat_session_service
                or ChatSessionService(
                    collection_service=active_collection_service,
                    repository=active_chat_repository,
                    runner=ResearchAgentRunner(
                        model=OpenAIChatModel(),
                        capabilities=CapabilityRegistry(
                            (
                                GetCollectionContextCapability(
                                    collection_service=active_collection_service,
                                    objective_repository=active_objective_repository,
                                ),
                                QueryPublishedFindingsCapability(
                                    collection_service=active_collection_service,
                                    objective_repository=active_objective_repository,
                                    objective_analysis_service=objective_analysis_service,
                                ),
                                ProposeObjectiveDraftsCapability(
                                    collection_service=active_collection_service,
                                    objective_repository=active_objective_repository,
                                ),
                                CreateObjectiveCandidateCapability(
                                    research_objective_service=research_objective_service,
                                ),
                            )
                        ),
                    ),
                )
            )
            application.state.experiment_plan_service = ExperimentPlanService(
                repository=active_experiment_plan_repository,
                finding_feedback_service=finding_feedback_service,
            )
            application.state.objective_analysis_service = objective_analysis_service
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="TsingAI-Lens API",
        version="0.12.0",
        docs_url=f"{PUBLIC_API_PREFIX}/docs",
        redoc_url=f"{PUBLIC_API_PREFIX}/redoc",
        openapi_url=f"{PUBLIC_API_PREFIX}/openapi.json",
        lifespan=lifespan,
    )
    if auth_session_service is not None:
        app.state.auth_session_service = auth_session_service
        auth_session_service.ensure_bootstrap_user()
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
            user = request.app.state.auth_session_service.resolve_session(
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

        request.state.current_user = user
        collection_id = _extract_collection_id(request.url.path)
        if collection_id and not _user_owns_collection(
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

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.include_router(auth.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(collections.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(references.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(goals.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(experiment_plans.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(chat_sessions.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(tasks.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(workspace.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(documents.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(research_objectives.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(
        finding_review.router, prefix=PUBLIC_API_V1_PREFIX
    )
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


def _user_owns_collection(
    collection_service: CollectionService,
    collection_id: str,
    user_id: str,
) -> bool:
    try:
        collection_service.get_collection_for_user(collection_id, user_id)
    except FileNotFoundError:
        return False
    return True


app = create_app()
