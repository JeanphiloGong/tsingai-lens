"""PostgreSQL repository for the Research Objective aggregate."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from domain.core import (
    Finding,
    FindingContext,
    FindingDerivation,
    FindingRelation,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperSkim,
    ResearchObjective,
)
from infra.persistence.postgres.models.build import (
    CollectionActiveBuild,
    CollectionBuild,
)
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisRecord,
    ObjectiveBuild,
    ObjectiveEvidenceRecord,
    ObjectiveFindingContextRecord,
    ObjectiveFindingDerivationRecord,
    ObjectiveFindingRecord,
    ObjectiveFindingRelationRecord,
    ObjectivePaperContributionRecord,
    ObjectivePaperSkim,
    ObjectiveResearchRecord,
    objective_build_candidates,
    objective_document_scope,
    objective_finding_evidence_links,
    objective_finding_relation_evidence_links,
)
from infra.persistence.postgres.models.source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
)


class PostgresObjectiveRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        """Replace generated candidates for one pending collection build."""
        with self.session_factory.begin() as session:
            self._require_writable_build(session, collection_id, build_id)
            source_document_ids = self._source_document_ids(
                session, collection_id, build_id
            )
            session.execute(
                delete(ObjectiveBuild).where(ObjectiveBuild.build_id == build_id)
            )
            session.flush()
            session.add(
                ObjectiveBuild(
                    build_id=build_id,
                    collection_id=collection_id,
                    research_objectives_ready=facts.research_objectives_ready,
                )
            )
            session.add_all(
                self._skim_row(
                    collection_id,
                    build_id,
                    source_document_ids,
                    position,
                    skim,
                )
                for position, skim in enumerate(facts.paper_skims)
            )
            session.flush()

            now = datetime.now(timezone.utc)
            for position, objective in enumerate(facts.research_objectives):
                if objective.collection_id != collection_id:
                    raise ValueError("objective belongs to another collection")
                row = session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective.objective_id),
                )
                if row is None:
                    row = ObjectiveResearchRecord(
                        collection_id=collection_id,
                        objective_id=objective.objective_id,
                        question=objective.question,
                        material_scope=list(objective.material_scope),
                        process_axes=list(objective.process_axes),
                        property_axes=list(objective.property_axes),
                        comparison_intent=objective.comparison_intent,
                        confidence=objective.confidence,
                        reason=objective.reason,
                        confirmation_status=objective.confirmation_status,
                        active_analysis_version=None,
                        published_analysis_version=None,
                        created_at=objective.created_at or now,
                        updated_at=objective.updated_at or now,
                    )
                    session.add(row)
                    session.flush()
                    self._replace_document_scope(session, objective)
                elif row.confirmation_status == "candidate":
                    row.question = objective.question
                    row.material_scope = list(objective.material_scope)
                    row.process_axes = list(objective.process_axes)
                    row.property_axes = list(objective.property_axes)
                    row.comparison_intent = objective.comparison_intent
                    row.confidence = objective.confidence
                    row.reason = objective.reason
                    row.updated_at = now
                    self._replace_document_scope(session, objective)
                session.execute(
                    objective_build_candidates.insert().values(
                        build_id=build_id,
                        collection_id=collection_id,
                        objective_id=objective.objective_id,
                        objective_order=position,
                    )
                )

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ObjectiveFactSet:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return ObjectiveFactSet()
            marker = session.get(ObjectiveBuild, resolved_build_id)
            if marker is None or marker.collection_id != collection_id:
                return ObjectiveFactSet()
            scope = self._scope_by_objective(session, collection_id)
            objective_rows = session.scalars(
                select(ObjectiveResearchRecord)
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
            return ObjectiveFactSet(
                research_objectives_ready=marker.research_objectives_ready,
                paper_skims=tuple(
                    self._skim_record(row)
                    for row in session.scalars(
                        select(ObjectivePaperSkim)
                        .where(ObjectivePaperSkim.build_id == resolved_build_id)
                        .order_by(ObjectivePaperSkim.skim_order)
                    )
                ),
                research_objectives=tuple(
                    self._objective_record(row, scope.get(row.objective_id, {}))
                    for row in objective_rows
                ),
            )

    def list_objectives(self, collection_id: str) -> tuple[ResearchObjective, ...]:
        with self.session_factory() as session:
            scope = self._scope_by_objective(session, collection_id)
            return tuple(
                self._objective_record(row, scope.get(row.objective_id, {}))
                for row in session.scalars(
                    select(ObjectiveResearchRecord)
                    .where(ObjectiveResearchRecord.collection_id == collection_id)
                    .order_by(
                        ObjectiveResearchRecord.created_at,
                        ObjectiveResearchRecord.objective_id,
                    )
                )
            )

    def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        with self.session_factory() as session:
            row = session.get(ObjectiveResearchRecord, (collection_id, objective_id))
            if row is None:
                return None
            scope = self._scope_by_objective(session, collection_id).get(
                objective_id, {}
            )
            return self._objective_record(row, scope)

    def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        with self.session_factory.begin() as session:
            row = self._locked_objective(session, collection_id, objective_id)
            if row.confirmation_status == "candidate":
                row.confirmation_status = "confirmed"
                row.updated_at = datetime.now(timezone.utc)
            scope = self._scope_by_objective(session, collection_id).get(
                objective_id, {}
            )
            return self._objective_record(row, scope)

    def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        with self.session_factory.begin() as session:
            row = self._locked_objective(session, collection_id, objective_id)
            if row.confirmation_status != "confirmed":
                raise ValueError("objective must be confirmed before analysis")
            existing = session.scalar(
                select(ObjectiveAnalysisRecord).where(
                    ObjectiveAnalysisRecord.collection_id == collection_id,
                    ObjectiveAnalysisRecord.objective_id == objective_id,
                    ObjectiveAnalysisRecord.status.in_(("queued", "running")),
                )
            )
            if existing is not None:
                scope = self._scope_by_objective(session, collection_id).get(
                    objective_id, {}
                )
                return self._objective_record(row, scope), self._analysis_record(existing)
            source_build_id = self._resolve_read_build(session, collection_id, None)
            if source_build_id is None:
                raise FileNotFoundError(f"active collection build not found: {collection_id}")
            next_version = (
                session.scalar(
                    select(func.max(ObjectiveAnalysisRecord.analysis_version)).where(
                        ObjectiveAnalysisRecord.collection_id == collection_id,
                        ObjectiveAnalysisRecord.objective_id == objective_id,
                    )
                )
                or 0
            ) + 1
            total_documents = len(
                self._scope_by_objective(session, collection_id)
                .get(objective_id, {})
                .get("seed", ())
            )
            now = datetime.now(timezone.utc)
            analysis_row = ObjectiveAnalysisRecord(
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=next_version,
                source_build_id=source_build_id,
                pipeline_version=pipeline_version,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
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
            scope = self._scope_by_objective(session, collection_id).get(
                objective_id, {}
            )
            return self._objective_record(row, scope), self._analysis_record(analysis_row)

    def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None:
        with self.session_factory.begin() as session:
            row = self._locked_analysis(
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

    def update_analysis_progress(
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
        with self.session_factory.begin() as session:
            row = self._locked_analysis(
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

    def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
    ) -> ObjectiveAnalysis:
        with self.session_factory.begin() as session:
            row = self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            failed = self._analysis_record(row).fail(
                error_code=error_code,
                error_message=error_message,
                completed_at=datetime.now(timezone.utc),
            )
            self._apply_analysis(row, failed)
            return failed

    def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        with self.session_factory.begin() as session:
            objective_row = self._locked_objective(
                session, collection_id, objective_id
            )
            analysis_row = self._locked_analysis(
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
                self._require_source_locator(
                    session,
                    collection_id,
                    analysis_row.source_build_id,
                    evidence,
                )
            for finding in findings:
                finding.validate_evidence(evidence_records)

            self._delete_analysis_artifacts(
                session, collection_id, objective_id, analysis_version
            )
            session.add_all(
                self._contribution_row(analysis_row.source_build_id, item)
                for item in contributions
            )
            session.flush()
            session.add_all(
                self._evidence_row(position, item)
                for position, item in enumerate(evidence_records)
            )
            session.flush()
            for finding in findings:
                self._write_finding(session, finding)
            succeeded = self._analysis_record(analysis_row).succeed(
                completed_at=datetime.now(timezone.utc)
            )
            self._apply_analysis(analysis_row, succeeded)
            objective = self._objective_record(
                objective_row,
                self._scope_by_objective(session, collection_id).get(
                    objective_id, {}
                ),
            ).publish_analysis(succeeded)
            objective_row.published_analysis_version = analysis_version
            objective_row.updated_at = datetime.now(timezone.utc)
            return objective, succeeded

    def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None:
        with self.session_factory() as session:
            if analysis_version is None:
                objective = session.get(
                    ObjectiveResearchRecord, (collection_id, objective_id)
                )
                if objective is None or objective.active_analysis_version is None:
                    return None
                analysis_version = objective.active_analysis_version
            row = session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            return self._analysis_record(row) if row is not None else None

    def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None:
        with self.session_factory() as session:
            objective = session.get(
                ObjectiveResearchRecord, (collection_id, objective_id)
            )
            if objective is None or objective.published_analysis_version is None:
                return None
            row = session.get(
                ObjectiveAnalysisRecord,
                (
                    collection_id,
                    objective_id,
                    objective.published_analysis_version,
                ),
            )
            return self._analysis_record(row) if row is not None else None

    def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]:
        with self.session_factory() as session:
            total = session.scalar(
                select(func.count())
                .select_from(ObjectiveFindingRecord)
                .where(
                    ObjectiveFindingRecord.collection_id == collection_id,
                    ObjectiveFindingRecord.objective_id == objective_id,
                    ObjectiveFindingRecord.analysis_version == analysis_version,
                )
            ) or 0
            rows = tuple(
                session.scalars(
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
            return tuple(self._finding_record(session, row) for row in rows), total

    def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None:
        with self.session_factory() as session:
            row = session.get(
                ObjectiveFindingRecord,
                (collection_id, objective_id, analysis_version, finding_id),
            )
            return self._finding_record(session, row) if row is not None else None

    def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[ObjectiveEvidence, ...], int]:
        with self.session_factory() as session:
            evidence_ids: tuple[str, ...] | None = None
            if finding_id is not None:
                evidence_ids = tuple(
                    session.scalars(
                        select(objective_finding_evidence_links.c.evidence_id)
                        .where(
                            objective_finding_evidence_links.c.collection_id
                            == collection_id,
                            objective_finding_evidence_links.c.objective_id
                            == objective_id,
                            objective_finding_evidence_links.c.analysis_version
                            == analysis_version,
                            objective_finding_evidence_links.c.finding_id
                            == finding_id,
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
                filters = (*filters, ObjectiveEvidenceRecord.evidence_id.in_(evidence_ids))
            total = session.scalar(
                select(func.count()).select_from(ObjectiveEvidenceRecord).where(*filters)
            ) or 0
            rows = session.scalars(
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
            if (item.collection_id, item.objective_id, item.analysis_version) != expected_key:
                raise ValueError("objective analysis artifact has cross-version identity")

    @staticmethod
    def _apply_analysis(row: ObjectiveAnalysisRecord, analysis: ObjectiveAnalysis) -> None:
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
    def _delete_analysis_artifacts(
        session: Session,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> None:
        for model in (
            ObjectiveFindingRecord,
            ObjectiveEvidenceRecord,
            ObjectivePaperContributionRecord,
        ):
            session.execute(
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
            evidence_kind=item.evidence_kind,
            property_normalized=item.property_normalized,
            material_system=dict(item.material_system),
            sample_context=dict(item.sample_context),
            process_context=dict(item.process_context),
            test_condition=dict(item.test_condition),
            resolved_condition=dict(item.resolved_condition),
            value_payload=dict(item.value_payload),
            unit=item.unit,
            baseline_context=dict(item.baseline_context),
            interpretation=item.interpretation,
            join_keys=dict(item.join_keys),
            anchor_ids=list(item.anchor_ids),
            resolution_status=item.resolution_status,
            failure_reason=item.failure_reason,
            confidence=item.confidence,
        )

    def _write_finding(self, session: Session, finding: Finding) -> None:
        session.add(
            ObjectiveFindingRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                finding_level=finding.finding_level,
                statement=finding.statement,
                variables=list(finding.variables),
                mediators=list(finding.mediators),
                outcomes=list(finding.outcomes),
                direction=finding.direction,
                scope_summary=finding.scope_summary,
                evidence_strength=finding.evidence_strength,
                generalization_status=finding.generalization_status,
                paper_count=finding.paper_count,
                confidence=finding.confidence,
                display_rank=finding.display_rank,
            )
        )
        session.flush()
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
            for position, relation in enumerate(finding.relations)
        )
        session.add(
            ObjectiveFindingContextRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                material_system=dict(finding.context.material_system),
                process_conditions=[
                    dict(value) for value in finding.context.process_conditions
                ],
                sample_state=dict(finding.context.sample_state),
                test_conditions=[
                    dict(value) for value in finding.context.test_conditions
                ],
                comparison_baseline=dict(finding.context.comparison_baseline),
                limitations=list(finding.context.limitations),
            )
        )
        session.add(
            ObjectiveFindingDerivationRecord(
                collection_id=finding.collection_id,
                objective_id=finding.objective_id,
                analysis_version=finding.analysis_version,
                finding_id=finding.finding_id,
                synthesis_mode=finding.derivation.synthesis_mode,
                comparison_status=finding.derivation.comparison_status,
                contributing_document_ids=list(
                    finding.derivation.contributing_document_ids
                ),
                rationale=finding.derivation.rationale,
            )
        )
        session.flush()
        for link_role, evidence_ids in (
            ("supporting", finding.derivation.supporting_evidence_ids),
            ("contradicting", finding.derivation.contradicting_evidence_ids),
            ("context", finding.context.supporting_evidence_ids),
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
                session.execute(objective_finding_evidence_links.insert(), rows)
        for relation_order, relation in enumerate(finding.relations):
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
                for position, evidence_id in enumerate(
                    relation.supporting_evidence_ids
                )
            ]
            if rows:
                session.execute(
                    objective_finding_relation_evidence_links.insert(), rows
                )

    def _finding_record(
        self,
        session: Session,
        row: ObjectiveFindingRecord,
    ) -> Finding:
        key_filters = (
            row.collection_id,
            row.objective_id,
            row.analysis_version,
            row.finding_id,
        )
        relation_rows = tuple(
            session.scalars(
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
        for link in session.execute(
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
        ).mappings():
            relation_links[int(link["relation_order"])].append(str(link["evidence_id"]))
        evidence_links: dict[str, list[str]] = defaultdict(list)
        for link in session.execute(
            select(objective_finding_evidence_links)
            .where(
                objective_finding_evidence_links.c.collection_id == key_filters[0],
                objective_finding_evidence_links.c.objective_id == key_filters[1],
                objective_finding_evidence_links.c.analysis_version == key_filters[2],
                objective_finding_evidence_links.c.finding_id == key_filters[3],
            )
            .order_by(
                objective_finding_evidence_links.c.link_role,
                objective_finding_evidence_links.c.position,
            )
        ).mappings():
            evidence_links[str(link["link_role"])].append(str(link["evidence_id"]))
        context_row = session.get(ObjectiveFindingContextRecord, key_filters)
        derivation_row = session.get(ObjectiveFindingDerivationRecord, key_filters)
        if context_row is None or derivation_row is None:
            raise RuntimeError(f"incomplete persisted finding: {row.finding_id}")
        return Finding(
            collection_id=row.collection_id,
            objective_id=row.objective_id,
            analysis_version=row.analysis_version,
            finding_id=row.finding_id,
            finding_level=row.finding_level,
            statement=row.statement,
            variables=tuple(row.variables),
            mediators=tuple(row.mediators),
            outcomes=tuple(row.outcomes),
            direction=row.direction,
            scope_summary=row.scope_summary,
            evidence_strength=row.evidence_strength,
            generalization_status=row.generalization_status,
            paper_count=row.paper_count,
            confidence=row.confidence,
            display_rank=row.display_rank,
            relations=tuple(
                FindingRelation(
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
            context=FindingContext(
                material_system=dict(context_row.material_system),
                process_conditions=tuple(
                    dict(value) for value in context_row.process_conditions
                ),
                sample_state=dict(context_row.sample_state),
                test_conditions=tuple(
                    dict(value) for value in context_row.test_conditions
                ),
                comparison_baseline=dict(context_row.comparison_baseline),
                limitations=tuple(context_row.limitations),
                supporting_evidence_ids=tuple(evidence_links.get("context", ())),
            ),
            derivation=FindingDerivation(
                synthesis_mode=derivation_row.synthesis_mode,
                comparison_status=derivation_row.comparison_status,
                contributing_document_ids=tuple(
                    derivation_row.contributing_document_ids
                ),
                supporting_evidence_ids=tuple(
                    evidence_links.get("supporting", ())
                ),
                contradicting_evidence_ids=tuple(
                    evidence_links.get("contradicting", ())
                ),
                rationale=derivation_row.rationale,
            ),
        )

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
            related_source_refs=tuple(
                dict(value) for value in row.related_source_refs
            ),
            evidence_role=row.evidence_role,
            selection_status=row.selection_status,
            selection_reason=row.selection_reason,
            evidence_kind=row.evidence_kind,
            property_normalized=row.property_normalized,
            material_system=dict(row.material_system),
            sample_context=dict(row.sample_context),
            process_context=dict(row.process_context),
            test_condition=dict(row.test_condition),
            resolved_condition=dict(row.resolved_condition),
            value_payload=dict(row.value_payload),
            unit=row.unit,
            baseline_context=dict(row.baseline_context),
            interpretation=row.interpretation,
            join_keys=dict(row.join_keys),
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
    def _objective_record(
        row: ObjectiveResearchRecord,
        scope: dict[str, tuple[str, ...]],
    ) -> ResearchObjective:
        return ResearchObjective(
            collection_id=row.collection_id,
            objective_id=row.objective_id,
            question=row.question,
            material_scope=tuple(row.material_scope),
            process_axes=tuple(row.process_axes),
            property_axes=tuple(row.property_axes),
            comparison_intent=row.comparison_intent,
            seed_document_ids=tuple(scope.get("seed", ())),
            excluded_document_ids=tuple(scope.get("excluded", ())),
            confidence=row.confidence,
            reason=row.reason,
            confirmation_status=row.confirmation_status,
            active_analysis_version=row.active_analysis_version,
            published_analysis_version=row.published_analysis_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _skim_record(row: ObjectivePaperSkim) -> PaperSkim:
        return PaperSkim(
            document_id=row.source_document_id,
            title=row.title,
            source_filename=row.source_filename,
            doc_role=row.doc_role,
            candidate_materials=tuple(row.candidate_materials),
            candidate_processes=tuple(row.candidate_processes),
            candidate_properties=tuple(row.candidate_properties),
            changed_variables=tuple(row.changed_variables),
            possible_objectives=tuple(row.possible_objectives),
            evidence_density=row.evidence_density,
            confidence=row.confidence,
            warnings=tuple(row.warnings),
        )

    @classmethod
    def _skim_row(
        cls,
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        skim: PaperSkim,
    ) -> ObjectivePaperSkim:
        cls._require_source_document(
            source_document_ids, collection_id, skim.document_id
        )
        return ObjectivePaperSkim(
            build_id=build_id,
            source_document_id=skim.document_id,
            collection_id=collection_id,
            skim_order=position,
            title=skim.title,
            source_filename=skim.source_filename,
            doc_role=skim.doc_role,
            candidate_materials=list(skim.candidate_materials),
            candidate_processes=list(skim.candidate_processes),
            candidate_properties=list(skim.candidate_properties),
            changed_variables=list(skim.changed_variables),
            possible_objectives=list(skim.possible_objectives),
            evidence_density=skim.evidence_density,
            confidence=skim.confidence,
            warnings=list(skim.warnings),
        )

    @staticmethod
    def _replace_document_scope(
        session: Session,
        objective: ResearchObjective,
    ) -> None:
        session.execute(
            delete(objective_document_scope).where(
                objective_document_scope.c.collection_id == objective.collection_id,
                objective_document_scope.c.objective_id == objective.objective_id,
            )
        )
        for scope_kind, document_ids in (
            ("seed", objective.seed_document_ids),
            ("excluded", objective.excluded_document_ids),
        ):
            rows = [
                {
                    "collection_id": objective.collection_id,
                    "objective_id": objective.objective_id,
                    "scope_kind": scope_kind,
                    "source_document_id": document_id,
                    "position": position,
                }
                for position, document_id in enumerate(document_ids)
            ]
            if rows:
                session.execute(objective_document_scope.insert(), rows)

    @staticmethod
    def _scope_by_objective(
        session: Session,
        collection_id: str,
    ) -> dict[str, dict[str, tuple[str, ...]]]:
        grouped: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in session.execute(
            select(objective_document_scope)
            .where(objective_document_scope.c.collection_id == collection_id)
            .order_by(
                objective_document_scope.c.objective_id,
                objective_document_scope.c.scope_kind,
                objective_document_scope.c.position,
            )
        ).mappings():
            grouped[str(row["objective_id"])][str(row["scope_kind"])].append(
                str(row["source_document_id"])
            )
        return {
            objective_id: {
                scope_kind: tuple(document_ids)
                for scope_kind, document_ids in scope.items()
            }
            for objective_id, scope in grouped.items()
        }

    @staticmethod
    def _require_source_locator(
        session: Session,
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
        exists = session.scalar(
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
    def _locked_objective(
        session: Session,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveResearchRecord:
        row = session.scalar(
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
    def _locked_analysis(
        session: Session,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysisRecord:
        row = session.scalar(
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
    def _source_document_ids(
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> set[str]:
        return set(
            session.scalars(
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
    def _require_build(
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = session.get(CollectionBuild, build_id)
        if build is None or build.collection_id != collection_id:
            raise FileNotFoundError(
                f"collection build not found: {collection_id}/{build_id}"
            )
        return build

    @classmethod
    def _require_writable_build(
        cls,
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = cls._require_build(session, collection_id, build_id)
        if build.status not in {"queued", "building"}:
            raise ValueError(f"collection build is not writable: {build_id}")
        return build

    @classmethod
    def _resolve_read_build(
        cls,
        session: Session,
        collection_id: str,
        build_id: str | None,
    ) -> str | None:
        if build_id is not None:
            cls._require_build(session, collection_id, build_id)
            return build_id
        return session.scalar(
            select(CollectionActiveBuild.build_id).where(
                CollectionActiveBuild.collection_id == collection_id
            )
        )


__all__ = ["PostgresObjectiveRepository"]
