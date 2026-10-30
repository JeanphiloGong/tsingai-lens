from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from infra.persistence.file.object_store import FileObjectStore
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.persistence.postgres.models.auth import AuthUser
from tests.integration.persistence.database_cleanup import reset_postgres_schema


@pytest.fixture
def postgres_sync_engine():
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
            command.upgrade(config, "head")
        yield engine
    finally:
        reset_postgres_schema(engine)
        engine.dispose()


@pytest.fixture
def postgres_session_factory(postgres_sync_engine, monkeypatch):
    # TestClient and asyncio.run may use different loops within the same test.
    engine = create_async_engine(postgres_sync_engine.url, poolclass=NullPool)
    with postgres_sync_engine.begin() as connection:
        connection.execute(
            insert(AuthUser).values(
                user_id="local-user",
                email="local-fixture@example.com",
                password_hash="!",
                created_at=datetime.now(timezone.utc),
            )
        )
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
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
            "repositories.feedback_dataset_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.objective_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr("repositories.chat_repository.AsyncSessionLocal", factory)
        monkeypatch.setattr(
            "repositories.model_connection_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.analysis_job_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.feedback_dataset_export_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.feedback_dataset_sample_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.feedback_case_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.pipeline_run_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.dataset_snapshot_repository.AsyncSessionLocal", factory
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
            "repositories.source_artifact_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.paper_map_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.document_profile_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr(
            "repositories.collection_repository.AsyncSessionLocal", factory
        )
        monkeypatch.setattr("repositories.auth_repository.AsyncSessionLocal", factory)
        yield factory
    finally:
        engine.sync_engine.dispose()


@pytest.fixture(autouse=True)
def _patch_domain_model_extractors(monkeypatch):
    from application.core.document_profiles import service as document_profile_service
    from application.core.objectives import analysis_service, objective_discovery_service
    from tests.support.fake_domain_model_extractor import FakeDomainModelExtractor

    fake = FakeDomainModelExtractor()
    monkeypatch.setattr(
        document_profile_service,
        "build_default_document_profile_extractor",
        lambda: fake,
    )
    for owner in (analysis_service, objective_discovery_service):
        monkeypatch.setattr(
            owner, "build_default_structured_response_client", lambda: fake
        )


@pytest.fixture
def auth_session_service(postgres_session_factory):
    from application.auth import session_service

    return session_service


@pytest.fixture
def collection_workspace(tmp_path):
    from infra.persistence.file import FileCollectionWorkspace

    return FileCollectionWorkspace(tmp_path / "collections")


@pytest.fixture
def object_store(collection_workspace):
    return FileObjectStore(collection_workspace.root_dir)


@pytest.fixture
def document_preparation_runtime(collection_workspace, object_store):
    from application.source.document_preparation_service import DocumentPreparationService
    return DocumentPreparationService(
        workspace=collection_workspace,
        object_store=object_store, max_concurrency=1,
    )


@pytest.fixture
def collection_service(postgres_session_factory):
    from application.source import collection_service
    from repositories.collection_repository import CollectionRepository

    collection_service.CollectionRepo = CollectionRepository()
    return collection_service


