import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from time import perf_counter

from application.auth import session_service as auth_session_service
from application.chat import AgentRunLimits, CapabilityRegistry, ResearchAgentRunner
from application.chat import session_service
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
from infra.llm.chat_model import OpenAIChatModel
from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
)
from infra.persistence import database
from infra.persistence.file import collection_workspace, object_store

from config import DATA_DIR
from controllers import auth_routes as auth
from controllers import feedback_case_routes as feedback_cases
from controllers import model_connection_routes as model_connections
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


@asynccontextmanager
async def lifespan(_application: object | None = None) -> AsyncIterator[None]:
    async with AsyncExitStack() as cleanup:
        database_engine = build_database_engine(DatabaseSettings())
        cleanup.push_async_callback(database_engine.dispose)
        database.engine = database_engine
        database.AsyncSessionLocal.configure(bind=database_engine)
        collection_workspace.Workspace = collection_workspace.FileCollectionWorkspace(DATA_DIR / "collections")
        object_store.Store = object_store.FileObjectStore(collection_workspace.Workspace.root_dir)
        await auth_session_service.ensure_bootstrap_user()
        chat_model = OpenAIChatModel()
        cleanup.push_async_callback(chat_model.client.close)
        runner = ResearchAgentRunner(
            model=chat_model,
            limits=_parse_agent_run_limits(),
            capabilities=CapabilityRegistry(
                (
                    GetCollectionContextCapability(),
                    BrowseCollectionPapersCapability(),
                    InspectDocumentSourcesCapability(),
                    SearchSourcesCapability(),
                    InspectTableCapability(),
                    ReadSourceCapability(),
                    InspectResearchProcessCapability(),
                    StartResearchProcessCapability(),
                    QueryPublishedFindingsCapability(),
                    InspectPublishedFindingCapability(),
                    RecordFindingFeedbackCapability(),
                    CurateFindingCapability(),
                    CreateFindingDraftCapability(),
                    CreateFindingVersionCapability(),
                    ProposePaperExperimentDraftCapability(),
                    CreatePaperExperimentRevisionCapability(),
                    ProposeObjectiveDraftsCapability(),
                    PreviewResearchScopeCapability(),
                    CreateObjectiveCandidateCapability(),
                    ConfirmObjectiveCapability(),
                    StartObjectiveAnalysisCapability(),
                    InspectObjectiveAnalysisCapability(),
                    AssessObjectiveQualityCapability(),
                    DeriveObjectiveCapability(),
                    ProposeResearchPlanCapability(),
                    CreateResearchPlanCapability(),
                    InspectResearchPlansCapability(),
                    ReviseResearchPlanCapability(),
                )
            ),
        )
        service = session_service.ChatSessionService(
            runner=runner,
        )
        cleanup.push_async_callback(service.close)
        session_service.ChatService = service
        yield


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
    app.include_router(model_connections.model_connection_router, prefix=PUBLIC_API_V1_PREFIX)
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
        version="0.13.11",
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
