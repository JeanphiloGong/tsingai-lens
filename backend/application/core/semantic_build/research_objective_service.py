from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha1, sha256
import json
import logging
import math
import os
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from openai import OpenAI

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
    ObjectiveReportArtifact,
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

ProgressCallback = Callable[[dict[str, Any]], None]

_DEFAULT_OBJECTIVE_REPORT_LANGUAGE = "zh"

_SKIM_TEXT_PREVIEW_CHARS = 4000
_SKIM_HEADING_LIMIT = 16
_SKIM_CAPTION_LIMIT = 12
_FRAME_SECTION_SNIPPET_LIMIT = 24
_FRAME_SECTION_TEXT_CHARS = 900
_FRAME_TABLE_LIMIT = 20
_FRAME_TABLE_ROW_LIMIT = 6
_ROUTE_TEXT_CHARS = 1200
_ROUTE_CANDIDATE_LIMIT = 40
_ROUTE_TEXT_CANDIDATE_LIMIT = 12
_ROUTE_TEXT_HINT_LIMIT = 3
_OBJECTIVE_EVIDENCE_TEXT_CHARS = 6000
_OBJECTIVE_RESULT_VALUE_METADATA_KEYS = {
    "value",
    "min",
    "max",
    "retention_percent",
    "direction",
    "statement",
    "value_origin",
    "source_value_text",
    "source_unit_text",
    "derivation_formula",
    "derivation_inputs",
}
_OBJECTIVE_NON_RESULT_VALUE_COLUMN_TERMS = (
    "standard deviation",
    "std",
    "sd",
    "variance",
    "error bar",
    "condition number",
    "sample number",
)
_OBJECTIVE_EXTRACTABLE_ROUTE_ROLES = {
    "current_experimental_evidence",
    "process_or_treatment",
    "test_condition",
    "characterization",
}
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
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
    "corrosion resistance": (
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
_OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES = frozenset(
    {"density", "relative density"}
)
_OBJECTIVE_PROPERTY_ALIASES = {
    "ductility": "elongation",
    "el": "elongation",
    "el%": "elongation",
    "elongation to failure": "elongation",
    "e corr": "corrosion potential",
    "ecorr": "corrosion potential",
    "e p": "pitting potential",
    "ep": "pitting potential",
    "i corr": "corrosion current density",
    "icorr": "corrosion current density",
    "current density": "corrosion current density",
    "i u": "ultimate tensile strength",
    "iu": "ultimate tensile strength",
    "sigma u": "ultimate tensile strength",
    "ultimate tensile": "ultimate tensile strength",
    "uts": "ultimate tensile strength",
    "\u0131 u": "ultimate tensile strength",
    "\u0131u": "ultimate tensile strength",
    "\u03c3 u": "ultimate tensile strength",
    "\u03c3u": "ultimate tensile strength",
    "i y": "yield strength",
    "iy": "yield strength",
    "sigma y": "yield strength",
    "\u0131 y": "yield strength",
    "\u0131y": "yield strength",
    "\u03c3 y": "yield strength",
    "\u03c3y": "yield strength",
}
_OBJECTIVE_PAIRWISE_TENSILE_PROPERTIES = (
    "yield strength",
    "ultimate tensile strength",
)
_OBJECTIVE_PAIRWISE_DUCTILITY_PROPERTY = "elongation"
_OBJECTIVE_PAIRWISE_DENSITY_MIN_DELTA = 2.0
_OBJECTIVE_PAIRWISE_ELONGATION_MIN_DELTA = 3.4
_OBJECTIVE_PAIRWISE_LARGE_SCOPE_LIMIT = 48
_OBJECTIVE_PAIRWISE_GROUP_LIMIT = 3
_OBJECTIVE_METHOD_FAMILY_PROPERTY_TYPES = (
    "tensile_mechanics",
    "microhardness",
    "density_porosity_microstructure",
)
_OBJECTIVE_GENERIC_RESULT_ROLE_TOKENS = frozenset(
    {
        "current",
        "evidence",
        "experimental",
        "measurement",
        "predicted",
        "prediction",
        "property",
        "result",
        "target",
    }
)
_OBJECTIVE_GENERIC_PROCESS_ROLE_TOKENS = frozenset(
    {
        "axis",
        "context",
        "parameter",
        "process",
        "variable",
    }
)
_OBJECTIVE_PRESERVED_PROPERTY_QUALIFIERS = frozenset(
    {
        "experiment",
        "experimental",
        "model",
        "predicted",
        "prediction",
    }
)
_OBJECTIVE_SINGLE_TOKEN_PROPERTY_QUALIFIERS = frozenset(
    {
        "average",
        "material",
        "relative",
        "surface",
        "total",
        "uniform",
    }
)
_OBJECTIVE_TENSILE_METHOD_PROPERTIES = frozenset(
    {
        "yield strength",
        "ultimate tensile strength",
        "tensile strength",
        "strength",
        "elongation",
        "modulus",
    }
)
_OBJECTIVE_MICROHARDNESS_METHOD_PROPERTIES = frozenset(
    {"hardness", "microhardness"}
)
_OBJECTIVE_CHARACTERIZATION_METHOD_PROPERTIES = frozenset(
    {
        "density",
        "relative density",
        "densification",
        "porosity",
        "grain size",
        "microstructure",
        "grain size primary dendrite spacing",
    }
)


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


class ResearchObjectiveReportNotFoundError(FileNotFoundError):
    """Raised when an objective report has not been requested yet."""

    def __init__(self, collection_id: str, objective_id: str) -> None:
        self.collection_id = collection_id
        self.objective_id = objective_id
        super().__init__(f"research objective report not found: {collection_id}/{objective_id}")


class ResearchObjectiveService:
    """Build and serve Core research-objective records."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        structured_extractor: CoreLLMStructuredExtractor | None = None,
        core_fact_repository: CoreFactRepository | None = None,
        source_artifact_repository: SourceArtifactRepository | None = None,
        document_profile_service: DocumentProfileService | None = None,
        llm_client: Any | None = None,
        report_model: str | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self._structured_extractor = structured_extractor
        self.report_model = (
            report_model
            or os.getenv("OBJECTIVE_REPORT_LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or "gpt-4o-mini"
        ).strip()
        self._report_llm_client = llm_client
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
            self._objective_list_item(
                self._display_objective_from_facts(objective, facts=facts),
                facts=facts,
            )
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
        objective = self._display_objective_from_facts(objective, facts=facts)

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
        raw_evidence_units = [
            unit
            for unit in facts.objective_evidence_units
            if unit.objective_id == objective_id
        ]
        evidence_units = self._objective_detail_evidence_units(
            tuple(raw_evidence_units),
            objective_context=context,
        )
        logic_chains = [
            chain
            for chain in facts.objective_logic_chains
            if chain.objective_id == objective_id
        ]
        logic_chain = self._objective_detail_logic_chain(
            objective=objective,
            objective_context=context,
            source_logic_chain=self._select_objective_logic_chain(logic_chains),
            evidence_units=evidence_units,
        )
        frame_views = self._objective_paper_frame_views(frames, facts=facts)
        report_artifact = self.core_fact_repository.read_objective_report_artifact(
            collection_id,
            objective_id,
        )

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
            "paper_frames": frame_views,
            "evidence_routes": routes,
            "evidence_units": [unit.to_record() for unit in evidence_units],
            "logic_chain": logic_chain.to_record() if logic_chain is not None else None,
            "conclusion_package": self._objective_conclusion_package(
                objective=objective,
                objective_context=context,
                frame_views=frame_views,
                evidence_units=evidence_units,
                logic_chain=logic_chain,
            ),
            "objective_report": (
                self._objective_report_response(collection_id, report_artifact)
                if report_artifact is not None
                else None
            ),
            "existing_comparison_rows": [],
            "warnings": [],
        }

    def request_objective_report(
        self,
        collection_id: str,
        objective_id: str,
        *,
        language: str = _DEFAULT_OBJECTIVE_REPORT_LANGUAGE,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        existing = self.core_fact_repository.read_objective_report_artifact(
            collection_id,
            objective_id,
        )
        if existing is not None and not force_regenerate:
            return self._objective_report_response(collection_id, existing)

        context = self._build_objective_report_context(collection_id, objective_id)
        now = self._now_iso()
        artifact = ObjectiveReportArtifact.from_mapping(
            {
                "report_id": f"orp_{uuid4().hex[:12]}",
                "objective_id": objective_id,
                "status": "generating",
                "stage": "requested",
                "message": "Objective report generation started.",
                "title": context["objective"]["question"],
                "language": language,
                "model": self.report_model,
                "data_version": self._objective_report_data_version(context),
                "markdown": None,
                "warnings": [],
                "source_refs": context["source_refs"],
                "created_at": now,
                "updated_at": now,
                "generated_at": None,
            }
        )
        self.core_fact_repository.upsert_objective_report_artifact(
            collection_id,
            artifact,
        )
        return self._objective_report_response(collection_id, artifact)

    def generate_objective_report(
        self,
        collection_id: str,
        objective_id: str,
        *,
        language: str = _DEFAULT_OBJECTIVE_REPORT_LANGUAGE,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        requested = self.request_objective_report(
            collection_id,
            objective_id,
            language=language,
            force_regenerate=force_regenerate,
        )
        if requested["status"] in {"ready", "ready_with_warnings"} and not force_regenerate:
            return requested
        if requested["status"] == "failed" and not force_regenerate:
            return requested

        context = self._build_objective_report_context(collection_id, objective_id)
        existing = self.core_fact_repository.read_objective_report_artifact(
            collection_id,
            objective_id,
        )
        if existing is None:
            raise ResearchObjectiveReportNotFoundError(collection_id, objective_id)

        try:
            markdown = self._generate_objective_report_markdown(
                context,
                language=language,
            )
            if not markdown:
                raise RuntimeError("objective report generation returned empty markdown")
            warnings = self._objective_report_warnings(context, markdown)
            status = "ready_with_warnings" if warnings else "ready"
            now = self._now_iso()
            artifact = ObjectiveReportArtifact.from_mapping(
                {
                    **existing.to_record(),
                    "status": status,
                    "stage": status,
                    "message": (
                        "Objective report generated with evidence warnings."
                        if warnings
                        else "Objective report generated."
                    ),
                    "title": self._extract_objective_report_title(markdown)
                    or existing.title,
                    "language": language,
                    "model": self.report_model,
                    "data_version": self._objective_report_data_version(context),
                    "markdown": markdown,
                    "warnings": warnings,
                    "source_refs": context["source_refs"],
                    "updated_at": now,
                    "generated_at": now,
                }
            )
            self.core_fact_repository.upsert_objective_report_artifact(
                collection_id,
                artifact,
            )
            return self._objective_report_response(collection_id, artifact)
        except Exception as exc:
            now = self._now_iso()
            failed = ObjectiveReportArtifact.from_mapping(
                {
                    **existing.to_record(),
                    "status": "failed",
                    "stage": "failed",
                    "message": str(exc),
                    "updated_at": now,
                }
            )
            self.core_fact_repository.upsert_objective_report_artifact(
                collection_id,
                failed,
            )
            raise

    def get_objective_report_status(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        artifact = self.core_fact_repository.read_objective_report_artifact(
            collection_id,
            objective_id,
        )
        if artifact is None:
            raise ResearchObjectiveReportNotFoundError(collection_id, objective_id)
        return self._objective_report_response(collection_id, artifact)

    def build_research_objectives(
        self,
        collection_id: str,
        progress_callback: ProgressCallback | None = None,
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
        table_cells_by_document_id = self._group_by_document_id(artifacts.table_cells)
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
            self._notify_progress(
                progress_callback,
                phase="objective_paper_skim_started",
                current=document_position,
                total=document_count,
                unit="documents",
                message="Scanning papers for candidate research objectives.",
                active_document_id=document.document_id,
            )
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
        self._notify_progress(
            progress_callback,
            phase="objective_discovery_started",
            current=0,
            total=1,
            unit="steps",
            message="Merging paper skims into collection research objectives.",
        )
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
            progress_callback=progress_callback,
        )
        objective_evidence_routes = self._build_objective_evidence_routes(
            collection_id=collection_id,
            extractor=extractor,
            objectives=research_objectives,
            objective_contexts=objective_contexts,
            objective_paper_frames=objective_paper_frames,
            blocks_by_document_id=blocks_by_document_id,
            tables_by_document_id=tables_by_document_id,
            progress_callback=progress_callback,
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
            table_cells_by_document_id=table_cells_by_document_id,
            progress_callback=progress_callback,
        )
        objective_logic_chains = self._build_objective_logic_chains(
            collection_id=collection_id,
            objectives=research_objectives,
            objective_contexts=objective_contexts,
            objective_evidence_units=objective_evidence_units,
            progress_callback=progress_callback,
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

    def _notify_progress(
        self,
        progress_callback: ProgressCallback | None,
        **progress_detail: Any,
    ) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(progress_detail)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Research objective progress callback failed phase=%s",
                progress_detail.get("phase"),
            )

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

    def _objective_detail_evidence_units(
        self,
        evidence_units: tuple[ObjectiveEvidenceUnit, ...],
        *,
        objective_context: ObjectiveContext | None,
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        if (
            objective_context is None
            or not objective_context.target_property_axes
            or not evidence_units
        ):
            return evidence_units
        target_axes = self._objective_target_property_axes(objective_context)
        if not target_axes:
            return evidence_units

        target_units = tuple(
            unit
            for unit in evidence_units
            if self._objective_evidence_unit_matches_target_property(
                unit,
                target_axes=target_axes,
            )
        )
        if not target_units:
            return target_units

        target_document_ids = {unit.document_id for unit in target_units}
        target_source_refs = {
            (
                str(source_ref.get("source_kind") or ""),
                str(source_ref.get("source_ref") or ""),
            )
            for unit in target_units
            for source_ref in unit.source_refs
            if source_ref.get("source_ref")
        }
        selected_ids = {unit.evidence_unit_id for unit in target_units}
        selected = list(target_units)
        for unit in evidence_units:
            if unit.evidence_unit_id in selected_ids or unit.property_normalized:
                continue
            if unit.unit_kind not in {
                "process_context",
                "sample_context",
                "test_condition",
            }:
                continue
            source_refs = {
                (
                    str(source_ref.get("source_kind") or ""),
                    str(source_ref.get("source_ref") or ""),
                )
                for source_ref in unit.source_refs
                if source_ref.get("source_ref")
            }
            if unit.document_id in target_document_ids and (
                not source_refs or bool(source_refs & target_source_refs)
            ):
                selected.append(unit)
                selected_ids.add(unit.evidence_unit_id)
        return tuple(selected)

    def _objective_evidence_unit_matches_target_property(
        self,
        unit: ObjectiveEvidenceUnit,
        *,
        target_axes: tuple[str, ...],
    ) -> bool:
        if self._objective_evidence_unit_is_relative_change_interpretation(unit):
            return False
        if (
            unit.unit_kind == "measurement"
            and self._objective_measurement_numeric_value(unit) is None
        ):
            return False
        if self._objective_property_matches_target_axes(
            unit.property_normalized,
            target_axes=target_axes,
        ):
            return True
        if unit.unit_kind in {"test_condition", "sample_context", "process_context"}:
            return False
        text = " ".join(
            value
            for value in (
                self._value_payload_text(unit.value_payload),
                unit.interpretation,
            )
            if value
        )
        return any(
            self._axis_label_is_mentioned(text, axis)
            for axis in target_axes
        )

    def _objective_evidence_unit_is_relative_change_interpretation(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> bool:
        if unit.unit_kind != "interpretation" or unit.baseline_context:
            return False
        text = " ".join(
            value
            for value in (
                self._value_payload_text(unit.value_payload),
                unit.interpretation,
            )
            if value
        )
        if not text:
            return False
        property_name = self._normalize_property_label(unit.property_normalized)
        if property_name != "elongation" and not re.search(
            r"\b(?:ductility|elongation)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return False
        return bool(
            re.search(
                r"\b(?:increase[sd]?|decrease[sd]?|improve[sd]?|reduce[sd]?)\b",
                text,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\bby\s+(?:about\s+|approximately\s+|approx\.?\s+|~\s*)?"
                r"\d+(?:\.\d+)?\s*%",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _objective_property_matches_target_axes(
        self,
        property_name: Any,
        *,
        target_axes: tuple[str, ...],
    ) -> bool:
        normalized = self._normalize_property_label(property_name)
        if not normalized:
            return False
        if self._objective_property_label_matches_target(
            normalized,
            target_axes=target_axes,
        ):
            return True
        expanded_axes = _BROAD_PROPERTY_AXIS_EXPANSIONS.get(normalized, ())
        return any(
            self._objective_property_label_matches_target(
                expanded_axis,
                target_axes=target_axes,
            )
            for expanded_axis in expanded_axes
        )

    def _objective_detail_logic_chain(
        self,
        *,
        objective: ResearchObjective,
        objective_context: ObjectiveContext | None,
        source_logic_chain: ObjectiveLogicChain | None,
        evidence_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> ObjectiveLogicChain | None:
        if source_logic_chain is None or not evidence_units:
            return None
        chain_payload = self._objective_logic_chain_payload(
            objective=objective,
            objective_context=objective_context,
            units=evidence_units,
        )
        return ObjectiveLogicChain.from_mapping(
            {
                "logic_chain_id": source_logic_chain.logic_chain_id,
                "objective_id": objective.objective_id,
                "chain_scope": source_logic_chain.chain_scope,
                "document_id": source_logic_chain.document_id,
                "question": objective.question,
                "evidence_unit_ids": [
                    unit.evidence_unit_id
                    for unit in evidence_units
                ],
                "chain_payload": chain_payload,
                "summary": self._objective_logic_chain_summary(chain_payload),
                "confidence": source_logic_chain.confidence,
            }
        )

    def _objective_conclusion_package(
        self,
        *,
        objective: ResearchObjective,
        objective_context: ObjectiveContext | None,
        frame_views: list[dict[str, Any]],
        evidence_units: tuple[ObjectiveEvidenceUnit, ...],
        logic_chain: ObjectiveLogicChain | None,
    ) -> dict[str, Any]:
        measurements = tuple(
            unit for unit in evidence_units if unit.unit_kind == "measurement"
        )
        comparisons = tuple(
            unit for unit in evidence_units if unit.unit_kind == "comparison"
        )
        mechanism_units = tuple(
            unit
            for unit in evidence_units
            if unit.unit_kind in {"characterization", "interpretation"}
        )
        measurement_ranges = self._objective_measurement_value_ranges(measurements)
        limitations = self._objective_conclusion_limitations(
            measurements=measurements,
            comparisons=comparisons,
            mechanism_units=mechanism_units,
        )
        paper_contributions = self._objective_conclusion_paper_contributions(
            frame_views=frame_views,
            evidence_units=evidence_units,
        )
        primary_evidence_tables = [
            {
                "table_id": "measurement-results",
                "title": "Measurement results",
                "rows": [
                    self._objective_conclusion_measurement_row(unit)
                    for unit in measurements
                ],
                "measurement_value_ranges": measurement_ranges,
            }
        ]
        controlled_comparisons = [
            self._objective_conclusion_comparison(unit)
            for unit in comparisons
        ]
        mechanism_chain = self._objective_conclusion_mechanism_chain(
            mechanism_units
        )
        conclusions = self._objective_conclusion_statements(
            measurement_ranges=measurement_ranges,
            comparisons=comparisons,
            mechanism_units=mechanism_units,
        )
        source_refs = self._objective_conclusion_source_refs(
            evidence_units,
            paper_contributions=paper_contributions,
        )
        status = self._objective_conclusion_status(
            measurements=measurements,
            logic_chain=logic_chain,
        )
        narrative_sections = self._objective_conclusion_narrative_sections(
            objective=objective,
            paper_contributions=paper_contributions,
            measurement_ranges=measurement_ranges,
            primary_evidence_tables=primary_evidence_tables,
            controlled_comparisons=controlled_comparisons,
            mechanism_chain=mechanism_chain,
            conclusions=conclusions,
            limitations=limitations,
            source_refs=source_refs,
        )
        traceability = self._objective_conclusion_traceability(narrative_sections)
        expert_report = self._objective_expert_report(
            objective=objective,
            status=status,
            paper_contributions=paper_contributions,
            measurement_ranges=measurement_ranges,
            primary_evidence_tables=primary_evidence_tables,
            controlled_comparisons=controlled_comparisons,
            mechanism_chain=mechanism_chain,
            conclusions=conclusions,
            limitations=limitations,
            source_refs=source_refs,
            traceability=traceability,
        )
        return {
            "schema_version": "objective_conclusion_package.v1",
            "title": objective.question,
            "objective": {
                "objective_id": objective.objective_id,
                "question": objective.question,
                "material_scope": list(objective.material_scope),
                "process_axes": list(objective.process_axes),
                "property_axes": (
                    list(objective_context.target_property_axes)
                    if objective_context is not None
                    else list(objective.property_axes)
                ),
            },
            "status": status,
            "narrative": {
                "status": (
                    "ready"
                    if narrative_sections and not traceability["unsupported_claim_count"]
                    else "limited"
                ),
                "sections": narrative_sections,
            },
            "paper_contributions": paper_contributions,
            "primary_evidence_tables": primary_evidence_tables,
            "controlled_comparisons": controlled_comparisons,
            "mechanism_chain": mechanism_chain,
            "conclusions": conclusions,
            "limitations": limitations,
            "source_refs": source_refs,
            "traceability": traceability,
            "expert_report": expert_report,
        }

    def _objective_expert_report(
        self,
        *,
        objective: ResearchObjective,
        status: str,
        paper_contributions: list[dict[str, Any]],
        measurement_ranges: list[dict[str, Any]],
        primary_evidence_tables: list[dict[str, Any]],
        controlled_comparisons: list[dict[str, Any]],
        mechanism_chain: dict[str, Any],
        conclusions: list[dict[str, Any]],
        limitations: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
        traceability: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": "objective_expert_report.v1",
            "status": status,
            "headline_conclusion": self._objective_conclusion_answer(
                objective=objective,
                paper_contributions=paper_contributions,
                measurement_ranges=measurement_ranges,
                controlled_comparisons=controlled_comparisons,
                mechanism_chain=mechanism_chain,
                limitations=limitations,
            ),
            "scientific_context": self._objective_conclusion_context_summary(
                objective=objective,
                paper_contributions=paper_contributions,
            ),
            "key_findings": self._objective_expert_key_findings(
                conclusions=conclusions,
                source_refs=source_refs,
            ),
            "evidence_matrix": self._objective_expert_evidence_matrix(
                paper_contributions=paper_contributions,
                measurement_ranges=measurement_ranges,
                primary_evidence_tables=primary_evidence_tables,
                controlled_comparisons=controlled_comparisons,
                mechanism_chain=mechanism_chain,
                limitations=limitations,
                source_refs=source_refs,
            ),
            "paper_contribution_map": self._objective_expert_paper_contribution_map(
                paper_contributions=paper_contributions,
                source_refs=source_refs,
            ),
            "controlled_comparisons": self._objective_expert_controlled_comparisons(
                controlled_comparisons=controlled_comparisons,
                source_refs=source_refs,
            ),
            "mechanism_chain": self._objective_expert_mechanism_chain(
                mechanism_chain=mechanism_chain,
                source_refs=source_refs,
            ),
            "limitations": self._objective_expert_limitations(
                limitations=limitations,
                source_refs=source_refs,
            ),
            "source_traceback": self._objective_expert_source_traceback(source_refs),
            "traceability": traceability,
        }

    def _objective_expert_key_findings(
        self,
        *,
        conclusions: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for index, conclusion in enumerate(conclusions, start=1):
            statement = str(conclusion.get("claim") or "").strip()
            if not statement:
                continue
            evidence_unit_ids = self._dedupe_preserving_order(
                [
                    str(evidence_unit_id or "")
                    for evidence_unit_id in conclusion.get("evidence_unit_ids", [])
                ]
            )
            findings.append(
                {
                    key: value
                    for key, value in {
                        "finding_id": f"finding-{index:03d}",
                        "statement": statement,
                        "strength": conclusion.get("strength") or "evidence",
                        "evidence_unit_ids": evidence_unit_ids,
                        "source_refs": self._objective_source_refs_for_evidence_ids(
                            source_refs,
                            evidence_unit_ids,
                        ),
                    }.items()
                    if value not in (None, "", [], {})
                }
            )
        return findings

    def _objective_expert_evidence_matrix(
        self,
        *,
        paper_contributions: list[dict[str, Any]],
        measurement_ranges: list[dict[str, Any]],
        primary_evidence_tables: list[dict[str, Any]],
        controlled_comparisons: list[dict[str, Any]],
        mechanism_chain: dict[str, Any],
        limitations: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        measurement_result_count = sum(
            len(table.get("rows", []))
            for table in primary_evidence_tables
        )
        return {
            "relevant_paper_count": len(paper_contributions),
            "measurement_result_count": measurement_result_count,
            "measurement_property_count": len(measurement_ranges),
            "controlled_comparison_count": len(controlled_comparisons),
            "mechanism_evidence_count": len(mechanism_chain.get("evidence", [])),
            "limitation_count": len(limitations),
            "source_ref_count": len(source_refs),
            "measurement_value_ranges": measurement_ranges,
        }

    def _objective_expert_paper_contribution_map(
        self,
        *,
        paper_contributions: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        contribution_map: list[dict[str, Any]] = []
        for contribution in paper_contributions:
            evidence_unit_ids = self._dedupe_preserving_order(
                [
                    str(evidence_unit_id or "")
                    for evidence_unit_id in contribution.get("evidence_unit_ids", [])
                ]
            )
            contribution_map.append(
                {
                    key: value
                    for key, value in {
                        "document_id": contribution.get("document_id"),
                        "paper_label": contribution.get("paper_label"),
                        "display_title": contribution.get("display_title"),
                        "paper_role": contribution.get("paper_role"),
                        "relevance": contribution.get("relevance"),
                        "contribution_summary": self._objective_contribution_claim(
                            contribution
                        ),
                        "changed_variables": contribution.get("changed_variables"),
                        "measured_property_scope": contribution.get(
                            "measured_property_scope"
                        ),
                        "evidence_unit_count": contribution.get("evidence_unit_count"),
                        "evidence_unit_ids": evidence_unit_ids,
                        "source_refs": self._objective_source_refs_for_evidence_ids(
                            source_refs,
                            evidence_unit_ids,
                        ),
                    }.items()
                    if value not in (None, "", [], {})
                }
            )
        return contribution_map

    def _objective_expert_controlled_comparisons(
        self,
        *,
        controlled_comparisons: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        report_comparisons: list[dict[str, Any]] = []
        for index, comparison in enumerate(controlled_comparisons, start=1):
            evidence_unit_id = str(comparison.get("evidence_unit_id") or "")
            source_ref_items = self._objective_source_refs_for_evidence_ids(
                source_refs,
                [evidence_unit_id],
            )
            report_comparisons.append(
                {
                    key: value
                    for key, value in {
                        "comparison_id": f"comparison-{index:03d}",
                        "evidence_unit_id": evidence_unit_id,
                        "document_id": comparison.get("document_id"),
                        "property": comparison.get("property"),
                        "comparison_axis": comparison.get("comparison_axis"),
                        "direction": comparison.get("direction"),
                        "validity": comparison.get("validity"),
                        "summary": comparison.get("summary"),
                        "sample_context": comparison.get("sample_context"),
                        "process_context": comparison.get("process_context"),
                        "baseline_context": comparison.get("baseline_context"),
                        "source_refs": source_ref_items,
                    }.items()
                    if value not in (None, "", [], {})
                }
            )
        return report_comparisons

    def _objective_expert_mechanism_chain(
        self,
        *,
        mechanism_chain: dict[str, Any],
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        report_evidence: list[dict[str, Any]] = []
        for evidence in mechanism_chain.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            evidence_unit_id = str(evidence.get("evidence_unit_id") or "")
            value_payload = evidence.get("value_payload")
            summary = (
                self._value_payload_text(value_payload)
                if isinstance(value_payload, dict)
                else None
            )
            report_evidence.append(
                {
                    key: value
                    for key, value in {
                        "evidence_unit_id": evidence_unit_id,
                        "document_id": evidence.get("document_id"),
                        "unit_kind": evidence.get("unit_kind"),
                        "property": evidence.get("property_normalized"),
                        "summary": summary or evidence.get("interpretation"),
                        "sample_context": evidence.get("sample_context"),
                        "process_context": evidence.get("process_context"),
                        "source_refs": self._objective_source_refs_for_evidence_ids(
                            source_refs,
                            [evidence_unit_id],
                        ),
                    }.items()
                    if value not in (None, "", [], {})
                }
            )
        return {
            "steps": list(mechanism_chain.get("steps", [])),
            "evidence": report_evidence,
            "evidence_unit_ids": list(mechanism_chain.get("evidence_unit_ids", [])),
        }

    def _objective_expert_limitations(
        self,
        *,
        limitations: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        report_limitations: list[dict[str, Any]] = []
        for limitation in limitations:
            evidence_unit_ids = self._dedupe_preserving_order(
                [
                    str(evidence_unit_id or "")
                    for evidence_unit_id in limitation.get("evidence_unit_ids", [])
                ]
            )
            report_limitations.append(
                {
                    key: value
                    for key, value in {
                        "code": limitation.get("code"),
                        "message": limitation.get("message"),
                        "evidence_unit_ids": evidence_unit_ids,
                        "source_refs": self._objective_source_refs_for_evidence_ids(
                            source_refs,
                            evidence_unit_ids,
                        ),
                    }.items()
                    if value not in (None, "", [], {})
                }
            )
        return report_limitations

    def _objective_expert_source_traceback(
        self,
        source_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                key: value
                for key, value in {
                    "evidence_unit_id": source_ref.get("evidence_unit_id"),
                    "document_id": source_ref.get("document_id"),
                    "display_label": source_ref.get("display_label"),
                    "source_kind": source_ref.get("source_kind"),
                    "source_ref": source_ref.get("source_ref"),
                    "page": source_ref.get("page") or source_ref.get("page_number"),
                    "anchor_id": source_ref.get("anchor_id"),
                    "route_id": source_ref.get("route_id"),
                    "role": source_ref.get("role"),
                }.items()
                if value not in (None, "", [], {})
            }
            for source_ref in source_refs
        ]

    def _objective_conclusion_narrative_sections(
        self,
        *,
        objective: ResearchObjective,
        paper_contributions: list[dict[str, Any]],
        measurement_ranges: list[dict[str, Any]],
        primary_evidence_tables: list[dict[str, Any]],
        controlled_comparisons: list[dict[str, Any]],
        mechanism_chain: dict[str, Any],
        conclusions: list[dict[str, Any]],
        limitations: list[dict[str, Any]],
        source_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "section_id": "answer",
                "title": "Answer",
                "body": self._objective_conclusion_answer(
                    objective=objective,
                    paper_contributions=paper_contributions,
                    measurement_ranges=measurement_ranges,
                    controlled_comparisons=controlled_comparisons,
                    mechanism_chain=mechanism_chain,
                    limitations=limitations,
                ),
                "claims": [],
                "evidence_unit_ids": self._dedupe_preserving_order(
                    [
                        evidence_unit_id
                        for statement in conclusions
                        for evidence_unit_id in statement.get("evidence_unit_ids", [])
                    ]
                ),
                "source_refs": self._objective_source_refs_for_evidence_ids(
                    source_refs,
                    [
                        evidence_unit_id
                        for statement in conclusions
                        for evidence_unit_id in statement.get("evidence_unit_ids", [])
                    ],
                ),
            },
            {
                "section_id": "research_context",
                "title": "Research context",
                "body": self._objective_conclusion_context_summary(
                    objective=objective,
                    paper_contributions=paper_contributions,
                ),
                "claims": [],
                "evidence_unit_ids": [],
                "source_refs": [],
            },
            {
                "section_id": "key_evidence",
                "title": "Key evidence",
                "body": self._objective_conclusion_evidence_summary(
                    measurement_ranges=measurement_ranges,
                    primary_evidence_tables=primary_evidence_tables,
                ),
                "claims": [
                    self._objective_traceable_claim(
                        statement,
                        source_refs=source_refs,
                    )
                    for statement in conclusions
                ],
                "evidence_unit_ids": self._dedupe_preserving_order(
                    [
                        evidence_unit_id
                        for statement in conclusions
                        for evidence_unit_id in statement.get("evidence_unit_ids", [])
                    ]
                ),
                "source_refs": self._objective_source_refs_for_evidence_ids(
                    source_refs,
                    [
                        evidence_unit_id
                        for statement in conclusions
                        for evidence_unit_id in statement.get("evidence_unit_ids", [])
                    ],
                ),
            },
            {
                "section_id": "paper_contributions",
                "title": "Paper contributions",
                "body": self._objective_conclusion_paper_summary(paper_contributions),
                "claims": [
                    self._objective_traceable_claim(
                        {
                            "claim": self._objective_contribution_claim(contribution),
                            "evidence_unit_ids": contribution.get("evidence_unit_ids", []),
                            "strength": "paper_contribution",
                        },
                        source_refs=source_refs,
                    )
                    for contribution in paper_contributions
                    if contribution.get("evidence_unit_ids")
                ],
                "evidence_unit_ids": self._dedupe_preserving_order(
                    [
                        evidence_unit_id
                        for contribution in paper_contributions
                        for evidence_unit_id in contribution.get("evidence_unit_ids", [])
                    ]
                ),
                "source_refs": self._objective_source_refs_for_evidence_ids(
                    source_refs,
                    [
                        evidence_unit_id
                        for contribution in paper_contributions
                        for evidence_unit_id in contribution.get("evidence_unit_ids", [])
                    ],
                ),
            },
            {
                "section_id": "controlled_comparisons",
                "title": "Controlled comparisons",
                "body": self._objective_conclusion_comparison_summary(
                    controlled_comparisons
                ),
                "claims": [
                    self._objective_traceable_claim(
                        {
                            "claim": comparison.get("summary"),
                            "evidence_unit_ids": [comparison.get("evidence_unit_id")],
                            "strength": comparison.get("validity") or "comparison",
                        },
                        source_refs=source_refs,
                    )
                    for comparison in controlled_comparisons
                    if comparison.get("summary")
                ],
                "evidence_unit_ids": self._dedupe_preserving_order(
                    [
                        str(comparison.get("evidence_unit_id") or "")
                        for comparison in controlled_comparisons
                    ]
                ),
                "source_refs": self._objective_source_refs_for_evidence_ids(
                    source_refs,
                    [
                        str(comparison.get("evidence_unit_id") or "")
                        for comparison in controlled_comparisons
                    ],
                ),
            },
            {
                "section_id": "mechanism_chain",
                "title": "Mechanism chain",
                "body": self._objective_conclusion_mechanism_summary(mechanism_chain),
                "claims": [
                    self._objective_traceable_claim(
                        {
                            "claim": evidence.get("summary"),
                            "evidence_unit_ids": [evidence.get("evidence_unit_id")],
                            "strength": "mechanism",
                        },
                        source_refs=source_refs,
                    )
                    for evidence in mechanism_chain.get("evidence", [])
                    if evidence.get("summary")
                ],
                "evidence_unit_ids": list(mechanism_chain.get("evidence_unit_ids", [])),
                "source_refs": self._objective_source_refs_for_evidence_ids(
                    source_refs,
                    list(mechanism_chain.get("evidence_unit_ids", [])),
                ),
            },
            {
                "section_id": "limitations",
                "title": "Limitations and uncertainties",
                "body": self._objective_conclusion_limitation_summary(limitations),
                "claims": [],
                "evidence_unit_ids": self._dedupe_preserving_order(
                    [
                        evidence_unit_id
                        for limitation in limitations
                        for evidence_unit_id in limitation.get("evidence_unit_ids", [])
                    ]
                ),
                "source_refs": self._objective_source_refs_for_evidence_ids(
                    source_refs,
                    [
                        evidence_unit_id
                        for limitation in limitations
                        for evidence_unit_id in limitation.get("evidence_unit_ids", [])
                    ],
                ),
            },
            {
                "section_id": "source_traceback",
                "title": "Source traceback",
                "body": self._objective_conclusion_source_summary(source_refs),
                "claims": [],
                "evidence_unit_ids": self._dedupe_preserving_order(
                    [
                        str(source_ref.get("evidence_unit_id") or "")
                        for source_ref in source_refs
                    ]
                ),
                "source_refs": source_refs,
            },
        ]

    def _objective_conclusion_answer(
        self,
        *,
        objective: ResearchObjective,
        paper_contributions: list[dict[str, Any]],
        measurement_ranges: list[dict[str, Any]],
        controlled_comparisons: list[dict[str, Any]],
        mechanism_chain: dict[str, Any],
        limitations: list[dict[str, Any]],
    ) -> str:
        materials = self._human_join(objective.material_scope)
        process_axes = self._human_join(objective.process_axes)
        property_axes = self._human_join(objective.property_axes)
        primary_paper = self._objective_primary_contribution(paper_contributions)
        pieces = [
            (
                f"For {materials or 'the selected material system'}, the current "
                f"evidence package evaluates how {process_axes or 'the process variables'} "
                f"affect {property_axes or 'the target response'}."
            )
        ]
        if primary_paper is not None:
            pieces.append(
                f"The strongest contribution is {self._objective_contribution_title(primary_paper)}, "
                f"because it directly contributes {self._objective_contribution_scope(primary_paper)}."
            )
        range_summary = self._objective_logic_chain_range_summary(measurement_ranges)
        if range_summary:
            pieces.append(f"The resolved measurement evidence covers {range_summary}.")
        if controlled_comparisons:
            pieces.append(
                f"{len(controlled_comparisons)} comparison item(s) connect the variable changes to observed results."
            )
        mechanism_count = len(mechanism_chain.get("evidence", []))
        if mechanism_count:
            pieces.append(
                "Mechanism evidence links processing or treatment changes to microstructure, defects, "
                "or author interpretation before reaching the reported property response."
            )
        if limitations:
            pieces.append(
                "The conclusion should still be read with the listed limitations because some joins, "
                "conditions, or mechanism evidence remain incomplete."
            )
        return " ".join(pieces)

    def _objective_conclusion_context_summary(
        self,
        *,
        objective: ResearchObjective,
        paper_contributions: list[dict[str, Any]],
    ) -> str:
        materials = self._human_join(objective.material_scope)
        process_axes = self._human_join(objective.process_axes)
        property_axes = self._human_join(objective.property_axes)
        paper_count = len(paper_contributions)
        return (
            f"Objective: {objective.question} The report is scoped to "
            f"{materials or 'the selected material system'}, process axes "
            f"{process_axes or 'not specified'}, and target properties "
            f"{property_axes or 'not specified'}. {paper_count} relevant paper(s) "
            "are considered in this objective-scoped evidence package."
        )

    def _objective_traceable_claim(
        self,
        statement: dict[str, Any],
        *,
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence_unit_ids = self._dedupe_preserving_order(
            [
                str(evidence_unit_id or "")
                for evidence_unit_id in statement.get("evidence_unit_ids", [])
            ]
        )
        claim_source_refs = self._objective_source_refs_for_evidence_ids(
            source_refs,
            evidence_unit_ids,
        )
        return {
            key: value
            for key, value in {
                "claim": statement.get("claim"),
                "evidence_unit_ids": evidence_unit_ids,
                "source_refs": claim_source_refs,
                "strength": statement.get("strength"),
            }.items()
            if value not in (None, "", [], {})
        }

    def _objective_source_refs_for_evidence_ids(
        self,
        source_refs: list[dict[str, Any]],
        evidence_unit_ids: list[str],
    ) -> list[dict[str, Any]]:
        wanted = {str(evidence_unit_id or "") for evidence_unit_id in evidence_unit_ids}
        if not wanted:
            return []
        return [
            source_ref
            for source_ref in source_refs
            if str(source_ref.get("evidence_unit_id") or "") in wanted
        ]

    def _objective_conclusion_evidence_summary(
        self,
        *,
        measurement_ranges: list[dict[str, Any]],
        primary_evidence_tables: list[dict[str, Any]],
    ) -> str:
        row_count = sum(
            len(table.get("rows", []))
            for table in primary_evidence_tables
        )
        range_summary = self._objective_logic_chain_range_summary(measurement_ranges)
        if not row_count:
            return "No resolved measurement rows are available yet for this objective."
        if range_summary:
            return (
                f"The key evidence table contains {row_count} measurement row(s). "
                f"Across those rows, {range_summary}."
            )
        return f"The key evidence table contains {row_count} measurement row(s)."

    def _objective_conclusion_paper_summary(
        self,
        paper_contributions: list[dict[str, Any]],
    ) -> str:
        if not paper_contributions:
            return "No paper contribution records are available for this objective."
        primary = self._objective_primary_contribution(paper_contributions)
        secondary_count = max(len(paper_contributions) - 1, 0)
        if primary is None:
            return f"{len(paper_contributions)} relevant paper(s) contribute objective-scoped evidence."
        pieces = [
            f"{self._objective_contribution_title(primary)} is the primary contribution: "
            f"it provides {self._objective_contribution_scope(primary)}."
        ]
        if secondary_count:
            pieces.append(
                f"The remaining {secondary_count} paper(s) are supporting or limited contributions for this objective."
            )
        return " ".join(pieces)

    def _objective_contribution_claim(
        self,
        contribution: dict[str, Any],
    ) -> str:
        title = self._objective_contribution_title(contribution)
        variables = self._human_join(contribution.get("changed_variables", []) or [])
        properties = self._human_join(contribution.get("measured_property_scope", []) or [])
        details = []
        if variables:
            details.append(f"variables: {variables}")
        if properties:
            details.append(f"properties: {properties}")
        if details:
            return f"{title} contributes {'; '.join(details)}."
        return f"{title} contributes objective-scoped evidence."

    def _objective_primary_contribution(
        self,
        paper_contributions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not paper_contributions:
            return None

        def rank(contribution: dict[str, Any]) -> tuple[int, int, int, str]:
            relevance = str(contribution.get("relevance") or "").lower()
            role = str(contribution.get("paper_role") or "").lower()
            relevance_score = {"high": 3, "medium": 2, "low": 1}.get(relevance, 0)
            role_score = 2 if "primary" in role or "experiment" in role else 0
            evidence_count = int(contribution.get("evidence_unit_count") or 0)
            return (
                relevance_score,
                role_score,
                evidence_count,
                str(contribution.get("document_id") or ""),
            )

        return max(paper_contributions, key=rank)

    def _objective_contribution_title(self, contribution: dict[str, Any]) -> str:
        return str(
            contribution.get("display_title")
            or contribution.get("title")
            or contribution.get("source_filename")
            or contribution.get("document_id")
            or "This paper"
        )

    def _objective_paper_display_title(
        self,
        *,
        title: Any,
        source_filename: Any,
        paper_label: str,
    ) -> str:
        raw_title = str(title or source_filename or "").strip()
        if not raw_title:
            return paper_label
        cleaned = self._objective_clean_paper_title(raw_title)
        if not cleaned:
            return paper_label
        if cleaned.lower().startswith(f"{paper_label.lower()} - "):
            return cleaned
        return f"{paper_label} - {cleaned}"

    def _objective_clean_paper_title(self, value: str) -> str:
        cleaned = value.strip()
        cleaned = re.sub(r"\.pdf$", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^[0-9a-f]{16,}[_-]+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^P\d{3}[-_\s]+", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("_", " ")
        return " ".join(cleaned.split())

    def _objective_contribution_scope(self, contribution: dict[str, Any]) -> str:
        variables = self._human_join(contribution.get("changed_variables", []) or [])
        properties = self._human_join(contribution.get("measured_property_scope", []) or [])
        if variables and properties:
            return f"{variables} evidence tied to {properties}"
        if variables:
            return f"{variables} process-variable evidence"
        if properties:
            return f"{properties} property evidence"
        return "objective-scoped evidence"

    def _objective_conclusion_evidence_matrix_summary(
        self,
        primary_evidence_tables: list[dict[str, Any]],
    ) -> str:
        row_count = sum(
            len(table.get("rows", []))
            for table in primary_evidence_tables
        )
        range_count = sum(
            len(table.get("measurement_value_ranges", []))
            for table in primary_evidence_tables
        )
        if not row_count:
            return "No measurement rows are available for the evidence matrix."
        return (
            f"The evidence matrix contains {row_count} measurement row(s) "
            f"and {range_count} property range summary item(s)."
        )

    def _objective_conclusion_comparison_summary(
        self,
        controlled_comparisons: list[dict[str, Any]],
    ) -> str:
        if not controlled_comparisons:
            return "No controlled comparison evidence is available yet, so the report cannot make a strict variable-isolated comparison."
        controlled_count = sum(
            1
            for comparison in controlled_comparisons
            if comparison.get("validity") == "controlled"
        )
        return (
            f"{len(controlled_comparisons)} comparison item(s) are available. "
            f"{controlled_count} comparison item(s) include an explicit baseline context; the others should be read as directional evidence."
        )

    def _objective_conclusion_mechanism_summary(
        self,
        mechanism_chain: dict[str, Any],
    ) -> str:
        evidence_count = len(mechanism_chain.get("evidence", []))
        if not evidence_count:
            return "No mechanism evidence is available yet, so the report cannot explain how the process variables cause the observed response."
        step_labels = [
            str(step.get("label") or "")
            for step in mechanism_chain.get("steps", [])
            if isinstance(step, dict) and step.get("label")
        ]
        if step_labels:
            return " ".join(step_labels)
        return (
            "Mechanism evidence is linked, but the process-structure-property steps are not resolved yet."
        )

    def _objective_conclusion_limitation_summary(
        self,
        limitations: list[dict[str, Any]],
    ) -> str:
        if not limitations:
            return "No explicit limitations are reported for the current evidence package."
        messages = [
            str(limitation.get("message") or "").strip()
            for limitation in limitations[:3]
            if limitation.get("message")
        ]
        if messages:
            return " ".join(messages)
        return f"{len(limitations)} limitation or uncertainty item(s) constrain this conclusion."

    def _objective_conclusion_source_summary(
        self,
        source_refs: list[dict[str, Any]],
    ) -> str:
        if not source_refs:
            return "No source references are attached to the current report package."
        documents = self._dedupe_preserving_order(
            [str(source_ref.get("document_id") or "") for source_ref in source_refs]
        )
        return (
            f"{len(source_refs)} source reference(s) support this report across "
            f"{len(documents)} document(s). Use these links to audit the evidence behind each claim."
        )

    def _objective_conclusion_traceability(
        self,
        sections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        unsupported_claims = []
        traceable_claim_count = 0
        for section in sections:
            for claim in section.get("claims", []):
                if not isinstance(claim, dict):
                    continue
                claim_text = str(claim.get("claim") or "").strip()
                if not claim_text:
                    continue
                if claim.get("evidence_unit_ids") and claim.get("source_refs"):
                    traceable_claim_count += 1
                    continue
                unsupported_claims.append(
                    {
                        "section_id": section.get("section_id"),
                        "claim": claim_text,
                    }
                )
        return {
            "status": "ready" if not unsupported_claims else "limited",
            "traceable_claim_count": traceable_claim_count,
            "unsupported_claim_count": len(unsupported_claims),
            "unsupported_claims": unsupported_claims,
        }

    def _objective_conclusion_status(
        self,
        *,
        measurements: tuple[ObjectiveEvidenceUnit, ...],
        logic_chain: ObjectiveLogicChain | None,
    ) -> str:
        if logic_chain is not None and measurements:
            return "ready"
        if measurements:
            return "limited"
        return "empty"

    def _objective_conclusion_paper_contributions(
        self,
        *,
        frame_views: list[dict[str, Any]],
        evidence_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> list[dict[str, Any]]:
        units_by_document: dict[str, list[ObjectiveEvidenceUnit]] = {}
        for unit in evidence_units:
            units_by_document.setdefault(unit.document_id, []).append(unit)
        contributions: list[dict[str, Any]] = []
        for frame in frame_views:
            if frame.get("relevance") == "irrelevant":
                continue
            document_id = str(frame.get("document_id") or "")
            document_units = units_by_document.get(document_id, [])
            paper_label = f"P{len(contributions) + 1:03d}"
            title = frame.get("title") or frame.get("source_filename")
            source_filename = frame.get("source_filename")
            contributions.append(
                {
                    "document_id": document_id,
                    "paper_label": paper_label,
                    "title": title,
                    "display_title": self._objective_paper_display_title(
                        title=title,
                        source_filename=source_filename,
                        paper_label=paper_label,
                    ),
                    "source_filename": source_filename,
                    "paper_role": frame.get("paper_role"),
                    "relevance": frame.get("relevance"),
                    "background": frame.get("background"),
                    "changed_variables": list(frame.get("changed_variables") or []),
                    "measured_property_scope": list(
                        frame.get("measured_property_scope") or []
                    ),
                    "evidence_unit_count": len(document_units),
                    "evidence_unit_ids": [
                        unit.evidence_unit_id for unit in document_units
                    ],
                }
            )
        return contributions

    def _objective_conclusion_measurement_row(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "evidence_unit_id": unit.evidence_unit_id,
                "document_id": unit.document_id,
                "property": unit.property_normalized,
                "sample_context": dict(unit.sample_context),
                "process_context": dict(unit.process_context),
                "test_condition": dict(unit.test_condition),
                "value": self._objective_measurement_numeric_value(unit),
                "source_value_text": unit.value_payload.get("source_value_text"),
                "unit": unit.unit,
                "resolution_status": unit.resolution_status,
                "source_refs": [dict(source_ref) for source_ref in unit.source_refs],
            }.items()
            if value not in (None, "", [], {})
        }

    def _objective_conclusion_comparison(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "evidence_unit_id": unit.evidence_unit_id,
                "document_id": unit.document_id,
                "property": unit.property_normalized,
                "comparison_axis": unit.value_payload.get("comparison_axis"),
                "direction": unit.value_payload.get("direction"),
                "summary": self._value_payload_text(unit.value_payload),
                "sample_context": dict(unit.sample_context),
                "process_context": dict(unit.process_context),
                "baseline_context": dict(unit.baseline_context),
                "source_refs": [dict(source_ref) for source_ref in unit.source_refs],
                "validity": (
                    "controlled"
                    if unit.baseline_context
                    else "directional"
                ),
            }.items()
            if value not in (None, "", [], {})
        }

    def _objective_conclusion_mechanism_chain(
        self,
        mechanism_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> dict[str, Any]:
        steps = [
            {
                "step_role": "process_to_microstructure",
                "label": "Process parameters change thermal history and melt-pool behavior.",
            },
            {
                "step_role": "microstructure_to_property",
                "label": "Microstructure, defects, and phase features affect measured properties.",
            },
        ]
        return {
            "steps": steps,
            "evidence": [
                self._objective_logic_unit_reference(unit)
                for unit in mechanism_units
            ],
            "evidence_unit_ids": [
                unit.evidence_unit_id for unit in mechanism_units
            ],
        }

    def _objective_conclusion_statements(
        self,
        *,
        measurement_ranges: list[dict[str, Any]],
        comparisons: tuple[ObjectiveEvidenceUnit, ...],
        mechanism_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> list[dict[str, Any]]:
        statements: list[dict[str, Any]] = []
        for value_range in measurement_ranges:
            property_name = str(value_range.get("property_normalized") or "").strip()
            if not property_name:
                continue
            statements.append(
                {
                    "claim": (
                        self._objective_measurement_range_claim(
                            property_name=property_name,
                            value_range=value_range,
                        )
                    ),
                    "evidence_unit_ids": [
                        item.get("evidence_unit_id")
                        for item in (
                            value_range.get("min"),
                            value_range.get("max"),
                        )
                        if isinstance(item, dict) and item.get("evidence_unit_id")
                    ],
                    "strength": "measured",
                }
            )
        if comparisons:
            statements.append(
                {
                    "claim": "Comparison evidence connects at least one variable change to the target response.",
                    "evidence_unit_ids": [
                        unit.evidence_unit_id for unit in comparisons
                    ],
                    "strength": "comparison",
                }
            )
        if mechanism_units:
            statements.append(
                {
                    "claim": "Characterization or interpretation evidence supports a process-structure-property explanation.",
                    "evidence_unit_ids": [
                        unit.evidence_unit_id for unit in mechanism_units
                    ],
                    "strength": "mechanism",
                }
            )
        return statements

    def _objective_measurement_range_claim(
        self,
        *,
        property_name: str,
        value_range: dict[str, Any],
    ) -> str:
        min_point = value_range.get("min")
        max_point = value_range.get("max")
        if not isinstance(min_point, dict) or not isinstance(max_point, dict):
            return f"{property_name} is backed by resolved measurement evidence."
        unit = str(value_range.get("unit") or "").strip()
        min_value = min_point.get("source_value_text") or min_point.get("value")
        max_value = max_point.get("source_value_text") or max_point.get("value")
        if min_value in (None, "") or max_value in (None, ""):
            return f"{property_name} is backed by resolved measurement evidence."
        min_label = self._objective_measurement_point_label(min_point)
        max_label = self._objective_measurement_point_label(max_point)
        if min_point.get("evidence_unit_id") == max_point.get("evidence_unit_id"):
            return f"{property_name} is reported as {self._format_value_with_unit(min_value, unit)} for {min_label}."
        return (
            f"{property_name} spans {self._format_value_with_unit(min_value, unit)} "
            f"to {self._format_value_with_unit(max_value, unit)} across "
            f"{min_label} and {max_label}."
        )

    def _objective_conclusion_limitations(
        self,
        *,
        measurements: tuple[ObjectiveEvidenceUnit, ...],
        comparisons: tuple[ObjectiveEvidenceUnit, ...],
        mechanism_units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> list[dict[str, Any]]:
        limitations: list[dict[str, Any]] = []
        if not measurements:
            limitations.append(
                {
                    "code": "measurement_results_missing",
                    "message": "No measurement results are available for this objective.",
                    "evidence_unit_ids": [],
                }
            )
        incomplete_context = [
            unit.evidence_unit_id
            for unit in measurements
            if not unit.sample_context or not unit.process_context
        ]
        if incomplete_context:
            limitations.append(
                {
                    "code": "sample_process_context_incomplete",
                    "message": "Some measurements do not have complete sample and process context.",
                    "evidence_unit_ids": incomplete_context,
                }
            )
        directional_comparisons = [
            unit.evidence_unit_id for unit in comparisons if not unit.baseline_context
        ]
        if directional_comparisons:
            limitations.append(
                {
                    "code": "comparison_baseline_incomplete",
                    "message": "Some comparison evidence is directional because baseline context is incomplete.",
                    "evidence_unit_ids": directional_comparisons,
                }
            )
        if not mechanism_units:
            limitations.append(
                {
                    "code": "mechanism_evidence_missing",
                    "message": "No mechanism or characterization evidence is available for this objective.",
                    "evidence_unit_ids": [],
                }
            )
        return limitations

    def _objective_conclusion_source_refs(
        self,
        evidence_units: tuple[ObjectiveEvidenceUnit, ...],
        *,
        paper_contributions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        document_labels = self._objective_document_display_labels(paper_contributions)
        for unit in evidence_units:
            for source_ref in unit.source_refs:
                record = {
                    key: value
                    for key, value in {
                        "evidence_unit_id": unit.evidence_unit_id,
                        "document_id": unit.document_id,
                        **dict(source_ref),
                    }.items()
                    if value not in (None, "", [], {})
                }
                record["display_label"] = self._objective_source_display_label(
                    record,
                    document_labels=document_labels,
                )
                key = json.dumps(record, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                refs.append(record)
        return refs

    def _objective_document_display_labels(
        self,
        paper_contributions: list[dict[str, Any]],
    ) -> dict[str, str]:
        labels: dict[str, str] = {}
        for index, contribution in enumerate(paper_contributions, start=1):
            document_id = str(contribution.get("document_id") or "")
            if document_id:
                labels[document_id] = f"P{index:03d}"
        return labels

    def _objective_source_display_label(
        self,
        source_ref: dict[str, Any],
        *,
        document_labels: dict[str, str],
    ) -> str:
        document_id = str(source_ref.get("document_id") or "").strip()
        document_label = document_labels.get(document_id) or self._short_source_identifier(
            document_id
        )
        kind_label = self._objective_source_kind_label(source_ref)
        page = source_ref.get("page") or source_ref.get("page_number")
        parts = [document_label, kind_label]
        if page not in (None, "", [], {}):
            parts.append(f"p.{page}")
        return " · ".join(part for part in parts if part)

    def _objective_source_kind_label(self, source_ref: dict[str, Any]) -> str:
        kind = str(source_ref.get("source_kind") or "").strip().lower()
        source_ref_id = str(source_ref.get("source_ref") or "").strip()
        if kind in {"table", "table_cell"}:
            table_number = self._trailing_number(source_ref_id)
            return f"Table {table_number}" if table_number else "Table"
        if kind in {"figure", "image"}:
            figure_number = self._trailing_number(source_ref_id)
            return f"Figure {figure_number}" if figure_number else "Figure"
        if kind in {"text_window", "block", "paragraph", "section"}:
            return "Text"
        return kind.replace("_", " ").title() if kind else "Source"

    def _trailing_number(self, value: str) -> str:
        match = re.search(r"(\d+)(?!.*\d)", value)
        return match.group(1) if match else ""

    def _short_source_identifier(self, value: str) -> str:
        if not value:
            return ""
        return value if len(value) <= 12 else value[:12]

    def _objective_measurement_point_label(self, point: dict[str, Any]) -> str:
        sample_context = point.get("sample_context")
        process_context = point.get("process_context")
        for record in (sample_context, process_context):
            if not isinstance(record, dict):
                continue
            for key in ("sample", "sample_id", "sample_label", "condition", "name"):
                value = record.get(key)
                if value not in (None, "", [], {}):
                    return str(value)
            for value in record.values():
                if value not in (None, "", [], {}):
                    return str(value)
        return "one resolved condition"

    def _format_value_with_unit(self, value: Any, unit: str) -> str:
        text = str(value)
        if not unit or unit in text:
            return text
        return f"{text} {unit}"

    def _human_join(self, values: Any) -> str:
        items = [
            str(value).strip()
            for value in values
            if str(value).strip()
        ] if isinstance(values, (list, tuple)) else []
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return f"{', '.join(items[:-1])}, and {items[-1]}"

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

    def _display_objective_from_facts(
        self,
        objective: ResearchObjective,
        *,
        facts,
    ) -> ResearchObjective:
        evidence_units = self._filter_objective_records(
            facts.objective_evidence_units,
            objective_id=objective.objective_id,
        )
        context = next(
            (
                candidate
                for candidate in facts.objective_contexts
                if candidate.objective_id == objective.objective_id
            ),
            None,
        )
        process_axes = self._display_process_axes(
            objective,
            context=context,
            evidence_units=evidence_units,
        )
        property_axes = (
            list(context.target_property_axes)
            if context is not None and context.target_property_axes
            else list(objective.property_axes)
        )
        if (
            tuple(process_axes) == objective.process_axes
            and tuple(property_axes) == objective.property_axes
        ):
            return objective
        payload = objective.to_record()
        payload["process_axes"] = process_axes
        payload["property_axes"] = property_axes
        payload["question"] = self._build_research_objective_question(payload)
        payload["comparison_intent"] = self._build_comparison_intent(payload)
        return ResearchObjective.from_mapping(payload)

    def _display_process_axes(
        self,
        objective: ResearchObjective,
        *,
        context: ObjectiveContext | None,
        evidence_units,
    ) -> list[str]:
        candidate_axes: list[str] = []
        if context is not None:
            candidate_axes.extend(context.variable_process_axes)
            candidate_axes.extend(context.process_context_axes)
        if not candidate_axes:
            candidate_axes.extend(objective.process_axes)
        observed_keys = self._objective_observed_process_axis_keys(evidence_units)
        selected: list[str] = []
        seen: set[str] = set()
        for axis in candidate_axes:
            key = self._axis_key(axis)
            if not key:
                continue
            if observed_keys and not self._process_axis_matches_observed_key(
                key,
                observed_keys,
            ):
                continue
            self._append_unique_axis(selected, seen, axis)
        if selected:
            return selected[:6]
        return list(objective.process_axes[:6])

    def _objective_observed_process_axis_keys(self, evidence_units) -> set[str]:
        keys: set[str] = set()
        for unit in evidence_units:
            for mapping in (unit.process_context, unit.resolved_condition):
                for key, value in mapping.items():
                    if self._has_observed_evidence_value(value):
                        keys.add(self._axis_key(key))
                    if isinstance(value, str):
                        keys.add(self._axis_key(value))
        return {key for key in keys if key}

    def _process_axis_matches_observed_key(
        self,
        axis_key: str,
        observed_keys: set[str],
    ) -> bool:
        axis_tokens = self._axis_token_set(axis_key)
        if not axis_tokens:
            return False
        for observed_key in observed_keys:
            if axis_key == observed_key:
                return True
            observed_tokens = self._axis_token_set(observed_key)
            if axis_tokens.issubset(observed_tokens) or observed_tokens.issubset(
                axis_tokens
            ):
                return True
        return False

    def _has_observed_evidence_value(self, value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str) and value.strip().lower() in {
            "unknown",
            "unspecified",
            "not specified",
            "n/a",
            "na",
            "none",
            "null",
        }:
            return False
        return True

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

    def _build_objective_report_context(
        self,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, Any]:
        detail = self.get_objective_research_view(collection_id, objective_id)
        conclusion_package = detail.get("conclusion_package") or {}
        expert_report = conclusion_package.get("expert_report") or {}
        source_refs = (
            conclusion_package.get("source_refs")
            or expert_report.get("source_traceback")
            or []
        )
        context = {
            "schema_version": "objective_report_context.v1",
            "collection_id": collection_id,
            "objective": detail["objective"],
            "readiness": detail["readiness"],
            "paper_frames": detail["paper_frames"],
            "evidence_summary": {
                "evidence_unit_count": len(detail["evidence_units"]),
                "measurement_count": self._count_records_by_kind(
                    detail["evidence_units"],
                    "measurement",
                ),
                "comparison_count": self._count_records_by_kind(
                    detail["evidence_units"],
                    "comparison",
                ),
                "characterization_count": self._count_records_by_kind(
                    detail["evidence_units"],
                    "characterization",
                ),
                "interpretation_count": self._count_records_by_kind(
                    detail["evidence_units"],
                    "interpretation",
                ),
            },
            "evidence_units": self._objective_report_evidence_units(
                detail["evidence_units"],
            ),
            "logic_chain": detail["logic_chain"],
            "conclusion_package": conclusion_package,
            "source_refs": self._objective_report_source_refs(source_refs),
        }
        return context

    def _objective_report_evidence_units(
        self,
        evidence_units: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        compact_units: list[dict[str, Any]] = []
        for unit in evidence_units:
            compact_units.append(
                {
                    key: value
                    for key, value in {
                        "evidence_unit_id": unit.get("evidence_unit_id"),
                        "document_id": unit.get("document_id"),
                        "unit_kind": unit.get("unit_kind"),
                        "property_normalized": unit.get("property_normalized"),
                        "material_system": unit.get("material_system"),
                        "sample_context": unit.get("sample_context"),
                        "process_context": unit.get("process_context"),
                        "test_condition": unit.get("test_condition"),
                        "value_payload": unit.get("value_payload"),
                        "unit": unit.get("unit"),
                        "baseline_context": unit.get("baseline_context"),
                        "interpretation": unit.get("interpretation"),
                        "source_refs": unit.get("source_refs"),
                        "resolution_status": unit.get("resolution_status"),
                        "confidence": unit.get("confidence"),
                    }.items()
                    if value not in (None, "", [], {})
                }
            )
        return compact_units

    def _objective_report_source_refs(
        self,
        source_refs: Any,
    ) -> list[dict[str, Any]]:
        compact_refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_ref in source_refs if isinstance(source_refs, list) else []:
            if not isinstance(source_ref, dict):
                continue
            record = {
                key: value
                for key, value in {
                    "evidence_unit_id": source_ref.get("evidence_unit_id"),
                    "document_id": source_ref.get("document_id"),
                    "display_label": source_ref.get("display_label"),
                    "source_kind": source_ref.get("source_kind"),
                    "source_ref": source_ref.get("source_ref"),
                    "page": source_ref.get("page") or source_ref.get("page_number"),
                    "anchor_id": source_ref.get("anchor_id"),
                    "route_id": source_ref.get("route_id"),
                    "role": source_ref.get("role"),
                }.items()
                if value not in (None, "", [], {})
            }
            if not record:
                continue
            key = json.dumps(record, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            compact_refs.append(record)
        return compact_refs

    def _generate_objective_report_markdown(
        self,
        context: dict[str, Any],
        *,
        language: str,
    ) -> str:
        system_prompt = (
            "You are a senior materials scientist writing a research-objective "
            "report from a provided evidence package. Use only the provided "
            "facts. Do not invent samples, values, mechanisms, papers, or "
            "comparisons. Every concrete claim with a value or comparison must "
            "cite the provided source labels when available."
        )
        user_prompt = (
            f"Language: {'Chinese' if language == 'zh' else 'English'}\n"
            "Write one Markdown report for this research objective.\n"
            "Required sections:\n"
            "# 研究目标\n"
            "## 结论摘要\n"
            "## 文献贡献\n"
            "## 样品、工艺和测试条件\n"
            "## 支撑数据\n"
            "## 受控比较\n"
            "## 机制解释\n"
            "## 局限性与不确定性\n"
            "## 证据来源\n"
            "If a section lacks evidence, say so explicitly instead of filling it with generic text.\n\n"
            f"EvidencePackage:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
        completion = self._get_report_llm_client().chat.completions.create(
            model=self.report_model,
            temperature=0.15,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content if completion.choices else None
        return self._coerce_llm_message_content(content)

    def _get_report_llm_client(self):
        if self._report_llm_client is None:
            self._report_llm_client = OpenAI(
                api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
                base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
            )
        return self._report_llm_client

    def _objective_report_warnings(
        self,
        context: dict[str, Any],
        markdown: str,
    ) -> list[str]:
        warnings: list[str] = []
        if not context["source_refs"]:
            warnings.append("No source references are available for this report.")
        if not context["evidence_units"]:
            warnings.append("No objective evidence units are available for this report.")
        if markdown.count("## ") < 6:
            warnings.append("Generated report is missing one or more expected sections.")
        return warnings

    def _objective_report_response(
        self,
        collection_id: str,
        artifact: ObjectiveReportArtifact,
    ) -> dict[str, Any]:
        return {
            "collection_id": collection_id,
            **artifact.to_record(),
        }

    def _objective_report_data_version(self, context: dict[str, Any]) -> str:
        payload = json.dumps(context, ensure_ascii=False, sort_keys=True)
        return sha256(payload.encode("utf-8")).hexdigest()

    def _extract_objective_report_title(self, markdown: str) -> str | None:
        match = re.search(r"^\s*#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
        if not match:
            return None
        return match.group(1).strip() or None

    def _count_records_by_kind(
        self,
        records: list[dict[str, Any]],
        unit_kind: str,
    ) -> int:
        return sum(1 for record in records if record.get("unit_kind") == unit_kind)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _coerce_llm_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return str(content or "").strip()
        parts: list[str] = []
        for item in content:
            text = item if isinstance(item, str) else getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()

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
        progress_callback: ProgressCallback | None = None,
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
                self._notify_progress(
                    progress_callback,
                    phase="objective_paper_framing_started",
                    current=completed_frame_requests,
                    total=total_frame_requests,
                    unit="frames",
                    message="Checking each paper against each research objective.",
                    active_document_id=document_id,
                    active_objective_id=objective.objective_id,
                )
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
        progress_callback: ProgressCallback | None = None,
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
            self._notify_progress(
                progress_callback,
                phase="objective_evidence_routing_started",
                current=frame_position,
                total=frame_count,
                unit="frames",
                message="Routing source blocks and tables for objective-scoped extraction.",
                active_document_id=frame.document_id,
                active_objective_id=frame.objective_id,
            )
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
            objective_context = context_by_objective_id.get(frame.objective_id)
            payload = {
                "collection_id": collection_id,
                "objective": objective.to_record(),
                "objective_context": (
                    objective_context.to_record()
                    if objective_context is not None else {}
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
            self._append_objective_context_hint_routes(
                routes=routes,
                seen=seen,
                frame=frame,
                objective_context=objective_context,
                candidate_by_key=candidate_by_key,
            )
            self._append_ranked_text_hint_routes(
                routes=routes,
                seen=seen,
                frame=frame,
                source_candidates=source_candidates,
            )
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

    def _append_objective_context_hint_routes(
        self,
        *,
        routes: list[ObjectiveEvidenceRoute],
        seen: set[tuple[str, str, str, str, str]],
        frame: ObjectivePaperFrame,
        objective_context: ObjectiveContext | None,
        candidate_by_key: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        if objective_context is None:
            return
        for hint in objective_context.routing_hints:
            table_id = str(hint.get("table_id") or "").strip()
            if not table_id:
                continue
            document_id = str(hint.get("document_id") or "").strip()
            if document_id and document_id != frame.document_id:
                continue
            candidate = candidate_by_key.get(("table", table_id))
            if candidate is None:
                continue
            role = self._objective_context_hint_route_role(hint)
            if role is None:
                continue
            route_key = (
                frame.objective_id,
                frame.document_id,
                "table",
                table_id,
                role,
            )
            if route_key in seen:
                continue
            seen.add(route_key)
            table_schema = self._route_table_schema_record(candidate=candidate)
            routes.append(
                ObjectiveEvidenceRoute.from_mapping(
                    {
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "source_kind": "table",
                        "source_ref": table_id,
                        "role": role,
                        "extractable": True,
                        "reason": hint.get("reason")
                        or "Selected from objective context routing hints.",
                        "table_schema": table_schema,
                        "column_roles": self._objective_context_hint_column_roles(
                            objective_context=objective_context,
                            hint=hint,
                            table_schema=table_schema,
                        ),
                        "join_keys": {},
                        "join_plan": {},
                        "confidence": objective_context.confidence,
                    }
                )
            )

    def _objective_context_hint_route_role(
        self,
        hint: dict[str, Any],
    ) -> str | None:
        role = str(hint.get("role") or "").strip()
        if role == "result_table":
            return "current_experimental_evidence"
        if role in {"condition_context", "process_context", "method_context"}:
            return "process_or_treatment"
        return None

    def _objective_context_hint_column_roles(
        self,
        *,
        objective_context: ObjectiveContext,
        hint: dict[str, Any],
        table_schema: dict[str, Any],
    ) -> dict[str, str]:
        hint_role = str(hint.get("role") or "")
        roles: dict[str, str] = {}
        for header in table_schema.get("column_headers", ()):
            header_text = str(header or "").strip()
            if not header_text:
                continue
            header_key = self._objective_column_key(header_text)
            if header_key == "condition_number":
                roles[header_text] = "sample_condition"
            elif header_key in {"sample", "sample_number"}:
                roles[header_text] = "sample_id"
            elif self._objective_value_column_is_statistical(header_text):
                roles[header_text] = "statistical_measure"
            elif self._objective_header_matches_any_axis(
                header_text,
                objective_context.target_property_axes,
            ) or (
                hint_role == "result_table"
                and header_key == "relative_density"
                and any(
                    axis in {"densification", "microstructure"}
                    for axis in objective_context.target_property_axes
                )
            ):
                roles[header_text] = "target_property"
            elif self._objective_header_matches_any_axis(
                header_text,
                objective_context.variable_process_axes,
            ) or self._objective_header_looks_process_variable(header_text):
                roles[header_text] = "process_variable"
        return roles

    def _append_ranked_text_hint_routes(
        self,
        *,
        routes: list[ObjectiveEvidenceRoute],
        seen: set[tuple[str, str, str, str, str]],
        frame: ObjectivePaperFrame,
        source_candidates: list[dict[str, Any]],
    ) -> None:
        existing_refs = {
            route.source_ref
            for route in routes
            if route.objective_id == frame.objective_id
            and route.document_id == frame.document_id
            and route.source_kind == "text_window"
        }
        ranked_candidates: list[tuple[int, int, dict[str, Any]]] = []
        for index, candidate in enumerate(source_candidates):
            if candidate.get("source_kind") != "text_window":
                continue
            source_ref = str(candidate.get("source_ref") or "").strip()
            if not source_ref or source_ref in existing_refs:
                continue
            ranked_candidates.append(
                (
                    -self._text_hint_route_priority(candidate),
                    index,
                    candidate,
                )
            )
        ranked_candidates.sort()
        added = 0
        for _, _, candidate in ranked_candidates:
            source_ref = str(candidate.get("source_ref") or "").strip()
            role = self._text_hint_route_role(frame=frame, candidate=candidate)
            route_key = (
                frame.objective_id,
                frame.document_id,
                "text_window",
                source_ref,
                role,
            )
            if route_key in seen:
                continue
            seen.add(route_key)
            routes.append(
                ObjectiveEvidenceRoute.from_mapping(
                    {
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "source_kind": "text_window",
                        "source_ref": source_ref,
                        "role": role,
                        "extractable": True,
                        "reason": "High-scoring objective text candidate retained for evidence extraction.",
                        "table_schema": {},
                        "column_roles": {},
                        "join_keys": {},
                        "join_plan": {},
                        "confidence": 0.62,
                    }
                )
            )
            added += 1
            if added >= _ROUTE_TEXT_HINT_LIMIT:
                break

    def _text_hint_route_priority(self, candidate: dict[str, Any]) -> int:
        section_key = self._objective_column_key(
            str(candidate.get("section_label") or "")
        )
        priority = 0
        if "conclusion" in section_key:
            priority += 8
        if section_key.startswith(("3_", "4_")):
            priority += 6
        if candidate.get("block_type") == "figure_caption":
            priority += 2
        if "abstract" in section_key:
            priority -= 3
        text = str(candidate.get("text") or "").casefold()
        if any(
            token in text
            for token in (
                "microstructure",
                "grain",
                "dendrite",
                "defect",
                "porosity",
                "sem",
            )
        ):
            priority += 2
        return priority

    def _text_hint_route_role(
        self,
        *,
        frame: ObjectivePaperFrame,
        candidate: dict[str, Any],
    ) -> str:
        text = " ".join(
            str(value or "")
            for value in (
                candidate.get("section_label"),
                candidate.get("text"),
                *frame.measured_property_scope,
            )
        ).casefold()
        if any(
            token in text
            for token in (
                "microstructure",
                "grain",
                "dendrite",
                "defect",
                "morphology",
                "porosity",
                "phase",
                "sem",
            )
        ):
            return "characterization"
        return "current_experimental_evidence"

    def _objective_header_matches_any_axis(
        self,
        header: str,
        axes: tuple[str, ...],
    ) -> bool:
        property_name, _unit = self._split_property_unit(header)
        normalized_property = self._normalize_property_label(property_name)
        if normalized_property and any(
            self._axis_values_match(normalized_property, axis) for axis in axes
        ):
            return True
        if any(self._axis_values_match(header, axis) for axis in axes):
            return True
        header_key = self._objective_column_key(header)
        if not header_key:
            return False
        for axis in axes:
            axis_key = self._objective_column_key(axis)
            if not axis_key:
                continue
            if axis_key in header_key or header_key in axis_key:
                return True
        return False

    def _objective_header_looks_process_variable(self, header: str) -> bool:
        header_key = self._objective_column_key(header)
        return any(
            token in header_key
            for token in (
                "duration",
                "energy",
                "hatch",
                "laser",
                "power",
                "scan",
                "speed",
                "temperature",
            )
        )

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
        table_cells_by_document_id: dict[str, list[Any]] | None = None,
        progress_callback: ProgressCallback | None = None,
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
            self._notify_progress(
                progress_callback,
                phase="objective_evidence_units_started",
                current=route_position,
                total=len(extractable_routes),
                unit="routes",
                message="Extracting objective evidence units from routed sources.",
                active_document_id=route.document_id,
                active_objective_id=route.objective_id,
            )
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
                table_cells=(
                    table_cells_by_document_id.get(route.document_id, [])
                    if table_cells_by_document_id is not None else []
                ),
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
            objective_context = context_by_objective_id.get(route.objective_id)
            payload = {
                "collection_id": collection_id,
                "objective": objective.to_record(),
                "objective_context": (
                    objective_context.to_record()
                    if objective_context is not None else {}
                ),
                "paper_frame": (
                    frame_by_key[(route.objective_id, route.document_id)].to_record()
                    if (route.objective_id, route.document_id) in frame_by_key
                    else {}
                ),
                "evidence_route": route.to_record(),
                "source": source,
            }
            route_unit_start = len(units)
            route_records = self._objective_table_matrix_evidence_unit_records(
                route=route,
                source=source,
                objective_context=objective_context,
            )
            needs_structural_repair = (
                self._objective_table_source_needs_llm_structural_repair(
                    route=route,
                    source=source,
                )
            )
            if (
                (not route_records or needs_structural_repair)
                and not self._objective_table_route_should_skip_llm_fallback(
                    route,
                    objective_context=objective_context,
                )
            ):
                try:
                    parsed = extractor.extract_objective_evidence_units(payload)
                except Exception:
                    logger.exception(
                        "Research objective evidence-unit extraction route failed collection_id=%s route_id=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s completed_routes=%s remaining_routes=%s",
                        collection_id,
                        route.route_id,
                        route.objective_id,
                        route.document_id,
                        route.source_kind,
                        route.source_ref,
                        route_position,
                        len(extractable_routes),
                        route_position - 1,
                        max(len(extractable_routes) - route_position, 0),
                    )
                    if not route_records:
                        continue
                else:
                    llm_route_records = tuple(
                        record
                        for item in parsed.evidence_units
                        for record in self._objective_evidence_unit_records_from_extracted(
                            route=route,
                            source=source,
                            objective_context=objective_context,
                            extracted_record=item.model_dump(),
                        )
                    )
                    route_records = self._objective_merge_table_repair_records(
                        deterministic_records=route_records,
                        llm_records=llm_route_records,
                    )
            for record in route_records:
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
        for unit in self._build_objective_method_family_test_condition_units(
            objective_contexts=objective_contexts,
            objective_paper_frames=objective_paper_frames,
            blocks_by_document_id=blocks_by_document_id,
        ):
            if not self._objective_evidence_unit_has_payload(unit):
                continue
            if unit.evidence_unit_id in seen:
                continue
            seen.add(unit.evidence_unit_id)
            units.append(unit)
        logger.info(
            "Research objective evidence-unit extraction finished collection_id=%s objective_evidence_units=%s",
            collection_id,
            len(units),
        )
        resolved_units = self._resolve_objective_evidence_unit_contexts(tuple(units))
        resolved_units = self._inherit_objective_material_systems(
            resolved_units,
            objectives=objectives,
            objective_contexts=objective_contexts,
        )
        resolved_units = self._dedupe_shared_density_measurements(
            resolved_units,
            context_by_objective_id=context_by_objective_id,
        )
        resolved_units = self._attach_objective_method_test_conditions_to_measurements(
            resolved_units
        )
        table_characterization_units = self._build_objective_table_characterization_units(
            units=resolved_units,
            objective_contexts=objective_contexts,
        )
        if table_characterization_units:
            resolved_units = (*resolved_units, *table_characterization_units)
        comparison_units = self._build_objective_pairwise_comparison_units(
            resolved_units,
            objective_contexts=objective_contexts,
        )
        if comparison_units:
            logger.info(
                "Research objective pairwise comparison units generated collection_id=%s comparison_unit_count=%s",
                collection_id,
                len(comparison_units),
            )
        return (*resolved_units, *comparison_units)

    def _objective_table_route_should_skip_llm_fallback(
        self,
        route: ObjectiveEvidenceRoute,
        *,
        objective_context: ObjectiveContext | None = None,
    ) -> bool:
        if route.source_kind != "table":
            return False
        role_text = " ".join(
            str(role or "").replace("_", " ").casefold()
            for role in route.column_roles.values()
        )
        has_result_like_role = any(
            token in role_text
            for token in (
                "process",
                "property",
                "result",
                "target",
                "measurement",
                "variable",
                "parameter",
                "resistance",
                "constant",
                "exponent",
                "evidence",
            )
        )
        if (
            route.role == "current_experimental_evidence"
            and objective_context is not None
            and has_result_like_role
            and not self._objective_route_result_columns(
                route,
                objective_context=objective_context,
            )
        ):
            return True
        if route.role != "test_condition":
            return False
        if not route.column_roles:
            return True
        return has_result_like_role

    def _objective_table_source_needs_llm_structural_repair(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        source: dict[str, Any],
    ) -> bool:
        if route.source_kind != "table":
            return False
        if route.role not in {"current_experimental_evidence", "process_or_treatment"}:
            return False
        cells = source.get("table_cells")
        if not isinstance(cells, list):
            return False
        return any(
            self._objective_cell_text_looks_structurally_fragmented(
                str(cell.get("cell_text") or "")
            )
            for cell in cells
            if isinstance(cell, dict)
        )

    def _objective_cell_text_looks_structurally_fragmented(self, text: str) -> bool:
        value = " ".join(str(text or "").split())
        if not value:
            return False
        if value.count("(") != value.count(")"):
            return True
        if value.count("[") != value.count("]"):
            return True
        if value.endswith(("/", "(", "[", "{")):
            return True
        if value.startswith((")", "]", "}")):
            return True
        return False

    def _objective_merge_table_repair_records(
        self,
        *,
        deterministic_records: tuple[dict[str, Any], ...],
        llm_records: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not deterministic_records:
            return llm_records
        if not llm_records:
            return deterministic_records
        preserved_records = tuple(
            record
            for record in deterministic_records
            if not (
                self._objective_evidence_record_has_fragmented_context(record)
                and any(
                    self._objective_evidence_records_have_same_result(record, llm_record)
                    for llm_record in llm_records
                )
            )
        )
        return (*preserved_records, *llm_records)

    def _objective_evidence_records_have_same_result(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> bool:
        left_key = self._objective_evidence_record_result_key(left)
        right_key = self._objective_evidence_record_result_key(right)
        if left_key is None or right_key is None:
            return False
        left_kind, left_property, left_unit, left_value = left_key
        right_kind, right_property, right_unit, right_value = right_key
        return (
            left_kind == right_kind
            and left_unit == right_unit
            and left_value == right_value
            and self._objective_result_properties_match(left_property, right_property)
        )

    def _objective_result_properties_match(self, left: str, right: str) -> bool:
        if not left or not right:
            return left == right
        return (
            left == right
            or self._axis_values_match(left, right)
            or left in right
            or right in left
        )

    def _objective_evidence_record_result_key(
        self,
        record: dict[str, Any],
    ) -> tuple[str, str, str, str] | None:
        value_payload = (
            record.get("value_payload")
            if isinstance(record.get("value_payload"), dict)
            else {}
        )
        raw_value = next(
            (
                candidate
                for candidate in (
                    value_payload.get("value"),
                    value_payload.get("source_value_text"),
                    value_payload.get("value_text"),
                )
                if candidate not in (None, "", [], {})
            ),
            None,
        )
        if raw_value in (None, "", [], {}):
            return None
        return (
            str(record.get("unit_kind") or "").strip().casefold(),
            str(record.get("property_normalized") or "").strip().casefold(),
            str(record.get("unit") or "").strip().casefold(),
            str(raw_value).strip().casefold(),
        )

    def _objective_evidence_record_has_fragmented_context(
        self,
        record: dict[str, Any],
    ) -> bool:
        return any(
            self._objective_payload_has_fragmented_text(record.get(field))
            for field in ("sample_context", "process_context", "test_condition", "join_keys")
        )

    def _objective_payload_has_fragmented_text(self, value: Any) -> bool:
        if isinstance(value, str):
            return self._objective_cell_text_looks_structurally_fragmented(value)
        if isinstance(value, Mapping):
            values = value.values()
        elif isinstance(value, (list, tuple)):
            values = value
        else:
            return False
        return any(self._objective_payload_has_fragmented_text(item) for item in values)

    def _build_objective_method_family_test_condition_units(
        self,
        *,
        objective_contexts: tuple[ObjectiveContext, ...],
        objective_paper_frames: tuple[ObjectivePaperFrame, ...],
        blocks_by_document_id: dict[str, list[Any]],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        context_by_objective_id = {
            context.objective_id: context
            for context in objective_contexts
        }
        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for frame in objective_paper_frames:
            if frame.relevance == "irrelevant":
                continue
            objective_context = context_by_objective_id.get(frame.objective_id)
            families = self._objective_method_families_for_context(objective_context)
            if not families:
                continue
            blocks = blocks_by_document_id.get(frame.document_id, [])
            for family in families:
                key = (frame.objective_id, frame.document_id, family)
                if key in seen:
                    continue
                candidate = self._objective_method_family_candidate(
                    family=family,
                    blocks=blocks,
                )
                if candidate is None:
                    continue
                block, quote, payload = candidate
                seen.add(key)
                source_ref = str(getattr(block, "block_id", "") or "")
                source_ref_payload = {
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                    "role": "test_condition",
                    "page": getattr(block, "page", None),
                }
                records.append(
                    {
                        "evidence_unit_id": self._objective_method_family_unit_id(
                            objective_id=frame.objective_id,
                            document_id=frame.document_id,
                            family=family,
                        ),
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "unit_kind": "test_condition",
                        "property_normalized": family,
                        "test_condition": {
                            "method_family": family,
                            **payload,
                        },
                        "value_payload": {
                            "method_family": family,
                            "evidence_quote": quote,
                        },
                        "source_refs": (
                            {
                                key: value
                                for key, value in source_ref_payload.items()
                                if value not in (None, "", [], {})
                            },
                        ),
                        "resolution_status": "resolved",
                        "confidence": 0.86,
                    }
                )
        return tuple(ObjectiveEvidenceUnit.from_mapping(record) for record in records)

    def _objective_method_families_for_context(
        self,
        objective_context: ObjectiveContext | None,
    ) -> tuple[str, ...]:
        if objective_context is None:
            return ()
        families: list[str] = []
        for axis in objective_context.target_property_axes:
            normalized = self._normalize_property_label(axis)
            if not normalized:
                continue
            property_candidates = (
                normalized,
                *_BROAD_PROPERTY_AXIS_EXPANSIONS.get(normalized, ()),
            )
            for property_name in property_candidates:
                family = self._objective_method_family_for_property(property_name)
                if family is not None:
                    families.append(family)
        return tuple(self._dedupe_preserving_order(families))

    def _objective_method_family_for_property(self, property_name: Any) -> str | None:
        normalized = self._normalize_property_label(property_name)
        if not normalized:
            return None
        if normalized in _OBJECTIVE_TENSILE_METHOD_PROPERTIES:
            return "tensile_mechanics"
        if normalized in _OBJECTIVE_MICROHARDNESS_METHOD_PROPERTIES:
            return "microhardness"
        if normalized in _OBJECTIVE_CHARACTERIZATION_METHOD_PROPERTIES:
            return "density_porosity_microstructure"
        return None

    def _objective_property_is_characterization(self, property_name: Any) -> bool:
        return (
            self._objective_method_family_for_property(property_name)
            == "density_porosity_microstructure"
        )

    def _objective_method_family_candidate(
        self,
        *,
        family: str,
        blocks: list[Any],
    ) -> tuple[Any, str, dict[str, Any]] | None:
        best: tuple[int, int, Any, str, dict[str, Any]] | None = None
        for position, block in enumerate(blocks):
            text = str(getattr(block, "text", "") or "").strip()
            if not text:
                continue
            combined_text = " ".join(
                part
                for part in (
                    str(getattr(block, "heading_path", "") or "").strip(),
                    text,
                )
                if part
            )
            score = self._score_objective_method_family_window(
                family=family,
                text=combined_text,
            )
            if score <= 0:
                continue
            quote = self._select_objective_method_family_quote(
                text,
                family=family,
            )
            if not quote:
                continue
            payload = self._build_objective_method_family_condition_payload(
                family=family,
                text=text,
            )
            if not payload:
                continue
            candidate = (score, -position, block, quote, payload)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None:
            return None
        _, _, block, quote, payload = best
        return block, quote, payload

    def _score_objective_method_family_window(
        self,
        *,
        family: str,
        text: str,
    ) -> int:
        lowered = text.casefold()
        if family == "tensile_mechanics":
            terms = (
                ("tensile", 4),
                ("stress-strain", 3),
                ("yield strength", 2),
                ("ultimate tensile", 2),
                ("astm e8", 4),
                ("instron", 4),
                ("strain rate", 2),
            )
        elif family == "microhardness":
            terms = (
                ("microhardness", 4),
                ("vickers", 4),
                ("hardness", 2),
                ("wilson", 3),
                ("holding time", 2),
                ("readings", 2),
            )
        elif family == "density_porosity_microstructure":
            terms = (
                ("sem", 3),
                ("imagej", 4),
                ("porosity", 3),
                ("relative density", 3),
                ("microstructure", 2),
                ("magnification", 2),
                ("horizontal", 1),
                ("vertical", 1),
            )
        else:
            return 0
        return sum(weight for term, weight in terms if term in lowered)

    def _build_objective_method_family_condition_payload(
        self,
        *,
        family: str,
        text: str,
    ) -> dict[str, Any]:
        if family == "tensile_mechanics":
            payload: dict[str, Any] = {
                "method": "tensile testing",
                "methods": ["tensile testing"],
                "test_method": "tensile testing",
                "standard": self._extract_first_pattern(
                    text,
                    r"\bASTM\s*E8M?\b",
                ),
                "instrument": self._extract_first_pattern(
                    text,
                    r"\bINSTRON\b[^.;,\n]*",
                ),
                "strain_rate_s-1": self._extract_first_pattern(
                    text,
                    r"\b\d+(?:\.\d+)?\s*mm\s*/\s*min\b",
                ),
                "specimen_geometry": (
                    "Fig. 2"
                    if re.search(r"\bFig\.\s*2\b", text, re.IGNORECASE)
                    else None
                ),
                "sample_orientation": self._extract_orientation_phrase(text),
                "details": self._compact_condition_details(text),
            }
        elif family == "microhardness":
            payload = {
                "method": "Vickers microhardness",
                "methods": ["Vickers microhardness"],
                "test_method": "Vickers microhardness",
                "instrument": self._extract_first_pattern(
                    text,
                    r"\b(?:Vickers\s+)?microhardness[^.;\n]*",
                ),
                "load": self._extract_first_pattern(text, r"\b\d+(?:\.\d+)?\s*N\b"),
                "holding_time": self._extract_first_pattern(
                    text,
                    r"\b\d+(?:\.\d+)?\s*s\b",
                ),
                "readings_per_sample": self._extract_first_pattern(
                    text,
                    r"\b\d+\s+(?:readings|measurements)\b[^.;\n]*",
                ),
                "sample_orientation": self._extract_orientation_phrase(text),
                "details": self._compact_condition_details(text),
            }
        else:
            payload = {
                "method": "SEM / ImageJ",
                "methods": self._dedupe_preserving_order(
                    [
                        method
                        for method in ("SEM", "ImageJ")
                        if method.casefold() in text.casefold()
                    ]
                )
                or ["SEM / ImageJ"],
                "test_method": "SEM / ImageJ",
                "instrument": self._extract_first_pattern(
                    text,
                    r"\bFEI[-\s]INSPECT\s*50\s*SEM\b",
                )
                or (
                    "SEM"
                    if re.search(r"\bSEM\b", text, re.IGNORECASE)
                    else None
                ),
                "section_orientation": self._extract_section_orientation_phrase(text),
                "surface_state": self._extract_surface_preparation_phrase(text),
                "magnification": self._extract_first_pattern(
                    text,
                    r"\b\d+(?:\.\d+)?\s*[xX]\s*(?:-|to)\s*\d+(?:\.\d+)?\s*[xX]\b",
                ),
                "details": self._compact_condition_details(text),
            }
        return {
            key: value
            for key, value in payload.items()
            if value not in (None, "", [], {})
        }

    def _select_objective_method_family_quote(
        self,
        text: str,
        *,
        family: str,
    ) -> str | None:
        terms = {
            "tensile_mechanics": ("tensile", "astm", "instron", "stress-strain"),
            "microhardness": ("microhardness", "vickers", "hardness", "wilson"),
            "density_porosity_microstructure": (
                "sem",
                "imagej",
                "porosity",
                "relative density",
                "microstructure",
            ),
        }.get(family, ())
        normalized_text = " ".join(str(text or "").split())
        if not normalized_text:
            return None
        for sentence in re.split(r"(?<=[.!?])\s+", normalized_text):
            if any(term in sentence.casefold() for term in terms):
                return sentence[:900].strip()
        return normalized_text[:900].strip()

    def _extract_first_pattern(
        self,
        text: str,
        pattern: str,
    ) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            return None
        return re.sub(r"\s+", " ", match.group(0)).strip()

    def _extract_orientation_phrase(self, text: str) -> str | None:
        lowered = text.casefold()
        if "horizontally" in lowered and "substrate" in lowered:
            return "all blocks built horizontally on substrate"
        if "horizontal" in lowered and "vertical" in lowered:
            return "horizontal and vertical sections"
        if "horizontal" in lowered:
            return "horizontal"
        if "vertical" in lowered:
            return "vertical"
        return None

    def _extract_section_orientation_phrase(self, text: str) -> str | None:
        lowered = text.casefold()
        if "horizontal" in lowered and "vertical" in lowered:
            return "horizontal and vertical sections"
        return self._extract_orientation_phrase(text)

    def _extract_surface_preparation_phrase(self, text: str) -> str | None:
        parts = []
        grit = self._extract_first_pattern(
            text,
            r"\b\d+\s*[-]\s*\d+\s*grit\b",
        )
        if grit:
            parts.append(grit)
        silica = self._extract_first_pattern(
            text,
            r"\bcolloidal\s+silica\b[^.;\n]*",
        )
        if silica:
            parts.append(silica)
        return "; ".join(parts) if parts else None

    def _compact_condition_details(self, text: str) -> str | None:
        normalized = " ".join(str(text or "").split())
        return normalized[:1000].strip() or None

    def _objective_method_family_unit_id(
        self,
        *,
        objective_id: str,
        document_id: str,
        family: str,
    ) -> str:
        seed = "|".join(("method_family", objective_id, document_id, family))
        return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"

    def _inherit_objective_material_systems(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
        *,
        objectives: tuple[ResearchObjective, ...] = (),
        objective_contexts: tuple[ObjectiveContext, ...],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        context_materials = {
            objective.objective_id: self._single_material_system_from_scope(
                objective.material_scope
            )
            for objective in objectives
        }
        context_materials.update(
            {
                context.objective_id: self._single_material_system_from_scope(
                    context.material_scope
                )
                for context in objective_contexts
                if context.material_scope
            }
        )
        if not any(context_materials.values()):
            return units

        resolved_units: list[ObjectiveEvidenceUnit] = []
        for unit in units:
            if self._has_observed_evidence_value(unit.material_system):
                resolved_units.append(unit)
                continue
            material_system = context_materials.get(unit.objective_id)
            if material_system is None:
                resolved_units.append(unit)
                continue
            record = unit.to_record()
            record["material_system"] = material_system
            resolved_units.append(ObjectiveEvidenceUnit.from_mapping(record))
        return tuple(resolved_units)

    def _single_material_system_from_scope(
        self,
        material_scope: tuple[str, ...],
    ) -> dict[str, str] | None:
        materials_by_key: dict[str, str] = {}
        for material in material_scope:
            text = str(material or "").strip()
            if not text or not self._has_observed_evidence_value(text):
                continue
            key = self._axis_key(text)
            if not key:
                continue
            materials_by_key.setdefault(key, text)
        if len(materials_by_key) != 1:
            return None
        return {"family": next(iter(materials_by_key.values()))}

    def _attach_objective_method_test_conditions_to_measurements(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        method_conditions = {
            (
                unit.objective_id,
                unit.document_id,
                str(unit.property_normalized or ""),
            ): unit
            for unit in units
            if unit.unit_kind == "test_condition"
            and unit.property_normalized in _OBJECTIVE_METHOD_FAMILY_PROPERTY_TYPES
        }
        if not method_conditions:
            return units

        resolved_units: list[ObjectiveEvidenceUnit] = []
        for unit in units:
            if unit.unit_kind != "measurement" or unit.test_condition:
                resolved_units.append(unit)
                continue
            family = self._objective_method_family_for_property(
                unit.property_normalized
            )
            if family is None:
                resolved_units.append(unit)
                continue
            condition = method_conditions.get(
                (unit.objective_id, unit.document_id, family)
            )
            if condition is None:
                resolved_units.append(unit)
                continue
            record = unit.to_record()
            record.update(
                {
                    "test_condition": dict(condition.test_condition),
                    "resolved_condition": {
                        **unit.resolved_condition,
                        "test_condition_unit_id": condition.evidence_unit_id,
                        "test_condition_family": family,
                    },
                    "resolution_status": "resolved",
                }
            )
            resolved_units.append(ObjectiveEvidenceUnit.from_mapping(record))
        return tuple(resolved_units)

    def _build_objective_table_characterization_units(
        self,
        *,
        units: tuple[ObjectiveEvidenceUnit, ...],
        objective_contexts: tuple[ObjectiveContext, ...],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        objective_ids_with_characterization_target = {
            context.objective_id
            for context in objective_contexts
            if any(
                self._objective_property_is_characterization(axis)
                for axis in context.target_property_axes
            )
        }
        density_units_by_scope: dict[tuple[str, str], list[ObjectiveEvidenceUnit]] = {}
        for unit in units:
            if unit.unit_kind != "measurement":
                continue
            if unit.objective_id not in objective_ids_with_characterization_target:
                continue
            if self._normalize_property_label(unit.property_normalized) not in {
                "density",
                "relative density",
            }:
                continue
            if self._objective_measurement_numeric_value(unit) is None:
                continue
            density_units_by_scope.setdefault(
                (unit.objective_id, unit.document_id),
                [],
            ).append(unit)

        records: list[dict[str, Any]] = []
        for (objective_id, document_id), density_units in density_units_by_scope.items():
            if not density_units:
                continue
            records.extend(
                self._objective_density_characterization_records(
                    objective_id=objective_id,
                    document_id=document_id,
                    density_units=density_units,
                )
            )
            records.extend(
                self._objective_strategy_characterization_records(
                    objective_id=objective_id,
                    document_id=document_id,
                    density_units=density_units,
                )
            )
        return tuple(ObjectiveEvidenceUnit.from_mapping(record) for record in records)

    def _objective_density_characterization_records(
        self,
        *,
        objective_id: str,
        document_id: str,
        density_units: list[ObjectiveEvidenceUnit],
    ) -> list[dict[str, Any]]:
        values = [
            (unit, self._objective_measurement_numeric_value(unit))
            for unit in density_units
        ]
        numeric_values = [
            (unit, value)
            for unit, value in values
            if value is not None
        ]
        if not numeric_values:
            return []
        min_value = min(value for _, value in numeric_values)
        max_unit, max_value = max(numeric_values, key=lambda item: item[1])
        sample_label = self._objective_sample_label(max_unit.sample_context)
        source_refs = self._dedupe_objective_source_refs(
            unit.source_refs
            for unit, _ in numeric_values
        )
        return [
            self._objective_characterization_record(
                objective_id=objective_id,
                document_id=document_id,
                characterization_type="density_porosity_sem_imagej",
                property_normalized="relative density",
                sample_context={"sample_count": len(numeric_values)},
                value_payload={
                    "relative_density_min": min_value,
                    "relative_density_max": max_value,
                    "sample_count": len(numeric_values),
                },
                unit="%",
                interpretation=(
                    "Table-derived SEM/ImageJ relative density evidence covers "
                    f"{len(numeric_values)} samples with relative density from "
                    f"{min_value:g}% to {max_value:g}%."
                ),
                source_refs=source_refs,
            ),
            self._objective_characterization_record(
                objective_id=objective_id,
                document_id=document_id,
                characterization_type="highest_density_sample",
                property_normalized="relative density",
                sample_context=dict(max_unit.sample_context),
                process_context=dict(max_unit.process_context),
                value_payload={
                    "relative_density": max_value,
                    "sample_label": sample_label,
                },
                unit="%",
                interpretation=(
                    f"Sample {sample_label} has the highest table-derived "
                    f"relative density at {max_value:g}%."
                ),
                source_refs=tuple(dict(ref) for ref in max_unit.source_refs),
            ),
        ]

    def _objective_strategy_characterization_records(
        self,
        *,
        objective_id: str,
        document_id: str,
        density_units: list[ObjectiveEvidenceUnit],
    ) -> list[dict[str, Any]]:
        units_by_strategy: dict[str, list[ObjectiveEvidenceUnit]] = {}
        for unit in density_units:
            strategy = self._objective_process_value(
                unit.process_context,
                "scan_strategy",
            )
            if strategy:
                units_by_strategy.setdefault(strategy.upper(), []).append(unit)

        records: list[dict[str, Any]] = []
        for strategy in sorted(units_by_strategy):
            strategy_units = units_by_strategy[strategy]
            values = [
                self._objective_measurement_numeric_value(unit)
                for unit in strategy_units
            ]
            numeric_values = [value for value in values if value is not None]
            if not numeric_values:
                continue
            sample_labels = self._dedupe_preserving_order(
                [
                    self._objective_sample_label(unit.sample_context)
                    for unit in strategy_units
                ]
            )
            records.append(
                self._objective_characterization_record(
                    objective_id=objective_id,
                    document_id=document_id,
                    characterization_type=f"scan_strategy_{strategy.lower()}",
                    property_normalized="relative density",
                    sample_context={
                        "scan_strategy": strategy,
                        "sample_labels": sample_labels,
                    },
                    value_payload={
                        "scan_strategy": strategy,
                        "relative_density_min": min(numeric_values),
                        "relative_density_max": max(numeric_values),
                    },
                    unit="%",
                    interpretation=(
                        f"Scan strategy {strategy} appears in samples "
                        f"{', '.join(sample_labels)} with table-derived relative "
                        f"density from {min(numeric_values):g}% to "
                        f"{max(numeric_values):g}%."
                    ),
                    source_refs=self._dedupe_objective_source_refs(
                        unit.source_refs for unit in strategy_units
                    ),
                )
            )
        return records

    def _objective_characterization_record(
        self,
        *,
        objective_id: str,
        document_id: str,
        characterization_type: str,
        property_normalized: str,
        sample_context: dict[str, Any],
        value_payload: dict[str, Any],
        unit: str,
        interpretation: str,
        source_refs: tuple[dict[str, Any], ...],
        process_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seed = "|".join(
            (
                "characterization",
                objective_id,
                document_id,
                characterization_type,
            )
        )
        return {
            "evidence_unit_id": f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}",
            "objective_id": objective_id,
            "document_id": document_id,
            "unit_kind": "characterization",
            "property_normalized": property_normalized,
            "sample_context": sample_context,
            "process_context": process_context or {},
            "test_condition": {
                "method": "SEM / ImageJ",
                "methods": ["SEM", "ImageJ"],
                "method_family": "density_porosity_microstructure",
            },
            "value_payload": {
                "characterization_type": characterization_type,
                **value_payload,
            },
            "unit": unit,
            "interpretation": interpretation,
            "source_refs": source_refs,
            "resolution_status": "resolved",
            "confidence": 0.86,
        }

    def _objective_process_value(
        self,
        process_context: dict[str, Any],
        target_key: str,
    ) -> str | None:
        for key, value in process_context.items():
            if self._objective_column_key(str(key)) == target_key:
                text = str(value or "").strip()
                return text or None
        return None

    def _objective_sample_label(self, sample_context: dict[str, Any]) -> str:
        for key in ("Sample number", "sample_number", "sample", "label"):
            value = sample_context.get(key)
            if value not in (None, ""):
                return str(value).strip()
        for key, value in sample_context.items():
            if "sample" in self._objective_column_key(str(key)) and value not in (
                None,
                "",
            ):
                return str(value).strip()
        return "sample"

    def _dedupe_objective_source_refs(
        self,
        source_ref_groups: Any,
    ) -> tuple[dict[str, Any], ...]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for refs in source_ref_groups:
            for ref in refs:
                key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(dict(ref))
        return tuple(deduped)

    def _resolve_objective_evidence_unit_contexts(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        context_units_by_key: dict[
            tuple[str, str, tuple[tuple[str, str], ...]],
            list[ObjectiveEvidenceUnit],
        ] = {}
        context_units_by_scope: dict[
            tuple[str, str],
            list[ObjectiveEvidenceUnit],
        ] = {}
        for unit in units:
            if unit.unit_kind == "measurement":
                continue
            if not unit.process_context and not unit.test_condition:
                continue
            context_units_by_scope.setdefault(
                (unit.objective_id, unit.document_id),
                [],
            ).append(unit)
            for key in self._objective_sample_context_match_keys(unit.sample_context):
                context_units_by_key.setdefault(
                    (unit.objective_id, unit.document_id, key),
                    [],
                ).append(unit)

        resolved_units: list[ObjectiveEvidenceUnit] = []
        for unit in units:
            if unit.unit_kind != "measurement":
                resolved_units.append(unit)
                continue
            context_unit = self._matching_objective_context_unit(
                unit=unit,
                context_units_by_key=context_units_by_key,
                context_units_by_scope=context_units_by_scope,
            )
            if context_unit is None:
                resolved_units.append(unit)
                continue
            merged_process_context = {
                **context_unit.process_context,
                **unit.process_context,
            }
            merged_test_condition = {
                **context_unit.test_condition,
                **unit.test_condition,
            }
            merged_sample_context = self._objective_resolved_sample_context(
                sample_context=unit.sample_context,
                context_sample_context=context_unit.sample_context,
            )
            if (
                merged_process_context == unit.process_context
                and merged_test_condition == unit.test_condition
                and merged_sample_context == unit.sample_context
            ):
                resolved_units.append(unit)
                continue
            resolved_condition = {
                **unit.resolved_condition,
                "context_unit_id": context_unit.evidence_unit_id,
                "matched_sample_context": dict(context_unit.sample_context),
            }
            record = unit.to_record()
            record.update(
                {
                    "process_context": merged_process_context,
                    "sample_context": merged_sample_context,
                    "test_condition": merged_test_condition,
                    "resolved_condition": resolved_condition,
                    "resolution_status": "resolved",
                }
            )
            resolved_units.append(ObjectiveEvidenceUnit.from_mapping(record))
        return tuple(resolved_units)

    def _dedupe_shared_density_measurements(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
        *,
        context_by_objective_id: dict[str, ObjectiveContext],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        best_by_key: dict[tuple[str, str, str, float, str], tuple[int, int]] = {}
        duplicate_keys: set[tuple[str, str, str, float, str]] = set()
        for index, unit in enumerate(units):
            key = self._shared_density_measurement_key(unit)
            if key is None:
                continue
            score = self._shared_density_measurement_objective_score(
                unit,
                objective_context=context_by_objective_id.get(unit.objective_id),
            )
            current = best_by_key.get(key)
            if current is None or score > current[0]:
                if current is not None:
                    duplicate_keys.add(key)
                best_by_key[key] = (score, index)
            else:
                duplicate_keys.add(key)
        if not duplicate_keys:
            return units

        keep_indexes = {
            index
            for key, (_score, index) in best_by_key.items()
            if key in duplicate_keys
        }
        deduped: list[ObjectiveEvidenceUnit] = []
        for index, unit in enumerate(units):
            key = self._shared_density_measurement_key(unit)
            if (
                key is not None
                and key in duplicate_keys
                and index not in keep_indexes
            ):
                continue
            deduped.append(unit)
        return tuple(deduped)

    def _shared_density_measurement_key(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> tuple[str, str, str, float, str] | None:
        if unit.unit_kind != "measurement":
            return None
        property_key = self._normalize_property_label(unit.property_normalized)
        if property_key not in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
            return None
        value = self._value_payload_numeric_value(unit.value_payload)
        if value is None:
            return None
        sample_key = self._objective_sample_identity_key(unit.sample_context)
        if not sample_key:
            return None
        return (
            unit.document_id,
            property_key,
            sample_key,
            value,
            str(unit.unit or "").casefold(),
        )

    def _shared_density_measurement_objective_score(
        self,
        unit: ObjectiveEvidenceUnit,
        *,
        objective_context: ObjectiveContext | None,
    ) -> int:
        if objective_context is None:
            return 0
        property_key = self._normalize_property_label(unit.property_normalized)
        if not property_key:
            return 0
        target_axes = self._objective_target_property_axes(objective_context)
        if self._property_axis_matches_any(property_key, target_axes):
            return 30
        if property_key in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
            if any(
                self._property_axis_matches_any(axis, _STRUCTURAL_PROPERTY_AXES)
                for axis in target_axes
            ):
                return 25
            if any(
                self._property_axis_matches_any(axis, _MECHANICAL_PROPERTY_AXES)
                for axis in target_axes
            ):
                return 20
        return 0

    def _objective_sample_identity_key(
        self,
        sample_context: dict[str, Any],
    ) -> str:
        for key in ("sample_number", "sample_id", "Sample number", "Sample"):
            value = str(sample_context.get(key) or "").strip()
            if value:
                return value.casefold()
        for key, value in sorted(sample_context.items()):
            value_text = str(value or "").strip()
            if value_text:
                return f"{key}:{value_text}".casefold()
        return ""

    def _matching_objective_context_unit(
        self,
        *,
        unit: ObjectiveEvidenceUnit,
        context_units_by_key: dict[
            tuple[str, str, tuple[tuple[str, str], ...]],
            list[ObjectiveEvidenceUnit],
        ],
        context_units_by_scope: dict[
            tuple[str, str],
            list[ObjectiveEvidenceUnit],
        ],
    ) -> ObjectiveEvidenceUnit | None:
        scope_candidates = context_units_by_scope.get(
            (unit.objective_id, unit.document_id),
            [],
        )
        if self._objective_sample_context_has_process_label(unit.sample_context):
            label_context_unit = self._matching_objective_process_label_context_unit(
                unit=unit,
                candidates=scope_candidates,
            )
            if label_context_unit is not None:
                return label_context_unit
        for key in self._objective_sample_context_match_keys(unit.sample_context):
            candidates = context_units_by_key.get(
                (unit.objective_id, unit.document_id, key),
                [],
            )
            if len(candidates) == 1:
                return candidates[0]
            process_context_candidates = [
                candidate
                for candidate in candidates
                if candidate.unit_kind == "process_context"
            ]
            if len(process_context_candidates) == 1:
                return process_context_candidates[0]
        return self._matching_objective_process_label_context_unit(
            unit=unit,
            candidates=scope_candidates,
        )

    def _objective_sample_context_has_process_label(
        self,
        sample_context: dict[str, Any],
    ) -> bool:
        if self._objective_sample_context_has_stable_label(sample_context):
            return True
        sample_number_keys = {
            "condition",
            "condition_no",
            "condition_number",
            "sample_no",
            "sample_number",
        }
        for key, value in sample_context.items():
            if self._objective_column_key(str(key)) in sample_number_keys:
                continue
            if re.search(r"[A-Za-z]", str(value or "")):
                return True
        return False

    def _objective_resolved_sample_context(
        self,
        *,
        sample_context: dict[str, Any],
        context_sample_context: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(sample_context)
        if self._objective_sample_context_has_explicit_number(merged):
            return merged
        for key, value in context_sample_context.items():
            if self._objective_column_key(str(key)) not in {
                "sample_no",
                "sample_number",
            }:
                continue
            if str(value).strip():
                merged[key] = value
                break
        return merged

    def _matching_objective_process_label_context_unit(
        self,
        *,
        unit: ObjectiveEvidenceUnit,
        candidates: list[ObjectiveEvidenceUnit],
    ) -> ObjectiveEvidenceUnit | None:
        match_fragments = [
            str(value).strip()
            for value in (
                tuple(unit.sample_context.values())
                + tuple(unit.process_context.values())
            )
            if str(value).strip()
        ]
        if not match_fragments:
            return None
        match_numbers: set[str] = set()
        for fragment in match_fragments:
            match_numbers.update(self._objective_numeric_match_tokens(fragment))
        match_text = self._objective_match_text(" ".join(match_fragments))
        scored: list[tuple[int, ObjectiveEvidenceUnit]] = []
        for candidate in candidates:
            if not candidate.process_context:
                continue
            score = self._objective_process_label_match_score(
                process_context=candidate.process_context,
                sample_numbers=match_numbers,
                sample_text=match_text,
            )
            if score >= 2:
                scored.append((score, candidate))
        if not scored:
            return None
        best_score = max(score for score, _candidate in scored)
        winners = [
            candidate
            for score, candidate in scored
            if score == best_score
        ]
        if len(winners) == 1:
            return winners[0]
        sample_number_keys = {
            "condition",
            "condition_no",
            "condition_number",
            "sample_no",
            "sample_number",
        }
        labeled_winners: list[tuple[ObjectiveEvidenceUnit, set[str]]] = []
        for candidate in winners:
            candidate_label_tokens = self._objective_context_label_tokens(
                candidate.sample_context,
                skip_keys=sample_number_keys,
            ) | self._objective_context_label_tokens(candidate.process_context)
            if candidate_label_tokens:
                labeled_winners.append((candidate, candidate_label_tokens))
        if len(labeled_winners) == 1:
            return labeled_winners[0][0]
        match_label_tokens = {
            token
            for token in match_text.split()
            if len(token) > 1 and not token.isdigit()
        }
        if match_label_tokens:
            scored_labeled_winners = [
                (len(candidate_label_tokens & match_label_tokens), candidate)
                for candidate, candidate_label_tokens in labeled_winners
            ]
            best_label_score = max(
                (score for score, _candidate in scored_labeled_winners),
                default=0,
            )
            best_labeled_winners = [
                candidate
                for score, candidate in scored_labeled_winners
                if score == best_label_score and score > 0
            ]
            if len(best_labeled_winners) == 1:
                return best_labeled_winners[0]
            sample_labeled_winners = [
                candidate
                for candidate in best_labeled_winners
                if self._objective_context_label_tokens(
                    candidate.sample_context,
                    skip_keys=sample_number_keys,
                )
            ]
            if len(sample_labeled_winners) == 1:
                return sample_labeled_winners[0]
        numbered_winners = [
            candidate
            for candidate in winners
            if self._objective_sample_context_has_explicit_number(
                candidate.sample_context
            )
        ]
        if len(numbered_winners) == 1:
            return numbered_winners[0]
        return None

    def _objective_context_label_tokens(
        self,
        context: dict[str, Any],
        *,
        skip_keys: set[str] | None = None,
    ) -> set[str]:
        tokens: set[str] = set()
        for key, value in context.items():
            column_key = self._objective_column_key(str(key))
            if skip_keys is not None and column_key in skip_keys:
                continue
            if not self._objective_context_key_carries_label(column_key):
                continue
            if not re.search(r"[A-Za-z]", str(value or "")):
                continue
            tokens.update(self._objective_text_label_tokens(value))
        return tokens

    def _objective_context_key_carries_label(self, column_key: str) -> bool:
        return (
            column_key
            in {
                "id",
                "label",
                "sample",
                "sample_id",
                "sample_label",
                "specimen",
                "specimens",
            }
            or "sample" in column_key
            or "specimen" in column_key
            or "treatment" in column_key
        )

    def _objective_text_label_tokens(self, value: Any) -> set[str]:
        return {
            token
            for token in self._objective_match_text(value).split()
            if len(token) > 1 and not token.isdigit()
        }

    def _objective_process_label_match_score(
        self,
        *,
        process_context: dict[str, Any],
        sample_numbers: set[str],
        sample_text: str,
    ) -> int:
        score = 0
        sample_tokens = self._objective_text_label_tokens(sample_text)
        for key, value in process_context.items():
            value_text = str(value).strip()
            if not value_text:
                continue
            for token in self._objective_numeric_match_tokens(value_text):
                if token in {"1", "-1"}:
                    continue
                if token in sample_numbers:
                    score += 1
            normalized_value = self._objective_match_text(value_text)
            if len(normalized_value) >= 3 and normalized_value in sample_text:
                score += 1
            column_key = self._objective_column_key(str(key))
            if sample_tokens and self._objective_context_key_carries_label(
                column_key
            ):
                score += len(
                    self._objective_text_label_tokens(value_text) & sample_tokens
                )
        return score

    def _objective_numeric_match_tokens(self, value: Any) -> tuple[str, ...]:
        tokens: list[str] = []
        for match in _NUMBER_PATTERN.finditer(str(value or "").replace(",", "")):
            number_text = match.group(0)
            number = self._coerce_number(number_text)
            if number is None:
                continue
            if number.is_integer():
                tokens.append(str(int(number)))
            else:
                tokens.append(("%f" % number).rstrip("0").rstrip("."))
        return tuple(tokens)

    def _objective_match_text(self, value: Any) -> str:
        return " ".join(
            re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split()
        )

    def _build_objective_pairwise_comparison_units(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
        *,
        objective_contexts: tuple[ObjectiveContext, ...],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        context_by_objective_id = {
            context.objective_id: context
            for context in objective_contexts
        }
        existing_keys = {
            self._objective_comparison_pair_key(unit)
            for unit in units
            if unit.unit_kind == "comparison"
        }
        measurements_by_key: dict[
            tuple[str, str, str, str | None],
            list[ObjectiveEvidenceUnit],
        ] = {}
        allowed_pair_specs_by_scope = self._objective_pairwise_allowed_specs(
            units,
            context_by_objective_id=context_by_objective_id,
        )
        for unit in units:
            objective_context = context_by_objective_id.get(unit.objective_id)
            if unit.unit_kind != "measurement":
                continue
            if (
                not unit.property_normalized
                or not unit.sample_context
                or not self._objective_unit_has_pairwise_context(unit)
                or self._objective_measurement_numeric_value(unit) is None
                or not self._objective_unit_matches_target_property(
                    unit,
                    objective_context=objective_context,
                )
            ):
                continue
            measurements_by_key.setdefault(
                (
                    unit.objective_id,
                    unit.document_id,
                    unit.property_normalized,
                    unit.unit,
                ),
                [],
            ).append(unit)

        generated: list[ObjectiveEvidenceUnit] = []
        generated_keys: set[tuple[str, str, str, str, str, str]] = set()
        for (
            objective_id,
            _document_id,
            _property_normalized,
            _unit,
        ), measurements in measurements_by_key.items():
            objective_context = context_by_objective_id.get(objective_id)
            allow_multi_axis = False
            if len(measurements) <= 3:
                allow_multi_axis = not any(
                    self._objective_single_changed_axis(
                        current=current,
                        baseline=candidate,
                        objective_context=objective_context,
                    )
                    is not None
                    for current_index, current in enumerate(measurements)
                    for candidate in measurements[current_index + 1:]
                )
            for current_index, current in enumerate(measurements):
                for candidate in measurements[current_index + 1:]:
                    comparison_axis = self._objective_single_changed_axis(
                        current=current,
                        baseline=candidate,
                        objective_context=objective_context,
                        allow_multi_axis=allow_multi_axis,
                    )
                    if comparison_axis is None:
                        continue
                    allowed_pair_specs = allowed_pair_specs_by_scope.get(
                        (objective_id, current.document_id)
                    )
                    if allowed_pair_specs is not None and (
                        self._objective_pairwise_relation_spec_key(current, candidate)
                        not in allowed_pair_specs
                    ):
                        continue
                    comparison_unit = self._objective_pairwise_comparison_unit(
                        first=current,
                        second=candidate,
                        comparison_axis=comparison_axis,
                        objective_context=objective_context,
                    )
                    pair_key = self._objective_comparison_pair_key(comparison_unit)
                    if pair_key in existing_keys or pair_key in generated_keys:
                        continue
                    generated_keys.add(pair_key)
                    generated.append(comparison_unit)
        return self._select_objective_comparison_units(tuple(generated))

    def _select_objective_comparison_units(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
    ) -> tuple[ObjectiveEvidenceUnit, ...]:
        if not units:
            return ()
        scope_counts: dict[tuple[str, str], int] = {}
        for unit in units:
            scope_key = (unit.objective_id, unit.document_id)
            scope_counts[scope_key] = scope_counts.get(scope_key, 0) + 1
        if all(
            count <= _OBJECTIVE_PAIRWISE_LARGE_SCOPE_LIMIT
            for count in scope_counts.values()
        ):
            return units

        grouped_units: dict[tuple[str, str, str, str], list[ObjectiveEvidenceUnit]] = {}
        for unit in units:
            scope_key = (unit.objective_id, unit.document_id)
            if scope_counts.get(scope_key, 0) <= _OBJECTIVE_PAIRWISE_LARGE_SCOPE_LIMIT:
                continue
            comparison_axis = str(unit.value_payload.get("comparison_axis") or "")
            axis_key = self._normalize_property_label(comparison_axis) or comparison_axis
            grouped_units.setdefault(
                (
                    unit.objective_id,
                    unit.document_id,
                    str(unit.property_normalized or ""),
                    axis_key,
                ),
                [],
            ).append(unit)

        selected_ids: set[str] = set()
        for group in grouped_units.values():
            selected_ids.update(
                unit.evidence_unit_id
                for unit in sorted(
                    group,
                    key=self._objective_comparison_unit_selection_key,
                )[:_OBJECTIVE_PAIRWISE_GROUP_LIMIT]
            )

        return tuple(
            unit
            for unit in units
            if scope_counts.get((unit.objective_id, unit.document_id), 0)
            <= _OBJECTIVE_PAIRWISE_LARGE_SCOPE_LIMIT
            or unit.evidence_unit_id in selected_ids
        )

    def _objective_comparison_unit_selection_key(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> tuple[int, float, str, str, str]:
        controlled_axes = unit.value_payload.get("controlled_axes")
        controlled_axis_count = (
            len(controlled_axes) if isinstance(controlled_axes, list) else 0
        )
        current_value = self._coerce_number(
            unit.value_payload.get("current_value")
            or unit.value_payload.get("value")
        )
        baseline_value = self._coerce_number(unit.baseline_context.get("value"))
        delta = (
            abs(current_value - baseline_value)
            if current_value is not None and baseline_value is not None
            else 0.0
        )
        baseline_sample_context = unit.baseline_context.get("sample_context")
        if not isinstance(baseline_sample_context, dict):
            baseline_sample_context = {}
        return (
            -controlled_axis_count,
            -delta,
            self._objective_sample_identity_key(unit.sample_context),
            self._objective_sample_identity_key(baseline_sample_context),
            unit.evidence_unit_id,
        )

    def _objective_pairwise_allowed_specs(
        self,
        units: tuple[ObjectiveEvidenceUnit, ...],
        *,
        context_by_objective_id: dict[str, ObjectiveContext],
    ) -> dict[tuple[str, str], set[tuple[str, str, str]]]:
        numeric_measurements = tuple(
            unit
            for unit in units
            if unit.unit_kind == "measurement"
            and unit.property_normalized
            and unit.sample_context
            and self._objective_unit_has_pairwise_context(unit)
            and self._objective_measurement_numeric_value(unit) is not None
            and self._objective_unit_matches_target_property(
                unit,
                objective_context=context_by_objective_id.get(unit.objective_id),
            )
        )
        document_density_values = self._objective_document_density_values(
            numeric_measurements
        )
        samples_by_scope: dict[tuple[str, str], dict[str, ObjectiveEvidenceUnit]] = {}
        results_by_scope: dict[
            tuple[str, str],
            dict[tuple[str, str], ObjectiveEvidenceUnit],
        ] = {}
        for unit in numeric_measurements:
            sample_key = self._objective_sample_identity_key(unit.sample_context)
            property_key = self._objective_pairwise_property_key(
                unit.property_normalized
            )
            if not sample_key or not property_key:
                continue
            scope_key = (unit.objective_id, unit.document_id)
            samples_by_scope.setdefault(scope_key, {}).setdefault(sample_key, unit)
            results_by_scope.setdefault(scope_key, {})[(sample_key, property_key)] = unit

        allowed_specs_by_scope: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
        for scope_key, samples_by_key in samples_by_scope.items():
            allowed_specs_by_scope[scope_key] = (
                self._select_objective_pairwise_relation_specs(
                    document_id=scope_key[1],
                    samples=list(samples_by_key.values()),
                    result_lookup=results_by_scope.get(scope_key, {}),
                    document_density_values=document_density_values,
                    objective_context=context_by_objective_id.get(scope_key[0]),
                )
            )
        return allowed_specs_by_scope

    def _select_objective_pairwise_relation_specs(
        self,
        *,
        document_id: str,
        samples: list[ObjectiveEvidenceUnit],
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
        document_density_values: dict[tuple[str, str], float],
        objective_context: ObjectiveContext | None,
    ) -> set[tuple[str, str, str]]:
        all_specs = self._objective_all_pairwise_relation_specs(
            samples=samples,
            result_lookup=result_lookup,
        )
        if len(samples) <= 3:
            return all_specs

        pbf_samples: list[dict[str, Any]] = []
        density_values: dict[str, float] = {}
        for sample in samples:
            sample_key = self._objective_sample_identity_key(sample.sample_context)
            pbf_context = self._objective_pbf_process_context(sample.process_context)
            density_value = document_density_values.get((document_id, sample_key))
            if not sample_key or pbf_context is None or density_value is None:
                return self._select_objective_adjacent_axis_relation_specs(
                    samples=samples,
                    result_lookup=result_lookup,
                    objective_context=objective_context,
                )
            density_values[sample_key] = density_value
            pbf_samples.append(
                {
                    "sample": sample,
                    "sample_key": sample_key,
                    "scan_strategy": pbf_context["scan_strategy"],
                    "scan_speed_mm_s": pbf_context["scan_speed_mm_s"],
                    "energy_density_j_mm3": pbf_context["energy_density_j_mm3"],
                }
            )

        primary = max(
            pbf_samples,
            key=lambda item: density_values.get(str(item["sample_key"]), -math.inf),
        )
        primary_strategy = str(primary.get("scan_strategy") or "").strip()
        if not primary_strategy:
            return all_specs

        selected_specs: set[tuple[str, str, str]] = set()
        speed_groups: dict[tuple[float, str], list[dict[str, Any]]] = {}
        strategy_groups: dict[tuple[float, float], list[dict[str, Any]]] = {}
        for item in pbf_samples:
            speed_groups.setdefault(
                (item["energy_density_j_mm3"], item["scan_strategy"]),
                [],
            ).append(item)
            strategy_groups.setdefault(
                (item["energy_density_j_mm3"], item["scan_speed_mm_s"]),
                [],
            ).append(item)

        for (_, strategy), group in speed_groups.items():
            if strategy != primary_strategy or len(group) < 2:
                continue
            for left_index, left in enumerate(group):
                for right in group[left_index + 1:]:
                    for property_name in _OBJECTIVE_PAIRWISE_TENSILE_PROPERTIES:
                        self._add_objective_pairwise_spec_if_numeric_delta(
                            selected_specs,
                            left=left["sample"],
                            right=right["sample"],
                            property_name=property_name,
                            result_lookup=result_lookup,
                        )
                    self._add_objective_pairwise_spec_if_numeric_delta(
                        selected_specs,
                        left=left["sample"],
                        right=right["sample"],
                        property_name=_OBJECTIVE_PAIRWISE_DUCTILITY_PROPERTY,
                        result_lookup=result_lookup,
                        min_abs_delta=_OBJECTIVE_PAIRWISE_ELONGATION_MIN_DELTA,
                    )
                    density_property = self._objective_density_property_for_pair(
                        left["sample"],
                        right["sample"],
                        result_lookup=result_lookup,
                    )
                    if density_property:
                        self._add_objective_pairwise_spec_if_numeric_delta(
                            selected_specs,
                            left=left["sample"],
                            right=right["sample"],
                            property_name=density_property,
                            result_lookup=result_lookup,
                            min_abs_delta=_OBJECTIVE_PAIRWISE_DENSITY_MIN_DELTA,
                        )

        eligible_strategy_groups = [
            (key, group)
            for key, group in strategy_groups.items()
            if len(group) >= 2
            and any(item["scan_strategy"] == primary_strategy for item in group)
        ]
        if eligible_strategy_groups:
            first_group_key, first_group = sorted(
                eligible_strategy_groups,
                key=lambda item: (item[0][0], -item[0][1]),
            )[0]
            primary_group_key = next(
                (
                    key
                    for key, group in strategy_groups.items()
                    if any(
                        item["sample_key"] == primary["sample_key"]
                        for item in group
                    )
                ),
                None,
            )
            primary_group = (
                strategy_groups.get(primary_group_key, [])
                if primary_group_key is not None
                else []
            )

            self._add_objective_first_strategy_group_specs(
                selected_specs,
                group=first_group,
                primary_strategy=primary_strategy,
                density_values=density_values,
                result_lookup=result_lookup,
            )
            if primary_group and primary_group_key != first_group_key:
                self._add_objective_primary_strategy_group_specs(
                    selected_specs,
                    group=primary_group,
                    primary_sample_key=str(primary["sample_key"]),
                    result_lookup=result_lookup,
                )

        return selected_specs or all_specs

    def _select_objective_adjacent_axis_relation_specs(
        self,
        *,
        samples: list[ObjectiveEvidenceUnit],
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
        objective_context: ObjectiveContext | None,
    ) -> set[tuple[str, str, str]]:
        if objective_context is None:
            return set()
        axes = tuple(
            self._normalize_property_label(axis)
            for axis in objective_context.variable_process_axes
            if self._normalize_property_label(axis)
        )
        if not axes:
            return set()
        sample_rows: list[tuple[ObjectiveEvidenceUnit, str, dict[str, str]]] = []
        observed_raw_axes: set[str] = set()
        for sample in samples:
            sample_key = self._objective_sample_identity_key(sample.sample_context)
            axis_values = self._objective_process_axis_values(
                sample,
                objective_context=objective_context,
            )
            raw_axis_values = self._objective_raw_process_axis_values(sample)
            if raw_axis_values:
                observed_raw_axes.update(raw_axis_values)
                axis_values = {**axis_values, **raw_axis_values}
            if sample_key and axis_values:
                sample_rows.append((sample, sample_key, axis_values))
        axes = (*axes, *tuple(sorted(observed_raw_axes - set(axes))))
        property_names = {
            property_name
            for sample_key, property_name in result_lookup.keys()
            if sample_key
        }
        selected_specs: set[tuple[str, str, str]] = set()
        for axis in axes:
            grouped: dict[tuple[tuple[str, str], ...], list[tuple[ObjectiveEvidenceUnit, str, str]]] = {}
            for sample, sample_key, axis_values in sample_rows:
                if axis not in axis_values:
                    continue
                group_key = tuple(
                    sorted(
                        (other_axis, value)
                        for other_axis, value in axis_values.items()
                        if other_axis != axis
                    )
                )
                grouped.setdefault(group_key, []).append(
                    (sample, sample_key, axis_values[axis])
                )
            for group in grouped.values():
                ordered = sorted(
                    group,
                    key=lambda item: self._objective_axis_sort_key(item[2]),
                )
                for left, right in zip(ordered, ordered[1:]):
                    if left[2] == right[2]:
                        continue
                    for property_name in property_names:
                        self._add_objective_pairwise_spec_if_numeric_delta(
                            selected_specs,
                            left=left[0],
                            right=right[0],
                            property_name=property_name,
                            result_lookup=result_lookup,
                        )
        return selected_specs

    def _objective_axis_sort_key(self, value: Any) -> tuple[int, float | str]:
        numeric_value = self._coerce_number(value)
        if numeric_value is not None:
            return (0, numeric_value)
        return (1, str(value).strip().casefold())

    def _objective_all_pairwise_relation_specs(
        self,
        *,
        samples: list[ObjectiveEvidenceUnit],
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> set[tuple[str, str, str]]:
        specs: set[tuple[str, str, str]] = set()
        property_names = {
            property_name
            for sample_key, property_name in result_lookup.keys()
            if sample_key
        }
        for left_index, left in enumerate(samples):
            for right in samples[left_index + 1:]:
                for property_name in property_names:
                    left_value, right_value = self._objective_pairwise_result_values(
                        left=left,
                        right=right,
                        property_name=property_name,
                        result_lookup=result_lookup,
                    )
                    if left_value is None or right_value is None:
                        continue
                    specs.add(
                        self._objective_pairwise_relation_spec_key(
                            left,
                            right,
                            property_name=property_name,
                        )
                    )
        return specs

    def _add_objective_first_strategy_group_specs(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        group: list[dict[str, Any]],
        primary_strategy: str,
        density_values: dict[str, float],
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> None:
        density_ordered = sorted(
            group,
            key=lambda item: density_values.get(str(item["sample_key"]), -math.inf),
        )
        for lower, higher in zip(density_ordered, density_ordered[1:]):
            density_property = self._objective_density_property_for_pair(
                lower["sample"],
                higher["sample"],
                result_lookup=result_lookup,
            )
            if density_property:
                self._add_objective_pairwise_spec_if_numeric_delta(
                    selected_specs,
                    left=lower["sample"],
                    right=higher["sample"],
                    property_name=density_property,
                    result_lookup=result_lookup,
                )

        primary_sample = next(
            (
                item
                for item in group
                if str(item.get("scan_strategy") or "") == primary_strategy
            ),
            None,
        )
        secondary_sample = next(
            (
                item
                for item in sorted(
                    group,
                    key=lambda item: str(item.get("scan_strategy") or ""),
                )
                if str(item.get("scan_strategy") or "") != primary_strategy
            ),
            None,
        )
        if primary_sample is None or secondary_sample is None:
            return
        for property_name in (
            *_OBJECTIVE_PAIRWISE_TENSILE_PROPERTIES,
            _OBJECTIVE_PAIRWISE_DUCTILITY_PROPERTY,
        ):
            self._add_objective_pairwise_spec_if_current_higher(
                selected_specs,
                current=primary_sample["sample"],
                reference=secondary_sample["sample"],
                property_name=property_name,
                result_lookup=result_lookup,
            )

    def _add_objective_primary_strategy_group_specs(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        group: list[dict[str, Any]],
        primary_sample_key: str,
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> None:
        primary_sample = next(
            (item for item in group if item["sample_key"] == primary_sample_key),
            None,
        )
        if primary_sample is None:
            return
        for reference_sample in group:
            if reference_sample["sample_key"] == primary_sample_key:
                continue
            for property_name in (
                "yield strength",
                _OBJECTIVE_PAIRWISE_DUCTILITY_PROPERTY,
            ):
                self._add_objective_pairwise_spec_if_current_higher(
                    selected_specs,
                    current=primary_sample["sample"],
                    reference=reference_sample["sample"],
                    property_name=property_name,
                    result_lookup=result_lookup,
                )

    def _add_objective_pairwise_spec_if_current_higher(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        current: ObjectiveEvidenceUnit,
        reference: ObjectiveEvidenceUnit,
        property_name: str,
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> None:
        current_value, reference_value = self._objective_pairwise_result_values(
            left=current,
            right=reference,
            property_name=property_name,
            result_lookup=result_lookup,
        )
        if current_value is None or reference_value is None:
            return
        if current_value <= reference_value:
            return
        selected_specs.add(
            self._objective_pairwise_relation_spec_key(
                current,
                reference,
                property_name=property_name,
            )
        )

    def _add_objective_pairwise_spec_if_numeric_delta(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        left: ObjectiveEvidenceUnit,
        right: ObjectiveEvidenceUnit,
        property_name: str,
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
        min_abs_delta: float = 0.0,
    ) -> None:
        left_value, right_value = self._objective_pairwise_result_values(
            left=left,
            right=right,
            property_name=property_name,
            result_lookup=result_lookup,
        )
        if left_value is None or right_value is None:
            return
        if math.isclose(left_value, right_value):
            return
        if abs(left_value - right_value) < min_abs_delta:
            return
        selected_specs.add(
            self._objective_pairwise_relation_spec_key(
                left,
                right,
                property_name=property_name,
            )
        )

    def _objective_pairwise_result_values(
        self,
        *,
        left: ObjectiveEvidenceUnit,
        right: ObjectiveEvidenceUnit,
        property_name: str,
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> tuple[float | None, float | None]:
        return (
            self._objective_pairwise_result_value(
                sample_key=self._objective_sample_identity_key(left.sample_context),
                property_name=property_name,
                result_lookup=result_lookup,
            ),
            self._objective_pairwise_result_value(
                sample_key=self._objective_sample_identity_key(right.sample_context),
                property_name=property_name,
                result_lookup=result_lookup,
            ),
        )

    def _objective_pairwise_result_value(
        self,
        *,
        sample_key: str,
        property_name: str,
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> float | None:
        unit = result_lookup.get((sample_key, property_name))
        if unit is None:
            return None
        return self._objective_measurement_numeric_value(unit)

    def _objective_density_property_for_pair(
        self,
        left: ObjectiveEvidenceUnit,
        right: ObjectiveEvidenceUnit,
        *,
        result_lookup: dict[tuple[str, str], ObjectiveEvidenceUnit],
    ) -> str | None:
        left_key = self._objective_sample_identity_key(left.sample_context)
        right_key = self._objective_sample_identity_key(right.sample_context)
        for property_name in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
            if (
                result_lookup.get((left_key, property_name)) is not None
                and result_lookup.get((right_key, property_name)) is not None
            ):
                return property_name
        return None

    def _objective_document_density_values(
        self,
        measurements: tuple[ObjectiveEvidenceUnit, ...],
    ) -> dict[tuple[str, str], float]:
        values: dict[tuple[str, str], float] = {}
        for unit in measurements:
            property_key = self._objective_pairwise_property_key(
                unit.property_normalized
            )
            if property_key not in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
                continue
            sample_key = self._objective_sample_identity_key(unit.sample_context)
            numeric_value = self._objective_measurement_numeric_value(unit)
            if not sample_key or numeric_value is None:
                continue
            values[(unit.document_id, sample_key)] = numeric_value
        return values

    def _objective_pbf_process_context(
        self,
        process_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        scan_strategy: str | None = None
        scan_speed: float | None = None
        energy_density: float | None = None
        for key, value in process_context.items():
            key_text = self._objective_column_key(str(key))
            if "scan" in key_text and "strategy" in key_text:
                scan_strategy = str(value).strip()
            elif "scan" in key_text and "speed" in key_text:
                scan_speed = self._coerce_number(value)
            elif "energy" in key_text and "density" in key_text:
                energy_density = self._coerce_number(value)
        if not scan_strategy or scan_speed is None or energy_density is None:
            return None
        return {
            "scan_strategy": scan_strategy,
            "scan_speed_mm_s": scan_speed,
            "energy_density_j_mm3": energy_density,
        }

    def _objective_pairwise_property_key(self, value: Any) -> str | None:
        return self._normalize_property_label(value)

    def _objective_unit_matches_target_property(
        self,
        unit: ObjectiveEvidenceUnit,
        *,
        objective_context: ObjectiveContext | None,
    ) -> bool:
        if objective_context is None or not objective_context.target_property_axes:
            return True
        property_key = self._objective_pairwise_property_key(unit.property_normalized)
        if not property_key:
            return False
        target_axes = self._objective_target_property_axes(objective_context)
        if self._objective_property_label_matches_target(
            property_key,
            target_axes=target_axes,
        ):
            return True
        return self._objective_density_property_matches_structural_target(
            property_key,
            target_axes=target_axes,
        )

    def _objective_pairwise_relation_spec_key(
        self,
        left: ObjectiveEvidenceUnit,
        right: ObjectiveEvidenceUnit,
        *,
        property_name: str | None = None,
    ) -> tuple[str, str, str]:
        left_sample = self._objective_sample_identity_key(left.sample_context)
        right_sample = self._objective_sample_identity_key(right.sample_context)
        first, second = sorted((left_sample, right_sample))
        property_key = property_name or self._objective_pairwise_property_key(
            left.property_normalized
        )
        return first, second, str(property_key or "")

    def _objective_single_changed_axis(
        self,
        *,
        current: ObjectiveEvidenceUnit,
        baseline: ObjectiveEvidenceUnit,
        objective_context: ObjectiveContext | None,
        allow_multi_axis: bool = False,
    ) -> str | None:
        axis_pairs = (
            (
                self._objective_process_axis_values(
                    current,
                    objective_context=objective_context,
                ),
                self._objective_process_axis_values(
                    baseline,
                    objective_context=objective_context,
                ),
            ),
            (
                self._objective_sample_axis_values(current),
                self._objective_sample_axis_values(baseline),
            ),
            (
                self._objective_raw_process_axis_values(current),
                self._objective_raw_process_axis_values(baseline),
            ),
        )
        for current_axes, baseline_axes in axis_pairs:
            comparison_axis = self._objective_single_changed_axis_from_values(
                current_axes=current_axes,
                baseline_axes=baseline_axes,
                allow_multi_axis=allow_multi_axis,
            )
            if comparison_axis is not None:
                return comparison_axis
        return None

    def _objective_single_changed_axis_from_values(
        self,
        *,
        current_axes: dict[str, str],
        baseline_axes: dict[str, str],
        allow_multi_axis: bool,
    ) -> str | None:
        if not current_axes or not baseline_axes:
            return None
        changed_axes = [
            axis
            for axis in current_axes
            if axis in baseline_axes and current_axes[axis] != baseline_axes[axis]
        ]
        if len(changed_axes) != 1:
            if allow_multi_axis and len(changed_axes) > 1:
                return ", ".join(changed_axes)
            return None
        return changed_axes[0]

    def _objective_unit_has_pairwise_context(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> bool:
        return bool(unit.process_context or self._objective_sample_axis_values(unit))

    def _objective_sample_axis_values(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, str]:
        axis_values: dict[str, str] = {}
        for key, value in unit.sample_context.items():
            value_text = str(value).strip()
            if not value_text:
                continue
            column_key = self._objective_column_key(str(key))
            if column_key in {
                "condition",
                "condition_no",
                "condition_number",
                "id",
                "label",
                "sample",
                "sample_id",
                "sample_label",
                "sample_no",
                "sample_number",
            }:
                continue
            axis_values[str(key).strip()] = value_text.casefold()
        return axis_values

    def _objective_process_axis_values(
        self,
        unit: ObjectiveEvidenceUnit,
        *,
        objective_context: ObjectiveContext | None,
    ) -> dict[str, str]:
        if objective_context is None or not objective_context.variable_process_axes:
            return {
                self._objective_column_key(key): str(value).strip().casefold()
                for key, value in unit.process_context.items()
                if str(value).strip()
            }
        axis_values: dict[str, str] = {}
        for axis in objective_context.variable_process_axes:
            axis_key = self._normalize_property_label(axis)
            if axis_key is None:
                continue
            for key, value in unit.process_context.items():
                if not str(value).strip():
                    continue
                if self._axis_values_match(
                    key,
                    axis,
                ) or self._axis_label_is_mentioned(key, axis):
                    axis_values[axis_key] = str(value).strip().casefold()
                    break
        return axis_values

    def _objective_raw_process_axis_values(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, str]:
        axis_values: dict[str, str] = {}
        for key, value in unit.process_context.items():
            if not str(key).strip() or not str(value).strip():
                continue
            if self._objective_column_key(str(key)):
                continue
            axis_key = self._axis_key(key) or str(key).strip().casefold()
            if axis_key:
                axis_values[axis_key] = str(value).strip().casefold()
        return axis_values

    def _objective_pairwise_comparison_unit(
        self,
        *,
        first: ObjectiveEvidenceUnit,
        second: ObjectiveEvidenceUnit,
        comparison_axis: str,
        objective_context: ObjectiveContext | None,
    ) -> ObjectiveEvidenceUnit:
        first_value = self._objective_measurement_numeric_value(first)
        second_value = self._objective_measurement_numeric_value(second)
        if first_value is None or second_value is None:
            raise ValueError("pairwise comparison requires numeric measurements")
        current, baseline = self._ordered_objective_comparison_pair(
            first=first,
            second=second,
            comparison_axis=comparison_axis,
            objective_context=objective_context,
        )
        current_value = self._objective_measurement_numeric_value(current)
        baseline_value = self._objective_measurement_numeric_value(baseline)
        if current_value is None or baseline_value is None:
            raise ValueError("pairwise comparison requires numeric measurements")
        controlled_axes = self._objective_comparison_controlled_axes(
            current=current,
            baseline=baseline,
            comparison_axis=comparison_axis,
            objective_context=objective_context,
        )
        seed = "|".join(
            (
                current.objective_id,
                current.document_id,
                str(current.property_normalized or ""),
                comparison_axis,
                current.evidence_unit_id,
                baseline.evidence_unit_id,
            )
        )
        return ObjectiveEvidenceUnit.from_mapping(
            {
                "evidence_unit_id": (
                    f"oeu_cmp_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"
                ),
                "objective_id": current.objective_id,
                "document_id": current.document_id,
                "unit_kind": "comparison",
                "property_normalized": current.property_normalized,
                "material_system": current.material_system or baseline.material_system,
                "sample_context": dict(current.sample_context),
                "process_context": dict(current.process_context),
                "test_condition": dict(current.test_condition),
                "value_payload": {
                    "value": current_value,
                    "current_value": current_value,
                    "source_value_text": current.value_payload.get(
                        "source_value_text"
                    ),
                    "direction": (
                        "increase"
                        if current_value > baseline_value
                        else "decrease"
                        if current_value < baseline_value
                        else "no_change"
                    ),
                    "comparison_axis": comparison_axis,
                    "controlled_axes": controlled_axes,
                    "current_evidence_unit_id": current.evidence_unit_id,
                    "baseline_evidence_unit_id": baseline.evidence_unit_id,
                },
                "unit": current.unit or baseline.unit,
                "baseline_context": {
                    "sample_context": dict(baseline.sample_context),
                    "process_context": dict(baseline.process_context),
                    "test_condition": dict(baseline.test_condition),
                    "value": baseline_value,
                    "source_value_text": baseline.value_payload.get(
                        "source_value_text"
                    ),
                    "evidence_unit_id": baseline.evidence_unit_id,
                },
                "source_refs": self._dedupe_chain_items(
                    [
                        *(dict(source_ref) for source_ref in current.source_refs),
                        *(dict(source_ref) for source_ref in baseline.source_refs),
                    ]
                ),
                "evidence_anchor_ids": self._dedupe_preserving_order(
                    [
                        *current.evidence_anchor_ids,
                        *baseline.evidence_anchor_ids,
                    ]
                ),
                "join_keys": {
                    "comparison_axis": comparison_axis,
                    "controlled_axes": controlled_axes,
                    "current_measurement_id": current.evidence_unit_id,
                    "baseline_measurement_id": baseline.evidence_unit_id,
                },
                "resolution_status": "resolved",
                "confidence": min(current.confidence, baseline.confidence),
            }
        )

    def _objective_comparison_controlled_axes(
        self,
        *,
        current: ObjectiveEvidenceUnit,
        baseline: ObjectiveEvidenceUnit,
        comparison_axis: str,
        objective_context: ObjectiveContext | None,
    ) -> list[dict[str, str]]:
        current_axes = self._objective_comparison_axis_value_map(
            current,
            objective_context=objective_context,
        )
        baseline_axes = self._objective_comparison_axis_value_map(
            baseline,
            objective_context=objective_context,
        )
        comparison_axis_key = (
            self._normalize_property_label(comparison_axis)
            or self._axis_key(comparison_axis)
        )
        controlled_axes: list[dict[str, str]] = []
        for axis_key, current_axis in sorted(current_axes.items()):
            if axis_key == comparison_axis_key:
                continue
            baseline_axis = baseline_axes.get(axis_key)
            if baseline_axis is None:
                continue
            if current_axis["value"] != baseline_axis["value"]:
                continue
            controlled_axes.append(
                {
                    "axis": current_axis["axis"],
                    "value": current_axis["value"],
                }
            )
        return controlled_axes

    def _objective_comparison_axis_value_map(
        self,
        unit: ObjectiveEvidenceUnit,
        *,
        objective_context: ObjectiveContext | None,
    ) -> dict[str, dict[str, str]]:
        axis_values: dict[str, dict[str, str]] = {}
        for source in (
            self._objective_process_axis_values(
                unit,
                objective_context=objective_context,
            ),
            self._objective_sample_axis_values(unit),
            self._objective_raw_process_axis_values(unit),
        ):
            for axis, value in source.items():
                axis_key = self._normalize_property_label(axis) or self._axis_key(axis)
                if not axis_key:
                    continue
                axis_values[axis_key] = {
                    "axis": axis,
                    "value": str(value).strip().casefold(),
                }
        return axis_values

    def _ordered_objective_comparison_pair(
        self,
        *,
        first: ObjectiveEvidenceUnit,
        second: ObjectiveEvidenceUnit,
        comparison_axis: str,
        objective_context: ObjectiveContext | None,
    ) -> tuple[ObjectiveEvidenceUnit, ObjectiveEvidenceUnit]:
        first_axis_value = self._objective_comparison_axis_value(
            first,
            comparison_axis=comparison_axis,
            objective_context=objective_context,
        )
        second_axis_value = self._objective_comparison_axis_value(
            second,
            comparison_axis=comparison_axis,
            objective_context=objective_context,
        )
        first_axis_number = self._coerce_number(first_axis_value)
        second_axis_number = self._coerce_number(second_axis_value)
        if (
            first_axis_number is not None
            and second_axis_number is not None
            and not math.isclose(first_axis_number, second_axis_number)
        ):
            return (
                (first, second)
                if first_axis_number > second_axis_number
                else (second, first)
            )

        first_value = self._objective_measurement_numeric_value(first)
        second_value = self._objective_measurement_numeric_value(second)
        if first_value is None or second_value is None:
            return first, second
        return (first, second) if first_value >= second_value else (second, first)

    def _objective_comparison_axis_value(
        self,
        unit: ObjectiveEvidenceUnit,
        *,
        comparison_axis: str,
        objective_context: ObjectiveContext | None,
    ) -> str | None:
        process_axis_values = self._objective_process_axis_values(
            unit,
            objective_context=objective_context,
        )
        comparison_axis_key = self._normalize_property_label(comparison_axis)
        if comparison_axis_key and comparison_axis_key in process_axis_values:
            return process_axis_values[comparison_axis_key]
        for key, value in unit.process_context.items():
            if self._axis_values_match(key, comparison_axis):
                return str(value).strip()

        sample_axis_values = self._objective_sample_axis_values(unit)
        if comparison_axis_key and comparison_axis_key in sample_axis_values:
            return sample_axis_values[comparison_axis_key]
        for key, value in unit.sample_context.items():
            if self._axis_values_match(key, comparison_axis):
                return str(value).strip()
        return None

    def _objective_comparison_pair_key(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> tuple[str, str, str, str, str, str]:
        baseline_context = unit.baseline_context
        baseline_sample_context = baseline_context.get("sample_context")
        if not isinstance(baseline_sample_context, dict):
            baseline_sample_context = {}
        comparison_axis = str(
            unit.value_payload.get("comparison_axis")
            or unit.value_payload.get("changed_process_axis")
            or ""
        )
        return (
            unit.objective_id,
            unit.document_id,
            str(unit.property_normalized or ""),
            self._objective_sample_identity_key(unit.sample_context),
            self._objective_sample_identity_key(baseline_sample_context),
            self._normalize_property_label(comparison_axis) or comparison_axis,
        )

    def _objective_sample_identity_key(
        self,
        sample_context: dict[str, Any],
    ) -> str:
        return "|".join(
            f"{self._objective_column_key(key)}={str(value).strip().casefold()}"
            for key, value in sorted(sample_context.items())
            if str(value).strip()
        )

    def _objective_sample_context_match_keys(
        self,
        sample_context: dict[str, Any],
    ) -> tuple[tuple[tuple[str, str], ...], ...]:
        items = tuple(
            sorted(
                (
                    column_key,
                    str(value).strip().casefold(),
                )
                for column, value in sample_context.items()
                if (column_key := self._objective_column_key(str(column)))
                in {
                    "condition",
                    "condition_no",
                    "condition_number",
                    "sample",
                    "sample_id",
                    "sample_no",
                    "sample_number",
                }
                and str(value).strip()
            )
        )
        if not items:
            return ()
        keys: list[tuple[tuple[str, str], ...]] = [items]
        if len(items) > 1:
            keys.extend((item,) for item in items)
        return tuple(keys)

    def _build_objective_route_source_payload(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        blocks: list[Any],
        tables: list[Any],
        table_cells: list[Any] | None = None,
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
            cells = tuple(
                cell
                for cell in table_cells or []
                if str(getattr(cell, "table_id", "") or "") == route.source_ref
            )
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
                "table_cells": [
                    {
                        "row_index": getattr(cell, "row_index", None),
                        "col_index": getattr(cell, "col_index", None),
                        "header_path": getattr(cell, "header_path", None),
                        "cell_text": str(getattr(cell, "cell_text", "") or ""),
                    }
                    for cell in sorted(
                        cells,
                        key=lambda item: (
                            getattr(item, "row_index", 0),
                            getattr(item, "col_index", 0),
                        ),
                    )
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

    def _objective_table_matrix_evidence_unit_records(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        source: dict[str, Any],
        objective_context: ObjectiveContext | None,
    ) -> tuple[dict[str, Any], ...]:
        if route.source_kind != "table":
            return ()
        headers, data_rows = self._objective_table_matrix_rows(source)
        if not headers or not data_rows:
            return ()
        if route.role == "current_experimental_evidence":
            return self._objective_result_table_matrix_records(
                route=route,
                source=source,
                objective_context=objective_context,
                headers=headers,
                data_rows=data_rows,
            )
        if route.role == "process_or_treatment":
            return self._objective_process_table_matrix_records(
                route=route,
                source=source,
                objective_context=objective_context,
                headers=headers,
                data_rows=data_rows,
            )
        return ()

    def _objective_table_matrix_rows(
        self,
        source: dict[str, Any],
    ) -> tuple[tuple[str, ...], tuple[tuple[int, tuple[str, ...]], ...]]:
        headers = tuple(
            str(header).strip()
            for header in source.get("column_headers", ())
            if str(header).strip()
        )
        matrix = tuple(
            tuple(str(cell).strip() for cell in row)
            for row in source.get("table_matrix", ())
            if isinstance(row, (list, tuple))
        )
        if not headers or not matrix:
            return (), ()
        candidate_rows = (
            matrix[1:]
            if self._objective_row_matches_headers(matrix[0], headers)
            else matrix
        )
        filtered_rows = tuple(
            row
            for row in candidate_rows
            if any(cell for cell in row)
            and not self._objective_table_matrix_continuation_header_row(
                headers=headers,
                row=row,
            )
        )
        data_rows = tuple(
            (row_index, row)
            for row_index, row in enumerate(filtered_rows, start=1)
        )
        return headers, data_rows

    def _objective_table_matrix_continuation_header_row(
        self,
        *,
        headers: tuple[str, ...],
        row: tuple[str, ...],
    ) -> bool:
        if not headers or not row:
            return False
        first_header_key = self._objective_column_key(headers[0])
        if first_header_key not in {"sample", "sample_id", "sample_number"}:
            return False
        first_cell = str(row[0] if row else "").strip()
        matches_header = self._objective_column_key(first_cell) == first_header_key
        continues_header = not first_cell and any(str(cell).strip() for cell in row[1:])
        return matches_header or continues_header

    def _objective_row_matches_headers(
        self,
        row: tuple[str, ...],
        headers: tuple[str, ...],
    ) -> bool:
        return tuple(self._objective_column_key(value) for value in row[: len(headers)]) == tuple(
            self._objective_column_key(value) for value in headers
        )

    def _objective_result_table_matrix_records(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        source: dict[str, Any],
        objective_context: ObjectiveContext | None,
        headers: tuple[str, ...],
        data_rows: tuple[tuple[int, tuple[str, ...]], ...],
    ) -> tuple[dict[str, Any], ...]:
        result_columns = self._objective_route_result_columns(
            route,
            objective_context=objective_context,
        )
        if not result_columns:
            return ()

        records: list[dict[str, Any]] = []
        for row_index, row in data_rows:
            row_values = self._objective_table_row_values(headers=headers, row=row)
            row_context = self._objective_table_row_context(
                route=route,
                row_values=row_values,
                result_columns=result_columns,
                objective_context=objective_context,
            )
            if self._objective_result_table_row_is_reference_context(
                route=route,
                row_values=row_values,
                result_columns=result_columns,
            ):
                continue
            row_context = self._objective_table_row_context_with_sample_number(
                row_context=row_context,
                row_index=row_index,
            )
            for result_column in result_columns:
                raw_value = row_values.get(result_column)
                if raw_value in (None, ""):
                    continue
                property_source = self._objective_result_column_property_label(
                    route=route,
                    result_column=result_column,
                    objective_context=objective_context,
                )
                _column_property, unit = self._split_property_unit(result_column)
                property_normalized = (
                    self._normalize_objective_unit_property(
                        property_source,
                        objective_context=objective_context,
                    )
                    or property_source
                )
                value_payload = {"source_value_text": str(raw_value)}
                numeric_value = self._coerce_result_cell_number(raw_value)
                if numeric_value is not None:
                    value_payload["value"] = numeric_value
                records.append(
                    {
                        "evidence_unit_id": self._objective_matrix_unit_id(
                            route=route,
                            row_index=row_index,
                            column=result_column,
                        ),
                        "objective_id": route.objective_id,
                        "document_id": route.document_id,
                        "unit_kind": "measurement",
                        "property_normalized": property_normalized,
                        "sample_context": row_context["sample_context"],
                        "process_context": row_context["process_context"],
                        "test_condition": row_context["test_condition"],
                        "value_payload": value_payload,
                        "unit": unit,
                        "source_refs": self._objective_route_source_refs(
                            route=route,
                            source=source,
                        ),
                        "join_keys": self._objective_table_join_keys(
                            route=route,
                            row_values=row_values,
                        ),
                        "resolution_status": "resolved",
                        "confidence": route.confidence,
                    }
                )
        return tuple(records)

    def _objective_process_table_matrix_records(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        source: dict[str, Any],
        objective_context: ObjectiveContext | None,
        headers: tuple[str, ...],
        data_rows: tuple[tuple[int, tuple[str, ...]], ...],
    ) -> tuple[dict[str, Any], ...]:
        result_columns = self._objective_route_result_columns(route)
        records: list[dict[str, Any]] = []
        for row_index, row in data_rows:
            row_values = self._objective_table_row_values(headers=headers, row=row)
            row_context = self._objective_table_row_context(
                route=route,
                row_values=row_values,
                result_columns=result_columns,
                objective_context=objective_context,
            )
            row_context = self._objective_table_row_context_with_sample_number(
                row_context=row_context,
                row_index=row_index,
            )
            if not row_context["process_context"] and not row_context["test_condition"]:
                continue
            records.append(
                {
                    "evidence_unit_id": self._objective_matrix_unit_id(
                        route=route,
                        row_index=row_index,
                        column="process_context",
                    ),
                    "objective_id": route.objective_id,
                    "document_id": route.document_id,
                    "unit_kind": "process_context",
                    "sample_context": row_context["sample_context"],
                    "process_context": row_context["process_context"],
                    "test_condition": row_context["test_condition"],
                    "source_refs": self._objective_route_source_refs(
                        route=route,
                        source=source,
                    ),
                    "join_keys": self._objective_table_join_keys(
                        route=route,
                        row_values=row_values,
                    ),
                    "resolution_status": "resolved",
                    "confidence": route.confidence,
                }
            )
        return tuple(records)

    def _objective_table_row_values(
        self,
        *,
        headers: tuple[str, ...],
        row: tuple[str, ...],
    ) -> dict[str, str]:
        return {
            header: row[index]
            for index, header in enumerate(headers)
            if index < len(row) and row[index] not in (None, "")
        }

    def _objective_table_row_context(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        row_values: dict[str, str],
        result_columns: set[str],
        objective_context: ObjectiveContext | None,
    ) -> dict[str, dict[str, str]]:
        sample_context: dict[str, str] = {}
        process_context: dict[str, str] = {}
        test_condition: dict[str, str] = {}
        for column, value in row_values.items():
            role = str(route.column_roles.get(column) or "").lower()
            column_key = self._objective_column_key(column)
            if "sample" in role or column_key in {
                "condition_number",
                "sample",
                "sample_number",
            }:
                sample_context[column] = value
            elif (
                column in result_columns
                or self._objective_value_column_is_non_result(column)
            ):
                continue
            elif (
                "test" in role
                or "condition" in role
                or column_key in {"test", "test_no", "test_number"}
            ):
                if route.role == "current_experimental_evidence":
                    sample_context[column] = value
                test_condition[column] = value
            elif self._objective_table_column_is_process_context(
                route=route,
                column=column,
                role=role,
                objective_context=objective_context,
            ):
                process_context[
                    self._objective_process_context_column_label(
                        column=column,
                        role=role,
                        objective_context=objective_context,
                    )
                ] = value
        return {
            "sample_context": sample_context,
            "process_context": process_context,
            "test_condition": test_condition,
        }

    def _objective_process_context_column_label(
        self,
        *,
        column: str,
        role: str,
        objective_context: ObjectiveContext | None,
    ) -> str:
        role_label = self._normalize_property_label(role)
        if (
            role_label
            and self._objective_process_role_is_specific(role_label)
            and (
                objective_context is None
                or self._objective_label_matches_process_axes(
                    role_label,
                    objective_context=objective_context,
                )
            )
        ):
            return role_label
        return column

    def _objective_process_role_is_specific(self, role_label: str) -> bool:
        role_tokens = self._axis_token_set(role_label)
        return bool(role_tokens) and not role_tokens.issubset(
            _OBJECTIVE_GENERIC_PROCESS_ROLE_TOKENS
        )

    def _objective_table_column_is_process_context(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        column: str,
        role: str,
        objective_context: ObjectiveContext | None,
    ) -> bool:
        role_text = str(role or "").strip()
        if "process" in role_text or "variable" in role_text:
            return True
        if objective_context is not None:
            for label in (column, role_text):
                if self._objective_label_matches_process_axes(
                    label,
                    objective_context=objective_context,
                ):
                    return True
        return route.role == "process_or_treatment"

    def _objective_label_matches_process_axes(
        self,
        label: Any,
        *,
        objective_context: ObjectiveContext,
    ) -> bool:
        label_text = str(label or "").strip()
        if not label_text:
            return False
        label_tokens = self._axis_token_set(self._axis_key(label_text))
        for axis in objective_context.variable_process_axes:
            axis_text = str(axis or "").strip()
            if not axis_text:
                continue
            if (
                self._axis_values_match(label_text, axis_text)
                or self._axis_label_is_mentioned(label_text, axis_text)
                or self._axis_label_is_mentioned(axis_text, label_text)
            ):
                return True
            axis_tokens = self._axis_token_set(self._axis_key(axis_text))
            if len(label_tokens & axis_tokens) >= 2:
                return True
        return False

    def _objective_result_table_row_is_reference_context(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        row_values: dict[str, str],
        result_columns: set[str],
    ) -> bool:
        if route.role != "current_experimental_evidence":
            return False
        context_values = tuple(
            str(value).strip()
            for column, value in row_values.items()
            if column not in result_columns
            and not self._objective_value_column_is_non_result(column)
            and str(value).strip()
        )
        if not context_values:
            return False
        context_text = " ".join(context_values)
        if re.search(r"\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\]", context_text):
            return True
        normalized = context_text.casefold()
        return any(
            marker in normalized
            for marker in (
                "literature",
                "previous study",
                "previous work",
                "reference material",
                "reference sample",
            )
        )

    def _objective_table_row_context_with_sample_number(
        self,
        *,
        row_context: dict[str, dict[str, str]],
        row_index: int,
    ) -> dict[str, dict[str, str]]:
        sample_context = dict(row_context["sample_context"])
        if self._objective_sample_context_has_explicit_number(sample_context):
            return row_context
        if sample_context and not self._objective_sample_context_needs_row_number(
            sample_context
        ) and self._objective_sample_context_has_stable_label(sample_context):
            return row_context
        if not sample_context and not (
            row_context["process_context"] or row_context["test_condition"]
        ):
            return row_context
        sample_context["sample_number"] = str(row_index)
        return {
            "sample_context": sample_context,
            "process_context": row_context["process_context"],
            "test_condition": row_context["test_condition"],
        }

    def _objective_sample_context_has_explicit_number(
        self,
        sample_context: dict[str, Any],
    ) -> bool:
        for key, value in sample_context.items():
            text = str(value).strip()
            if not text:
                continue
            column_key = self._objective_column_key(str(key))
            if column_key in {
                "condition",
                "condition_no",
                "condition_number",
                "sample_no",
                "sample_number",
            }:
                return True
            if column_key in {"sample", "sample_id"} and (
                re.fullmatch(r"0*\d+", text)
                or re.search(r"\bS0*\d+\b", text, flags=re.IGNORECASE)
                or re.search(r"\bsample\s*#?\s*0*\d+\b", text, flags=re.IGNORECASE)
            ):
                return True
        return False

    def _objective_sample_context_needs_row_number(
        self,
        sample_context: dict[str, Any],
    ) -> bool:
        for value in sample_context.values():
            tokens = [
                token
                for token in self._objective_numeric_match_tokens(value)
                if token not in {"1", "-1"}
            ]
            if len(set(tokens)) >= 2:
                return True
        return False

    def _objective_sample_context_has_stable_label(
        self,
        sample_context: dict[str, Any],
    ) -> bool:
        for key in sample_context:
            column_key = self._objective_column_key(str(key))
            if column_key in {"id", "label", "sample", "sample_id", "sample_label"}:
                return True
            if "sample" in column_key and "condition" not in column_key:
                return True
        return False

    def _objective_table_join_keys(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        row_values: dict[str, str],
    ) -> dict[str, Any]:
        if route.join_keys:
            return dict(route.join_keys)
        join_keys = {
            self._objective_column_key(column): value
            for column, value in row_values.items()
            if self._objective_column_key(column)
            in {"condition_number", "sample", "sample_number"}
        }
        return join_keys

    def _objective_matrix_unit_id(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        row_index: int,
        column: str,
    ) -> str:
        seed = "|".join((route.route_id, str(row_index), column))
        return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"

    def _objective_evidence_unit_records_from_extracted(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        source: dict[str, Any],
        objective_context: ObjectiveContext | None,
        extracted_record: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        record = dict(extracted_record)
        record["property_normalized"] = self._normalize_objective_unit_property(
            record.get("property_normalized"),
            objective_context=objective_context,
        )
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
        text_measurement_records = (
            self._numeric_text_characterization_measurement_records(
                record,
                source_text=str(source.get("text") or ""),
            )
        )
        if text_measurement_records:
            return text_measurement_records
        record = self._normalize_text_evidence_unit_record(
            route=route,
            record=record,
        )
        if (
            route.source_kind == "text_window"
            and record.get("unit_kind") == "measurement"
            and not self._objective_text_measurement_matches_context(
                record.get("property_normalized"),
                objective_context=objective_context,
            )
        ):
            normalized = dict(record)
            normalized["unit_kind"] = (
                "characterization"
                if self._objective_text_numeric_mechanism_property(
                    record.get("property_normalized")
                )
                else "interpretation"
            )
            return (normalized,)
        if route.source_kind == "text_window" and record.get("unit_kind") != "measurement":
            return (record,)

        if route.role != "current_experimental_evidence":
            return (record,)

        value_payload = (
            record.get("value_payload")
            if isinstance(record.get("value_payload"), dict)
            else {}
        )
        result_items = self._objective_result_value_items(
            route=route,
            objective_context=objective_context,
            value_payload=value_payload,
        )
        if not result_items:
            return (record,)

        normalized_records: list[dict[str, Any]] = []
        for property_name, raw_value in result_items:
            property_normalized, unit = self._split_property_unit(property_name)
            property_normalized = (
                self._normalize_objective_unit_property(
                    property_normalized,
                    objective_context=objective_context,
                )
                or property_normalized
            )
            value_record = {
                "source_value_text": str(raw_value),
            }
            numeric_value = self._coerce_number(raw_value)
            if numeric_value is not None:
                value_record["value"] = numeric_value
            normalized = dict(record)
            normalized.update(
                {
                    "unit_kind": "measurement",
                    "property_normalized": (
                        record.get("property_normalized") or property_normalized
                    ),
                    "value_payload": value_record,
                    "unit": record.get("unit") or unit,
                    "resolution_status": (
                        "resolved"
                        if record.get("sample_context")
                        else record.get("resolution_status")
                    ),
                }
            )
            normalized_records.append(normalized)
        return tuple(normalized_records)

    def _normalize_text_evidence_unit_record(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        if route.source_kind != "text_window":
            return record
        if record.get("unit_kind") == "comparison":
            value_payload = (
                record.get("value_payload")
                if isinstance(record.get("value_payload"), dict)
                else {}
            )
            baseline_context = (
                record.get("baseline_context")
                if isinstance(record.get("baseline_context"), dict)
                else {}
            )
            if not value_payload and not baseline_context:
                normalized = dict(record)
                if route.role == "characterization":
                    normalized["unit_kind"] = "characterization"
                else:
                    normalized["unit_kind"] = "interpretation"
                return normalized
        if record.get("unit_kind") == "characterization":
            normalized = self._numeric_text_characterization_measurement_record(
                record,
            )
            if normalized is not None:
                return normalized
        if record.get("unit_kind") != "measurement":
            return record
        value_payload = (
            record.get("value_payload")
            if isinstance(record.get("value_payload"), dict)
            else {}
        )
        if self._text_measurement_has_explicit_numeric_value(value_payload):
            return record
        normalized = dict(record)
        if route.role == "characterization" and self._objective_property_is_characterization(
            record.get("property_normalized")
        ):
            normalized["unit_kind"] = "characterization"
        else:
            normalized["unit_kind"] = "interpretation"
        if not normalized.get("interpretation"):
            normalized["interpretation"] = self._value_payload_text(value_payload)
        return normalized

    def _text_measurement_has_explicit_numeric_value(
        self,
        value_payload: dict[str, Any],
    ) -> bool:
        for key in ("value", "numeric_value", "normalized_value", "current_value"):
            value = value_payload.get(key)
            if value in (None, "", [], {}):
                continue
            if self._coerce_number(value) is not None:
                return True
        source_value = value_payload.get("source_value_text")
        return self._source_value_text_is_atomic_numeric(source_value)

    def _source_value_text_is_atomic_numeric(self, value: Any) -> bool:
        if value in (None, "", [], {}) or isinstance(value, (dict, list, tuple, set)):
            return False
        text = str(value).strip()
        if not text:
            return False
        unit_pattern = r"(?:%|MPa|GPa|HV|mV|V|A/cm2|uA/cm2|µA/cm2|C/s|°C/s|deg\s*C/s)"
        return bool(
            re.fullmatch(
                rf"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*(?:{unit_pattern})?",
                text,
                flags=re.IGNORECASE,
            )
            or re.fullmatch(
                rf"[-+]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:x|×)\s*10\s*\^?\s*[-+]?\d+\s*(?:{unit_pattern})?",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _objective_text_measurement_matches_context(
        self,
        property_name: Any,
        *,
        objective_context: ObjectiveContext | None,
    ) -> bool:
        if objective_context is None or not objective_context.target_property_axes:
            return True
        property_key = self._normalize_property_label(property_name)
        if not property_key:
            return True
        target_axes = self._objective_target_property_axes(objective_context)
        if self._objective_property_label_matches_target(
            property_key,
            target_axes=target_axes,
        ):
            return True
        if property_key in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
            return any(
                self._property_axis_matches_any(axis, _STRUCTURAL_PROPERTY_AXES)
                or self._property_axis_matches_any(axis, _MECHANICAL_PROPERTY_AXES)
                for axis in target_axes
            )
        return False

    def _objective_text_numeric_mechanism_property(self, property_name: Any) -> bool:
        property_key = self._normalize_property_label(property_name)
        if not property_key:
            return False
        property_tokens = self._axis_token_set(property_key)
        if not property_tokens:
            return False
        return any(
            mechanism_tokens.issubset(property_tokens)
            for mechanism_tokens in (
                {"cool", "rate"},
                {"thermal", "gradient"},
                {"melt", "pool"},
                {"width", "depth"},
                self._axis_token_set("residual stress"),
                {"recrystallization"},
            )
        )

    def _numeric_text_characterization_measurement_record(
        self,
        record: dict[str, Any],
    ) -> dict[str, Any] | None:
        records = self._numeric_text_characterization_measurement_records(record)
        if len(records) == 1:
            return records[0]
        return None

    def _numeric_text_characterization_measurement_records(
        self,
        record: dict[str, Any],
        *,
        source_text: str = "",
    ) -> tuple[dict[str, Any], ...]:
        if record.get("unit_kind") != "characterization":
            return ()
        respective_items = self._respective_density_measurement_items(record)
        respective_record = record
        if not respective_items:
            respective_items = self._source_text_respective_density_measurement_items(
                source_text
            )
            if respective_items:
                respective_record = dict(record)
                respective_record["evidence_unit_id"] = (
                    self._source_text_density_record_base_id(record)
                )
                respective_record["process_context"] = {}
        if respective_items:
            return tuple(
                self._numeric_text_characterization_measurement_record_from_value(
                    record=respective_record,
                    property_normalized="relative density",
                    raw_value=raw_value,
                    sample_context={"sample_id": sample_label},
                    unit="%",
                    item_index=index,
                )
                for index, (sample_label, raw_value) in enumerate(respective_items, start=1)
            )
        value_payload = (
            record.get("value_payload")
            if isinstance(record.get("value_payload"), dict)
            else {}
        )
        record_property_normalized = self._normalize_property_label(
            record.get("property_normalized"),
        )
        mapped_numeric_items = self._mapped_text_numeric_measurement_items(
            value_payload
        )
        if record_property_normalized and mapped_numeric_items:
            return tuple(
                self._numeric_text_characterization_measurement_record_from_value(
                    record=record,
                    property_normalized=record_property_normalized,
                    raw_value=sample_value,
                    sample_context={"sample_id": sample_label},
                    unit=self._unit_from_value_text(sample_value),
                    item_index=index,
                )
                for index, (sample_label, sample_value) in enumerate(
                    mapped_numeric_items,
                    start=1,
                )
            )
        value_item = self._numeric_text_characterization_value_item(
            record=record,
            value_payload=value_payload,
        )
        if value_item is None:
            return ()
        property_normalized, raw_value = value_item
        mapped_density_items = self._mapped_density_measurement_items(raw_value)
        if (
            property_normalized in {"relative density", "density"}
            and mapped_density_items
        ):
            return tuple(
                self._numeric_text_characterization_measurement_record_from_value(
                    record=record,
                    property_normalized=property_normalized,
                    raw_value=sample_value,
                    sample_context={"sample_id": sample_label},
                    item_index=index,
                )
                for index, (sample_label, sample_value) in enumerate(
                    mapped_density_items,
                    start=1,
                )
            )
        numeric_value = self._coerce_number(raw_value)
        if numeric_value is None:
            return ()
        return (
            self._numeric_text_characterization_measurement_record_from_value(
                record=record,
                property_normalized=property_normalized,
                raw_value=raw_value,
            ),
        )

    def _mapped_density_measurement_items(
        self,
        raw_value: Any,
    ) -> tuple[tuple[str, Any], ...]:
        if not isinstance(raw_value, dict):
            return ()
        items: list[tuple[str, Any]] = []
        for sample_label, sample_value in raw_value.items():
            label_text = str(sample_label).strip()
            if not label_text or self._coerce_number(sample_value) is None:
                continue
            items.append((label_text, sample_value))
        if len(items) < 2:
            return ()
        return tuple(items)

    def _mapped_text_numeric_measurement_items(
        self,
        value_payload: dict[str, Any],
    ) -> tuple[tuple[str, Any], ...]:
        items: list[tuple[str, Any]] = []
        for sample_label, sample_value in value_payload.items():
            label_text = str(sample_label).strip()
            if (
                not label_text
                or sample_value in (None, "", [], {})
                or label_text.lower() in _OBJECTIVE_RESULT_VALUE_METADATA_KEYS
            ):
                continue
            if self._coerce_number(sample_value) is None:
                continue
            items.append((label_text, sample_value))
        if len(items) < 2:
            return ()
        return tuple(items)

    def _numeric_text_characterization_measurement_record_from_value(
        self,
        *,
        record: dict[str, Any],
        property_normalized: str,
        raw_value: Any,
        sample_context: dict[str, Any] | None = None,
        unit: str | None = None,
        item_index: int | None = None,
    ) -> dict[str, Any]:
        numeric_value = self._coerce_number(raw_value)
        resolved_unit = unit or str(record.get("unit") or "").strip() or None
        if resolved_unit is None and "%" in str(raw_value):
            resolved_unit = "%"
        if resolved_unit is None:
            resolved_unit = self._unit_from_value_text(raw_value)
        normalized = dict(record)
        if item_index is not None:
            seed = "|".join(
                (
                    str(record.get("evidence_unit_id") or ""),
                    str(item_index),
                    str(sample_context or {}),
                    str(raw_value),
                )
            )
            normalized["evidence_unit_id"] = (
                f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"
            )
        if sample_context is not None:
            normalized["sample_context"] = dict(sample_context)
        normalized.update(
            {
                "unit_kind": "measurement",
                "property_normalized": property_normalized,
                "value_payload": {
                    "source_value_text": str(raw_value),
                    "value": numeric_value,
                },
                "unit": resolved_unit,
            }
        )
        return normalized

    def _unit_from_value_text(self, value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if "%" in text:
            return "%"
        if re.search(r"\bMPa\b", text, flags=re.IGNORECASE):
            return "MPa"
        if re.search(r"(?:deg\s*)?C\s*/\s*s", text, flags=re.IGNORECASE):
            return "C/s"
        return None

    def _respective_density_measurement_items(
        self,
        record: dict[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        sample_labels = self._objective_text_sample_labels(record.get("sample_context"))
        if not sample_labels:
            return ()
        value_payload = (
            record.get("value_payload")
            if isinstance(record.get("value_payload"), dict)
            else {}
        )
        text = self._value_payload_text(value_payload) or ""
        if "density" not in text.casefold() or "respectively" not in text.casefold():
            return ()
        match = re.search(
            r"\b(?:was|were|is|are)\s+"
            r"([0-9][0-9.,\s]*(?:and\s*)?[0-9.]+)\s*%?\s*,?\s*respectively",
            text,
            flags=re.IGNORECASE,
        )
        if match is None:
            return ()
        value_text = match.group(1)
        values = tuple(
            value_match.group(0)
            for value_match in _NUMBER_PATTERN.finditer(value_text)
        )
        if len(values) != len(sample_labels):
            return ()
        return tuple(zip(sample_labels, values))

    def _source_text_respective_density_measurement_items(
        self,
        source_text: str,
    ) -> tuple[tuple[str, str], ...]:
        text = " ".join(str(source_text or "").split())
        if "density" not in text.casefold() or "respectively" not in text.casefold():
            return ()
        sample_match = re.search(
            r"\bdensity\s+of\s+(?:the\s+)?(?:\w+\s+)?samples?\s+of\s+(.+?)\s+"
            r"(?:was|were)\s+measured\b",
            text,
            flags=re.IGNORECASE,
        )
        if sample_match is None:
            return ()
        value_match = re.search(
            r"\b(?:which\s+)?(?:was|were|is|are)\s+"
            r"([0-9][0-9.,\s]*(?:and\s*)?[0-9.]+)\s*%?\s*,?\s*respectively",
            text,
            flags=re.IGNORECASE,
        )
        if value_match is None:
            return ()
        sample_labels = self._split_respective_density_sample_labels(
            sample_match.group(1)
        )
        values = tuple(
            item.group(0)
            for item in _NUMBER_PATTERN.finditer(value_match.group(1))
        )
        if len(sample_labels) < 2 or len(values) != len(sample_labels):
            return ()
        return tuple(zip(sample_labels, values))

    def _split_respective_density_sample_labels(
        self,
        sample_text: str,
    ) -> tuple[str, ...]:
        normalized = " ".join(str(sample_text or "").split()).strip(" ,")
        if not normalized:
            return ()
        normalized = re.sub(r",?\s+and\s+", ", ", normalized, flags=re.IGNORECASE)
        return tuple(
            label.strip(" ,")
            for label in normalized.split(",")
            if label.strip(" ,")
        )

    def _source_text_density_record_base_id(
        self,
        record: dict[str, Any],
    ) -> str:
        source_refs = record.get("source_refs") or []
        source_key = json.dumps(source_refs, ensure_ascii=False, sort_keys=True)
        seed = "|".join(
            (
                str(record.get("objective_id") or ""),
                str(record.get("document_id") or ""),
                source_key,
                "source-text-density",
            )
        )
        return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"

    def _objective_text_sample_labels(self, sample_context: Any) -> tuple[str, ...]:
        if not isinstance(sample_context, dict):
            return ()
        for key in ("sample_ids", "samples", "sample_labels"):
            value = sample_context.get(key)
            if isinstance(value, (list, tuple)):
                labels = tuple(str(item).strip() for item in value if str(item).strip())
                if labels:
                    return labels
        return ()

    def _numeric_text_characterization_value_item(
        self,
        *,
        record: dict[str, Any],
        value_payload: dict[str, Any],
    ) -> tuple[str, Any] | None:
        property_normalized = self._normalize_property_label(
            record.get("property_normalized"),
        )
        if property_normalized in {"relative density", "density"}:
            for key in ("value", "source_value_text", "result"):
                value = value_payload.get(key)
                if value not in (None, "", [], {}):
                    return property_normalized, value
        for key, value in value_payload.items():
            if value in (None, "", [], {}):
                continue
            key_normalized = self._objective_column_key(str(key))
            if key_normalized not in {
                "density",
                "density_value",
                "density_percent",
                "relative_density",
                "relative_density_value",
                "relative_density_percent",
            }:
                continue
            if (
                key_normalized.startswith("relative_")
                or str(record.get("unit") or "").strip() == "%"
                or "%" in str(value)
            ):
                return "relative density", value
            return "density", value
        return None

    def _objective_result_value_items(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        objective_context: ObjectiveContext | None,
        value_payload: dict[str, Any],
    ) -> tuple[tuple[str, Any], ...]:
        if not value_payload:
            return ()
        result_columns = self._objective_route_result_columns(
            route,
            objective_context=objective_context,
        )
        result_column_by_key = {
            self._objective_column_key(column): column
            for column in result_columns
        }
        items: list[tuple[str, Any]] = []
        for key, value in value_payload.items():
            if value in (None, "", [], {}):
                continue
            key_text = str(key or "").strip()
            if (
                not key_text
                or key_text.lower() in _OBJECTIVE_RESULT_VALUE_METADATA_KEYS
                or self._objective_value_column_is_non_result(key_text)
            ):
                continue
            if result_columns:
                result_column = result_column_by_key.get(
                    self._objective_column_key(key_text),
                )
                if result_column is None:
                    continue
            else:
                result_column = key_text
            items.append((result_column, value))
        return tuple(items)

    def _objective_route_result_columns(
        self,
        route: ObjectiveEvidenceRoute,
        *,
        objective_context: ObjectiveContext | None = None,
    ) -> set[str]:
        result_columns: set[str] = set()
        for column, role in route.column_roles.items():
            column_text = str(column)
            if self._objective_value_column_is_non_result(column_text):
                continue
            role_text = str(role or "").strip().lower()
            if any(
                token in role_text
                for token in ("result", "target", "measurement", "property")
            ):
                if self._objective_result_column_matches_target(
                    column_text,
                    objective_context=objective_context,
                ):
                    result_columns.add(column_text)
                continue
            if (
                route.role == "current_experimental_evidence"
                and objective_context is not None
                and self._objective_column_key(role_text)
                == "current_experimental_evidence"
                and self._objective_result_column_is_specific_metric(column_text)
            ):
                result_columns.add(column_text)
                continue
            if (
                route.role == "current_experimental_evidence"
                and objective_context is not None
                and self._objective_header_matches_any_axis(
                    column_text,
                    objective_context.target_property_axes,
                )
            ):
                result_columns.add(column_text)
                continue
            if (
                route.role == "current_experimental_evidence"
                and objective_context is not None
                and self._objective_column_key(column_text) == "relative_density"
                and any(
                    axis in {"densification", "microstructure"}
                    for axis in objective_context.target_property_axes
                )
            ):
                result_columns.add(column_text)
                continue
            role_label = self._normalize_property_label(role_text)
            if (
                route.role == "current_experimental_evidence"
                and objective_context is not None
                and role_label
                and self._objective_property_label_matches_target(
                    role_label,
                    target_axes=self._objective_target_property_axes(
                        objective_context
                    ),
                )
            ):
                result_columns.add(column_text)
        return result_columns

    def _objective_result_column_property_label(
        self,
        *,
        route: ObjectiveEvidenceRoute,
        result_column: str,
        objective_context: ObjectiveContext | None,
    ) -> str:
        role_label = self._normalize_property_label(
            route.column_roles.get(result_column)
        )
        if (
            role_label
            and objective_context is not None
            and self._objective_result_role_is_specific_property(role_label)
            and self._objective_property_label_matches_target(
                role_label,
                target_axes=self._objective_target_property_axes(objective_context),
            )
        ):
            return role_label
        property_name, _unit = self._split_property_unit(result_column)
        return (
            self._normalize_property_label(property_name)
            or str(property_name or result_column).strip()
        )

    def _objective_result_role_is_specific_property(self, role_label: str) -> bool:
        role_tokens = self._axis_token_set(role_label)
        if not role_tokens:
            return False
        return not role_tokens.issubset(_OBJECTIVE_GENERIC_RESULT_ROLE_TOKENS)

    def _objective_result_column_is_specific_metric(self, column_text: str) -> bool:
        property_name, _unit = self._split_property_unit(column_text)
        tokens = self._axis_token_set(property_name)
        if not tokens:
            return False
        return bool(tokens & {"coefficient", "distance", "index", "score"})

    def _objective_result_column_matches_target(
        self,
        column_text: str,
        *,
        objective_context: ObjectiveContext | None,
    ) -> bool:
        if objective_context is None or not objective_context.target_property_axes:
            return True
        property_name, _unit = self._split_property_unit(column_text)
        normalized = self._normalize_property_label(property_name) or property_name
        target_axes = self._objective_target_property_axes(objective_context)
        if self._objective_property_label_matches_target(
            normalized,
            target_axes=target_axes,
        ):
            return True
        if self._objective_density_property_matches_structural_target(
            normalized,
            target_axes=target_axes,
        ):
            return True
        return any(
            self._axis_label_is_mentioned(normalized, axis)
            or self._axis_label_is_mentioned(column_text, axis)
            for axis in target_axes
        )

    def _objective_density_property_matches_structural_target(
        self,
        property_name: str,
        *,
        target_axes: tuple[str, ...],
    ) -> bool:
        if property_name not in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
            return False
        return any(
            axis in _STRUCTURAL_PROPERTY_AXES
            for axis in (
                self._normalize_property_label(target_axis)
                for target_axis in target_axes
            )
        )

    def _objective_property_label_matches_target(
        self,
        property_name: Any,
        *,
        target_axes: tuple[str, ...],
    ) -> bool:
        normalized = self._normalize_property_label(property_name)
        if not normalized:
            return False
        if self._property_axis_matches_any(normalized, target_axes):
            return True
        return self._objective_contextual_property_variant_match(
            normalized,
            target_axes=target_axes,
        ) is not None

    def _objective_contextual_property_variant_match(
        self,
        property_name: str,
        *,
        target_axes: tuple[str, ...],
    ) -> tuple[str, set[str]] | None:
        property_tokens = self._axis_token_set(self._axis_key(property_name))
        if not property_tokens:
            return None
        for target_axis in target_axes:
            target_key = self._normalize_property_label(target_axis)
            if not target_key:
                continue
            target_tokens = self._axis_token_set(self._axis_key(target_key))
            if (
                not target_tokens
                or target_tokens == property_tokens
                or not target_tokens.issubset(property_tokens)
            ):
                continue
            extra_tokens = property_tokens - target_tokens
            if len(target_tokens) >= 2:
                return target_key, extra_tokens
            if target_tokens == {"density"}:
                if extra_tokens.issubset({"material", "relative"}):
                    return target_key, extra_tokens
                continue
            if extra_tokens and extra_tokens.issubset(
                _OBJECTIVE_SINGLE_TOKEN_PROPERTY_QUALIFIERS
            ):
                return target_key, extra_tokens
        return None

    def _objective_target_property_axes(
        self,
        objective_context: ObjectiveContext,
    ) -> tuple[str, ...]:
        axes: list[str] = []
        seen: set[str] = set()
        for axis in objective_context.target_property_axes:
            normalized = self._normalize_property_label(axis)
            if normalized:
                self._append_unique_axis(axes, seen, normalized)
                for expanded in _BROAD_PROPERTY_AXIS_EXPANSIONS.get(normalized, ()):
                    self._append_unique_axis(axes, seen, expanded)
            else:
                self._append_unique_axis(axes, seen, axis)
        return tuple(axes)

    def _objective_value_column_is_non_result(self, value: str) -> bool:
        text = " ".join(
            str(value or "").lower().replace("_", " ").replace("-", " ").split()
        )
        if not text:
            return True
        return any(term in text for term in _OBJECTIVE_NON_RESULT_VALUE_COLUMN_TERMS)

    def _objective_value_column_is_statistical(self, value: str) -> bool:
        text = " ".join(
            str(value or "").lower().replace("_", " ").replace("-", " ").split()
        )
        return any(
            term in text
            for term in ("standard deviation", "std", "sd", "variance", "error bar")
        )

    def _objective_column_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")

    def _split_property_unit(self, value: str) -> tuple[str, str | None]:
        text = str(value or "").strip()
        text = re.sub(r"\s*>\s*(?=[\[(])", " ", text).strip()
        if text.endswith("]") and "[" in text:
            name, _, suffix = text.rpartition("[")
            unit = suffix[:-1].strip()
            return name.strip() or text, unit or None
        if text.endswith(")") and "(" in text:
            name, _, suffix = text.rpartition("(")
            unit = suffix[:-1].strip()
            return name.strip() or text, unit or None
        return text, None

    def _normalize_objective_unit_property(
        self,
        value: Any,
        *,
        objective_context: ObjectiveContext | None,
    ) -> str | None:
        normalized = self._normalize_property_label(value)
        if not normalized:
            return None
        if objective_context is None:
            return normalized
        for target_axis in objective_context.target_property_axes:
            if self._axis_values_match(normalized, target_axis):
                return self._normalize_property_label(target_axis)
        variant_match = self._objective_contextual_property_variant_match(
            normalized,
            target_axes=self._objective_target_property_axes(objective_context),
        )
        if variant_match is not None:
            target_axis, extra_tokens = variant_match
            if extra_tokens & _OBJECTIVE_PRESERVED_PROPERTY_QUALIFIERS:
                return normalized
            return self._normalize_property_label(target_axis) or normalized
        return normalized

    def _normalize_property_label(self, value: Any) -> str | None:
        text = self._label_without_unit_suffix(value)
        text = text.replace("_", " ").replace("-", " ").strip()
        normalized = " ".join(text.split()).casefold()
        if not normalized:
            return None
        return _OBJECTIVE_PROPERTY_ALIASES.get(normalized, normalized)

    def _label_without_unit_suffix(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s*>\s*(?=[\[(])", " ", text).strip()
        text = re.sub(r"\s*(?:\[[^\]]*\]|\([^)]*\))\s*$", "", text).strip()
        return text

    def _coerce_number(self, value: Any) -> float | None:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        scientific_match = re.search(
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:[xX\u00d7]\s*10)\s*\^?\s*([-+]?\d+)",
            text,
        )
        if scientific_match is not None:
            return float(scientific_match.group(1)) * (10 ** int(scientific_match.group(2)))
        match = _NUMBER_PATTERN.search(text)
        if match is None:
            return None
        return float(match.group(0))

    def _coerce_result_cell_number(self, value: Any) -> float | None:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        matches = list(_NUMBER_PATTERN.finditer(text))
        if len(matches) >= 2:
            leading_prefix = text[: matches[0].start()]
            between_first_and_second = text[matches[0].end() : matches[1].start()]
            if "(" in leading_prefix and ")" in between_first_and_second:
                return float(matches[1].group(0))
        return self._coerce_number(text)

    def _value_payload_numeric_value(
        self,
        value_payload: dict[str, Any],
    ) -> float | None:
        value = value_payload.get("value")
        if isinstance(value, (int, float)):
            return float(value)
        if value not in (None, ""):
            return self._coerce_number(value)
        return self._coerce_number(value_payload.get("source_value_text"))

    def _value_payload_text(
        self,
        value_payload: dict[str, Any],
    ) -> str | None:
        for key in ("statement", "summary", "source_value_text", "result", "value"):
            value = value_payload.get(key)
            if value not in (None, "", [], {}):
                return str(value)
        if value_payload:
            return json.dumps(value_payload, ensure_ascii=False, sort_keys=True)
        return None

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
        if unit.unit_kind in {
            "characterization",
            "comparison",
            "interpretation",
            "measurement",
        }:
            return bool(
                unit.value_payload
                or unit.baseline_context
                or unit.interpretation
            )
        return any(
            (
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
        progress_callback: ProgressCallback | None = None,
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
        objective_count = len(objectives)
        for objective_position, objective in enumerate(objectives, start=1):
            self._notify_progress(
                progress_callback,
                phase="objective_logic_chains_started",
                current=objective_position,
                total=objective_count,
                unit="objectives",
                message="Assembling objective logic chains from extracted evidence.",
                active_objective_id=objective.objective_id,
            )
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
                "measurement_value_ranges": cross_paper.get(
                    "measurement_value_ranges",
                    [],
                ),
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
        measurement_value_ranges = self._objective_measurement_value_ranges(
            measurements
        )
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
            "measurement_range_ready": bool(measurement_value_ranges),
            "measurement_value_ranges": measurement_value_ranges,
            "gaps": gaps,
        }

    def _objective_measurement_value_ranges(
        self,
        measurements: tuple[ObjectiveEvidenceUnit, ...],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[ObjectiveEvidenceUnit]] = {}
        for unit in measurements:
            if self._objective_measurement_numeric_value(unit) is None:
                continue
            grouped.setdefault(unit.property_normalized or "measurement", []).append(
                unit
            )

        ranges: list[dict[str, Any]] = []
        for property_name, property_units in grouped.items():
            sorted_units = sorted(
                property_units,
                key=lambda unit: (
                    self._objective_measurement_numeric_value(unit) or 0.0,
                    unit.evidence_unit_id,
                ),
            )
            min_unit = sorted_units[0]
            max_unit = sorted_units[-1]
            ranges.append(
                {
                    "property_normalized": property_name,
                    "measurement_count": len(property_units),
                    "min": self._objective_measurement_range_point(min_unit),
                    "max": self._objective_measurement_range_point(max_unit),
                    "unit": min_unit.unit or max_unit.unit,
                }
            )
        return ranges

    def _objective_measurement_numeric_value(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> float | None:
        for key in ("value", "numeric_value", "normalized_value", "current_value"):
            value = unit.value_payload.get(key)
            if value in (None, "", [], {}):
                continue
            numeric_value = self._coerce_number(value)
            if numeric_value is not None:
                return numeric_value
        source_value = unit.value_payload.get("source_value_text")
        if self._source_value_text_is_atomic_numeric(source_value):
            return self._coerce_number(source_value)
        return None

    def _objective_measurement_range_point(
        self,
        unit: ObjectiveEvidenceUnit,
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "evidence_unit_id": unit.evidence_unit_id,
                "value": self._objective_measurement_numeric_value(unit),
                "source_value_text": unit.value_payload.get("source_value_text"),
                "sample_context": dict(unit.sample_context),
                "process_context": dict(unit.process_context),
                "test_condition": dict(unit.test_condition),
                "source_refs": [dict(source_ref) for source_ref in unit.source_refs],
            }.items()
            if value not in (None, "", [], {})
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
        cross_paper = chain_payload.get("cross_paper", {})
        value_ranges = (
            cross_paper.get("measurement_value_ranges", [])
            if isinstance(cross_paper, dict)
            else []
        )
        range_summary = self._objective_logic_chain_range_summary(value_ranges)
        if range_summary:
            return (
                f"{question or 'Objective'}: {measurement_count} measurement "
                f"unit(s) across {document_count} document(s); {range_summary}."
            )
        return (
            f"{question or 'Objective'}: assembled {measurement_count} "
            f"measurement unit(s) across {document_count} document(s)."
        )

    def _objective_logic_chain_range_summary(
        self,
        value_ranges: Any,
    ) -> str:
        if not isinstance(value_ranges, list):
            return ""
        pieces: list[str] = []
        for value_range in value_ranges[:5]:
            if not isinstance(value_range, dict):
                continue
            property_name = str(value_range.get("property_normalized") or "").strip()
            min_point = value_range.get("min")
            max_point = value_range.get("max")
            if (
                not property_name
                or not isinstance(min_point, dict)
                or not isinstance(max_point, dict)
            ):
                continue
            unit = str(value_range.get("unit") or "").strip()
            min_value = (
                min_point.get("value")
                if unit
                else min_point.get("source_value_text") or min_point.get("value")
            )
            max_value = (
                max_point.get("value")
                if unit
                else max_point.get("source_value_text") or max_point.get("value")
            )
            if min_value in (None, "") or max_value in (None, ""):
                continue
            suffix = (
                f" {unit}"
                if unit and unit not in {str(min_value), str(max_value)}
                else ""
            )
            pieces.append(f"{property_name} range {min_value}-{max_value}{suffix}")
        return "; ".join(pieces)

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
        candidates.extend(
            self._build_ranked_route_text_candidates(
                frame=frame,
                blocks=blocks,
                limit=max(_ROUTE_CANDIDATE_LIMIT - len(candidates), 0),
            )
        )
        return candidates[:_ROUTE_CANDIDATE_LIMIT]

    def _build_ranked_route_text_candidates(
        self,
        *,
        frame: ObjectivePaperFrame,
        blocks: list[Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        scored_candidates: list[tuple[int, int, dict[str, Any]]] = []
        for block in sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        ):
            block_id = str(getattr(block, "block_id", "") or "")
            text = str(getattr(block, "text", "") or "").strip()
            block_type = str(getattr(block, "block_type", "") or "")
            section_label = self._block_section_label(block)
            if (
                not block_id
                or not text
                or block_type
                not in {"paragraph", "list_item", "figure_caption"}
            ):
                continue
            score = self._route_text_candidate_score(
                frame=frame,
                block_type=block_type,
                section_label=section_label,
                text=text,
            )
            if score <= 0:
                continue
            scored_candidates.append(
                (
                    -score,
                    int(getattr(block, "block_order", 0) or 0),
                    {
                        "source_kind": "text_window",
                        "source_ref": block_id,
                        "frame_status": "relevant",
                        "section_label": section_label,
                        "block_type": block_type,
                        "text": text[:_ROUTE_TEXT_CHARS],
                    },
                )
            )
        scored_candidates.sort()
        return [
            candidate
            for _, _, candidate in scored_candidates[: min(limit, _ROUTE_TEXT_CANDIDATE_LIMIT)]
        ]

    def _route_text_candidate_score(
        self,
        *,
        frame: ObjectivePaperFrame,
        block_type: str,
        section_label: str,
        text: str,
    ) -> int:
        text_haystack = text.casefold()
        if "references" in self._objective_column_key(section_label):
            return 0
        score = 0
        for term in frame.material_match:
            term_text = str(term or "").strip().casefold()
            if term_text and term_text in text_haystack:
                score += 1
        for term in (*frame.changed_variables, *frame.measured_property_scope):
            term_text = str(term or "").strip().casefold()
            if term_text and term_text in text_haystack:
                score += 4
        for term in frame.test_environment_scope:
            term_text = str(term or "").strip().casefold()
            if term_text and term_text in text_haystack:
                score += 2
        score += self._route_text_numeric_mechanism_score(
            section_label=section_label,
            text=text,
        )
        section_key = self._objective_column_key(section_label)
        if section_key.startswith(("3_", "4_")) or "conclusion" in section_key:
            score += 3
        if block_type in {"figure_caption", "list_item"}:
            score += 1
        if any(
            token in text_haystack
            for token in (
                "affect",
                "compared",
                "comparison",
                "exhibited",
                "observed",
                "result",
                "showed",
            )
        ):
            score += 2
        if any(
            token in text_haystack
            for token in (
                "fabricated",
                "processed",
                "treated",
                "treatment",
            )
        ):
            score += 2
        return score if score >= 4 else 0

    def _route_text_numeric_mechanism_score(
        self,
        *,
        section_label: str,
        text: str,
    ) -> int:
        if not _NUMBER_PATTERN.search(text):
            return 0
        haystack = " ".join(
            part
            for part in (
                str(section_label or "").casefold(),
                str(text or "").casefold(),
            )
            if part
        )
        if not any(
            token in haystack
            for token in (
                "cooling rate",
                "thermal gradient",
                "thermal simulation",
                "melt pool",
                "width to depth",
                "width/depth",
                "residual stress",
                "recrystallization",
            )
        ):
            return 0
        score = 4
        if any(token in haystack for token in ("microstructure", "thermal", "stress")):
            score += 1
        return score

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
        role = str(record.get("role") or "").strip()
        if role == "low_value_or_irrelevant":
            return False
        if role in _OBJECTIVE_EXTRACTABLE_ROUTE_ROLES:
            return True
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
        if objective.seed_document_ids:
            return ()
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
            candidate_skims = list(paper_skims) if not objective.seed_document_ids else []
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
            candidate_skims = list(paper_skims) if not objective.seed_document_ids else []
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
                source_objectives=source_objectives,
                source_field="material_scope",
            )
            process_axes = self._validated_merge_axes(
                tuple(group.process_axes),
                source_objectives=source_objectives,
                source_field="process_axes",
            )
            property_axes = self._validated_merge_axes(
                tuple(group.property_axes),
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
        unique_objectives: list[ResearchObjective] = []
        seen_objective_ids: set[str] = set()
        for objective in objectives:
            if objective.objective_id in seen_objective_ids:
                continue
            seen_objective_ids.add(objective.objective_id)
            unique_objectives.append(objective)

        deduped: list[ResearchObjective] = []
        for objective in unique_objectives:
            if self._objective_is_redundant_property_subset(
                objective,
                objectives=tuple(unique_objectives),
            ):
                continue
            deduped.append(objective)
        return tuple(deduped)

    def _objective_is_redundant_property_subset(
        self,
        objective: ResearchObjective,
        *,
        objectives: tuple[ResearchObjective, ...],
    ) -> bool:
        property_keys = self._axis_key_set(*objective.property_axes)
        if not property_keys:
            return False
        material_keys = self._axis_key_set(*objective.material_scope)
        process_keys = self._axis_key_set(*objective.process_axes)
        for other in objectives:
            if other.objective_id == objective.objective_id:
                continue
            other_property_keys = self._axis_key_set(*other.property_axes)
            if not property_keys < other_property_keys:
                continue
            other_material_keys = self._axis_key_set(*other.material_scope)
            if (
                material_keys
                and other_material_keys
                and not material_keys.intersection(other_material_keys)
            ):
                continue
            other_process_keys = self._axis_key_set(*other.process_axes)
            if (
                process_keys
                and other_process_keys
                and not process_keys.issubset(other_process_keys)
            ):
                continue
            return True
        return False

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
            seeded_skims = list(paper_skims) if not objective.seed_document_ids else []
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
        source_objectives: tuple[ResearchObjective, ...],
        source_field: str,
    ) -> list[str] | None:
        allowed_axes = self._axis_key_set(
            *(
                value
                for objective in source_objectives
                for value in getattr(objective, source_field)
            )
        )
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
        text = self._label_without_unit_suffix(value).casefold()
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
        if len(overlap) / max(len(alias_tokens), len(canonical_tokens)) >= 0.75:
            return True
        if len(alias_tokens) != len(canonical_tokens):
            return False
        return all(
            any(
                self._axis_token_is_close(alias_token, canonical_token)
                for canonical_token in canonical_tokens
            )
            for alias_token in alias_tokens
        ) and all(
            any(
                self._axis_token_is_close(canonical_token, alias_token)
                for alias_token in alias_tokens
            )
            for canonical_token in canonical_tokens
        )

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
            for token in (
                value.replace("_", " ").replace("-", " ").replace("/", " ").split()
            )
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
