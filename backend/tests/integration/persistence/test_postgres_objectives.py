from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from domain.core import (
    Finding,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperStudyDisposition,
    PaperStudySourceRef,
    PaperSkim,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats, ModelUsage, TokenUsage
from domain.source import CollectionRecord
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.objective_repository import PostgresObjectiveRepository
from infra.persistence.postgres.source_artifact_repository import (
    PostgresSourceArtifactRepository,
)
from tests.integration.persistence.database_cleanup import reset_postgres_schema
from tests.integration.persistence.test_postgres_source_artifacts import (
    BACKEND_ROOT,
    NOW,
    REAL_SOURCE_DOCUMENT_ID,
    REAL_SOURCE_ROW_ID,
    _artifacts,
    _collection_import,
    _finish,
    _real_shape_artifacts,
    _task,
)

pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)


def _objective(
    question: str = "How does temperature affect strength?",
    *,
    objective_id: str = "objective-1",
) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": objective_id,
            "question": question,
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "requested_comparator": "compare temperature conditions",
            "seed_document_ids": ["srcdoc_runtime"],
            "confidence": 0.9,
            "reason": "The paper reports comparable measurements.",
            "source_relationship_ids": ["relationship-1"],
            "rank": 1,
        }
    )


def _study_facts(objective: ResearchObjective | None = None) -> ObjectiveFactSet:
    return ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=(
            PaperSkim.from_mapping(
                {
                    "document_id": "srcdoc_runtime",
                    "doc_role": "primary_experiment",
                    "studies": [
                        {
                            "study_id": "study-1",
                            "design_type": "experimental",
                            "claim_scope": "current_work",
                            "experiment_label": "temperature series",
                            "material_scope": ["Alloy A"],
                            "relationships": [
                                {
                                    "relationship_id": "relationship-1",
                                    "varied_factors": ["temperature"],
                                    "outcome": "strength",
                                    "source_refs": [
                                        {
                                            "source_kind": "block",
                                            "source_ref": "block-support-1",
                                        }
                                    ],
                                    "confidence": 0.9,
                                }
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "unresolved_signals": [
                        {
                            "signal_type": "outcome",
                            "label": "hardness",
                            "design_type": "experimental",
                            "claim_scope": "current_work",
                            "material_scope": ["Alloy A"],
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "block-context",
                                }
                            ],
                            "confidence": 0.7,
                            "reason": "No changed variable was identified.",
                        }
                    ],
                    "source_unit_coverage": [
                        {
                            "source_unit_id": "results-1-source-1",
                            "window_id": "results-1",
                            "source_kind": "block",
                            "source_ref": "block-support-1",
                            "status": "relationship_emitted",
                        },
                        {
                            "source_unit_id": "results-1-source-2",
                            "window_id": "results-1",
                            "source_kind": "block",
                            "source_ref": "block-context",
                            "status": "unresolved_signal_emitted",
                        },
                        {
                            "source_unit_id": "results-1-source-3",
                            "window_id": "results-1",
                            "source_kind": "block",
                            "source_ref": "block-mechanism",
                            "status": "no_study_signal",
                            "reason": "The unit contains mechanism context only.",
                        },
                        {
                            "source_unit_id": "results-1-source-4",
                            "window_id": "results-1",
                            "source_kind": "block",
                            "source_ref": "block-support-1",
                            "status": "extraction_failed",
                            "reason": "The window response failed validation.",
                        },
                    ],
                    "evidence_density": "high",
                    "confidence": 0.9,
                }
            ),
        ),
        research_objectives=(objective or _objective(),),
        study_dispositions=(
            PaperStudyDisposition.from_mapping(
                {
                    "document_id": "srcdoc_runtime",
                    "study_id": "study-1",
                    "relationship_id": "relationship-1",
                    "status": "promoted",
                    "objective_id": (objective or _objective()).objective_id,
                }
            ),
        ),
    )


def _analysis_artifacts():
    source_document = _artifacts()[0]
    source_document_ids = (
        "srcdoc_runtime",
        "srcdoc_supporting",
        "srcdoc_contradicting",
        "srcdoc_excluded",
    )
    blocks = tuple(
        replace(
            source_document.blocks[0],
            block_id=block_id,
            document_id=document_id,
            text=text,
            text_unit_ids=(),
        )
        for block_id, document_id, text in (
            ("block-support-1", source_document_ids[0], "Strength increased."),
            ("block-support-2", source_document_ids[1], "Strength increased."),
            ("block-contradict", source_document_ids[2], "Strength decreased."),
            ("block-context", source_document_ids[0], "Tests used ambient air."),
            ("block-mechanism", source_document_ids[0], "Grain refinement occurred."),
        )
    )
    return tuple(
        replace(
            source_document,
            document_id=document_id,
            document_order=position,
            title=f"Paper {position + 1}",
            text_units=(),
            blocks=tuple(
                block for block in blocks if block.document_id == document_id
            ),
            tables=(),
            table_rows=(),
            table_cells=(),
            figures=(),
        )
        for position, document_id in enumerate(source_document_ids)
    )


