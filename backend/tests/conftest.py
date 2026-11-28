from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from infra.persistence.file.object_store import FileObjectStore
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.integration.persistence.database_cleanup import reset_postgres_schema


@pytest.fixture
def postgres_sync_engine(request):
    database_url = os.getenv("LENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not str(url.database).endswith(
        "_test"
    ):
        pytest.fail(
            "LENS_TEST_DATABASE_URL must use postgresql+psycopg and a *_test database"
        )

    engine = create_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    reset_postgres_schema(engine)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, getattr(request, "param", "head"))
        yield engine
    finally:
        reset_postgres_schema(engine)
        engine.dispose()


@pytest.fixture
def postgres_session_factory(postgres_sync_engine, monkeypatch):
    # TestClient and asyncio.run may use different loops within the same test.
    engine = create_async_engine(postgres_sync_engine.url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        # Web startup configures the same native factory as the repositories.
        # Keep its engine inside this test's isolated PostgreSQL database.
        monkeypatch.setenv(
            "LENS_DATABASE_URL",
            postgres_sync_engine.url.render_as_string(hide_password=False),
        )
        monkeypatch.setattr("main.build_database_engine", lambda _settings: engine)
        monkeypatch.setattr("infra.persistence.database.AsyncSessionLocal", factory)
        monkeypatch.setattr(
            "application.core.objectives.analysis.experiment_query_service.AsyncSessionLocal",
            factory,
        )
        monkeypatch.setattr(
            "application.core.objectives.objective_analysis_service.AsyncSessionLocal",
            factory,
        )
        monkeypatch.setattr(
            "application.core.objectives.paper_experiment_authoring_service.AsyncSessionLocal",
            factory,
        )
        monkeypatch.setattr(
            "application.core.objectives.finding_authoring_service.AsyncSessionLocal",
            factory,
        )
        monkeypatch.setattr(
            "application.core.objectives.analysis_service.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.objective_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "conversation.repositories.conversation_repository.AsyncSessionLocal", factory,
        )
        monkeypatch.setattr(
            "agent.repositories.task_repository.AsyncSessionLocal", factory,
        )
        monkeypatch.setattr(
            "pipeline.application.pipeline_run_service.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "pipeline.application.document_preparation_runner.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "research.discovery.application.discovery_service.AsyncSessionLocal",
            factory,
        )

        monkeypatch.setattr(
            "repositories.model_connection_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.pipeline_run_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.finding_review_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.evaluation_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.experiment_plan_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "document.repositories.source_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "research.discovery.repositories.paper_map_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "document.repositories.profile_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.workspace_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr("conversation.feedback.repository.AsyncSessionLocal", factory)
        yield factory
    finally:
        engine.sync_engine.dispose()


@pytest.fixture(autouse=True)
def _patch_domain_model_extractors(monkeypatch):
    from document.application import profile_extraction as extraction
    from tests.support.fake_domain_model_extractor import FakeDomainModelExtractor

    fake = FakeDomainModelExtractor()
    monkeypatch.setattr(
        extraction, "build_default_document_profile_extractor", lambda: fake
    )


@pytest.fixture
def identity_subjects(postgres_session_factory):
    from tests.support.identity import subjects

    return subjects


@pytest.fixture
def workspace_files(tmp_path, monkeypatch):
    from infra.persistence.file import workspace_files as workspace_module

    workspace = workspace_module.FileWorkspace(tmp_path / "workspaces")
    monkeypatch.setattr(workspace_module, "Workspace", workspace, raising=False)
    return workspace


@pytest.fixture
def object_store(workspace_files, monkeypatch):
    from infra.persistence.file import object_store as store_module

    store = FileObjectStore(workspace_files.root_dir)
    monkeypatch.setattr(store_module, "Store", store, raising=False)
    return store




@pytest.fixture
def workspace_service(postgres_session_factory):
    from application.source import workspace_service
    from repositories.workspace_repository import WorkspaceRepository

    workspace_service.WorkspaceRepo = WorkspaceRepository()
    return workspace_service


@pytest.fixture(autouse=True)
def _isolate_application_module_dependencies(monkeypatch):
    """Restore directly patched singleton dependencies and per-test task state."""
    from application.source import agent_workspace_service as workspace_context
    from application.source import agent_source_service as document_sources
    from agent.capabilities import research_scope
    import application.core.objectives.analysis.analysis_record_source as _test_analysis_record_source
    import document.application.profile_service as _test_document_profile_service
    import application.core.objectives.analysis.experiment_analysis_writer as _test_experiment_analysis_writer
    import application.core.objectives.analysis.experiment_projection as _test_experiment_projection
    import application.core.objectives.analysis.experiment_finding_synthesis as _test_experiment_finding_synthesis_service
    import application.core.objectives.analysis.experiment_query_service as _test_experiment_query_service
    import application.core.objectives.analysis_service as _test_objective_analysis_service
    import application.core.objectives.finding_authoring_service as _test_finding_authoring_service
    import application.core.objectives.objective_analysis_service as _test_experiment_analysis_service
    import research.application.objectives.objective_authoring_service as _test_objective_authoring_service
    import research.discovery.application.candidate_formation as _test_candidate_formation
    import research.discovery.application.discovery_service as _test_objective_discovery_service
    import application.core.objectives.objective_input_service as _test_objective_input_service
    import application.core.objectives.paper_experiment_authoring_service as _test_paper_experiment_authoring_service
    import application.evaluation.finding_feedback_service as _test_finding_feedback_service
    import application.evaluation.finding_dataset_service as _test_finding_dataset_service
    import application.evaluation.finding_snapshot_service as _test_finding_snapshot_service
    import application.goal.brief_service as _test_goal_service
    import application.goal.experiment_plan_service as _test_experiment_plan_service
    import pipeline.application.pipeline_run_service as _test_pipeline_run_service
    import application.source.workspace_service as _test_workspace_service
    import document.application.markdown as _test_document_markdown_service
    import pipeline.application.document_preparation_runner as _test_document_preparation_service
    import document.application.references as _test_source_reference_extraction_service
    import document.application.reference_workflow as _test_reference_workflow_service
    import document.application.import_service as _test_source_import_service
    from document.controllers import document_routes, reference_routes
    from controllers.core import (
        finding_review_routes,
        paper_experiment_routes,
    )
    from research.controllers import objective_routes as research_objective_routes
    from controllers.goal import experiment_plan_routes, goal_routes
    from controllers.source import workspace_routes
    from pipeline.controllers import pipeline_run_routes

    from agent.tools import objective as objective_candidate
    from agent.capabilities import (
        objective_proposal,
        objective_analysis,
        objective_derivation,
    )

    from agent.capabilities import (
        finding_authoring,
        finding_review,
        paper_experiment_authoring,
    )

    from agent.capabilities import published_findings, research_planning

    dependencies = (
        (
            published_findings,
            [
                "workspace_service",
                "ObjectiveRepo",
                "objective_analysis_service",
                "finding_feedback_service",
            ],
        ),
        (
            research_planning,
            [
                "workspace_service",
                "finding_dataset_service",
                "experiment_plan_service",
            ],
        ),
        (finding_authoring, ["finding_authoring_service"]),
        (finding_review, ["workspace_service", "finding_feedback_service"]),
        (
            paper_experiment_authoring,
            ["paper_experiment_authoring_service", "task_repository"],
        ),
        (objective_candidate, ["objective_authoring_service"]),
        (objective_proposal, ["workspace_service", "ObjectiveRepo", "PaperMapRepo"]),
        (
            objective_analysis,
            [
                "workspace_service",
                "ObjectiveRepo",
                "objective_authoring_service",
                "objective_analysis_service",
            ],
        ),
        (objective_derivation, ["workspace_service", "objective_analysis_service"]),
        (document_sources, ["workspace_service", "SourceRepo"]),
        (
            workspace_context,
            [
                "workspace_service",
                "ObjectiveRepo",
                "ProfileRepo",
                "PaperMapRepo",
                "SourceRepo",
            ],
        ),
        (research_scope, ["workspace_service", "PaperMapRepo"]),
        (_test_analysis_record_source, ["ObjectiveRepo"]),
        (
            _test_document_profile_service,
            [
                "ProfileRepo",
                "SourceRepo",
                "workspace_service",
            ],
        ),
        (
            _test_experiment_analysis_writer,
            [
                "ExperimentAnalysisRepo",
                "PaperExperimentRepo",
                "experiment_finding_synthesis_service",
            ],
        ),
        (
            _test_experiment_projection,
            ["ObjectiveRepo", "experiment_query_service"],
        ),
        (_test_experiment_finding_synthesis_service, []),
        (
            _test_experiment_query_service,
            [
                "workspace_service",
                "ComparisonGroupRepo",
                "ExperimentFindingRepo",
                "ObjectiveExperimentSelectionRepo",
                "ObjectiveRepo",
                "PaperExperimentRepo",
            ],
        ),
        (
            _test_objective_analysis_service,
            [
                "workspace_service",
                "ObjectiveRepo",
                "document_profile_service",
                "experiment_analysis_service",
                "experiment_analysis_writer",
                "experiment_projection",
                "objective_input_service",
            ],
        ),
        (
            _test_finding_authoring_service,
            [
                "ObjectiveRepo",
                "workspace_service",
                "experiment_analysis_writer",
                "experiment_query_service",
            ],
        ),
        (
            _test_experiment_analysis_service,
            [
                "ObjectiveRepo",
                "PaperExperimentRepo",
                "PaperMapRepo",
                "workspace_service",
                "objective_input_service",
            ],
        ),
        (
            _test_objective_authoring_service,
            [
                "ObjectiveRepo",
                "workspace_service",
                "experiment_projection",
            ],
        ),
        (_test_candidate_formation, []),
        (
            _test_objective_discovery_service,
            [
                "workspace_service",
                "ObjectiveRepo",
                "candidate_formation",
                "objective_input_service",
                "pipeline_run_service",
            ],
        ),
        (
            _test_objective_input_service,
            [
                "PaperMapRepo",
                "SourceRepo",
                "workspace_service",
                "document_profile_service",
                "paper_research_map_service",
            ],
        ),
        (
            _test_paper_experiment_authoring_service,
            ["SourceRepo", "workspace_service", "experiment_analysis_writer"],
        ),
        (_test_finding_feedback_service, ["workspace_service", "FindingReviewRepo"]),
        (_test_finding_dataset_service, ["workspace_service", "ObjectiveRepo"]),
        (
            _test_finding_snapshot_service,
            ["ObjectiveRepo", "FindingReviewRepo", "experiment_projection"],
        ),
        (_test_goal_service, ["workspace_service"]),
        (
            _test_experiment_plan_service,
            ["ExperimentPlanRepo", "finding_snapshot_service", "workspace_service"],
        ),
        (_test_pipeline_run_service, ["PipelineRunRepo", "WorkspaceRepo"]),
        (
            _test_workspace_service,
            ["WorkspaceRepo"],
        ),
        (_test_document_markdown_service, ["SourceRepo", "workspace_service"]),
        (
            _test_document_preparation_service,
            [
                "ProfileRepo",
                "SourceRepo",
                "workspace_service",
                "document_profile_service",
                "pipeline_run_service",
            ],
        ),
        (_test_source_reference_extraction_service, []),
        (
            _test_reference_workflow_service,
            ["SourceRepo", "workspace_service"],
        ),
        (_test_source_import_service, ["WorkspaceRepo"]),
        (
            document_routes,
            [
                "document_profile_service",
                "markdown",
                "archive",
            ],
        ),
        (
            finding_review_routes,
            [
                "finding_feedback_service",
                "finding_dataset_service",
                "finding_authoring_service",
            ],
        ),
        (paper_experiment_routes, ["experiment_query_service"]),
        (
            research_objective_routes,
            [
                "objective_analysis_service",
                "objective_scope_service",
                "list_objectives",
            ],
        ),
        (experiment_plan_routes, ["experiment_plan_service"]),
        (goal_routes, ["brief_service"]),
        (
            workspace_routes,
            ["workspace_service", "source_archive_service", "source_import_service"],
        ),
        (
            pipeline_run_routes,
            [
                "workspace_service",
                "pipeline_run_service",
            ],
        ),
        (reference_routes, ["reference_workflow_service"]),
    )
    for module, names in dependencies:
        for name in names:
            value = getattr(module, name, None)
            if isinstance(value, set):
                value = set(value)
            monkeypatch.setattr(module, name, value, raising=False)


@pytest.fixture(autouse=True)
def _external_identity_transport(monkeypatch):
    from infra.identity import client
    from tests.support.identity import subjects

    subjects.users.clear()
    subjects.tokens.clear()
    monkeypatch.setattr(client, "Client", subjects, raising=False)
    monkeypatch.setattr(client, "IdentityClient", lambda: subjects)


@pytest.fixture(autouse=True)
def model_master_key(tmp_path, monkeypatch):
    from infra.llm.model_credentials import load_master_key
    path = tmp_path / "model-key"
    path.write_bytes(bytes(range(32)))
    monkeypatch.setenv("LENS_MODEL_KEY_FILE", str(path))
    load_master_key.cache_clear()
    yield
    load_master_key.cache_clear()
