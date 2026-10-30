"""Create Findings from immutable PaperExperiment selections."""

from __future__ import annotations

from dataclasses import dataclass, replace

from application.core.objectives.analysis import (
    experiment_analysis_writer,
    experiment_query_service,
)
from application.core.objectives.objective_analysis_service import (
    ResearchObjectiveNotFoundError,
)
from application.source import collection_service
from domain.core.finding import Finding
from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ServerException,
)
from infra.persistence.database import AsyncSessionLocal
from repositories.objective_repository import (
    OBJECTIVE_ANALYSIS_ABSTENTION_REASONS,
    ObjectiveAnalysis,
)


@dataclass(frozen=True)
class FindingAuthoringResult:
    analysis: ObjectiveAnalysis
    finding: Finding | None


from repositories.objective_repository import ObjectiveRepo


async def create_selection_version(
    *,
    collection_id: str,
    objective_id: str,
    source_analysis_version: int,
    selection_ids: tuple[str, ...],
    comparison_group_ids: tuple[str, ...] = (),
    created_by_user_id: str,
    parent_finding_id: str | None = None,
    limitations: tuple[str, ...] = (),
    abstention_reason: str | None = None,
) -> FindingAuthoringResult:
    limitations = tuple(
        dict.fromkeys(item.strip() for item in limitations if item.strip())
    )
    if len(limitations) > 20 or any(len(item) > 1000 for item in limitations):
        raise RequestInvalidException("Finding limitations exceed the allowed length")
    if abstention_reason is not None:
        if abstention_reason not in OBJECTIVE_ANALYSIS_ABSTENTION_REASONS:
            raise RequestInvalidException("unsupported Finding abstention")
        if (
            selection_ids
            or comparison_group_ids
            or parent_finding_id
            or not limitations
        ):
            raise RequestInvalidException(
                "abstention requires an explanation and no experiment selections or parent"
            )
    await collection_service.get_collection_for_user(collection_id, created_by_user_id)
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)
    if objective.active_analysis_version != source_analysis_version:
        raise ResourceConflictException(
            "Source analysis version is not the active published snapshot.",
            data={"code": "source_analysis_stale"},
        )
    source_analysis = await ObjectiveRepo.read_analysis(
        collection_id, objective_id, source_analysis_version
    )
    if source_analysis is None or source_analysis.status != "succeeded":
        raise ResourceConflictException(
            "Source analysis version is not a completed snapshot.",
            data={"code": "source_analysis_incomplete"},
        )
    source = await experiment_query_service.read_analysis_bundle(
        collection_id, objective_id, source_analysis_version
    )
    selected_ids = set(selection_ids)
    for group_id in comparison_group_ids:
        group = next(
            (item for item in source.groups if item.group_id == group_id), None
        )
        if group is None:
            raise RequestInvalidException(
                f"Finding references an unknown comparison group: {group_id}"
            )
        selected_ids.update(
            item.selection_id for item in group.members if item.role == "included"
        )
    chosen = tuple(
        item for item in source.selections if item.selection_id in selected_ids
    )
    if abstention_reason is None and (not chosen or len(chosen) != len(selected_ids)):
        raise RequestInvalidException(
            "Finding references an unknown experiment selection"
        )
    if parent_finding_id is not None:
        parent = next(
            (item for item in source.findings if item.finding_id == parent_finding_id),
            None,
        )
        if parent is None:
            raise RequestInvalidException(
                "parent Finding is not in the source analysis snapshot"
            )
    coverage = await ObjectiveRepo.list_contributions(
        collection_id, objective_id, source_analysis_version
    )
    _objective, queued = await ObjectiveRepo.queue_analysis(
        collection_id,
        objective_id,
        document_inputs=source_analysis.document_inputs,
        pipeline_version=source_analysis.pipeline_version,
        model_name=source_analysis.model_name,
        prompt_versions=dict(source_analysis.prompt_versions),
        origin="human_authored",
        created_by_user_id=created_by_user_id,
        source_analysis_version=source_analysis_version,
    )
    claimed = await ObjectiveRepo.claim_analysis(
        collection_id, objective_id, queued.analysis_version
    )
    if claimed is None:
        raise ResourceConflictException(
            "Finding analysis snapshot could not be claimed.",
            data={
                "code": "analysis_claim_conflict",
                "analysis_version": queued.analysis_version,
            },
        )
    try:
        async with AsyncSessionLocal() as db, db.begin():
            result = await experiment_analysis_writer.write_selection_finding_revision(
                collection_id=collection_id,
                objective=objective,
                analysis=claimed,
                revisions=source.revisions,
                selections=chosen,
                created_by=created_by_user_id,
                parent_finding_id=parent_finding_id,
                limitations=limitations,
                db=db,
            )
            await ObjectiveRepo.publish_experiment_analysis(
                db,
                collection_id,
                objective_id,
                claimed.analysis_version,
                contributions=tuple(
                    replace(item, analysis_version=claimed.analysis_version)
                    for item in coverage
                ),
                abstention_reason=abstention_reason,
                abstention_note=("\n".join(limitations) if abstention_reason else None),
            )
    except Exception as exc:
        await ObjectiveRepo.fail_analysis(
            collection_id,
            objective_id,
            claimed.analysis_version,
            error_code="authored_finding_publish_failed",
            error_message=str(exc),
            expected_status="running",
        )
        raise
    mapped = {f"{item.selection_id}:v{claimed.analysis_version}" for item in chosen}
    finding = next(
        (item for item in result.findings if set(item.selection_ids) == mapped),
        result.findings[0] if result.findings else None,
    )
    analysis = await ObjectiveRepo.read_analysis(
        collection_id, objective_id, claimed.analysis_version
    )
    if analysis is None:
        raise ServerException(
            "The Finding was published, but its analysis snapshot could not be reloaded.",
            data={
                "code": "published_analysis_reload_failed",
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": claimed.analysis_version,
            },
        )
    return FindingAuthoringResult(analysis=analysis, finding=finding)


async def validate_selection_references(
    *,
    collection_id: str,
    objective_id: str,
    source_analysis_version: int,
    selection_ids: tuple[str, ...],
    comparison_group_ids: tuple[str, ...] = (),
    user_id: str,
) -> None:
    """Validate transient draft references against the published graph."""
    await collection_service.get_collection_for_user(collection_id, user_id)
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)
    if objective.active_analysis_version != source_analysis_version:
        raise ResourceConflictException(
            "Source analysis version is not the active published snapshot.",
            data={"code": "source_analysis_stale"},
        )
    source = await experiment_query_service.read_analysis_bundle(
        collection_id, objective_id, source_analysis_version
    )
    selected_ids = set(selection_ids)
    for group_id in comparison_group_ids:
        group = next(
            (item for item in source.groups if item.group_id == group_id), None
        )
        if group is None:
            raise RequestInvalidException(
                f"Finding references an unknown comparison group: {group_id}"
            )
        selected_ids.update(
            item.selection_id for item in group.members if item.role == "included"
        )
    known_ids = {item.selection_id for item in source.selections}
    if not selected_ids or not selected_ids <= known_ids:
        raise RequestInvalidException(
            "Finding references an unknown experiment selection"
        )


__all__ = [
    "FindingAuthoringResult",
    "create_selection_version",
    "validate_selection_references",
]
