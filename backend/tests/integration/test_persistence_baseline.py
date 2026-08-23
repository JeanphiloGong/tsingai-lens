from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

import pytest

from domain.core import (
    BaselineReference,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    ObjectiveFactSet,
    ResearchObjective,
    SampleVariant,
    TestCondition as CoreTestCondition,
)
from domain.core.paper_fact import PaperFactSet
from domain.chat import ChatMessage, ChatSession
from domain.evaluation import (
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    FindingCuration,
    FindingFeedback,
)
from domain.goal import ExperimentPlanRecord
from domain.pipeline import ExecutionTimestamps, PipelineNodeRun
from domain.source import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionFileRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
    source_documents_from_records,
    SourceReferenceEntry,
    SourceReferenceSet,
    TaskRecord,
)
from application.source.artifact_registry_service import ArtifactRegistryService
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.evaluation_repository import (
    PostgresEvaluationRepository,
)
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.experiment_plan_repository import (
    PostgresExperimentPlanRepository,
)
from infra.persistence.postgres.models.objective import ObjectiveResearchRecord
from infra.persistence.sqlite import SqliteSourceArtifactRepository
from scripts.persistence.capture_baseline import capture_baseline
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.objective_review_repository import InMemoryObjectiveReviewRepository


BACKEND_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "persistence_revision"


def test_baseline_rejects_missing_canonical_curated_finding() -> None:
    scenario = json.loads((FIXTURE_DIR / "scenario.json").read_text(encoding="utf-8"))
    scenario["records"]["curations"][0].pop("curated_finding")

    with pytest.raises(ValueError, match="invalid canonical curation"):
        capture_baseline(scenario)


def test_baseline_rejects_mismatched_curated_finding_identity() -> None:
    scenario = json.loads((FIXTURE_DIR / "scenario.json").read_text(encoding="utf-8"))
    scenario["records"]["curations"][0]["curated_finding"]["finding_id"] = (
        "finding-other"
    )

    with pytest.raises(ValueError, match="invalid canonical curation"):
        capture_baseline(scenario)


