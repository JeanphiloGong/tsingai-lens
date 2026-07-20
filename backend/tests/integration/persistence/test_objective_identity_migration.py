from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import URL, create_engine, event, func, select
from sqlalchemy.engine import make_url

from infra.persistence.database import build_session_factory
from infra.persistence.postgres.base import Base
from infra.persistence.postgres.models.auth import AuthUser
from infra.persistence.postgres.models.build import CollectionBuild, Task
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import (
    CollectionDocument,
    Document,
    DocumentVersion,
)
from infra.persistence.postgres.models.migration import ObjectiveIdentityMigration
from infra.persistence.postgres.models.objective import (
    ObjectiveBuild,
    ObjectiveResearchRecord,
    ResearchObjectiveLifecycle,
)
from infra.persistence.postgres.models.objective_workspace import (
    ObjectiveExperimentPlan,
    ObjectiveMessage,
    ObjectiveSession,
)
from infra.persistence.postgres.models.paper_fact import (
    PaperFactEvidenceAnchor,
    PaperFactMeasurementResult,
)
from infra.persistence.postgres.models.source import SourceDocument
from infra.persistence.postgres.models.understanding import (
    ResearchFindingRecord,
    ResearchUnderstandingRecord,
)
from infra.persistence.postgres.models.evaluation import (
    ResearchUnderstandingCurationRecord,
    ResearchUnderstandingFeedbackRecord,
)
from scripts.persistence.migrate_goal_identity import (
    MigrationBlockedError,
    apply_migration,
    build_migration_plan,
)
from scripts.persistence import migrate_goal_identity


NOW = "2026-07-20T08:00:00+00:00"
BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def migration_target(tmp_path: Path):
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "target.sqlite"))
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    _seed_target(sessions)
    try:
        yield sessions
    finally:
        engine.dispose()


def test_dry_run_is_deterministic_and_never_mutates_target(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "source.sqlite")
    before = source.read_bytes()

    first = build_migration_plan(source, migration_target)
    second = build_migration_plan(source, migration_target)

    assert first.to_dict() == second.to_dict()
    assert first.status == "dry_run_ready"
    assert [(item.goal_id, item.objective_id, item.mapping_kind) for item in first.mappings] == [
        ("goal-linked", "objective-linked", "linked"),
        ("goal-standalone", first.mappings[1].objective_id, "standalone"),
    ]
    assert first.mappings[1].objective_id.startswith("obj_migrated_")
    assert first.source_sha256
    assert first.manifest_sha256
    assert first.record_counts == {
        "curations": 1,
        "feedback": 1,
        "messages": 1,
        "plans": 1,
        "sessions": 1,
        "understandings": 1,
    }
    assert first.evidence_link_count == 1
    assert source.read_bytes() == before
    with migration_target() as session:
        assert session.scalar(select(func.count()).select_from(ResearchUnderstandingRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ObjectiveIdentityMigration)) == 0


