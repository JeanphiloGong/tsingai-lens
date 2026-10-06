"""Create Findings from immutable PaperExperiment selections."""

from __future__ import annotations

from dataclasses import dataclass, replace

from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
)
from application.core.objectives.analysis.experiment_query_service import (
    ExperimentQueryService,
)
from application.repositories.objective_repository import (
    OBJECTIVE_ANALYSIS_ABSTENTION_REASONS,
    ObjectiveAnalysis,
    ObjectiveRepository,
)
from application.repositories.transaction import RepositoryTransactionFactory
from application.source.collection_service import CollectionService
from domain.core.finding import Finding


@dataclass(frozen=True)
class FindingAuthoringResult:
    analysis: ObjectiveAnalysis
    finding: Finding | None


class FindingAuthoringService:
    """Publish a new analysis snapshot synthesized from selected experiments."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        objective_repository: ObjectiveRepository,
        experiment_query_service: ExperimentQueryService,
        experiment_analysis_writer: ExperimentAnalysisWriter,
        experiment_analysis_transaction_factory: RepositoryTransactionFactory | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository
        self.experiment_query_service = experiment_query_service
        self.experiment_analysis_writer = experiment_analysis_writer
        self.experiment_analysis_transaction_factory = experiment_analysis_transaction_factory

    async def create_selection_version(
        self,
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
            raise ValueError("Finding limitations exceed the allowed length")
        if abstention_reason is not None:
            if abstention_reason not in OBJECTIVE_ANALYSIS_ABSTENTION_REASONS:
                raise ValueError("unsupported Finding abstention")
            if (
                selection_ids
                or comparison_group_ids
                or parent_finding_id
                or not limitations
            ):
                raise ValueError(
                    "abstention requires an explanation and no experiment selections or parent"
                )
        if self.experiment_analysis_transaction_factory is None:
            raise RuntimeError(
                "Finding authoring requires a shared analysis transaction"
            )
        await self.collection_service.get_collection_for_user(
            collection_id, created_by_user_id
        )
        objective = await self.objective_repository.read_objective(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(f"research objective not found: {collection_id}/{objective_id}")
        if objective.active_analysis_version != source_analysis_version:
            raise ValueError("source analysis version is not the active published snapshot")
        source_analysis = await self.objective_repository.read_analysis(
            collection_id, objective_id, source_analysis_version
        )
        if source_analysis is None or source_analysis.status != "succeeded":
            raise ValueError("source analysis version is not a completed snapshot")
        source = await self.experiment_query_service.read_analysis_bundle(
            collection_id, objective_id, source_analysis_version
        )
        selected_ids = set(selection_ids)
        for group_id in comparison_group_ids:
            group = next(
                (item for item in source.groups if item.group_id == group_id), None
            )
            if group is None:
                raise ValueError(f"Finding references an unknown comparison group: {group_id}")
            selected_ids.update(
                item.selection_id for item in group.members if item.role == "included"
            )
        chosen = tuple(
            item for item in source.selections if item.selection_id in selected_ids
        )
        if abstention_reason is None and (
            not chosen or len(chosen) != len(selected_ids)
        ):
            raise ValueError("Finding references an unknown experiment selection")
        if parent_finding_id is not None:
            parent = next(
                (
                    item
                    for item in source.findings
                    if item.finding_id == parent_finding_id
                ),
                None,
            )
            if parent is None:
                raise ValueError(
                    "parent Finding is not in the source analysis snapshot"
                )
        coverage = await self.objective_repository.list_contributions(
            collection_id, objective_id, source_analysis_version
        )
        _objective, queued = await self.objective_repository.queue_analysis(
            collection_id, objective_id, document_inputs=source_analysis.document_inputs,
            pipeline_version=source_analysis.pipeline_version, model_name=source_analysis.model_name,
            prompt_versions=dict(source_analysis.prompt_versions), origin="human_authored",
            created_by_user_id=created_by_user_id,
            source_analysis_version=source_analysis_version,
        )
        claimed = await self.objective_repository.claim_analysis(
            collection_id, objective_id, queued.analysis_version
        )
        if claimed is None:
            raise ValueError("Finding analysis snapshot could not be claimed")
        try:
            async with self.experiment_analysis_transaction_factory.begin() as transaction:
                result = await self.experiment_analysis_writer.write_selection_finding_revision(
                    collection_id=collection_id,
                    objective=objective,
                    analysis=claimed,
                    revisions=source.revisions,
                    selections=chosen,
                    created_by=created_by_user_id,
                    parent_finding_id=parent_finding_id,
                    limitations=limitations,
                    transaction=transaction,
                )
                await self.objective_repository.publish_experiment_analysis(
                    collection_id,
                    objective_id,
                    claimed.analysis_version,
                    contributions=tuple(
                        replace(item, analysis_version=claimed.analysis_version)
                        for item in coverage
                    ),
                    transaction=transaction,
                    abstention_reason=abstention_reason,
                    abstention_note=(
                        "\n".join(limitations) if abstention_reason else None
                    ),
                )
        except Exception as exc:
            await self.objective_repository.fail_analysis(
                collection_id, objective_id, claimed.analysis_version,
                error_code="authored_finding_publish_failed",
                error_message=str(exc), expected_status="running",
            )
            raise
        mapped = {f"{item.selection_id}:v{claimed.analysis_version}" for item in chosen}
        finding = next((item for item in result.findings if set(item.selection_ids) == mapped), result.findings[0] if result.findings else None)
        analysis = await self.objective_repository.read_analysis(collection_id, objective_id, claimed.analysis_version)
        if analysis is None:
            raise FileNotFoundError("published Finding analysis snapshot not found")
        return FindingAuthoringResult(analysis=analysis, finding=finding)

    async def validate_selection_references(
        self,
        *,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        selection_ids: tuple[str, ...],
        comparison_group_ids: tuple[str, ...] = (),
        user_id: str,
    ) -> None:
        """Validate transient draft references against the published graph."""
        await self.collection_service.get_collection_for_user(collection_id, user_id)
        objective = await self.objective_repository.read_objective(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(f"research objective not found: {collection_id}/{objective_id}")
        if objective.active_analysis_version != source_analysis_version:
            raise ValueError("source analysis version is not the active published snapshot")
        source = await self.experiment_query_service.read_analysis_bundle(
            collection_id, objective_id, source_analysis_version
        )
        selected_ids = set(selection_ids)
        for group_id in comparison_group_ids:
            group = next((item for item in source.groups if item.group_id == group_id), None)
            if group is None:
                raise ValueError(f"Finding references an unknown comparison group: {group_id}")
            selected_ids.update(item.selection_id for item in group.members if item.role == "included")
        known_ids = {item.selection_id for item in source.selections}
        if not selected_ids or not selected_ids <= known_ids:
            raise ValueError("Finding references an unknown experiment selection")


__all__ = ["FindingAuthoringResult", "FindingAuthoringService"]
