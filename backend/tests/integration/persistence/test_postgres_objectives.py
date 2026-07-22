from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import os
from threading import Barrier

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.source import CollectionRecord
from domain.core import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveFactSet,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.models.objective import (
    ObjectiveContextRecord,
    ObjectiveEvidenceRouteRecord,
    ObjectiveEvidenceUnitRecord,
    ObjectiveLogicChainRecord,
    ObjectivePaperFrameRecord,
    ObjectivePaperSkim,
    objective_unit_source_refs,
)
from infra.persistence.postgres.paper_fact_repository import PostgresPaperFactRepository
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from tests.integration.persistence.test_postgres_paper_facts import _paper_facts
from tests.integration.persistence.test_postgres_source_artifacts import (
    BACKEND_ROOT,
    NOW,
    REAL_SOURCE_BLOCK_ID,
    REAL_SOURCE_DOCUMENT_ID,
    REAL_SOURCE_TABLE_ID,
    _artifacts,
    _collection_import,
    _finish,
    _real_shape_artifacts,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)


def _objective_facts(
    question: str = "How does processing affect strength?",
) -> ObjectiveFactSet:
    objective = ResearchObjective.from_mapping(
        {
            "objective_id": "objective-1",
            "question": question,
            "material_scope": ["Alloy A"],
            "process_axes": ["temperature"],
            "property_axes": ["strength"],
            "comparison_intent": "compare temperature conditions",
            "seed_document_ids": ["srcdoc_runtime"],
            "excluded_document_ids": [],
            "confidence": 0.9,
            "reason": "The paper reports comparable measurements.",
        }
    )
    context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": question,
            "material_scope": ["Alloy A"],
            "variable_process_axes": ["temperature"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["strength"],
            "excluded_property_axes": ["density"],
            "objective_evidence_lens": {"target_outcome_axes": ["strength"]},
            "routing_hints": [{"table_id": "table-1", "role": "result_table"}],
            "extraction_guidance": {"prefer": "direct measurements"},
            "confidence": 0.88,
        }
    )
    frame = ObjectivePaperFrame.from_mapping(
        {
            "frame_id": "frame-1",
            "objective_id": objective.objective_id,
            "document_id": "srcdoc_runtime",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "background": "Direct experimental evidence.",
            "material_match": ["Alloy A"],
            "changed_variables": ["temperature"],
            "measured_property_scope": ["strength"],
            "test_environment_scope": ["ambient"],
            "relevant_sections": ["Methods"],
            "relevant_tables": ["table-1"],
            "excluded_tables": [],
        }
    )
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "route_id": "route-1",
            "objective_id": objective.objective_id,
            "document_id": "srcdoc_runtime",
            "source_kind": "table",
            "source_ref": "table-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "reason": "The table reports strength.",
            "table_schema": {"columns": ["Sample", "Value"]},
            "column_roles": {"Value": "measurement"},
            "join_keys": {"sample": "Sample"},
            "join_plan": {"on": "sample"},
            "confidence": 0.86,
        }
    )
    unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "unit-1",
            "objective_id": objective.objective_id,
            "document_id": "srcdoc_runtime",
            "source_kind": "table",
            "source_ref": "table-1",
            "evidence_role": "current_experimental_evidence",
            "selection_reason": "The table reports strength.",
            "selection_status": "extracted",
            "unit_kind": "measurement",
            "property_normalized": "strength",
            "material_system": {"name": "Alloy A"},
            "sample_context": {"label": "Sample A"},
            "process_context": {"temperature_c": 600},
            "resolved_condition": {"temperature_c": 25},
            "test_condition": {"method": "tensile"},
            "value_payload": {"value": 100},
            "unit": "MPa",
            "baseline_context": {"label": "Untreated"},
            "interpretation": "Higher temperature increased strength.",
            "source_refs": [
                {"source_kind": "table", "source_ref": "table-1", "page": 1},
                {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "role": "test_condition",
                },
            ],
            "evidence_anchor_ids": ["anchor-1"],
            "join_keys": {"sample": "A"},
            "resolution_status": "resolved",
            "confidence": 0.84,
        }
    )
    chain = ObjectiveLogicChain.from_mapping(
        {
            "logic_chain_id": "chain-1",
            "objective_id": objective.objective_id,
            "chain_scope": "paper",
            "document_id": "srcdoc_runtime",
            "question": question,
            "evidence_unit_ids": [unit.evidence_unit_id],
            "chain_payload": {"path": ["temperature", "strength"]},
            "summary": "Temperature to strength evidence chain.",
            "confidence": 0.82,
        }
    )
    return ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=(
            PaperSkim.from_mapping(
                {
                    "document_id": "srcdoc_runtime",
                    "title": "Paper",
                    "source_filename": "paper.pdf",
                    "doc_role": "experimental",
                    "candidate_materials": ["Alloy A"],
                    "candidate_processes": ["LPBF", "temperature"],
                    "candidate_properties": ["strength"],
                    "changed_variables": ["temperature"],
                    "possible_objectives": [question],
                    "evidence_density": "high",
                    "confidence": 0.9,
                    "warnings": ["synthetic"],
                }
            ),
        ),
        research_objectives=(objective,),
        objective_contexts=(context,),
        objective_paper_frames=(frame,),
        objective_evidence_routes=(route,),
        objective_evidence_units=(unit,),
        objective_logic_chains=(chain,),
    )


