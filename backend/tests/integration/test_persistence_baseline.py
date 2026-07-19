from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from domain.core import (
    BaselineReference,
    ConfirmedGoal,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    ResearchObjective,
    ResearchUnderstanding,
    SampleVariant,
    TestCondition as CoreTestCondition,
)
from domain.evaluation import (
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)
from domain.goal import ExperimentPlanRecord
from domain.source import (
    SourceArtifactSet,
    SourceReferenceEntry,
    SourceReferenceSet,
)
from infra.persistence.file import (
    FileArtifactRepository,
    FileCollectionRepository,
    FileTaskRepository,
)
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.sqlite import (
    SqliteAuthRepository,
    SqliteCoreFactRepository,
    SqliteEvaluationRepository,
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
    SqliteSourceArtifactRepository,
)
from scripts.persistence.capture_baseline import capture_baseline


BACKEND_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "persistence_revision"


def test_current_repositories_round_trip_the_reviewed_persistence_baseline(tmp_path) -> None:
    scenario = json.loads((FIXTURE_DIR / "scenario.json").read_text(encoding="utf-8"))
    expected = json.loads(
        (FIXTURE_DIR / "expected-baseline.json").read_text(encoding="utf-8")
    )
    records = scenario["records"]
    collection_id = records["collections"][0]["collection_id"]
    db_path = tmp_path / "lens.sqlite"

    collection_repository = FileCollectionRepository(tmp_path / "collections")
    object_store = FileObjectStore(collection_repository.root_dir)
    task_repository = FileTaskRepository(tmp_path / "tasks")
    artifact_repository = FileArtifactRepository(tmp_path / "collections")
    auth_repository = SqliteAuthRepository(db_path)
    source_repository = SqliteSourceArtifactRepository(db_path)
    core_repository = SqliteCoreFactRepository(db_path)
    goal_session_repository = SqliteGoalSessionRepository(db_path)
    experiment_plan_repository = SqliteExperimentPlanRepository(db_path)
    evaluation_repository = SqliteEvaluationRepository(db_path)

    collection_repository.create_collection_dirs(collection_id)
    collection_repository.write_collection(collection_id, records["collections"][0])
    collection_repository.write_files(collection_id, records["collection_files"])
    collection_repository.write_import_manifest(
        collection_id,
        records["import_manifests"][0],
    )
    object_payload = b"Synthetic fixture content; no paper or user data."
    object_store.write(
        f"{collection_id}/input/{records['collection_files'][0]['stored_filename']}",
        object_payload,
        sha256(object_payload).hexdigest(),
    )
    task_repository.write_task(records["tasks"][0]["task_id"], records["tasks"][0])
    artifact_repository.write(collection_id, records["artifacts"][0])

    auth_repository.write_user(records["auth_users"][0])
    auth_repository.write_session(records["auth_sessions"][0])

    source_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
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

    core_repository.replace_collection_research_objectives(
        collection_id,
        (),
        tuple(ResearchObjective.from_mapping(item) for item in records["research_objectives"]),
        (),
        (),
        (),
        (),
        (),
    )
    core_repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            document_profiles=tuple(
                DocumentProfile.from_mapping(item)
                for item in records["core_document_profiles"]
            ),
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
    for item in records["confirmed_goals"]:
        core_repository.upsert_confirmed_goal(ConfirmedGoal.from_mapping(item))
    for item in records["research_understandings"]:
        core_repository.upsert_research_understanding(
            collection_id,
            ResearchUnderstanding.from_mapping(item),
        )

    goal_session_repository.write_session(records["goal_sessions"][0])
    goal_session_repository.write_messages(
        records["goal_sessions"][0]["session_id"],
        records["goal_messages"],
    )
    experiment_plan_repository.upsert_plan(
        ExperimentPlanRecord.from_mapping(records["experiment_plans"][0])
    )

    gold_set = EvaluationGoldSet.from_mapping(records["evaluation_gold_sets"][0])
    evaluation_repository.upsert_gold_set(
        gold_set,
        tuple(
            EvaluationGoldItem.from_mapping(item)
            for item in records["evaluation_gold_items"]
        ),
    )
    evaluation_repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshot.from_mapping(records["prediction_snapshots"][0])
    )
    evaluation_repository.upsert_evaluation_run(
        EvaluationRun.from_mapping(records["evaluation_runs"][0])
    )
    for item in records["feedback"]:
        evaluation_repository.upsert_research_understanding_feedback(
            ResearchUnderstandingFeedback.from_mapping(item)
        )
    for item in records["curations"]:
        evaluation_repository.upsert_research_understanding_curation(
            ResearchUnderstandingCuration.from_mapping(item)
        )

    observed = deepcopy(scenario)
    observed_records = observed["records"]
    observed_records["collections"] = [collection_repository.read_collection(collection_id)]
    observed_records["collection_files"] = collection_repository.read_files(collection_id)
    observed_records["import_manifests"] = [
        collection_repository.read_import_manifest(collection_id)
    ]
    observed_records["tasks"] = [task_repository.read_task(records["tasks"][0]["task_id"])]
    observed_records["artifacts"] = [artifact_repository.read(collection_id)]
    observed_records["auth_users"] = [
        auth_repository.read_user(records["auth_users"][0]["user_id"])
    ]
    observed_records["auth_sessions"] = [
        auth_repository.read_session(records["auth_sessions"][0]["session_id"])
    ]

    source = source_repository.read_collection_artifacts(collection_id)
    references = source_repository.read_collection_references(collection_id)
    source_families = {
        "source_documents": [item.to_record() for item in source.documents],
        "source_text_units": [item.to_record() for item in source.text_units],
        "source_blocks": [item.to_record() for item in source.blocks],
        "source_tables": [item.to_record() for item in source.tables],
        "source_table_rows": [item.to_record() for item in source.table_rows],
        "source_table_cells": [item.to_record() for item in source.table_cells],
        "source_figures": [item.to_record() for item in source.figures],
        "source_reference_entries": [item.to_record() for item in references.entries],
    }
    for family, actual_items in source_families.items():
        expected_items = records[family]
        observed_records[family] = [
            {key: actual.get(key) for key in expected_items[index]}
            for index, actual in enumerate(actual_items)
        ]

    facts = core_repository.read_collection_facts(collection_id)
    core_families = {
        "core_document_profiles": [item.to_record() for item in facts.document_profiles],
        "core_evidence_anchors": [item.to_record() for item in facts.evidence_anchors],
        "core_method_facts": [item.to_record() for item in facts.method_facts],
        "core_sample_variants": [item.to_record() for item in facts.sample_variants],
        "core_test_conditions": [item.to_record() for item in facts.test_conditions],
        "core_baseline_references": [item.to_record() for item in facts.baseline_references],
        "core_measurement_results": [item.to_record() for item in facts.measurement_results],
        "research_objectives": [item.to_record() for item in facts.research_objectives],
        "confirmed_goals": [
            item.to_record() for item in core_repository.list_confirmed_goals(collection_id)
        ],
        "research_understandings": [
            item.to_record()
            for item in core_repository.list_research_understandings(collection_id)
        ],
    }
    for family, actual_items in core_families.items():
        expected_items = records[family]
        observed_records[family] = [
            {key: actual.get(key) for key in expected_items[index]}
            for index, actual in enumerate(actual_items)
        ]

    session_id = records["goal_sessions"][0]["session_id"]
    observed_records["goal_sessions"] = [goal_session_repository.read_session(session_id)]
    observed_records["goal_messages"] = goal_session_repository.read_messages(session_id)
    observed_records["experiment_plans"] = [
        item.to_record()
        for item in experiment_plan_repository.list_plans(collection_id, "goal_strength")
    ]
    observed_records["feedback"] = [
        item.to_record()
        for item in evaluation_repository.list_research_understanding_feedback(
            collection_id
        )
    ]
    observed_records["curations"] = [
        item.to_record()
        for item in evaluation_repository.list_research_understanding_curations(
            collection_id
        )
    ]
    observed_records["evaluation_gold_sets"] = [
        evaluation_repository.read_gold_set("gold_strength").to_record()
    ]
    observed_records["evaluation_gold_items"] = [
        item.to_record() for item in evaluation_repository.list_gold_items("gold_strength")
    ]
    observed_records["prediction_snapshots"] = [
        evaluation_repository.read_prediction_snapshot("snapshot_strength").to_record()
    ]
    observed_records["evaluation_runs"] = [
        evaluation_repository.read_evaluation_run("evaluation_strength").to_record()
    ]

    assert capture_baseline(observed) == expected
