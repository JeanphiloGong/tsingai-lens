"""PostgreSQL repository for the Research Objective aggregate."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import (
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveEvidenceComparison,
    ObjectiveEvidenceContext,
    ObjectiveEvidenceResult,
    ObjectiveEvidenceVariable,
    ObjectiveFactSet,
    PaperContribution,
    PaperSourceUnitCoverage,
    PaperStudy,
    PaperStudyDisposition,
    PaperStudyRelationship,
    PaperStudySignal,
    PaperSkim,
    ResearchObjective,
    build_research_objective_id,
)
from domain.pipeline import ExecutionStats
from infra.persistence.postgres.models.build import (
    CollectionActiveBuild,
    CollectionBuild,
)
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisRecord,
    ObjectiveAuthoredCandidateRecord,
    ObjectiveBuild,
    ObjectiveEvidenceRecord,
    ObjectiveFindingContextRecord,
    ObjectiveFindingPaperContributionRecord,
    ObjectiveFindingRecord,
    ObjectiveFindingRelationRecord,
    ObjectivePaperContributionRecord,
    ObjectivePaperSourceUnitCoverage,
    ObjectivePaperSkim,
    ObjectivePaperStudy,
    ObjectivePaperStudyDisposition,
    ObjectivePaperStudyRelationship,
    ObjectivePaperStudySignal,
    ObjectiveResearchRecord,
    objective_build_candidates,
    objective_build_relationship_links,
    objective_document_scope,
    objective_finding_evidence_links,
    objective_finding_relation_evidence_links,
)
from infra.persistence.postgres.models.source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
    SourceTableRow,
)


class PostgresObjectiveRepository:
    backend_name = "postgresql"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        """Replace generated paper studies and Objectives for one pending build."""
        async with self.session_factory.begin() as session:
            await self._require_writable_build(session, collection_id, build_id)
            source_document_ids = await self._source_document_ids(
                session, collection_id, build_id
            )
            await session.execute(
                delete(ObjectiveBuild).where(ObjectiveBuild.build_id == build_id)
            )
            await session.flush()
            session.add(
                ObjectiveBuild(
                    build_id=build_id,
                    collection_id=collection_id,
                    research_objectives_ready=facts.research_objectives_ready,
                )
            )
            for position, skim in enumerate(facts.paper_skims):
                session.add(
                    await self._skim_row(
                        session,
                        collection_id,
                        build_id,
                        source_document_ids,
                        position,
                        skim,
                    )
                )
                await session.flush()
                await self._write_paper_study_rows(
                    session,
                    collection_id=collection_id,
                    build_id=build_id,
                    skim=skim,
                )
            await session.flush()

            now = datetime.now(timezone.utc)
            relationship_index = self._relationship_index(facts.paper_skims)
            for position, objective in enumerate(facts.research_objectives):
                if objective.collection_id != collection_id:
                    raise ValueError("objective belongs to another collection")
                row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective.objective_id),
                )
                if row is None:
                    row = ObjectiveResearchRecord(
                        collection_id=collection_id,
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
                        created_at=objective.created_at or now,
                        updated_at=objective.updated_at or now,
                    )
                    session.add(row)
                    await session.flush()
                else:
                    if self._objective_definition_id(
                        row
                    ) != self._objective_definition_id(objective):
                        raise ValueError(
                            "research objective identity collision: "
                            f"{collection_id}/{objective.objective_id}"
                        )
                    authored = await session.get(
                        ObjectiveAuthoredCandidateRecord,
                        (collection_id, objective.objective_id),
                    )
                    if row.confirmation_status == "candidate" and authored is None:
                        row.question = objective.question
                        row.material_scope = list(objective.material_scope)
                        row.variables = list(objective.variables)
                        row.outcomes = list(objective.outcomes)
                        row.mechanisms = list(objective.mechanisms)
                        row.constraints = list(objective.constraints)
                        row.requested_comparator = objective.requested_comparator
                        row.confidence = objective.confidence
                        row.reason = objective.reason
                        row.updated_at = now
                await session.execute(
                    objective_build_candidates.insert().values(
                        build_id=build_id,
                        collection_id=collection_id,
                        objective_id=objective.objective_id,
                        objective_order=position,
                    )
                )
                await self._replace_document_scope(session, build_id, objective)
                for link_order, relationship_id in enumerate(
                    objective.source_relationship_ids
                ):
                    try:
                        document_id, study_id, _relationship = relationship_index[
                            relationship_id
                        ]
                    except KeyError as exc:
                        raise ValueError(
                            "objective references an unknown paper study relationship"
                        ) from exc
                    await session.execute(
                        objective_build_relationship_links.insert().values(
                            build_id=build_id,
                            collection_id=collection_id,
                            objective_id=objective.objective_id,
                            source_document_id=document_id,
                            study_id=study_id,
                            relationship_id=relationship_id,
                            link_order=link_order,
                        )
                    )
            session.add_all(
                ObjectivePaperStudyDisposition(
                    build_id=build_id,
                    collection_id=collection_id,
                    source_document_id=item.document_id,
                    study_id=item.study_id,
                    relationship_id=item.relationship_id,
                    status=item.status.value,
                    objective_id=item.objective_id,
                    reason=item.reason,
                )
                for item in facts.study_dispositions
            )

    async def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ObjectiveFactSet:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return ObjectiveFactSet()
            marker = await session.get(ObjectiveBuild, resolved_build_id)
            if marker is None or marker.collection_id != collection_id:
                return ObjectiveFactSet()
            scope = await self._scope_by_objective(
                session,
                collection_id,
                build_id=resolved_build_id,
            )
            objective_rows = (
                await session.execute(
                    select(
                        ObjectiveResearchRecord,
                        objective_build_candidates.c.objective_order,
                    )
                    .join(
                        objective_build_candidates,
                        (
                            objective_build_candidates.c.collection_id
                            == ObjectiveResearchRecord.collection_id
                        )
                        & (
                            objective_build_candidates.c.objective_id
                            == ObjectiveResearchRecord.objective_id
                        ),
                    )
                    .where(
                        objective_build_candidates.c.collection_id == collection_id,
                        objective_build_candidates.c.build_id == resolved_build_id,
                    )
                    .order_by(objective_build_candidates.c.objective_order)
                )
            ).all()
            skim_rows = tuple(
                await session.scalars(
                    select(ObjectivePaperSkim)
                    .where(ObjectivePaperSkim.build_id == resolved_build_id)
                    .order_by(ObjectivePaperSkim.skim_order)
                )
            )
            relationships_by_study = await self._relationship_rows_by_study(
                session, resolved_build_id
            )
            studies_by_document = await self._study_rows_by_document(
                session, resolved_build_id, relationships_by_study
            )
            signals_by_document = await self._signal_rows_by_document(
                session, resolved_build_id
            )
            coverage_by_document = await self._coverage_rows_by_document(
                session, resolved_build_id
            )
            relationship_ids_by_objective = await self._relationship_ids_by_objective(
                session, resolved_build_id
            )
            analysis_versions_by_objective = await self._analysis_versions_by_objective(
                session,
                collection_id,
                resolved_build_id,
            )
            return ObjectiveFactSet(
                research_objectives_ready=marker.research_objectives_ready,
                paper_skims=tuple(
                    self._skim_record(
                        row,
                        studies=studies_by_document.get(row.source_document_id, ()),
                        signals=signals_by_document.get(row.source_document_id, ()),
                        coverage=coverage_by_document.get(row.source_document_id, ()),
                    )
                    for row in skim_rows
                ),
                research_objectives=tuple(
                    self._objective_record(
                        row,
                        scope.get(row.objective_id, {}),
                        source_relationship_ids=relationship_ids_by_objective.get(
                            row.objective_id, ()
                        ),
                        rank=int(objective_order) + 1,
                        analysis_versions=analysis_versions_by_objective.get(
                            row.objective_id, (None, None)
                        ),
                    )
                    for row, objective_order in objective_rows
                ),
                study_dispositions=tuple(
                    PaperStudyDisposition.from_mapping(
                        {
                            "document_id": row.source_document_id,
                            "study_id": row.study_id,
                            "relationship_id": row.relationship_id,
                            "status": row.status,
                            "objective_id": row.objective_id,
                            "reason": row.reason,
                        }
                    )
                    for row in await session.scalars(
                        select(ObjectivePaperStudyDisposition)
                        .where(ObjectivePaperStudyDisposition.build_id == resolved_build_id)
                        .order_by(
                            ObjectivePaperStudyDisposition.source_document_id,
                            ObjectivePaperStudyDisposition.study_id,
                            ObjectivePaperStudyDisposition.relationship_id,
                        )
                    )
                ),
            )

    async def list_objectives(self, collection_id: str) -> tuple[ResearchObjective, ...]:
        async with self.session_factory() as session:
            build_id = await self._resolve_read_build(session, collection_id, None)
            generated_rows: list[tuple[ObjectiveResearchRecord, int]] = []
            marker = await session.get(ObjectiveBuild, build_id) if build_id else None
            if (
                build_id is not None
                and marker is not None
                and marker.collection_id == collection_id
                and marker.research_objectives_ready
            ):
                generated_rows = list(
                    (
                        await session.execute(
                            select(
                                ObjectiveResearchRecord,
                                objective_build_candidates.c.objective_order,
                            )
                            .join(
                                objective_build_candidates,
                                (
                                    objective_build_candidates.c.collection_id
                                    == ObjectiveResearchRecord.collection_id
                                )
                                & (
                                    objective_build_candidates.c.objective_id
                                    == ObjectiveResearchRecord.objective_id
                                ),
                            )
                            .where(
                                objective_build_candidates.c.collection_id
                                == collection_id,
                                objective_build_candidates.c.build_id == build_id,
                            )
                            .order_by(objective_build_candidates.c.objective_order)
                        )
                    ).all()
                )
            authored_rows = list(
                await session.scalars(
                    select(ObjectiveAuthoredCandidateRecord)
                    .where(
                        ObjectiveAuthoredCandidateRecord.collection_id == collection_id
                    )
                    .order_by(
                        ObjectiveAuthoredCandidateRecord.created_at,
                        ObjectiveAuthoredCandidateRecord.objective_id,
                    )
                )
            )
            authored_by_id = {row.objective_id: row for row in authored_rows}
            ordered_rows: list[
                tuple[ObjectiveResearchRecord, ObjectiveAuthoredCandidateRecord | None]
            ] = []
            seen: set[str] = set()
            for row, _objective_order in generated_rows:
                ordered_rows.append((row, authored_by_id.get(row.objective_id)))
                seen.add(row.objective_id)
            for authored in authored_rows:
                if authored.objective_id in seen:
                    continue
                row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, authored.objective_id),
                )
                if row is not None:
                    ordered_rows.append((row, authored))

            scopes: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {}
            relationships: dict[str, dict[str, tuple[str, ...]]] = {}
            versions: dict[str, dict[str, tuple[int | None, int | None]]] = {}
            records: list[ResearchObjective] = []
            for position, (row, authored) in enumerate(ordered_rows, start=1):
                source_build_id = authored.source_build_id if authored else build_id
                if source_build_id is None:
                    continue
                scopes.setdefault(
                    source_build_id,
                    await self._scope_by_objective(
                        session,
                        collection_id,
                        build_id=source_build_id,
                    ),
                )
                relationships.setdefault(
                    source_build_id,
                    await self._relationship_ids_by_objective(session, source_build_id),
                )
                versions.setdefault(
                    source_build_id,
                    await self._analysis_versions_by_objective(
                        session,
                        collection_id,
                        source_build_id,
                    ),
                )
                records.append(
                    self._objective_record(
                        row,
                        scopes[source_build_id].get(row.objective_id, {}),
                        source_relationship_ids=(
                            ()
                            if authored is not None
                            else relationships[source_build_id].get(row.objective_id, ())
                        ),
                        rank=position,
                        analysis_versions=versions[source_build_id].get(
                            row.objective_id, (None, None)
                        ),
                        authored=authored,
                    )
                )
            return tuple(records)

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective:
        if objective.origin != "chat_assisted":
            raise ValueError("authored candidate must have chat_assisted origin")
        if objective.created_by_user_id != created_by_user_id or (
            objective.created_by_tool_call_id != created_by_tool_call_id
        ):
            raise ValueError("authored candidate provenance does not match the request")
        async with self.session_factory.begin() as session:
            existing_call = await session.scalar(
                select(ObjectiveAuthoredCandidateRecord).where(
                    ObjectiveAuthoredCandidateRecord.created_by_tool_call_id
                    == created_by_tool_call_id
                )
            )
            if existing_call is not None:
                if (
                    existing_call.collection_id != objective.collection_id
                    or existing_call.objective_id != objective.objective_id
                    or existing_call.created_by_user_id != created_by_user_id
                ):
                    raise ValueError(
                        "authored candidate tool call already created a different objective"
                    )
                row = await self._locked_objective(
                    session,
                    objective.collection_id,
                    objective.objective_id,
                )
                return await self._authored_objective_record(
                    session,
                    row,
                    existing_call,
                )

            build_id = await self._resolve_read_build(
                session,
                objective.collection_id,
                None,
            )
            marker = await session.get(ObjectiveBuild, build_id) if build_id else None
            if (
                build_id is None
                or marker is None
                or marker.collection_id != objective.collection_id
                or not marker.research_objectives_ready
            ):
                raise FileNotFoundError(
                    f"research objectives not ready: {objective.collection_id}"
                )
            requested_document_ids = set(objective.seed_document_ids) | set(
                objective.excluded_document_ids
            )
            available_document_ids = set(
                await session.scalars(
                    select(
                        SourceDocument.source_document_id,
                    )
                    .where(
                        SourceDocument.collection_id == objective.collection_id,
                        SourceDocument.build_id == build_id,
                        SourceDocument.source_document_id.in_(requested_document_ids),
                    )
                )
            )
            missing = requested_document_ids - available_document_ids
            if missing:
                raise FileNotFoundError(
                    "authored candidate Source document not found: "
                    + ", ".join(sorted(missing))
                )

            row = await session.get(
                ObjectiveResearchRecord,
                (objective.collection_id, objective.objective_id),
            )
            now = datetime.now(timezone.utc)
            if row is None:
                row = ObjectiveResearchRecord(
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
                    confirmation_status="candidate",
                    active_analysis_version=None,
                    published_analysis_version=None,
                    created_at=objective.created_at or now,
                    updated_at=objective.updated_at or now,
                )
                session.add(row)
                await session.flush()
            elif self._objective_definition_id(row) != self._objective_definition_id(
                objective
            ):
                raise ValueError(
                    "research objective identity collision: "
                    f"{objective.collection_id}/{objective.objective_id}"
                )

            existing_authored = await session.get(
                ObjectiveAuthoredCandidateRecord,
                (objective.collection_id, objective.objective_id),
            )
            if existing_authored is None:
                existing_authored = ObjectiveAuthoredCandidateRecord(
                    collection_id=objective.collection_id,
                    objective_id=objective.objective_id,
                    source_build_id=build_id,
                    origin="chat_assisted",
                    seed_document_ids=list(objective.seed_document_ids),
                    excluded_document_ids=list(objective.excluded_document_ids),
                    created_by_user_id=created_by_user_id,
                    created_by_tool_call_id=created_by_tool_call_id,
                    created_at=now,
                )
                session.add(existing_authored)
                await session.flush()
            await session.refresh(row)
            await session.refresh(existing_authored)
            return await self._authored_objective_record(session, row, existing_authored)

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        async with self.session_factory() as session:
            link = await self._objective_build_link(
                session,
                collection_id,
                objective_id,
            )
            if link is None:
                return None
            row = await session.get(ObjectiveResearchRecord, (collection_id, objective_id))
            if row is None:
                return None
            source_relationship_ids, rank, build_id = link
            authored = await self._authored_candidate(
                session,
                collection_id,
                objective_id,
            )
            scope = await self._objective_scope(
                session,
                collection_id,
                objective_id,
                build_id=build_id,
                authored=authored,
            )
            return self._objective_record(
                row,
                scope,
                source_relationship_ids=source_relationship_ids,
                rank=rank,
                analysis_versions=(
                    await self._analysis_versions_by_objective(
                        session,
                        collection_id,
                        build_id,
                    )
                ).get(objective_id, (None, None)),
                authored=authored,
            )

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        async with self.session_factory.begin() as session:
            link = await self._require_objective_build_link(
                session,
                collection_id,
                objective_id,
            )
            source_relationship_ids, rank, source_build_id = link
            row = await self._locked_objective(session, collection_id, objective_id)
            authored = await self._authored_candidate(
                session,
                collection_id,
                objective_id,
            )
            now = datetime.now(timezone.utc)
            if row.confirmation_status == "candidate":
                row.confirmation_status = "confirmed"
                row.updated_at = now
            existing = await session.scalar(
                select(ObjectiveAnalysisRecord).where(
                    ObjectiveAnalysisRecord.collection_id == collection_id,
                    ObjectiveAnalysisRecord.objective_id == objective_id,
                    ObjectiveAnalysisRecord.source_build_id == source_build_id,
                    ObjectiveAnalysisRecord.status.in_(("queued", "running")),
                )
            )
            if existing is not None:
                scope = await self._objective_scope(
                    session,
                    collection_id,
                    objective_id,
                    build_id=source_build_id,
                    authored=authored,
                )
                return self._objective_record(
                    row,
                    scope,
                    source_relationship_ids=source_relationship_ids,
                    rank=rank,
                    analysis_versions=(
                        await self._analysis_versions_by_objective(
                            session,
                            collection_id,
                            source_build_id,
                        )
                    ).get(objective_id, (None, None)),
                    authored=authored,
                ), self._analysis_record(existing)
            next_version = (
                await session.scalar(
                    select(func.max(ObjectiveAnalysisRecord.analysis_version)).where(
                        ObjectiveAnalysisRecord.collection_id == collection_id,
                        ObjectiveAnalysisRecord.objective_id == objective_id,
                    )
                )
                or 0
            ) + 1
            scope = await self._objective_scope(
                session,
                collection_id,
                objective_id,
                build_id=source_build_id,
                authored=authored,
            )
            total_documents = int(
                await session.scalar(
                    select(func.count())
                    .select_from(SourceDocument)
                    .where(
                        SourceDocument.collection_id == collection_id,
                        SourceDocument.build_id == source_build_id,
                    )
                )
                or 0
            )
            if total_documents == 0:
                total_documents = len(scope.get("seed", ()))
            analysis_row = ObjectiveAnalysisRecord(
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=next_version,
                source_build_id=source_build_id,
                pipeline_version=pipeline_version,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                stats=ExecutionStats().to_record(),
                diagnostics=[],
                status="queued",
                phase="queued",
                processed_document_count=0,
                total_document_count=total_documents,
                current_document_id=None,
                progress_message="Objective analysis is queued.",
                error_code=None,
                error_message=None,
                created_at=now,
                started_at=None,
                completed_at=None,
            )
            session.add(analysis_row)
            row.active_analysis_version = next_version
            row.updated_at = now
            return self._objective_record(
                row,
                scope,
                source_relationship_ids=source_relationship_ids,
                rank=rank,
                analysis_versions=(
                    next_version,
                    (
                        await self._analysis_versions_by_objective(
                            session,
                            collection_id,
                            source_build_id,
                        )
                    ).get(objective_id, (None, None))[1],
                ),
                authored=authored,
            ), self._analysis_record(analysis_row)

    async def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            if row.status != "queued":
                return None
            now = datetime.now(timezone.utc)
            row.status = "running"
            row.phase = "started"
            row.started_at = now
            row.error_code = None
            row.error_message = None
            row.progress_message = "Objective analysis has started."
            return self._analysis_record(row)

    async def update_analysis_progress(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        phase: str,
        processed_document_count: int,
        total_document_count: int,
        current_document_id: str | None,
        progress_message: str | None,
    ) -> ObjectiveAnalysis:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            updated = self._analysis_record(row).update_progress(
                phase=phase,
                processed_document_count=processed_document_count,
                total_document_count=total_document_count,
                current_document_id=current_document_id,
                progress_message=progress_message,
            )
            self._apply_analysis(row, updated)
            return updated

    async def update_analysis_execution_stats(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        stats: ExecutionStats,
        model_name: str | None,
        prompt_versions: dict[str, str],
        diagnostics: tuple[dict[str, Any], ...],
    ) -> ObjectiveAnalysis:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            updated = replace(
                self._analysis_record(row),
                stats=stats,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                diagnostics=diagnostics,
            )
            self._apply_analysis(row, updated)
            return updated

    async def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
        expected_status: str | None = None,
    ) -> ObjectiveAnalysis:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            analysis = self._analysis_record(row)
            if expected_status is not None and analysis.status != expected_status:
                return analysis
            failed = analysis.fail(
                error_code=error_code,
                error_message=error_message,
                completed_at=datetime.now(timezone.utc),
            )
            self._apply_analysis(row, failed)
            return failed

    async def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        async with self.session_factory.begin() as session:
            objective_row = await self._locked_objective(session, collection_id, objective_id)
            analysis_row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            if analysis_row.status != "running":
                raise ValueError("only running objective analysis can be published")
            expected_key = (collection_id, objective_id, analysis_version)
            self._validate_artifact_keys(
                expected_key,
                contributions,
                evidence_records,
                findings,
            )
            contribution_documents = {item.document_id for item in contributions}
            if {item.document_id for item in evidence_records} - contribution_documents:
                raise ValueError("objective evidence lacks owning paper contribution")
            for evidence in evidence_records:
                await self._require_source_locator(
                    session,
                    collection_id,
                    analysis_row.source_build_id,
                    evidence,
                )
            for finding in findings:
                finding.validate_sources(evidence_records, contributions)

            await self._delete_analysis_artifacts(
                session, collection_id, objective_id, analysis_version
            )
            session.add_all(
                self._contribution_row(analysis_row.source_build_id, item)
                for item in contributions
            )
            await session.flush()
            session.add_all(
                self._evidence_row(position, item)
                for position, item in enumerate(evidence_records)
            )
            await session.flush()
            for finding in findings:
                await self._write_finding(session, finding)
            succeeded = self._analysis_record(analysis_row).succeed(
                completed_at=datetime.now(timezone.utc)
            )
            self._apply_analysis(analysis_row, succeeded)
            source_relationship_ids, rank, _build_id = await self._require_objective_build_link(
                session,
                collection_id,
                objective_id,
                build_id=analysis_row.source_build_id,
            )
            authored = await self._authored_candidate(
                session,
                collection_id,
                objective_id,
            )
            objective = self._objective_record(
                objective_row,
                await self._objective_scope(
                    session,
                    collection_id,
                    objective_id,
                    build_id=analysis_row.source_build_id,
                    authored=authored,
                ),
                source_relationship_ids=source_relationship_ids,
                rank=rank,
                analysis_versions=(analysis_version, analysis_version),
                authored=authored,
            ).publish_analysis(succeeded)
            objective_row.published_analysis_version = analysis_version
            objective_row.updated_at = datetime.now(timezone.utc)
            return objective, succeeded

    async def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory() as session:
            if analysis_version is None:
                link = await self._objective_build_link(
                    session,
                    collection_id,
                    objective_id,
                )
                if link is None:
                    return None
                _relationship_ids, _rank, build_id = link
                analysis_version = (
                    await self._analysis_versions_by_objective(
                        session,
                        collection_id,
                        build_id,
                    )
                ).get(objective_id, (None, None))[0]
                if analysis_version is None:
                    return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            return self._analysis_record(row) if row is not None else None

    async def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory() as session:
            link = await self._objective_build_link(
                session,
                collection_id,
                objective_id,
            )
            if link is None:
                return None
            _relationship_ids, _rank, build_id = link
            published_analysis_version = (
                await self._analysis_versions_by_objective(
                    session,
                    collection_id,
                    build_id,
                )
            ).get(objective_id, (None, None))[1]
            if published_analysis_version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (
                    collection_id,
                    objective_id,
                    published_analysis_version,
                ),
            )
            return self._analysis_record(row) if row is not None else None

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(ObjectivePaperContributionRecord)
                .where(
                    ObjectivePaperContributionRecord.collection_id == collection_id,
                    ObjectivePaperContributionRecord.objective_id == objective_id,
                    ObjectivePaperContributionRecord.analysis_version
                    == analysis_version,
                )
                .order_by(ObjectivePaperContributionRecord.source_document_id)
            )
            return tuple(self._contribution_record(row) for row in rows)

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]:
        async with self.session_factory() as session:
            total = (
                await session.scalar(
                    select(func.count())
                    .select_from(ObjectiveFindingRecord)
                    .where(
                        ObjectiveFindingRecord.collection_id == collection_id,
                        ObjectiveFindingRecord.objective_id == objective_id,
                        ObjectiveFindingRecord.analysis_version == analysis_version,
                    )
                )
                or 0
            )
            rows = tuple(
                await session.scalars(
                    select(ObjectiveFindingRecord)
                    .where(
                        ObjectiveFindingRecord.collection_id == collection_id,
                        ObjectiveFindingRecord.objective_id == objective_id,
                        ObjectiveFindingRecord.analysis_version == analysis_version,
                    )
                    .order_by(
                        ObjectiveFindingRecord.display_rank,
                        ObjectiveFindingRecord.finding_id,
                    )
                    .offset(max(0, offset))
                    .limit(max(1, min(limit, 200)))
                )
            )
            return tuple(
                [await self._finding_record(session, row) for row in rows]
            ), total

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveFindingRecord,
                (collection_id, objective_id, analysis_version, finding_id),
            )
            return await self._finding_record(session, row) if row is not None else None

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[ObjectiveEvidence, ...], int]:
        async with self.session_factory() as session:
            evidence_ids: tuple[str, ...] | None = None
            if finding_id is not None:
                evidence_ids = tuple(
                    await session.scalars(
                        select(objective_finding_evidence_links.c.evidence_id)
                        .where(
                            objective_finding_evidence_links.c.collection_id
                            == collection_id,
                            objective_finding_evidence_links.c.objective_id
                            == objective_id,
                            objective_finding_evidence_links.c.analysis_version
                            == analysis_version,
                            objective_finding_evidence_links.c.finding_id == finding_id,
                        )
                        .order_by(
                            objective_finding_evidence_links.c.link_role,
                            objective_finding_evidence_links.c.position,
                        )
                    )
                )
                if not evidence_ids:
                    return (), 0
            filters = (
                ObjectiveEvidenceRecord.collection_id == collection_id,
                ObjectiveEvidenceRecord.objective_id == objective_id,
                ObjectiveEvidenceRecord.analysis_version == analysis_version,
            )
            if evidence_ids is not None:
                filters = (
                    *filters,
                    ObjectiveEvidenceRecord.evidence_id.in_(evidence_ids),
                )
            total = (
                await session.scalar(
                    select(func.count())
                    .select_from(ObjectiveEvidenceRecord)
                    .where(*filters)
                )
                or 0
            )
            rows = await session.scalars(
                select(ObjectiveEvidenceRecord)
                .where(*filters)
                .order_by(
                    ObjectiveEvidenceRecord.evidence_order,
                    ObjectiveEvidenceRecord.evidence_id,
                )
                .offset(max(0, offset))
                .limit(max(1, min(limit, 500)))
            )
            return tuple(self._evidence_record(row) for row in rows), total

    @staticmethod
    def _validate_artifact_keys(
        expected_key: tuple[str, str, int],
        contributions: Iterable[PaperContribution],
        evidence_records: Iterable[ObjectiveEvidence],
        findings: Iterable[Finding],
    ) -> None:
        for item in (*tuple(contributions), *tuple(evidence_records), *tuple(findings)):
            if (
                item.collection_id,
                item.objective_id,
                item.analysis_version,
            ) != expected_key:
                raise ValueError(
                    "objective analysis artifact has cross-version identity"
                )

    @staticmethod
    def _apply_analysis(
        row: ObjectiveAnalysisRecord, analysis: ObjectiveAnalysis
    ) -> None:
        row.model_name = analysis.model_name
        row.prompt_versions = dict(analysis.prompt_versions)
        row.stats = analysis.stats.to_record()
        row.diagnostics = [dict(item) for item in analysis.diagnostics]
        row.status = analysis.status
        row.phase = analysis.phase
        row.processed_document_count = analysis.processed_document_count
        row.total_document_count = analysis.total_document_count
        row.current_document_id = analysis.current_document_id
        row.progress_message = analysis.progress_message
        row.error_code = analysis.error_code
        row.error_message = analysis.error_message
        row.started_at = analysis.started_at
        row.completed_at = analysis.completed_at

    @staticmethod
    async def _delete_analysis_artifacts(
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> None:
        for model in (
            ObjectiveFindingRecord,
            ObjectiveEvidenceRecord,
            ObjectivePaperContributionRecord,
        ):
            await session.execute(
                delete(model).where(
                    model.collection_id == collection_id,
                    model.objective_id == objective_id,
                    model.analysis_version == analysis_version,
                )
            )

    @staticmethod
    def _contribution_row(
        source_build_id: str,
        item: PaperContribution,
    ) -> ObjectivePaperContributionRecord:
        return ObjectivePaperContributionRecord(
            collection_id=item.collection_id,
            objective_id=item.objective_id,
            analysis_version=item.analysis_version,
            source_document_id=item.document_id,
            source_build_id=source_build_id,
            analysis_status=item.analysis_status,
            relevance=item.relevance,
            paper_role=item.paper_role,
            contribution_summary=item.contribution_summary,
            material_match=list(item.material_match),
            changed_variables=list(item.changed_variables),
            measured_property_scope=list(item.measured_property_scope),
            test_environment_scope=list(item.test_environment_scope),
            exclusion_reason=item.exclusion_reason,
            warnings=list(item.warnings),
            confidence=item.confidence,
            evidence_disposition=item.evidence_disposition,
            routed_source_count=item.routed_source_count,
            extracted_source_count=item.extracted_source_count,
            comparable_evidence_count=item.comparable_evidence_count,
            failed_source_count=item.failed_source_count,
            evidence_disposition_reason=item.evidence_disposition_reason,
        )

    @staticmethod
    def _evidence_row(
        position: int,
        item: ObjectiveEvidence,
    ) -> ObjectiveEvidenceRecord:
        return ObjectiveEvidenceRecord(
            collection_id=item.collection_id,
            objective_id=item.objective_id,
            analysis_version=item.analysis_version,
            evidence_id=item.evidence_id,
            source_document_id=item.document_id,
            evidence_order=position,
            source_kind=item.source_kind,
            source_ref=item.source_ref,
            source_excerpt=item.source_excerpt,
            page_numbers=list(item.page_numbers),
            related_source_refs=[dict(value) for value in item.related_source_refs],
            evidence_role=item.evidence_role,
            selection_status=item.selection_status,
            selection_reason=item.selection_reason,
            changed_variables=[
                variable.to_record() for variable in item.changed_variables
            ],
            comparison=item.comparison.to_record() if item.comparison else None,
            reported_result=(
                item.reported_result.to_record() if item.reported_result else None
            ),
            attribution_scope=item.attribution_scope,
            scientific_context=item.scientific_context.to_record(),
            anchor_ids=list(item.anchor_ids),
            resolution_status=item.resolution_status,
            failure_reason=item.failure_reason,
            confidence=item.confidence,
        )

    @staticmethod
    def _contribution_record(
        row: ObjectivePaperContributionRecord,
    ) -> PaperContribution:
        return PaperContribution.from_mapping(
            {
                "collection_id": row.collection_id,
                "objective_id": row.objective_id,
                "analysis_version": row.analysis_version,
                "document_id": row.source_document_id,
                "analysis_status": row.analysis_status,
                "relevance": row.relevance,
                "paper_role": row.paper_role,
                "contribution_summary": row.contribution_summary,
                "material_match": row.material_match,
                "changed_variables": row.changed_variables,
                "measured_property_scope": row.measured_property_scope,
                "test_environment_scope": row.test_environment_scope,
                "exclusion_reason": row.exclusion_reason,
                "warnings": row.warnings,
                "confidence": row.confidence,
                "evidence_disposition": row.evidence_disposition,
                "routed_source_count": row.routed_source_count,
                "extracted_source_count": row.extracted_source_count,
                "comparable_evidence_count": row.comparable_evidence_count,
                "failed_source_count": row.failed_source_count,
                "evidence_disposition_reason": row.evidence_disposition_reason,
            }
        )

    async def _write_finding(self, session: AsyncSession, finding: Finding) -> None:
        session.add(
            ObjectiveFindingRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                statement=finding.statement,
                factors=list(finding.factors),
                outcome=finding.outcome,
                direction=finding.direction,
                assertion_strength=finding.assertion_strength,
                attribution_scope=finding.attribution_scope,
                synthesis_status=finding.synthesis_status,
                certainty=finding.certainty,
                display_rank=finding.display_rank,
            )
        )
        await session.flush()
        session.add_all(
            ObjectiveFindingRelationRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                relation_order=position,
                source_term=relation.source_term,
                relation_type=relation.relation_type,
                target_term=relation.target_term,
                direction=relation.direction,
                assertion_strength=relation.assertion_strength,
            )
            for position, relation in enumerate(finding.mechanisms)
        )
        session.add(
            ObjectiveFindingContextRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                scientific_context=finding.scientific_context.to_record(),
                limitations=list(finding.limitations),
            )
        )
        session.add_all(
            ObjectiveFindingPaperContributionRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                source_document_id=contribution.document_id,
                paper_order=position,
            )
            for position, contribution in enumerate(finding.paper_contributions)
        )
        await session.flush()
        for link_role, evidence_ids in (
            ("supporting", finding.supporting_evidence_ids),
            ("contradicting", finding.contradicting_evidence_ids),
            ("context", finding.context_evidence_ids),
            ("boundary", finding.condition_boundary_evidence_ids),
        ):
            rows = [
                {
                    "collection_id": finding.collection_id,
                    "objective_id": finding.objective_id,
                    "analysis_version": finding.analysis_version,
                    "finding_id": finding.finding_id,
                    "evidence_id": evidence_id,
                    "link_role": link_role,
                    "position": position,
                }
                for position, evidence_id in enumerate(evidence_ids)
            ]
            if rows:
                await session.execute(objective_finding_evidence_links.insert(), rows)
        for relation_order, relation in enumerate(finding.mechanisms):
            rows = [
                {
                    "collection_id": finding.collection_id,
                    "objective_id": finding.objective_id,
                    "analysis_version": finding.analysis_version,
                    "finding_id": finding.finding_id,
                    "relation_order": relation_order,
                    "evidence_id": evidence_id,
                    "position": position,
                }
                for position, evidence_id in enumerate(relation.supporting_evidence_ids)
            ]
            if rows:
                await session.execute(
                    objective_finding_relation_evidence_links.insert(), rows
                )

    async def _finding_record(
        self,
        session: AsyncSession,
        row: ObjectiveFindingRecord,
    ) -> Finding:
        key_filters = (
            row.collection_id,
            row.objective_id,
            row.analysis_version,
            row.finding_id,
        )
        relation_rows = tuple(
            await session.scalars(
                select(ObjectiveFindingRelationRecord)
                .where(
                    ObjectiveFindingRelationRecord.collection_id == key_filters[0],
                    ObjectiveFindingRelationRecord.objective_id == key_filters[1],
                    ObjectiveFindingRelationRecord.analysis_version == key_filters[2],
                    ObjectiveFindingRelationRecord.finding_id == key_filters[3],
                )
                .order_by(ObjectiveFindingRelationRecord.relation_order)
            )
        )
        relation_links: dict[int, list[str]] = defaultdict(list)
        for link in (
            await session.execute(
                select(objective_finding_relation_evidence_links)
                .where(
                    objective_finding_relation_evidence_links.c.collection_id
                    == key_filters[0],
                    objective_finding_relation_evidence_links.c.objective_id
                    == key_filters[1],
                    objective_finding_relation_evidence_links.c.analysis_version
                    == key_filters[2],
                    objective_finding_relation_evidence_links.c.finding_id
                    == key_filters[3],
                )
                .order_by(
                    objective_finding_relation_evidence_links.c.relation_order,
                    objective_finding_relation_evidence_links.c.position,
                )
            )
        ).mappings():
            relation_links[int(link["relation_order"])].append(str(link["evidence_id"]))
        evidence_links: dict[str, list[str]] = defaultdict(list)
        for link in (
            await session.execute(
                select(objective_finding_evidence_links)
                .where(
                    objective_finding_evidence_links.c.collection_id
                    == key_filters[0],
                    objective_finding_evidence_links.c.objective_id == key_filters[1],
                    objective_finding_evidence_links.c.analysis_version
                    == key_filters[2],
                    objective_finding_evidence_links.c.finding_id == key_filters[3],
                )
                .order_by(
                    objective_finding_evidence_links.c.link_role,
                    objective_finding_evidence_links.c.position,
                )
            )
        ).mappings():
            evidence_links[str(link["link_role"])].append(str(link["evidence_id"]))
        context_row = await session.get(ObjectiveFindingContextRecord, key_filters)
        paper_rows = tuple(
            await session.scalars(
                select(ObjectiveFindingPaperContributionRecord)
                .where(
                    ObjectiveFindingPaperContributionRecord.collection_id
                    == key_filters[0],
                    ObjectiveFindingPaperContributionRecord.objective_id
                    == key_filters[1],
                    ObjectiveFindingPaperContributionRecord.analysis_version
                    == key_filters[2],
                    ObjectiveFindingPaperContributionRecord.finding_id
                    == key_filters[3],
                )
                .order_by(ObjectiveFindingPaperContributionRecord.paper_order)
            )
        )
        if context_row is None or not paper_rows:
            raise RuntimeError(f"incomplete persisted finding: {row.finding_id}")
        linked_evidence_ids = {
            evidence_id
            for evidence_ids in evidence_links.values()
            for evidence_id in evidence_ids
        }
        evidence_documents: dict[str, str] = {}
        for evidence_id in linked_evidence_ids:
            evidence_row = await session.get(
                ObjectiveEvidenceRecord,
                (*key_filters[:3], evidence_id),
            )
            if evidence_row is None:
                raise RuntimeError(
                    f"persisted Finding references missing Evidence: {evidence_id}"
                )
            evidence_documents[evidence_id] = evidence_row.source_document_id

        def evidence_for_document(link_role: str, document_id: str) -> tuple[str, ...]:
            return tuple(
                evidence_id
                for evidence_id in evidence_links.get(link_role, ())
                if evidence_documents[evidence_id] == document_id
            )

        return Finding(
            collection_id=row.collection_id,
            objective_id=row.objective_id,
            analysis_version=row.analysis_version,
            finding_id=row.finding_id,
            statement=row.statement,
            factors=tuple(row.factors),
            outcome=row.outcome,
            direction=row.direction,
            assertion_strength=row.assertion_strength,
            attribution_scope=row.attribution_scope,
            synthesis_status=row.synthesis_status,
            certainty=row.certainty,
            display_rank=row.display_rank,
            mechanisms=tuple(
                FindingMechanismRelation(
                    source_term=relation.source_term,
                    relation_type=relation.relation_type,
                    target_term=relation.target_term,
                    direction=relation.direction,
                    assertion_strength=relation.assertion_strength,
                    supporting_evidence_ids=tuple(
                        relation_links.get(relation.relation_order, ())
                    ),
                )
                for relation in relation_rows
            ),
            scientific_context=ObjectiveEvidenceContext.from_mapping(
                context_row.scientific_context
            ),
            limitations=tuple(context_row.limitations),
            paper_contributions=tuple(
                [
                    FindingPaperContribution(
                        document_id=paper_row.source_document_id,
                        analysis_status=await self._paper_contribution_status(
                            session,
                            key_filters[:3],
                            paper_row.source_document_id,
                        ),
                        supporting_evidence_ids=evidence_for_document(
                            "supporting", paper_row.source_document_id
                        ),
                        contradicting_evidence_ids=evidence_for_document(
                            "contradicting", paper_row.source_document_id
                        ),
                        context_evidence_ids=evidence_for_document(
                            "context", paper_row.source_document_id
                        ),
                        condition_boundary_evidence_ids=evidence_for_document(
                            "boundary", paper_row.source_document_id
                        ),
                    )
                    for paper_row in paper_rows
                ]
            ),
        )

    @staticmethod
    async def _paper_contribution_status(
        session: AsyncSession,
        analysis_key: tuple[str, str, int],
        document_id: str,
    ) -> str:
        row = await session.get(
            ObjectivePaperContributionRecord,
            (*analysis_key, document_id),
        )
        if row is None:
            raise RuntimeError(
                f"persisted Finding references missing PaperContribution: {document_id}"
            )
        return row.analysis_status

    @staticmethod
    def _evidence_record(row: ObjectiveEvidenceRecord) -> ObjectiveEvidence:
        return ObjectiveEvidence(
            collection_id=row.collection_id,
            objective_id=row.objective_id,
            analysis_version=row.analysis_version,
            evidence_id=row.evidence_id,
            document_id=row.source_document_id,
            source_kind=row.source_kind,
            source_ref=row.source_ref,
            source_excerpt=row.source_excerpt,
            page_numbers=tuple(row.page_numbers),
            related_source_refs=tuple(dict(value) for value in row.related_source_refs),
            evidence_role=row.evidence_role,
            selection_status=row.selection_status,
            selection_reason=row.selection_reason,
            changed_variables=tuple(
                ObjectiveEvidenceVariable.from_mapping(value)
                for value in row.changed_variables
            ),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(row.comparison)
                if row.comparison is not None
                else None
            ),
            reported_result=(
                ObjectiveEvidenceResult.from_mapping(row.reported_result)
                if row.reported_result is not None
                else None
            ),
            attribution_scope=row.attribution_scope,
            scientific_context=ObjectiveEvidenceContext.from_mapping(
                row.scientific_context
            ),
            anchor_ids=tuple(row.anchor_ids),
            resolution_status=row.resolution_status,
            failure_reason=row.failure_reason,
            confidence=row.confidence,
        )

    @staticmethod
    def _analysis_record(row: ObjectiveAnalysisRecord) -> ObjectiveAnalysis:
        return ObjectiveAnalysis(
            collection_id=row.collection_id,
            objective_id=row.objective_id,
            analysis_version=row.analysis_version,
            source_build_id=row.source_build_id,
            pipeline_version=row.pipeline_version,
            model_name=row.model_name,
            prompt_versions=dict(row.prompt_versions),
            stats=ExecutionStats.from_mapping(row.stats),
            diagnostics=tuple(dict(item) for item in row.diagnostics),
            status=row.status,
            phase=row.phase,
            processed_document_count=row.processed_document_count,
            total_document_count=row.total_document_count,
            current_document_id=row.current_document_id,
            progress_message=row.progress_message,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    def _objective_definition_id(
        objective: ObjectiveResearchRecord | ResearchObjective,
    ) -> str:
        return build_research_objective_id(
            question=objective.question,
            material_scope=tuple(objective.material_scope),
            variables=tuple(objective.variables),
            outcomes=tuple(objective.outcomes),
            mechanisms=tuple(objective.mechanisms),
            constraints=tuple(objective.constraints),
            requested_comparator=objective.requested_comparator,
        )

    @staticmethod
    def _objective_record(
        row: ObjectiveResearchRecord,
        scope: dict[str, tuple[str, ...]],
        *,
        source_relationship_ids: tuple[str, ...] = (),
        rank: int | None = None,
        analysis_versions: tuple[int | None, int | None],
        authored: ObjectiveAuthoredCandidateRecord | None = None,
    ) -> ResearchObjective:
        active_analysis_version, published_analysis_version = analysis_versions
        seed_document_ids = (
            tuple(authored.seed_document_ids)
            if authored is not None
            else tuple(scope.get("seed", ()))
        )
        excluded_document_ids = (
            tuple(authored.excluded_document_ids)
            if authored is not None
            else tuple(scope.get("excluded", ()))
        )
        return ResearchObjective(
            collection_id=row.collection_id,
            objective_id=row.objective_id,
            question=row.question,
            material_scope=tuple(row.material_scope),
            variables=tuple(row.variables),
            outcomes=tuple(row.outcomes),
            mechanisms=tuple(row.mechanisms),
            constraints=tuple(row.constraints),
            requested_comparator=row.requested_comparator,
            seed_document_ids=seed_document_ids,
            excluded_document_ids=excluded_document_ids,
            confidence=row.confidence,
            reason=row.reason,
            source_relationship_ids=source_relationship_ids,
            rank=rank,
            confirmation_status=row.confirmation_status,
            active_analysis_version=active_analysis_version,
            published_analysis_version=published_analysis_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            origin=authored.origin if authored is not None else "system_discovered",
            source_build_id=(
                authored.source_build_id if authored is not None else None
            ),
            created_by_user_id=(
                authored.created_by_user_id if authored is not None else None
            ),
            created_by_tool_call_id=(
                authored.created_by_tool_call_id if authored is not None else None
            ),
        )

    @classmethod
    async def _authored_objective_record(
        cls,
        session: AsyncSession,
        row: ObjectiveResearchRecord,
        authored: ObjectiveAuthoredCandidateRecord,
    ) -> ResearchObjective:
        return cls._objective_record(
            row,
            {},
            rank=await cls._objective_rank(
                session,
                authored.collection_id,
                authored.objective_id,
            ),
            analysis_versions=(
                await cls._analysis_versions_by_objective(
                    session,
                    authored.collection_id,
                    authored.source_build_id,
                )
            ).get(authored.objective_id, (None, None)),
            authored=authored,
        )

    @staticmethod
    def _skim_record(
        row: ObjectivePaperSkim,
        *,
        studies: tuple[PaperStudy, ...],
        signals: tuple[PaperStudySignal, ...],
        coverage: tuple[PaperSourceUnitCoverage, ...],
    ) -> PaperSkim:
        return PaperSkim.from_mapping(
            {
                "document_id": row.source_document_id,
                "doc_role": row.doc_role,
                "studies": [study.to_record() for study in studies],
                "unresolved_signals": [signal.to_record() for signal in signals],
                "source_unit_coverage": [item.to_record() for item in coverage],
                "evidence_density": row.evidence_density,
                "confidence": row.confidence,
                "warnings": row.warnings,
                "map_status": row.map_status,
                "map_limitations": row.map_limitations,
                "review_synthesis": row.review_synthesis,
            }
        )

    @classmethod
    async def _skim_row(
        cls,
        session: AsyncSession,
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        skim: PaperSkim,
    ) -> ObjectivePaperSkim:
        cls._require_source_document(
            source_document_ids, collection_id, skim.document_id
        )
        await cls._require_paper_skim_source_refs(
            session,
            collection_id,
            build_id,
            skim,
        )
        return ObjectivePaperSkim(
            build_id=build_id,
            source_document_id=skim.document_id,
            collection_id=collection_id,
            skim_order=position,
            doc_role=skim.doc_role,
            evidence_density=skim.evidence_density,
            confidence=skim.confidence,
            warnings=list(skim.warnings),
            map_status=skim.map_status,
            map_limitations=list(skim.map_limitations),
            review_synthesis=skim.review_synthesis.to_record(),
        )

    @staticmethod
    async def _require_paper_skim_source_refs(
        session: AsyncSession,
        collection_id: str,
        build_id: str,
        skim: PaperSkim,
    ) -> None:
        model_by_kind = {
            "document": (SourceDocument, SourceDocument.source_document_id),
            "block": (SourceBlock, SourceBlock.block_id),
            "table": (SourceTable, SourceTable.table_id),
            "table_row": (SourceTableRow, SourceTableRow.row_id),
            "figure": (SourceFigure, SourceFigure.figure_id),
        }
        source_refs = (
            ref
            for refs in (
                *(relationship.source_refs for study in skim.studies for relationship in study.relationships),
                *(signal.source_refs for signal in skim.unresolved_signals),
                *(
                    item.source_refs
                    for field_name in (
                        "synthesis_claims",
                        "disputes",
                        "evidence_gaps",
                        "citation_leads",
                    )
                    for item in getattr(skim.review_synthesis, field_name)
                ),
                skim.source_unit_coverage,
            )
            for ref in refs
        )
        for source_ref in source_refs:
            model_and_id = model_by_kind.get(source_ref.source_kind)
            if model_and_id is None:
                raise ValueError(
                    f"unsupported paper study source kind: {source_ref.source_kind}"
                )
            model, id_column = model_and_id
            filters = (
                model.collection_id == collection_id,
                model.build_id == build_id,
                id_column == source_ref.source_ref,
            )
            if source_ref.source_kind != "document":
                filters = (
                    *filters,
                    model.source_document_id == skim.document_id,
                )
            elif source_ref.source_ref != skim.document_id:
                raise FileNotFoundError(
                    "paper study Source document belongs to another skim: "
                    f"{source_ref.source_ref}/{skim.document_id}"
                )
            exists = await session.scalar(
                select(func.count()).select_from(model).where(*filters)
            )
            if not exists:
                raise FileNotFoundError(
                    "paper study source not found: "
                    f"{collection_id}/{build_id}/{skim.document_id}/"
                    f"{source_ref.source_kind}/{source_ref.source_ref}"
                )

    @staticmethod
    def _relationship_index(
        paper_skims: Iterable[PaperSkim],
    ) -> dict[str, tuple[str, str, PaperStudyRelationship]]:
        return {
            relationship.relationship_id: (
                skim.document_id,
                study.study_id,
                relationship,
            )
            for skim in paper_skims
            for study in skim.studies
            for relationship in study.relationships
        }

    @staticmethod
    async def _write_paper_study_rows(
        session: AsyncSession,
        *,
        collection_id: str,
        build_id: str,
        skim: PaperSkim,
    ) -> None:
        for study_order, study in enumerate(skim.studies):
            session.add(
                ObjectivePaperStudy(
                    build_id=build_id,
                    source_document_id=skim.document_id,
                    study_id=study.study_id,
                    collection_id=collection_id,
                    study_order=study_order,
                    design_type=study.design_type,
                    claim_scope=study.claim_scope,
                    experiment_label=study.experiment_label,
                    material_scope=list(study.material_scope),
                    process_context=list(study.process_context),
                    sample_context=list(study.sample_context),
                    test_context=list(study.test_context),
                    comparator=study.comparator,
                    fixed_conditions=list(study.fixed_conditions),
                    confidence=study.confidence,
                )
            )
            session.add_all(
                ObjectivePaperStudyRelationship(
                    build_id=build_id,
                    source_document_id=skim.document_id,
                    study_id=study.study_id,
                    relationship_id=relationship.relationship_id,
                    collection_id=collection_id,
                    relationship_order=relationship_order,
                    varied_factors=list(relationship.varied_factors),
                    outcome=relationship.outcome,
                    source_refs=[ref.to_record() for ref in relationship.source_refs],
                    confidence=relationship.confidence,
                )
                for relationship_order, relationship in enumerate(study.relationships)
            )
        session.add_all(
            ObjectivePaperStudySignal(
                build_id=build_id,
                source_document_id=skim.document_id,
                signal_id=signal.signal_id,
                collection_id=collection_id,
                signal_order=signal_order,
                payload=signal.to_record(),
            )
            for signal_order, signal in enumerate(skim.unresolved_signals)
        )
        session.add_all(
            ObjectivePaperSourceUnitCoverage(
                build_id=build_id,
                source_document_id=skim.document_id,
                source_unit_id=item.source_unit_id,
                collection_id=collection_id,
                coverage_order=coverage_order,
                window_id=item.window_id,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                status=item.status.value,
                reason=item.reason,
            )
            for coverage_order, item in enumerate(skim.source_unit_coverage)
        )

    @staticmethod
    async def _coverage_rows_by_document(
        session: AsyncSession,
        build_id: str,
    ) -> dict[str, tuple[PaperSourceUnitCoverage, ...]]:
        grouped: dict[str, list[PaperSourceUnitCoverage]] = defaultdict(list)
        for row in await session.scalars(
            select(ObjectivePaperSourceUnitCoverage)
            .where(ObjectivePaperSourceUnitCoverage.build_id == build_id)
            .order_by(
                ObjectivePaperSourceUnitCoverage.source_document_id,
                ObjectivePaperSourceUnitCoverage.coverage_order,
            )
        ):
            grouped[row.source_document_id].append(
                PaperSourceUnitCoverage.from_mapping(
                    {
                        "source_unit_id": row.source_unit_id,
                        "window_id": row.window_id,
                        "source_kind": row.source_kind,
                        "source_ref": row.source_ref,
                        "status": row.status,
                        "reason": row.reason,
                    }
                )
            )
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    async def _relationship_rows_by_study(
        session: AsyncSession,
        build_id: str,
    ) -> dict[tuple[str, str], tuple[PaperStudyRelationship, ...]]:
        grouped: dict[tuple[str, str], list[PaperStudyRelationship]] = defaultdict(list)
        for row in await session.scalars(
            select(ObjectivePaperStudyRelationship)
            .where(ObjectivePaperStudyRelationship.build_id == build_id)
            .order_by(
                ObjectivePaperStudyRelationship.source_document_id,
                ObjectivePaperStudyRelationship.study_id,
                ObjectivePaperStudyRelationship.relationship_order,
            )
        ):
            grouped[(row.source_document_id, row.study_id)].append(
                PaperStudyRelationship.from_mapping(
                    {
                        "relationship_id": row.relationship_id,
                        "varied_factors": row.varied_factors,
                        "outcome": row.outcome,
                        "source_refs": row.source_refs,
                        "confidence": row.confidence,
                    }
                )
            )
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    async def _study_rows_by_document(
        session: AsyncSession,
        build_id: str,
        relationships_by_study: dict[
            tuple[str, str], tuple[PaperStudyRelationship, ...]
        ],
    ) -> dict[str, tuple[PaperStudy, ...]]:
        grouped: dict[str, list[PaperStudy]] = defaultdict(list)
        for row in await session.scalars(
            select(ObjectivePaperStudy)
            .where(ObjectivePaperStudy.build_id == build_id)
            .order_by(
                ObjectivePaperStudy.source_document_id,
                ObjectivePaperStudy.study_order,
            )
        ):
            grouped[row.source_document_id].append(
                PaperStudy.from_mapping(
                    {
                        "study_id": row.study_id,
                        "document_id": row.source_document_id,
                        "design_type": row.design_type,
                        "claim_scope": row.claim_scope,
                        "experiment_label": row.experiment_label,
                        "material_scope": row.material_scope,
                        "process_context": row.process_context,
                        "sample_context": row.sample_context,
                        "test_context": row.test_context,
                        "comparator": row.comparator,
                        "fixed_conditions": row.fixed_conditions,
                        "relationships": [
                            item.to_record()
                            for item in relationships_by_study.get(
                                (row.source_document_id, row.study_id), ()
                            )
                        ],
                        "confidence": row.confidence,
                    }
                )
            )
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    async def _signal_rows_by_document(
        session: AsyncSession,
        build_id: str,
    ) -> dict[str, tuple[PaperStudySignal, ...]]:
        grouped: dict[str, list[PaperStudySignal]] = defaultdict(list)
        for row in await session.scalars(
            select(ObjectivePaperStudySignal)
            .where(ObjectivePaperStudySignal.build_id == build_id)
            .order_by(
                ObjectivePaperStudySignal.source_document_id,
                ObjectivePaperStudySignal.signal_order,
            )
        ):
            grouped[row.source_document_id].append(
                PaperStudySignal.from_mapping(row.payload)
            )
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    async def _relationship_ids_by_objective(
        session: AsyncSession,
        build_id: str,
    ) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in (
            await session.execute(
                select(objective_build_relationship_links)
                .where(objective_build_relationship_links.c.build_id == build_id)
                .order_by(
                    objective_build_relationship_links.c.objective_id,
                    objective_build_relationship_links.c.link_order,
                )
            )
        ).mappings():
            grouped[str(row["objective_id"])].append(str(row["relationship_id"]))
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    async def _replace_document_scope(
        session: AsyncSession,
        build_id: str,
        objective: ResearchObjective,
    ) -> None:
        await session.execute(
            delete(objective_document_scope).where(
                objective_document_scope.c.collection_id == objective.collection_id,
                objective_document_scope.c.objective_id == objective.objective_id,
                objective_document_scope.c.build_id == build_id,
            )
        )
        for scope_kind, document_ids in (
            ("seed", objective.seed_document_ids),
            ("excluded", objective.excluded_document_ids),
        ):
            rows = [
                {
                    "build_id": build_id,
                    "collection_id": objective.collection_id,
                    "objective_id": objective.objective_id,
                    "scope_kind": scope_kind,
                    "source_document_id": document_id,
                    "position": position,
                }
                for position, document_id in enumerate(document_ids)
            ]
            if rows:
                await session.execute(objective_document_scope.insert(), rows)

    @staticmethod
    async def _scope_by_objective(
        session: AsyncSession,
        collection_id: str,
        *,
        build_id: str,
    ) -> dict[str, dict[str, tuple[str, ...]]]:
        grouped: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in (
            await session.execute(
                select(objective_document_scope)
                .where(
                    objective_document_scope.c.collection_id == collection_id,
                    objective_document_scope.c.build_id == build_id,
                )
                .order_by(
                    objective_document_scope.c.objective_id,
                    objective_document_scope.c.scope_kind,
                    objective_document_scope.c.position,
                )
            )
        ).mappings():
            grouped[str(row["objective_id"])][str(row["scope_kind"])].append(
                str(row["source_document_id"])
            )
        build_seed_scope: dict[str, list[str]] = defaultdict(list)
        for row in (
            await session.execute(
                select(objective_build_relationship_links)
                .where(
                    objective_build_relationship_links.c.collection_id
                    == collection_id,
                    objective_build_relationship_links.c.build_id == build_id,
                )
                .order_by(
                    objective_build_relationship_links.c.objective_id,
                    objective_build_relationship_links.c.link_order,
                )
            )
        ).mappings():
            objective_id = str(row["objective_id"])
            document_id = str(row["source_document_id"])
            if document_id not in build_seed_scope[objective_id]:
                build_seed_scope[objective_id].append(document_id)
        for objective_id, document_ids in build_seed_scope.items():
            grouped[objective_id]["seed"] = document_ids
        return {
            objective_id: {
                scope_kind: tuple(document_ids)
                for scope_kind, document_ids in scope.items()
            }
            for objective_id, scope in grouped.items()
        }

    @staticmethod
    async def _authored_candidate(
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAuthoredCandidateRecord | None:
        return await session.get(
            ObjectiveAuthoredCandidateRecord,
            (collection_id, objective_id),
        )

    @classmethod
    async def _objective_scope(
        cls,
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
        *,
        build_id: str,
        authored: ObjectiveAuthoredCandidateRecord | None,
    ) -> dict[str, tuple[str, ...]]:
        if authored is not None:
            if authored.source_build_id != build_id:
                raise ValueError("authored candidate is bound to another Source build")
            return {
                "seed": tuple(authored.seed_document_ids),
                "excluded": tuple(authored.excluded_document_ids),
            }
        return (
            await cls._scope_by_objective(
                session,
                collection_id,
                build_id=build_id,
            )
        ).get(objective_id, {})

    @classmethod
    async def _objective_rank(
        cls,
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
    ) -> int:
        active_build_id = await cls._resolve_read_build(session, collection_id, None)
        generated_ids: list[str] = []
        if active_build_id is not None:
            marker = await session.get(ObjectiveBuild, active_build_id)
            if (
                marker is not None
                and marker.collection_id == collection_id
                and marker.research_objectives_ready
            ):
                generated_ids = [
                    str(row.objective_id)
                    for row in await session.execute(
                        select(objective_build_candidates.c.objective_id)
                        .where(
                            objective_build_candidates.c.collection_id
                            == collection_id,
                            objective_build_candidates.c.build_id == active_build_id,
                        )
                        .order_by(objective_build_candidates.c.objective_order)
                    )
                ]
        if objective_id in generated_ids:
            return generated_ids.index(objective_id) + 1

        authored_ids = [
            row.objective_id
            for row in await session.scalars(
                select(ObjectiveAuthoredCandidateRecord)
                .where(
                    ObjectiveAuthoredCandidateRecord.collection_id == collection_id
                )
                .order_by(
                    ObjectiveAuthoredCandidateRecord.created_at,
                    ObjectiveAuthoredCandidateRecord.objective_id,
                )
            )
            if row.objective_id not in generated_ids
        ]
        try:
            return len(generated_ids) + authored_ids.index(objective_id) + 1
        except ValueError as exc:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            ) from exc

    @staticmethod
    async def _analysis_versions_by_objective(
        session: AsyncSession,
        collection_id: str,
        build_id: str,
    ) -> dict[str, tuple[int | None, int | None]]:
        versions: dict[str, tuple[int | None, int | None]] = {}
        for row in await session.scalars(
            select(ObjectiveAnalysisRecord)
            .where(
                ObjectiveAnalysisRecord.collection_id == collection_id,
                ObjectiveAnalysisRecord.source_build_id == build_id,
            )
            .order_by(
                ObjectiveAnalysisRecord.objective_id,
                ObjectiveAnalysisRecord.analysis_version,
            )
        ):
            _active, published = versions.get(row.objective_id, (None, None))
            versions[row.objective_id] = (
                row.analysis_version,
                row.analysis_version if row.status == "succeeded" else published,
            )
        return versions

    @staticmethod
    async def _require_source_locator(
        session: AsyncSession,
        collection_id: str,
        source_build_id: str,
        evidence: ObjectiveEvidence,
    ) -> None:
        model_and_id = {
            "text_window": (SourceBlock, SourceBlock.block_id),
            "table": (SourceTable, SourceTable.table_id),
            "figure": (SourceFigure, SourceFigure.figure_id),
        }[evidence.source_kind]
        model, id_column = model_and_id
        exists = await session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.collection_id == collection_id,
                model.build_id == source_build_id,
                model.source_document_id == evidence.document_id,
                id_column == evidence.source_ref,
            )
        )
        if not exists:
            raise FileNotFoundError(
                "objective evidence source not found: "
                f"{collection_id}/{source_build_id}/{evidence.document_id}/"
                f"{evidence.source_kind}/{evidence.source_ref}"
            )

    @staticmethod
    async def _locked_objective(
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveResearchRecord:
        row = await session.scalar(
            select(ObjectiveResearchRecord)
            .where(
                ObjectiveResearchRecord.collection_id == collection_id,
                ObjectiveResearchRecord.objective_id == objective_id,
            )
            .with_for_update()
        )
        if row is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return row

    @staticmethod
    async def _locked_analysis(
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysisRecord:
        row = await session.scalar(
            select(ObjectiveAnalysisRecord)
            .where(
                ObjectiveAnalysisRecord.collection_id == collection_id,
                ObjectiveAnalysisRecord.objective_id == objective_id,
                ObjectiveAnalysisRecord.analysis_version == analysis_version,
            )
            .with_for_update()
        )
        if row is None:
            raise FileNotFoundError(
                "objective analysis not found: "
                f"{collection_id}/{objective_id}/{analysis_version}"
            )
        return row

    @staticmethod
    async def _source_document_ids(
        session: AsyncSession,
        collection_id: str,
        build_id: str,
    ) -> set[str]:
        return set(
            await session.scalars(
                select(SourceDocument.source_document_id).where(
                    SourceDocument.collection_id == collection_id,
                    SourceDocument.build_id == build_id,
                )
            )
        )

    @staticmethod
    def _require_source_document(
        source_document_ids: set[str],
        collection_id: str,
        source_document_id: str,
    ) -> None:
        if source_document_id not in source_document_ids:
            raise FileNotFoundError(
                f"source document not found: {collection_id}/{source_document_id}"
            )

    @staticmethod
    async def _require_build(
        session: AsyncSession,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = await session.get(CollectionBuild, build_id)
        if build is None or build.collection_id != collection_id:
            raise FileNotFoundError(
                f"collection build not found: {collection_id}/{build_id}"
            )
        return build

    @classmethod
    async def _require_writable_build(
        cls,
        session: AsyncSession,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = await cls._require_build(session, collection_id, build_id)
        if build.status not in {"queued", "building"}:
            raise ValueError(f"collection build is not writable: {build_id}")
        return build

    @classmethod
    async def _resolve_read_build(
        cls,
        session: AsyncSession,
        collection_id: str,
        build_id: str | None,
    ) -> str | None:
        if build_id is not None:
            await cls._require_build(session, collection_id, build_id)
            return build_id
        return await session.scalar(
            select(CollectionActiveBuild.build_id).where(
                CollectionActiveBuild.collection_id == collection_id
            )
        )

    @classmethod
    async def _objective_build_link(
        cls,
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
        *,
        build_id: str | None = None,
    ) -> tuple[tuple[str, ...], int, str] | None:
        authored = await cls._authored_candidate(session, collection_id, objective_id)
        if authored is not None and (
            build_id is None or build_id == authored.source_build_id
        ):
            marker = await session.get(ObjectiveBuild, authored.source_build_id)
            if (
                marker is not None
                and marker.collection_id == collection_id
                and marker.research_objectives_ready
            ):
                return (
                    (),
                    await cls._objective_rank(session, collection_id, objective_id),
                    authored.source_build_id,
                )
        resolved_build_id = await cls._resolve_read_build(session, collection_id, build_id)
        if resolved_build_id is None:
            return None
        marker = await session.get(ObjectiveBuild, resolved_build_id)
        if (
            marker is None
            or marker.collection_id != collection_id
            or not marker.research_objectives_ready
        ):
            return None
        link = (
            await session.execute(
                select(objective_build_candidates.c.objective_order).where(
                    objective_build_candidates.c.collection_id == collection_id,
                    objective_build_candidates.c.build_id == resolved_build_id,
                    objective_build_candidates.c.objective_id == objective_id,
                )
            )
        ).one_or_none()
        if link is None:
            return None
        source_relationship_ids = (
            await cls._relationship_ids_by_objective(session, resolved_build_id)
        ).get(objective_id, ())
        return source_relationship_ids, int(link.objective_order) + 1, resolved_build_id

    @classmethod
    async def _require_objective_build_link(
        cls,
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
        *,
        build_id: str | None = None,
    ) -> tuple[tuple[str, ...], int, str]:
        link = await cls._objective_build_link(
            session,
            collection_id,
            objective_id,
            build_id=build_id,
        )
        if link is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return link


__all__ = ["PostgresObjectiveRepository"]