def _write_build(source_repository, builds, build_id: str, facts: ObjectiveFactSet):
    task = _task(f"task_{build_id}")
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_artifacts("col_source", build_id, _artifacts())
    paper_facts = _paper_facts()
    paper_repository = PostgresPaperFactRepository(source_repository.session_factory)
    paper_repository.replace_document_profiles(
        "col_source", build_id, paper_facts.document_profiles
    )
    paper_repository.replace_paper_facts("col_source", build_id, paper_facts)
    PostgresObjectiveRepository(source_repository.session_factory).replace(
        "col_source", build_id, facts
    )
    return task


def test_objective_repository_round_trips_relations_and_active_build(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    expected = _objective_facts()
    task = _write_build(source_repository, builds, "build_objectives", expected)

    assert repository.read("col_source") == ObjectiveFactSet()
    assert repository.read("col_source", build_id="build_objectives") == expected

    _finish(builds, task, success=True)

    assert repository.read("col_source") == expected
    with pytest.raises(ValueError, match="collection build is not writable"):
        repository.replace("col_source", "build_objectives", expected)


def test_failed_objective_build_cannot_replace_active_facts(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    first = _objective_facts("How does temperature affect strength?")
    first_task = _write_build(source_repository, builds, "build_first", first)
    _finish(builds, first_task, success=True)

    failed = _objective_facts("How does speed affect strength?")
    failed_task = _write_build(source_repository, builds, "build_failed", failed)
    _finish(builds, failed_task, success=False)

    assert repository.read("col_source") == first
    assert repository.read("col_source", build_id="build_failed") == failed


def test_objective_lifecycle_pins_confirmed_semantics_across_candidate_refresh(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    first = _objective_facts("How does temperature affect strength?")
    first_task = _write_build(source_repository, builds, "build_first", first)
    _finish(builds, first_task, success=True)

    candidate = repository.read_objective_workspace("col_source", "objective-1")
    assert candidate is not None
    assert candidate.status == "candidate"
    assert candidate.source_build_id == "build_first"

    confirmed = repository.confirm_objective("col_source", "objective-1")
    assert confirmed.status == "confirmed"
    assert confirmed.source_build_id == "build_first"

    refreshed = _objective_facts("How does speed affect strength?")
    refreshed_task = _write_build(
        source_repository,
        builds,
        "build_refreshed",
        refreshed,
    )
    _finish(builds, refreshed_task, success=True)

    workspaces = repository.list_objective_workspaces("col_source")
    assert [(item.objective_id, item.question, item.status) for item in workspaces] == [
        (
            "objective-1",
            "How does temperature affect strength?",
            "confirmed",
        )
    ]
    assert repository.confirm_objective("col_source", "objective-1").status == "confirmed"


def test_objective_analysis_lifecycle_is_idempotent_and_claims_once(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    task = _write_build(
        source_repository,
        builds,
        "build_lifecycle",
        _objective_facts(),
    )
    _finish(builds, task, success=True)

    with pytest.raises(ValueError, match="candidate -> queued"):
        repository.queue_objective_analysis("col_source", "objective-1")

    repository.confirm_objective("col_source", "objective-1")
    first_queue = repository.queue_objective_analysis("col_source", "objective-1")
    second_queue = repository.queue_objective_analysis("col_source", "objective-1")
    assert first_queue.status == second_queue.status == "queued"

    claimed = repository.claim_objective_analysis("col_source", "objective-1")
    assert claimed is not None
    assert claimed.status == "running"
    assert repository.claim_objective_analysis("col_source", "objective-1") is None

    progressed = repository.update_objective_analysis_progress(
        "col_source",
        "objective-1",
        {"phase": "routing", "current": 1, "total": 2},
    )
    assert progressed.analysis_progress == {
        "phase": "routing",
        "current": 1,
        "total": 2,
    }

    ready = repository.mark_objective_analysis_ready("col_source", "objective-1")
    assert ready.status == "ready"
    assert ready.analysis_error is None
    assert ready.analysis_progress == {
        "phase": "completed",
        "unit": "steps",
        "message": "Objective analysis is ready.",
    }
    assert repository.queue_objective_analysis("col_source", "objective-1").status == "queued"


def test_objective_analysis_failure_keeps_error_and_is_retryable(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    task = _write_build(
        source_repository,
        builds,
        "build_failed_analysis",
        _objective_facts(),
    )
    _finish(builds, task, success=True)
    repository.confirm_objective("col_source", "objective-1")
    repository.queue_objective_analysis("col_source", "objective-1")
    repository.claim_objective_analysis("col_source", "objective-1")

    failed = repository.mark_objective_analysis_failed(
        "col_source",
        "objective-1",
        "model request failed",
    )
    assert failed.status == "failed"
    assert failed.analysis_error == "model request failed"

    retried = repository.queue_objective_analysis("col_source", "objective-1")
    assert retried.status == "queued"
    assert retried.analysis_error is None


def test_objective_replacement_is_atomic_for_invalid_links(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    original = _objective_facts()
    _write_build(source_repository, builds, "build_invalid", original)

    invalid_chain = replace(
        original.objective_logic_chains[0],
        evidence_unit_ids=("missing-unit",),
    )
    with pytest.raises(IntegrityError):
        repository.replace(
            "col_source",
            "build_invalid",
            replace(original, objective_logic_chains=(invalid_chain,)),
        )
    assert repository.read("col_source", build_id="build_invalid") == original

    invalid_route = replace(original.objective_evidence_routes[0], source_ref="missing")
    with pytest.raises(FileNotFoundError, match="objective source not found"):
        repository.replace(
            "col_source",
            "build_invalid",
            replace(original, objective_evidence_routes=(invalid_route,)),
        )
    assert repository.read("col_source", build_id="build_invalid") == original


def test_objective_repository_rejects_missing_paper_fact_anchor(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    facts = _objective_facts()
    task = _task("task_missing_anchor")
    builds.add_task(task, build_id="build_missing_anchor")
    source_repository.replace_collection_artifacts(
        "col_source", "build_missing_anchor", _artifacts()
    )

    with pytest.raises(IntegrityError):
        PostgresObjectiveRepository(source_repository.session_factory).replace(
            "col_source", "build_missing_anchor", facts
        )


def test_typed_source_identity_rejects_mismatched_public_reference(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    _write_build(
        source_repository,
        builds,
        "build_source_identity",
        _objective_facts(),
    )

    with pytest.raises(IntegrityError):
        with source_repository.session_factory.begin() as session:
            route = session.get(
                ObjectiveEvidenceRouteRecord,
                ("build_source_identity", "route-1"),
            )
            assert route is not None
            route.source_ref = "block-1"

    with pytest.raises(IntegrityError):
        with source_repository.session_factory.begin() as session:
            session.execute(
                objective_unit_source_refs.update()
                .where(
                    objective_unit_source_refs.c.build_id == "build_source_identity",
                    objective_unit_source_refs.c.evidence_unit_id == "unit-1",
                    objective_unit_source_refs.c.position == 0,
                )
                .values(source_ref="block-1")
            )


def test_objective_unit_read_uses_relational_source_identity(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    _write_build(
        source_repository,
        builds,
        "build_relational_source_identity",
        _objective_facts(),
    )

    with source_repository.session_factory.begin() as session:
        session.execute(
            objective_unit_source_refs.update()
            .where(
                objective_unit_source_refs.c.build_id
                == "build_relational_source_identity",
                objective_unit_source_refs.c.evidence_unit_id == "unit-1",
                objective_unit_source_refs.c.position == 0,
            )
            .values(
                metadata_json={
                    "source_kind": "figure",
                    "source_ref": "figure-not-authoritative",
                    "page": 1,
                }
            )
        )

    facts = repository.read(
        "col_source",
        build_id="build_relational_source_identity",
    )

    assert facts.objective_evidence_units[0].source_refs[0] == {
        "source_kind": "table",
        "source_ref": "table-1",
        "page": 1,
    }


def test_objective_document_lineage_is_owned_by_source_documents() -> None:
    document_scoped_models = (
        ObjectivePaperSkim,
        ObjectivePaperFrameRecord,
        ObjectiveEvidenceRouteRecord,
        ObjectiveEvidenceUnitRecord,
        ObjectiveLogicChainRecord,
    )

    assert all(
        "document_version_id" not in model.__table__.columns
        for model in document_scoped_models
    )


def test_objective_context_cannot_escape_parent_collection(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    facts = _objective_facts()
    _write_build(source_repository, builds, "build_context_scope", facts)

    with pytest.raises(IntegrityError):
        with source_repository.session_factory.begin() as session:
            context = session.get(
                ObjectiveContextRecord,
                ("build_context_scope", "objective-1"),
            )
            assert context is not None
            context.collection_id = "col_other"


def test_documentless_logic_chain_cannot_escape_parent_collection(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    facts = _objective_facts()
    _write_build(source_repository, builds, "build_chain_scope", facts)

    with pytest.raises(IntegrityError):
        with source_repository.session_factory.begin() as session:
            session.add(
                ObjectiveLogicChainRecord(
                    build_id="build_chain_scope",
                    logic_chain_id="chain-cross-collection",
                    collection_id="col_other",
                    objective_id="objective-1",
                    chain_order=1,
                    chain_scope="cross_paper",
                    source_document_id=None,
                    question="Cross-paper chain",
                    chain_payload={},
                    summary=None,
                    confidence=0.8,
                )
            )


def test_postgresql_enforces_objective_contract() -> None:
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
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            command.upgrade(config, "head")
        sessions = build_session_factory(engine)
        PostgresAuthRepository(sessions).add_user(
            {
                "user_id": "user_objectives",
                "email": "objectives@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat(),
            }
        )
        collections = PostgresCollectionRepository(sessions)
        collections.add_collection(
            CollectionRecord(
                collection_id="col_source",
                owner_user_id="user_objectives",
                name="Objective collection",
                description=None,
                status="idle",
                paper_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        collections.add_collection_import(
            _collection_import("stored-paper.pdf"),
            updated_at=NOW,
        )
        source_repository = PostgresSourceArtifactRepository(sessions)
        builds = PostgresBuildRepository(sessions)
        repository = PostgresObjectiveRepository(sessions)
        facts = _objective_facts()
        facts = replace(
            facts,
            research_objectives=tuple(
                replace(item, seed_document_ids=(REAL_SOURCE_DOCUMENT_ID,))
                for item in facts.research_objectives
            ),
            objective_contexts=tuple(
                replace(
                    item,
                    routing_hints=(
                        {"table_id": REAL_SOURCE_TABLE_ID, "role": "result_table"},
                    ),
                )
                for item in facts.objective_contexts
            ),
            paper_skims=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.paper_skims
            ),
            objective_paper_frames=tuple(
                replace(
                    item,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    relevant_tables=(REAL_SOURCE_TABLE_ID,),
                )
                for item in facts.objective_paper_frames
            ),
            objective_evidence_routes=tuple(
                replace(
                    item,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    source_ref=REAL_SOURCE_TABLE_ID,
                )
                for item in facts.objective_evidence_routes
            ),
            objective_evidence_units=tuple(
                replace(
                    item,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    source_refs=(
                        {
                            "source_kind": "table",
                            "source_ref": REAL_SOURCE_TABLE_ID,
                            "page": 1,
                        },
                        {
                            "source_kind": "text_window",
                            "source_ref": REAL_SOURCE_BLOCK_ID,
                            "role": "test_condition",
                        },
                    ),
                )
                for item in facts.objective_evidence_units
            ),
            objective_logic_chains=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in facts.objective_logic_chains
            ),
        )
        task = _task("task_build_objectives_postgresql")
        builds.add_task(task, build_id="build_objectives_postgresql")
        source_repository.replace_collection_artifacts(
            "col_source",
            "build_objectives_postgresql",
            _real_shape_artifacts(),
        )
        paper_facts = _paper_facts()
        paper_facts = replace(
            paper_facts,
            document_profiles=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.document_profiles
            ),
            evidence_anchors=tuple(
                replace(
                    item,
                    document_id=REAL_SOURCE_DOCUMENT_ID,
                    block_id=REAL_SOURCE_BLOCK_ID,
                    figure_or_table=REAL_SOURCE_TABLE_ID,
                )
                for item in paper_facts.evidence_anchors
            ),
            method_facts=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.method_facts
            ),
            sample_variants=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.sample_variants
            ),
            test_conditions=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.test_conditions
            ),
            baseline_references=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.baseline_references
            ),
            measurement_results=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.measurement_results
            ),
            characterization_observations=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.characterization_observations
            ),
            structure_features=tuple(
                replace(item, document_id=REAL_SOURCE_DOCUMENT_ID)
                for item in paper_facts.structure_features
            ),
        )
        paper_repository = PostgresPaperFactRepository(sessions)
        paper_repository.replace_document_profiles(
            "col_source",
            "build_objectives_postgresql",
            paper_facts.document_profiles,
        )
        paper_repository.replace_paper_facts(
            "col_source",
            "build_objectives_postgresql",
            paper_facts,
        )
        repository.replace("col_source", "build_objectives_postgresql", facts)

        assert repository.read("col_source") == ObjectiveFactSet()
        assert (
            repository.read(
                "col_source",
                build_id="build_objectives_postgresql",
            )
            == facts
        )
        with pytest.raises(IntegrityError):
            with sessions.begin() as session:
                route = session.get(
                    ObjectiveEvidenceRouteRecord,
                    ("build_objectives_postgresql", "route-1"),
                )
                assert route is not None
                route.source_ref = "block-1"
        with pytest.raises(IntegrityError):
            with sessions.begin() as session:
                context = session.get(
                    ObjectiveContextRecord,
                    ("build_objectives_postgresql", "objective-1"),
                )
                assert context is not None
                context.collection_id = "col_other"

        _finish(builds, task, success=True)

        assert repository.read("col_source") == facts

        barrier = Barrier(2)

        def confirm() -> ResearchObjective:
            barrier.wait()
            return repository.confirm_objective("col_source", "objective-1")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(confirm), executor.submit(confirm))
            confirmed = tuple(future.result() for future in futures)

        assert [objective.status for objective in confirmed] == [
            "confirmed",
            "confirmed",
        ]

        queue_barrier = Barrier(2)

        def queue() -> ResearchObjective:
            queue_barrier.wait()
            return repository.queue_objective_analysis("col_source", "objective-1")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(queue), executor.submit(queue))
            queued = tuple(future.result() for future in futures)

        assert [objective.status for objective in queued] == ["queued", "queued"]

        claim_barrier = Barrier(2)

        def claim() -> ResearchObjective | None:
            claim_barrier.wait()
            return repository.claim_objective_analysis("col_source", "objective-1")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (executor.submit(claim), executor.submit(claim))
            claimed = tuple(future.result() for future in futures)

        assert sum(objective is not None for objective in claimed) == 1
        assert next(objective for objective in claimed if objective is not None).status == (
            "running"
        )
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE collections CASCADE"))
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        engine.dispose()
