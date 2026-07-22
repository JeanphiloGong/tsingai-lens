"""Direct SQLAlchemy repository for build-versioned objective evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from domain.core import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveFactSet,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
    require_objective_status_transition,
)
from infra.persistence.postgres.models.build import (
    CollectionActiveBuild,
    CollectionBuild,
)
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.objective import (
    ObjectiveBuild,
    ObjectiveContextRecord,
    ObjectiveEvidenceRouteRecord,
    ObjectiveEvidenceUnitRecord,
    ObjectiveLogicChainRecord,
    ObjectivePaperFrameRecord,
    ObjectivePaperSkim,
    ObjectiveResearchRecord,
    ResearchObjectiveLifecycle,
    objective_document_links,
    objective_frame_table_links,
    objective_logic_chain_unit_links,
    objective_unit_anchor_links,
    objective_unit_source_refs,
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
        with self.session_factory.begin() as session:
            self._require_writable_build(session, collection_id, build_id)
            source_document_ids = self._source_document_ids(
                session, collection_id, build_id
            )

            for link_table in (
                objective_logic_chain_unit_links,
                objective_unit_anchor_links,
                objective_unit_source_refs,
                objective_frame_table_links,
                objective_document_links,
            ):
                session.execute(
                    delete(link_table).where(link_table.c.build_id == build_id)
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
            session.flush()

            session.add_all(
                self._skim_row(
                    collection_id, build_id, source_document_ids, position, item
                )
                for position, item in enumerate(facts.paper_skims)
            )
            session.add_all(
                ObjectiveResearchRecord(
                    build_id=build_id,
                    objective_id=item.objective_id,
                    collection_id=collection_id,
                    objective_order=position,
                    question=item.question,
                    material_scope=list(item.material_scope),
                    process_axes=list(item.process_axes),
                    property_axes=list(item.property_axes),
                    comparison_intent=item.comparison_intent,
                    confidence=item.confidence,
                    reason=item.reason,
                )
                for position, item in enumerate(facts.research_objectives)
            )
            session.flush()

            session.add_all(
                ObjectiveContextRecord(
                    build_id=build_id,
                    objective_id=item.objective_id,
                    collection_id=collection_id,
                    context_order=position,
                    question=item.question,
                    material_scope=list(item.material_scope),
                    variable_process_axes=list(item.variable_process_axes),
                    process_context_axes=list(item.process_context_axes),
                    target_property_axes=list(item.target_property_axes),
                    excluded_property_axes=list(item.excluded_property_axes),
                    objective_evidence_lens=dict(item.objective_evidence_lens),
                    routing_hints=[dict(value) for value in item.routing_hints],
                    extraction_guidance=dict(item.extraction_guidance),
                    confidence=item.confidence,
                )
                for position, item in enumerate(facts.objective_contexts)
            )
            session.add_all(
                self._frame_row(
                    collection_id, build_id, source_document_ids, position, item
                )
                for position, item in enumerate(facts.objective_paper_frames)
            )
            session.add_all(
                self._route_row(
                    session,
                    collection_id,
                    build_id,
                    source_document_ids,
                    position,
                    item,
                )
                for position, item in enumerate(facts.objective_evidence_routes)
            )
            session.add_all(
                self._unit_row(
                    collection_id, build_id, source_document_ids, position, item
                )
                for position, item in enumerate(facts.objective_evidence_units)
            )
            session.add_all(
                self._chain_row(
                    collection_id, build_id, source_document_ids, position, item
                )
                for position, item in enumerate(facts.objective_logic_chains)
            )
            session.flush()

            self._write_links(session, collection_id, build_id, facts)

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

            document_links = self._read_grouped_links(
                session,
                objective_document_links,
                resolved_build_id,
                ("objective_id", "link_kind"),
                "source_document_id",
            )
            frame_tables = self._read_grouped_links(
                session,
                objective_frame_table_links,
                resolved_build_id,
                ("frame_id", "link_kind"),
                "table_id",
            )
            unit_anchors = self._read_grouped_links(
                session,
                objective_unit_anchor_links,
                resolved_build_id,
                ("evidence_unit_id",),
                "anchor_id",
            )
            chain_units = self._read_grouped_links(
                session,
                objective_logic_chain_unit_links,
                resolved_build_id,
                ("logic_chain_id",),
                "evidence_unit_id",
            )
            source_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in session.execute(
                select(objective_unit_source_refs)
                .where(objective_unit_source_refs.c.build_id == resolved_build_id)
                .order_by(
                    objective_unit_source_refs.c.evidence_unit_id,
                    objective_unit_source_refs.c.position,
                )
            ).mappings():
                source_ref = dict(row["metadata_json"])
                source_ref.update(
                    {
                        "source_kind": str(row["source_kind"]),
                        "source_ref": str(row["source_ref"]),
                    }
                )
                source_refs[str(row["evidence_unit_id"])].append(source_ref)

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
                    self._objective_record(row, document_links)
                    for row in session.scalars(
                        select(ObjectiveResearchRecord)
                        .where(ObjectiveResearchRecord.build_id == resolved_build_id)
                        .order_by(ObjectiveResearchRecord.objective_order)
                    )
                ),
                objective_contexts=tuple(
                    self._context_record(row)
                    for row in session.scalars(
                        select(ObjectiveContextRecord)
                        .where(ObjectiveContextRecord.build_id == resolved_build_id)
                        .order_by(ObjectiveContextRecord.context_order)
                    )
                ),
                objective_paper_frames=tuple(
                    self._frame_record(row, frame_tables)
                    for row in session.scalars(
                        select(ObjectivePaperFrameRecord)
                        .where(ObjectivePaperFrameRecord.build_id == resolved_build_id)
                        .order_by(ObjectivePaperFrameRecord.frame_order)
                    )
                ),
                objective_evidence_routes=tuple(
                    self._route_record(row)
                    for row in session.scalars(
                        select(ObjectiveEvidenceRouteRecord)
                        .where(
                            ObjectiveEvidenceRouteRecord.build_id == resolved_build_id
                        )
                        .order_by(ObjectiveEvidenceRouteRecord.route_order)
                    )
                ),
                objective_evidence_units=tuple(
                    self._unit_record(row, source_refs, unit_anchors)
                    for row in session.scalars(
                        select(ObjectiveEvidenceUnitRecord)
                        .where(
                            ObjectiveEvidenceUnitRecord.build_id == resolved_build_id
                        )
                        .order_by(ObjectiveEvidenceUnitRecord.unit_order)
                    )
                ),
                objective_logic_chains=tuple(
                    self._chain_record(row, chain_units)
                    for row in session.scalars(
                        select(ObjectiveLogicChainRecord)
                        .where(ObjectiveLogicChainRecord.build_id == resolved_build_id)
                        .order_by(ObjectiveLogicChainRecord.chain_order)
                    )
                ),
            )

    def list_objective_workspaces(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        with self.session_factory() as session:
            active_build_id = self._resolve_read_build(session, collection_id, None)
            lifecycle_rows = tuple(
                session.scalars(
                    select(ResearchObjectiveLifecycle)
                    .where(ResearchObjectiveLifecycle.collection_id == collection_id)
                    .order_by(
                        ResearchObjectiveLifecycle.created_at,
                        ResearchObjectiveLifecycle.objective_id,
                    )
                )
            )

        active_objectives = (
            self.read(collection_id, build_id=active_build_id).research_objectives
            if active_build_id is not None
            else ()
        )
        lifecycles_by_id = {row.objective_id: row for row in lifecycle_rows}
        workspaces: list[ResearchObjective] = []
        seen: set[str] = set()
        for objective in active_objectives:
            lifecycle = lifecycles_by_id.get(objective.objective_id)
            if lifecycle is None:
                workspaces.append(
                    self._with_workspace(objective, source_build_id=active_build_id)
                )
            else:
                workspaces.append(self._objective_for_lifecycle(collection_id, lifecycle))
            seen.add(objective.objective_id)
        workspaces.extend(
            self._objective_for_lifecycle(collection_id, lifecycle)
            for lifecycle in lifecycle_rows
            if lifecycle.objective_id not in seen
        )
        return tuple(workspaces)

    def read_objective_workspace(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        with self.session_factory() as session:
            lifecycle = session.get(
                ResearchObjectiveLifecycle,
                (collection_id, objective_id),
            )
            active_build_id = (
                None
                if lifecycle is not None
                else self._resolve_read_build(session, collection_id, None)
            )
        if lifecycle is not None:
            return self._objective_for_lifecycle(collection_id, lifecycle)
        if active_build_id is None:
            return None
        objective = self._objective_for_build(
            collection_id,
            active_build_id,
            objective_id,
        )
        return (
            self._with_workspace(objective, source_build_id=active_build_id)
            if objective is not None
            else None
        )

    def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        with self.session_factory.begin() as session:
            collection = session.scalar(
                select(Collection)
                .where(Collection.collection_id == collection_id)
                .with_for_update()
            )
            if collection is None:
                raise FileNotFoundError(
                    f"research objective not found: {collection_id}/{objective_id}"
                )
            lifecycle = session.get(
                ResearchObjectiveLifecycle,
                (collection_id, objective_id),
            )
            if lifecycle is None:
                active = session.get(CollectionActiveBuild, collection_id)
                if active is None:
                    raise FileNotFoundError(
                        f"research objective not found: {collection_id}/{objective_id}"
                    )
                objective = session.get(
                    ObjectiveResearchRecord,
                    (active.build_id, objective_id),
                )
                if objective is None or objective.collection_id != collection_id:
                    raise FileNotFoundError(
                        f"research objective not found: {collection_id}/{objective_id}"
                    )
                require_objective_status_transition("candidate", "confirmed")
                now = datetime.now(timezone.utc)
                session.add(
                    ResearchObjectiveLifecycle(
                        collection_id=collection_id,
                        objective_id=objective_id,
                        source_build_id=active.build_id,
                        status="confirmed",
                        analysis_error=None,
                        analysis_progress=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return self._require_objective_workspace(collection_id, objective_id)

    def queue_objective_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        with self.session_factory.begin() as session:
            lifecycle = self._locked_lifecycle(session, collection_id, objective_id)
            if lifecycle is None:
                candidate = self.read_objective_workspace(collection_id, objective_id)
                if candidate is None:
                    raise FileNotFoundError(
                        f"research objective not found: {collection_id}/{objective_id}"
                    )
                require_objective_status_transition("candidate", "queued")
            elif lifecycle.status not in {"queued", "running"}:
                require_objective_status_transition(lifecycle.status, "queued")
                lifecycle.status = "queued"
                lifecycle.analysis_error = None
                lifecycle.analysis_progress = {
                    "phase": "queued",
                    "unit": "steps",
                    "message": "Objective analysis is queued.",
                }
                lifecycle.updated_at = datetime.now(timezone.utc)
        return self._require_objective_workspace(collection_id, objective_id)

    def claim_objective_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        claimed = False
        with self.session_factory.begin() as session:
            lifecycle = self._locked_lifecycle(session, collection_id, objective_id)
            if lifecycle is None:
                raise FileNotFoundError(
                    f"research objective not found: {collection_id}/{objective_id}"
                )
            if lifecycle.status == "queued":
                require_objective_status_transition("queued", "running")
                lifecycle.status = "running"
                lifecycle.analysis_error = None
                lifecycle.analysis_progress = {
                    "phase": "objective_analysis_started",
                    "unit": "steps",
                    "message": "Objective analysis has started.",
                }
                lifecycle.updated_at = datetime.now(timezone.utc)
                claimed = True
        return (
            self._require_objective_workspace(collection_id, objective_id)
            if claimed
            else None
        )

    def update_objective_analysis_progress(
        self,
        collection_id: str,
        objective_id: str,
        analysis_progress: dict[str, Any],
    ) -> ResearchObjective:
        with self.session_factory.begin() as session:
            lifecycle = self._require_locked_lifecycle(
                session, collection_id, objective_id
            )
            if lifecycle.status != "running":
                raise ValueError(
                    f"objective analysis is not running: {lifecycle.status}"
                )
            lifecycle.analysis_progress = dict(analysis_progress)
            lifecycle.updated_at = datetime.now(timezone.utc)
        return self._require_objective_workspace(collection_id, objective_id)

    def mark_objective_analysis_ready(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        with self.session_factory.begin() as session:
            lifecycle = self._require_locked_lifecycle(
                session, collection_id, objective_id
            )
            require_objective_status_transition(lifecycle.status, "ready")
            lifecycle.status = "ready"
            lifecycle.analysis_error = None
            lifecycle.analysis_progress = {
                "phase": "completed",
                "unit": "steps",
                "message": "Objective analysis is ready.",
            }
            lifecycle.updated_at = datetime.now(timezone.utc)
        return self._require_objective_workspace(collection_id, objective_id)

    def mark_objective_analysis_failed(
        self,
        collection_id: str,
        objective_id: str,
        analysis_error: str,
    ) -> ResearchObjective:
        with self.session_factory.begin() as session:
            lifecycle = self._require_locked_lifecycle(
                session, collection_id, objective_id
            )
            require_objective_status_transition(lifecycle.status, "failed")
            lifecycle.status = "failed"
            lifecycle.analysis_error = str(analysis_error)
            lifecycle.analysis_progress = {
                "phase": "failed",
                "unit": "steps",
                "message": "Objective analysis failed.",
            }
            lifecycle.updated_at = datetime.now(timezone.utc)
        return self._require_objective_workspace(collection_id, objective_id)

    @staticmethod
    def _skim_row(
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        item: PaperSkim,
    ) -> ObjectivePaperSkim:
        PostgresObjectiveRepository._require_source_document(
            source_document_ids, collection_id, item.document_id
        )
        return ObjectivePaperSkim(
            build_id=build_id,
            source_document_id=item.document_id,
            collection_id=collection_id,
            skim_order=position,
            title=item.title,
            source_filename=item.source_filename,
            doc_role=item.doc_role,
            candidate_materials=list(item.candidate_materials),
            candidate_processes=list(item.candidate_processes),
            candidate_properties=list(item.candidate_properties),
            changed_variables=list(item.changed_variables),
            possible_objectives=list(item.possible_objectives),
            evidence_density=item.evidence_density,
            confidence=item.confidence,
            warnings=list(item.warnings),
        )

    @staticmethod
    def _frame_row(
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        item: ObjectivePaperFrame,
    ) -> ObjectivePaperFrameRecord:
        PostgresObjectiveRepository._require_source_document(
            source_document_ids, collection_id, item.document_id
        )
        return ObjectivePaperFrameRecord(
            build_id=build_id,
            frame_id=item.frame_id,
            collection_id=collection_id,
            objective_id=item.objective_id,
            source_document_id=item.document_id,
            frame_order=position,
            relevance=item.relevance,
            paper_role=item.paper_role,
            background=item.background,
            material_match=list(item.material_match),
            changed_variables=list(item.changed_variables),
            measured_property_scope=list(item.measured_property_scope),
            test_environment_scope=list(item.test_environment_scope),
            relevant_sections=list(item.relevant_sections),
        )

    @classmethod
    def _route_row(
        cls,
        session: Session,
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        item: ObjectiveEvidenceRoute,
    ) -> ObjectiveEvidenceRouteRecord:
        cls._require_source_document(
            source_document_ids, collection_id, item.document_id
        )
        typed_ids = cls._typed_source_ids(
            session,
            collection_id,
            build_id,
            item.document_id,
            item.source_kind,
            item.source_ref,
        )
        return ObjectiveEvidenceRouteRecord(
            build_id=build_id,
            route_id=item.route_id,
            collection_id=collection_id,
            objective_id=item.objective_id,
            source_document_id=item.document_id,
            route_order=position,
            source_kind=item.source_kind,
            source_ref=item.source_ref,
            **typed_ids,
            role=item.role,
            extractable=item.extractable,
            reason=item.reason,
            table_schema=dict(item.table_schema),
            column_roles=dict(item.column_roles),
            join_keys=dict(item.join_keys),
            join_plan=dict(item.join_plan),
            confidence=item.confidence,
        )

    @staticmethod
    def _unit_row(
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        item: ObjectiveEvidenceUnit,
    ) -> ObjectiveEvidenceUnitRecord:
        PostgresObjectiveRepository._require_source_document(
            source_document_ids, collection_id, item.document_id
        )
        return ObjectiveEvidenceUnitRecord(
            build_id=build_id,
            evidence_unit_id=item.evidence_unit_id,
            collection_id=collection_id,
            objective_id=item.objective_id,
            source_document_id=item.document_id,
            unit_order=position,
            unit_kind=item.unit_kind,
            source_kind=item.source_kind,
            source_ref=item.source_ref,
            evidence_role=item.evidence_role,
            selection_reason=item.selection_reason,
            selection_status=item.selection_status,
            property_normalized=item.property_normalized,
            material_system=dict(item.material_system),
            sample_context=dict(item.sample_context),
            process_context=dict(item.process_context),
            resolved_condition=dict(item.resolved_condition),
            test_condition=dict(item.test_condition),
            value_payload=dict(item.value_payload),
            unit=item.unit,
            baseline_context=dict(item.baseline_context),
            interpretation=item.interpretation,
            join_keys=dict(item.join_keys),
            resolution_status=item.resolution_status,
            confidence=item.confidence,
        )

    @staticmethod
    def _chain_row(
        collection_id: str,
        build_id: str,
        source_document_ids: set[str],
        position: int,
        item: ObjectiveLogicChain,
    ) -> ObjectiveLogicChainRecord:
        if item.document_id:
            PostgresObjectiveRepository._require_source_document(
                source_document_ids, collection_id, item.document_id
            )
        return ObjectiveLogicChainRecord(
            build_id=build_id,
            logic_chain_id=item.logic_chain_id,
            collection_id=collection_id,
            objective_id=item.objective_id,
            chain_order=position,
            chain_scope=item.chain_scope,
            source_document_id=item.document_id,
            question=item.question,
            chain_payload=dict(item.chain_payload),
            summary=item.summary,
            confidence=item.confidence,
        )

    @classmethod
    def _write_links(
        cls,
        session: Session,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        document_rows = [
            {
                "build_id": build_id,
                "objective_id": objective.objective_id,
                "link_kind": link_kind,
                "source_document_id": document_id,
                "collection_id": collection_id,
                "position": position,
            }
            for objective in facts.research_objectives
            for link_kind, document_ids in (
                ("seed", objective.seed_document_ids),
                ("excluded", objective.excluded_document_ids),
            )
            for position, document_id in enumerate(document_ids)
        ]
        if document_rows:
            session.execute(objective_document_links.insert(), document_rows)
        frame_table_rows = [
            {
                "build_id": build_id,
                "frame_id": frame.frame_id,
                "link_kind": link_kind,
                "table_id": table_id,
                "collection_id": collection_id,
                "source_document_id": frame.document_id,
                "position": position,
            }
            for frame in facts.objective_paper_frames
            for link_kind, table_ids in (
                ("relevant", frame.relevant_tables),
                ("excluded", frame.excluded_tables),
            )
            for position, table_id in enumerate(table_ids)
        ]
        if frame_table_rows:
            session.execute(objective_frame_table_links.insert(), frame_table_rows)
        source_ref_rows: list[dict[str, Any]] = []
        for unit in facts.objective_evidence_units:
            for position, source_ref in enumerate(unit.source_refs):
                source_kind = str(source_ref.get("source_kind") or "")
                source_ref_id = str(source_ref.get("source_ref") or "")
                source_ref_rows.append(
                    {
                        "build_id": build_id,
                        "evidence_unit_id": unit.evidence_unit_id,
                        "position": position,
                        "collection_id": collection_id,
                        "source_document_id": unit.document_id,
                        "source_kind": source_kind,
                        "source_ref": source_ref_id,
                        **cls._typed_source_ids(
                            session,
                            collection_id,
                            build_id,
                            unit.document_id,
                            source_kind,
                            source_ref_id,
                        ),
                        "metadata_json": dict(source_ref),
                    }
                )
        if source_ref_rows:
            session.execute(objective_unit_source_refs.insert(), source_ref_rows)
        anchor_rows = [
            {
                "build_id": build_id,
                "evidence_unit_id": unit.evidence_unit_id,
                "anchor_id": anchor_id,
                "collection_id": collection_id,
                "position": position,
            }
            for unit in facts.objective_evidence_units
            for position, anchor_id in enumerate(unit.evidence_anchor_ids)
        ]
        if anchor_rows:
            session.execute(objective_unit_anchor_links.insert(), anchor_rows)
        chain_unit_rows = [
            {
                "build_id": build_id,
                "logic_chain_id": chain.logic_chain_id,
                "evidence_unit_id": unit_id,
                "collection_id": collection_id,
                "position": position,
            }
            for chain in facts.objective_logic_chains
            for position, unit_id in enumerate(chain.evidence_unit_ids)
        ]
        if chain_unit_rows:
            session.execute(objective_logic_chain_unit_links.insert(), chain_unit_rows)

    @staticmethod
    def _skim_record(row: ObjectivePaperSkim) -> PaperSkim:
        return PaperSkim.from_mapping(
            {
                "document_id": row.source_document_id,
                "title": row.title,
                "source_filename": row.source_filename,
                "doc_role": row.doc_role,
                "candidate_materials": row.candidate_materials,
                "candidate_processes": row.candidate_processes,
                "candidate_properties": row.candidate_properties,
                "changed_variables": row.changed_variables,
                "possible_objectives": row.possible_objectives,
                "evidence_density": row.evidence_density,
                "confidence": row.confidence,
                "warnings": row.warnings,
            }
        )

    @staticmethod
    def _objective_record(
        row: ObjectiveResearchRecord,
        links: dict[tuple[str, ...], tuple[str, ...]],
    ) -> ResearchObjective:
        return ResearchObjective.from_mapping(
            {
                "objective_id": row.objective_id,
                "question": row.question,
                "material_scope": row.material_scope,
                "process_axes": row.process_axes,
                "property_axes": row.property_axes,
                "comparison_intent": row.comparison_intent,
                "seed_document_ids": links.get((row.objective_id, "seed"), ()),
                "excluded_document_ids": links.get((row.objective_id, "excluded"), ()),
                "confidence": row.confidence,
                "reason": row.reason,
            }
        )

    @staticmethod
    def _context_record(row: ObjectiveContextRecord) -> ObjectiveContext:
        return ObjectiveContext.from_mapping(
            {
                "objective_id": row.objective_id,
                "question": row.question,
                "material_scope": row.material_scope,
                "variable_process_axes": row.variable_process_axes,
                "process_context_axes": row.process_context_axes,
                "target_property_axes": row.target_property_axes,
                "excluded_property_axes": row.excluded_property_axes,
                "objective_evidence_lens": row.objective_evidence_lens,
                "routing_hints": row.routing_hints,
                "extraction_guidance": row.extraction_guidance,
                "confidence": row.confidence,
            }
        )

    @staticmethod
    def _frame_record(
        row: ObjectivePaperFrameRecord,
        links: dict[tuple[str, ...], tuple[str, ...]],
    ) -> ObjectivePaperFrame:
        return ObjectivePaperFrame.from_mapping(
            {
                "frame_id": row.frame_id,
                "objective_id": row.objective_id,
                "document_id": row.source_document_id,
                "relevance": row.relevance,
                "paper_role": row.paper_role,
                "background": row.background,
                "material_match": row.material_match,
                "changed_variables": row.changed_variables,
                "measured_property_scope": row.measured_property_scope,
                "test_environment_scope": row.test_environment_scope,
                "relevant_sections": row.relevant_sections,
                "relevant_tables": links.get((row.frame_id, "relevant"), ()),
                "excluded_tables": links.get((row.frame_id, "excluded"), ()),
            }
        )

    @staticmethod
    def _route_record(row: ObjectiveEvidenceRouteRecord) -> ObjectiveEvidenceRoute:
        return ObjectiveEvidenceRoute.from_mapping(
            {
                "route_id": row.route_id,
                "objective_id": row.objective_id,
                "document_id": row.source_document_id,
                "source_kind": row.source_kind,
                "source_ref": row.source_ref,
                "role": row.role,
                "extractable": row.extractable,
                "reason": row.reason,
                "table_schema": row.table_schema,
                "column_roles": row.column_roles,
                "join_keys": row.join_keys,
                "join_plan": row.join_plan,
                "confidence": row.confidence,
            }
        )

    @staticmethod
    def _unit_record(
        row: ObjectiveEvidenceUnitRecord,
        source_refs: dict[str, list[dict[str, Any]]],
        anchors: dict[tuple[str, ...], tuple[str, ...]],
    ) -> ObjectiveEvidenceUnit:
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": row.evidence_unit_id,
                "objective_id": row.objective_id,
                "document_id": row.source_document_id,
                "unit_kind": row.unit_kind,
                "source_kind": row.source_kind,
                "source_ref": row.source_ref,
                "evidence_role": row.evidence_role,
                "selection_reason": row.selection_reason,
                "selection_status": row.selection_status,
                "property_normalized": row.property_normalized,
                "material_system": row.material_system,
                "sample_context": row.sample_context,
                "process_context": row.process_context,
                "resolved_condition": row.resolved_condition,
                "test_condition": row.test_condition,
                "value_payload": row.value_payload,
                "unit": row.unit,
                "baseline_context": row.baseline_context,
                "interpretation": row.interpretation,
                "source_refs": source_refs.get(row.evidence_unit_id, ()),
                "evidence_anchor_ids": anchors.get((row.evidence_unit_id,), ()),
                "join_keys": row.join_keys,
                "resolution_status": row.resolution_status,
                "confidence": row.confidence,
            }
        )

    @staticmethod
    def _chain_record(
        row: ObjectiveLogicChainRecord,
        links: dict[tuple[str, ...], tuple[str, ...]],
    ) -> ObjectiveLogicChain:
        return ObjectiveLogicChain.from_mapping(
            {
                "logic_chain_id": row.logic_chain_id,
                "objective_id": row.objective_id,
                "chain_scope": row.chain_scope,
                "document_id": row.source_document_id,
                "question": row.question,
                "evidence_unit_ids": links.get((row.logic_chain_id,), ()),
                "chain_payload": row.chain_payload,
                "summary": row.summary,
                "confidence": row.confidence,
            }
        )

    @staticmethod
    def _read_grouped_links(
        session: Session,
        table,
        build_id: str,
        key_columns: tuple[str, ...],
        value_column: str,
    ) -> dict[tuple[str, ...], tuple[str, ...]]:
        grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
        rows = session.execute(
            select(table)
            .where(table.c.build_id == build_id)
            .order_by(
                *(getattr(table.c, name) for name in key_columns), table.c.position
            )
        ).mappings()
        for row in rows:
            key = tuple(str(row[name]) for name in key_columns)
            grouped[key].append(str(row[value_column]))
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    def _typed_source_ids(
        session: Session,
        collection_id: str,
        build_id: str,
        document_id: str,
        source_kind: str,
        source_ref: str,
    ) -> dict[str, str | None]:
        model_and_field = {
            "text_window": (SourceBlock, SourceBlock.block_id),
            "table": (SourceTable, SourceTable.table_id),
            "figure": (SourceFigure, SourceFigure.figure_id),
        }.get(source_kind)
        if model_and_field is None:
            raise ValueError(f"unsupported objective source kind: {source_kind}")
        model, field = model_and_field
        found = session.scalar(
            select(field).where(
                model.collection_id == collection_id,
                model.build_id == build_id,
                model.source_document_id == document_id,
                field == source_ref,
            )
        )
        if found is None:
            raise FileNotFoundError(
                "objective source not found: "
                f"{collection_id}/{build_id}/{document_id}/{source_kind}/{source_ref}"
            )
        return {
            "source_block_id": source_ref if source_kind == "text_window" else None,
            "source_table_id": source_ref if source_kind == "table" else None,
            "source_figure_id": source_ref if source_kind == "figure" else None,
        }

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

    def _objective_for_lifecycle(
        self,
        collection_id: str,
        lifecycle: ResearchObjectiveLifecycle,
    ) -> ResearchObjective:
        objective = self._objective_for_build(
            collection_id,
            lifecycle.source_build_id,
            lifecycle.objective_id,
        )
        if objective is None:
            raise FileNotFoundError(
                "research objective lifecycle source not found: "
                f"{collection_id}/{lifecycle.objective_id}"
            )
        return self._with_workspace(
            objective,
            source_build_id=lifecycle.source_build_id,
            status=lifecycle.status,
            analysis_error=lifecycle.analysis_error,
            analysis_progress=lifecycle.analysis_progress,
            created_at=lifecycle.created_at.isoformat(),
            updated_at=lifecycle.updated_at.isoformat(),
        )

    def _objective_for_build(
        self,
        collection_id: str,
        build_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        return next(
            (
                objective
                for objective in self.read(
                    collection_id,
                    build_id=build_id,
                ).research_objectives
                if objective.objective_id == objective_id
            ),
            None,
        )

    @staticmethod
    def _with_workspace(
        objective: ResearchObjective,
        *,
        source_build_id: str | None,
        status: str = "candidate",
        analysis_error: str | None = None,
        analysis_progress: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> ResearchObjective:
        return ResearchObjective.from_mapping(
            {
                **objective.to_record(),
                "source_build_id": source_build_id,
                "status": status,
                "analysis_error": analysis_error,
                "analysis_progress": analysis_progress,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

    def _require_objective_workspace(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        objective = self.read_objective_workspace(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return objective

    @staticmethod
    def _locked_lifecycle(
        session: Session,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjectiveLifecycle | None:
        return session.scalar(
            select(ResearchObjectiveLifecycle)
            .where(
                ResearchObjectiveLifecycle.collection_id == collection_id,
                ResearchObjectiveLifecycle.objective_id == objective_id,
            )
            .with_for_update()
        )

    @classmethod
    def _require_locked_lifecycle(
        cls,
        session: Session,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjectiveLifecycle:
        lifecycle = cls._locked_lifecycle(session, collection_id, objective_id)
        if lifecycle is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return lifecycle

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