@pytest.mark.anyio
async def test_current_repositories_round_trip_the_reviewed_persistence_baseline(
    tmp_path,
    postgres_session_factory,
) -> None:
    scenario = json.loads((FIXTURE_DIR / "scenario.json").read_text(encoding="utf-8"))
    expected = json.loads(
        (FIXTURE_DIR / "expected-baseline.json").read_text(encoding="utf-8")
    )
    records = scenario["records"]
    collection_id = records["collections"][0]["collection_id"]
    db_path = tmp_path / "lens.sqlite"

    collection_workspace = FileCollectionWorkspace(tmp_path / "collections")
    object_store = FileObjectStore(collection_workspace.root_dir)
    auth_repository = PostgresAuthRepository(postgres_session_factory)
    collection_repository = PostgresCollectionRepository(postgres_session_factory)
    build_repository = PostgresBuildRepository(postgres_session_factory)
    source_repository = SqliteSourceArtifactRepository(db_path)
    paper_fact_repository = MemoryPaperFactRepository()
    objective_repository = MemoryObjectiveRepository()
    artifact_registry_service = ArtifactRegistryService(
        build_repository,
        source_artifact_repository=source_repository,
    )
    chat_repository = PostgresChatRepository(postgres_session_factory)
    experiment_plan_repository = PostgresExperimentPlanRepository(
        postgres_session_factory
    )
    evaluation_repository = PostgresEvaluationRepository(
        postgres_session_factory
    )
    review_repository = InMemoryObjectiveReviewRepository()

    await auth_repository.add_user(records["auth_users"][0])
    await collection_repository.add_collection(
        CollectionRecord.from_mapping(
            records["collections"][0],
            collection_id,
            now_iso=records["collections"][0]["created_at"],
        )
    )
    paths = collection_workspace.create_collection_dirs(collection_id)
    assert not (paths.collection_dir / "meta.json").exists()
    object_payload = b"Synthetic fixture content; no paper or user data."
    object_digest = sha256(object_payload).hexdigest()
    fixture_file = records["collection_files"][0]
    storage_key = f"{collection_id}/input/{fixture_file['stored_filename']}"
    object_store.write(
        storage_key,
        object_payload,
        object_digest,
    )
    file_record = CollectionFileRecord(
        file_id=fixture_file["file_id"],
        collection_id=collection_id,
        object_id="obj_strength",
        object_kind="source_input",
        original_filename=fixture_file["original_filename"],
        stored_filename=fixture_file["stored_filename"],
        storage_key=storage_key,
        sha256=object_digest,
        media_type=fixture_file["media_type"],
        status="stored",
        size_bytes=len(object_payload),
        created_at=records["collections"][0]["created_at"],
        document_id=fixture_file["document_id"],
    )
    fixture_import = records["import_manifests"][0]["imports"][0]
    await collection_repository.add_collection_import(
        CollectionImportRecord(
            import_id=fixture_import["import_id"],
            collection_id=collection_id,
            channel=fixture_import["source_type"],
            adapter_name=fixture_import["source_type"],
            adapter_version=None,
            raw_locator=fixture_file["original_filename"],
            goal_context=None,
            warnings=(),
            ingested_at=records["collections"][0]["updated_at"],
            documents=(
                CollectionImportDocumentRecord(
                    source_document_id=fixture_file["document_id"],
                    origin_channel=fixture_import["source_type"],
                    file=file_record,
                    language=None,
                    ingest_status="normalized",
                    text_units=(),
                ),
            ),
        ),
        updated_at=records["collections"][0]["updated_at"],
    )
    task_record = TaskRecord.from_mapping(records["tasks"][0])
    await build_repository.add_task(task_record, build_id="build_baseline")
    artifact_stage = BuildStageRecord(
        stage_id="stage_artifact_registry_baseline",
        build_id="build_baseline",
        stage_order=0,
        node=PipelineNodeRun(
            name="artifact_registry",
            dependencies=("source_artifacts",),
            status="succeeded",
            timestamps=ExecutionTimestamps(
                started_at=task_record.created_at,
                finished_at=task_record.updated_at,
            ),
        ),
    )
    await build_repository.update_task(task_record, stages=(artifact_stage,))
    await build_repository.add_artifact_versions(
        task_record.task_id,
        tuple(
            ArtifactVersionRecord(
                artifact_version_id=f"artifact_baseline_{artifact_kind}",
                build_stage_id=artifact_stage.stage_id,
                artifact_kind=artifact_kind,
                schema_version=1,
                content_version=1,
                status="ready",
                object_id=None,
                details={},
                created_at=task_record.updated_at,
            )
            for artifact_kind in (
                "documents",
            )
        ),
    )
    await build_repository.finish_build(
        task_record,
        build_status="succeeded",
        activate=True,
    )

    session_token_hash = sha256(b"synthetic-baseline-session-token").hexdigest()
    await auth_repository.add_session(
        {
            **records["auth_sessions"][0],
            "token_hash": session_token_hash,
        }
    )

    source_repository.replace_collection_documents(
        collection_id,
        source_documents_from_records(
            documents=records["source_documents"],
            text_units=records["source_text_units"],
            blocks=records["source_blocks"],
            tables=records["source_tables"],
            table_rows=records["source_table_rows"],
            table_cells=records["source_table_cells"],
            figures=records["source_figures"],
        ),
    )
    source_repository.replace_collection_references(
        collection_id,
        SourceReferenceSet(
            entries=tuple(
                SourceReferenceEntry.from_record(item)
                for item in records["source_reference_entries"]
            )
        ),
    )

    research_objectives = tuple(
        ResearchObjective.from_mapping(
            {"collection_id": collection_id, **item}
        )
        for item in records["research_objectives"]
    )
    await objective_repository.replace(
        collection_id,
        "build_baseline",
        ObjectiveFactSet(
            research_objectives=research_objectives,
        ),
    )
    objective = research_objectives[0]
    objective_timestamp = datetime.fromisoformat(
        records["collections"][0]["created_at"]
    )
    async with postgres_session_factory.begin() as session:
        session.add(
            ObjectiveResearchRecord(
                collection_id=objective.collection_id,
                objective_id=objective.objective_id,
                question=objective.question,
                material_scope=list(objective.material_scope),
                variables=list(objective.variables),
                outcomes=list(objective.outcomes),
                mechanisms=list(objective.mechanisms),
                constraints=list(objective.constraints),
                requested_comparator=objective.requested_comparator,
                confidence=objective.confidence,
                reason=objective.reason,
                confirmation_status=objective.confirmation_status,
                active_analysis_version=None,
                published_analysis_version=None,
                created_at=objective_timestamp,
                updated_at=objective_timestamp,
            )
        )
    await paper_fact_repository.replace_document_profiles(
        collection_id,
        "build_test",
        tuple(
            DocumentProfile.from_mapping(item)
            for item in records["core_document_profiles"]
        ),
    )
    await paper_fact_repository.replace_paper_facts(
        collection_id,
        "build_test",
        PaperFactSet(
            paper_facts_ready=True,
            evidence_anchors=tuple(
                EvidenceAnchor.from_mapping(item)
                for item in records["core_evidence_anchors"]
            ),
            method_facts=tuple(
                MethodFact.from_mapping(item) for item in records["core_method_facts"]
            ),
            sample_variants=tuple(
                SampleVariant.from_mapping(item)
                for item in records["core_sample_variants"]
            ),
            test_conditions=tuple(
                CoreTestCondition.from_mapping(item)
                for item in records["core_test_conditions"]
            ),
            baseline_references=tuple(
                BaselineReference.from_mapping(item)
                for item in records["core_baseline_references"]
            ),
            measurement_results=tuple(
                MeasurementResult.from_mapping(item)
                for item in records["core_measurement_results"]
            ),
        ),
    )
    chat_session = ChatSession.from_mapping(records["chat_sessions"][0])
    await chat_repository.add_session(chat_session)
    await chat_repository.save_trajectory(
        session=chat_session,
        messages=tuple(
            ChatMessage.from_mapping(item) for item in records["chat_messages"]
        ),
        tool_calls=(),
        tool_results=(),
    )
    await experiment_plan_repository.upsert_plan(
        ExperimentPlanRecord.from_mapping(records["experiment_plans"][0])
    )

    gold_set = EvaluationGoldSet.from_mapping(records["evaluation_gold_sets"][0])
    await evaluation_repository.upsert_gold_set(
        gold_set,
        tuple(
            EvaluationGoldItem.from_mapping(item)
            for item in records["evaluation_gold_items"]
        ),
    )
    await evaluation_repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshot.from_mapping(records["prediction_snapshots"][0])
    )
    await evaluation_repository.upsert_evaluation_run(
        EvaluationRun.from_mapping(records["evaluation_runs"][0])
    )
    for item in records["feedback"]:
        await review_repository.upsert_feedback(
            FindingFeedback.from_mapping(item)
        )
    for item in records["curations"]:
        await review_repository.upsert_curation(
            FindingCuration.from_mapping(item)
        )

    observed = deepcopy(scenario)
    observed_records = observed["records"]
    stored_collection_record = await collection_repository.read_collection(collection_id)
    assert stored_collection_record is not None
    stored_collection = stored_collection_record.to_record()
    observed_records["collections"] = [
        {key: stored_collection.get(key) for key in records["collections"][0]}
    ]
    stored_files = await collection_repository.list_collection_files(collection_id)
    observed_records["collection_files"] = [
        {
            key: (
                stored_file.size_bytes
                if key == "byte_size"
                else stored_file.to_record().get(key)
            )
            for key in records["collection_files"][index]
        }
        for index, stored_file in enumerate(stored_files)
    ]
    observed_records["import_manifests"] = [
        {
            "schema_version": 1,
            "collection_id": collection_id,
            "imports": [
                item.to_record()
                for item in await collection_repository.list_collection_imports(collection_id)
            ],
        }
    ]
    observed_records["tasks"] = [
        {
            key: (await build_repository.read_task(task_record.task_id)).to_record().get(key)
            for key in records["tasks"][0]
        }
    ]
    projected_artifacts = await artifact_registry_service.get_for_task(
        task_record.task_id
    )
    observed_records["artifacts"] = [
        {key: projected_artifacts.get(key) for key in records["artifacts"][0]}
    ]
    observed_records["auth_users"] = [
        await auth_repository.read_user(records["auth_users"][0]["user_id"])
    ]
    observed_records["auth_sessions"] = [
        await auth_repository.read_session_by_token_hash(session_token_hash)
    ]

    source = source_repository.read_collection_documents(collection_id)
    references = source_repository.read_collection_references(collection_id)
    source_families = {
        "source_documents": [item.to_record() for item in source],
        "source_text_units": [
            item.to_record() for document in source for item in document.text_units
        ],
        "source_blocks": [
            item.to_record() for document in source for item in document.blocks
        ],
        "source_tables": [
            item.to_record() for document in source for item in document.tables
        ],
        "source_table_rows": [
            item.to_record() for document in source for item in document.table_rows
        ],
        "source_table_cells": [
            item.to_record() for document in source for item in document.table_cells
        ],
        "source_figures": [
            item.to_record() for document in source for item in document.figures
        ],
        "source_reference_entries": [item.to_record() for item in references.entries],
    }
    for family, actual_items in source_families.items():
        expected_items = records[family]
        observed_records[family] = [
            {key: actual.get(key) for key in expected_items[index]}
            for index, actual in enumerate(actual_items)
        ]

    paper_facts = await paper_fact_repository.read(collection_id)
    objective_facts = await objective_repository.read(
        collection_id,
        build_id="build_baseline",
    )
    core_families = {
        "core_document_profiles": [
            item.to_record() for item in paper_facts.document_profiles
        ],
        "core_evidence_anchors": [
            item.to_record() for item in paper_facts.evidence_anchors
        ],
        "core_method_facts": [item.to_record() for item in paper_facts.method_facts],
        "core_sample_variants": [
            item.to_record() for item in paper_facts.sample_variants
        ],
        "core_test_conditions": [
            item.to_record() for item in paper_facts.test_conditions
        ],
        "core_baseline_references": [
            item.to_record() for item in paper_facts.baseline_references
        ],
        "core_measurement_results": [
            item.to_record() for item in paper_facts.measurement_results
        ],
        "research_objectives": [
            item.to_record() for item in objective_facts.research_objectives
        ],
    }
    for family, actual_items in core_families.items():
        expected_items = records[family]
        observed_records[family] = [
            {key: actual.get(key) for key in expected_items[index]}
            for index, actual in enumerate(actual_items)
        ]

    session_id = records["chat_sessions"][0]["session_id"]
    observed_records["chat_sessions"] = [
        (await chat_repository.read_session(session_id)).to_record()
    ]
    observed_records["chat_messages"] = [
        item.to_record() for item in await chat_repository.read_messages(session_id)
    ]
    observed_records["experiment_plans"] = [
        item.to_record()
        for item in await experiment_plan_repository.list_plans(
            collection_id, "objective_strength"
        )
    ]
    observed_records["feedback"] = [
        item.to_record() for item in await review_repository.list_feedback(collection_id)
    ]
    observed_records["curations"] = [
        item.to_record() for item in await review_repository.list_curations(collection_id)
    ]
    observed_records["evaluation_gold_sets"] = [
        (await evaluation_repository.read_gold_set("gold_strength")).to_record()
    ]
    observed_records["evaluation_gold_items"] = [
        item.to_record()
        for item in await evaluation_repository.list_gold_items("gold_strength")
    ]
    observed_records["prediction_snapshots"] = [
        (
            await evaluation_repository.read_prediction_snapshot("snapshot_strength")
        ).to_record()
    ]
    observed_records["evaluation_runs"] = [
        (
            await evaluation_repository.read_evaluation_run("evaluation_strength")
        ).to_record()
    ]

    assert capture_baseline(observed) == expected
