#!/usr/bin/env python3
"""Offline, dry-run-first migration from historical Goal to Objective identity."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.postgres.models.auth import AuthUser
from infra.persistence.postgres.models.evaluation import (
    ResearchUnderstandingCurationRecord,
    ResearchUnderstandingFeedbackRecord,
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
    PaperFactBaselineReference,
    PaperFactCharacterizationObservation,
    PaperFactEvidenceAnchor,
    PaperFactMeasurementResult,
    PaperFactMethod,
    PaperFactSampleVariant,
    PaperFactStructureFeature,
    PaperFactTestCondition,
)
from infra.persistence.postgres.models.source import SourceDocument
from infra.persistence.postgres.models.understanding import (
    ResearchClaimRecord,
    ResearchContextRecord,
    ResearchEvidenceRefRecord,
    ResearchFindingRecord,
    ResearchRelationRecord,
    ResearchUnderstandingRecord,
    research_claim_context_links,
    research_claim_evidence_links,
    research_finding_evidence_links,
    research_relation_context_links,
    research_relation_evidence_links,
)


_REQUIRED_SOURCE_TABLES = (
    "core_confirmed_goals",
    "core_research_understanding_artifacts",
    "goal_experiment_plans",
    "goal_messages",
    "goal_sessions",
    "research_understanding_curations",
    "research_understanding_feedback",
)
_FAMILIES = (
    "understandings",
    "feedback",
    "curations",
    "sessions",
    "messages",
    "plans",
)
_FORBIDDEN_IDENTITY_KEYS = frozenset(
    {"goal_id", "source_objective_id", "focused_goal_id"}
)


@dataclass(frozen=True)
class GoalObjectiveMapping:
    collection_id: str
    goal_id: str
    objective_id: str
    source_build_id: str
    mapping_kind: str
    lifecycle_status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "collection_id": self.collection_id,
            "goal_id": self.goal_id,
            "objective_id": self.objective_id,
            "source_build_id": self.source_build_id,
            "mapping_kind": self.mapping_kind,
            "lifecycle_status": self.lifecycle_status,
        }


@dataclass(frozen=True)
class MigrationBlocker:
    code: str
    collection_id: str | None
    record_id: str | None
    detail: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "collection_id": self.collection_id,
            "record_id": self.record_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MigrationReport:
    status: str
    source_sha256: str
    manifest_sha256: str
    mappings: tuple[GoalObjectiveMapping, ...]
    blockers: tuple[MigrationBlocker, ...]
    record_counts: dict[str, int]
    content_hashes: dict[str, str]
    evidence_link_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "objective-identity-migration.v1",
            "status": self.status,
            "source_sha256": self.source_sha256,
            "manifest_sha256": self.manifest_sha256,
            "mappings": [item.to_dict() for item in self.mappings],
            "blockers": [item.to_dict() for item in self.blockers],
            "record_counts": dict(sorted(self.record_counts.items())),
            "content_hashes": dict(sorted(self.content_hashes.items())),
            "evidence_link_count": self.evidence_link_count,
        }


class MigrationBlockedError(RuntimeError):
    def __init__(self, report: MigrationReport) -> None:
        self.report = report
        super().__init__(f"objective identity migration blocked by {len(report.blockers)} issue(s)")


@dataclass(frozen=True)
class _MigrationData:
    report: MigrationReport
    goals: tuple[dict[str, Any], ...]
    understandings: tuple[dict[str, Any], ...]
    feedback: tuple[dict[str, Any], ...]
    curations: tuple[dict[str, Any], ...]
    sessions: tuple[dict[str, Any], ...]
    messages: tuple[dict[str, Any], ...]
    plans: tuple[dict[str, Any], ...]


def build_migration_plan(
    source_path: Path,
    session_factory: sessionmaker[Session],
) -> MigrationReport:
    data = _prepare_migration(Path(source_path), session_factory)
    if data.report.blockers:
        raise MigrationBlockedError(data.report)
    return data.report


def apply_migration(
    source_path: Path,
    session_factory: sessionmaker[Session],
    *,
    expected_source_sha256: str,
    backup_reference: str,
) -> MigrationReport:
    backup_reference = backup_reference.strip()
    if not backup_reference:
        raise ValueError("a verified backup reference is required for apply")
    data = _prepare_migration(Path(source_path), session_factory)
    if data.report.blockers:
        raise MigrationBlockedError(data.report)
    if expected_source_sha256 != data.report.source_sha256:
        raise ValueError("reviewed source SHA-256 does not match the current snapshot")

    with session_factory.begin() as session:
        existing_audit = session.get(
            ObjectiveIdentityMigration, data.report.source_sha256
        )
        if existing_audit is not None:
            if existing_audit.manifest_sha256 != data.report.manifest_sha256:
                raise ValueError("completed migration manifest does not match current target state")
            return replace(data.report, status="already_applied")

        _insert_standalone_objectives(session, data)
        _upsert_lifecycles(session, data)
        _insert_understandings(session, data.understandings)
        _insert_feedback(session, data.feedback)
        _insert_curations(session, data.curations)
        _insert_sessions(session, data.sessions)
        _insert_messages(session, data.messages)
        _insert_plans(session, data.plans)
        _validate_target_counts(session, data.report)
        session.add(
            ObjectiveIdentityMigration(
                source_sha256=data.report.source_sha256,
                manifest_sha256=data.report.manifest_sha256,
                backup_reference=backup_reference,
                status="applied",
                record_counts=data.report.record_counts,
                content_hashes=data.report.content_hashes,
                applied_at=datetime.now(timezone.utc),
            )
        )
    return replace(data.report, status="applied")


def _prepare_migration(
    source_path: Path,
    session_factory: sessionmaker[Session],
) -> _MigrationData:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_sha256 = sha256(source_path.read_bytes()).hexdigest()
    source = _read_source(source_path)
    if sha256(source_path.read_bytes()).hexdigest() != source_sha256:
        raise ValueError("source snapshot changed while it was being read")
    blockers: list[MigrationBlocker] = []
    with session_factory() as session:
        completed_audit = session.get(ObjectiveIdentityMigration, source_sha256)
        mappings = _build_mappings(
            session,
            source["goals"],
            blockers,
            allow_existing_standalone=completed_audit is not None,
        )
        mapping_by_goal = {
            (item.collection_id, item.goal_id): item for item in mappings
        }
        understanding_rows = _normalize_understandings(
            source["understandings"], mapping_by_goal, blockers
        )
        _validate_evidence_sources(session, understanding_rows, blockers)
        understandings_by_objective = {
            (item["collection_id"], item["objective_id"]): item
            for item in understanding_rows
        }
        feedback = _normalize_reviews(
            "feedback",
            source["feedback"],
            mapping_by_goal,
            understandings_by_objective,
            blockers,
        )
        curations = _normalize_reviews(
            "curations",
            source["curations"],
            mapping_by_goal,
            understandings_by_objective,
            blockers,
        )
        valid_user_ids = set(session.scalars(select(AuthUser.user_id)))
        sessions = _normalize_sessions(
            source["sessions"],
            mapping_by_goal,
            mappings,
            valid_user_ids,
            blockers,
        )
        messages = _normalize_messages(source["messages"], sessions, blockers)
        plans = _normalize_plans(
            source["plans"], mapping_by_goal, messages, blockers
        )
        _detect_target_conflicts(
            session,
            source_sha256,
            understanding_rows,
            blockers,
        )

    families = {
        "understandings": understanding_rows,
        "feedback": feedback,
        "curations": curations,
        "sessions": sessions,
        "messages": messages,
        "plans": plans,
    }
    _validate_no_residual_goal_identity(families, blockers)
    record_counts = {name: len(rows) for name, rows in families.items()}
    content_hashes = {name: _family_hash(rows) for name, rows in families.items()}
    evidence_link_count = sum(
        len(item["payload"].get("evidence_refs") or ())
        for item in understanding_rows
    )
    sorted_blockers = tuple(
        sorted(
            blockers,
            key=lambda item: (
                item.code,
                item.collection_id or "",
                item.record_id or "",
                item.detail,
            ),
        )
    )
    sorted_mappings = tuple(
        sorted(mappings, key=lambda item: (item.collection_id, item.goal_id))
    )
    manifest = {
        "source_sha256": source_sha256,
        "mappings": [item.to_dict() for item in sorted_mappings],
        "record_counts": record_counts,
        "content_hashes": content_hashes,
        "evidence_link_count": evidence_link_count,
    }
    report = MigrationReport(
        status="blocked" if sorted_blockers else "dry_run_ready",
        source_sha256=source_sha256,
        manifest_sha256=_hash_json(manifest),
        mappings=sorted_mappings,
        blockers=sorted_blockers,
        record_counts=record_counts,
        content_hashes=content_hashes,
        evidence_link_count=evidence_link_count,
    )
    return _MigrationData(
        report=report,
        goals=tuple(source["goals"]),
        understandings=tuple(understanding_rows),
        feedback=tuple(feedback),
        curations=tuple(curations),
        sessions=tuple(sessions),
        messages=tuple(messages),
        plans=tuple(plans),
    )


def _read_source(path: Path) -> dict[str, list[dict[str, Any]]]:
    uri = f"file:{path.resolve()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(set(_REQUIRED_SOURCE_TABLES) - tables)
        if missing:
            raise ValueError(f"source snapshot is missing tables: {', '.join(missing)}")
        return {
            "goals": _rows(connection, "core_confirmed_goals", "collection_id, goal_id"),
            "understandings": _rows(
                connection,
                "core_research_understanding_artifacts",
                "collection_id, scope_type, scope_id",
            ),
            "feedback": _rows(
                connection, "research_understanding_feedback", "feedback_id"
            ),
            "curations": _rows(
                connection, "research_understanding_curations", "curation_id"
            ),
            "sessions": _rows(connection, "goal_sessions", "session_id"),
            "messages": _rows(connection, "goal_messages", "session_id, position"),
            "plans": _rows(connection, "goal_experiment_plans", "plan_id"),
        }


def _rows(
    connection: sqlite3.Connection,
    table: str,
    order_by: str,
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}")]


def _build_mappings(
    session: Session,
    goals: list[dict[str, Any]],
    blockers: list[MigrationBlocker],
    *,
    allow_existing_standalone: bool,
) -> list[GoalObjectiveMapping]:
    objectives = session.scalars(select(ObjectiveResearchRecord)).all()
    objective_by_key = {
        (item.collection_id, item.objective_id): item for item in objectives
    }
    builds_by_collection: dict[str, list[ObjectiveBuild]] = {}
    for build in session.scalars(select(ObjectiveBuild)).all():
        builds_by_collection.setdefault(build.collection_id, []).append(build)
    lifecycles = {
        (item.collection_id, item.objective_id): item
        for item in session.scalars(select(ResearchObjectiveLifecycle)).all()
    }
    mappings: list[GoalObjectiveMapping] = []
    signatures_by_objective: dict[tuple[str, str], tuple[Any, ...]] = {}
    for goal in goals:
        collection_id = str(goal["collection_id"])
        goal_id = str(goal["goal_id"])
        status = str(goal["status"])
        if status == "running":
            blockers.append(
                MigrationBlocker(
                    "running_goal",
                    collection_id,
                    goal_id,
                    "historical running work must be resolved before migration",
                )
            )
        source_objective_id = _optional_text(goal.get("source_objective_id"))
        if source_objective_id:
            objective = objective_by_key.get((collection_id, source_objective_id))
            if objective is None:
                blockers.append(
                    MigrationBlocker(
                        "orphan_source_objective",
                        collection_id,
                        goal_id,
                        "linked Objective does not exist in the same collection",
                    )
                )
                continue
            objective_id = source_objective_id
            source_build_id = objective.build_id
            mapping_kind = "linked"
            if _goal_signature(goal) != _objective_signature(objective):
                blockers.append(
                    MigrationBlocker(
                        "objective_snapshot_drift",
                        collection_id,
                        goal_id,
                        "historical Goal content differs from its linked Objective",
                    )
                )
            lifecycle = lifecycles.get((collection_id, objective_id))
            if lifecycle and lifecycle.status == "running":
                blockers.append(
                    MigrationBlocker(
                        "running_objective",
                        collection_id,
                        objective_id,
                        "target Objective analysis is running",
                    )
                )
            if lifecycle and lifecycle.source_build_id != source_build_id:
                blockers.append(
                    MigrationBlocker(
                        "objective_snapshot_drift",
                        collection_id,
                        objective_id,
                        "target Objective lifecycle pins a different source build",
                    )
                )
        else:
            builds = sorted(
                builds_by_collection.get(collection_id, ()),
                key=lambda item: item.build_id,
            )
            if len(builds) != 1:
                blockers.append(
                    MigrationBlocker(
                        "standalone_objective_build_ambiguous",
                        collection_id,
                        goal_id,
                        "standalone Goal requires exactly one Objective build",
                    )
                )
                continue
            objective_id = _standalone_objective_id(collection_id, goal_id)
            source_build_id = builds[0].build_id
            mapping_kind = "standalone"
            existing_standalone = objective_by_key.get((collection_id, objective_id))
            if existing_standalone is not None and not allow_existing_standalone:
                blockers.append(
                    MigrationBlocker(
                        "partial_target_state",
                        collection_id,
                        objective_id,
                        "deterministic standalone Objective already exists without migration audit",
                    )
                )
        signature = _goal_signature(goal)
        objective_key = (collection_id, objective_id)
        previous_signature = signatures_by_objective.get(objective_key)
        if previous_signature is not None and previous_signature != signature:
            blockers.append(
                MigrationBlocker(
                    "duplicate_goal_conflict",
                    collection_id,
                    goal_id,
                    "non-equivalent Goals map to the same Objective",
                )
            )
        signatures_by_objective[objective_key] = signature
        mappings.append(
            GoalObjectiveMapping(
                collection_id=collection_id,
                goal_id=goal_id,
                objective_id=objective_id,
                source_build_id=source_build_id,
                mapping_kind=mapping_kind,
                lifecycle_status=_lifecycle_status(status),
            )
        )
    return mappings


def _goal_signature(goal: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _normalized_text(goal.get("question")),
        tuple(_json_list(goal.get("material_hints"))),
        tuple(_json_list(goal.get("process_hints"))),
        tuple(_json_list(goal.get("property_hints"))),
    )


def _objective_signature(objective: ObjectiveResearchRecord) -> tuple[Any, ...]:
    return (
        _normalized_text(objective.question),
        tuple(objective.material_scope),
        tuple(objective.process_axes),
        tuple(objective.property_axes),
    )


def _normalize_understandings(
    rows: list[dict[str, Any]],
    mappings: dict[tuple[str, str], GoalObjectiveMapping],
    blockers: list[MigrationBlocker],
) -> list[dict[str, Any]]:
    by_objective: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        collection_id = str(row["collection_id"])
        scope_type = str(row["scope_type"])
        scope_id = str(row["scope_id"])
        if scope_type == "goal":
            mapping = mappings.get((collection_id, scope_id))
            if mapping is None:
                blockers.append(
                    MigrationBlocker(
                        "orphan_goal_reference",
                        collection_id,
                        scope_id,
                        "Understanding references a Goal with no valid mapping",
                    )
                )
                continue
        elif scope_type == "objective":
            matching = [
                item
                for item in mappings.values()
                if item.collection_id == collection_id and item.objective_id == scope_id
            ]
            if not matching:
                blockers.append(
                    MigrationBlocker(
                        "orphan_objective_understanding",
                        collection_id,
                        scope_id,
                        "Objective-scoped Understanding has no migrated Objective",
                    )
                )
                continue
            mapping = matching[0]
        else:
            continue
        payload = _json_object(row["payload"])
        normalized_scope = {
            "scope_type": "objective",
            "collection_id": collection_id,
            "objective_id": mapping.objective_id,
            "title": (payload.get("scope") or {}).get("title"),
        }
        payload["scope"] = normalized_scope
        payload = _remove_identity_keys(payload)
        understanding_id = _stable_id(
            "understanding", collection_id, mapping.objective_id
        )
        item = {
            "understanding_id": understanding_id,
            "collection_id": collection_id,
            "objective_id": mapping.objective_id,
            "source_build_id": mapping.source_build_id,
            "created_at": str(row.get("updated_at") or row.get("created_at") or ""),
            "payload": payload,
            "content_sha256": _hash_json(payload),
        }
        key = (collection_id, mapping.objective_id)
        previous = by_objective.get(key)
        if previous is not None and previous["content_sha256"] != item["content_sha256"]:
            blockers.append(
                MigrationBlocker(
                    "understanding_scope_conflict",
                    collection_id,
                    mapping.objective_id,
                    "Goal and Objective scopes contain different Understanding content",
                )
            )
            continue
        by_objective[key] = item
    return [by_objective[key] for key in sorted(by_objective)]


def _normalize_reviews(
    family: str,
    rows: list[dict[str, Any]],
    mappings: dict[tuple[str, str], GoalObjectiveMapping],
    understandings: dict[tuple[str, str], dict[str, Any]],
    blockers: list[MigrationBlocker],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        collection_id = str(row["collection_id"])
        scope_type = str(row["scope_type"])
        scope_id = str(row["scope_id"])
        mapping = mappings.get((collection_id, scope_id)) if scope_type == "goal" else None
        objective_id = mapping.objective_id if mapping else scope_id
        understanding = understandings.get((collection_id, objective_id))
        record_id = str(row[f"{'feedback' if family == 'feedback' else 'curation'}_id"])
        if understanding is None:
            blockers.append(
                MigrationBlocker(
                    "orphan_goal_reference",
                    collection_id,
                    record_id,
                    f"{family} row has no migrated Understanding",
                )
            )
            continue
        payload = understanding["payload"]
        claim_ids = {str(item.get("claim_id")) for item in payload.get("claims") or ()}
        findings = _findings(payload)
        finding_ids = {str(item.get("finding_id")) for item in findings}
        claim_id = _optional_text(row.get("claim_id"))
        finding_id = _optional_text(row.get("finding_id"))
        if not claim_id or claim_id not in claim_ids:
            blockers.append(
                MigrationBlocker(
                    "orphan_review_claim", collection_id, record_id, "review claim does not exist"
                )
            )
            continue
        if finding_id and finding_id not in finding_ids:
            blockers.append(
                MigrationBlocker(
                    "orphan_review_finding", collection_id, record_id, "review Finding does not exist"
                )
            )
            continue
        item = _remove_identity_keys(dict(row))
        item.pop("scope_type", None)
        item.pop("scope_id", None)
        item.update(
            {
                "understanding_id": understanding["understanding_id"],
                "collection_id": collection_id,
                "objective_id": objective_id,
                "claim_id": claim_id,
                "finding_id": finding_id,
            }
        )
        normalized.append(item)
    return sorted(normalized, key=lambda item: str(item.get("feedback_id") or item.get("curation_id")))


def _normalize_sessions(
    rows: list[dict[str, Any]],
    mappings: dict[tuple[str, str], GoalObjectiveMapping],
    all_mappings: list[GoalObjectiveMapping],
    valid_user_ids: set[str],
    blockers: list[MigrationBlocker],
) -> list[dict[str, Any]]:
    objectives = {(item.collection_id, item.objective_id) for item in all_mappings}
    normalized: list[dict[str, Any]] = []
    for row in rows:
        collection_id = str(row["collection_id"])
        user_id = str(row["user_id"])
        if user_id not in valid_user_ids:
            blockers.append(
                MigrationBlocker(
                    "orphan_session_user",
                    collection_id,
                    str(row["session_id"]),
                    "session user does not exist in PostgreSQL",
                )
            )
            continue
        goal_id = _optional_text(row.get("focused_goal_id"))
        existing_objective_id = _optional_text(row.get("focused_objective_id"))
        mapping = mappings.get((collection_id, goal_id)) if goal_id else None
        if goal_id and mapping is None:
            blockers.append(
                MigrationBlocker(
                    "orphan_goal_reference",
                    collection_id,
                    str(row["session_id"]),
                    "session focuses a Goal with no valid mapping",
                )
            )
            continue
        objective_id = mapping.objective_id if mapping else existing_objective_id
        if mapping and existing_objective_id and existing_objective_id != mapping.objective_id:
            blockers.append(
                MigrationBlocker(
                    "session_focus_conflict",
                    collection_id,
                    str(row["session_id"]),
                    "focused Goal and Objective disagree",
                )
            )
            continue
        if objective_id and (collection_id, objective_id) not in objectives:
            blockers.append(
                MigrationBlocker(
                    "orphan_session_objective",
                    collection_id,
                    str(row["session_id"]),
                    "session Objective is not part of the migration",
                )
            )
            continue
        item = _remove_identity_keys(dict(row))
        item["focused_objective_id"] = objective_id
        item["intent_brief"] = _remove_identity_keys(
            _json_object(row.get("goal_brief_json") or "{}")
        )
        normalized.append(item)
    return sorted(normalized, key=lambda item: str(item["session_id"]))


def _normalize_messages(
    rows: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    blockers: list[MigrationBlocker],
) -> list[dict[str, Any]]:
    session_ids = {str(item["session_id"]) for item in sessions}
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if str(row["session_id"]) not in session_ids:
            blockers.append(
                MigrationBlocker(
                    "orphan_message_session",
                    None,
                    str(row["message_id"]),
                    "message session was not migrated",
                )
            )
            continue
        item = dict(row)
        for field in (
            "used_evidence_ids",
            "warnings",
            "source_links",
            "source_finding_refs",
        ):
            item[field] = _remove_identity_keys(_json_list(item.get(field)))
        item["links"] = _remove_identity_keys(_json_object(item.get("links") or "{}"))
        normalized.append(item)
    return sorted(normalized, key=lambda item: (str(item["session_id"]), int(item["position"])))


def _normalize_plans(
    rows: list[dict[str, Any]],
    mappings: dict[tuple[str, str], GoalObjectiveMapping],
    messages: list[dict[str, Any]],
    blockers: list[MigrationBlocker],
) -> list[dict[str, Any]]:
    message_ids = {str(item["message_id"]) for item in messages}
    normalized: list[dict[str, Any]] = []
    for row in rows:
        collection_id = str(row["collection_id"])
        goal_id = str(row["goal_id"])
        mapping = mappings.get((collection_id, goal_id))
        if mapping is None:
            blockers.append(
                MigrationBlocker(
                    "orphan_goal_reference",
                    collection_id,
                    str(row["plan_id"]),
                    "experiment plan references a Goal with no valid mapping",
                )
            )
            continue
        source_message_id = _optional_text(row.get("source_message_id"))
        if source_message_id and source_message_id not in message_ids:
            blockers.append(
                MigrationBlocker(
                    "orphan_plan_message",
                    collection_id,
                    str(row["plan_id"]),
                    "experiment plan source message was not migrated",
                )
            )
            continue
        item = _remove_identity_keys(dict(row))
        item["objective_id"] = mapping.objective_id
        item["source_links"] = _remove_identity_keys(_json_list(row["source_links"]))
        item["metadata_json"] = _remove_identity_keys(_json_object(row["metadata"]))
        normalized.append(item)
    return sorted(normalized, key=lambda item: str(item["plan_id"]))


def _detect_target_conflicts(
    session: Session,
    source_sha256: str,
    understandings: list[dict[str, Any]],
    blockers: list[MigrationBlocker],
) -> None:
    audit = session.get(ObjectiveIdentityMigration, source_sha256)
    target_models = {
        "understandings": ResearchUnderstandingRecord,
        "feedback": ResearchUnderstandingFeedbackRecord,
        "curations": ResearchUnderstandingCurationRecord,
        "sessions": ObjectiveSession,
        "messages": ObjectiveMessage,
        "plans": ObjectiveExperimentPlan,
    }
    target_counts = {
        family: session.scalar(select(func.count()).select_from(model))
        for family, model in target_models.items()
    }
    if audit is not None:
        if target_counts != audit.record_counts:
            blockers.append(
                MigrationBlocker(
                    "applied_target_drift",
                    None,
                    source_sha256,
                    "completed migration target counts no longer match its audit",
                )
            )
        return
    for family, count in target_counts.items():
        if count:
            blockers.append(
                MigrationBlocker(
                    "partial_target_state",
                    None,
                    family,
                    f"target contains {count} {family} row(s) without a completed audit",
                )
            )
    for item in understandings:
        existing = session.scalar(
            select(ResearchUnderstandingRecord).where(
                ResearchUnderstandingRecord.collection_id == item["collection_id"],
                ResearchUnderstandingRecord.objective_id == item["objective_id"],
                ResearchUnderstandingRecord.version == 1,
            )
        )
        if existing and existing.content_sha256 != item["content_sha256"]:
            blockers.append(
                MigrationBlocker(
                    "target_content_conflict",
                    item["collection_id"],
                    item["objective_id"],
                    "existing target Understanding has different content",
                )
            )


def _validate_evidence_sources(
    session: Session,
    understandings: list[dict[str, Any]],
    blockers: list[MigrationBlocker],
) -> None:
    fact_id_columns = (
        PaperFactMethod.method_id,
        PaperFactSampleVariant.variant_id,
        PaperFactTestCondition.test_condition_id,
        PaperFactBaselineReference.baseline_id,
        PaperFactCharacterizationObservation.observation_id,
        PaperFactStructureFeature.feature_id,
        PaperFactMeasurementResult.result_id,
    )
    references_by_build: dict[
        tuple[str, str], tuple[set[str], dict[str, str], dict[str, str]]
    ] = {}
    for understanding in understandings:
        collection_id = str(understanding["collection_id"])
        source_build_id = str(understanding["source_build_id"])
        build_key = (collection_id, source_build_id)
        references = references_by_build.get(build_key)
        if references is None:
            documents = set(
                session.scalars(
                    select(SourceDocument.source_document_id).where(
                        SourceDocument.collection_id == collection_id,
                        SourceDocument.build_id == source_build_id,
                    )
                )
            )
            anchors = {
                str(anchor_id): str(source_document_id)
                for anchor_id, source_document_id in session.execute(
                    select(
                        PaperFactEvidenceAnchor.anchor_id,
                        PaperFactEvidenceAnchor.source_document_id,
                    ).where(
                        PaperFactEvidenceAnchor.collection_id == collection_id,
                        PaperFactEvidenceAnchor.build_id == source_build_id,
                    )
                )
            }
            facts: dict[str, str] = {}
            for id_column in fact_id_columns:
                model = id_column.class_
                facts.update(
                    {
                        str(fact_id): str(source_document_id)
                        for fact_id, source_document_id in session.execute(
                            select(id_column, model.source_document_id).where(
                                model.collection_id == collection_id,
                                model.build_id == source_build_id,
                            )
                        )
                    }
                )
            references = (documents, anchors, facts)
            references_by_build[build_key] = references

        documents, anchors, facts = references
        for evidence in understanding["payload"].get("evidence_refs") or ():
            evidence_ref_id = str(evidence.get("evidence_ref_id") or "unknown")
            document_id = _optional_text(evidence.get("document_id"))
            if document_id and document_id not in documents:
                blockers.append(
                    MigrationBlocker(
                        "missing_evidence_document",
                        collection_id,
                        evidence_ref_id,
                        "Evidence document is absent from the Objective source build",
                    )
                )
            for anchor_id in evidence.get("anchor_ids") or ():
                anchor_document_id = anchors.get(str(anchor_id))
                if anchor_document_id is None:
                    blockers.append(
                        MigrationBlocker(
                            "missing_evidence_anchor",
                            collection_id,
                            evidence_ref_id,
                            "Evidence anchor is absent from the Objective source build",
                        )
                    )
                elif document_id and anchor_document_id != document_id:
                    blockers.append(
                        MigrationBlocker(
                            "evidence_source_conflict",
                            collection_id,
                            evidence_ref_id,
                            "Evidence anchor resolves to a different source document",
                        )
                    )
            for fact_id in evidence.get("fact_ids") or ():
                fact_document_id = facts.get(str(fact_id))
                if fact_document_id is None:
                    blockers.append(
                        MigrationBlocker(
                            "missing_evidence_fact",
                            collection_id,
                            evidence_ref_id,
                            "Evidence fact is absent from the Objective source build",
                        )
                    )
                elif document_id and fact_document_id != document_id:
                    blockers.append(
                        MigrationBlocker(
                            "evidence_source_conflict",
                            collection_id,
                            evidence_ref_id,
                            "Evidence fact resolves to a different source document",
                        )
                    )


def _validate_no_residual_goal_identity(
    families: Mapping[str, list[dict[str, Any]]],
    blockers: list[MigrationBlocker],
) -> None:
    id_fields = (
        "understanding_id",
        "feedback_id",
        "curation_id",
        "session_id",
        "message_id",
        "plan_id",
    )
    for family, rows in families.items():
        for row in rows:
            if not _contains_goal_identity(row):
                continue
            record_id = next(
                (str(row[field]) for field in id_fields if row.get(field)),
                None,
            )
            blockers.append(
                MigrationBlocker(
                    "residual_goal_identity",
                    _optional_text(row.get("collection_id")),
                    record_id,
                    f"normalized {family} payload retains Goal identity",
                )
            )


def _contains_goal_identity(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key) in _FORBIDDEN_IDENTITY_KEYS
            or _contains_goal_identity(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_goal_identity(item) for item in value)
    if not isinstance(value, str):
        return False
    if "/" not in value and "?" not in value:
        return False
    parsed = urlsplit(value)
    path_segments = {segment.casefold() for segment in parsed.path.split("/")}
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query)}
    return bool({"goal", "goals"} & path_segments) or bool(
        _FORBIDDEN_IDENTITY_KEYS & query_keys
    )


def _insert_standalone_objectives(session: Session, data: _MigrationData) -> None:
    goals = {(str(item["collection_id"]), str(item["goal_id"])): item for item in data.goals}
    for mapping in data.report.mappings:
        if mapping.mapping_kind != "standalone":
            continue
        existing = session.get(
            ObjectiveResearchRecord,
            {"build_id": mapping.source_build_id, "objective_id": mapping.objective_id},
        )
        if existing is not None:
            continue
        goal = goals[(mapping.collection_id, mapping.goal_id)]
        next_order = session.scalar(
            select(func.coalesce(func.max(ObjectiveResearchRecord.objective_order), -1)).where(
                ObjectiveResearchRecord.build_id == mapping.source_build_id
            )
        ) + 1
        session.add(
            ObjectiveResearchRecord(
                build_id=mapping.source_build_id,
                objective_id=mapping.objective_id,
                collection_id=mapping.collection_id,
                objective_order=next_order,
                question=str(goal["question"]),
                material_scope=_json_list(goal["material_hints"]),
                process_axes=_json_list(goal["process_hints"]),
                property_axes=_json_list(goal["property_hints"]),
                comparison_intent=None,
                confidence=1.0,
                reason="Materialized from a standalone historical Goal during offline migration.",
            )
        )
        session.flush()


def _upsert_lifecycles(session: Session, data: _MigrationData) -> None:
    goal_by_id = {
        (str(item["collection_id"]), str(item["goal_id"])): item for item in data.goals
    }
    understanding_keys = {
        (item["collection_id"], item["objective_id"]): item
        for item in data.understandings
    }
    grouped: dict[tuple[str, str], list[GoalObjectiveMapping]] = {}
    for mapping in data.report.mappings:
        grouped.setdefault((mapping.collection_id, mapping.objective_id), []).append(mapping)
    rank = {"confirmed": 0, "failed": 1, "ready": 2}
    for (collection_id, objective_id), mappings in grouped.items():
        status = max((item.lifecycle_status for item in mappings), key=rank.get)
        error = None
        understanding = understanding_keys.get((collection_id, objective_id))
        has_findings = bool(understanding and _findings(understanding["payload"]))
        if status == "ready" and not has_findings:
            status = "failed"
            error = "Historical ready Goal had no reviewable Findings; retry analysis after migration."
        mapping = mappings[0]
        lifecycle = session.get(
            ResearchObjectiveLifecycle,
            {"collection_id": collection_id, "objective_id": objective_id},
        )
        timestamps = [goal_by_id[(item.collection_id, item.goal_id)] for item in mappings]
        created_at = min(_datetime(item["created_at"]) for item in timestamps)
        updated_at = max(_datetime(item["updated_at"]) for item in timestamps)
        if lifecycle is None:
            session.add(
                ResearchObjectiveLifecycle(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    source_build_id=mapping.source_build_id,
                    status=status,
                    analysis_error=error,
                    analysis_progress={"phase": "migrated", "unit": "steps"},
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        else:
            if lifecycle.status == "running":
                raise RuntimeError("running Objective lifecycle appeared after dry-run")
            lifecycle.status = status
            lifecycle.analysis_error = error
            lifecycle.analysis_progress = {"phase": "migrated", "unit": "steps"}
            lifecycle.updated_at = updated_at
    session.flush()


def _insert_understandings(session: Session, rows: tuple[dict[str, Any], ...]) -> None:
    for item in rows:
        existing = session.get(ResearchUnderstandingRecord, item["understanding_id"])
        if existing is not None:
            continue
        payload = item["payload"]
        session.add(
            ResearchUnderstandingRecord(
                understanding_id=item["understanding_id"],
                collection_id=item["collection_id"],
                objective_id=item["objective_id"],
                source_build_id=item["source_build_id"],
                version=1,
                schema_version=str(payload.get("schema_version") or "research_understanding.v1"),
                state=str(payload.get("state") or "empty"),
                title=_optional_text((payload.get("scope") or {}).get("title")),
                content_sha256=item["content_sha256"],
                warnings=list(payload.get("warnings") or ()),
                presentation_metadata={
                    key: value
                    for key, value in dict(payload.get("presentation") or {}).items()
                    if key not in {"findings", "review_candidates"}
                },
                model_traces=list(payload.get("model_traces") or ()),
                created_at=_datetime(item.get("created_at")),
            )
        )
        session.flush()
        _insert_understanding_children(session, item["understanding_id"], payload)


def _insert_understanding_children(
    session: Session,
    understanding_id: str,
    payload: dict[str, Any],
) -> None:
    claims = list(payload.get("claims") or ())
    relations = list(payload.get("relations") or ())
    evidence_refs = list(payload.get("evidence_refs") or ())
    contexts = list(payload.get("contexts") or ())
    for position, ref in enumerate(evidence_refs):
        session.add(
            ResearchEvidenceRefRecord(
                understanding_id=understanding_id,
                evidence_ref_id=str(ref["evidence_ref_id"]),
                evidence_order=position,
                source_kind=str(ref.get("source_kind") or "unknown"),
                source_document_id=_optional_text(ref.get("document_id")),
                label=str(ref.get("label") or ref["evidence_ref_id"]),
                locator=dict(ref.get("locator") or {}),
                fact_ids=list(ref.get("fact_ids") or ()),
                anchor_ids=list(ref.get("anchor_ids") or ()),
                confidence=ref.get("confidence"),
                traceability_status=str(ref.get("traceability_status") or "unknown"),
                evidence_role=_optional_text(ref.get("evidence_role")),
                quote=_optional_text(ref.get("quote")),
                href=_optional_text(ref.get("href")),
            )
        )
    for position, context in enumerate(contexts):
        session.add(
            ResearchContextRecord(
                understanding_id=understanding_id,
                context_id=str(context["context_id"]),
                context_order=position,
                label=str(context.get("label") or context["context_id"]),
                material_scope=list(context.get("material_scope") or ()),
                process_context=dict(context.get("process_context") or {}),
                test_condition=dict(context.get("test_condition") or {}),
                property_scope=list(context.get("property_scope") or ()),
                limitations=list(context.get("limitations") or ()),
            )
        )
    for position, claim in enumerate(claims):
        session.add(
            ResearchClaimRecord(
                understanding_id=understanding_id,
                claim_id=str(claim["claim_id"]),
                claim_order=position,
                claim_type=str(claim.get("claim_type") or "finding"),
                statement=str(claim.get("statement") or ""),
                status=str(claim.get("status") or "limited"),
                confidence=claim.get("confidence"),
                strength=_optional_text(claim.get("strength")),
                source_object_ids=list(claim.get("source_object_ids") or ()),
                warnings=list(claim.get("warnings") or ()),
            )
        )
    for position, relation in enumerate(relations):
        details = {
            key: value
            for key, value in relation.items()
            if key
            not in {
                "relation_id",
                "relation_type",
                "subject",
                "predicate",
                "object",
                "statement",
                "status",
                "confidence",
                "evidence_ref_ids",
                "context_ids",
                "supporting_evidence_ref_ids",
                "conflicting_evidence_ref_ids",
                "context_evidence_ref_ids",
                "mechanism_evidence_ref_ids",
            }
        }
        session.add(
            ResearchRelationRecord(
                understanding_id=understanding_id,
                relation_id=str(relation["relation_id"]),
                relation_order=position,
                relation_type=str(relation.get("relation_type") or "compares"),
                subject=str(relation.get("subject") or ""),
                predicate=str(relation.get("predicate") or ""),
                object=str(relation.get("object") or ""),
                statement=_optional_text(relation.get("statement")),
                status=str(relation.get("status") or "limited"),
                confidence=relation.get("confidence"),
                details=details,
            )
        )
    session.flush()
    for claim in claims:
        for position, evidence_ref_id in enumerate(claim.get("evidence_ref_ids") or ()):
            session.execute(
                research_claim_evidence_links.insert().values(
                    understanding_id=understanding_id,
                    claim_id=str(claim["claim_id"]),
                    evidence_ref_id=str(evidence_ref_id),
                    position=position,
                )
            )
        for position, context_id in enumerate(claim.get("context_ids") or ()):
            session.execute(
                research_claim_context_links.insert().values(
                    understanding_id=understanding_id,
                    claim_id=str(claim["claim_id"]),
                    context_id=str(context_id),
                    position=position,
                )
            )
    for relation in relations:
        evidence_roles = (
            ("direct", relation.get("evidence_ref_ids") or ()),
            ("supporting", relation.get("supporting_evidence_ref_ids") or ()),
            ("conflicting", relation.get("conflicting_evidence_ref_ids") or ()),
            ("context", relation.get("context_evidence_ref_ids") or ()),
            ("mechanism", relation.get("mechanism_evidence_ref_ids") or ()),
        )
        for role, evidence_ids in evidence_roles:
            for position, evidence_ref_id in enumerate(evidence_ids):
                session.execute(
                    research_relation_evidence_links.insert().values(
                        understanding_id=understanding_id,
                        relation_id=str(relation["relation_id"]),
                        evidence_ref_id=str(evidence_ref_id),
                        role=role,
                        position=position,
                    )
                )
        for position, context_id in enumerate(relation.get("context_ids") or ()):
            session.execute(
                research_relation_context_links.insert().values(
                    understanding_id=understanding_id,
                    relation_id=str(relation["relation_id"]),
                    context_id=str(context_id),
                    position=position,
                )
            )
    for position, finding in enumerate(_findings(payload)):
        evidence_ids = list(finding.get("evidence_ref_ids") or ())
        session.add(
            ResearchFindingRecord(
                understanding_id=understanding_id,
                finding_id=str(finding["finding_id"]),
                claim_id=str(finding["claim_id"]),
                finding_order=position,
                statement=str(finding.get("statement") or ""),
                fingerprint=_optional_text(
                    finding.get("fingerprint") or finding.get("finding_fingerprint")
                ),
                review_status=_optional_text(finding.get("review_status")),
                evidence_ref_ids=evidence_ids,
                details={
                    key: value
                    for key, value in finding.items()
                    if key
                    not in {
                        "finding_id",
                        "claim_id",
                        "statement",
                        "fingerprint",
                        "finding_fingerprint",
                        "review_status",
                        "evidence_ref_ids",
                    }
                },
            )
        )
        session.flush()
        for evidence_position, evidence_ref_id in enumerate(evidence_ids):
            session.execute(
                research_finding_evidence_links.insert().values(
                    understanding_id=understanding_id,
                    finding_id=str(finding["finding_id"]),
                    evidence_ref_id=str(evidence_ref_id),
                    position=evidence_position,
                )
            )


def _insert_feedback(session: Session, rows: tuple[dict[str, Any], ...]) -> None:
    for item in rows:
        if session.get(ResearchUnderstandingFeedbackRecord, item["feedback_id"]):
            continue
        session.add(
            ResearchUnderstandingFeedbackRecord(
                feedback_id=item["feedback_id"],
                understanding_id=item["understanding_id"],
                collection_id=item["collection_id"],
                objective_id=item["objective_id"],
                finding_id=item["finding_id"],
                claim_id=item["claim_id"],
                finding_fingerprint=_optional_text(item.get("finding_fingerprint")),
                review_status=item["review_status"],
                issue_type=item["issue_type"],
                note=_optional_text(item.get("note")),
                reviewer=_optional_text(item.get("reviewer")),
                created_at=_datetime(item.get("created_at")),
            )
        )


def _insert_curations(session: Session, rows: tuple[dict[str, Any], ...]) -> None:
    for item in rows:
        if session.get(ResearchUnderstandingCurationRecord, item["curation_id"]):
            continue
        session.add(
            ResearchUnderstandingCurationRecord(
                curation_id=item["curation_id"],
                understanding_id=item["understanding_id"],
                collection_id=item["collection_id"],
                objective_id=item["objective_id"],
                finding_id=item["finding_id"],
                claim_id=item["claim_id"],
                finding_fingerprint=_optional_text(item.get("finding_fingerprint")),
                curated_claim_type=item["curated_claim_type"],
                curated_status=item["curated_status"],
                curated_statement=item["curated_statement"],
                curated_support_grade=_optional_text(item.get("curated_support_grade")),
                curated_review_status=_optional_text(item.get("curated_review_status")),
                curated_variables=_json_list(item.get("curated_variables_json")),
                curated_mediators=_json_list(item.get("curated_mediators_json")),
                curated_outcomes=_json_list(item.get("curated_outcomes_json")),
                curated_direction=_optional_text(item.get("curated_direction")),
                curated_scope_summary=_optional_text(item.get("curated_scope_summary")),
                curated_evidence_ref_ids=_json_list(
                    item.get("curated_evidence_ref_ids_json")
                ),
                curated_context_ids=_json_list(item.get("curated_context_ids_json")),
                note=_optional_text(item.get("note")),
                reviewer=_optional_text(item.get("reviewer")),
                updated_at=_datetime(item.get("updated_at")),
            )
        )


def _insert_sessions(session: Session, rows: tuple[dict[str, Any], ...]) -> None:
    for item in rows:
        if session.get(ObjectiveSession, item["session_id"]):
            continue
        session.add(
            ObjectiveSession(
                session_id=item["session_id"],
                user_id=item["user_id"],
                collection_id=item["collection_id"],
                focused_material_id=_optional_text(item.get("focused_material_id")),
                focused_paper_id=_optional_text(item.get("focused_paper_id")),
                focused_objective_id=item.get("focused_objective_id"),
                goal_text=_optional_text(item.get("goal_text")),
                intent_brief=item["intent_brief"],
                answer_mode=item["answer_mode"],
                rolling_summary=str(item.get("rolling_summary") or ""),
                last_evidence_ids=_json_list(item.get("last_evidence_ids")),
                last_material_ids=_json_list(item.get("last_material_ids")),
                last_paper_ids=_json_list(item.get("last_paper_ids")),
                collection_data_version=_optional_text(item.get("collection_data_version")),
                created_at=_datetime(item.get("created_at")),
                updated_at=_datetime(item.get("updated_at")),
            )
        )
    session.flush()


def _insert_messages(session: Session, rows: tuple[dict[str, Any], ...]) -> None:
    for item in rows:
        if session.get(ObjectiveMessage, item["message_id"]):
            continue
        session.add(
            ObjectiveMessage(
                message_id=item["message_id"],
                session_id=item["session_id"],
                position=int(item["position"]),
                role=item["role"],
                content=item["content"],
                source_mode=_optional_text(item.get("source_mode")),
                used_evidence_ids=list(item["used_evidence_ids"]),
                warnings=list(item["warnings"]),
                links=dict(item["links"]),
                source_links=list(item["source_links"]),
                review_gate=_optional_text(item.get("review_gate")),
                source_finding_refs=list(item["source_finding_refs"]),
                created_at=_datetime(item.get("created_at")),
            )
        )
    session.flush()


def _insert_plans(session: Session, rows: tuple[dict[str, Any], ...]) -> None:
    for item in rows:
        if session.get(ObjectiveExperimentPlan, item["plan_id"]):
            continue
        session.add(
            ObjectiveExperimentPlan(
                plan_id=item["plan_id"],
                collection_id=item["collection_id"],
                objective_id=item["objective_id"],
                title=item["title"],
                content=item["content"],
                status=item["status"],
                source_message_id=_optional_text(item.get("source_message_id")),
                source_links=list(item["source_links"]),
                metadata_json=dict(item["metadata_json"]),
                created_by=_optional_text(item.get("created_by")),
                created_at=_datetime(item.get("created_at")),
                updated_at=_datetime(item.get("updated_at")),
            )
        )
    session.flush()


def _validate_target_counts(session: Session, report: MigrationReport) -> None:
    models = {
        "understandings": ResearchUnderstandingRecord,
        "feedback": ResearchUnderstandingFeedbackRecord,
        "curations": ResearchUnderstandingCurationRecord,
        "sessions": ObjectiveSession,
        "messages": ObjectiveMessage,
        "plans": ObjectiveExperimentPlan,
    }
    for family, model in models.items():
        count = session.scalar(select(func.count()).select_from(model))
        if count != report.record_counts[family]:
            raise RuntimeError(
                f"post-write count mismatch for {family}: expected "
                f"{report.record_counts[family]}, got {count}"
            )


def _findings(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    presentation = payload.get("presentation")
    if not isinstance(presentation, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("findings", "review_candidates"):
        value = presentation.get(key)
        if isinstance(value, list):
            rows.extend(dict(item) for item in value if isinstance(item, Mapping))
    return rows


def _remove_identity_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _remove_identity_keys(item)
            for key, item in value.items()
            if str(key) not in _FORBIDDEN_IDENTITY_KEYS
        }
    if isinstance(value, list | tuple):
        return [_remove_identity_keys(item) for item in value]
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    if not value:
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError("expected JSON list")
    return parsed


def _hash_json(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _family_hash(rows: list[dict[str, Any]]) -> str:
    if len(rows) == 1:
        row = rows[0]
        return str(row.get("content_sha256") or _hash_json(row))
    return _hash_json(rows)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _standalone_objective_id(collection_id: str, goal_id: str) -> str:
    return _stable_id("obj_migrated", collection_id, goal_id)


def _lifecycle_status(status: str) -> str:
    return {
        "pending": "confirmed",
        "ready": "ready",
        "failed": "failed",
        "running": "confirmed",
    }.get(status, "confirmed")


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _datetime(value: Any) -> datetime:
    text = _optional_text(value)
    if not text:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _write_report(report: MigrationReport, path: Path | None) -> None:
    text = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    if path is None:
        print(text)
        return
    path.write_text(f"{text}\n", encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run and apply the one-way Goal-to-Objective identity migration."
    )
    parser.add_argument("--source", type=Path, required=True, help="Read-only legacy SQLite snapshot")
    parser.add_argument(
        "--database-url",
        help="Target SQLAlchemy URL; omit to use the validated LENS_DATABASE_URL",
    )
    parser.add_argument("--report", type=Path, help="Write the sanitized JSON report")
    parser.add_argument("--apply", action="store_true", help="Apply after all explicit safety gates")
    parser.add_argument("--expected-source-sha256", help="Exact SHA-256 reviewed during dry-run")
    parser.add_argument("--backup-reference", help="Operator-verified backup identifier")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    engine = (
        create_engine(args.database_url)
        if args.database_url
        else build_database_engine(DatabaseSettings())
    )
    sessions = build_session_factory(engine)
    try:
        if args.apply:
            if not args.expected_source_sha256:
                raise ValueError("--expected-source-sha256 is required with --apply")
            report = apply_migration(
                args.source,
                sessions,
                expected_source_sha256=args.expected_source_sha256,
                backup_reference=args.backup_reference or "",
            )
        else:
            report = build_migration_plan(args.source, sessions)
        _write_report(report, args.report)
        return 0
    except MigrationBlockedError as exc:
        _write_report(exc.report, args.report)
        return 2
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GoalObjectiveMapping",
    "MigrationBlockedError",
    "MigrationBlocker",
    "MigrationReport",
    "apply_migration",
    "build_migration_plan",
    "main",
]
