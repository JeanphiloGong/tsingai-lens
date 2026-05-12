from __future__ import annotations

from difflib import SequenceMatcher
import logging
from typing import Any

from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.source.collection_service import CollectionService
from domain.core import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
    build_research_objective_id,
    is_question_shaped_objective,
)
from domain.ports import CoreFactRepository, SourceArtifactRepository
from domain.source import SourceArtifactSet
from infra.persistence.factory import (
    build_core_fact_repository,
    build_source_artifact_repository,
)
from .llm.extractor import (
    CoreLLMStructuredExtractor,
    build_default_core_llm_structured_extractor,
)
from .llm.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredObjectiveMergePlan,
)

logger = logging.getLogger(__name__)

_SKIM_TEXT_PREVIEW_CHARS = 4000
_SKIM_HEADING_LIMIT = 16
_SKIM_CAPTION_LIMIT = 12
_FRAME_SECTION_SNIPPET_LIMIT = 24
_FRAME_SECTION_TEXT_CHARS = 900
_FRAME_TABLE_LIMIT = 20
_FRAME_TABLE_ROW_LIMIT = 6
_ROUTE_TEXT_CHARS = 1200
_ROUTE_CANDIDATE_LIMIT = 40
_OBJECTIVE_EVIDENCE_TEXT_CHARS = 6000
_BROAD_PROPERTY_AXIS_EXPANSIONS = {
    "mechanical properties": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "mechanical property": (
        "yield strength",
        "ultimate tensile strength",
        "elongation",
        "microhardness",
    ),
    "corrosion properties": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passivation behavior",
    ),
    "corrosion property": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passivation behavior",
    ),
}
_STRUCTURAL_PROPERTY_AXES = (
    "densification",
    "relative density",
    "microstructure",
)
_MECHANICAL_PROPERTY_AXES = _BROAD_PROPERTY_AXIS_EXPANSIONS[
    "mechanical properties"
]


class ResearchObjectivesNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve research objectives."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"research objectives not ready: {collection_id}")


class ResearchObjectiveNotFoundError(FileNotFoundError):
    """Raised when one persisted research objective cannot be found."""

    def __init__(self, collection_id: str, objective_id: str) -> None:
        self.collection_id = collection_id
        self.objective_id = objective_id
        super().__init__(f"research objective not found: {collection_id}/{objective_id}")


