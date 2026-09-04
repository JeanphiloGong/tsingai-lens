"""PostgreSQL persistence for current Objective discovery and analyses."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.pipeline import ExecutionStats
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisRecord,
    ObjectiveDocumentEvidenceRecord,
    ObjectiveDiscoveryRecord,
    ObjectiveEvidenceRecord,
    ObjectiveFindingRecord,
    ObjectivePaperContributionRecord,
    ObjectiveResearchRecord,
)
from infra.persistence.postgres.models.source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
)


class PostgresObjectiveRepository:
    backend_name = "postgres"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(
        self,
        collection_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        for objective in facts.research_objectives:
            if objective.collection_id != collection_id:
                raise ValueError("objective belongs to another collection")
            if objective.origin != "system_discovered":
                raise ValueError("Objective discovery can only replace system candidates")

        now = datetime.now(timezone.utc)
        objective_ids = [item.objective_id for item in facts.research_objectives]
        async with self.session_factory.begin() as session:
            discovery = await session.get(ObjectiveDiscoveryRecord, collection_id)
            if discovery is None:
                discovery = ObjectiveDiscoveryRecord(
                    collection_id=collection_id,
                    research_objectives_ready=facts.research_objectives_ready,
                    document_inputs=[item.to_record() for item in facts.document_inputs],
                    objective_ids=objective_ids,
                    study_dispositions=[
                        item.to_record() for item in facts.study_dispositions
                    ],
                    updated_at=now,
                )
                session.add(discovery)
            else:
                discovery.research_objectives_ready = facts.research_objectives_ready
                discovery.document_inputs = [
                    item.to_record() for item in facts.document_inputs
                ]
                discovery.objective_ids = objective_ids
                discovery.study_dispositions = [
                    item.to_record() for item in facts.study_dispositions
                ]
                discovery.updated_at = now

            existing_system_rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord).where(
                        ObjectiveResearchRecord.collection_id == collection_id,
                        ObjectiveResearchRecord.origin == "system_discovered",
                    )
                )
            )
            retained_ids = set(objective_ids)
            for row in existing_system_rows:
                existing = self._objective_from_row(row)
                if (
                    existing.confirmation_status == "candidate"
                    and row.objective_id not in retained_ids
                ):
                    await session.delete(row)

            for objective in facts.research_objectives:
                row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective.objective_id),
                )
                if row is not None:
                    existing = self._objective_from_row(row)
                    if existing.origin != "system_discovered":
                        raise ValueError("research objective identity collision")
                    objective = replace(
                        objective,
                        confirmation_status=existing.confirmation_status,
                        active_analysis_version=existing.active_analysis_version,
                        published_analysis_version=existing.published_analysis_version,
                    )
                    self._write_objective(row, objective, now=now)
                    continue
                session.add(self._new_objective_row(objective, now=now))

    async def read(self, collection_id: str) -> ObjectiveFactSet:
        async with self.session_factory() as session:
            discovery = await session.get(ObjectiveDiscoveryRecord, collection_id)
            if discovery is None:
                return ObjectiveFactSet()
            rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord).where(
                        ObjectiveResearchRecord.collection_id == collection_id,
                        ObjectiveResearchRecord.objective_id.in_(
                            discovery.objective_ids or [""]
                        ),
                    )
                )
            )
            by_id = {row.objective_id: self._objective_from_row(row) for row in rows}
            return ObjectiveFactSet(
                research_objectives_ready=discovery.research_objectives_ready,
                document_inputs=tuple(
                    PreparedDocumentInput.from_mapping(item)
                    for item in discovery.document_inputs
                ),
                research_objectives=tuple(
                    by_id[objective_id]
                    for objective_id in discovery.objective_ids
                    if objective_id in by_id
                ),
                study_dispositions=tuple(
                    PaperStudyDisposition.from_mapping(item)
                    for item in discovery.study_dispositions
                ),
            )

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord)
                    .where(ObjectiveResearchRecord.collection_id == collection_id)
                    .order_by(
                        ObjectiveResearchRecord.rank,
                        ObjectiveResearchRecord.created_at,
                        ObjectiveResearchRecord.objective_id,
                    )
                )
            )
            return tuple(self._objective_from_row(row) for row in rows)

    async def list_objective_records(
        self,
        collection_id: str,
    ) -> tuple[dict[str, Any], ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord)
                    .where(ObjectiveResearchRecord.collection_id == collection_id)
                    .order_by(
                        ObjectiveResearchRecord.rank,
                        ObjectiveResearchRecord.created_at,
                        ObjectiveResearchRecord.objective_id,
                    )
                )
            )
            return tuple(self._objective_record_from_row(row) for row in rows)

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
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            prior = await session.scalar(
                select(ObjectiveResearchRecord).where(
                    ObjectiveResearchRecord.created_by_tool_call_id
                    == created_by_tool_call_id
                )
            )
            if prior is not None:
                existing = self._objective_from_row(prior)
                if (
                    existing.collection_id != objective.collection_id
                    or existing.objective_id != objective.objective_id
                    or existing.created_by_user_id != created_by_user_id
                ):
                    raise ValueError(
                        "authored candidate tool call already created a different objective"
                    )
                return existing
            collision = await session.get(
                ObjectiveResearchRecord,
                (objective.collection_id, objective.objective_id),
            )
            if collision is not None:
                raise ValueError("research objective identity collision")
            maximum_rank = await session.scalar(
                select(func.max(ObjectiveResearchRecord.rank)).where(
                    ObjectiveResearchRecord.collection_id == objective.collection_id
                )
            )
            created = replace(
                objective,
                rank=int(maximum_rank or 0) + 1,
            )
            session.add(self._new_objective_row(created, now=now))
            return created

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveResearchRecord,
                (collection_id, objective_id),
            )
            return self._objective_from_row(row) if row is not None else None

    async def read_objective_record(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveResearchRecord,
                (collection_id, objective_id),
            )
            return self._objective_record_from_row(row) if row is not None else None

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
        origin: str = "system_generated",
        created_by_user_id: str | None = None,
        created_by_tool_call_id: str | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            row = await self._locked_objective(session, collection_id, objective_id)
            objective = self._objective_from_row(row)
            if objective.confirmation_status == "candidate":
                objective = objective.confirm()
            active_row = await session.scalar(
                select(ObjectiveAnalysisRecord)
                .where(
                    ObjectiveAnalysisRecord.collection_id == collection_id,
                    ObjectiveAnalysisRecord.objective_id == objective_id,
                    ObjectiveAnalysisRecord.status.in_(("queued", "running")),
                )
                .order_by(ObjectiveAnalysisRecord.analysis_version.desc())
                .with_for_update()
            )
            if active_row is not None:
                active = self._analysis_from_row(active_row)
                if active.document_inputs != document_inputs:
                    raise ValueError(
                        "an active analysis already uses a different document scope"
                    )
                if (
                    active.origin != origin
                    or active.created_by_user_id != created_by_user_id
                    or active.created_by_tool_call_id != created_by_tool_call_id
                ):
                    raise ValueError(
                        "an active analysis already uses different authoring provenance"
                    )
                self._write_objective(row, objective, now=now)
                return objective, active
            maximum_version = await session.scalar(
                select(func.max(ObjectiveAnalysisRecord.analysis_version)).where(
                    ObjectiveAnalysisRecord.collection_id == collection_id,
                    ObjectiveAnalysisRecord.objective_id == objective_id,
                )
            )
            version = int(maximum_version or 0) + 1
            analysis = ObjectiveAnalysis(
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=version,
                document_inputs=document_inputs,
                pipeline_version=pipeline_version,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                total_document_count=len(document_inputs),
                progress_message="Objective analysis is queued.",
                created_at=now,
                origin=origin,
                created_by_user_id=created_by_user_id,
                created_by_tool_call_id=created_by_tool_call_id,
            )
            objective = objective.queue_analysis(version)
            self._write_objective(row, objective, now=now)
            session.add(self._new_analysis_row(analysis, now=now))
            return objective, analysis

    async def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session,
                collection_id,
                objective_id,
                analysis_version,
            )
            analysis = self._analysis_from_row(row)
            if analysis.status != "queued":
                return None
            analysis = analysis.start(started_at=datetime.now(timezone.utc))
            self._write_analysis(row, analysis)
            return analysis

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
            analysis = self._analysis_from_row(row).update_progress(
                phase=phase,
                processed_document_count=processed_document_count,
                total_document_count=total_document_count,
                current_document_id=current_document_id,
                progress_message=progress_message,
            )
            self._write_analysis(row, analysis)
            return analysis

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
            analysis = replace(
                self._analysis_from_row(row),
                stats=stats,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                diagnostics=diagnostics,
            )
            self._write_analysis(row, analysis)
            return analysis

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
            analysis = self._analysis_from_row(row)
            if expected_status is not None and analysis.status != expected_status:
                return analysis
            analysis = analysis.fail(
                error_code=error_code,
                error_message=error_message,
                completed_at=datetime.now(timezone.utc),
            )
            self._write_analysis(row, analysis)
            return analysis

    async def interrupt_active_analyses(self) -> int:
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveAnalysisRecord)
                    .where(ObjectiveAnalysisRecord.status.in_(("queued", "running")))
                    .with_for_update()
                )
            )
            for row in rows:
                analysis = self._analysis_from_row(row).fail(
                    error_code="analysis_interrupted",
                    error_message=(
                        "Objective analysis was interrupted by a backend restart. "
                        "Retry the analysis."
                    ),
                    completed_at=now,
                )
                self._write_analysis(row, analysis)
            return len(rows)

    async def write_document_evidence(
        self,
        checkpoint: ObjectiveDocumentEvidence,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            row = await session.get(ObjectiveDocumentEvidenceRecord, checkpoint.key)
            if row is None:
                session.add(
                    ObjectiveDocumentEvidenceRecord(
                        collection_id=checkpoint.collection_id,
                        objective_id=checkpoint.objective_id,
                        document_id=checkpoint.document_id,
                        input_fingerprint=checkpoint.input_fingerprint,
                        status=checkpoint.status,
                        payload=checkpoint.to_record(),
                        created_at=checkpoint.started_at or now,
                        updated_at=now,
                    )
                )
                return
            row.status = checkpoint.status
            row.payload = checkpoint.to_record()
            row.updated_at = now

    async def read_document_evidence(
        self,
        collection_id: str,
        objective_id: str,
        document_id: str,
        input_fingerprint: str,
    ) -> ObjectiveDocumentEvidence | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveDocumentEvidenceRecord,
                (collection_id, objective_id, document_id, input_fingerprint),
            )
            return (
                ObjectiveDocumentEvidence.from_mapping(row.payload)
                if row is not None
                else None
            )

    async def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
        abstention_reason: str | None = None,
        abstention_note: str | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        key = (collection_id, objective_id, analysis_version)
        async with self.session_factory.begin() as session:
            analysis_row = await self._locked_analysis(session, *key)
            objective_row = await self._locked_objective(
                session, collection_id, objective_id
            )
            analysis = self._analysis_from_row(analysis_row)
            if analysis.status != "running":
                raise ValueError("only running objective analysis can be published")
            for record in (*contributions, *evidence_records, *findings):
                if record.key[:3] != key:
                    raise ValueError("analysis artifact belongs to another version")
            input_documents = {item.document_id for item in analysis.document_inputs}
            contribution_documents = {item.document_id for item in contributions}
            if contribution_documents != input_documents:
                raise ValueError("paper contributions must cover every analysis input")
            if {item.document_id for item in evidence_records} - contribution_documents:
                raise ValueError("objective evidence lacks owning paper contribution")
            for evidence in evidence_records:
                await self._require_source_locator(session, collection_id, evidence)
            for finding in findings:
                finding.validate_sources(evidence_records, contributions)

            await session.execute(
                delete(ObjectiveEvidenceRecord).where(
                    ObjectiveEvidenceRecord.collection_id == collection_id,
                    ObjectiveEvidenceRecord.objective_id == objective_id,
                    ObjectiveEvidenceRecord.analysis_version == analysis_version,
                )
            )
            await session.execute(
                delete(ObjectiveFindingRecord).where(
                    ObjectiveFindingRecord.collection_id == collection_id,
                    ObjectiveFindingRecord.objective_id == objective_id,
                    ObjectiveFindingRecord.analysis_version == analysis_version,
                )
            )
            await session.execute(
                delete(ObjectivePaperContributionRecord).where(
                    ObjectivePaperContributionRecord.collection_id == collection_id,
                    ObjectivePaperContributionRecord.objective_id == objective_id,
                    ObjectivePaperContributionRecord.analysis_version
                    == analysis_version,
                )
            )
            session.add_all(
                ObjectivePaperContributionRecord(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    analysis_version=analysis_version,
                    source_document_id=item.document_id,
                    payload=item.to_record(),
                )
                for item in contributions
            )
            await session.flush()
            session.add_all(
                ObjectiveEvidenceRecord(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    analysis_version=analysis_version,
                    evidence_id=item.evidence_id,
                    source_document_id=item.document_id,
                    payload=item.to_record(),
                )
                for item in evidence_records
            )
            session.add_all(
                ObjectiveFindingRecord(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    analysis_version=analysis_version,
                    finding_id=item.finding_id,
                    display_rank=item.display_rank,
                    payload=item.to_record(),
                )
                for item in findings
            )
            analysis = analysis.succeed(
                completed_at=datetime.now(timezone.utc),
                abstention_reason=abstention_reason,
                abstention_note=abstention_note,
            )
            objective = self._objective_from_row(objective_row).publish_analysis(
                analysis
            )
            self._write_analysis(analysis_row, analysis)
            self._write_objective(
                objective_row,
                objective,
                now=datetime.now(timezone.utc),
            )
            return objective, analysis

    async def publish_authored_analysis(
        self,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        *,
        analysis: ObjectiveAnalysis,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        async with self.session_factory.begin() as session:
            objective_row = await self._locked_objective(
                session, collection_id, objective_id
            )
            objective = self._objective_from_row(objective_row)
            if objective.published_analysis_version != source_analysis_version:
                raise ValueError("source analysis version is stale")
            source_row = await self._locked_analysis(
                session, collection_id, objective_id, source_analysis_version
            )
            source = self._analysis_from_row(source_row)
            active_version = (
                objective.active_analysis_version or source_analysis_version
            )
            if active_version != source_analysis_version:
                active_row = await self._locked_analysis(
                    session, collection_id, objective_id, active_version
                )
                if self._analysis_from_row(active_row).status in {"queued", "running"}:
                    raise ValueError("objective analysis is currently running")
            if analysis.analysis_version != active_version + 1:
                raise ValueError("authored analysis version is no longer current")
            if analysis.status != "succeeded" or analysis.origin == "system_generated":
                raise ValueError(
                    "authored analysis must be a completed authored version"
                )
            if analysis.source_analysis_version != source_analysis_version:
                raise ValueError(
                    "authored analysis source version differs from request"
                )
            if source.status != "succeeded":
                raise ValueError(
                    "authored analysis requires a succeeded source version"
                )
            for record in (*contributions, *evidence_records, *findings):
                if record.key[:3] != analysis.key:
                    raise ValueError("analysis artifact belongs to another version")
            input_documents = {item.document_id for item in analysis.document_inputs}
            contribution_documents = {item.document_id for item in contributions}
            if contribution_documents != input_documents:
                raise ValueError(
                    "paper contributions must cover every analysis input"
                )
            if {item.document_id for item in evidence_records} - contribution_documents:
                raise ValueError(
                    "objective evidence lacks owning paper contribution"
                )
            for evidence in evidence_records:
                await self._require_source_locator(session, collection_id, evidence)
            for finding in findings:
                finding.validate_sources(evidence_records, contributions)

            now = datetime.now(timezone.utc)
            session.add(self._new_analysis_row(analysis, now=now))
            session.add_all(
                ObjectivePaperContributionRecord(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    analysis_version=analysis.analysis_version,
                    source_document_id=item.document_id,
                    payload=item.to_record(),
                )
                for item in contributions
            )
            await session.flush()
            session.add_all(
                ObjectiveEvidenceRecord(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    analysis_version=analysis.analysis_version,
                    evidence_id=item.evidence_id,
                    source_document_id=item.document_id,
                    payload=item.to_record(),
                )
                for item in evidence_records
            )
            session.add_all(
                ObjectiveFindingRecord(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    analysis_version=analysis.analysis_version,
                    finding_id=item.finding_id,
                    display_rank=item.display_rank,
                    payload=item.to_record(),
                )
                for item in findings
            )
            objective = objective.queue_analysis(analysis.analysis_version)
            objective = objective.publish_analysis(analysis)
            self._write_objective(objective_row, objective, now=now)
            return objective, analysis

    async def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory() as session:
            if analysis_version is None:
                objective_row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective_id),
                )
                if objective_row is None:
                    return None
                analysis_version = self._objective_from_row(
                    objective_row
                ).active_analysis_version
            if analysis_version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            return self._analysis_from_row(row) if row is not None else None

    async def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory() as session:
            objective_row = await session.get(
                ObjectiveResearchRecord,
                (collection_id, objective_id),
            )
            if objective_row is None:
                return None
            version = self._objective_from_row(
                objective_row
            ).published_analysis_version
            if version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, version),
            )
            return self._analysis_from_row(row) if row is not None else None

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectivePaperContributionRecord)
                    .where(
                        ObjectivePaperContributionRecord.collection_id == collection_id,
                        ObjectivePaperContributionRecord.objective_id == objective_id,
                        ObjectivePaperContributionRecord.analysis_version
                        == analysis_version,
                    )
                    .order_by(ObjectivePaperContributionRecord.source_document_id)
                )
            )
            return tuple(PaperContribution.from_mapping(row.payload) for row in rows)

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]:
        conditions = (
            ObjectiveFindingRecord.collection_id == collection_id,
            ObjectiveFindingRecord.objective_id == objective_id,
            ObjectiveFindingRecord.analysis_version == analysis_version,
        )
        async with self.session_factory() as session:
            total = int(
                await session.scalar(
                    select(func.count()).select_from(ObjectiveFindingRecord).where(
                        *conditions
                    )
                )
                or 0
            )
            rows = tuple(
                await session.scalars(
                    select(ObjectiveFindingRecord)
                    .where(*conditions)
                    .order_by(
                        ObjectiveFindingRecord.display_rank,
                        ObjectiveFindingRecord.finding_id,
                    )
                    .offset(max(0, offset))
                    .limit(max(1, min(limit, 200)))
                )
            )
            return tuple(Finding.from_mapping(row.payload) for row in rows), total

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
            return Finding.from_mapping(row.payload) if row is not None else None

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
            evidence_ids: set[str] | None = None
            if finding_id is not None:
                finding_row = await session.get(
                    ObjectiveFindingRecord,
                    (collection_id, objective_id, analysis_version, finding_id),
                )
                if finding_row is None:
                    return (), 0
                finding = Finding.from_mapping(finding_row.payload)
                evidence_ids = {
                    *finding.supporting_evidence_ids,
                    *finding.contradicting_evidence_ids,
                    *finding.context_evidence_ids,
                }
            conditions = [
                ObjectiveEvidenceRecord.collection_id == collection_id,
                ObjectiveEvidenceRecord.objective_id == objective_id,
                ObjectiveEvidenceRecord.analysis_version == analysis_version,
            ]
            if evidence_ids is not None:
                if not evidence_ids:
                    return (), 0
                conditions.append(
                    ObjectiveEvidenceRecord.evidence_id.in_(evidence_ids)
                )
            total = int(
                await session.scalar(
                    select(func.count()).select_from(ObjectiveEvidenceRecord).where(
                        *conditions
                    )
                )
                or 0
            )
            rows = tuple(
                await session.scalars(
                    select(ObjectiveEvidenceRecord)
                    .where(*conditions)
                    .order_by(ObjectiveEvidenceRecord.evidence_id)
                    .offset(max(0, offset))
                    .limit(max(1, min(limit, 500)))
                )
            )
            return (
                tuple(ObjectiveEvidence.from_mapping(row.payload) for row in rows),
                total,
            )

    @staticmethod
    def _objective_from_row(row: ObjectiveResearchRecord) -> ResearchObjective:
        return ResearchObjective.from_mapping(row.payload)

    @staticmethod
    def _objective_record_from_row(
        row: ObjectiveResearchRecord,
    ) -> dict[str, Any]:
        record = PostgresObjectiveRepository._objective_from_row(row).to_record()
        record["created_at"] = row.created_at.isoformat()
        record["updated_at"] = row.updated_at.isoformat()
        return record

    @staticmethod
    def _analysis_from_row(row: ObjectiveAnalysisRecord) -> ObjectiveAnalysis:
        return ObjectiveAnalysis.from_mapping(row.payload)

    @staticmethod
    def _new_objective_row(
        objective: ResearchObjective,
        *,
        now: datetime,
    ) -> ObjectiveResearchRecord:
        return ObjectiveResearchRecord(
            collection_id=objective.collection_id,
            objective_id=objective.objective_id,
            rank=objective.rank or 1,
            origin=objective.origin,
            created_by_tool_call_id=objective.created_by_tool_call_id,
            payload=objective.to_record(),
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _write_objective(
        row: ObjectiveResearchRecord,
        objective: ResearchObjective,
        *,
        now: datetime,
    ) -> None:
        row.rank = objective.rank or row.rank
        row.origin = objective.origin
        row.created_by_tool_call_id = objective.created_by_tool_call_id
        row.payload = objective.to_record()
        row.updated_at = now

    @staticmethod
    def _new_analysis_row(
        analysis: ObjectiveAnalysis,
        *,
        now: datetime,
    ) -> ObjectiveAnalysisRecord:
        return ObjectiveAnalysisRecord(
            collection_id=analysis.collection_id,
            objective_id=analysis.objective_id,
            analysis_version=analysis.analysis_version,
            status=analysis.status,
            payload=analysis.to_record(),
            created_at=analysis.created_at or now,
            updated_at=now,
        )

    @staticmethod
    def _write_analysis(
        row: ObjectiveAnalysisRecord,
        analysis: ObjectiveAnalysis,
    ) -> None:
        row.status = analysis.status
        row.payload = analysis.to_record()
        row.updated_at = datetime.now(timezone.utc)

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
    async def _require_source_locator(
        session: AsyncSession,
        collection_id: str,
        evidence: ObjectiveEvidence,
    ) -> None:
        document_collection = await session.scalar(
            select(SourceDocument.collection_id).where(
                SourceDocument.source_document_id == evidence.document_id
            )
        )
        if document_collection != collection_id:
            raise FileNotFoundError(
                f"source document not found: {collection_id}/{evidence.document_id}"
            )
        model, identity = {
            "text_window": (SourceBlock, SourceBlock.block_id),
            "table": (SourceTable, SourceTable.table_id),
            "figure": (SourceFigure, SourceFigure.figure_id),
        }[evidence.source_kind]
        exists = await session.scalar(
            select(func.count()).select_from(model).where(
                model.source_document_id == evidence.document_id,
                identity == evidence.source_ref,
            )
        )
        if not exists:
            raise FileNotFoundError(
                "objective evidence source not found: "
                f"{collection_id}/{evidence.document_id}/"
                f"{evidence.source_kind}/{evidence.source_ref}"
            )


__all__ = ["PostgresObjectiveRepository"]