def test_apply_preserves_identity_content_and_evidence_and_is_idempotent(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "source.sqlite")
    dry_run = build_migration_plan(source, migration_target)

    applied = apply_migration(
        source,
        migration_target,
        expected_source_sha256=dry_run.source_sha256,
        backup_reference="backup:test-20260720",
    )
    repeated = apply_migration(
        source,
        migration_target,
        expected_source_sha256=dry_run.source_sha256,
        backup_reference="backup:test-20260720",
    )

    assert applied.status == "applied"
    assert repeated.status == "already_applied"
    assert repeated.manifest_sha256 == applied.manifest_sha256
    assert repeated.content_hashes == applied.content_hashes
    with migration_target() as session:
        understanding = session.scalar(select(ResearchUnderstandingRecord))
        finding = session.scalar(select(ResearchFindingRecord))
        feedback = session.scalar(select(ResearchUnderstandingFeedbackRecord))
        curation = session.scalar(select(ResearchUnderstandingCurationRecord))
        workspace_session = session.scalar(select(ObjectiveSession))
        message = session.scalar(select(ObjectiveMessage))
        plan = session.scalar(select(ObjectiveExperimentPlan))
        assert understanding.objective_id == "objective-linked"
        assert understanding.content_sha256 == applied.content_hashes["understandings"]
        assert finding.finding_id == "finding-1"
        assert finding.evidence_ref_ids == ["evidence-1"]
        assert feedback.objective_id == "objective-linked"
        assert curation.objective_id == "objective-linked"
        assert workspace_session.focused_objective_id == "objective-linked"
        assert message.position == 0
        assert plan.objective_id == "objective-linked"
        assert session.scalar(select(func.count()).select_from(ObjectiveIdentityMigration)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchUnderstandingRecord)) == 1


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        ("running", "running_goal"),
        ("orphan", "orphan_goal_reference"),
        ("objective_drift", "objective_snapshot_drift"),
        ("scope_conflict", "understanding_scope_conflict"),
        ("duplicate_conflict", "duplicate_goal_conflict"),
        ("orphan_user", "orphan_session_user"),
    ],
)
def test_dry_run_blocks_unsafe_source_state(
    tmp_path: Path,
    migration_target,
    mutation: str,
    blocker: str,
) -> None:
    source = _write_source(tmp_path / f"{mutation}.sqlite", mutation=mutation)

    with pytest.raises(MigrationBlockedError) as exc_info:
        build_migration_plan(source, migration_target)

    assert blocker in {item.code for item in exc_info.value.report.blockers}
    with migration_target() as session:
        assert session.scalar(select(func.count()).select_from(ResearchUnderstandingRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ObjectiveIdentityMigration)) == 0


def test_dry_run_blocks_embedded_goal_url(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "goal-url.sqlite", mutation="embedded_goal_url")

    with pytest.raises(MigrationBlockedError) as exc_info:
        build_migration_plan(source, migration_target)

    assert "residual_goal_identity" in {
        item.code for item in exc_info.value.report.blockers
    }


def test_dry_run_blocks_source_and_core_evidence_drift(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "evidence-drift.sqlite", mutation="evidence_drift")

    with pytest.raises(MigrationBlockedError) as exc_info:
        build_migration_plan(source, migration_target)

    assert {
        "missing_evidence_document",
        "missing_evidence_fact",
        "missing_evidence_anchor",
    }.issubset({item.code for item in exc_info.value.report.blockers})


def test_dry_run_rejects_source_file_change_during_read(
    tmp_path: Path,
    migration_target,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_source(tmp_path / "source-drift.sqlite")
    original_read_source = migrate_goal_identity._read_source

    def mutate_then_read(path: Path):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE core_confirmed_goals SET payload = ? WHERE goal_id = ?",
                ('{"changed":true}', "goal-standalone"),
            )
        return original_read_source(path)

    monkeypatch.setattr(migrate_goal_identity, "_read_source", mutate_then_read)

    with pytest.raises(ValueError, match="changed while it was being read"):
        build_migration_plan(source, migration_target)


def test_apply_requires_reviewed_hash_and_backup_reference(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "source.sqlite")
    dry_run = build_migration_plan(source, migration_target)

    with pytest.raises(ValueError, match="source SHA-256"):
        apply_migration(
            source,
            migration_target,
            expected_source_sha256="0" * 64,
            backup_reference="backup:test",
        )
    with pytest.raises(ValueError, match="backup reference"):
        apply_migration(
            source,
            migration_target,
            expected_source_sha256=dry_run.source_sha256,
            backup_reference="",
        )


def test_dry_run_blocks_running_target_lifecycle(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "running-target.sqlite")
    with migration_target.begin() as session:
        lifecycle = session.get(
            ResearchObjectiveLifecycle,
            {"collection_id": "collection-1", "objective_id": "objective-linked"},
        )
        lifecycle.status = "running"

    with pytest.raises(MigrationBlockedError) as exc_info:
        build_migration_plan(source, migration_target)

    assert "running_objective" in {
        item.code for item in exc_info.value.report.blockers
    }