class ResearchObjectiveService:
    """Build and serve Core research-objective records."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        structured_extractor: CoreLLMStructuredExtractor | None = None,
        core_fact_repository: CoreFactRepository | None = None,
        source_artifact_repository: SourceArtifactRepository | None = None,
        document_profile_service: DocumentProfileService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self._structured_extractor = structured_extractor
        self.core_fact_repository = (
            core_fact_repository
            or getattr(document_profile_service, "core_fact_repository", None)
            or build_core_fact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.source_artifact_repository = (
            source_artifact_repository
            or getattr(document_profile_service, "source_artifact_repository", None)
            or build_source_artifact_repository(
                self.collection_service.root_dir.parent / "lens.sqlite"
            )
        )
        self.document_profile_service = document_profile_service or DocumentProfileService(
            collection_service=self.collection_service,
            structured_extractor=structured_extractor,
            core_fact_repository=self.core_fact_repository,
            source_artifact_repository=self.source_artifact_repository,
        )

    def read_paper_skims(self, collection_id: str) -> tuple[PaperSkim, ...]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.research_objectives_ready:
            return facts.paper_skims
        self.build_research_objectives(collection_id)
        return self.core_fact_repository.read_collection_facts(collection_id).paper_skims

    def read_research_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.research_objectives_ready:
            return facts.research_objectives
        return self.build_research_objectives(collection_id)

    def read_objective_contexts(
        self,
        collection_id: str,
    ) -> tuple[ObjectiveContext, ...]:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.research_objectives_ready:
            return facts.objective_contexts
        self.build_research_objectives(collection_id)
        return self.core_fact_repository.read_collection_facts(
            collection_id
        ).objective_contexts

    def list_objective_workspaces(self, collection_id: str) -> dict[str, Any]:
        facts = self._read_objective_workspace_facts(collection_id)
        objectives = [
            self._objective_list_item(objective, facts=facts)
            for objective in facts.research_objectives
        ]
        return {
            "collection_id": collection_id,
            "state": self._objective_collection_state(facts=facts, objectives=objectives),
            "readiness": self._objective_workspace_readiness(facts),
            "objectives": objectives,
            "warnings": [],
        }

    def get_objective_research_view(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        facts = self._read_objective_workspace_facts(collection_id)
        objective = next(
            (
                candidate
                for candidate in facts.research_objectives
                if candidate.objective_id == objective_id
            ),
            None,
        )
        if objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, objective_id)

        context = next(
            (
                candidate
                for candidate in facts.objective_contexts
                if candidate.objective_id == objective_id
            ),
            None,
        )
        frames = [
            frame
            for frame in facts.objective_paper_frames
            if frame.objective_id == objective_id
        ]
        routes = [
            route.to_record()
            for route in facts.objective_evidence_routes
            if route.objective_id == objective_id
        ]
        evidence_units = [
            unit.to_record()
            for unit in facts.objective_evidence_units
            if unit.objective_id == objective_id
        ]
        logic_chains = [
            chain
            for chain in facts.objective_logic_chains
            if chain.objective_id == objective_id
        ]
        logic_chain = self._select_objective_logic_chain(logic_chains)

        return {
            "collection_id": collection_id,
            "state": self._objective_detail_state(
                frames=frames,
                routes=routes,
                evidence_units=evidence_units,
                logic_chain=logic_chain,
            ),
            "objective": objective.to_record(),
            "objective_context": context.to_record() if context is not None else None,
            "readiness": self._objective_workspace_readiness(
                facts,
                objective_id=objective_id,
            ),
            "paper_frames": self._objective_paper_frame_views(frames, facts=facts),
            "evidence_routes": routes,
            "evidence_units": evidence_units,
            "logic_chain": logic_chain.to_record() if logic_chain is not None else None,
            "existing_comparison_rows": [],
            "warnings": [],
        }

    def build_research_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self._load_source_artifacts(collection_id)
            profiles = self.document_profile_service.read_document_profiles(collection_id)
        except (FileNotFoundError, DocumentProfilesNotReadyError) as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

        profiles_by_document_id = {
            profile.document_id: profile
            for profile in profiles
        }
        blocks_by_document_id = self._group_by_document_id(artifacts.blocks)
        tables_by_document_id = self._group_by_document_id(artifacts.tables)
        figures_by_document_id = self._group_by_document_id(artifacts.figures)
        extractor = self._get_structured_extractor()

        logger.info(
            "Research objective paper skim started collection_id=%s document_count=%s",
            collection_id,
            len(artifacts.documents),
        )
        paper_skims: list[PaperSkim] = []
        document_count = len(artifacts.documents)
        for document_position, document in enumerate(artifacts.documents, start=1):
            document_blocks = blocks_by_document_id.get(document.document_id, [])
            document_tables = tables_by_document_id.get(document.document_id, [])
            document_figures = figures_by_document_id.get(document.document_id, [])
            logger.info(
                "Research objective paper skim document started collection_id=%s document_id=%s document_position=%s document_count=%s block_count=%s table_count=%s figure_count=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                len(document_blocks),
                len(document_tables),
                len(document_figures),
            )
            payload = self._build_paper_skim_payload(
                collection_id=collection_id,
                document=document,
                profile=profiles_by_document_id.get(document.document_id),
                blocks=document_blocks,
                tables=document_tables,
                figures=document_figures,
            )
            parsed = extractor.extract_paper_skim(payload)
            record = parsed.model_dump()
            record.update(
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "source_filename": self._resolve_source_filename(document),
                }
            )
            paper_skim = PaperSkim.from_mapping(record)
            paper_skims.append(paper_skim)
            logger.info(
                "Research objective paper skim document finished collection_id=%s document_id=%s document_position=%s document_count=%s doc_role=%s candidate_materials=%s candidate_processes=%s candidate_properties=%s possible_objectives=%s completed_documents=%s remaining_documents=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                paper_skim.doc_role,
                len(paper_skim.candidate_materials),
                len(paper_skim.candidate_processes),
                len(paper_skim.candidate_properties),
                len(paper_skim.possible_objectives),
                document_position,
                max(document_count - document_position, 0),
            )

        objective_payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
        }
        parsed_objectives = extractor.discover_research_objectives(objective_payload)
        discovered_objective_count = len(parsed_objectives.objectives)
        skim_by_document_id = {
            skim.document_id: skim
            for skim in paper_skims
            if skim.document_id
        }
        research_objectives = tuple(
            objective
            for objective in (
                self._normalize_research_objective(
                    ResearchObjective.from_mapping(item.model_dump()),
                    skim_by_document_id=skim_by_document_id,
                    paper_skims=tuple(paper_skims),
                )
                for item in parsed_objectives.objectives
            )
            if is_question_shaped_objective(objective)
        )
        research_objectives = self._canonicalize_research_objective_axes_with_llm(
            collection_id=collection_id,
            extractor=extractor,
            paper_skims=tuple(paper_skims),
            objectives=research_objectives,
        )
        research_objectives = self._merge_research_objectives_with_llm(
            collection_id=collection_id,
            extractor=extractor,
            paper_skims=tuple(paper_skims),
            objectives=research_objectives,
        )
        research_objectives = self._split_mixed_property_objectives(
            paper_skims=tuple(paper_skims),
            objectives=research_objectives,
        )
        research_objectives = self._align_research_objective_text_with_axes(
            paper_skims=tuple(paper_skims),
            objectives=research_objectives,
        )
        research_objectives = self._dedupe_research_objectives(research_objectives)
        logger.info(
            "Research objective discovery finished collection_id=%s paper_skim_count=%s discovered_objective_count=%s accepted_objective_count=%s",
            collection_id,
            len(paper_skims),
            discovered_objective_count,
            len(research_objectives),
        )
        objective_contexts = self._build_objective_contexts(
            paper_skims=tuple(paper_skims),
            objectives=research_objectives,
            tables=artifacts.tables,
        )
        logger.info(
            "Research objective context build finished collection_id=%s objective_count=%s context_count=%s",
            collection_id,
            len(research_objectives),
            len(objective_contexts),
        )
        objective_paper_frames = self._build_objective_paper_frames(
            collection_id=collection_id,
            extractor=extractor,
            objectives=research_objectives,
            objective_contexts=objective_contexts,
            paper_skims=tuple(paper_skims),
            documents=artifacts.documents,
            profiles_by_document_id=profiles_by_document_id,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
        )
        objective_evidence_routes = self._build_objective_evidence_routes(
            collection_id=collection_id,
            extractor=extractor,
            objectives=research_objectives,
            objective_contexts=objective_contexts,
            objective_paper_frames=objective_paper_frames,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
        )
        objective_evidence_units = self._build_objective_evidence_units(
            collection_id=collection_id,
            extractor=extractor,
            objectives=research_objectives,
            objective_contexts=objective_contexts,
            objective_paper_frames=objective_paper_frames,
            objective_evidence_routes=objective_evidence_routes,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
        )
        objective_logic_chains = self._build_objective_logic_chains(
            collection_id=collection_id,
            objectives=research_objectives,
            objective_contexts=objective_contexts,
            objective_evidence_units=objective_evidence_units,
        )

        self.core_fact_repository.replace_collection_research_objectives(
            collection_id,
            tuple(paper_skims),
            research_objectives,
            objective_contexts,
            objective_paper_frames,
            objective_evidence_routes,
            objective_evidence_units,
            objective_logic_chains,
        )
        logger.info(
            "Research objective build finished collection_id=%s paper_skim_count=%s objective_count=%s objective_evidence_units=%s objective_logic_chains=%s",
            collection_id,
            len(paper_skims),
            len(research_objectives),
            len(objective_evidence_units),
            len(objective_logic_chains),
        )
        return research_objectives

    def _read_objective_workspace_facts(self, collection_id: str):
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        if facts.research_objectives_ready:
            return facts
        if not self.collection_service.list_files(collection_id):
            return facts
        raise ResearchObjectivesNotReadyError(collection_id)

    def _objective_workspace_readiness(
        self,
        facts,
        *,
        objective_id: str | None = None,
    ) -> dict[str, bool]:
        frames = self._filter_objective_records(
            facts.objective_paper_frames,
            objective_id=objective_id,
        )
        routes = self._filter_objective_records(
            facts.objective_evidence_routes,
            objective_id=objective_id,
        )
        evidence_units = self._filter_objective_records(
            facts.objective_evidence_units,
            objective_id=objective_id,
        )
        logic_chains = self._filter_objective_records(
            facts.objective_logic_chains,
            objective_id=objective_id,
        )
        return {
            "objectives_ready": bool(facts.research_objectives_ready),
            "frames_ready": bool(frames),
            "routes_ready": bool(routes),
            "evidence_units_ready": bool(evidence_units),
            "logic_chain_ready": bool(logic_chains),
        }

    def _filter_objective_records(
        self,
        records,
        *,
        objective_id: str | None,
    ) -> tuple[Any, ...]:
        if objective_id is None:
            return tuple(records)
        return tuple(
            record
            for record in records
            if getattr(record, "objective_id", None) == objective_id
        )

    def _objective_list_item(self, objective: ResearchObjective, *, facts) -> dict[str, Any]:
        frames = self._filter_objective_records(
            facts.objective_paper_frames,
            objective_id=objective.objective_id,
        )
        routes = self._filter_objective_records(
            facts.objective_evidence_routes,
            objective_id=objective.objective_id,
        )
        evidence_units = self._filter_objective_records(
            facts.objective_evidence_units,
            objective_id=objective.objective_id,
        )
        logic_chains = self._filter_objective_records(
            facts.objective_logic_chains,
            objective_id=objective.objective_id,
        )
        record = objective.to_record()
        record.update(
            {
                "state": self._objective_detail_state(
                    frames=frames,
                    routes=routes,
                    evidence_units=evidence_units,
                    logic_chain=self._select_objective_logic_chain(logic_chains),
                ),
                "paper_frame_count": len(frames),
                "evidence_route_count": len(routes),
                "evidence_unit_count": len(evidence_units),
                "logic_chain_count": len(logic_chains),
            }
        )
        return record

    def _objective_collection_state(
        self,
        *,
        facts,
        objectives: list[dict[str, Any]],
    ) -> str:
        if not objectives:
            return "empty"
        if any(objective["state"] == "ready" for objective in objectives):
            return "ready"
        if any(
            objective["state"] in {"partial", "processing"}
            for objective in objectives
        ):
            return "partial"
        if facts.research_objectives_ready:
            return "partial"
        return "empty"

    def _objective_detail_state(
        self,
        *,
        frames,
        routes,
        evidence_units,
        logic_chain,
    ) -> str:
        if logic_chain is not None:
            return "ready"
        if frames or routes or evidence_units:
            return "partial"
        return "empty"

    def _select_objective_logic_chain(self, logic_chains):
        for chain in logic_chains:
            if chain.chain_scope == "objective":
                return chain
        return logic_chains[0] if logic_chains else None

    def _objective_paper_frame_views(
        self,
        frames: list[ObjectivePaperFrame],
        *,
        facts,
    ) -> list[dict[str, Any]]:
        metadata_by_document_id = self._objective_document_metadata(facts)
        return [
            {
                **frame.to_record(),
                "title": metadata_by_document_id.get(frame.document_id, {}).get("title"),
                "source_filename": metadata_by_document_id.get(
                    frame.document_id,
                    {},
                ).get("source_filename"),
            }
            for frame in frames
        ]

    def _objective_document_metadata(self, facts) -> dict[str, dict[str, str | None]]:
        metadata: dict[str, dict[str, str | None]] = {}
        for skim in facts.paper_skims:
            metadata[skim.document_id] = {
                "title": skim.title,
                "source_filename": skim.source_filename,
            }
        for profile in facts.document_profiles:
            metadata[profile.document_id] = {
                "title": profile.title or metadata.get(profile.document_id, {}).get("title"),
                "source_filename": (
                    profile.source_filename
                    or metadata.get(profile.document_id, {}).get("source_filename")
                ),
            }
        return metadata

    def _build_objective_paper_frames(
        self,
        *,
        collection_id: str,
        extractor: CoreLLMStructuredExtractor,
        objectives: tuple[ResearchObjective, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
        paper_skims: tuple[PaperSkim, ...],
        documents: tuple[Any, ...],
        profiles_by_document_id: dict[str, Any],
        blocks_by_document_id: dict[str, list[Any]],
        tables_by_document_id: dict[str, list[Any]],
    ) -> tuple[ObjectivePaperFrame, ...]:
        context_by_objective_id = {
            context.objective_id: context
            for context in objective_contexts
        }
        skim_by_document_id = {
            skim.document_id: skim
            for skim in paper_skims
            if skim.document_id
        }
        frames: list[ObjectivePaperFrame] = []
        logger.info(
            "Research objective paper framing started collection_id=%s objective_count=%s document_count=%s",
            collection_id,
            len(objectives),
            len(documents),
        )
        objective_count = len(objectives)
        document_count = len(documents)
        total_frame_requests = objective_count * document_count
        completed_frame_requests = 0
        for objective_position, objective in enumerate(objectives, start=1):
            objective_context = context_by_objective_id.get(objective.objective_id)
            for document_position, document in enumerate(documents, start=1):
                completed_frame_requests += 1
                document_id = str(getattr(document, "document_id", "") or "")
                tables = tables_by_document_id.get(document_id, [])
                known_table_ids = {
                    str(getattr(table, "table_id", "") or "")
                    for table in tables
                    if str(getattr(table, "table_id", "") or "")
                }
                logger.info(
                    "Research objective paper framing document started collection_id=%s objective_id=%s objective_position=%s objective_count=%s document_id=%s document_position=%s document_count=%s completed_frame_requests=%s total_frame_requests=%s remaining_frame_requests=%s table_count=%s",
                    collection_id,
                    objective.objective_id,
                    objective_position,
                    objective_count,
                    document_id,
                    document_position,
                    document_count,
                    completed_frame_requests - 1,
                    total_frame_requests,
                    max(total_frame_requests - completed_frame_requests + 1, 0),
                    len(tables),
                )
                payload = self._build_objective_paper_frame_payload(
                    collection_id=collection_id,
                    objective=objective,
                    objective_context=objective_context,
                    paper_skim=skim_by_document_id.get(document_id),
                    document=document,
                    profile=profiles_by_document_id.get(document_id),
                    blocks=blocks_by_document_id.get(document_id, []),
                    tables=tables,
                )
                parsed = extractor.frame_objective_paper(payload)
                record = parsed.model_dump()
                relevant_tables = self._filter_known_values(
                    record.get("relevant_tables"),
                    known_values=known_table_ids,
                )
                excluded_tables = tuple(
                    table_id
                    for table_id in self._filter_known_values(
                        record.get("excluded_tables"),
                        known_values=known_table_ids,
                    )
                    if table_id not in set(relevant_tables)
                )
                section_labels = {
                    str(item.get("section_label") or "")
                    for item in payload["section_snippets"]
                    if str(item.get("section_label") or "")
                }
                record.update(
                    {
                        "objective_id": objective.objective_id,
                        "document_id": document_id,
                        "relevant_sections": self._filter_known_values(
                            record.get("relevant_sections"),
                            known_values=section_labels,
                        ),
                        "relevant_tables": relevant_tables,
                        "excluded_tables": excluded_tables,
                    }
                )
                frame = ObjectivePaperFrame.from_mapping(record)
                frames.append(frame)
                logger.info(
                    "Research objective paper framing document finished collection_id=%s objective_id=%s objective_position=%s objective_count=%s document_id=%s document_position=%s document_count=%s relevance=%s paper_role=%s relevant_tables=%s excluded_tables=%s completed_frame_requests=%s total_frame_requests=%s remaining_frame_requests=%s",
                    collection_id,
                    objective.objective_id,
                    objective_position,
                    objective_count,
                    document_id,
                    document_position,
                    document_count,
                    frame.relevance,
                    frame.paper_role,
                    len(frame.relevant_tables),
                    len(frame.excluded_tables),
                    completed_frame_requests,
                    total_frame_requests,
                    max(total_frame_requests - completed_frame_requests, 0),
                )
        logger.info(
            "Research objective paper framing finished collection_id=%s frame_count=%s",
            collection_id,
            len(frames),
        )
        return tuple(frames)

    def _build_objective_evidence_routes(
        self,
        *,
        collection_id: str,
        extractor: CoreLLMStructuredExtractor,
        objectives: tuple[ResearchObjective, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
        objective_paper_frames: tuple[ObjectivePaperFrame, ...],
        blocks_by_document_id: dict[str, list[Any]],
        tables_by_document_id: dict[str, list[Any]],
    ) -> tuple[ObjectiveEvidenceRoute, ...]:
        objective_by_id = {
            objective.objective_id: objective
            for objective in objectives
        }
        context_by_objective_id = {
            context.objective_id: context
            for context in objective_contexts
        }
        routes: list[ObjectiveEvidenceRoute] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        logger.info(
            "Research objective evidence routing started collection_id=%s frame_count=%s",
            collection_id,
            len(objective_paper_frames),
        )
        frame_count = len(objective_paper_frames)
        for frame_position, frame in enumerate(objective_paper_frames, start=1):
            logger.info(
                "Research objective evidence routing frame started collection_id=%s objective_id=%s document_id=%s frame_id=%s frame_position=%s frame_count=%s relevance=%s completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.frame_id,
                frame_position,
                frame_count,
                frame.relevance,
                frame_position - 1,
                max(frame_count - frame_position + 1, 0),
            )
            if frame.relevance == "irrelevant":
                logger.info(
                    "Research objective evidence routing frame skipped collection_id=%s objective_id=%s document_id=%s frame_id=%s frame_position=%s frame_count=%s reason=irrelevant completed_frames=%s remaining_frames=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    frame.frame_id,
                    frame_position,
                    frame_count,
                    frame_position,
                    max(frame_count - frame_position, 0),
                )
                continue
            objective = objective_by_id.get(frame.objective_id)
            if objective is None:
                logger.info(
                    "Research objective evidence routing frame skipped collection_id=%s objective_id=%s document_id=%s frame_id=%s frame_position=%s frame_count=%s reason=missing_objective completed_frames=%s remaining_frames=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    frame.frame_id,
                    frame_position,
                    frame_count,
                    frame_position,
                    max(frame_count - frame_position, 0),
                )
                continue
            source_candidates = self._build_route_source_candidates(
                frame=frame,
                blocks=blocks_by_document_id.get(frame.document_id, []),
                tables=tables_by_document_id.get(frame.document_id, []),
            )
            if not source_candidates:
                logger.info(
                    "Research objective evidence routing frame finished collection_id=%s objective_id=%s document_id=%s frame_id=%s frame_position=%s frame_count=%s source_candidate_count=0 route_count=0 extractable_route_count=0 completed_frames=%s remaining_frames=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    frame.frame_id,
                    frame_position,
                    frame_count,
                    frame_position,
                    max(frame_count - frame_position, 0),
                )
                continue
            frame_route_count_before = len(routes)
            candidate_by_key = {
                (candidate["source_kind"], candidate["source_ref"]): candidate
                for candidate in source_candidates
            }
            payload = {
                "collection_id": collection_id,
                "objective": objective.to_record(),
                "objective_context": (
                    context_by_objective_id[frame.objective_id].to_record()
                    if frame.objective_id in context_by_objective_id
                    else {}
                ),
                "paper_frame": frame.to_record(),
                "source_candidates": source_candidates,
            }
            parsed = extractor.route_objective_evidence(payload)
            for item in parsed.routes:
                record = item.model_dump()
                source_kind = str(record.get("source_kind") or "")
                source_ref = str(record.get("source_ref") or "")
                candidate = candidate_by_key.get((source_kind, source_ref))
                if candidate is None:
                    continue
                if candidate.get("frame_status") == "excluded":
                    record["role"] = "low_value_or_irrelevant"
                    record["extractable"] = False
                role = str(record.get("role") or "low_value_or_irrelevant")
                route_key = (
                    frame.objective_id,
                    frame.document_id,
                    source_kind,
                    source_ref,
                    role,
                )
                if route_key in seen:
                    continue
                seen.add(route_key)
                record.update(
                    {
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "table_schema": self._route_table_schema_record(
                            candidate=candidate,
                        ),
                        "extractable": self._normalize_route_extractable(record),
                    }
                )
                if source_kind != "table":
                    record.update(
                        {
                            "column_roles": {},
                            "join_keys": {},
                            "join_plan": {},
                        }
                    )
                routes.append(ObjectiveEvidenceRoute.from_mapping(record))
            frame_routes = routes[frame_route_count_before:]
            logger.info(
                "Research objective evidence routing frame finished collection_id=%s objective_id=%s document_id=%s frame_id=%s frame_position=%s frame_count=%s source_candidate_count=%s route_count=%s extractable_route_count=%s completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.frame_id,
                frame_position,
                frame_count,
                len(source_candidates),
                len(frame_routes),
                sum(1 for route in frame_routes if route.extractable),
                frame_position,
                max(frame_count - frame_position, 0),
            )
        logger.info(
            "Research objective evidence routing finished collection_id=%s route_count=%s",
            collection_id,
            len(routes),
        )
        return tuple(routes)

    def _build_objective_evidence_units(
        self,
        *,
        collection_id: str,
        extractor: CoreLLMStructuredExtractor,
        objectives: tuple[ResearchObjective, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
        objective_paper_frames: tuple[ObjectivePaperFrame, ...],
        objective_evidence_routes: tuple[ObjectiveEvidenceRoute, ...],
        blocks_by_document_id: dict[str, list[Any]],
        tables_by_document_id: dict[str, list[Any]],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        objective_by_id = {
            objective.objective_id: objective
            for objective in objectives
        }
        context_by_objective_id = {
            context.objective_id: context
            for context in objective_contexts
        }
        frame_by_key = {
            (frame.objective_id, frame.document_id): frame
            for frame in objective_paper_frames
        }
        extractable_routes = tuple(
            route
            for route in objective_evidence_routes
            if route.extractable and route.role != "low_value_or_irrelevant"
        )
        logger.info(
            "Research objective evidence-unit extraction started collection_id=%s route_count=%s extractable_route_count=%s",
            collection_id,
            len(objective_evidence_routes),
            len(extractable_routes),
        )
        units: list[ObjectiveEvidenceUnit] = []
        seen: set[str] = set()
        for route_position, route in enumerate(extractable_routes, start=1):
            objective = objective_by_id.get(route.objective_id)
            if objective is None:
                logger.info(
                    "Research objective evidence-unit extraction route skipped collection_id=%s route_id=%s reason=missing_objective route_position=%s route_count=%s",
                    collection_id,
                    route.route_id,
                    route_position,
                    len(extractable_routes),
                )
                continue
            source = self._build_objective_route_source_payload(
                route=route,
                blocks=blocks_by_document_id.get(route.document_id, []),
                tables=tables_by_document_id.get(route.document_id, []),
            )
            if not source:
                logger.info(
                    "Research objective evidence-unit extraction route skipped collection_id=%s route_id=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s reason=missing_source route_position=%s route_count=%s",
                    collection_id,
                    route.route_id,
                    route.objective_id,
                    route.document_id,
                    route.source_kind,
                    route.source_ref,
                    route_position,
                    len(extractable_routes),
                )
                continue
            payload = {
                "collection_id": collection_id,
                "objective": objective.to_record(),
                "objective_context": (
                    context_by_objective_id[route.objective_id].to_record()
                    if route.objective_id in context_by_objective_id
                    else {}
                ),
                "paper_frame": (
                    frame_by_key[(route.objective_id, route.document_id)].to_record()
                    if (route.objective_id, route.document_id) in frame_by_key
                    else {}
                ),
                "evidence_route": route.to_record(),
                "source": source,
            }
            parsed = extractor.extract_objective_evidence_units(payload)
            route_unit_start = len(units)
            for item in parsed.evidence_units:
                record = item.model_dump()
                record.update(
                    {
                        "objective_id": route.objective_id,
                        "document_id": route.document_id,
                        "source_refs": self._objective_route_source_refs(
                            route=route,
                            source=source,
                        ),
                        "join_keys": record.get("join_keys") or dict(route.join_keys),
                    }
                )
                if not record.get("confidence"):
                    record["confidence"] = route.confidence
                unit = ObjectiveEvidenceUnit.from_mapping(record)
                if not self._objective_evidence_unit_has_payload(unit):
                    continue
                if unit.evidence_unit_id in seen:
                    continue
                seen.add(unit.evidence_unit_id)
                units.append(unit)
            logger.info(
                "Research objective evidence-unit extraction route finished collection_id=%s route_id=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s evidence_units=%s completed_routes=%s remaining_routes=%s",
                collection_id,
                route.route_id,
                route.objective_id,
                route.document_id,
                route.source_kind,
                route.source_ref,
                route_position,
                len(extractable_routes),
                len(units) - route_unit_start,
                route_position,
                max(len(extractable_routes) - route_position, 0),
            )
        logger.info(
            "Research objective evidence-unit extraction finished collection_id=%s objective_evidence_units=%s",
            collection_id,
            len(units),
        )
        return tuple(units)

    def _build_objective_route_source_payload(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        blocks: list[Any],
        tables: list[Any],
    ) -> dict[str, Any]:
        if route.source_kind == "table":
            table = next(
                (
                    candidate
                    for candidate in tables
                    if str(getattr(candidate, "table_id", "") or "") == route.source_ref
                ),
                None,
            )
            if table is None:
                return {}
            return {
                "source_kind": "table",
                "source_ref": route.source_ref,
                "document_id": route.document_id,
                "page": getattr(table, "page", None),
                "caption_text": getattr(table, "caption_text", None),
                "heading_path": getattr(table, "heading_path", None),
                "column_headers": [
                    str(value)
                    for value in getattr(table, "column_headers", ()) or ()
                ],
                "table_matrix": [
                    [str(cell) for cell in row]
                    for row in getattr(table, "table_matrix", ()) or ()
                    if isinstance(row, (list, tuple))
                ],
            }
        if route.source_kind == "text_window":
            block = next(
                (
                    candidate
                    for candidate in blocks
                    if str(getattr(candidate, "block_id", "") or "") == route.source_ref
                ),
                None,
            )
            if block is None:
                return {}
            text = str(getattr(block, "text", "") or "").strip()
            return {
                "source_kind": "text_window",
                "source_ref": route.source_ref,
                "document_id": route.document_id,
                "page": getattr(block, "page", None),
                "block_type": getattr(block, "block_type", None),
                "heading_path": getattr(block, "heading_path", None),
                "text": text[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
            }
        return {}

    def _objective_route_source_refs(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        source: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        ref = {
            "route_id": route.route_id,
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "role": route.role,
            "page": source.get("page"),
        }
        return (
            {
                key: value
                for key, value in ref.items()
                if value not in (None, "", [], {})
            },
        )

    def _objective_evidence_unit_has_payload(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> bool:
        return any(
            (
                unit.unit_kind != "unknown",
                unit.property_normalized,
                unit.material_system,
                unit.sample_context,
                unit.process_context,
                unit.resolved_condition,
                unit.test_condition,
                unit.value_payload,
                unit.baseline_context,
                unit.interpretation,
            )
        )

    def _build_objective_logic_chains(
        self,
        *,
        collection_id: str,
        objectives: tuple[ResearchObjective, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
        objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> tuple[ObjectiveLogicChain, ...]:
        context_by_objective_id = {
            context.objective_id: context
            for context in objective_contexts
        }
        units_by_objective_id: dict[str, list[ObjectiveEvidenceUnit]] = {}
        for unit in objective_evidence_units:
            units_by_objective_id.setdefault(unit.objective_id, []).append(unit)
        logger.info(
            "Research objective logic-chain assembly started collection_id=%s objective_count=%s objective_evidence_units=%s",
            collection_id,
            len(objectives),
            len(objective_evidence_units),
        )
        chains: list[ObjectiveLogicChain] = []
        for objective in objectives:
            units = tuple(units_by_objective_id.get(objective.objective_id, ()))
            if not units:
                continue
            chain_payload = self._objective_logic_chain_payload(
                objective=objective,
                objective_context=context_by_objective_id.get(objective.objective_id),
                units=units,
            )
            chains.append(
                ObjectiveLogicChain.from_mapping(
                    {
                        "objective_id": objective.objective_id,
                        "chain_scope": "objective",
                        "question": objective.question,
                        "evidence_unit_ids": [
                            unit.evidence_unit_id
                            for unit in units
                        ],
                        "chain_payload": chain_payload,
                        "summary": self._objective_logic_chain_summary(chain_payload),
                        "confidence": objective.confidence,
                    }
                )
            )
            logger.info(
                "Research objective logic-chain assembly objective finished collection_id=%s objective_id=%s evidence_unit_count=%s",
                collection_id,
                objective.objective_id,
                len(units),
            )
        logger.info(
            "Research objective logic-chain assembly finished collection_id=%s logic_chain_count=%s",
            collection_id,
            len(chains),
        )
        return tuple(chains)

    def _objective_logic_chain_payload(
        self,
        *,
        objective: ResearchObjective,
        objective_context: ObjectiveContext | None,
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> dict[str, Any]:
        counts_by_kind: dict[str, int] = {}
        document_ids: list[str] = []
        for unit in units:
            counts_by_kind[unit.unit_kind] = counts_by_kind.get(unit.unit_kind, 0) + 1
            if unit.document_id not in document_ids:
                document_ids.append(unit.document_id)
        evidence_unit_ids_by_role = self._objective_evidence_unit_ids_by_role(units)
        paper_chains = [
            self._objective_paper_logic_chain(
                document_id=document_id,
                units=tuple(unit for unit in units if unit.document_id == document_id),
            )
            for document_id in document_ids
        ]
        cross_paper = self._objective_cross_paper_logic(
            paper_chains=paper_chains,
            units=units,
        )
        return {
            "schema_version": "objective_logic_chain.v1",
            "objective": objective.to_record(),
            "context": objective_context.to_record() if objective_context else {},
            "unit_counts_by_kind": counts_by_kind,
            "document_ids": document_ids,
            "evidence_unit_ids_by_role": evidence_unit_ids_by_role,
            "steps": self._objective_logic_chain_steps(
                objective=objective,
                objective_context=objective_context,
                evidence_unit_ids_by_role=evidence_unit_ids_by_role,
                cross_paper=cross_paper,
            ),
            "paper_chains": paper_chains,
            "cross_paper": cross_paper,
        }

    def _objective_paper_logic_chain(
        self,
        *,
        document_id: str,
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> dict[str, Any]:
        measurements = tuple(unit for unit in units if unit.unit_kind == "measurement")
        test_conditions = tuple(
            unit for unit in units if unit.unit_kind == "test_condition"
        )
        sample_process_units = tuple(
            unit
            for unit in units
            if unit.unit_kind in {"sample_context", "process_context", "measurement"}
            and (unit.sample_context or unit.process_context)
        )
        characterization = tuple(
            unit for unit in units if unit.unit_kind == "characterization"
        )
        comparisons = tuple(unit for unit in units if unit.unit_kind == "comparison")
        interpretations = tuple(
            unit for unit in units if unit.unit_kind == "interpretation"
        )
        return {
            "document_id": document_id,
            "evidence_unit_ids": [unit.evidence_unit_id for unit in units],
            "sample_and_process_contexts": self._dedupe_chain_items(
                [
                    self._objective_sample_process_chain_item(unit)
                    for unit in sample_process_units
                ]
            ),
            "test_conditions": [
                self._objective_logic_unit_reference(unit)
                for unit in test_conditions
            ],
            "characterization_observations": [
                self._objective_logic_unit_reference(unit)
                for unit in characterization
            ],
            "measurement_results": [
                self._objective_logic_unit_reference(unit)
                for unit in measurements
            ],
            "comparisons": [
                self._objective_logic_unit_reference(unit)
                for unit in comparisons
            ],
            "author_interpretations": [
                self._objective_logic_unit_reference(unit)
                for unit in interpretations
            ],
            "resolution": {
                "measurement_count": len(measurements),
                "resolved_measurement_count": sum(
                    1
                    for unit in measurements
                    if unit.resolution_status == "resolved"
                ),
                "test_condition_count": len(test_conditions),
                "characterization_count": len(characterization),
                "comparison_count": len(comparisons),
                "gaps": self._objective_paper_logic_gaps(
                    measurements=measurements,
                    test_conditions=test_conditions,
                    sample_process_units=sample_process_units,
                    characterization=characterization,
                    comparisons=comparisons,
                ),
            },
        }

    def _objective_evidence_unit_ids_by_role(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> dict[str, list[str]]:
        roles = {
            "sample_and_process_context": [],
            "test_and_characterization": [],
            "measurements": [],
            "comparisons": [],
            "interpretations": [],
            "other": [],
        }
        for unit in units:
            if unit.unit_kind in {"sample_context", "process_context"}:
                roles["sample_and_process_context"].append(unit.evidence_unit_id)
            elif unit.unit_kind == "test_condition":
                roles["test_and_characterization"].append(unit.evidence_unit_id)
            elif unit.unit_kind == "characterization":
                roles["test_and_characterization"].append(unit.evidence_unit_id)
            elif unit.unit_kind == "measurement":
                roles["measurements"].append(unit.evidence_unit_id)
                if unit.sample_context or unit.process_context:
                    roles["sample_and_process_context"].append(unit.evidence_unit_id)
                if unit.test_condition:
                    roles["test_and_characterization"].append(unit.evidence_unit_id)
            elif unit.unit_kind == "comparison":
                roles["comparisons"].append(unit.evidence_unit_id)
            elif unit.unit_kind == "interpretation":
                roles["interpretations"].append(unit.evidence_unit_id)
            else:
                roles["other"].append(unit.evidence_unit_id)
        return {
            role: self._dedupe_preserving_order(unit_ids)
            for role, unit_ids in roles.items()
            if unit_ids
        }

    def _objective_logic_chain_steps(
        self,
        *,
        objective: ResearchObjective,
        objective_context: ObjectiveContext | None,
        evidence_unit_ids_by_role: dict[str, list[str]],
        cross_paper: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "step_role": "research_objective",
                "question": objective.question,
                "material_scope": list(objective.material_scope),
                "target_property_axes": (
                    list(objective_context.target_property_axes)
                    if objective_context is not None
                    else []
                ),
            },
            {
                "step_role": "sample_and_process_context",
                "evidence_unit_ids": evidence_unit_ids_by_role.get(
                    "sample_and_process_context",
                    [],
                ),
            },
            {
                "step_role": "test_and_characterization",
                "evidence_unit_ids": evidence_unit_ids_by_role.get(
                    "test_and_characterization",
                    [],
                ),
            },
            {
                "step_role": "measurement_results",
                "evidence_unit_ids": evidence_unit_ids_by_role.get("measurements", []),
                "measured_properties": cross_paper.get("measured_properties", []),
            },
            {
                "step_role": "comparison_and_interpretation",
                "evidence_unit_ids": [
                    *evidence_unit_ids_by_role.get("comparisons", []),
                    *evidence_unit_ids_by_role.get("interpretations", []),
                ],
            },
            {
                "step_role": "cross_paper_resolution",
                "document_count": cross_paper.get("document_count", 0),
                "gaps": cross_paper.get("gaps", []),
            },
        ]

    def _objective_cross_paper_logic(
        self,
        *,
        paper_chains: list[dict[str, Any]],
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> dict[str, Any]:
        measurements = tuple(unit for unit in units if unit.unit_kind == "measurement")
        comparisons = tuple(unit for unit in units if unit.unit_kind == "comparison")
        gaps = []
        if not comparisons:
            gaps.append("comparison_units_missing")
        if any(
            unit.resolution_status != "resolved"
            for unit in measurements
        ):
            gaps.append("unresolved_measurements_present")
        return {
            "document_count": len(paper_chains),
            "measured_properties": self._dedupe_preserving_order(
                [
                    unit.property_normalized
                    for unit in measurements
                    if unit.property_normalized
                ]
            ),
            "sample_labels": self._dedupe_preserving_order(
                [
                    str(unit.sample_context.get("label"))
                    for unit in units
                    if unit.sample_context.get("label")
                ]
            ),
            "resolved_measurement_count": sum(
                1
                for unit in measurements
                if unit.resolution_status == "resolved"
            ),
            "comparison_unit_count": len(comparisons),
            "comparison_ready": bool(comparisons),
            "gaps": gaps,
        }

    def _objective_paper_logic_gaps(
        self,
        *,
        measurements: tuple[ObjectiveEvidenceUnit, ...],
        test_conditions: tuple[ObjectiveEvidenceUnit, ...],
        sample_process_units: tuple[ObjectiveEvidenceUnit, ...],
        characterization: tuple[ObjectiveEvidenceUnit, ...],
        comparisons: tuple[ObjectiveEvidenceUnit, ...],
    ) -> list[str]:
        gaps = []
        if not sample_process_units:
            gaps.append("sample_or_process_context_missing")
        if not test_conditions and not any(unit.test_condition for unit in measurements):
            gaps.append("test_condition_missing")
        if not measurements:
            gaps.append("measurement_results_missing")
        if not characterization:
            gaps.append("characterization_observations_missing")
        if not comparisons:
            gaps.append("comparison_units_missing")
        return gaps

    def _objective_sample_process_chain_item(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "evidence_unit_id": unit.evidence_unit_id,
                "document_id": unit.document_id,
                "sample_context": dict(unit.sample_context),
                "process_context": dict(unit.process_context),
                "join_keys": dict(unit.join_keys),
                "source_refs": [dict(source_ref) for source_ref in unit.source_refs],
                "resolution_status": unit.resolution_status,
            }.items()
            if value not in (None, "", [], {})
        }

    def _objective_logic_unit_reference(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "evidence_unit_id": unit.evidence_unit_id,
                "document_id": unit.document_id,
                "unit_kind": unit.unit_kind,
                "property_normalized": unit.property_normalized,
                "material_system": dict(unit.material_system),
                "sample_context": dict(unit.sample_context),
                "process_context": dict(unit.process_context),
                "test_condition": dict(unit.test_condition),
                "value_payload": dict(unit.value_payload),
                "unit": unit.unit,
                "baseline_context": dict(unit.baseline_context),
                "interpretation": unit.interpretation,
                "source_refs": [dict(source_ref) for source_ref in unit.source_refs],
                "evidence_anchor_ids": list(unit.evidence_anchor_ids),
                "join_keys": dict(unit.join_keys),
                "resolution_status": unit.resolution_status,
                "confidence": unit.confidence,
            }.items()
            if value not in (None, "", [], {})
        }

    def _objective_logic_chain_summary(
        self,
        chain_payload: dict[str, Any],
    ) -> str:
        objective = chain_payload.get("objective", {})
        question = (
            objective.get("question")
            if isinstance(objective, dict)
            else None
        )
        counts = chain_payload.get("unit_counts_by_kind", {})
        measurement_count = counts.get("measurement", 0) if isinstance(counts, dict) else 0
        document_ids = chain_payload.get("document_ids", [])
        document_count = len(document_ids) if isinstance(document_ids, list) else 0
        return (
            f"{question or 'Objective'}: assembled {measurement_count} "
            f"measurement unit(s) across {document_count} document(s)."
        )

    def _dedupe_chain_items(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            key = repr(sorted(item.items()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _dedupe_preserving_order(
        self,
        values: list[str | None],
    ) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    def _build_route_source_candidates(
        self,
        *,
        frame: ObjectivePaperFrame,
        blocks: list[Any],
        tables: list[Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        table_by_id = {
            str(getattr(table, "table_id", "") or ""): table
            for table in tables
            if str(getattr(table, "table_id", "") or "")
        }
        for table_id in (*frame.relevant_tables, *frame.excluded_tables):
            table = table_by_id.get(table_id)
            if table is None:
                continue
            table_schema = self._build_route_table_schema(table)
            candidates.append(
                {
                    "source_kind": "table",
                    "source_ref": table_id,
                    "frame_status": (
                        "excluded"
                        if table_id in frame.excluded_tables
                        else "relevant"
                    ),
                    "caption_text": getattr(table, "caption_text", None),
                    "heading_path": getattr(table, "heading_path", None),
                    "table_schema": table_schema,
                    "sample_rows": table_schema["sample_rows"],
                }
            )
        relevant_sections = set(frame.relevant_sections)
        if relevant_sections:
            for block in sorted(
                blocks,
                key=lambda item: int(getattr(item, "block_order", 0) or 0),
            ):
                if len(candidates) >= _ROUTE_CANDIDATE_LIMIT:
                    break
                block_id = str(getattr(block, "block_id", "") or "")
                text = str(getattr(block, "text", "") or "").strip()
                block_type = str(getattr(block, "block_type", "") or "")
                section_label = self._block_section_label(block)
                if (
                    not block_id
                    or not text
                    or block_type not in {"paragraph", "list_item"}
                ):
                    continue
                if section_label not in relevant_sections:
                    continue
                candidates.append(
                    {
                        "source_kind": "text_window",
                        "source_ref": block_id,
                        "frame_status": "relevant",
                        "section_label": section_label,
                        "block_type": block_type,
                        "text": text[:_ROUTE_TEXT_CHARS],
                    }
                )
        return candidates[:_ROUTE_CANDIDATE_LIMIT]

    def _build_route_table_schema(self, table: Any) -> dict[str, Any]:
        matrix = tuple(getattr(table, "table_matrix", ()) or ())
        return {
            "table_id": str(getattr(table, "table_id", "") or ""),
            "caption_text": getattr(table, "caption_text", None),
            "heading_path": getattr(table, "heading_path", None),
            "column_headers": [
                str(value)
                for value in getattr(table, "column_headers", ()) or ()
            ],
            "row_count": int(getattr(table, "row_count", 0) or 0),
            "col_count": int(getattr(table, "col_count", 0) or 0),
            "sample_rows": [
                [str(cell) for cell in row]
                for row in matrix[:_FRAME_TABLE_ROW_LIMIT]
                if isinstance(row, (list, tuple))
            ],
        }

    def _route_table_schema_record(
        self,
        *,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        if candidate.get("source_kind") != "table":
            return {}
        candidate_schema = candidate.get("table_schema")
        return dict(candidate_schema) if isinstance(candidate_schema, dict) else {}

    def _normalize_route_extractable(self, record: dict[str, Any]) -> bool:
        if record.get("role") == "low_value_or_irrelevant":
            return False
        return bool(record.get("extractable"))

    def _build_objective_paper_frame_payload(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        objective_context: ObjectiveContext | None,
        paper_skim: PaperSkim | None,
        document: Any,
        profile: Any,
        blocks: list[Any],
        tables: list[Any],
    ) -> dict[str, Any]:
        return {
            "collection_id": collection_id,
            "objective": objective.to_record(),
            "objective_context": (
                objective_context.to_record() if objective_context is not None else {}
            ),
            "paper_skim": paper_skim.to_record() if paper_skim is not None else {},
            "document": {
                "document_id": getattr(document, "document_id", None),
                "title": getattr(document, "title", None),
                "source_filename": self._resolve_source_filename(document),
            },
            "document_profile": profile.to_record() if profile else {},
            "section_snippets": self._build_frame_section_snippets(blocks),
            "table_summaries": self._build_frame_table_summaries(tables),
        }

    def _build_frame_section_snippets(self, blocks: list[Any]) -> list[dict[str, Any]]:
        snippets: list[dict[str, Any]] = []
        for block in sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        ):
            text = str(getattr(block, "text", "") or "").strip()
            if not text:
                continue
            block_type = str(getattr(block, "block_type", "") or "")
            if block_type not in {"heading", "paragraph", "list_item"}:
                continue
            section_label = str(getattr(block, "heading_path", "") or "").strip()
            if block_type == "heading":
                section_label = text
            if not section_label:
                section_label = "Unsectioned"
            snippets.append(
                {
                    "section_label": section_label,
                    "block_type": block_type,
                    "text": text[:_FRAME_SECTION_TEXT_CHARS],
                }
            )
            if len(snippets) >= _FRAME_SECTION_SNIPPET_LIMIT:
                break
        return snippets

    def _build_frame_table_summaries(self, tables: list[Any]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for table in sorted(
            tables,
            key=lambda item: int(getattr(item, "table_order", 0) or 0),
        )[:_FRAME_TABLE_LIMIT]:
            matrix = tuple(getattr(table, "table_matrix", ()) or ())
            sample_rows = [
                [str(cell) for cell in row]
                for row in matrix[:_FRAME_TABLE_ROW_LIMIT]
                if isinstance(row, (list, tuple))
            ]
            summaries.append(
                {
                    "table_id": str(getattr(table, "table_id", "") or ""),
                    "caption_text": getattr(table, "caption_text", None),
                    "heading_path": getattr(table, "heading_path", None),
                    "column_headers": [
                        str(value)
                        for value in getattr(table, "column_headers", ()) or ()
                    ],
                    "row_count": int(getattr(table, "row_count", 0) or 0),
                    "col_count": int(getattr(table, "col_count", 0) or 0),
                    "sample_rows": sample_rows,
                }
            )
        return summaries

    def _block_section_label(self, block: Any) -> str:
        block_type = str(getattr(block, "block_type", "") or "")
        if block_type == "heading":
            heading = str(getattr(block, "text", "") or "").strip()
            if heading:
                return heading
        section_label = str(getattr(block, "heading_path", "") or "").strip()
        return section_label or "Unsectioned"

    def _filter_known_values(
        self,
        values: Any,
        *,
        known_values: set[str],
    ) -> tuple[str, ...]:
        if not known_values or not isinstance(values, (list, tuple, set)):
            return ()
        filtered: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text not in known_values or text in seen:
                continue
            seen.add(text)
            filtered.append(text)
        return tuple(filtered)

    def _build_objective_contexts(
        self,
        *,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
        tables: tuple[Any, ...],
    ) -> tuple[ObjectiveContext, ...]:
        contexts: list[ObjectiveContext] = []
        for objective in objectives:
            relevant_skims = self._select_relevant_skims(
                objective,
                paper_skims=paper_skims,
            )
            variable_axes, context_axes = self._split_objective_process_axes(
                objective,
                paper_skims=paper_skims,
            )
            target_properties = list(objective.property_axes)
            excluded_properties = self._excluded_objective_properties(
                relevant_skims=relevant_skims,
                target_properties=target_properties,
            )
            routing_hints = self._build_objective_table_routing_hints(
                objective,
                tables=tables,
                target_property_axes=target_properties,
                variable_process_axes=variable_axes,
            )
            contexts.append(
                ObjectiveContext.from_mapping(
                    {
                        "objective_id": objective.objective_id,
                        "question": objective.question,
                        "material_scope": list(objective.material_scope),
                        "variable_process_axes": variable_axes,
                        "process_context_axes": context_axes,
                        "target_property_axes": target_properties,
                        "excluded_property_axes": excluded_properties,
                        "routing_hints": routing_hints,
                        "extraction_guidance": {
                            "focus": (
                                "Extract current-work evidence that connects "
                                "the variable process axes to the target "
                                "property axes for this objective."
                            ),
                            "do_not_treat_as_variables": context_axes,
                            "do_not_treat_as_result_properties": variable_axes,
                            "do_not_extract_as_target_results": excluded_properties,
                        },
                        "confidence": objective.confidence,
                    }
                )
            )
        return tuple(contexts)

    def _select_relevant_skims(
        self,
        objective: ResearchObjective,
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[PaperSkim, ...]:
        seeded = tuple(
            skim
            for skim in paper_skims
            if skim.document_id in objective.seed_document_ids
        )
        if seeded:
            return seeded
        excluded = set(objective.excluded_document_ids)
        selected = tuple(skim for skim in paper_skims if skim.document_id not in excluded)
        return selected or paper_skims

    def _excluded_objective_properties(
        self,
        *,
        relevant_skims: tuple[PaperSkim, ...],
        target_properties: list[str],
    ) -> list[str]:
        candidates = self._unique_axis_values(
            value
            for skim in relevant_skims
            for value in skim.candidate_properties
        )
        excluded: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if any(
                self._axis_values_match(candidate, target_property)
                for target_property in target_properties
            ):
                continue
            self._append_unique_axis(excluded, seen, candidate)
        return excluded

    def _build_objective_table_routing_hints(
        self,
        objective: ResearchObjective,
        *,
        tables: tuple[Any, ...],
        target_property_axes: list[str],
        variable_process_axes: list[str],
    ) -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []
        selected_document_ids = set(objective.seed_document_ids)
        excluded_document_ids = set(objective.excluded_document_ids)
        for table in tables:
            document_id = str(getattr(table, "document_id", "") or "")
            if document_id in excluded_document_ids:
                continue
            if selected_document_ids and document_id not in selected_document_ids:
                continue
            table_text = self._objective_table_search_text(table)
            matched_property_axes = [
                axis
                for axis in target_property_axes
                if self._source_text_mentions_axis(table_text, axis)
            ]
            matched_variable_axes = [
                axis
                for axis in variable_process_axes
                if self._source_text_mentions_axis(table_text, axis)
            ]
            if matched_property_axes:
                role = "result_table"
                strength = (
                    "strong"
                    if matched_variable_axes or len(matched_property_axes) > 1
                    else "medium"
                )
            elif matched_variable_axes:
                role = "condition_context"
                strength = "strong" if len(matched_variable_axes) > 1 else "medium"
            else:
                continue
            hints.append(
                {
                    "table_id": str(getattr(table, "table_id", "") or ""),
                    "document_id": document_id,
                    "caption_text": getattr(table, "caption_text", None),
                    "role": role,
                    "strength": strength,
                    "matched_property_axes": matched_property_axes,
                    "matched_variable_process_axes": matched_variable_axes,
                    "reason": self._build_objective_table_routing_reason(
                        role,
                        matched_property_axes=matched_property_axes,
                        matched_variable_axes=matched_variable_axes,
                    ),
                }
            )
        return hints

    def _objective_table_search_text(self, table: Any) -> str:
        pieces = [
            str(getattr(table, "caption_text", "") or ""),
            " ".join(str(value) for value in getattr(table, "column_headers", ()) or ()),
        ]
        for row in tuple(getattr(table, "table_matrix", ()) or ())[:6]:
            if isinstance(row, (list, tuple)):
                pieces.append(" ".join(str(cell) for cell in row))
        return " ".join(piece for piece in pieces if piece.strip())

    def _source_text_mentions_axis(self, text: str, axis: str) -> bool:
        text_tokens = self._axis_token_set(self._axis_key(text))
        axis_tokens = self._axis_token_set(self._axis_key(axis))
        if not axis_tokens or not text_tokens:
            return False
        return all(
            any(
                axis_token == text_token
                or self._is_acronym_match(axis_token, text_token)
                or self._axis_token_is_close(axis_token, text_token)
                for text_token in text_tokens
            )
            for axis_token in axis_tokens
        )

    def _axis_token_is_close(self, left: str, right: str) -> bool:
        if left == right:
            return True
        if left.startswith("dens") and right.startswith("dens"):
            return True
        if abs(len(left) - len(right)) > 2:
            return False
        if len(left) < 6 or len(right) < 6:
            return False
        return SequenceMatcher(a=left, b=right).ratio() >= 0.88

    def _build_objective_table_routing_reason(
        self,
        role: str,
        *,
        matched_property_axes: list[str],
        matched_variable_axes: list[str],
    ) -> str:
        if role == "result_table":
            if matched_variable_axes:
                return "Table contains target property columns and variable process columns."
            return "Table contains target property columns."
        return "Table contains variable process columns and can provide condition context."

    def _get_structured_extractor(self) -> CoreLLMStructuredExtractor:
        if self._structured_extractor is None:
            self._structured_extractor = build_default_core_llm_structured_extractor()
        return self._structured_extractor

    def _load_source_artifacts(self, collection_id: str) -> SourceArtifactSet:
        artifacts = self.source_artifact_repository.read_collection_artifacts(
            collection_id
        )
        if not artifacts.documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return artifacts

    def _build_paper_skim_payload(
        self,
        *,
        collection_id: str,
        document: Any,
        profile: Any,
        blocks: list[Any],
        tables: list[Any],
        figures: list[Any],
    ) -> dict[str, Any]:
        ordered_blocks = sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        )
        headings = self._extract_headings(ordered_blocks)
        text_preview = self._build_text_preview(document, ordered_blocks)
        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": document.title,
            "source_filename": self._resolve_source_filename(document),
            "document_profile": profile.to_record() if profile else {},
            "text_preview": text_preview,
            "headings": headings,
            "table_captions": [
                {
                    "table_id": table.table_id,
                    "caption_text": table.caption_text,
                    "heading_path": table.heading_path,
                    "column_headers": list(table.column_headers),
                }
                for table in sorted(tables, key=lambda item: item.table_order)[
                    :_SKIM_CAPTION_LIMIT
                ]
            ],
            "figure_captions": [
                {
                    "figure_id": figure.figure_id,
                    "caption_text": figure.caption_text,
                    "heading_path": figure.heading_path,
                }
                for figure in sorted(figures, key=lambda item: item.figure_order)[
                    :_SKIM_CAPTION_LIMIT
                ]
            ],
        }

    def _extract_headings(self, blocks: list[Any]) -> list[str]:
        headings: list[str] = []
        seen: set[str] = set()
        for block in blocks:
            heading = ""
            if getattr(block, "block_type", "") == "heading":
                heading = str(getattr(block, "text", "") or "").strip()
            if not heading:
                heading = str(getattr(block, "heading_path", "") or "").strip()
            if not heading:
                continue
            key = heading.lower()
            if key in seen:
                continue
            seen.add(key)
            headings.append(heading)
            if len(headings) >= _SKIM_HEADING_LIMIT:
                break
        return headings

    def _build_text_preview(self, document: Any, blocks: list[Any]) -> str:
        parts = [
            str(getattr(block, "text", "") or "").strip()
            for block in blocks
            if str(getattr(block, "text", "") or "").strip()
            and getattr(block, "block_type", "") in {"paragraph", "list_item"}
        ]
        text = "\n\n".join(parts).strip()
        if not text:
            text = str(document.text or "").strip()
        return text[:_SKIM_TEXT_PREVIEW_CHARS]

    def _resolve_source_filename(self, document: Any) -> str | None:
        metadata = getattr(document, "metadata", {}) or {}
        for key in ("source_filename", "original_filename", "stored_filename"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return None

    def _normalize_research_objective(
        self,
        objective: ResearchObjective,
        *,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> ResearchObjective:
        payload = objective.to_record()
        payload["process_axes"] = self._merge_process_axes_from_skims(
            objective,
            skim_by_document_id=skim_by_document_id,
            paper_skims=paper_skims,
        )
        payload["property_axes"] = self._expand_broad_property_axes(
            objective.property_axes,
            objective=objective,
            skim_by_document_id=skim_by_document_id,
            paper_skims=paper_skims,
        )
        if not str(payload.get("comparison_intent") or "").strip():
            payload["comparison_intent"] = self._build_comparison_intent(payload)
        return ResearchObjective.from_mapping(payload)

    def _merge_process_axes_from_skims(
        self,
        objective: ResearchObjective,
        *,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in objective.process_axes:
            self._append_unique_axis(merged, seen, value)

        candidate_skims = [
            skim_by_document_id[document_id]
            for document_id in objective.seed_document_ids
            if document_id in skim_by_document_id
        ]
        if not candidate_skims:
            candidate_skims = list(paper_skims)
        for skim in candidate_skims:
            for value in (*skim.candidate_processes, *skim.changed_variables):
                self._append_unique_axis(merged, seen, value)
        return merged

    def _expand_broad_property_axes(
        self,
        values: tuple[str, ...],
        *,
        objective: ResearchObjective,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> list[str]:
        expanded: list[str] = []
        seen: set[str] = set()
        available_properties = self._available_property_axes(
            objective,
            skim_by_document_id=skim_by_document_id,
            paper_skims=paper_skims,
        )
        for value in values:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            replacements = _BROAD_PROPERTY_AXIS_EXPANSIONS.get(normalized.lower())
            if replacements is None:
                self._append_unique_axis(expanded, seen, normalized)
                continue
            matched_replacements = [
                replacement
                for replacement in replacements
                if self._property_axis_is_available(replacement, available_properties)
            ]
            if not matched_replacements:
                self._append_unique_axis(expanded, seen, normalized)
                continue
            for replacement in matched_replacements:
                self._append_unique_axis(expanded, seen, replacement)
        return expanded

    def _available_property_axes(
        self,
        objective: ResearchObjective,
        *,
        skim_by_document_id: dict[str, PaperSkim],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        candidate_skims = [
            skim_by_document_id[document_id]
            for document_id in objective.seed_document_ids
            if document_id in skim_by_document_id
        ]
        if not candidate_skims:
            candidate_skims = list(paper_skims)
        return {
            self._axis_key(value)
            for skim in candidate_skims
            for value in skim.candidate_properties
            if self._axis_key(value)
        }

    def _property_axis_is_available(
        self,
        replacement: str,
        available_properties: set[str],
    ) -> bool:
        key = self._axis_key(replacement)
        if key in available_properties:
            return True
        if key == "microhardness" and "hardness" in available_properties:
            return True
        if (
            key == "corrosion current density"
            and "current density" in available_properties
        ):
            return True
        return False

    def _canonicalize_research_objective_axes_with_llm(
        self,
        *,
        collection_id: str,
        extractor: CoreLLMStructuredExtractor,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        axis_candidates = self._build_axis_canonicalization_candidates(objectives)
        if sum(len(values) for values in axis_candidates.values()) <= 1:
            return objectives
        payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
            "axis_candidates": axis_candidates,
        }
        try:
            canonicalization_plan = extractor.canonicalize_research_objective_axes(
                payload
            )
        except Exception:
            logger.warning(
                "Research objective axis canonicalization failed; using normalized axes collection_id=%s",
                collection_id,
                exc_info=True,
            )
            return objectives

        axis_mapping = self._validate_axis_canonicalization_plan(
            canonicalization_plan,
            axis_candidates=axis_candidates,
        )
        if axis_mapping is None:
            logger.warning(
                "Research objective axis canonicalization rejected; using normalized axes collection_id=%s",
                collection_id,
            )
            return objectives
        return tuple(
            self._apply_axis_canonicalization(objective, axis_mapping)
            for objective in objectives
        )

    def _build_axis_canonicalization_candidates(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> dict[str, list[str]]:
        return {
            "material": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.material_scope
            ),
            "process": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.process_axes
            ),
            "property": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.property_axes
            ),
        }

    def _validate_axis_canonicalization_plan(
        self,
        canonicalization_plan: StructuredAxisCanonicalizationPlan,
        *,
        axis_candidates: dict[str, list[str]],
    ) -> dict[str, dict[str, str]] | None:
        expected_keys = {
            axis_type: {
                self._axis_key(value)
                for value in values
                if self._axis_key(value)
            }
            for axis_type, values in axis_candidates.items()
        }
        seen_keys: dict[str, set[str]] = {
            axis_type: set()
            for axis_type in expected_keys
        }
        axis_mapping: dict[str, dict[str, str]] = {
            axis_type: {}
            for axis_type in expected_keys
        }

        for group in canonicalization_plan.axis_groups:
            axis_type = group.axis_type
            if axis_type not in expected_keys:
                return None
            aliases = tuple(str(value or "").strip() for value in group.aliases)
            canonical = str(group.canonical or "").strip()
            canonical_key = self._axis_key(canonical)
            alias_keys = tuple(self._axis_key(alias) for alias in aliases)
            if not aliases or not canonical or not canonical_key:
                return None
            if canonical_key not in alias_keys:
                return None
            for alias, alias_key in zip(aliases, alias_keys, strict=True):
                if not alias_key:
                    return None
                if not self._axis_alias_matches_canonical(alias, canonical):
                    return None
                if alias_key not in expected_keys[axis_type]:
                    return None
                if alias_key in seen_keys[axis_type]:
                    return None
                seen_keys[axis_type].add(alias_key)
                axis_mapping[axis_type][alias_key] = canonical

        for axis_type, expected in expected_keys.items():
            if seen_keys[axis_type] != expected:
                return None
        return axis_mapping

    def _apply_axis_canonicalization(
        self,
        objective: ResearchObjective,
        axis_mapping: dict[str, dict[str, str]],
    ) -> ResearchObjective:
        payload = objective.to_record()
        payload["material_scope"] = self._canonicalize_axis_values(
            objective.material_scope,
            axis_type="material",
            axis_mapping=axis_mapping,
        )
        payload["process_axes"] = self._canonicalize_axis_values(
            objective.process_axes,
            axis_type="process",
            axis_mapping=axis_mapping,
        )
        payload["property_axes"] = self._canonicalize_axis_values(
            objective.property_axes,
            axis_type="property",
            axis_mapping=axis_mapping,
        )
        return ResearchObjective.from_mapping(payload)

    def _canonicalize_axis_values(
        self,
        values: tuple[str, ...],
        *,
        axis_type: str,
        axis_mapping: dict[str, dict[str, str]],
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        mapping = axis_mapping.get(axis_type, {})
        for value in values:
            canonical = mapping.get(self._axis_key(value), value)
            self._append_unique_axis(merged, seen, canonical)
        return merged

    def _merge_research_objectives_with_llm(
        self,
        *,
        collection_id: str,
        extractor: CoreLLMStructuredExtractor,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        if len(objectives) <= 1:
            return objectives
        payload = {
            "collection_id": collection_id,
            "paper_skims": [skim.to_record() for skim in paper_skims],
            "candidate_objectives": [objective.to_record() for objective in objectives],
        }
        try:
            merge_plan = extractor.merge_research_objectives(payload)
        except Exception:
            logger.warning(
                "Research objective merge decision failed; using normalized objectives collection_id=%s",
                collection_id,
                exc_info=True,
            )
            return objectives

        merged = self._validate_objective_merge_plan(
            merge_plan,
            objectives=objectives,
            paper_skims=paper_skims,
        )
        if merged is None:
            logger.warning(
                "Research objective merge decision rejected; using normalized objectives collection_id=%s",
                collection_id,
            )
            return objectives
        return merged

    def _validate_objective_merge_plan(
        self,
        merge_plan: StructuredObjectiveMergePlan,
        *,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[ResearchObjective, ...] | None:
        objective_by_id = {objective.objective_id: objective for objective in objectives}
        allowed_material_axes = self._allowed_material_axes(objectives, paper_skims)
        allowed_process_axes = self._allowed_process_axes(objectives, paper_skims)
        allowed_property_axes = self._allowed_property_axes(objectives, paper_skims)
        used_source_ids: set[str] = set()
        merged_objectives: list[ResearchObjective] = []

        for group in merge_plan.merged_objectives:
            source_ids = tuple(
                str(value or "").strip()
                for value in group.source_objective_ids
            )
            if not source_ids:
                return None
            if any(source_id not in objective_by_id for source_id in source_ids):
                return None
            if any(source_id in used_source_ids for source_id in source_ids):
                return None
            used_source_ids.update(source_ids)
            source_objectives = tuple(
                objective_by_id[source_id]
                for source_id in source_ids
            )
            property_components = self._property_overlap_components(source_objectives)
            if len(property_components) > 1:
                for component in property_components:
                    merged_objectives.append(
                        self._build_objective_from_property_component(component)
                    )
                continue

            material_scope = self._validated_merge_axes(
                tuple(group.material_scope),
                allowed_axes=allowed_material_axes,
                source_objectives=source_objectives,
                source_field="material_scope",
            )
            process_axes = self._validated_merge_axes(
                tuple(group.process_axes),
                allowed_axes=allowed_process_axes,
                source_objectives=source_objectives,
                source_field="process_axes",
            )
            property_axes = self._validated_merge_axes(
                tuple(group.property_axes),
                allowed_axes=allowed_property_axes,
                source_objectives=source_objectives,
                source_field="property_axes",
            )
            if material_scope is None or process_axes is None or property_axes is None:
                return None

            payload = {
                "objective_id": build_research_objective_id(group.question),
                "question": group.question,
                "material_scope": material_scope,
                "process_axes": process_axes,
                "property_axes": property_axes,
                "comparison_intent": group.comparison_intent,
                "seed_document_ids": self._merge_objective_axes(
                    source_objectives,
                    "seed_document_ids",
                ),
                "excluded_document_ids": self._merge_objective_axes(
                    source_objectives,
                    "excluded_document_ids",
                ),
                "confidence": group.confidence,
                "reason": group.reason,
            }
            objective = ResearchObjective.from_mapping(payload)
            if not objective.comparison_intent:
                return None
            if not is_question_shaped_objective(objective):
                return None
            merged_objectives.append(objective)

        if used_source_ids != set(objective_by_id):
            return None
        return tuple(merged_objectives)

    def _dedupe_research_objectives(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        deduped: list[ResearchObjective] = []
        seen_objective_ids: set[str] = set()
        for objective in objectives:
            if objective.objective_id in seen_objective_ids:
                continue
            seen_objective_ids.add(objective.objective_id)
            deduped.append(objective)
        return tuple(deduped)

    def _split_mixed_property_objectives(
        self,
        *,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        split_objectives: list[ResearchObjective] = []
        for objective in objectives:
            split_objectives.extend(
                self._split_single_mixed_property_objective(
                    objective,
                    paper_skims=paper_skims,
                )
            )
        return tuple(split_objectives)

    def _split_single_mixed_property_objective(
        self,
        objective: ResearchObjective,
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[ResearchObjective, ...]:
        structural_axes = [
            value
            for value in objective.property_axes
            if self._property_axis_matches_any(value, _STRUCTURAL_PROPERTY_AXES)
        ]
        mechanical_axes = [
            value
            for value in objective.property_axes
            if self._property_axis_matches_any(value, _MECHANICAL_PROPERTY_AXES)
        ]
        grouped_keys = self._axis_key_set(*structural_axes, *mechanical_axes)
        other_axes = [
            value
            for value in objective.property_axes
            if self._axis_key(value) not in grouped_keys
        ]
        if not structural_axes or not mechanical_axes or other_axes:
            return (objective,)

        return (
            self._build_property_split_objective(
                objective,
                property_axes=structural_axes,
                paper_skims=paper_skims,
                reason=(
                    "Split mixed objective to keep structural and densification "
                    "outcomes separate from mechanical-property outcomes."
                ),
            ),
            self._build_property_split_objective(
                objective,
                property_axes=mechanical_axes,
                paper_skims=paper_skims,
                reason=(
                    "Split mixed objective to keep mechanical-property outcomes "
                    "separate from structural and densification outcomes."
                ),
            ),
        )

    def _build_property_split_objective(
        self,
        objective: ResearchObjective,
        *,
        property_axes: list[str],
        paper_skims: tuple[PaperSkim, ...],
        reason: str,
    ) -> ResearchObjective:
        payload = objective.to_record()
        payload["property_axes"] = property_axes
        variable_axes, context_axes = self._split_objective_process_axes(
            objective,
            paper_skims=paper_skims,
        )
        if len(variable_axes) >= 2:
            payload["question"] = self._build_aligned_research_objective_question(
                payload,
                variable_axes=variable_axes,
                context_axes=context_axes,
            )
            payload["comparison_intent"] = self._build_aligned_comparison_intent(
                payload,
                variable_axes=variable_axes,
                context_axes=context_axes,
            )
        else:
            payload["question"] = self._build_research_objective_question(payload)
            payload["comparison_intent"] = self._build_comparison_intent(payload)
        payload["objective_id"] = build_research_objective_id(payload["question"])
        payload["reason"] = reason
        return ResearchObjective.from_mapping(payload)

    def _align_research_objective_text_with_axes(
        self,
        *,
        paper_skims: tuple[PaperSkim, ...],
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ResearchObjective, ...]:
        return tuple(
            self._align_single_research_objective_text(
                objective,
                paper_skims=paper_skims,
            )
            for objective in objectives
        )

    def _align_single_research_objective_text(
        self,
        objective: ResearchObjective,
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> ResearchObjective:
        variable_axes, context_axes = self._split_objective_process_axes(
            objective,
            paper_skims=paper_skims,
        )
        if len(variable_axes) < 2:
            return objective

        question_missing_axes = [
            axis
            for axis in variable_axes
            if not self._axis_label_is_mentioned(objective.question, axis)
        ]
        intent_text = str(objective.comparison_intent or "")
        intent_missing_axes = [
            axis
            for axis in variable_axes
            if not self._axis_label_is_mentioned(intent_text, axis)
        ]
        if not question_missing_axes and not intent_missing_axes:
            return objective

        payload = objective.to_record()
        if question_missing_axes:
            payload["question"] = self._build_aligned_research_objective_question(
                payload,
                variable_axes=variable_axes,
                context_axes=context_axes,
            )
            payload["objective_id"] = build_research_objective_id(
                payload["question"]
            )
        if intent_missing_axes:
            payload["comparison_intent"] = self._build_aligned_comparison_intent(
                payload,
                variable_axes=variable_axes,
                context_axes=context_axes,
            )
        return ResearchObjective.from_mapping(payload)

    def _split_objective_process_axes(
        self,
        objective: ResearchObjective,
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[list[str], list[str]]:
        changed_variables = self._relevant_changed_variables(
            objective,
            paper_skims=paper_skims,
        )
        variable_axes: list[str] = []
        seen_variable_keys: set[str] = set()
        for changed_variable in changed_variables:
            for process_axis in objective.process_axes:
                if self._axis_values_match(process_axis, changed_variable):
                    self._append_unique_axis(
                        variable_axes,
                        seen_variable_keys,
                        process_axis,
                    )
                    break
        for process_axis in objective.process_axes:
            if any(
                self._axis_values_match(process_axis, changed_variable)
                for changed_variable in changed_variables
            ):
                self._append_unique_axis(
                    variable_axes,
                    seen_variable_keys,
                    process_axis,
                )

        context_axes: list[str] = []
        seen_context_keys: set[str] = set()
        for process_axis in objective.process_axes:
            if any(
                self._axis_values_match(process_axis, variable_axis)
                for variable_axis in variable_axes
            ):
                continue
            self._append_unique_axis(context_axes, seen_context_keys, process_axis)
        return variable_axes, context_axes

    def _relevant_changed_variables(
        self,
        objective: ResearchObjective,
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> list[str]:
        seeded_skims = [
            skim
            for skim in paper_skims
            if skim.document_id in objective.seed_document_ids
        ]
        if not seeded_skims:
            seeded_skims = list(paper_skims)
        return self._unique_axis_values(
            value
            for skim in seeded_skims
            for value in skim.changed_variables
        )

    def _build_aligned_research_objective_question(
        self,
        payload: dict[str, Any],
        *,
        variable_axes: list[str],
        context_axes: list[str],
    ) -> str:
        variable_text = self._join_axis_text(variable_axes)
        property_text = (
            self._join_axis_text(payload.get("property_axes"))
            or "the reported outcomes"
        )
        material_text = (
            self._join_axis_text(payload.get("material_scope"))
            or "the material system"
        )
        context_text = self._join_axis_text(context_axes)
        material_phrase = material_text
        if context_text:
            material_phrase = f"{material_phrase} processed via {context_text}"
        return f"How do {variable_text} affect {property_text} of {material_phrase}?"

    def _build_aligned_comparison_intent(
        self,
        payload: dict[str, Any],
        *,
        variable_axes: list[str],
        context_axes: list[str],
    ) -> str:
        material_text = (
            self._join_axis_text(payload.get("material_scope"))
            or "the material system"
        )
        variable_text = self._join_axis_text(variable_axes)
        property_text = (
            self._join_axis_text(payload.get("property_axes"))
            or "the reported outcomes"
        )
        context_text = self._join_axis_text(context_axes)
        context_phrase = f" in {context_text}" if context_text else ""
        return (
            f"Compare {material_text}{context_phrase} across {variable_text} "
            f"and evaluate changes in {property_text}."
        )

    def _property_overlap_components(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[tuple[ResearchObjective, ...], ...]:
        components: list[tuple[list[ResearchObjective], set[str]]] = []
        for objective in objectives:
            current_keys = self._axis_key_set(*objective.property_axes)
            matched_indexes = [
                index
                for index, (_, component_keys) in enumerate(components)
                if current_keys and component_keys.intersection(current_keys)
            ]
            if not matched_indexes:
                components.append(([objective], set(current_keys)))
                continue
            first_index = matched_indexes[0]
            components[first_index][0].append(objective)
            components[first_index][1].update(current_keys)
            for index in reversed(matched_indexes[1:]):
                objectives_to_move, keys_to_move = components.pop(index)
                components[first_index][0].extend(objectives_to_move)
                components[first_index][1].update(keys_to_move)
        return tuple(tuple(component_objectives) for component_objectives, _ in components)

    def _build_objective_from_property_component(
        self,
        objectives: tuple[ResearchObjective, ...],
    ) -> ResearchObjective:
        if len(objectives) == 1:
            return objectives[0]
        payload = {
            "material_scope": self._merge_objective_axes(objectives, "material_scope"),
            "process_axes": self._merge_objective_axes(objectives, "process_axes"),
            "property_axes": self._merge_objective_axes(objectives, "property_axes"),
            "seed_document_ids": self._merge_objective_axes(
                objectives,
                "seed_document_ids",
            ),
            "excluded_document_ids": self._merge_objective_axes(
                objectives,
                "excluded_document_ids",
            ),
            "confidence": max(objective.confidence for objective in objectives),
            "reason": "Merged objectives with overlapping property axes.",
        }
        payload["question"] = self._build_research_objective_question(payload)
        payload["objective_id"] = build_research_objective_id(payload["question"])
        payload["comparison_intent"] = self._build_comparison_intent(payload)
        return ResearchObjective.from_mapping(payload)

    def _validated_merge_axes(
        self,
        values: tuple[str, ...],
        *,
        allowed_axes: set[str],
        source_objectives: tuple[ResearchObjective, ...],
        source_field: str,
    ) -> list[str] | None:
        if not values:
            return self._merge_objective_axes(source_objectives, source_field)
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = self._axis_key(value)
            if not key:
                continue
            if key not in allowed_axes:
                return None
            self._append_unique_axis(merged, seen, value)
        for objective in source_objectives:
            for value in getattr(objective, source_field):
                self._append_unique_axis(merged, seen, value)
        return merged

    def _allowed_material_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        return self._axis_key_set(
            *(
                value
                for objective in objectives
                for value in objective.material_scope
            ),
            *(value for skim in paper_skims for value in skim.candidate_materials),
        )

    def _allowed_process_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        return self._axis_key_set(
            *(value for objective in objectives for value in objective.process_axes),
            *(value for skim in paper_skims for value in skim.candidate_processes),
            *(value for skim in paper_skims for value in skim.changed_variables),
        )

    def _allowed_property_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
    ) -> set[str]:
        return self._axis_key_set(
            *(value for objective in objectives for value in objective.property_axes),
            *(value for skim in paper_skims for value in skim.candidate_properties),
        )

    def _axis_key_set(self, *values: Any) -> set[str]:
        return {self._axis_key(value) for value in values if self._axis_key(value)}

    def _unique_axis_values(self, values: Any) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            self._append_unique_axis(merged, seen, value)
        return merged

    def _merge_objective_axes(
        self,
        objectives: tuple[ResearchObjective, ...],
        field_name: str,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for objective in objectives:
            for value in getattr(objective, field_name):
                self._append_unique_axis(merged, seen, value)
        return merged

    def _build_research_objective_question(self, payload: dict[str, Any]) -> str:
        process_text = (
            self._join_axis_text(payload.get("process_axes"))
            or "the studied process axes"
        )
        property_text = (
            self._join_axis_text(payload.get("property_axes"))
            or "the reported outcomes"
        )
        material_text = (
            self._join_axis_text(payload.get("material_scope"))
            or "the material system"
        )
        return f"How do {process_text} affect {property_text} of {material_text}?"

    def _build_comparison_intent(self, payload: dict[str, Any]) -> str:
        material_text = (
            self._join_axis_text(payload.get("material_scope"))
            or "the material system"
        )
        process_text = (
            self._join_axis_text(payload.get("process_axes"))
            or "the studied process axes"
        )
        property_text = (
            self._join_axis_text(payload.get("property_axes"))
            or "the reported outcomes"
        )
        return (
            f"Compare {material_text} across {process_text} and evaluate changes in "
            f"{property_text}."
        )

    def _append_unique_axis(
        self,
        target: list[str],
        seen: set[str],
        value: Any,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = self._axis_key(text)
        if key in seen:
            return
        seen.add(key)
        target.append(text)

    def _axis_key(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        if text.endswith(")") and "(" in text:
            base, _, suffix = text.rpartition("(")
            acronym = suffix[:-1].strip()
            if base.strip() and acronym.isalpha() and len(acronym) <= 8:
                text = base.strip()
        return " ".join(text.split())

    def _axis_alias_matches_canonical(self, alias: str, canonical: str) -> bool:
        alias_key = self._axis_key(alias)
        canonical_key = self._axis_key(canonical)
        if alias_key == canonical_key:
            return True
        if self._is_acronym_match(alias_key, canonical_key):
            return True
        alias_tokens = self._axis_token_set(alias_key)
        canonical_tokens = self._axis_token_set(canonical_key)
        if not alias_tokens or not canonical_tokens:
            return False
        overlap = alias_tokens & canonical_tokens
        return len(overlap) / max(len(alias_tokens), len(canonical_tokens)) >= 0.75

    def _axis_values_match(self, left: str, right: str) -> bool:
        return self._axis_alias_matches_canonical(left, right)

    def _property_axis_matches_any(
        self,
        value: str,
        candidates: tuple[str, ...],
    ) -> bool:
        return any(self._axis_values_match(value, candidate) for candidate in candidates)

    def _axis_label_is_mentioned(self, text: str, axis: str) -> bool:
        text_tokens = self._axis_token_set(self._axis_key(text))
        axis_tokens = self._axis_token_set(self._axis_key(axis))
        return bool(axis_tokens and axis_tokens.issubset(text_tokens))

    def _is_acronym_match(self, left: str, right: str) -> bool:
        for short, long in ((left, right), (right, left)):
            if len(short) > 8 or not short.isalpha():
                continue
            acronym = "".join(token[0] for token in long.split() if token)
            if acronym and short == acronym:
                return True
        return False

    def _axis_token_set(self, value: str) -> set[str]:
        return {
            self._normalize_axis_token(token)
            for token in value.replace("-", " ").replace("/", " ").split()
            if self._normalize_axis_token(token)
        }

    def _normalize_axis_token(self, token: str) -> str:
        normalized = "".join(char for char in token.casefold() if char.isalnum())
        if len(normalized) > 5 and normalized.endswith("ing"):
            normalized = normalized[:-3]
            if len(normalized) >= 2 and normalized[-1] == normalized[-2]:
                normalized = normalized[:-1]
        if len(normalized) > 4 and normalized.endswith("ies"):
            normalized = f"{normalized[:-3]}y"
        elif len(normalized) > 3 and normalized.endswith("s"):
            normalized = normalized[:-1]
        return normalized

    def _join_axis_text(self, value: Any) -> str:
        if not isinstance(value, list):
            return ""
        items = [str(item).strip() for item in value if str(item).strip()]
        if len(items) <= 1:
            return "".join(items)
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return f"{', '.join(items[:-1])}, and {items[-1]}"

    def _group_by_document_id(self, values: tuple[Any, ...]) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for value in values:
            document_id = str(getattr(value, "document_id", "") or "")
            if not document_id:
                continue
            grouped.setdefault(document_id, []).append(value)
        return grouped


__all__ = [
    "ResearchObjectiveService",
    "ResearchObjectivesNotReadyError",
]