def _prepare_studies(source_repository, builds, build_id: str = "build_objectives"):
    task = _task(f"task_{build_id}")
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_documents(
        "col_source", build_id, _analysis_artifacts()
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    repository.replace("col_source", build_id, _study_facts())
    _finish(builds, task, success=True)
    return repository


def _contribution(
    version: int,
    document_id: str = "srcdoc_runtime",
    *,
    analysis_status: str = "analyzed",
) -> PaperContribution:
    return PaperContribution.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "document_id": document_id,
            "analysis_status": analysis_status,
            "relevance": "high" if analysis_status == "analyzed" else "none",
            "paper_role": "primary_experiment",
            "contribution_summary": "Direct experimental evidence.",
            "material_match": ["Alloy A"],
            "changed_variables": ["temperature"],
            "measured_property_scope": ["strength"],
            "test_environment_scope": ["ambient"],
            "exclusion_reason": (
                "Outside the confirmed Objective scope."
                if analysis_status == "excluded"
                else None
            ),
            "confidence": 0.9,
            "evidence_disposition": (
                "excluded"
                if analysis_status == "excluded"
                else "comparable_evidence"
            ),
            "routed_source_count": 0 if analysis_status == "excluded" else 1,
            "extracted_source_count": 0 if analysis_status == "excluded" else 1,
            "comparable_evidence_count": (
                0 if analysis_status == "excluded" else 1
            ),
            "failed_source_count": 0,
        }
    )


def _evidence(
    version: int,
    evidence_id: str = "evidence-support-1",
    document_id: str = "srcdoc_runtime",
    source_ref: str = "block-support-1",
    *,
    evidence_role: str = "direct_result",
    direction: str = "increase",
    confidence: float = 0.9,
) -> ObjectiveEvidence:
    is_result = evidence_role in {"direct_result", "contradictory_result"}
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "evidence_id": evidence_id,
            "document_id": document_id,
            "source_kind": "text_window",
            "source_ref": source_ref,
            "source_excerpt": "Strength increased from 90 to 100 MPa at 600 C.",
            "page_numbers": [1],
            "evidence_role": evidence_role,
            "selection_status": "extracted",
            "selection_reason": "Reports measured strength.",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ] if is_result else [],
            "comparison": {
                "baseline_label": "500 C",
                "target_label": "600 C",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            } if is_result else None,
            "reported_result": {
                "outcome": "strength",
                "value": 100,
                "unit": "MPa",
                "direction": direction,
                "result_text": "Strength increased from 90 to 100 MPa.",
            } if is_result else None,
            "attribution_scope": (
                "isolated_effect" if is_result else "descriptive_only"
            ),
            "scientific_context": {
                "material": [{"name": "name", "value": "Alloy A"}],
                "sample": [],
                "process": [{"name": "temperature", "value": 600, "unit": "C"}],
                "test": [{"name": "environment", "value": "ambient"}],
            },
            "resolution_status": "resolved",
            "confidence": confidence,
        }
    )


def _finding(version: int) -> Finding:
    return Finding.from_mapping(
        {
            "collection_id": "col_source",
            "objective_id": "objective-1",
            "analysis_version": version,
            "finding_id": "finding-1",
            "statement": "Temperature was associated with strength under reported conditions.",
            "factors": ["temperature"],
            "outcome": "strength",
            "direction": "increase",
            "assertion_strength": "associative",
            "attribution_scope": "isolated_effect",
            "synthesis_status": "condition_dependent",
            "certainty": 0.7,
            "display_rank": 0,
            "mechanisms": [
                {
                    "source_term": "temperature",
                    "relation_type": "changes",
                    "target_term": "grain refinement",
                    "direction": "increase",
                    "assertion_strength": "descriptive",
                    "supporting_evidence_ids": ["evidence-mechanism"],
                }
            ],
            "scientific_context": {
                "material": [{"name": "name", "value": "Alloy A"}],
                "sample": [],
                "process": [{"name": "temperature", "value": 600, "unit": "C"}],
                "test": [{"name": "environment", "value": "ambient"}],
            },
            "limitations": ["The papers report an explicit condition boundary."],
            "paper_contributions": [
                {
                    "document_id": "srcdoc_runtime",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-support-1"],
                    "context_evidence_ids": [
                        "evidence-context",
                        "evidence-mechanism",
                    ],
                    "condition_boundary_evidence_ids": ["evidence-context"],
                },
                {
                    "document_id": "srcdoc_supporting",
                    "analysis_status": "analyzed",
                    "supporting_evidence_ids": ["evidence-support-2"],
                },
                {
                    "document_id": "srcdoc_contradicting",
                    "analysis_status": "analyzed",
                    "contradicting_evidence_ids": ["evidence-contradict"],
                },
                {
                    "document_id": "srcdoc_excluded",
                    "analysis_status": "excluded",
                },
            ],
        }
    )