def test_dry_run_blocks_partial_target_without_completed_audit(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "partial-target.sqlite")
    report = build_migration_plan(source, migration_target)
    linked = next(
        item for item in report.mappings if item.objective_id == "objective-linked"
    )
    with migration_target.begin() as session:
        session.add(
            ResearchUnderstandingRecord(
                understanding_id="understanding_partial",
                collection_id="collection-1",
                objective_id="objective-linked",
                source_build_id=linked.source_build_id,
                version=1,
                schema_version="research_understanding.v1",
                state="ready",
                title=None,
                content_sha256=report.content_hashes["understandings"],
                warnings=[],
                presentation_metadata={},
                model_traces=[],
                created_at=datetime.fromisoformat(NOW),
            )
        )

    with pytest.raises(MigrationBlockedError) as exc_info:
        build_migration_plan(source, migration_target)

    assert "partial_target_state" in {
        item.code for item in exc_info.value.report.blockers
    }


def test_equivalent_duplicate_goals_share_one_objective_without_data_duplication(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "duplicate.sqlite", mutation="duplicate_equivalent")

    report = build_migration_plan(source, migration_target)

    linked = [item for item in report.mappings if item.objective_id == "objective-linked"]
    assert [item.goal_id for item in linked] == ["goal-duplicate", "goal-linked"]
    assert report.record_counts["understandings"] == 1


def test_ready_without_findings_is_imported_as_retryable_failed(
    tmp_path: Path,
    migration_target,
) -> None:
    source = _write_source(tmp_path / "no-findings.sqlite", mutation="no_findings")
    with sqlite3.connect(source) as connection:
        connection.execute("DELETE FROM research_understanding_feedback")
        connection.execute("DELETE FROM research_understanding_curations")
    dry_run = build_migration_plan(source, migration_target)

    apply_migration(
        source,
        migration_target,
        expected_source_sha256=dry_run.source_sha256,
        backup_reference="backup:no-findings",
    )

    with migration_target() as session:
        lifecycle = session.get(
            ResearchObjectiveLifecycle,
            {"collection_id": "collection-1", "objective_id": "objective-linked"},
        )
        assert lifecycle.status == "failed"
        assert "no reviewable Findings" in lifecycle.analysis_error