@pytest.fixture(autouse=True)
def _isolate_application_module_dependencies(monkeypatch):
    """Restore directly patched singleton dependencies and per-test task state."""
    import application.chat.session_service as _test_chat_session_service
    from application.chat.capabilities import collection_context, research_scope, document_sources
    import application.core.objectives.analysis.analysis_record_source as _test_analysis_record_source
    import application.core.document_profiles.service as _test_document_profile_service
    import application.core.objectives.analysis.experiment_analysis_writer as _test_experiment_analysis_writer
    import application.core.objectives.analysis.experiment_projection as _test_experiment_projection
    import application.core.objectives.analysis.experiment_finding_synthesis as _test_experiment_finding_synthesis_service
    import application.core.objectives.analysis.experiment_query_service as _test_experiment_query_service
    import application.core.objectives.analysis_service as _test_objective_analysis_service
    import application.core.objectives.finding_authoring_service as _test_finding_authoring_service
    import application.core.objectives.objective_analysis_service as _test_experiment_analysis_service
    import application.core.objectives.objective_authoring_service as _test_objective_authoring_service
    import application.core.objectives.objective_candidate_service as _test_objective_candidate_service
    import application.core.objectives.objective_discovery_service as _test_objective_discovery_service
    import application.core.objectives.objective_input_service as _test_objective_input_service
    import application.core.objectives.paper_experiment_authoring_service as _test_paper_experiment_authoring_service
    import application.evaluation.finding_feedback_service as _test_finding_feedback_service
    import application.feedback.dataset_export_service as _test_dataset_export_service
    import application.feedback.dataset_service as _test_dataset_service
    import application.feedback.dataset_snapshot_service as _test_dataset_snapshot_service
    import application.feedback.feedback_case_service as _test_feedback_case_service
    import application.goal.brief_service as _test_goal_service
    import application.goal.experiment_plan_service as _test_experiment_plan_service
    import application.pipeline.pipeline_run_service as _test_pipeline_run_service
    import application.source.collection_service as _test_collection_service
    import application.source.document_markdown_service as _test_document_markdown_service
    import application.source.document_preparation_service as _test_document_preparation_service
    import application.source.reference_extraction_service as _test_source_reference_extraction_service
    import application.source.reference_workflow_service as _test_reference_workflow_service
    import application.source.source_import_service as _test_source_import_service
    from application.auth import session_service as _test_auth_session_service
    from controllers import auth_routes, feedback_case_routes
    from controllers.chat import chat_session_routes
    from controllers.core import (
        document_routes,
        finding_review_routes,
        paper_experiment_routes,
        research_objective_routes,
    )
    from controllers.feedback import dataset_snapshot_routes, feedback_dataset_routes
    from controllers.goal import experiment_plan_routes, goal_routes
    from controllers.source import (
        collection_routes,
        pipeline_run_routes,
        reference_routes,
    )

    from application.chat.capabilities import objective_candidate, objective_proposal, objective_analysis, objective_derivation

    dependencies = (
        (objective_candidate, ["objective_authoring_service"]),
        (objective_proposal, ["collection_service", "ObjectiveRepo", "PaperMapRepo"]),
        (objective_analysis, ["collection_service", "ObjectiveRepo", "objective_authoring_service", "objective_analysis_service"]),
        (objective_derivation, ["collection_service", "objective_analysis_service"]),
        (document_sources, ["collection_service", "SourceArtifactRepo"]),
        (collection_context, ["collection_service", "ObjectiveRepo", "DocumentProfileRepo", "PaperMapRepo", "SourceArtifactRepo"]),
        (research_scope, ["collection_service", "PaperMapRepo"]),
        (_test_analysis_record_source, ["ObjectiveRepo"]),
        (
            _test_chat_session_service,
            [
                "AnalysisJobRepo",
                "ChatRepo",
                "CollectionRepo",
                "SourceArtifactRepo",
                "collection_service",
            ],
        ),
        (
            _test_document_profile_service,
            [
                "DocumentProfileRepo",
                "SourceArtifactRepo",
                "collection_service",
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
                "collection_service",
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
                "collection_service",
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
                "collection_service",
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
                "collection_service",
                "objective_input_service",
            ],
        ),
        (
            _test_objective_authoring_service,
            [
                "ObjectiveRepo",
                "collection_service",
                "experiment_projection",
            ],
        ),
        (_test_objective_candidate_service, []),
        (
            _test_objective_discovery_service,
            [
                "collection_service",
                "ObjectiveRepo",
                "objective_candidate_service",
                "objective_input_service",
                "pipeline_run_service",
            ],
        ),
        (
            _test_objective_input_service,
            [
                "PaperMapRepo",
                "SourceArtifactRepo",
                "collection_service",
                "document_profile_service",
                "paper_research_map_service",
            ],
        ),
        (
            _test_paper_experiment_authoring_service,
            ["SourceArtifactRepo", "collection_service", "experiment_analysis_writer"],
        ),
        (
            _test_finding_feedback_service,
            [
                "collection_service",
                "FindingReviewRepo",
                "ObjectiveRepo",
                "experiment_projection",
            ],
        ),
        (
            _test_dataset_export_service,
            [
                "FeedbackDatasetExportRepo",
                "FeedbackDatasetSampleRepo",
                "dataset_service",
            ],
        ),
        (
            _test_dataset_service,
            [
                "FeedbackCaseRepo",
                "FeedbackDatasetRepo",
                "FeedbackDatasetSampleRepo",
                "collection_service",
            ],
        ),
        (
            _test_dataset_snapshot_service,
            [
                "ChatRepo",
                "DatasetSnapshotRepo",
                "FeedbackCaseRepo",
                "collection_service",
            ],
        ),
        (
            _test_feedback_case_service,
            ["ChatRepo", "CollectionRepo", "FeedbackCaseRepo", "collection_service"],
        ),
        (_test_goal_service, ["collection_service"]),
        (
            _test_experiment_plan_service,
            ["ExperimentPlanRepo", "finding_feedback_service", "collection_service"],
        ),
        (_test_pipeline_run_service, ["PipelineRunRepo", "CollectionRepo"]),
        (
            _test_collection_service,
            ["CollectionRepo"],
        ),
        (_test_document_markdown_service, ["SourceArtifactRepo", "collection_service"]),
        (
            _test_document_preparation_service,
            [
                "DocumentProfileRepo",
                "SourceArtifactRepo",
                "collection_service",
                "document_profile_service",
                "pipeline_run_service",
            ],
        ),
        (_test_source_reference_extraction_service, []),
        (
            _test_reference_workflow_service,
            ["SourceArtifactRepo", "collection_service"],
        ),
        (_test_source_import_service, ["CollectionRepo"]),
        (_test_auth_session_service, ["AuthRepo", "SESSION_TTL"]),
        (auth_routes, ["session_service"]),
        (chat_session_routes, ["chat_session_service"]),
        (
            document_routes,
            [
                "document_profile_service",
                "document_markdown_service",
                "source_archive_service",
            ],
        ),
        (
            finding_review_routes,
            ["finding_feedback_service", "finding_authoring_service"],
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
        (dataset_snapshot_routes, ["dataset_snapshot_service"]),
        (feedback_dataset_routes, ["dataset_service", "dataset_export_service"]),
        (feedback_case_routes, ["feedback_case_service"]),
        (experiment_plan_routes, ["experiment_plan_service"]),
        (goal_routes, ["brief_service"]),
        (
            collection_routes,
            ["collection_service", "source_archive_service", "source_import_service"],
        ),
        (
            pipeline_run_routes,
            [
                "collection_service",
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