def _analysis_contributions(version: int) -> tuple[PaperContribution, ...]:
    return (
        _contribution(version),
        _contribution(version, "srcdoc_supporting"),
        _contribution(version, "srcdoc_contradicting"),
        _contribution(version, "srcdoc_excluded", analysis_status="excluded"),
    )


def _analysis_evidence(version: int) -> tuple[ObjectiveEvidence, ...]:
    return (
        _evidence(version),
        _evidence(
            version,
            "evidence-support-2",
            "srcdoc_supporting",
            "block-support-2",
            confidence=0.8,
        ),
        _evidence(
            version,
            "evidence-contradict",
            "srcdoc_contradicting",
            "block-contradict",
            evidence_role="contradictory_result",
            direction="decrease",
            confidence=0.7,
        ),
        _evidence(
            version,
            "evidence-context",
            "srcdoc_runtime",
            "block-context",
            evidence_role="condition_context",
        ),
        _evidence(
            version,
            "evidence-mechanism",
            "srcdoc_runtime",
            "block-mechanism",
            evidence_role="mechanism_context",
        ),
    )


def _queue_and_claim(repository: PostgresObjectiveRepository):
    repository.confirm_objective("col_source", "objective-1")
    objective, queued = repository.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    claimed = repository.claim_analysis(
        "col_source", "objective-1", queued.analysis_version
    )
    assert claimed is not None
    assert claimed.total_document_count == 4
    return objective, claimed


def test_study_build_round_trips_without_analysis_artifacts(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds)

    facts = repository.read("col_source")
    assert facts.research_objectives_ready is True
    assert facts.paper_skims == _study_facts().paper_skims
    assert facts.study_dispositions == _study_facts().study_dispositions
    assert tuple(
        {
            key: value
            for key, value in item.to_record().items()
            if key not in {"created_at", "updated_at"}
        }
        for item in facts.research_objectives
    ) == tuple(
        {
            key: value
            for key, value in item.to_record().items()
            if key not in {"created_at", "updated_at"}
        }
        for item in _study_facts().research_objectives
    )
    assert repository.list_objectives("col_source")[0].objective_id == "objective-1"
    objective = repository.read_objective("col_source", "objective-1")
    assert objective is not None
    assert objective.source_relationship_ids == ("relationship-1",)
    assert objective.rank == 1
    assert repository.read_published_analysis("col_source", "objective-1") is None


