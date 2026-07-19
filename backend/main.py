from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from time import perf_counter

from config import DATA_DIR
from application.auth import AuthSessionService, SessionNotFoundError
from application.core.comparison_service import ComparisonService
from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
)
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.semantic_build.paper_facts_service import PaperFactsService
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.core.workspace_overview_service import WorkspaceService
from application.goal.brief_service import GoalService
from application.goal.session_service import GoalSessionService
from application.pipeline.collection_build.service import CollectionBuildPipelineService
from application.pipeline.goal_analysis.service import GoalAnalysisPipelineService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.document_markdown_service import DocumentMarkdownService
from application.source.task_service import TaskService
from controllers import auth
from controllers.core import (
    comparable_results,
    comparisons,
    confirmed_goals,
    documents,
    evidence,
    goal_analysis,
    research_objectives,
    research_understanding_feedback,
    research_view,
    results,
    workspace,
)
from controllers.derived import graph
from controllers.goal import intake as goals
from controllers.goal import experiment_plans
from controllers.goal import sessions as goal_sessions
from controllers.source import collections, references, tasks
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.file import FileCollectionWorkspace

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
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = None
        try:
            session_factory = None
            if auth_session_service is None or collection_service is None:
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
            task_service = TaskService()
            artifact_registry_service = ArtifactRegistryService()
            document_profile_service = DocumentProfileService(
                collection_service=active_collection_service,
            )
            paper_facts_service = PaperFactsService(
                collection_service=active_collection_service,
                document_profile_service=document_profile_service,
            )
            comparison_service = ComparisonService(
                collection_service=active_collection_service,
                document_profile_service=document_profile_service,
            )
            research_objective_service = ResearchObjectiveService(
                collection_service=active_collection_service,
                document_profile_service=document_profile_service,
            )
            workspace_service = WorkspaceService(
                collection_service=active_collection_service,
                task_service=task_service,
                document_profile_service=document_profile_service,
            )
            research_view_service = ResearchViewAggregationService(
                collection_service=active_collection_service,
                task_service=task_service,
                document_profile_service=document_profile_service,
                paper_facts_service=paper_facts_service,
                comparison_service=comparison_service,
                workspace_service=workspace_service,
            )

            application.state.collection_service = active_collection_service
            application.state.task_service = task_service
            application.state.artifact_registry_service = artifact_registry_service
            application.state.document_profile_service = document_profile_service
            application.state.document_markdown_service = DocumentMarkdownService(
                collection_service=active_collection_service,
            )
            application.state.paper_facts_service = paper_facts_service
            application.state.comparison_service = comparison_service
            application.state.research_objective_service = research_objective_service
            application.state.workspace_service = workspace_service
            application.state.research_view_service = research_view_service
            application.state.build_pipeline_service = CollectionBuildPipelineService(
                collection_service=active_collection_service,
                task_service=task_service,
                artifact_registry_service=artifact_registry_service,
                document_profile_service=document_profile_service,
                research_objective_service=research_objective_service,
            )
            application.state.goal_service = GoalService(active_collection_service)
            application.state.goal_session_service = GoalSessionService(
                collection_service=active_collection_service,
                task_service=task_service,
                research_view_service=research_view_service,
                workspace_service=workspace_service,
                comparison_service=comparison_service,
                paper_facts_service=paper_facts_service,
                research_objective_service=research_objective_service,
            )
            application.state.goal_analysis_service = GoalAnalysisPipelineService(
                research_objective_service=research_objective_service,
            )
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="TsingAI-Lens API",
        version="0.9.0",
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
    app.include_router(goal_sessions.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(graph.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(tasks.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(workspace.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(documents.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(evidence.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(confirmed_goals.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(goal_analysis.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(research_objectives.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(research_understanding_feedback.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(research_view.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(comparisons.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(results.router, prefix=PUBLIC_API_V1_PREFIX)
    app.include_router(comparable_results.router, prefix=PUBLIC_API_V1_PREFIX)
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