def test_postgresql_apply_is_atomic_and_matches_orm_schema(tmp_path: Path) -> None:
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
        _seed_target(sessions)
        source = _write_source(tmp_path / "postgres-source.sqlite")
        dry_run = build_migration_plan(source, sessions)

        applied = apply_migration(
            source,
            sessions,
            expected_source_sha256=dry_run.source_sha256,
            backup_reference="backup:postgres-test",
        )

        assert applied.status == "applied"
        with sessions() as session:
            assert session.scalar(
                select(func.count()).select_from(ResearchUnderstandingRecord)
            ) == 1
            assert session.scalar(
                select(func.count()).select_from(ObjectiveIdentityMigration)
            ) == 1
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        engine.dispose()
def _seed_target(session_factory) -> None:
    now = datetime.fromisoformat(NOW)
    with session_factory.begin() as session:
        session.add(
            AuthUser(
                user_id="user-1",
                email="migration@example.com",
                display_name="Migration User",
                password_hash="test-password-hash",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Collection(
                collection_id="collection-1",
                owner_user_id="user-1",
                name="Migration collection",
                description=None,
                status="ready",
                paper_count=0,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            Task(
                task_id="task-1",
                collection_id="collection-1",
                task_type="build",
                status="completed",
                current_stage="completed",
                progress_percent=100,
                progress_detail=None,
                output_path=None,
                errors=[],
                warnings=[],
                details={},
                created_at=now,
                updated_at=now,
                started_at=now,
                finished_at=now,
            )
        )
        session.flush()
        session.add(
            CollectionBuild(
                build_id="build-1",
                task_id="task-1",
                collection_id="collection-1",
                build_number=1,
                status="succeeded",
                created_at=now,
                started_at=now,
                finished_at=now,
            )
        )
        session.flush()
        session.add(
            Document(
                document_id="canonical-document-1",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            DocumentVersion(
                document_version_id="document-version-1",
                document_id="canonical-document-1",
                sha256="1" * 64,
                media_type="application/pdf",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            CollectionDocument(
                collection_document_id="collection-document-1",
                collection_id="collection-1",
                document_id="canonical-document-1",
                document_version_id="document-version-1",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            SourceDocument(
                build_id="build-1",
                source_document_id="document-1",
                collection_id="collection-1",
                collection_document_id="collection-document-1",
                document_version_id="document-version-1",
                human_readable_id=1,
                title="Synthetic source",
                text="Strength increased.",
                creation_date=None,
                metadata_json={},
            )
        )
        session.flush()
        session.add(
            PaperFactEvidenceAnchor(
                build_id="build-1",
                anchor_id="anchor-1",
                collection_id="collection-1",
                source_document_id="document-1",
                document_version_id="document-version-1",
                anchor_order=0,
                locator_type="page",
                locator_confidence="high",
                source_type="text",
                section_id=None,
                char_range_json=None,
                bbox_json=None,
                page=1,
                quote="Strength increased.",
                deep_link=None,
                block_id=None,
                snippet_id=None,
                figure_or_table=None,
                quote_span=None,
            )
        )
        session.add(
            PaperFactMeasurementResult(
                build_id="build-1",
                result_id="result-1",
                collection_id="collection-1",
                source_document_id="document-1",
                document_version_id="document-version-1",
                fact_order=0,
                domain_profile="materials",
                variant_id=None,
                property_normalized="strength",
                result_type="scalar",
                claim_scope="document",
                value_payload={"value": 620},
                unit="MPa",
                test_condition_id=None,
                baseline_id=None,
                traceability_status="resolved",
                result_source_type="text",
                epistemic_status="reported",
            )
        )
        session.flush()
        session.add(
            ObjectiveBuild(
                build_id="build-1",
                collection_id="collection-1",
                research_objectives_ready=True,
            )
        )
        session.flush()
        session.add(
            ObjectiveResearchRecord(
                build_id="build-1",
                objective_id="objective-linked",
                collection_id="collection-1",
                objective_order=0,
                question="How does heat treatment affect strength?",
                material_scope=["Alloy A"],
                process_axes=["heat treatment"],
                property_axes=["strength"],
                comparison_intent=None,
                confidence=0.9,
                reason="Synthetic migration fixture",
            )
        )
        session.flush()
        session.add(
            ResearchObjectiveLifecycle(
                collection_id="collection-1",
                objective_id="objective-linked",
                source_build_id="build-1",
                status="confirmed",
                analysis_error=None,
                analysis_progress=None,
                created_at=now,
                updated_at=now,
            )
        )


def _write_source(path: Path, *, mutation: str | None = None) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(_SOURCE_SCHEMA)
        goals = [
            (
                "collection-1",
                "goal-linked",
                "How does heat treatment affect strength?",
                "objective_candidate",
                '["Alloy A"]',
                '["heat treatment"]',
                '["strength"]',
                "objective-linked",
                "running" if mutation == "running" else "ready",
                None,
                NOW,
                NOW,
                "{}",
            ),
            (
                "collection-1",
                "goal-standalone",
                "Which process window improves ductility?",
                "user_input",
                '["Alloy A"]',
                '["process window"]',
                '["ductility"]',
                None,
                "pending",
                None,
                NOW,
                NOW,
                "{}",
            ),
        ]
        if mutation == "objective_drift":
            goals[0] = (*goals[0][:2], "A different research question", *goals[0][3:])
        if mutation == "duplicate_conflict":
            goals.append(
                (
                    "collection-1",
                    "goal-duplicate",
                    "A non-equivalent question",
                    "objective_candidate",
                    "[]",
                    "[]",
                    "[]",
                    "objective-linked",
                    "ready",
                    None,
                    NOW,
                    NOW,
                    "{}",
                )
            )
        if mutation == "duplicate_equivalent":
            goals.append(
                (
                    "collection-1",
                    "goal-duplicate",
                    "How does heat treatment affect strength?",
                    "objective_candidate",
                    '["Alloy A"]',
                    '["heat treatment"]',
                    '["strength"]',
                    "objective-linked",
                    "ready",
                    None,
                    NOW,
                    NOW,
                    "{}",
                )
            )
        connection.executemany(
            "INSERT INTO core_confirmed_goals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            goals,
        )
        understanding = _understanding_payload()
        if mutation == "no_findings":
            understanding["presentation"]["findings"] = []
        if mutation == "evidence_drift":
            evidence = understanding["evidence_refs"][0]
            evidence["document_id"] = "missing-document"
            evidence["fact_ids"] = ["missing-fact"]
            evidence["anchor_ids"] = ["missing-anchor"]
        connection.execute(
            "INSERT INTO core_research_understanding_artifacts VALUES (?, ?, ?, ?, ?, ?)",
            (
                "collection-1",
                "goal",
                "goal-linked",
                understanding["schema_version"],
                understanding["state"],
                json.dumps(understanding, sort_keys=True),
            ),
        )
        if mutation == "scope_conflict":
            objective_understanding = _understanding_payload()
            objective_understanding["claims"][0]["statement"] = "Conflicting content"
            objective_understanding["scope"] = {
                "scope_type": "objective",
                "collection_id": "collection-1",
                "objective_id": "objective-linked",
            }
            connection.execute(
                "INSERT INTO core_research_understanding_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "collection-1",
                    "objective",
                    "objective-linked",
                    objective_understanding["schema_version"],
                    objective_understanding["state"],
                    json.dumps(objective_understanding, sort_keys=True),
                ),
            )
        referenced_goal = "goal-missing" if mutation == "orphan" else "goal-linked"
        connection.execute(
            "INSERT INTO research_understanding_feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "feedback-1",
                "collection-1",
                "goal",
                referenced_goal,
                "finding-1",
                "claim-1",
                "finding.v1:test",
                "accepted",
                "none",
                None,
                "reviewer-1",
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO research_understanding_curations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "curation-1",
                "collection-1",
                "goal",
                "goal-linked",
                "finding-1",
                "claim-1",
                "finding.v1:test",
                "finding",
                "supported",
                "Heat treatment improves strength.",
                "strong",
                "accepted",
                "[]",
                "[]",
                "[]",
                "increases",
                "Alloy A",
                '["evidence-1"]',
                "[]",
                "reviewed",
                "reviewer-1",
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO goal_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "session-1",
                "user-missing" if mutation == "orphan_user" else "user-1",
                "collection-1",
                None,
                None,
                "objective-linked",
                "goal-linked",
                "How does heat treatment affect strength?",
                "{}",
                "grounded",
                "",
                "[]",
                "[]",
                "[]",
                "build-1",
                NOW,
                NOW,
            ),
        )
        message_source_links = (
            '[{"kind":"evidence","label":"Finding","href":"/goals/goal-linked"}]'
            if mutation == "embedded_goal_url"
            else '[{"kind":"evidence","label":"Finding","href":"/objectives/objective-linked"}]'
        )
        connection.execute(
            "INSERT INTO goal_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "message-1",
                "session-1",
                0,
                "assistant",
                "Grounded answer",
                "collection_grounded",
                '["evidence-1"]',
                "[]",
                "{}",
                message_source_links,
                NOW,
                "protocol_ready_findings",
                '[{"finding_id":"finding-1","evidence_ref_ids":["evidence-1"]}]',
            ),
        )
        connection.execute(
            "INSERT INTO goal_experiment_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "plan-1",
                "collection-1",
                "goal-linked",
                "Validation plan",
                "Repeat the controlled experiment.",
                "ready_for_review",
                "message-1",
                '[{"kind":"evidence","href":"/objectives/objective-linked"}]',
                '{"finding_ids":["finding-1"]}',
                "user-1",
                NOW,
                NOW,
            ),
        )
    return path


def _understanding_payload() -> dict:
    return {
        "schema_version": "research_understanding.v1",
        "state": "ready",
        "scope": {
            "scope_type": "goal",
            "collection_id": "collection-1",
            "goal_id": "goal-linked",
            "objective_id": "objective-linked",
            "title": "Heat treatment strength",
        },
        "claims": [
            {
                "claim_id": "claim-1",
                "claim_type": "finding",
                "statement": "Heat treatment improves strength.",
                "status": "supported",
                "confidence": 0.9,
                "evidence_ref_ids": ["evidence-1"],
                "context_ids": [],
                "source_object_ids": [],
                "warnings": [],
            }
        ],
        "relations": [],
        "evidence_refs": [
            {
                "evidence_ref_id": "evidence-1",
                "source_kind": "finding",
                "document_id": "document-1",
                "label": "Synthetic evidence",
                "locator": {"page": 1},
                "fact_ids": ["result-1"],
                "anchor_ids": ["anchor-1"],
                "confidence": 0.9,
                "traceability_status": "resolved",
                "quote": "Strength increased.",
                "href": "/api/v1/collections/collection-1/documents/document-1/source",
            }
        ],
        "contexts": [],
        "warnings": [],
        "model_traces": [],
        "presentation": {
            "findings": [
                {
                    "finding_id": "finding-1",
                    "claim_id": "claim-1",
                    "statement": "Heat treatment improves strength.",
                    "fingerprint": "finding.v1:test",
                    "evidence_ref_ids": ["evidence-1"],
                    "review_status": "accepted",
                }
            ]
        },
    }


_SOURCE_SCHEMA = """
CREATE TABLE core_confirmed_goals (
    collection_id TEXT NOT NULL, goal_id TEXT NOT NULL, question TEXT NOT NULL,
    source_type TEXT NOT NULL, material_hints TEXT NOT NULL, process_hints TEXT NOT NULL,
    property_hints TEXT NOT NULL, source_objective_id TEXT, status TEXT NOT NULL,
    analysis_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(collection_id, goal_id)
);
CREATE TABLE core_research_understanding_artifacts (
    collection_id TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
    schema_version TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(collection_id, scope_type, scope_id)
);
CREATE TABLE research_understanding_feedback (
    feedback_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL, scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL, finding_id TEXT, claim_id TEXT NOT NULL,
    finding_fingerprint TEXT, review_status TEXT NOT NULL, issue_type TEXT NOT NULL,
    note TEXT, reviewer TEXT, created_at TEXT NOT NULL
);
CREATE TABLE research_understanding_curations (
    curation_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL, scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL, finding_id TEXT, claim_id TEXT NOT NULL,
    finding_fingerprint TEXT, curated_claim_type TEXT NOT NULL,
    curated_status TEXT NOT NULL, curated_statement TEXT NOT NULL,
    curated_support_grade TEXT, curated_review_status TEXT,
    curated_variables_json TEXT NOT NULL, curated_mediators_json TEXT NOT NULL,
    curated_outcomes_json TEXT NOT NULL, curated_direction TEXT,
    curated_scope_summary TEXT, curated_evidence_ref_ids_json TEXT NOT NULL,
    curated_context_ids_json TEXT NOT NULL, note TEXT, reviewer TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE goal_sessions (
    session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, collection_id TEXT NOT NULL,
    focused_material_id TEXT, focused_paper_id TEXT, focused_objective_id TEXT,
    focused_goal_id TEXT, goal_text TEXT, goal_brief_json TEXT NOT NULL,
    answer_mode TEXT NOT NULL, rolling_summary TEXT NOT NULL,
    last_evidence_ids TEXT NOT NULL, last_material_ids TEXT NOT NULL,
    last_paper_ids TEXT NOT NULL, collection_data_version TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE goal_messages (
    message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, position INTEGER NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, source_mode TEXT,
    used_evidence_ids TEXT NOT NULL, warnings TEXT NOT NULL, links TEXT NOT NULL,
    source_links TEXT NOT NULL, created_at TEXT NOT NULL, review_gate TEXT,
    source_finding_refs TEXT NOT NULL
);
CREATE TABLE goal_experiment_plans (
    plan_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL, goal_id TEXT NOT NULL,
    title TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL,
    source_message_id TEXT, source_links TEXT NOT NULL, metadata TEXT NOT NULL,
    created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""