def test_study_build_round_trips_table_row_source_locator(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task = _task("task_table_row_objective_source")
    build_id = "build_table_row_objective_source"
    builds.add_task(task, build_id=build_id)
    source_artifacts = _artifacts()
    source_document = source_artifacts[0]
    long_row_id = f"row-{'x' * 300}"
    source_repository.replace_collection_documents(
        "col_source",
        build_id,
        tuple(
            replace(
                document,
                tables=source_document.tables,
                table_rows=(
                    replace(source_document.table_rows[0], row_id=long_row_id),
                ),
            )
            if document.document_id == source_document.document_id
            else document
            for document in _analysis_artifacts()
        ),
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    facts = _study_facts()
    skim = facts.paper_skims[0]
    study = skim.studies[0]
    relationship = replace(
        study.relationships[0],
        source_refs=(PaperStudySourceRef("table_row", long_row_id),),
    )
    coverage = replace(
        skim.source_unit_coverage[0],
        source_kind="table_row",
        source_ref=long_row_id,
    )
    row_facts = replace(
        facts,
        paper_skims=(
            replace(
                skim,
                studies=(replace(study, relationships=(relationship,)),),
                source_unit_coverage=(coverage, *skim.source_unit_coverage[1:]),
            ),
        ),
    )

    repository.replace("col_source", build_id, row_facts)

    persisted_skim = repository.read(
        "col_source", build_id=build_id
    ).paper_skims[0]
    persisted_relationship = persisted_skim.studies[0].relationships[0]
    assert [
        source_ref.to_record()
        for source_ref in persisted_relationship.source_refs
    ] == [{"source_kind": "table_row", "source_ref": long_row_id}]
    assert persisted_skim.source_unit_coverage[0].source_ref == long_row_id


def test_postgresql_round_trips_long_source_unit_coverage_locator() -> None:
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

    assert len(REAL_SOURCE_ROW_ID) > 160
    engine = create_engine(url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        reset_postgres_schema(engine)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        sessions = build_session_factory(engine)
        PostgresAuthRepository(sessions).add_user(
            {
                "user_id": "user_source",
                "email": "source@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
            }
        )
        collections = PostgresCollectionRepository(sessions)
        collections.add_collection(
            CollectionRecord(
                collection_id="col_source",
                owner_user_id="user_source",
                name="Source collection",
                description=None,
                status="idle",
                paper_count=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        collections.add_collection_import(
            _collection_import("stored-paper.pdf"), updated_at=NOW
        )
        source_repository = PostgresSourceArtifactRepository(sessions)
        builds = PostgresBuildRepository(sessions)
        build_id = "build_objectives_postgresql"
        builds.add_task(_task("task_objectives_postgresql"), build_id=build_id)
        source_repository.replace_collection_documents(
            "col_source",
            build_id,
            _real_shape_artifacts(),
        )
        relationship_id = "relationship-long-row"
        skim = PaperSkim.from_mapping(
            {
                "document_id": REAL_SOURCE_DOCUMENT_ID,
                "doc_role": "primary_experiment",
                "studies": [
                    {
                        "study_id": "study-long-row",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "relationships": [
                            {
                                "relationship_id": relationship_id,
                                "varied_factors": ["temperature"],
                                "outcome": "strength",
                                "source_refs": [
                                    {
                                        "source_kind": "table_row",
                                        "source_ref": REAL_SOURCE_ROW_ID,
                                    }
                                ],
                                "confidence": 0.9,
                            }
                        ],
                        "confidence": 0.9,
                    }
                ],
                "source_unit_coverage": [
                    {
                        "source_unit_id": "results-1-source-1",
                        "window_id": "results-1",
                        "source_kind": "table_row",
                        "source_ref": REAL_SOURCE_ROW_ID,
                        "status": "relationship_emitted",
                    }
                ],
                "evidence_density": "high",
                "confidence": 0.9,
            }
        )
        objective = ResearchObjective.from_mapping(
            {
                "collection_id": "col_source",
                "objective_id": "objective-long-row",
                "question": "How does temperature affect strength?",
                "variables": ["temperature"],
                "outcomes": ["strength"],
                "seed_document_ids": [REAL_SOURCE_DOCUMENT_ID],
                "source_relationship_ids": [relationship_id],
                "rank": 1,
                "confidence": 0.9,
            }
        )
        facts = ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(skim,),
            research_objectives=(objective,),
            study_dispositions=(
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": REAL_SOURCE_DOCUMENT_ID,
                        "study_id": "study-long-row",
                        "relationship_id": relationship_id,
                        "status": "promoted",
                        "objective_id": objective.objective_id,
                    }
                ),
            ),
        )
        repository = PostgresObjectiveRepository(sessions)

        repository.replace("col_source", build_id, facts)

        persisted = repository.read("col_source", build_id=build_id)
        assert persisted.paper_skims[0].source_unit_coverage[0].source_ref == (
            REAL_SOURCE_ROW_ID
        )
        assert (
            persisted.paper_skims[0].studies[0].relationships[0].source_refs[0].source_ref
            == REAL_SOURCE_ROW_ID
        )
    finally:
        reset_postgres_schema(engine)
        engine.dispose()


def test_confirmed_objective_rebuild_scopes_lineage_and_analysis_to_each_build(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds, "build_initial_scope")
    _objective_row, analysis = _queue_and_claim(repository)
    repository.publish_analysis(
        "col_source",
        "objective-1",
        analysis.analysis_version,
        contributions=_analysis_contributions(analysis.analysis_version),
        evidence_records=_analysis_evidence(analysis.analysis_version),
        findings=(_finding(analysis.analysis_version),),
    )

    initial_facts = _study_facts()
    supporting_skim = PaperSkim.from_mapping(
        {
            "document_id": "srcdoc_supporting",
            "doc_role": "primary_experiment",
            "studies": [
                {
                    "study_id": "study-2",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "experiment_label": "supporting temperature series",
                    "material_scope": ["Alloy A"],
                    "relationships": [
                        {
                            "relationship_id": "relationship-2",
                            "varied_factors": ["temperature"],
                            "outcome": "strength",
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": "block-support-2",
                                }
                            ],
                            "confidence": 0.8,
                        }
                    ],
                    "confidence": 0.8,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.8,
        }
    )
    supporting_disposition = PaperStudyDisposition.from_mapping(
        {
            "document_id": "srcdoc_supporting",
            "study_id": "study-2",
            "relationship_id": "relationship-2",
            "status": "promoted",
            "objective_id": "objective-1",
        }
    )
    expanded_objective = replace(
        initial_facts.research_objectives[0],
        seed_document_ids=("srcdoc_runtime", "srcdoc_supporting"),
        excluded_document_ids=("srcdoc_excluded",),
        source_relationship_ids=("relationship-1", "relationship-2"),
    )
    expanded_facts = replace(
        initial_facts,
        paper_skims=(*initial_facts.paper_skims, supporting_skim),
        research_objectives=(expanded_objective,),
        study_dispositions=(
            *initial_facts.study_dispositions,
            supporting_disposition,
        ),
    )
    expanded_task = _task("task_expanded_objective_scope")
    expanded_build_id = "build_expanded_objective_scope"
    builds.add_task(expanded_task, build_id=expanded_build_id)
    source_repository.replace_collection_documents(
        "col_source", expanded_build_id, _analysis_artifacts()
    )

    repository.replace("col_source", expanded_build_id, expanded_facts)
    _finish(builds, expanded_task, success=True)

    expanded = repository.read("col_source").research_objectives[0]
    assert expanded.seed_document_ids == (
        "srcdoc_runtime",
        "srcdoc_supporting",
    )
    assert expanded.source_relationship_ids == (
        "relationship-1",
        "relationship-2",
    )
    assert expanded.excluded_document_ids == ("srcdoc_excluded",)
    assert expanded.confirmation_status == "confirmed"
    assert expanded.active_analysis_version is None
    assert expanded.published_analysis_version is None
    assert repository.read_published_analysis("col_source", "objective-1") is None

    contracted_objective = replace(
        initial_facts.research_objectives[0],
        seed_document_ids=("srcdoc_supporting",),
        excluded_document_ids=("srcdoc_contradicting",),
        source_relationship_ids=("relationship-2",),
    )
    contracted_facts = ObjectiveFactSet(
        research_objectives_ready=True,
        paper_skims=(supporting_skim,),
        research_objectives=(contracted_objective,),
        study_dispositions=(supporting_disposition,),
    )
    contracted_task = _task("task_contracted_objective_scope")
    contracted_build_id = "build_contracted_objective_scope"
    builds.add_task(contracted_task, build_id=contracted_build_id)
    source_repository.replace_collection_documents(
        "col_source", contracted_build_id, _analysis_artifacts()
    )

    repository.replace("col_source", contracted_build_id, contracted_facts)
    _finish(builds, contracted_task, success=True)

    active_facts = repository.read("col_source")
    contracted = active_facts.research_objectives[0]
    assert contracted.seed_document_ids == ("srcdoc_supporting",)
    assert contracted.excluded_document_ids == ("srcdoc_contradicting",)
    assert contracted.source_relationship_ids == ("relationship-2",)
    assert contracted.confirmation_status == "confirmed"
    assert contracted.active_analysis_version is None
    assert contracted.published_analysis_version is None
    assert active_facts.study_dispositions == (supporting_disposition,)
    initial = repository.read(
        "col_source", build_id="build_initial_scope"
    ).research_objectives[0]
    assert initial.seed_document_ids == ("srcdoc_runtime",)
    assert initial.excluded_document_ids == ()
    assert initial.source_relationship_ids == ("relationship-1",)
    assert initial.active_analysis_version == analysis.analysis_version
    assert initial.published_analysis_version == analysis.analysis_version
    expanded_history = repository.read(
        "col_source", build_id="build_expanded_objective_scope"
    ).research_objectives[0]
    assert expanded_history.excluded_document_ids == ("srcdoc_excluded",)
    assert expanded_history.active_analysis_version is None
    assert expanded_history.published_analysis_version is None
    persisted_analysis = repository.read_analysis(
        "col_source", "objective-1", analysis.analysis_version
    )
    assert persisted_analysis.source_build_id == "build_initial_scope"
    assert persisted_analysis.status == "succeeded"


def test_rebuild_rejects_reused_objective_id_for_another_scientific_definition(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds, "build_confirmed_identity")
    repository.confirm_objective("col_source", "objective-1")

    initial_facts = _study_facts()
    skim = initial_facts.paper_skims[0]
    study = skim.studies[0]
    changed_relationship = replace(
        study.relationships[0],
        varied_factors=("pressure",),
        outcome="hardness",
    )
    changed_objective = ResearchObjective.from_mapping(
        {
            **initial_facts.research_objectives[0].to_record(),
            "question": "How does pressure affect hardness?",
            "variables": ["pressure"],
            "outcomes": ["hardness"],
        }
    )
    changed_facts = replace(
        initial_facts,
        paper_skims=(
            replace(
                skim,
                studies=(replace(study, relationships=(changed_relationship,)),),
            ),
        ),
        research_objectives=(changed_objective,),
    )
    task = _task("task_conflicting_objective_identity")
    build_id = "build_conflicting_objective_identity"
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_documents(
        "col_source", build_id, _analysis_artifacts()
    )

    with pytest.raises(ValueError, match="research objective identity collision"):
        repository.replace("col_source", build_id, changed_facts)

    confirmed = repository.read_objective("col_source", "objective-1")
    assert confirmed is not None
    assert confirmed.question == "How does temperature affect strength?"
    assert confirmed.variables == ("temperature",)
    assert confirmed.outcomes == ("strength",)
    assert confirmed.confirmation_status == "confirmed"
    assert repository.read("col_source", build_id=build_id) == ObjectiveFactSet()


@pytest.mark.parametrize("source_ref", ("missing-block", "block-support-2"))
def test_study_build_rejects_missing_or_cross_document_source_refs(
    source_repositories,
    source_ref: str,
) -> None:
    source_repository, builds = source_repositories
    task = _task("task_invalid_objective_source")
    build_id = "build_invalid_objective_source"
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_documents(
        "col_source", build_id, _analysis_artifacts()
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    facts = _study_facts()
    skim = facts.paper_skims[0]
    study = skim.studies[0]
    relationship = replace(
        study.relationships[0],
        source_refs=(PaperStudySourceRef("block", source_ref),),
    )
    invalid_facts = replace(
        facts,
        paper_skims=(
            replace(skim, studies=(replace(study, relationships=(relationship,)),)),
        ),
    )

    with pytest.raises(FileNotFoundError, match="paper study source not found"):
        repository.replace("col_source", build_id, invalid_facts)

    assert repository.read("col_source", build_id=build_id) == ObjectiveFactSet()


def test_study_build_rejects_invalid_source_unit_coverage_ref(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    task = _task("task_invalid_objective_coverage_source")
    build_id = "build_invalid_objective_coverage_source"
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_documents(
        "col_source", build_id, _analysis_artifacts()
    )
    repository = PostgresObjectiveRepository(source_repository.session_factory)
    facts = _study_facts()
    skim = facts.paper_skims[0]
    invalid_coverage = replace(
        skim.source_unit_coverage[0],
        source_ref="block-support-2",
    )

    with pytest.raises(FileNotFoundError, match="paper study source not found"):
        repository.replace(
            "col_source",
            build_id,
            replace(
                facts,
                paper_skims=(
                    replace(
                        skim,
                        source_unit_coverage=(
                            invalid_coverage,
                            *skim.source_unit_coverage[1:],
                        ),
                    ),
                ),
            ),
        )

    assert repository.read("col_source", build_id=build_id) == ObjectiveFactSet()


def test_list_objectives_uses_only_the_active_ready_build_and_persisted_rank(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds, "build_stale_objectives")

    task = _task("task_ranked_objectives")
    build_id = "build_ranked_objectives"
    builds.add_task(task, build_id=build_id)
    source_repository.replace_collection_documents(
        "col_source", build_id, _analysis_artifacts()
    )
    skim = PaperSkim.from_mapping(
        {
            "document_id": "srcdoc_runtime",
            "doc_role": "primary_experiment",
            "studies": [
                {
                    "study_id": "study-z",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "relationship_id": "relationship-z",
                            "varied_factors": ["temperature"],
                            "outcome": "strength",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "block-support-1"}
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "confidence": 0.9,
                },
                {
                    "study_id": "study-a",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "relationships": [
                        {
                            "relationship_id": "relationship-a",
                            "varied_factors": ["ambient condition"],
                            "outcome": "hardness",
                            "source_refs": [
                                {"source_kind": "block", "source_ref": "block-context"}
                            ],
                            "confidence": 0.8,
                        }
                    ],
                    "confidence": 0.8,
                },
            ],
        }
    )
    objectives = (
        ResearchObjective.from_mapping(
            {
                "collection_id": "col_source",
                "objective_id": "objective-z",
                "question": "How does temperature affect strength?",
                "variables": ["temperature"],
                "outcomes": ["strength"],
                "seed_document_ids": ["srcdoc_runtime"],
                "source_relationship_ids": ["relationship-z"],
                "rank": 1,
                "confidence": 0.9,
            }
        ),
        ResearchObjective.from_mapping(
            {
                "collection_id": "col_source",
                "objective_id": "objective-a",
                "question": "How does ambient condition affect hardness?",
                "variables": ["ambient condition"],
                "outcomes": ["hardness"],
                "seed_document_ids": ["srcdoc_runtime"],
                "source_relationship_ids": ["relationship-a"],
                "rank": 2,
                "confidence": 0.8,
            }
        ),
    )
    dispositions = tuple(
        PaperStudyDisposition.from_mapping(
            {
                "document_id": "srcdoc_runtime",
                "study_id": study_id,
                "relationship_id": relationship_id,
                "status": "promoted",
                "objective_id": objective_id,
            }
        )
        for study_id, relationship_id, objective_id in (
            ("study-z", "relationship-z", "objective-z"),
            ("study-a", "relationship-a", "objective-a"),
        )
    )
    repository.replace(
        "col_source",
        build_id,
        ObjectiveFactSet(
            research_objectives_ready=True,
            paper_skims=(skim,),
            research_objectives=objectives,
            study_dispositions=dispositions,
        ),
    )
    _finish(builds, task, success=True)

    listed = repository.list_objectives("col_source")
    assert [item.objective_id for item in listed] == ["objective-z", "objective-a"]
    assert [item.rank for item in listed] == [1, 2]
    assert [item.source_relationship_ids for item in listed] == [
        ("relationship-z",),
        ("relationship-a",),
    ]
    active = repository.read_objective("col_source", "objective-z")
    assert active is not None
    assert active.source_relationship_ids == ("relationship-z",)
    assert active.rank == 1
    assert repository.read_objective("col_source", "objective-1") is None

    pending_task = _task("task_pending_objectives")
    pending_build_id = "build_pending_objectives"
    builds.add_task(pending_task, build_id=pending_build_id)
    source_repository.replace_collection_documents(
        "col_source", pending_build_id, _analysis_artifacts()
    )
    repository.replace(
        "col_source",
        pending_build_id,
        ObjectiveFactSet(
            paper_skims=(skim,),
            study_dispositions=tuple(
                PaperStudyDisposition.from_mapping(
                    {
                        "document_id": "srcdoc_runtime",
                        "study_id": study.study_id,
                        "relationship_id": relationship.relationship_id,
                        "status": "pending",
                    }
                )
                for study in skim.studies
                for relationship in study.relationships
            ),
        ),
    )
    _finish(builds, pending_task, success=True)

    assert repository.list_objectives("col_source") == ()
    assert repository.read_objective("col_source", "objective-z") is None


def test_authored_candidate_is_idempotent_and_survives_collection_rebuild(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(
        source_repository,
        builds,
        "build_authored_source",
    )
    candidate = ResearchObjective.from_mapping(
        {
            "collection_id": "col_source",
            "question": (
                "How does temperature affect strength under ambient conditions?"
            ),
            "material_scope": ["Alloy A"],
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "constraints": ["ambient conditions"],
            "seed_document_ids": ["srcdoc_runtime"],
            "confidence": 0.9,
            "reason": "Supported by one PaperSkim relationship context.",
            "origin": "chat_assisted",
            "created_by_user_id": "user_source",
            "created_by_tool_call_id": "call-authored-1",
        }
    )

    created = repository.create_authored_candidate(
        candidate,
        created_by_user_id="user_source",
        created_by_tool_call_id="call-authored-1",
    )
    retried = repository.create_authored_candidate(
        candidate,
        created_by_user_id="user_source",
        created_by_tool_call_id="call-authored-1",
    )

    assert retried == created
    assert created.confirmation_status == "candidate"
    assert created.origin == "chat_assisted"
    assert created.source_build_id == "build_authored_source"
    assert created.created_by_user_id == "user_source"
    assert created.created_by_tool_call_id == "call-authored-1"
    assert created.source_relationship_ids == ()
    assert created.rank == 2

    _prepare_studies(source_repository, builds, "build_after_authored")

    listed = repository.list_objectives("col_source")
    restored = repository.read_objective("col_source", created.objective_id)
    assert [item.objective_id for item in listed] == [
        "objective-1",
        created.objective_id,
    ]
    assert restored is not None
    assert restored.source_build_id == "build_authored_source"
    assert restored.rank == 2

    confirmed = repository.confirm_objective("col_source", created.objective_id)
    queued_objective, analysis = repository.queue_analysis(
        "col_source",
        created.objective_id,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={"finding": "v1"},
    )
    assert confirmed.confirmation_status == "confirmed"
    assert queued_objective.active_analysis_version == 1
    assert analysis.source_build_id == "build_authored_source"


def test_authored_candidate_rejects_reusing_tool_call_for_other_arguments(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds, "build_authored_collision")
    first = ResearchObjective.from_mapping(
        {
            "collection_id": "col_source",
            "question": "How does temperature affect strength?",
            "variables": ["temperature"],
            "outcomes": ["strength"],
            "seed_document_ids": ["srcdoc_runtime"],
            "confidence": 0.9,
            "origin": "chat_assisted",
            "created_by_user_id": "user_source",
            "created_by_tool_call_id": "call-authored-collision",
        }
    )
    second = ResearchObjective.from_mapping(
        {
            "collection_id": "col_source",
            "question": "How does temperature affect hardness?",
            "variables": ["temperature"],
            "outcomes": ["hardness"],
            "seed_document_ids": ["srcdoc_runtime"],
            "confidence": 0.8,
            "origin": "chat_assisted",
            "created_by_user_id": "user_source",
            "created_by_tool_call_id": "call-authored-collision",
        }
    )
    repository.create_authored_candidate(
        first,
        created_by_user_id="user_source",
        created_by_tool_call_id="call-authored-collision",
    )

    with pytest.raises(ValueError, match="different objective"):
        repository.create_authored_candidate(
            second,
            created_by_user_id="user_source",
            created_by_tool_call_id="call-authored-collision",
        )


def test_analysis_version_claim_progress_and_retry_are_explicit(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds)
    objective, claimed = _queue_and_claim(repository)

    assert objective.active_analysis_version == 1
    assert objective.source_relationship_ids == ("relationship-1",)
    assert objective.rank == 1
    assert claimed.status == "running"
    assert repository.claim_analysis("col_source", "objective-1", 1) is None
    progressed = repository.update_analysis_progress(
        "col_source",
        "objective-1",
        1,
        phase="evidence",
        processed_document_count=1,
        total_document_count=4,
        current_document_id="srcdoc_runtime",
        progress_message="Extracting evidence.",
    )
    assert progressed.phase == "evidence"

    still_running = repository.fail_analysis(
        "col_source",
        "objective-1",
        1,
        error_code="analysis_dispatch_failed",
        error_message="Worker submission failed.",
        expected_status="queued",
    )
    assert still_running.status == "running"

    failed = repository.fail_analysis(
        "col_source",
        "objective-1",
        1,
        error_code="provider_timeout",
        error_message="model unavailable",
    )
    assert failed.status == "failed"
    objective, retry = repository.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    assert retry.analysis_version == 2
    assert objective.active_analysis_version == 2


def test_analysis_execution_stats_round_trip_provider_usage(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)
    stats = ExecutionStats(
        duration_ms=1400,
        model_usage=(
            ModelUsage("merged-qwen", 2, TokenUsage(1800, 240, 2040)),
        ),
        prompt_versions={"paper_framing": "paper_framing.v1"},
    )

    updated = repository.update_analysis_execution_stats(
        "col_source",
        "objective-1",
        claimed.analysis_version,
        stats=stats,
        model_name="merged-qwen",
        prompt_versions={"paper_framing": "paper_framing.v1"},
    )

    assert updated.stats == stats
    assert updated.model_name == "merged-qwen"
    assert updated.prompt_versions == {"paper_framing": "paper_framing.v1"}
    persisted = repository.read_analysis(
        "col_source",
        "objective-1",
        claimed.analysis_version,
    )
    assert persisted is not None
    assert persisted.stats == stats
    assert persisted.model_name == "merged-qwen"
    assert persisted.prompt_versions == {"paper_framing": "paper_framing.v1"}


def test_publish_is_atomic_and_reads_findings_and_exact_evidence(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)
    version = claimed.analysis_version

    objective, succeeded = repository.publish_analysis(
        "col_source",
        "objective-1",
        version,
        contributions=_analysis_contributions(version),
        evidence_records=_analysis_evidence(version),
        findings=(_finding(version),),
    )

    assert succeeded.status == "succeeded"
    assert objective.published_analysis_version == version
    published = repository.read_published_analysis("col_source", "objective-1")
    assert published is not None
    assert published.key == succeeded.key
    assert published.status == "succeeded"
    findings, finding_total = repository.list_findings(
        "col_source", "objective-1", version
    )
    evidence, evidence_total = repository.list_evidence(
        "col_source", "objective-1", version, finding_id="finding-1"
    )
    assert finding_total == 1
    assert findings == (_finding(version),)
    assert evidence_total == 5
    assert evidence == _analysis_evidence(version)
    persisted_contributions = {
        item.document_id: item
        for item in repository.list_contributions(
            "col_source", "objective-1", version
        )
    }
    assert persisted_contributions == {
        item.document_id: item for item in _analysis_contributions(version)
    }


def test_failed_retry_preserves_previous_published_version(source_repositories) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)
    repository.publish_analysis(
        "col_source",
        "objective-1",
        1,
        contributions=_analysis_contributions(1),
        evidence_records=_analysis_evidence(1),
        findings=(_finding(1),),
    )
    objective, retry = repository.queue_analysis(
        "col_source",
        "objective-1",
        pipeline_version="test.v2",
        model_name=None,
        prompt_versions={},
    )
    repository.claim_analysis("col_source", "objective-1", retry.analysis_version)
    repository.fail_analysis(
        "col_source",
        "objective-1",
        retry.analysis_version,
        error_code="provider_timeout",
        error_message="timeout",
    )

    current = repository.read_objective("col_source", "objective-1")
    assert current is not None
    assert current.active_analysis_version == 2
    assert current.published_analysis_version == 1
    assert repository.read_published_analysis("col_source", "objective-1").analysis_version == 1


def test_publish_rejects_cross_version_artifacts_without_partial_writes(
    source_repositories,
) -> None:
    source_repository, builds = source_repositories
    repository = _prepare_studies(source_repository, builds)
    _objective_row, claimed = _queue_and_claim(repository)

    with pytest.raises(ValueError, match="cross-version"):
        repository.publish_analysis(
            "col_source",
            "objective-1",
            claimed.analysis_version,
            contributions=_analysis_contributions(1),
            evidence_records=(replace(_evidence(1), analysis_version=2),),
            findings=(_finding(1),),
        )

    assert repository.read_analysis("col_source", "objective-1", 1).status == "running"
    assert repository.read_published_analysis("col_source", "objective-1") is None
