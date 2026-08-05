from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from hashlib import sha1
import json
import logging
import math
import re
from typing import Any, Callable, Iterable, Mapping

from openai import OpenAIError
from pydantic import ValidationError

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.objectives.finding_synthesis_service import (
    FindingSynthesisService,
)
from application.core.objectives.extraction import (
    ObjectiveExtractor,
    build_default_objective_extractor,
)
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredObjectiveMergePlan,
    StructuredResearchObjective,
)
from application.source.artifact_input_service import load_document_tree
from application.source.collection_service import CollectionService
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveEvidenceComparison,
    ObjectiveEvidenceContext,
    ObjectiveEvidenceResult,
    ObjectiveEvidenceVariable,
    ObjectiveFactSet,
    PaperContribution,
    PaperSkim,
    ResearchObjective,
    build_research_objective_id,
    is_question_shaped_objective,
    normalize_objective_confidence,
    normalize_objective_terms,
)
from domain.ports import (
    ObjectiveRepository,
    PaperFactRepository,
    SourceArtifactRepository,
)
from domain.source import SourceArtifactSet, SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ObjectiveAnalysisArtifacts:
    """Canonical values produced by one versioned Objective analysis run."""

    contributions: tuple[PaperContribution, ...]
    evidence_records: tuple[ObjectiveEvidence, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class SourceSelectionHint:
    """Transient table-selection hint used only during one analysis run."""

    table_id: str
    document_id: str
    caption_text: str | None
    role: str
    strength: str | None
    matched_outcomes: tuple[str, ...]
    matched_variables: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        if not self.table_id:
            raise ValueError("source selection hint requires table_id")
        if self.role not in {"result_table", "condition_context"}:
            raise ValueError(f"unsupported source selection hint role: {self.role}")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceSelectionHint":
        return cls(
            table_id=_transient_text(payload.get("table_id")),
            document_id=_transient_text(payload.get("document_id")),
            caption_text=_transient_optional_text(payload.get("caption_text")),
            role=_transient_text(payload.get("role")),
            strength=_transient_optional_text(payload.get("strength")),
            matched_outcomes=normalize_objective_terms(
                payload.get("matched_outcomes")
            ),
            matched_variables=normalize_objective_terms(
                payload.get("matched_variables")
            ),
            reason=_transient_optional_text(payload.get("reason")),
        )


@dataclass(frozen=True)
class PaperAnalysisFrame:
    """Transient paper traversal state; never persisted or exposed by the API."""

    objective_id: str
    document_id: str
    relevance: str
    paper_role: str
    background: str | None
    material_match: tuple[str, ...]
    changed_variables: tuple[str, ...]
    measured_property_scope: tuple[str, ...]
    test_environment_scope: tuple[str, ...]
    relevant_sections: tuple[str, ...]
    relevant_tables: tuple[str, ...]
    excluded_tables: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperAnalysisFrame":
        return cls(
            objective_id=_transient_text(payload.get("objective_id")),
            document_id=_transient_text(
                payload.get("document_id") or payload.get("paper_id")
            ),
            relevance=_transient_text(payload.get("relevance")) or "uncertain",
            paper_role=_transient_text(payload.get("paper_role")) or "uncertain",
            background=_transient_optional_text(payload.get("background")),
            material_match=normalize_objective_terms(payload.get("material_match")),
            changed_variables=normalize_objective_terms(
                payload.get("changed_variables")
            ),
            measured_property_scope=normalize_objective_terms(
                payload.get("measured_property_scope")
            ),
            test_environment_scope=normalize_objective_terms(
                payload.get("test_environment_scope")
            ),
            relevant_sections=normalize_objective_terms(
                payload.get("relevant_sections")
            ),
            relevant_tables=normalize_objective_terms(payload.get("relevant_tables")),
            excluded_tables=normalize_objective_terms(payload.get("excluded_tables")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "relevance": self.relevance,
            "paper_role": self.paper_role,
            "background": self.background,
            "material_match": list(self.material_match),
            "changed_variables": list(self.changed_variables),
            "measured_property_scope": list(self.measured_property_scope),
            "test_environment_scope": list(self.test_environment_scope),
            "relevant_sections": list(self.relevant_sections),
            "relevant_tables": list(self.relevant_tables),
            "excluded_tables": list(self.excluded_tables),
        }


@dataclass(frozen=True)
class EvidenceCandidate:
    """Transient source-selection decision keyed by its stable Source locator."""

    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    role: str
    extractable: bool
    reason: str | None
    table_schema: dict[str, Any]
    column_roles: dict[str, Any]
    join_plan: dict[str, Any]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvidenceCandidate":
        return cls(
            objective_id=_transient_text(payload.get("objective_id")),
            document_id=_transient_text(
                payload.get("document_id") or payload.get("paper_id")
            ),
            source_kind=_transient_text(payload.get("source_kind")) or "text_window",
            source_ref=_transient_text(payload.get("source_ref")),
            role=_transient_text(payload.get("role")) or "low_value_or_irrelevant",
            extractable=bool(payload.get("extractable")),
            reason=_transient_optional_text(payload.get("reason")),
            table_schema=_transient_mapping(payload.get("table_schema")),
            column_roles=_transient_mapping(payload.get("column_roles")),
            join_plan=_transient_mapping(payload.get("join_plan")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "role": self.role,
            "extractable": self.extractable,
            "reason": self.reason,
            "table_schema": dict(self.table_schema),
            "column_roles": dict(self.column_roles),
            "join_plan": dict(self.join_plan),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ExtractedEvidenceDraft:
    """Transient structured extraction before Source text is attached."""

    evidence_id: str
    objective_id: str
    document_id: str
    source_kind: str | None
    source_ref: str | None
    evidence_role: str | None
    selection_reason: str | None
    selection_status: str
    changed_variables: tuple[ObjectiveEvidenceVariable, ...]
    comparison: ObjectiveEvidenceComparison | None
    reported_result: ObjectiveEvidenceResult | None
    attribution_scope: str
    scientific_context: ObjectiveEvidenceContext
    source_refs: tuple[dict[str, Any], ...]
    evidence_anchor_ids: tuple[str, ...]
    resolution_status: str
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExtractedEvidenceDraft":
        source_refs = _transient_mapping_tuple(payload.get("source_refs"))
        first_source_ref = source_refs[0] if source_refs else {}
        objective_id = _transient_text(payload.get("objective_id"))
        document_id = _transient_text(
            payload.get("document_id") or payload.get("paper_id")
        )
        source_kind = _transient_optional_text(
            payload.get("source_kind") or first_source_ref.get("source_kind")
        )
        source_ref = _transient_optional_text(
            payload.get("source_ref") or first_source_ref.get("source_ref")
        )
        evidence_role = _transient_optional_text(
            payload.get("evidence_role") or first_source_ref.get("evidence_role")
        )
        reported_result_payload = payload.get("reported_result")
        reported_result = (
            ObjectiveEvidenceResult.from_mapping(reported_result_payload)
            if isinstance(reported_result_payload, Mapping)
            else None
        )
        evidence_id = _transient_optional_text(payload.get("evidence_id"))
        if evidence_id is None:
            identity = json.dumps(
                [
                    objective_id,
                    document_id,
                    evidence_role,
                    source_refs,
                    payload.get("changed_variables"),
                    payload.get("comparison"),
                    payload.get("reported_result"),
                ],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            evidence_id = f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        return cls(
            evidence_id=evidence_id,
            objective_id=objective_id,
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            evidence_role=evidence_role,
            selection_reason=_transient_optional_text(
                payload.get("selection_reason")
                or first_source_ref.get("selection_reason")
            ),
            selection_status=_transient_text(payload.get("selection_status"))
            or "extracted",
            changed_variables=tuple(
                ObjectiveEvidenceVariable.from_mapping(item)
                for item in payload.get("changed_variables", ())
                if isinstance(item, Mapping)
            ),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=reported_result,
            attribution_scope=_transient_text(payload.get("attribution_scope"))
            or "not_attributable",
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ObjectiveEvidenceContext()
            ),
            source_refs=source_refs,
            evidence_anchor_ids=normalize_objective_terms(
                payload.get("evidence_anchor_ids") or payload.get("anchor_ids")
            ),
            resolution_status=_transient_text(payload.get("resolution_status"))
            or "unknown",
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "evidence_role": self.evidence_role,
            "selection_reason": self.selection_reason,
            "selection_status": self.selection_status,
            "changed_variables": [
                item.to_record() for item in self.changed_variables
            ],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "attribution_scope": self.attribution_scope,
            "scientific_context": self.scientific_context.to_record(),
            "source_refs": [dict(item) for item in self.source_refs],
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "resolution_status": self.resolution_status,
            "confidence": self.confidence,
        }


def _transient_text(value: Any) -> str:
    return str(value or "").strip()


def _transient_optional_text(value: Any) -> str | None:
    text = _transient_text(value)
    return text or None


def _transient_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _transient_mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))

_SKIM_TEXT_PREVIEW_CHARS = 4000
_SKIM_MODEL_TEXT_PREVIEW_CHARS = 400
_SKIM_HEADING_LIMIT = 16
_SKIM_CAPTION_LIMIT = 12
_DISCOVERY_AXIS_VALUE_LIMIT = 2
_DISCOVERY_OBJECTIVE_LIMIT = 3
_DISCOVERY_TEXT_VALUE_CHARS = 80
_DISCOVERY_OBJECTIVE_TEXT_CHARS = 180
_FRAME_SECTION_SNIPPET_LIMIT = 12
_FRAME_SECTION_TEXT_CHARS = 420
_FRAME_SECTION_OVERVIEW_LIMIT = 4
_FRAME_TABLE_LIMIT = 10
_FRAME_TABLE_ROW_LIMIT = 3
_ROUTE_TEXT_CHARS = 900
_ROUTE_PROMPT_TEXT_CHARS = 320
_ROUTE_PROMPT_HEADER_LIMIT = 8
_ROUTE_CANDIDATE_LIMIT = 40
_ROUTE_TEXT_CANDIDATE_LIMIT = 8
_ROUTE_TEXT_HINT_LIMIT = 3
_ROUTE_TREE_TEXT_SECTION_LIMIT = 3
_OBJECTIVE_STATE_ITEM_LIMIT = 12
_OBJECTIVE_STATE_TEXT_CHARS = 220
_OBJECTIVE_EVIDENCE_TEXT_CHARS = 6000
_OBJECTIVE_EVIDENCE_PROMPT_TEXT_CHARS = 1800
_OBJECTIVE_EVIDENCE_PROMPT_TABLE_ROWS = 8
_OBJECTIVE_EVIDENCE_PROMPT_TABLE_CELLS = 80
_OBJECTIVE_PAIRWISE_SCOPE_LIMIT = 48
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
    "densification": ("relative density",),
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
    "pitting corrosion behavior": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passive film resistance",
        "passivation behavior",
    ),
    "pitting corrosion": (
        "corrosion potential",
        "pitting potential",
        "corrosion current density",
        "passive film resistance",
        "passivation behavior",
    ),
    "defect structure": (
        "defect complexity",
        "defect density",
        "defect diameter",
        "defect distribution",
        "max defect length",
        "max defect diameter",
        "max defect size",
        "defect length",
        "defect shape",
        "defect size",
        "porosity",
    ),
    "microstructure": (
        "cellular structure",
        "cellular-dendritic microstructure",
        "crystallographic texture",
        "grain morphology",
        "grain structure",
    ),
    "fatigue strength": (
        "fatigue strength",
        "fatigue limit",
        "fatigue strength at 10 4 cycles",
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
    "fat 50": "fatigue limit",
    "fat 50 %": "fatigue limit",
    "fat50": "fatigue limit",
    "fat50 %": "fatigue limit",
    "fat at 10 4 cycles": "fatigue strength",
    "i corr": "corrosion current density",
    "icorr": "corrosion current density",
    "current density": "corrosion current density",
    "r film": "passive film resistance",
    "rfilm": "passive film resistance",
    "film resistance": "passive film resistance",
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
    "max. defect length": "max defect length",
    "max defect length": "max defect length",
    "max defect length lcsm": "max defect length",
    "max. defect diameter": "max defect diameter",
    "maximum defect diameter": "max defect diameter",
    "maximum defect size": "max defect size",
    "maximum defect length": "max defect length",
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
_OBJECTIVE_SYMBOL_AXIS_ALIASES = {
    "alpha": ("build orientation alpha angle",),
    "α": ("build orientation alpha angle",),
    "beta": ("build orientation beta angle",),
    "β": ("build orientation beta angle",),
    "theta": ("scan strategy rotation angle",),
    "θ": ("scan strategy rotation angle",),
    "ɵ": ("scan strategy rotation angle",),
    "ved": ("volumetric energy density", "energy density"),
}
_OBJECTIVE_AXIS_SYNONYMS = {
    "scan strategy": ("scanning strategy",),
    "scanning strategy": ("scan strategy",),
}
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
        "defect length",
        "defect structure",
        "grain size",
        "max defect length",
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


class ResearchObjectiveService:
    """Discover objective candidates and generate analysis artifacts."""

    def __init__(
        self,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        paper_fact_repository: PaperFactRepository,
        objective_repository: ObjectiveRepository,
        document_profile_service: DocumentProfileService,
        finding_synthesis_service: FindingSynthesisService,
        objective_extractor: ObjectiveExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._objective_extractor = objective_extractor
        self.paper_fact_repository = paper_fact_repository
        self.objective_repository = objective_repository
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service
        self.finding_synthesis_service = finding_synthesis_service

    def discover_and_replace_objective_candidates(
        self,
        collection_id: str,
        progress_callback: ProgressCallback | None = None,
        *,
        build_id: str,
    ) -> tuple[ResearchObjective, ...]:
        objective_inputs = self._build_objective_candidate_inputs(
            collection_id,
            progress_callback=progress_callback,
            build_id=build_id,
        )
        self.objective_repository.replace(
            collection_id,
            build_id,
            ObjectiveFactSet(
                research_objectives_ready=True,
                paper_skims=objective_inputs["paper_skims"],
                research_objectives=objective_inputs["research_objectives"],
            ),
        )
        logger.info(
            "Research objective candidates finished collection_id=%s paper_skim_count=%s objective_count=%s",
            collection_id,
            len(objective_inputs["paper_skims"]),
            len(objective_inputs["research_objectives"]),
        )
        return objective_inputs["research_objectives"]

    def generate_objective_analysis_artifacts(
        self,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveAnalysisArtifacts:
        if analysis.collection_id != collection_id:
            raise ValueError("analysis belongs to another collection")
        objective = self.objective_repository.read_objective(
            collection_id, analysis.objective_id
        )
        if objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        if objective.active_analysis_version != analysis.analysis_version:
            raise ValueError("analysis is not the active objective version")
        objective_inputs = self._build_objective_analysis_inputs(
            collection_id,
            build_id=analysis.source_build_id,
        )
        paper_frames = self._build_objective_paper_frames(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            objectives=(objective,),
            paper_skims=objective_inputs["paper_skims"],
            documents=objective_inputs["artifacts"].documents,
            profiles_by_document_id=objective_inputs["profiles_by_document_id"],
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        evidence_candidates = self._build_objective_evidence_routes(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            objectives=(objective,),
            objective_paper_frames=paper_frames,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        evidence_drafts = self._build_objective_evidence(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            objectives=(objective,),
            paper_skims=objective_inputs["paper_skims"],
            objective_paper_frames=paper_frames,
            objective_evidence_routes=evidence_candidates,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            table_cells_by_document_id=objective_inputs[
                "table_cells_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        evidence_drafts = self._objective_detail_evidence(
            evidence_drafts,
            objective_context=objective,
        )
        contributions = self._analysis_contributions(
            collection_id=collection_id,
            analysis=analysis,
            frames=paper_frames,
        )
        evidence_records = self._analysis_evidence_records(
            collection_id=collection_id,
            analysis=analysis,
            drafts=evidence_drafts,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            figures_by_document_id=objective_inputs["figures_by_document_id"],
        )
        findings = self.finding_synthesis_service.synthesize(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            contributions=contributions,
            evidence_records=evidence_records,
        )
        return ObjectiveAnalysisArtifacts(
            contributions=contributions,
            evidence_records=evidence_records,
            findings=findings,
        )

    def _analysis_contributions(
        self,
        *,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        frames: tuple[PaperAnalysisFrame, ...],
    ) -> tuple[PaperContribution, ...]:
        contributions: list[PaperContribution] = []
        for frame in frames:
            excluded = frame.relevance == "irrelevant" or frame.paper_role == "irrelevant"
            contributions.append(
                PaperContribution(
                    collection_id=collection_id,
                    objective_id=analysis.objective_id,
                    analysis_version=analysis.analysis_version,
                    document_id=frame.document_id,
                    analysis_status="excluded" if excluded else "analyzed",
                    relevance=frame.relevance,
                    paper_role=frame.paper_role,
                    contribution_summary=frame.background,
                    material_match=frame.material_match,
                    changed_variables=frame.changed_variables,
                    measured_property_scope=frame.measured_property_scope,
                    test_environment_scope=frame.test_environment_scope,
                    exclusion_reason=(
                        frame.background or "Paper is not relevant to this objective."
                        if excluded
                        else None
                    ),
                    warnings=(),
                    confidence=1.0 if frame.relevance == "high" else 0.7,
                )
            )
        return tuple(contributions)

    def _analysis_evidence_records(
        self,
        *,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        drafts: tuple[ExtractedEvidenceDraft, ...],
        blocks_by_document_id: Mapping[str, list[Any]],
        tables_by_document_id: Mapping[str, list[Any]],
        figures_by_document_id: Mapping[str, list[Any]],
    ) -> tuple[ObjectiveEvidence, ...]:
        records: list[ObjectiveEvidence] = []
        seen: set[str] = set()
        for draft in drafts:
            source = self._canonical_evidence_source(
                draft,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
            )
            if source is None or draft.evidence_id in seen:
                continue
            seen.add(draft.evidence_id)
            evidence_role = self._canonical_evidence_role(draft)
            records.append(
                ObjectiveEvidence(
                    collection_id=collection_id,
                    objective_id=analysis.objective_id,
                    analysis_version=analysis.analysis_version,
                    evidence_id=draft.evidence_id[:128],
                    document_id=draft.document_id,
                    source_kind=source["source_kind"],
                    source_ref=source["source_ref"],
                    source_excerpt=source["source_excerpt"],
                    page_numbers=source["page_numbers"],
                    related_source_refs=source["related_source_refs"],
                    evidence_role=evidence_role,
                    selection_status="extracted",
                    selection_reason=draft.selection_reason,
                    changed_variables=draft.changed_variables,
                    comparison=draft.comparison,
                    reported_result=draft.reported_result,
                    attribution_scope=draft.attribution_scope,
                    scientific_context=draft.scientific_context,
                    anchor_ids=draft.evidence_anchor_ids,
                    resolution_status=(
                        draft.resolution_status
                        if draft.resolution_status in {"resolved", "partial"}
                        else "partial"
                    ),
                    failure_reason=None,
                    confidence=draft.confidence,
                )
            )
        return tuple(records)

    def _canonical_evidence_source(
        self,
        draft: ExtractedEvidenceDraft,
        *,
        blocks_by_document_id: Mapping[str, list[Any]],
        tables_by_document_id: Mapping[str, list[Any]],
        figures_by_document_id: Mapping[str, list[Any]],
    ) -> dict[str, Any] | None:
        candidates = [
            *[dict(value) for value in draft.source_refs],
            {
                "source_kind": draft.source_kind,
                "source_ref": draft.source_ref,
            },
        ]
        related: list[dict[str, Any]] = []
        seen_locators: set[tuple[Any, ...]] = set()
        excerpts: list[str] = []
        primary: dict[str, Any] | None = None
        for candidate in candidates:
            source_kind = _transient_text(candidate.get("source_kind"))
            source_ref = _transient_text(candidate.get("source_ref"))
            if not source_ref:
                continue
            normalized_kind = "text_window" if source_kind in {"block", "text"} else source_kind
            located = self._source_excerpt_for_locator(
                document_id=draft.document_id,
                source_kind=normalized_kind,
                source_ref=source_ref,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
            )
            locator = {
                key: value
                for key, value in candidate.items()
                if key != "source_excerpt" and value not in (None, "", [], {})
            }
            locator["source_kind"] = normalized_kind or "text_window"
            locator["source_ref"] = source_ref
            page = candidate.get("page") or (located or {}).get("page")
            if page not in (None, ""):
                locator["page"] = page
            locator_key = (
                locator["source_kind"],
                locator["source_ref"],
                locator.get("row_index"),
                locator.get("col_index"),
            )
            is_bare_duplicate = (
                locator.get("row_index") is None
                and locator.get("col_index") is None
                and any(
                    item.get("source_kind") == locator["source_kind"]
                    and item.get("source_ref") == locator["source_ref"]
                    for item in related
                )
            )
            if locator_key not in seen_locators and not is_bare_duplicate:
                seen_locators.add(locator_key)
                related.append(locator)
            if located is None:
                continue
            if primary is None:
                primary = {
                    "source_kind": located["source_kind"],
                    "source_ref": source_ref,
                    "page": located["page"],
                }
            excerpt = _transient_text(candidate.get("source_excerpt"))
            if not excerpt and not excerpts:
                excerpt = located["source_excerpt"]
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
        if primary is None or not excerpts:
            return None
        return {
            "source_kind": primary["source_kind"],
            "source_ref": primary["source_ref"],
            "source_excerpt": "\n".join(excerpts)[:12_000],
            "page_numbers": ((primary["page"],) if primary["page"] else ()),
            "related_source_refs": tuple(related),
        }

    @staticmethod
    def _source_excerpt_for_locator(
        *,
        document_id: str,
        source_kind: str,
        source_ref: str,
        blocks_by_document_id: Mapping[str, list[Any]],
        tables_by_document_id: Mapping[str, list[Any]],
        figures_by_document_id: Mapping[str, list[Any]],
    ) -> dict[str, Any] | None:
        if source_kind == "text_window":
            for block in blocks_by_document_id.get(document_id, []):
                if str(getattr(block, "block_id", "")) == source_ref:
                    text = str(getattr(block, "text", "")).strip()
                    if text:
                        return {
                            "source_kind": "text_window",
                            "source_excerpt": text[:12_000],
                            "page": getattr(block, "page", None),
                        }
        elif source_kind == "table":
            for table in tables_by_document_id.get(document_id, []):
                if str(getattr(table, "table_id", "")) == source_ref:
                    record = table.to_record()
                    text = str(
                        record.get("table_markdown")
                        or record.get("table_text")
                        or record.get("caption_text")
                        or ""
                    ).strip()
                    if text:
                        return {
                            "source_kind": "table",
                            "source_excerpt": text[:12_000],
                            "page": getattr(table, "page", None),
                        }
        elif source_kind == "figure":
            for figure in figures_by_document_id.get(document_id, []):
                if str(getattr(figure, "figure_id", "")) == source_ref:
                    text = str(getattr(figure, "caption_text", "") or "").strip()
                    if text:
                        return {
                            "source_kind": "figure",
                            "source_excerpt": text[:12_000],
                            "page": getattr(figure, "page", None),
                        }
        return None

    @staticmethod
    def _canonical_evidence_role(draft: ExtractedEvidenceDraft) -> str:
        role = _transient_text(draft.evidence_role)
        if role in {
            "direct_result",
            "condition_context",
            "mechanism_context",
            "baseline_context",
            "comparison_context",
            "background_context",
            "contradictory_result",
            "irrelevant",
        }:
            return role
        return "irrelevant"

    def _build_objective_candidate_inputs(
        self,
        collection_id: str,
        progress_callback: ProgressCallback | None = None,
        *,
        build_id: str | None = None,
    ) -> dict[str, Any]:
        source_inputs = self._load_objective_source_inputs(
            collection_id,
            build_id=build_id,
        )
        artifacts = source_inputs["artifacts"]
        profiles_by_document_id = source_inputs["profiles_by_document_id"]
        blocks_by_document_id = source_inputs["blocks_by_document_id"]
        tables_by_document_id = source_inputs["tables_by_document_id"]
        figures_by_document_id = source_inputs["figures_by_document_id"]
        document_trees_by_document_id = source_inputs["document_trees_by_document_id"]
        extractor = source_inputs["extractor"]

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
                active_document_title=getattr(document, "title", None),
                active_source_filename=self._resolve_source_filename(document),
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
                document_tree=document_trees_by_document_id.get(document.document_id),
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
            "paper_skims": [
                self._build_objective_discovery_skim(skim)
                for skim in paper_skims
            ],
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
        discovery_skims = {
            str(skim["document_id"]): skim for skim in objective_payload["paper_skims"]
        }
        accepted_objectives: list[ResearchObjective] = []
        for item in parsed_objectives.objectives:
            objective = self._canonicalize_objective_document_ids(
                ResearchObjective.from_mapping(
                    {
                        **item.model_dump(),
                        "collection_id": collection_id,
                    }
                ),
                documents=artifacts.documents,
            )
            if not is_question_shaped_objective(objective):
                continue
            matching_document_ids: set[str] = set()
            for document_id, skim in discovery_skims.items():
                for candidate_question in skim["possible_objectives"]:
                    try:
                        StructuredResearchObjective.model_validate(
                            {
                                "question": candidate_question,
                                "material_scope": [
                                    *objective.material_scope,
                                    *skim["candidate_materials"],
                                ],
                                "variables": objective.variables,
                                "outcomes": objective.outcomes,
                                "constraints": [
                                    *objective.constraints,
                                    *skim["candidate_processes"],
                                ],
                            }
                        )
                    except ValidationError:
                        continue
                    matching_document_ids.add(document_id)
                    break
            seed_document_ids = set(objective.seed_document_ids)
            if not seed_document_ids and len(matching_document_ids) == 1:
                payload = objective.to_record()
                payload["seed_document_ids"] = sorted(matching_document_ids)
                objective = ResearchObjective.from_mapping(payload)
                seed_document_ids = set(objective.seed_document_ids)
                logger.info(
                    "Research objective recovered one missing seed document "
                    "collection_id=%s question=%s seed_document_id=%s",
                    collection_id,
                    objective.question,
                    next(iter(seed_document_ids)),
                )
            if not seed_document_ids or not seed_document_ids.issubset(
                matching_document_ids
            ):
                logger.warning(
                    "Research objective rejected because axes do not come from one "
                    "seed candidate collection_id=%s question=%s seed_document_ids=%s",
                    collection_id,
                    objective.question,
                    sorted(seed_document_ids),
                )
                continue
            accepted_objectives.append(objective)
        research_objectives = tuple(accepted_objectives)
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
        for objective in research_objectives:
            StructuredResearchObjective.model_validate(
                {
                    key: value
                    for key, value in objective.to_record().items()
                    if key in StructuredResearchObjective.model_fields
                }
            )
        research_objectives = self._dedupe_research_objectives(research_objectives)
        logger.info(
            "Research objective discovery finished collection_id=%s paper_skim_count=%s discovered_objective_count=%s accepted_objective_count=%s",
            collection_id,
            len(paper_skims),
            discovered_objective_count,
            len(research_objectives),
        )
        return {
            **source_inputs,
            "paper_skims": tuple(paper_skims),
            "research_objectives": research_objectives,
        }

    @staticmethod
    def _build_objective_discovery_skim(skim: PaperSkim) -> dict[str, Any]:
        """Keep collection-level discovery input within the model context budget."""

        def values(
            items: tuple[str, ...],
            limit: int,
        ) -> list[str]:
            return [
                str(item).strip()[:_DISCOVERY_TEXT_VALUE_CHARS]
                for item in items[:limit]
                if str(item).strip()
            ]

        possible_objectives = [
            text
            for item in skim.possible_objectives
            if (text := str(item).strip())
            and len(text) <= _DISCOVERY_OBJECTIVE_TEXT_CHARS
        ][:_DISCOVERY_OBJECTIVE_LIMIT]

        return {
            "document_id": skim.document_id,
            "doc_role": skim.doc_role,
            "candidate_materials": values(
                skim.candidate_materials,
                _DISCOVERY_AXIS_VALUE_LIMIT,
            ),
            "candidate_processes": values(
                skim.candidate_processes,
                _DISCOVERY_AXIS_VALUE_LIMIT,
            ),
            "possible_objectives": possible_objectives,
        }

    def _canonicalize_objective_document_ids(
        self,
        objective: ResearchObjective,
        *,
        documents: Iterable[Any],
    ) -> ResearchObjective:
        """Keep model-produced document references within the current build."""
        aliases: dict[str, str] = {}
        canonical_ids: set[str] = set()
        for document in documents:
            document_id = str(getattr(document, "document_id", "") or "").strip()
            if not document_id:
                continue
            canonical_ids.add(document_id)
            metadata = getattr(document, "metadata", {}) or {}
            for key in (
                "source_filename",
                "original_filename",
                "stored_filename",
                "source_path",
            ):
                value = str(metadata.get(key) or "").strip()
                if value:
                    aliases[value] = document_id
                    aliases[value.rsplit("/", 1)[-1]] = document_id

        def canonicalize(values: Iterable[str]) -> list[str]:
            result: list[str] = []
            seen: set[str] = set()
            for value in values:
                normalized = str(value or "").strip()
                document_id = (
                    normalized
                    if normalized in canonical_ids
                    else aliases.get(normalized)
                    or aliases.get(normalized.rsplit("/", 1)[-1])
                )
                if (
                    not document_id
                    and len(normalized) >= 32
                    and all(
                        character in "0123456789abcdefABCDEF"
                        for character in normalized
                    )
                ):
                    truncated_matches = [
                        candidate
                        for candidate in canonical_ids
                        if len(candidate) == len(normalized) + 1
                        and candidate.startswith(normalized)
                    ]
                    if len(truncated_matches) == 1:
                        document_id = truncated_matches[0]
                if document_id and document_id not in seen:
                    seen.add(document_id)
                    result.append(document_id)
            return result

        payload = objective.to_record()
        payload["seed_document_ids"] = canonicalize(objective.seed_document_ids)
        payload["excluded_document_ids"] = canonicalize(
            objective.excluded_document_ids
        )
        return ResearchObjective.from_mapping(payload)

    def _build_objective_analysis_inputs(
        self,
        collection_id: str,
        *,
        build_id: str,
    ) -> dict[str, Any]:
        source_inputs = self._load_objective_source_inputs(
            collection_id,
            build_id=build_id,
        )
        facts = self.objective_repository.read(collection_id, build_id=build_id)
        if facts.research_objectives_ready and facts.paper_skims:
            return {
                **source_inputs,
                "paper_skims": facts.paper_skims,
                "research_objectives": facts.research_objectives,
            }
        raise ResearchObjectivesNotReadyError(collection_id)

    def _load_objective_source_inputs(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self._load_source_artifacts(collection_id, build_id=build_id)
            profiles = self.document_profile_service.read_document_profiles(
                collection_id,
                build_id=build_id,
            )
        except (FileNotFoundError, DocumentProfilesNotReadyError) as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

        return {
            "artifacts": artifacts,
            "profiles_by_document_id": {
                profile.document_id: profile
                for profile in profiles
            },
            "blocks_by_document_id": self._group_by_document_id(artifacts.blocks),
            "tables_by_document_id": self._group_by_document_id(artifacts.tables),
            "table_cells_by_document_id": self._group_by_document_id(
                artifacts.table_cells
            ),
            "figures_by_document_id": self._group_by_document_id(artifacts.figures),
            "document_trees_by_document_id": {
                document.document_id: load_document_tree(
                    collection_id,
                    document.document_id,
                    self.source_artifact_repository,
                    build_id=build_id,
                )
                for document in artifacts.documents
            },
            "extractor": self._get_objective_extractor(),
        }

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

    def _objective_detail_evidence(
        self,
        evidence_items: tuple[ExtractedEvidenceDraft, ...],
        *,
        objective_context: ResearchObjective | None,
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        if (
            objective_context is None
            or not objective_context.outcomes
            or not evidence_items
        ):
            return evidence_items
        target_axes = self._objective_outcomes(objective_context)
        if not target_axes:
            return evidence_items

        target_units = tuple(
            unit
            for unit in evidence_items
            if self._objective_evidence_matches_target_property(
                unit,
                target_axes=target_axes,
            )
        )
        if not target_units:
            return target_units

        target_document_ids = {unit.document_id for unit in target_units}
        selected_ids = {unit.evidence_id for unit in target_units}
        selected = list(target_units)
        for unit in evidence_items:
            if unit.evidence_id in selected_ids or unit.reported_result is not None:
                continue
            if unit.document_id in target_document_ids:
                selected.append(unit)
                selected_ids.add(unit.evidence_id)
        return tuple(selected)

    def _objective_evidence_matches_target_property(
        self,
        unit: ExtractedEvidenceDraft,
        *,
        target_axes: tuple[str, ...],
    ) -> bool:
        if unit.reported_result is None:
            return False
        return self._objective_property_matches_target_axes(
            unit.reported_result.outcome,
            target_axes=target_axes,
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

    def _progress_document_metadata(
        self,
        *,
        document_trees_by_document_id: dict[str, SourceDocumentTree],
    ) -> dict[str, dict[str, str | None]]:
        return {
            document_id: {
                "title": str(tree.root.title or "").strip() or None,
                "source_filename": None,
            }
            for document_id, tree in document_trees_by_document_id.items()
        }

    def _build_objective_paper_frames(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
        documents: tuple[Any, ...],
        profiles_by_document_id: dict[str, Any],
        blocks_by_document_id: dict[str, list[Any]],
        tables_by_document_id: dict[str, list[Any]],
        document_trees_by_document_id: dict[str, SourceDocumentTree],
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[PaperAnalysisFrame, ...]:
        skim_by_document_id = {
            skim.document_id: skim
            for skim in paper_skims
            if skim.document_id
        }
        frames: list[PaperAnalysisFrame] = []
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
            for document_position, document in enumerate(documents, start=1):
                completed_frame_requests += 1
                document_id = str(getattr(document, "document_id", "") or "")
                document_title = str(getattr(document, "title", None) or "").strip() or None
                source_filename = self._resolve_source_filename(document)
                self._notify_progress(
                    progress_callback,
                    phase="objective_paper_framing_started",
                    current=completed_frame_requests,
                    total=total_frame_requests,
                    unit="frames",
                    message="Checking each paper against each research objective.",
                    active_document_id=document_id,
                    active_document_title=document_title,
                    active_source_filename=source_filename,
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
                    paper_skim=skim_by_document_id.get(document_id),
                    document=document,
                    profile=profiles_by_document_id.get(document_id),
                    blocks=blocks_by_document_id.get(document_id, []),
                    tables=tables,
                    document_tree=document_trees_by_document_id.get(document_id),
                )
                try:
                    parsed = extractor.assess_objective_paper(payload)
                    record = parsed.model_dump()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Research objective paper framing model failed; using deterministic frame collection_id=%s objective_id=%s document_id=%s",
                        collection_id,
                        objective.objective_id,
                        document_id,
                        exc_info=True,
                    )
                    record = self._build_deterministic_objective_paper_frame_record(
                        objective=objective,
                        paper_skim=skim_by_document_id.get(document_id),
                        payload=payload,
                    )
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
                frame = PaperAnalysisFrame.from_mapping(record)
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
        extractor: ObjectiveExtractor,
        objectives: tuple[ResearchObjective, ...],
        objective_paper_frames: tuple[PaperAnalysisFrame, ...],
        blocks_by_document_id: dict[str, list[Any]],
        tables_by_document_id: dict[str, list[Any]],
        document_trees_by_document_id: dict[str, SourceDocumentTree],
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[EvidenceCandidate, ...]:
        objective_by_id = {
            objective.objective_id: objective
            for objective in objectives
        }
        all_tables = tuple(
            table
            for document_tables in tables_by_document_id.values()
            for table in document_tables
        )
        routing_hints_by_objective_id = {
            objective.objective_id: self._build_objective_table_routing_hints(
                objective,
                tables=all_tables,
            )
            for objective in objectives
        }
        routes: list[EvidenceCandidate] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        logger.info(
            "Research objective evidence routing started collection_id=%s frame_count=%s",
            collection_id,
            len(objective_paper_frames),
        )
        frame_count = len(objective_paper_frames)
        document_metadata = self._progress_document_metadata(
            document_trees_by_document_id=document_trees_by_document_id,
        )
        for frame_position, frame in enumerate(objective_paper_frames, start=1):
            frame_document_metadata = document_metadata.get(frame.document_id, {})
            self._notify_progress(
                progress_callback,
                phase="objective_evidence_routing_started",
                current=frame_position,
                total=frame_count,
                unit="frames",
                message="Routing source blocks and tables for objective-scoped extraction.",
                active_document_id=frame.document_id,
                active_document_title=frame_document_metadata.get("title"),
                active_source_filename=frame_document_metadata.get("source_filename"),
                active_objective_id=frame.objective_id,
            )
            logger.info(
                "Research objective evidence routing frame started collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s relevance=%s completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.document_id,
                frame_position,
                frame_count,
                frame.relevance,
                frame_position - 1,
                max(frame_count - frame_position + 1, 0),
            )
            if frame.relevance == "irrelevant":
                logger.info(
                    "Research objective evidence routing frame skipped collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s reason=irrelevant completed_frames=%s remaining_frames=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    frame.document_id,
                    frame_position,
                    frame_count,
                    frame_position,
                    max(frame_count - frame_position, 0),
                )
                continue
            objective = objective_by_id.get(frame.objective_id)
            if objective is None:
                logger.info(
                    "Research objective evidence routing frame skipped collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s reason=missing_objective completed_frames=%s remaining_frames=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    frame.document_id,
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
                document_tree=document_trees_by_document_id.get(frame.document_id),
            )
            if not source_candidates:
                logger.info(
                    "Research objective evidence routing frame finished collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s source_candidate_count=0 route_count=0 extractable_route_count=0 completed_frames=%s remaining_frames=%s",
                    collection_id,
                    frame.objective_id,
                    frame.document_id,
                    frame.document_id,
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
            objective_context = objective_by_id.get(frame.objective_id)
            for candidate in source_candidates:
                if candidate.get("frame_status") == "excluded":
                    route_key = (
                        frame.objective_id,
                        frame.document_id,
                        str(candidate.get("source_kind") or ""),
                        str(candidate.get("source_ref") or ""),
                        "low_value_or_irrelevant",
                    )
                    if route_key not in seen:
                        seen.add(route_key)
                        routes.append(
                            EvidenceCandidate.from_mapping(
                                {
                                    "objective_id": frame.objective_id,
                                    "document_id": frame.document_id,
                                    "source_kind": candidate.get("source_kind"),
                                    "source_ref": candidate.get("source_ref"),
                                    "role": "low_value_or_irrelevant",
                                    "extractable": False,
                                    "reason": "Excluded by objective paper frame.",
                                    "table_schema": self._route_table_schema_record(
                                        candidate=candidate,
                                    ),
                                    "column_roles": {},
                                    "join_plan": {},
                                    "confidence": 0.7,
                                }
                            )
                        )
                    continue
                payload = {
                    "collection_id": collection_id,
                    "objective": self._route_prompt_objective_record(objective),
                    "paper_frame": self._route_prompt_paper_frame_record(frame),
                    "tree_position": self._route_tree_position(candidate),
                    "document_state": self._empty_objective_document_state(),
                    "current_source": self._route_prompt_current_source(candidate),
                }
                try:
                    parsed = extractor.select_objective_evidence(payload)
                    route_records = [item.model_dump() for item in parsed.selections[:1]]
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Research objective evidence routing model failed; using deterministic route collection_id=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s",
                        collection_id,
                        frame.objective_id,
                        frame.document_id,
                        candidate.get("source_kind"),
                        candidate.get("source_ref"),
                        exc_info=True,
                    )
                    route_records = [
                        self._build_deterministic_objective_route_record(
                            objective_context=objective_context,
                            candidate=candidate,
                        )
                    ]
                for record in route_records:
                    source_kind = str(candidate.get("source_kind") or "")
                    source_ref = str(candidate.get("source_ref") or "")
                    route_candidate = candidate_by_key.get((source_kind, source_ref))
                    if route_candidate is None:
                        continue
                    record = self._finalize_objective_route_record(
                        record=record,
                        frame=frame,
                        objective_context=objective_context,
                        route_candidate=route_candidate,
                    )
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
                    routes.append(EvidenceCandidate.from_mapping(record))
            self._append_objective_context_hint_routes(
                routes=routes,
                seen=seen,
                frame=frame,
                objective_context=objective_context,
                routing_hints=routing_hints_by_objective_id.get(
                    frame.objective_id,
                    (),
                ),
                candidate_by_key=candidate_by_key,
            )
            self._append_ranked_text_hint_routes(
                routes=routes,
                seen=seen,
                frame=frame,
                objective_context=objective_context,
                source_candidates=source_candidates,
            )
            frame_routes = routes[frame_route_count_before:]
            logger.info(
                "Research objective evidence routing frame finished collection_id=%s objective_id=%s document_id=%s document_id=%s frame_position=%s frame_count=%s source_candidate_count=%s route_count=%s extractable_route_count=%s completed_frames=%s remaining_frames=%s",
                collection_id,
                frame.objective_id,
                frame.document_id,
                frame.document_id,
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

    def _build_deterministic_objective_route_record(
        self,
        *,
        objective_context: ResearchObjective | None,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence_role = self._route_candidate_evidence_role(
            objective_context=objective_context,
            candidate=candidate,
        )
        if evidence_role == "direct_support":
            role = "current_experimental_evidence"
            extractable = True
        elif evidence_role == "mediator_context":
            role = "characterization"
            extractable = False
        elif evidence_role == "background_context":
            role = "process_or_treatment"
            extractable = True
        else:
            role = "low_value_or_irrelevant"
            extractable = False
        return {
            "role": role,
            "extractable": extractable,
            "reason": "Deterministic route built after model routing failed.",
            "confidence": 0.62 if extractable else 0.55,
        }

    def _finalize_objective_route_record(
        self,
        *,
        record: dict[str, Any],
        frame: PaperAnalysisFrame,
        objective_context: ResearchObjective | None,
        route_candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        finalized = dict(record)
        if route_candidate.get("frame_status") == "excluded":
            finalized["role"] = "low_value_or_irrelevant"
            finalized["extractable"] = False
        evidence_role = self._route_candidate_evidence_role(
            objective_context=objective_context,
            candidate=route_candidate,
        )
        finalized = self._apply_route_evidence_role(
            record=finalized,
            evidence_role=evidence_role,
        )
        source_kind = str(route_candidate.get("source_kind") or "")
        source_ref = str(route_candidate.get("source_ref") or "")
        finalized.update(
            {
                "objective_id": frame.objective_id,
                "document_id": frame.document_id,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "table_schema": self._route_table_schema_record(
                    candidate=dict(route_candidate),
                ),
                "extractable": self._normalize_route_extractable(finalized),
            }
        )
        if source_kind == "table":
            table_schema = self._route_table_schema_record(candidate=dict(route_candidate))
            role = str(finalized.get("role") or "low_value_or_irrelevant")
            finalized.update(
                {
                    "column_roles": (
                        self._objective_context_hint_column_roles(
                            objective_context=objective_context,
                            hint_role=(
                                "result_table"
                                if role == "current_experimental_evidence"
                                else "condition_context"
                            ),
                            table_schema=table_schema,
                        )
                        if objective_context is not None
                        else {}
                    ),
                }
            )
        else:
            finalized.update({"column_roles": {}})
        return finalized

    def _append_objective_context_hint_routes(
        self,
        *,
        routes: list[EvidenceCandidate],
        seen: set[tuple[str, str, str, str, str]],
        frame: PaperAnalysisFrame,
        objective_context: ResearchObjective | None,
        routing_hints: tuple[SourceSelectionHint, ...],
        candidate_by_key: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        if objective_context is None:
            return
        for hint in routing_hints:
            table_id = hint.table_id
            if not table_id:
                continue
            document_id = hint.document_id
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
                EvidenceCandidate.from_mapping(
                    {
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "source_kind": "table",
                        "source_ref": table_id,
                        "role": role,
                        "extractable": True,
                        "reason": hint.reason
                        or "Selected from objective context routing hints.",
                        "table_schema": table_schema,
                        "column_roles": self._objective_context_hint_column_roles(
                            objective_context=objective_context,
                            hint_role=hint.role,
                            table_schema=table_schema,
                        ),
                        "join_plan": {},
                        "confidence": objective_context.confidence,
                    }
                )
            )

    def _route_prompt_objective_record(
        self,
        objective: ResearchObjective,
    ) -> dict[str, Any]:
        return {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": list(objective.material_scope),
            "variables": list(objective.variables),
            "outcomes": list(objective.outcomes),
            "mechanisms": list(objective.mechanisms),
            "constraints": list(objective.constraints),
            "requested_comparator": objective.requested_comparator,
        }

    def _route_prompt_paper_frame_record(
        self,
        frame: PaperAnalysisFrame,
    ) -> dict[str, Any]:
        return {
            "document_id": frame.document_id,
            "objective_id": frame.objective_id,
            "document_id": frame.document_id,
            "relevance": frame.relevance,
            "paper_role": frame.paper_role,
            "material_match": list(frame.material_match),
            "changed_variables": list(frame.changed_variables),
            "measured_property_scope": list(frame.measured_property_scope),
            "test_environment_scope": list(frame.test_environment_scope),
        }

    def _route_prompt_current_source(
        self,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        source_kind = str(candidate.get("source_kind") or "")
        if source_kind == "table":
            table_schema = (
                candidate.get("table_schema")
                if isinstance(candidate.get("table_schema"), dict)
                else {}
            )
            column_headers = (
                table_schema.get("column_headers")
                if isinstance(table_schema.get("column_headers"), (list, tuple))
                else ()
            )
            return {
                "source_kind": "table",
                "source_ref": str(candidate.get("source_ref") or ""),
                "frame_status": str(candidate.get("frame_status") or ""),
                "caption_text": str(candidate.get("caption_text") or "")[
                    :_ROUTE_PROMPT_TEXT_CHARS
                ],
                "heading_path": candidate.get("heading_path"),
                "column_headers": [
                    str(header)[:_OBJECTIVE_STATE_TEXT_CHARS]
                    for header in column_headers[:_ROUTE_PROMPT_HEADER_LIMIT]
                    if str(header).strip()
                ],
                "row_count": table_schema.get("row_count"),
                "col_count": table_schema.get("col_count"),
            }
        return {
            "source_kind": source_kind or "text_window",
            "source_ref": str(candidate.get("source_ref") or ""),
            "frame_status": str(candidate.get("frame_status") or ""),
            "section_label": candidate.get("section_label"),
            "block_type": candidate.get("block_type"),
            "text_hint": str(candidate.get("text") or "")[:_ROUTE_PROMPT_TEXT_CHARS],
        }

    def _objective_context_hint_route_role(
        self,
        hint: SourceSelectionHint,
    ) -> str | None:
        role = hint.role
        if role == "result_table":
            return "current_experimental_evidence"
        if role == "condition_context":
            return "process_or_treatment"
        return None

    def _objective_context_hint_column_roles(
        self,
        *,
        objective_context: ResearchObjective,
        hint_role: str,
        table_schema: dict[str, Any],
    ) -> dict[str, str]:
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
                objective_context.outcomes,
            ) or (
                hint_role == "result_table"
                and header_key == "relative_density"
                and any(
                    axis in {"densification", "microstructure"}
                    for axis in objective_context.outcomes
                )
            ):
                roles[header_text] = "target_property"
            elif self._objective_header_matches_any_axis(
                header_text,
                objective_context.variables,
            ) or self._objective_header_looks_process_variable(header_text):
                roles[header_text] = "process_variable"
        return roles

    def _append_ranked_text_hint_routes(
        self,
        *,
        routes: list[EvidenceCandidate],
        seen: set[tuple[str, str, str, str, str]],
        frame: PaperAnalysisFrame,
        objective_context: ResearchObjective | None,
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
            evidence_role = self._route_candidate_evidence_role(
                objective_context=objective_context,
                candidate=candidate,
            )
            if evidence_role == "irrelevant":
                continue
            role = self._text_hint_route_role(
                frame=frame,
                candidate=candidate,
                evidence_role=evidence_role,
            )
            extractable = evidence_role in {"direct_support", "background_context"}
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
                EvidenceCandidate.from_mapping(
                    {
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "source_kind": "text_window",
                        "source_ref": source_ref,
                        "role": role,
                        "extractable": extractable,
                        "reason": (
                            "High-scoring objective text candidate retained as "
                            f"{evidence_role}."
                        ),
                        "join_plan": {"evidence_role": evidence_role},
                        "table_schema": {},
                        "column_roles": {},
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
            phrase in text
            for phrase in (
                "compared with",
                "comparing",
                "decreased",
                "exhibited",
                "formation of",
                "formed",
                "higher than",
                "increased",
                "lower than",
                "observed",
                "resulted in",
                "resulted into",
            )
        ):
            priority += 8
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
        if any(
            phrase in text
            for phrase in (
                "aims to",
                "following conclusions can be drawn",
                "was investigated",
            )
        ):
            priority -= 8
        return priority

    def _text_hint_route_role(
        self,
        *,
        frame: PaperAnalysisFrame,
        candidate: dict[str, Any],
        evidence_role: str = "direct_support",
    ) -> str:
        if evidence_role == "background_context":
            return "process_or_treatment"
        if evidence_role == "mediator_context":
            return "characterization"
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

    def _route_candidate_evidence_role(
        self,
        *,
        objective_context: ResearchObjective | None,
        candidate: Mapping[str, Any],
    ) -> str:
        if objective_context is None:
            return "direct_support"
        text = self._route_candidate_text(candidate)
        if not text:
            return "irrelevant"
        target_axes = objective_context.outcomes
        mechanisms = objective_context.mechanisms
        context_axes = (
            *objective_context.material_scope,
            *objective_context.constraints,
        )
        variable_axes = objective_context.variables
        if self._route_text_mentions_any_axis(text, target_axes):
            return "direct_support"
        if self._route_text_mentions_any_axis(text, mechanisms):
            return "mediator_context"
        if self._route_text_mentions_any_axis(text, (*variable_axes, *context_axes)):
            return "background_context"
        return "irrelevant"

    def _apply_route_evidence_role(
        self,
        *,
        record: dict[str, Any],
        evidence_role: str,
    ) -> dict[str, Any]:
        updated = dict(record)
        join_plan = dict(updated.get("join_plan") or {})
        join_plan["evidence_role"] = evidence_role
        updated["join_plan"] = join_plan
        if evidence_role == "irrelevant":
            updated["role"] = "low_value_or_irrelevant"
            updated["extractable"] = False
        elif evidence_role == "mediator_context":
            updated["role"] = "characterization"
            updated["extractable"] = False
        elif evidence_role == "background_context":
            updated["role"] = "process_or_treatment"
        return updated

    def _route_candidate_text(self, candidate: Mapping[str, Any]) -> str:
        table_schema = candidate.get("table_schema")
        column_headers = (
            table_schema.get("column_headers")
            if isinstance(table_schema, Mapping)
            else candidate.get("column_headers")
        )
        return " ".join(
            str(value or "")
            for value in (
                candidate.get("section_label"),
                candidate.get("caption_text"),
                candidate.get("heading_path"),
                candidate.get("text"),
                " ".join(str(item) for item in column_headers or []),
            )
            if str(value or "").strip()
        )

    def _route_text_mentions_any_axis(
        self,
        text: str,
        axes: Iterable[str],
    ) -> bool:
        return any(self._source_text_mentions_axis(text, axis) for axis in axes)

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

    def _build_objective_evidence(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
        objectives: tuple[ResearchObjective, ...],
        paper_skims: tuple[PaperSkim, ...],
        objective_paper_frames: tuple[PaperAnalysisFrame, ...],
        objective_evidence_routes: tuple[EvidenceCandidate, ...],
        blocks_by_document_id: dict[str, list[Any]],
        tables_by_document_id: dict[str, list[Any]],
        document_trees_by_document_id: dict[str, SourceDocumentTree],
        table_cells_by_document_id: dict[str, list[Any]] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        objective_by_id = {
            objective.objective_id: objective
            for objective in objectives
        }
        frame_by_key = {
            (frame.objective_id, frame.document_id): frame
            for frame in objective_paper_frames
        }
        extractable_routes = self._tree_order_objective_routes(
            tuple(
                route
                for route in objective_evidence_routes
                if route.extractable and route.role != "low_value_or_irrelevant"
            ),
            document_trees_by_document_id=document_trees_by_document_id,
        )
        logger.info(
            "Research objective evidence extraction started collection_id=%s route_count=%s extractable_route_count=%s",
            collection_id,
            len(objective_evidence_routes),
            len(extractable_routes),
        )
        units: list[ExtractedEvidenceDraft] = []
        seen: set[str] = set()
        document_state_units: dict[tuple[str, str], list[ExtractedEvidenceDraft]] = {}
        llm_evidence_unavailable = False
        llm_table_repair_unavailable = False
        document_metadata = self._progress_document_metadata(
            document_trees_by_document_id=document_trees_by_document_id,
        )
        for route_position, route in enumerate(extractable_routes, start=1):
            route_document_metadata = document_metadata.get(route.document_id, {})
            self._notify_progress(
                progress_callback,
                phase="objective_evidence_extraction_started",
                current=route_position,
                total=len(extractable_routes),
                unit="selections",
                message="Extracting objective evidence from selected sources.",
                active_document_id=route.document_id,
                active_document_title=route_document_metadata.get("title"),
                active_source_filename=route_document_metadata.get("source_filename"),
                active_objective_id=route.objective_id,
            )
            objective = objective_by_id.get(route.objective_id)
            if objective is None:
                logger.info(
                    "Research objective evidence extraction route skipped collection_id=%s source_ref=%s reason=missing_objective route_position=%s route_count=%s",
                    collection_id,
                    route.source_ref,
                    route_position,
                    len(extractable_routes),
                )
                continue
            source = self._build_objective_route_source_payload(
                route=route,
                blocks=blocks_by_document_id.get(route.document_id, []),
                tables=tables_by_document_id.get(route.document_id, []),
                document_tree=document_trees_by_document_id.get(route.document_id),
                table_cells=(
                    table_cells_by_document_id.get(route.document_id, [])
                    if table_cells_by_document_id is not None else []
                ),
            )
            if not source:
                logger.info(
                    "Research objective evidence extraction route skipped collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s reason=missing_source route_position=%s route_count=%s",
                    collection_id,
                    route.source_ref,
                    route.objective_id,
                    route.document_id,
                    route.source_kind,
                    route.source_ref,
                    route_position,
                    len(extractable_routes),
                )
                continue
            objective_context = objective_by_id.get(route.objective_id)
            tree_position = self._route_tree_position(
                self._source_candidate_from_route(
                    route=route,
                    source=source,
                    document_tree=document_trees_by_document_id.get(route.document_id),
                )
            )
            prior_document_state = self._objective_document_state_payload(
                document_state_units.get((route.objective_id, route.document_id), [])
            )
            payload = {
                "collection_id": collection_id,
                "objective": self._route_prompt_objective_record(objective),
                "paper_frame": self._route_prompt_paper_frame_record(
                    frame_by_key[(route.objective_id, route.document_id)]
                )
                if (route.objective_id, route.document_id) in frame_by_key
                else {},
                "evidence_route": self._objective_evidence_prompt_route_record(route),
                "tree_position": tree_position,
                "document_state": prior_document_state,
                "source": self._objective_evidence_prompt_source(source),
            }
            source, table_repair_failed = self._repair_objective_table_source_if_needed(
                collection_id=collection_id,
                extractor=extractor,
                route=route,
                source=source,
                llm_unavailable=llm_table_repair_unavailable,
            )
            llm_table_repair_unavailable = (
                llm_table_repair_unavailable or table_repair_failed
            )
            payload["source"] = self._objective_evidence_prompt_source(source)
            route_unit_start = len(units)
            route_records = self._objective_table_matrix_evidence_records(
                route=route,
                source=source,
                objective_context=objective_context,
            )
            needs_structural_repair = (
                self._objective_table_source_needs_llm_structural_repair(
                    route=route,
                    source=source,
                )
                and not (
                    source.get("table_matrix_structural_repair_applied")
                    and route_records
                )
            )
            if (
                (not route_records or needs_structural_repair)
                and not self._objective_table_route_should_skip_llm_fallback(route)
                and not llm_evidence_unavailable
            ):
                try:
                    parsed = extractor.extract_objective_evidence(payload)
                except Exception as exc:
                    llm_evidence_unavailable = isinstance(exc, OpenAIError)
                    logger.exception(
                        "Research objective evidence extraction route failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s completed_routes=%s remaining_routes=%s provider_unavailable=%s",
                        collection_id,
                        route.source_ref,
                        route.objective_id,
                        route.document_id,
                        route.source_kind,
                        route.source_ref,
                        route_position,
                        len(extractable_routes),
                        route_position - 1,
                        max(len(extractable_routes) - route_position, 0),
                        llm_evidence_unavailable,
                    )
                    if not route_records:
                        continue
                else:
                    llm_route_records = tuple(
                        record
                        for item in parsed.extractions
                        for record in self._objective_evidence_records_from_extracted(
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
                unit = ExtractedEvidenceDraft.from_mapping(record)
                if not self._objective_evidence_has_payload(unit):
                    continue
                if unit.evidence_id in seen:
                    continue
                seen.add(unit.evidence_id)
                units.append(unit)
                document_state_units.setdefault(
                    (unit.objective_id, unit.document_id),
                    [],
                ).append(unit)
            logger.info(
                "Research objective evidence extraction route finished collection_id=%s source_ref=%s objective_id=%s document_id=%s source_kind=%s source_ref=%s route_position=%s route_count=%s extractions=%s completed_routes=%s remaining_routes=%s",
                collection_id,
                route.source_ref,
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
            objectives=objectives,
            objective_paper_frames=objective_paper_frames,
            blocks_by_document_id=blocks_by_document_id,
        ):
            if not self._objective_evidence_has_payload(unit):
                continue
            if unit.evidence_id in seen:
                continue
            seen.add(unit.evidence_id)
            units.append(unit)
        logger.info(
            "Research objective evidence extraction finished collection_id=%s objective_extractions=%s",
            collection_id,
            len(units),
        )
        enriched_units = self._enrich_objective_scope_context(
            tuple(units),
            paper_skims=paper_skims,
        )
        bound_units = self._bind_objective_result_process_context(enriched_units)
        comparison_units = self._build_objective_pairwise_comparison_units(
            bound_units,
            objectives=objectives,
        )
        if comparison_units:
            logger.info(
                "Research objective pairwise comparison units generated collection_id=%s comparison_unit_count=%s",
                collection_id,
                len(comparison_units),
            )
        return (*bound_units, *comparison_units)

    @staticmethod
    def _enrich_objective_scope_context(
        units: tuple[ExtractedEvidenceDraft, ...],
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        skim_by_document_id = {item.document_id: item for item in paper_skims}
        enriched: list[ExtractedEvidenceDraft] = []
        for unit in units:
            paper_skim = skim_by_document_id.get(unit.document_id)
            context = unit.scientific_context.to_record()
            if not context["material"]:
                material_values = (
                    paper_skim.candidate_materials
                    if paper_skim and paper_skim.candidate_materials
                    else ()
                )
                context["material"] = [
                    {"name": "material", "value": value, "unit": None}
                    for value in material_values
                ]
            if paper_skim and paper_skim.candidate_processes:
                process_identity_names = {
                    "fabrication process",
                    "manufacturing process",
                    "process",
                    "processing method",
                    "production process",
                }
                has_process_identity = any(
                    " ".join(
                        str(item.get("name") or "")
                        .casefold()
                        .replace("_", " ")
                        .split()
                    )
                    in process_identity_names
                    for item in context["process"]
                )
                if not has_process_identity:
                    context["process"] = [
                        *context["process"],
                        *(
                            {
                                "name": "process",
                                "value": value,
                                "unit": None,
                            }
                            for value in paper_skim.candidate_processes
                        ),
                    ]
            if context == unit.scientific_context.to_record():
                enriched.append(unit)
                continue
            record = unit.to_record()
            record["scientific_context"] = context
            enriched.append(ExtractedEvidenceDraft.from_mapping(record))
        return tuple(enriched)

    def _objective_table_route_should_skip_llm_fallback(
        self,
        route: EvidenceCandidate,
    ) -> bool:
        return route.source_kind == "table"

    def _repair_objective_table_source_if_needed(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
        route: EvidenceCandidate,
        source: dict[str, Any],
        llm_unavailable: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        if llm_unavailable:
            return source, False
        if not self._objective_table_source_needs_llm_structural_repair(
            route=route,
            source=source,
        ):
            return source, False
        repair_payload = self._build_objective_table_matrix_repair_payload(
            route=route,
            source=source,
        )
        try:
            parsed = extractor.repair_table_matrix(repair_payload)
        except Exception:
            logger.exception(
                "Research objective table matrix repair failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_ref=%s",
                collection_id,
                route.source_ref,
                route.objective_id,
                route.document_id,
                route.source_ref,
            )
            return source, True
        repaired_matrix = self._validated_objective_repaired_table_matrix(
            source=source,
            repaired_table_matrix=getattr(parsed, "repaired_table_matrix", None),
        )
        if not repaired_matrix:
            return source, False
        original_matrix = self._normalized_objective_table_matrix(
            source.get("table_matrix")
        )
        repaired_matrix, residual_repairs = (
            self._cleanup_objective_repaired_table_matrix_residual_fragments(
                original_matrix=original_matrix,
                repaired_matrix=repaired_matrix,
                column_headers=source.get("column_headers", ()),
            )
        )
        if repaired_matrix == original_matrix:
            return source, False
        repaired_source = dict(source)
        repaired_source["raw_table_matrix"] = source.get("table_matrix", [])
        repaired_source["table_matrix"] = repaired_matrix
        repaired_source["table_matrix_structural_repair_applied"] = (
            not self._objective_table_matrix_has_structural_fragments(
                repaired_matrix
            )
        )
        repairs = getattr(parsed, "repairs", None)
        repair_records = []
        if repairs:
            repair_records.extend(
                repair_item.model_dump()
                if hasattr(repair_item, "model_dump")
                else repair_item
                for repair_item in repairs
            )
        repair_records.extend(residual_repairs)
        if repair_records:
            repaired_source["table_matrix_repairs"] = repair_records
        warnings = getattr(parsed, "warnings", None)
        if warnings:
            repaired_source["table_matrix_repair_warnings"] = [
                str(warning)
                for warning in warnings
                if str(warning).strip()
            ]
        return repaired_source, False

    def _build_objective_table_matrix_repair_payload(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        compact_source = {
            "source_kind": source.get("source_kind"),
            "source_ref": source.get("source_ref"),
            "document_id": source.get("document_id"),
            "page": source.get("page"),
            "caption_text": source.get("caption_text"),
            "heading_path": source.get("heading_path"),
            "column_headers": [
                str(value)
                for value in source.get("column_headers", ())
                if str(value).strip()
            ],
            "table_matrix": self._normalized_objective_table_matrix(
                source.get("table_matrix")
            ),
            "table_cells": self._compact_objective_table_cells_for_repair(source),
        }
        return {
            "table_role": route.role,
            "repair_focus": [
                "repair parser-split cells",
                "preserve table width",
                "preserve numeric result cells exactly",
            ],
            "source": {
                key: value
                for key, value in compact_source.items()
                if value not in (None, "", [], {})
            },
        }

    def _compact_objective_table_cells_for_repair(
        self,
        source: dict[str, Any],
    ) -> list[dict[str, Any]]:
        cells = source.get("table_cells")
        if not isinstance(cells, list):
            return []
        fragmented_columns = {
            cell.get("col_index")
            for cell in cells
            if isinstance(cell, dict)
            and self._objective_cell_text_looks_structurally_fragmented(
                str(cell.get("cell_text") or "")
            )
        }
        if not fragmented_columns:
            return []
        compact_cells: list[dict[str, Any]] = []
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            col_index = cell.get("col_index")
            if col_index not in fragmented_columns and col_index != 0:
                continue
            compact_cells.append(
                {
                    "row_index": cell.get("row_index"),
                    "col_index": col_index,
                    "header_path": cell.get("header_path"),
                    "cell_text": str(cell.get("cell_text") or ""),
                }
            )
        return compact_cells

    def _validated_objective_repaired_table_matrix(
        self,
        *,
        source: dict[str, Any],
        repaired_table_matrix: Any,
    ) -> list[list[str]]:
        if not isinstance(repaired_table_matrix, list) or not repaired_table_matrix:
            return []
        headers = [
            str(header).strip()
            for header in source.get("column_headers", ())
            if str(header).strip()
        ]
        expected_width = len(headers)
        repaired_rows: list[list[str]] = []
        for row in repaired_table_matrix:
            if not isinstance(row, (list, tuple)):
                return []
            repaired_row = [str(cell).strip() for cell in row]
            if expected_width and len(repaired_row) != expected_width:
                return []
            repaired_rows.append(repaired_row)
        if expected_width and not self._objective_row_matches_headers(
            tuple(repaired_rows[0]),
            tuple(headers),
        ):
            repaired_rows.insert(0, headers)
        return repaired_rows

    def _normalized_objective_table_matrix(self, value: Any) -> list[list[str]]:
        if not isinstance(value, list):
            return []
        return [
            [str(cell).strip() for cell in row]
            for row in value
            if isinstance(row, (list, tuple))
        ]

    def _cleanup_objective_repaired_table_matrix_residual_fragments(
        self,
        *,
        original_matrix: list[list[str]],
        repaired_matrix: list[list[str]],
        column_headers: Any,
    ) -> tuple[list[list[str]], list[dict[str, Any]]]:
        if not original_matrix or not repaired_matrix:
            return repaired_matrix, []
        headers = [str(value).strip() for value in column_headers or ()]
        cleaned_matrix: list[list[str]] = []
        repairs: list[dict[str, Any]] = []
        for row_index, repaired_row in enumerate(repaired_matrix):
            original_row = (
                original_matrix[row_index]
                if row_index < len(original_matrix)
                else []
            )
            cleaned_row: list[str] = []
            for col_index, repaired_cell in enumerate(repaired_row):
                original_cell = (
                    original_row[col_index]
                    if col_index < len(original_row)
                    else ""
                )
                cleaned_cell = self._cleanup_objective_repaired_cell_residual_prefix(
                    original_cell=original_cell,
                    repaired_cell=repaired_cell,
                )
                cleaned_row.append(cleaned_cell)
                if cleaned_cell != repaired_cell:
                    repairs.append(
                        {
                            "row_index": row_index,
                            "column": (
                                headers[col_index]
                                if col_index < len(headers)
                                else str(col_index)
                            ),
                            "before": repaired_cell,
                            "after": cleaned_cell,
                            "reason": (
                                "Removed a leading closing-fragment prefix that "
                                "belonged to the previous parser-split row label."
                            ),
                        }
                    )
            cleaned_matrix.append(cleaned_row)
        return cleaned_matrix, repairs

    def _cleanup_objective_repaired_cell_residual_prefix(
        self,
        *,
        original_cell: str,
        repaired_cell: str,
    ) -> str:
        original = " ".join(str(original_cell or "").split())
        repaired = " ".join(str(repaired_cell or "").split())
        if not original or not repaired:
            return repaired_cell
        if not self._objective_cell_text_looks_structurally_fragmented(original):
            return repaired_cell
        match = re.match(r"^([^\s()[\]{}|]{1,32}\))\s+(.+)$", original)
        if match is None:
            return repaired_cell
        prefix = f"{match.group(1)} "
        original_remainder = match.group(2).strip()
        if not self._objective_cell_text_looks_structurally_fragmented(
            original_remainder
        ):
            return repaired_cell
        if not repaired.startswith(prefix):
            return repaired_cell
        candidate = repaired[len(prefix):].strip()
        if not candidate:
            return repaired_cell
        if self._objective_cell_text_looks_structurally_fragmented(candidate):
            return repaired_cell
        return candidate

    def _objective_table_matrix_has_structural_fragments(
        self,
        table_matrix: list[list[str]],
    ) -> bool:
        return any(
            self._objective_cell_text_looks_structurally_fragmented(cell)
            for row in table_matrix
            for cell in row
        )

    def _objective_table_source_needs_llm_structural_repair(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
    ) -> bool:
        if route.source_kind != "table":
            return False
        if route.role not in {"current_experimental_evidence", "process_or_treatment"}:
            return False
        matrix = source.get("table_matrix")
        if (
            isinstance(matrix, list)
            and self._objective_table_matrix_has_structural_fragments(
                self._normalized_objective_table_matrix(matrix)
            )
        ):
            return True
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
        return deterministic_records or llm_records

    def _build_objective_method_family_test_condition_units(
        self,
        *,
        objectives: tuple[ResearchObjective, ...],
        objective_paper_frames: tuple[PaperAnalysisFrame, ...],
        blocks_by_document_id: dict[str, list[Any]],
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        context_by_objective_id = {
            context.objective_id: context
            for context in objectives
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
                        "evidence_id": self._objective_method_family_unit_id(
                            objective_id=frame.objective_id,
                            document_id=frame.document_id,
                            family=family,
                        ),
                        "objective_id": frame.objective_id,
                        "document_id": frame.document_id,
                        "evidence_role": "condition_context",
                        "selection_reason": quote,
                        "changed_variables": [],
                        "comparison": None,
                        "reported_result": None,
                        "attribution_scope": "not_attributable",
                        "scientific_context": {
                            "material": [],
                            "sample": [],
                            "process": [],
                            "test": [
                                {"name": "method_family", "value": family},
                                *(
                                    {"name": key, "value": value}
                                    for key, value in payload.items()
                                ),
                            ],
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
        return tuple(ExtractedEvidenceDraft.from_mapping(record) for record in records)

    def _objective_method_families_for_context(
        self,
        objective_context: ResearchObjective | None,
    ) -> tuple[str, ...]:
        if objective_context is None:
            return ()
        families: list[str] = []
        for axis in objective_context.outcomes:
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

    def _bind_objective_result_process_context(
        self,
        units: tuple[ExtractedEvidenceDraft, ...],
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        process_context_by_sample: dict[
            tuple[str, str, str], ExtractedEvidenceDraft
        ] = {}
        process_context_scopes: set[tuple[str, str]] = set()
        conflicting_samples: set[tuple[str, str, str]] = set()
        for unit in units:
            if (
                unit.evidence_role != "condition_context"
                or not unit.scientific_context.process
            ):
                continue
            sample_identity = self._objective_explicit_sample_identity(unit)
            if not sample_identity:
                continue
            key = (unit.objective_id, unit.document_id, sample_identity)
            process_context_scopes.add((unit.objective_id, unit.document_id))
            existing = process_context_by_sample.get(key)
            if existing is None:
                process_context_by_sample[key] = unit
                continue
            if self._objective_process_context_signature(
                existing
            ) != self._objective_process_context_signature(unit):
                conflicting_samples.add(key)

        bound: list[ExtractedEvidenceDraft] = []
        for unit in units:
            comparison = unit.comparison
            scope = (unit.objective_id, unit.document_id)
            if (
                unit.source_kind == "text_window"
                and unit.reported_result is not None
                and comparison is not None
                and unit.attribution_scope in {"isolated_effect", "joint_effect"}
                and scope in process_context_scopes
            ):
                baseline_key = (
                    unit.objective_id,
                    unit.document_id,
                    comparison.baseline_label.casefold(),
                )
                target_key = (
                    unit.objective_id,
                    unit.document_id,
                    comparison.target_label.casefold(),
                )
                baseline_context = process_context_by_sample.get(baseline_key)
                target_context = process_context_by_sample.get(target_key)
                groups_are_grounded = bool(
                    baseline_context is not None
                    and target_context is not None
                    and baseline_key not in conflicting_samples
                    and target_key not in conflicting_samples
                )
                if not groups_are_grounded:
                    payload = unit.to_record()
                    payload["changed_variables"] = []
                    comparison_payload = comparison.to_record()
                    comparison_payload.update(
                        {
                            "comparable": False,
                            "incomparability_reasons": [
                                "comparison groups do not bind to source process conditions"
                            ],
                        }
                    )
                    payload["comparison"] = comparison_payload
                    payload["attribution_scope"] = "not_attributable"
                    payload["resolution_status"] = "partial"
                    bound.append(ExtractedEvidenceDraft.from_mapping(payload))
                    continue

                baseline_process = {
                    self._normalize_property_label(item.name)
                    or self._objective_column_key(item.name): item
                    for item in baseline_context.scientific_context.process
                }
                target_process = {
                    self._normalize_property_label(item.name)
                    or self._objective_column_key(item.name): item
                    for item in target_context.scientific_context.process
                }
                changed_variables: list[dict[str, Any]] = []
                incomparability_reasons: list[str] = []
                for key in sorted(set(baseline_process) | set(target_process)):
                    baseline_attribute = baseline_process.get(key)
                    target_attribute = target_process.get(key)
                    if baseline_attribute is None or target_attribute is None:
                        name = (
                            target_attribute.name
                            if target_attribute is not None
                            else baseline_attribute.name
                        )
                        incomparability_reasons.append(
                            "process comparison is missing one group value for "
                            f"{name}"
                        )
                    else:
                        name = target_attribute.name
                        if (
                            baseline_attribute is not None
                            and target_attribute is not None
                            and baseline_attribute.value == target_attribute.value
                            and baseline_attribute.unit == target_attribute.unit
                        ):
                            continue
                    changed_variables.append(
                        {
                            "name": name,
                            "baseline_value": (
                                baseline_attribute.value
                                if baseline_attribute is not None
                                else None
                            ),
                            "target_value": (
                                target_attribute.value
                                if target_attribute is not None
                                else None
                            ),
                            "unit": (
                                target_attribute.unit
                                if target_attribute is not None
                                else baseline_attribute.unit
                            ),
                        }
                    )
                if not changed_variables:
                    incomparability_reasons.append(
                        "bound process conditions do not contain a changed variable"
                    )
                comparable = not incomparability_reasons
                payload = unit.to_record()
                payload["changed_variables"] = changed_variables
                payload["comparison"] = {
                    "baseline_label": comparison.baseline_label,
                    "target_label": comparison.target_label,
                    "axis_names": [
                        item["name"] for item in changed_variables
                    ] or list(comparison.axis_names),
                    "comparable": comparable,
                    "incomparability_reasons": incomparability_reasons,
                }
                payload["attribution_scope"] = (
                    "not_attributable"
                    if not comparable
                    else (
                        "isolated_effect"
                        if len(changed_variables) == 1
                        else "joint_effect"
                    )
                )
                scientific_context = unit.scientific_context.to_record()
                scientific_context["process"] = self._objective_common_pairwise_context(
                    baseline_context,
                    target_context,
                )["process"]
                payload["scientific_context"] = scientific_context
                payload["source_refs"] = list(
                    self._dedupe_objective_source_refs(
                        (
                            unit.source_refs,
                            baseline_context.source_refs,
                            target_context.source_refs,
                        )
                    )
                )
                payload["confidence"] = min(
                    unit.confidence,
                    baseline_context.confidence,
                    target_context.confidence,
                )
                bound.append(ExtractedEvidenceDraft.from_mapping(payload))
                continue
            if (
                unit.reported_result is None
                or unit.attribution_scope != "descriptive_only"
                or unit.scientific_context.process
            ):
                bound.append(unit)
                continue
            sample_identity = self._objective_explicit_sample_identity(unit)
            key = (unit.objective_id, unit.document_id, sample_identity)
            process_context = process_context_by_sample.get(key)
            if (
                not sample_identity
                or key in conflicting_samples
                or process_context is None
            ):
                bound.append(unit)
                continue
            payload = unit.to_record()
            scientific_context = unit.scientific_context.to_record()
            scientific_context["process"] = [
                item.to_record()
                for item in process_context.scientific_context.process
            ]
            payload["scientific_context"] = scientific_context
            payload["source_refs"] = list(
                self._dedupe_objective_source_refs(
                    (unit.source_refs, process_context.source_refs)
                )
            )
            payload["confidence"] = min(unit.confidence, process_context.confidence)
            bound.append(ExtractedEvidenceDraft.from_mapping(payload))
        return tuple(bound)

    def _objective_explicit_sample_identity(
        self,
        unit: ExtractedEvidenceDraft,
    ) -> str | None:
        sample_values = {
            item.name: item.value
            for item in unit.scientific_context.sample
            if item.name != "sample_number"
        }
        return self._objective_sample_identity_key(sample_values) or None

    def _objective_process_context_signature(
        self,
        unit: ExtractedEvidenceDraft,
    ) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            sorted(
                (
                    item.name.casefold(),
                    str(item.value).casefold(),
                    str(item.unit or "").casefold(),
                )
                for item in unit.scientific_context.process
            )
        )

    def _build_objective_pairwise_comparison_units(
        self,
        units: tuple[ExtractedEvidenceDraft, ...],
        *,
        objectives: tuple[ResearchObjective, ...],
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        del objectives
        results_by_scope: dict[
            tuple[str, str, str, str | None, str, str],
            list[ExtractedEvidenceDraft],
        ] = {}
        for unit in units:
            result = unit.reported_result
            if result is None or unit.attribution_scope != "descriptive_only":
                continue
            if self._coerce_number(result.value) is None or not unit.source_refs:
                continue
            primary_source = unit.source_refs[0]
            results_by_scope.setdefault(
                (
                    unit.objective_id,
                    unit.document_id,
                    result.outcome,
                    result.unit,
                    str(primary_source.get("source_kind") or ""),
                    str(primary_source.get("source_ref") or ""),
                ),
                [],
            ).append(unit)

        generated: list[ExtractedEvidenceDraft] = []
        generated_by_scope: dict[tuple[str, str], int] = {}
        for measurements in results_by_scope.values():
            for baseline_index, baseline in enumerate(measurements):
                for target in measurements[baseline_index + 1 :]:
                    scope_key = (target.objective_id, target.document_id)
                    if generated_by_scope.get(scope_key, 0) >= _OBJECTIVE_PAIRWISE_SCOPE_LIMIT:
                        break
                    baseline_process = {
                        item.name.casefold(): item
                        for item in baseline.scientific_context.process
                    }
                    target_process = {
                        item.name.casefold(): item
                        for item in target.scientific_context.process
                    }
                    changed_variables: list[dict[str, Any]] = []
                    changed_axis_names: list[str] = []
                    incomparability_reasons: list[str] = []
                    for key in sorted(set(baseline_process) | set(target_process)):
                        baseline_attribute = baseline_process.get(key)
                        target_attribute = target_process.get(key)
                        baseline_value = (
                            baseline_attribute.value if baseline_attribute else None
                        )
                        target_value = target_attribute.value if target_attribute else None
                        if baseline_value == target_value:
                            continue
                        name = (
                            target_attribute.name
                            if target_attribute is not None
                            else baseline_attribute.name
                        )
                        changed_axis_names.append(name)
                        if baseline_attribute is None or target_attribute is None:
                            incomparability_reasons.append(
                                "process comparison is missing one group value for "
                                f"{name}: {baseline_value!s} vs {target_value!s}"
                            )
                        changed_variables.append(
                            {
                                "name": name,
                                "baseline_value": baseline_value,
                                "target_value": target_value,
                                "unit": (
                                    target_attribute.unit
                                    if target_attribute is not None
                                    else baseline_attribute.unit
                                ),
                            }
                        )
                    condition_axis_names: list[str] = []
                    for context_name in ("material", "test"):
                        baseline_attributes = {
                            item.name.casefold(): item
                            for item in getattr(
                                baseline.scientific_context, context_name
                            )
                        }
                        target_attributes = {
                            item.name.casefold(): item
                            for item in getattr(target.scientific_context, context_name)
                        }
                        for key in sorted(
                            set(baseline_attributes) | set(target_attributes)
                        ):
                            baseline_attribute = baseline_attributes.get(key)
                            target_attribute = target_attributes.get(key)
                            baseline_value = (
                                baseline_attribute.value if baseline_attribute else None
                            )
                            target_value = (
                                target_attribute.value if target_attribute else None
                            )
                            if baseline_value == target_value:
                                continue
                            name = (
                                target_attribute.name
                                if target_attribute is not None
                                else baseline_attribute.name
                            )
                            condition_axis_names.append(name)
                            incomparability_reasons.append(
                                f"{context_name} condition differs for {name}: "
                                f"{baseline_value!s} vs {target_value!s}"
                            )

                    baseline_sample = {
                        item.name.casefold(): item
                        for item in baseline.scientific_context.sample
                    }
                    target_sample = {
                        item.name.casefold(): item
                        for item in target.scientific_context.sample
                    }
                    for key in sorted(set(baseline_sample) | set(target_sample)):
                        baseline_attribute = baseline_sample.get(key)
                        target_attribute = target_sample.get(key)
                        baseline_value = (
                            baseline_attribute.value if baseline_attribute else None
                        )
                        target_value = target_attribute.value if target_attribute else None
                        if self._objective_table_column_is_sample_key(
                            self._objective_column_key(key)
                        ) and self._objective_sample_values_are_opaque_identifiers(
                            baseline_value,
                            target_value,
                        ):
                            continue
                        if baseline_value == target_value:
                            continue
                        name = (
                            target_attribute.name
                            if target_attribute is not None
                            else baseline_attribute.name
                        )
                        condition_axis_names.append(name)
                        incomparability_reasons.append(
                            f"sample condition differs for {name}: "
                            f"{baseline_value!s} vs {target_value!s}"
                        )

                    axis_names = tuple(
                        dict.fromkeys((*changed_axis_names, *condition_axis_names))
                    )
                    if not axis_names:
                        continue
                    baseline_sample_values = {
                        item.name: item.value
                        for item in baseline.scientific_context.sample
                    }
                    target_sample_values = {
                        item.name: item.value
                        for item in target.scientific_context.sample
                    }
                    baseline_label = (
                        self._objective_sample_identity_key(baseline_sample_values)
                        or baseline.evidence_id
                    )
                    target_label = (
                        self._objective_sample_identity_key(target_sample_values)
                        or target.evidence_id
                    )
                    comparable = not incomparability_reasons and bool(
                        changed_variables
                    )
                    attribution_scope = (
                        "not_attributable"
                        if not comparable
                        else (
                            "isolated_effect"
                            if len(changed_variables) == 1
                            else "joint_effect"
                        )
                    )
                    baseline_result = baseline.reported_result
                    target_result = target.reported_result
                    if baseline_result is None or target_result is None:
                        continue
                    baseline_value = self._coerce_number(baseline_result.value)
                    target_value = self._coerce_number(target_result.value)
                    if baseline_value is None or target_value is None:
                        continue
                    direction = (
                        "increase"
                        if target_value > baseline_value
                        else "decrease"
                        if target_value < baseline_value
                        else "no_change"
                    )
                    source_refs = self._dedupe_objective_source_refs(
                        (baseline.source_refs, target.source_refs)
                    )
                    identity = json.dumps(
                        [
                            baseline.evidence_id,
                            target.evidence_id,
                            axis_names,
                            target_result.outcome,
                        ],
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                    generated.append(
                        ExtractedEvidenceDraft.from_mapping(
                            {
                                "evidence_id": (
                                    "oeu_cmp_"
                                    + sha1(identity.encode("utf-8")).hexdigest()[:16]
                                ),
                                "objective_id": target.objective_id,
                                "document_id": target.document_id,
                                "source_kind": target.source_kind,
                                "source_ref": target.source_ref,
                                "evidence_role": "direct_result",
                                "selection_reason": (
                                    "Deterministic comparison of rows from the same "
                                    "result table."
                                ),
                                "selection_status": "extracted",
                                "changed_variables": changed_variables,
                                "comparison": {
                                    "baseline_label": baseline_label,
                                    "target_label": target_label,
                                    "axis_names": list(axis_names),
                                    "comparable": comparable,
                                    "incomparability_reasons": (
                                        incomparability_reasons
                                    ),
                                },
                                "reported_result": {
                                    "outcome": target_result.outcome,
                                    "value": target_result.value,
                                    "unit": target_result.unit,
                                    "direction": direction,
                                    "result_text": (
                                        f"{target_result.outcome} changed from "
                                        f"{baseline_result.value!s} to "
                                        f"{target_result.value!s}"
                                        + (
                                            f" {target_result.unit}"
                                            if target_result.unit
                                            else ""
                                        )
                                        + f" between {baseline_label} and "
                                        f"{target_label}."
                                    ),
                                },
                                "attribution_scope": attribution_scope,
                                "scientific_context": (
                                    self._objective_common_pairwise_context(
                                        baseline,
                                        target,
                                    )
                                ),
                                "source_refs": source_refs,
                                "evidence_anchor_ids": list(
                                    dict.fromkeys(
                                        (
                                            *baseline.evidence_anchor_ids,
                                            *target.evidence_anchor_ids,
                                        )
                                    )
                                ),
                                "resolution_status": "resolved",
                                "confidence": min(
                                    baseline.confidence, target.confidence
                                ),
                            }
                        )
                    )
                    generated_by_scope[scope_key] = (
                        generated_by_scope.get(scope_key, 0) + 1
                    )
        return tuple(generated)


    def _objective_common_pairwise_context(
        self,
        baseline: ExtractedEvidenceDraft,
        target: ExtractedEvidenceDraft,
    ) -> dict[str, list[dict[str, Any]]]:
        context: dict[str, list[dict[str, Any]]] = {}
        for context_name in ("material", "sample", "process", "test"):
            baseline_attributes = {
                item.name.casefold(): item
                for item in getattr(baseline.scientific_context, context_name)
            }
            target_attributes = {
                item.name.casefold(): item
                for item in getattr(target.scientific_context, context_name)
            }
            common: list[dict[str, Any]] = []
            for key in sorted(set(baseline_attributes) & set(target_attributes)):
                baseline_attribute = baseline_attributes[key]
                target_attribute = target_attributes[key]
                if (
                    baseline_attribute.value != target_attribute.value
                    or baseline_attribute.unit != target_attribute.unit
                ):
                    continue
                if context_name == "sample" and self._objective_table_column_is_sample_key(
                    self._objective_column_key(target_attribute.name)
                ) and self._objective_sample_values_are_opaque_identifiers(
                    baseline_attribute.value,
                    target_attribute.value,
                ):
                    continue
                common.append(target_attribute.to_record())
            context[context_name] = common
        return context


    def _objective_sample_identity_key(
        self,
        sample_attributes: dict[str, Any],
    ) -> str:
        preferred_keys = (
            "sample_number",
            "sample_no",
            "sample_id",
            "sample",
            "specimen_id",
            "specimen",
            "specimens",
            "case",
            "id",
            "no",
            "printed_316l",
            "condition_number",
            "condition_no",
            "condition",
        )
        normalized_items = {
            self._objective_column_key(key): str(value).strip()
            for key, value in sample_attributes.items()
            if str(value).strip()
        }
        for column_key in preferred_keys:
            value_text = normalized_items.get(column_key)
            if value_text:
                return value_text.casefold()
        return "|".join(
            f"{self._objective_column_key(key)}={str(value).strip().casefold()}"
            for key, value in sorted(sample_attributes.items())
            if str(value).strip()
        )


    def _build_objective_route_source_payload(
        self,
        *,
        route: EvidenceCandidate,
        blocks: list[Any],
        tables: list[Any],
        document_tree: SourceDocumentTree | None = None,
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
            source_block_id = self._route_text_block_id(
                route=route,
                document_tree=document_tree,
            )
            block = next(
                (
                    candidate
                    for candidate in blocks
                    if str(getattr(candidate, "block_id", "") or "") == source_block_id
                ),
                None,
            )
            if block is None:
                return self._build_objective_tree_text_source_payload(
                    route=route,
                    document_tree=document_tree,
                )
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

    def _route_text_block_id(
        self,
        *,
        route: EvidenceCandidate,
        document_tree: SourceDocumentTree | None,
    ) -> str:
        if document_tree is None:
            return route.source_ref
        node = self._tree_node_for_route_source(
            document_tree=document_tree,
            source_ref_kind="block",
            source_ref_id=route.source_ref,
        )
        if node is None:
            return route.source_ref
        source_ref_id = str(getattr(node, "source_ref_id", "") or "").strip()
        return source_ref_id or route.source_ref

    def _build_objective_tree_text_source_payload(
        self,
        *,
        route: EvidenceCandidate,
        document_tree: SourceDocumentTree | None,
    ) -> dict[str, Any]:
        if document_tree is None:
            return {}
        node = self._tree_node_for_route_source(
            document_tree=document_tree,
            source_ref_kind="block",
            source_ref_id=route.source_ref,
        )
        if node is None or self._tree_node_in_reference_branch(document_tree, node):
            return {}
        text = str(getattr(node, "text", "") or "").strip()
        if not text:
            return {}
        section_path = self._tree_node_section_path(
            document_tree=document_tree,
            node=node,
        )
        return {
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "document_id": route.document_id,
            "page": getattr(node, "page_start", None),
            "block_type": self._route_text_node_block_type(node),
            "heading_path": " > ".join(section_path) if section_path else None,
            "text": text[:_OBJECTIVE_EVIDENCE_TEXT_CHARS],
        }

    def _objective_table_matrix_evidence_records(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
        objective_context: ResearchObjective | None,
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
            process_records = self._objective_process_table_matrix_records(
                route=route,
                source=source,
                objective_context=objective_context,
                headers=headers,
                data_rows=data_rows,
            )
            recover_result_columns = bool(
                self._objective_route_result_columns(
                    route,
                    objective_context=objective_context,
                )
                or (
                    objective_context is not None
                    and objective_context.outcomes
                )
            )
            result_records = (
                self._objective_result_table_matrix_records(
                    route=route,
                    source=source,
                    objective_context=objective_context,
                    headers=headers,
                    data_rows=data_rows,
                )
                if recover_result_columns
                else ()
            )
            return (*process_records, *result_records)
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
        route: EvidenceCandidate,
        source: dict[str, Any],
        objective_context: ResearchObjective | None,
        headers: tuple[str, ...],
        data_rows: tuple[tuple[int, tuple[str, ...]], ...],
    ) -> tuple[dict[str, Any], ...]:
        result_columns = self._objective_route_result_columns(
            route,
            objective_context=objective_context,
        )
        if objective_context is not None:
            result_columns.update(
                header
                for header in headers
                if not self._objective_value_column_is_non_result(header)
                and self._objective_result_column_matches_target(
                    header,
                    objective_context=objective_context,
                )
            )
        if not result_columns:
            return ()

        records: list[dict[str, Any]] = []
        for row_index, row in data_rows:
            row_values = self._objective_table_row_values(headers=headers, row=row)
            row_attributes = self._objective_table_row_attributes(
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
            row_attributes = self._objective_table_row_attributes_with_sample_number(
                row_attributes=row_attributes,
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
                outcome = (
                    self._normalize_objective_unit_property(
                        property_source,
                        objective_context=objective_context,
                    )
                    or property_source
                )
                numeric_value = self._coerce_result_cell_number(raw_value)
                records.append(
                    {
                        "evidence_id": self._objective_matrix_unit_id(
                            route=route,
                            row_index=row_index,
                            column=result_column,
                        ),
                        "objective_id": route.objective_id,
                        "document_id": route.document_id,
                        "evidence_role": "direct_result",
                        "changed_variables": [],
                        "comparison": None,
                        "reported_result": {
                            "outcome": outcome,
                            "value": numeric_value,
                            "unit": unit,
                            "direction": "unknown",
                            "result_text": (
                                f"{outcome} = {raw_value}"
                                + (f" {unit}" if unit else "")
                            ),
                        },
                        "attribution_scope": "descriptive_only",
                        "scientific_context": {
                            "material": [
                                {"name": key, "value": value}
                                for key, value in row_attributes["material"].items()
                            ],
                            "sample": [
                                {"name": key, "value": value}
                                for key, value in row_attributes["sample"].items()
                            ],
                            "process": [
                                {"name": key, "value": value}
                                for key, value in row_attributes["process"].items()
                            ],
                            "test": [
                                {"name": key, "value": value}
                                for key, value in row_attributes["test"].items()
                            ],
                        },
                        "source_refs": self._objective_route_source_refs(
                            route=route,
                            source=source,
                            row_index=row_index,
                            col_index=headers.index(result_column),
                            header_path=result_column,
                            source_excerpt=" | ".join(
                                f"{header}: {row_values[header]}"
                                for header in headers
                                if header in row_values
                            ),
                        ),
                        "resolution_status": "resolved",
                        "confidence": route.confidence,
                    }
                )
        return tuple(records)

    def _objective_process_table_matrix_records(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
        objective_context: ResearchObjective | None,
        headers: tuple[str, ...],
        data_rows: tuple[tuple[int, tuple[str, ...]], ...],
    ) -> tuple[dict[str, Any], ...]:
        result_columns = self._objective_route_result_columns(route)
        records: list[dict[str, Any]] = []
        for row_index, row in data_rows:
            row_values = self._objective_table_row_values(headers=headers, row=row)
            row_attributes = self._objective_table_row_attributes(
                route=route,
                row_values=row_values,
                result_columns=result_columns,
                objective_context=objective_context,
            )
            row_attributes = self._objective_table_row_attributes_with_sample_number(
                row_attributes=row_attributes,
                row_index=row_index,
            )
            if (
                not row_attributes["material"]
                and not row_attributes["process"]
                and not row_attributes["test"]
            ):
                continue
            records.append(
                {
                    "evidence_id": self._objective_matrix_unit_id(
                        route=route,
                        row_index=row_index,
                        column="scientific_context",
                    ),
                    "objective_id": route.objective_id,
                    "document_id": route.document_id,
                    "evidence_role": "condition_context",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": None,
                    "attribution_scope": "not_attributable",
                    "scientific_context": {
                        "material": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["material"].items()
                        ],
                        "sample": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["sample"].items()
                        ],
                        "process": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["process"].items()
                        ],
                        "test": [
                            {"name": key, "value": value}
                            for key, value in row_attributes["test"].items()
                        ],
                    },
                    "source_refs": self._objective_route_source_refs(
                        route=route,
                        source=source,
                        row_index=row_index,
                        source_excerpt=" | ".join(
                            f"{header}: {row_values[header]}"
                            for header in headers
                            if header in row_values
                        ),
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

    def _objective_table_row_attributes(
        self,
        *,
        route: EvidenceCandidate,
        row_values: dict[str, str],
        result_columns: set[str],
        objective_context: ResearchObjective | None,
    ) -> dict[str, dict[str, str]]:
        material_attributes: dict[str, str] = {}
        sample_attributes: dict[str, str] = {}
        process_attributes: dict[str, str] = {}
        test_attributes: dict[str, str] = {}
        for column, value in row_values.items():
            role = str(route.column_roles.get(column) or "").lower()
            column_key = self._objective_column_key(column)
            is_objective_symbol_axis = bool(
                objective_context is not None
                and column not in result_columns
                and not self._objective_value_column_is_non_result(column)
                and self._objective_process_column_axis_keys(column)
                and self._objective_label_matches_variables(
                    column,
                    objective_context=objective_context,
                )
            )
            if is_objective_symbol_axis:
                process_attributes[
                    self._objective_process_attribute_label(
                        column=column,
                        role=role,
                        objective_context=objective_context,
                    )
                ] = value
            elif (
                any(term in role for term in ("material", "alloy", "composition"))
                or column_key
                in {
                    "material",
                    "material_system",
                    "alloy",
                    "alloy_name",
                    "alloy_type",
                    "composition",
                }
            ):
                material_attributes[column] = value
            elif "sample" in role or self._objective_table_column_is_sample_key(
                column_key
            ):
                sample_attributes[column] = value
            elif (
                column in result_columns
                or self._objective_value_column_is_non_result(column)
            ):
                continue
            elif self._objective_table_column_is_process_attribute(
                route=route,
                column=column,
                role=role,
                objective_context=objective_context,
            ):
                process_attributes[
                    self._objective_process_attribute_label(
                        column=column,
                        role=role,
                        objective_context=objective_context,
                    )
                ] = value
            elif (
                "test" in role
                or "condition" in role
                or column_key in {"test", "test_no", "test_number"}
            ):
                if route.role == "current_experimental_evidence":
                    sample_attributes[column] = value
                test_attributes[column] = value
        return {
            "material": material_attributes,
            "sample": sample_attributes,
            "process": process_attributes,
            "test": test_attributes,
        }

    def _objective_process_attribute_label(
        self,
        *,
        column: str,
        role: str,
        objective_context: ResearchObjective | None,
    ) -> str:
        if objective_context is not None:
            symbol_axes = {
                axis
                for axis in self._objective_process_column_axis_keys(column)
                if any(
                    self._axis_values_match(axis, objective_axis)
                    for objective_axis in objective_context.variables
                )
            }
            if len(symbol_axes) == 1:
                return next(iter(symbol_axes))
        role_label = self._normalize_property_label(role)
        if (
            role_label
            and self._objective_process_role_is_specific(role_label)
            and (
                objective_context is None
                or self._objective_label_matches_variables(
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

    def _objective_table_column_is_process_attribute(
        self,
        *,
        route: EvidenceCandidate,
        column: str,
        role: str,
        objective_context: ResearchObjective | None,
    ) -> bool:
        role_text = str(role or "").strip()
        if "process" in role_text or "variable" in role_text:
            return True
        if objective_context is not None:
            for label in (column, role_text):
                if self._objective_label_matches_variables(
                    label,
                    objective_context=objective_context,
                ):
                    return True
        return route.role == "process_or_treatment" and objective_context is None

    def _objective_process_column_axis_keys(self, value: Any) -> set[str]:
        column = self._label_without_unit_suffix(value)
        column = " ".join(column.split()).casefold()
        if not column:
            return set()
        return {
            axis_key
            for alias in _OBJECTIVE_SYMBOL_AXIS_ALIASES.get(column, ())
            if (axis_key := self._normalize_property_label(alias))
        }

    def _objective_label_matches_variables(
        self,
        label: Any,
        *,
        objective_context: ResearchObjective,
    ) -> bool:
        label_text = str(label or "").strip()
        if not label_text:
            return False
        label_axis_keys = self._objective_process_column_axis_keys(label_text)
        label_tokens = self._axis_token_set(self._axis_key(label_text))
        for axis in objective_context.variables:
            axis_text = str(axis or "").strip()
            if not axis_text:
                continue
            axis_key = self._normalize_property_label(axis_text)
            if axis_key and any(
                label_axis_key == axis_key
                or self._axis_label_is_mentioned(label_axis_key, axis_key)
                for label_axis_key in label_axis_keys
            ):
                return True
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
        route: EvidenceCandidate,
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

    def _objective_table_row_attributes_with_sample_number(
        self,
        *,
        row_attributes: dict[str, dict[str, str]],
        row_index: int,
    ) -> dict[str, dict[str, str]]:
        sample_attributes = dict(row_attributes["sample"])
        if self._objective_sample_attributes_have_explicit_number(sample_attributes):
            return row_attributes
        if sample_attributes and not self._objective_sample_attributes_need_row_number(
            sample_attributes
        ) and self._objective_sample_attributes_have_stable_label(sample_attributes):
            return row_attributes
        if not sample_attributes and not (
            row_attributes["material"]
            or row_attributes["process"]
            or row_attributes["test"]
        ):
            return row_attributes
        sample_attributes["sample_number"] = str(row_index)
        return {
            "material": row_attributes["material"],
            "sample": sample_attributes,
            "process": row_attributes["process"],
            "test": row_attributes["test"],
        }

    def _objective_sample_attributes_have_explicit_number(
        self,
        sample_attributes: dict[str, Any],
    ) -> bool:
        for key, value in sample_attributes.items():
            text = str(value).strip()
            if not text:
                continue
            column_key = self._objective_column_key(str(key))
            if column_key in {
                "case",
                "condition",
                "condition_no",
                "condition_number",
                "id",
                "no",
                "sample_no",
                "sample_number",
                "specimen",
                "specimen_id",
                "specimens",
            }:
                return True
            if column_key in {"sample", "sample_id"} and (
                re.fullmatch(r"0*\d+", text)
                or re.search(r"\bS0*\d+\b", text, flags=re.IGNORECASE)
                or re.search(r"\bsample\s*#?\s*0*\d+\b", text, flags=re.IGNORECASE)
            ):
                return True
        return False

    def _objective_sample_attributes_need_row_number(
        self,
        sample_attributes: dict[str, Any],
    ) -> bool:
        for value in sample_attributes.values():
            tokens = [
                token
                for token in self._objective_numeric_match_tokens(value)
                if token not in {"1", "-1"}
            ]
            if len(set(tokens)) >= 2:
                return True
        return False

    def _objective_sample_attributes_have_stable_label(
        self,
        sample_attributes: dict[str, Any],
    ) -> bool:
        for key in sample_attributes:
            column_key = self._objective_column_key(str(key))
            if column_key in {
                "id",
                "label",
                "material",
                "printed_316l",
                "sample",
                "sample_id",
                "sample_label",
            }:
                return True
            if "sample" in column_key and "condition" not in column_key:
                return True
        return False


    def _objective_table_column_is_sample_key(self, column_key: str) -> bool:
        return column_key in {
            "case",
            "condition",
            "condition_no",
            "condition_number",
            "id",
            "no",
            "printed_316l",
            "sample",
            "sample_id",
            "sample_no",
            "sample_number",
            "specimen",
            "specimen_id",
            "specimens",
        }

    @staticmethod
    def _objective_sample_values_are_opaque_identifiers(*values: Any) -> bool:
        state_terms = (
            "as built",
            "as fabricated",
            "as slm",
            "annealed",
            "aged",
            "heat treated",
            "hip slm",
            "hot isostatic",
            "solution treated",
            "stress relieved",
        )
        normalized = [
            " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))
            for value in values
        ]
        return bool(normalized) and not any(
            term in value for value in normalized for term in state_terms
        )

    def _objective_matrix_unit_id(
        self,
        *,
        route: EvidenceCandidate,
        row_index: int,
        column: str,
    ) -> str:
        seed = "|".join((route.source_ref, str(row_index), column))
        return f"oeu_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"

    def _objective_evidence_records_from_extracted(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
        objective_context: ResearchObjective | None,
        extracted_record: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        record = self._objective_complete_extracted_variable_endpoints(
            extracted_record,
            source=source,
        )
        record = self._objective_retain_source_grounded_context(
            record,
            source=source,
        )
        reported_result = record.get("reported_result")
        if isinstance(reported_result, Mapping):
            normalized_result = dict(reported_result)
            result_value = normalized_result.get("value")
            direction = str(normalized_result.get("direction") or "unknown")
            result_text = (
                f"_{self._objective_column_key(result_value)}_"
                f"{self._objective_column_key(normalized_result.get('result_text'))}_"
            )
            direction_terms = {
                "increase": (
                    "increase",
                    "increased",
                    "increases",
                    "increasing",
                    "higher",
                    "greater",
                    "larger",
                    "more",
                ),
                "decrease": (
                    "decrease",
                    "decreased",
                    "decreases",
                    "decreasing",
                    "lower",
                    "less",
                    "reduced",
                    "reduction",
                    "smaller",
                ),
                "improve": (
                    "improve",
                    "improved",
                    "improves",
                    "improving",
                    "better",
                    "enhance",
                    "enhanced",
                ),
                "worsen": (
                    "worsen",
                    "worsened",
                    "worsens",
                    "worsening",
                    "worse",
                    "degrade",
                    "degraded",
                    "deteriorate",
                    "deteriorated",
                ),
                "no_change": (
                    "no_change",
                    "no_significant_difference",
                    "similar",
                    "unchanged",
                    "remained_constant",
                ),
            }
            if (
                not _NUMBER_PATTERN.search(str(result_value or ""))
                and direction in direction_terms
                and not any(
                    f"_{term}_" in result_text for term in direction_terms[direction]
                )
            ):
                normalized_result["direction"] = "unknown"
            record["reported_result"] = normalized_result
            reported_result = normalized_result
        if not isinstance(reported_result, Mapping):
            record["changed_variables"] = []
            record["comparison"] = None
        if isinstance(reported_result, Mapping):
            if not self._objective_extracted_result_is_source_grounded(
                record,
                source=source,
            ):
                return ()
            outcome = self._normalize_objective_unit_property(
                reported_result.get("outcome"),
                objective_context=objective_context,
            )
            if not outcome:
                return ()
            if (
                objective_context is not None
                and objective_context.outcomes
                and not self._objective_property_matches_target_axes(
                    outcome,
                    target_axes=self._objective_outcomes(objective_context),
                )
            ):
                return ()
            normalized_result = dict(reported_result)
            normalized_result["outcome"] = outcome
            record["reported_result"] = normalized_result
        else:
            scientific_context = record.get("scientific_context")
            if not isinstance(scientific_context, Mapping) or not any(
                scientific_context.get(group)
                for group in ("material", "sample", "process", "test")
            ):
                return ()
        record.update(
            {
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "source_refs": self._objective_route_source_refs(
                    route=route,
                    source=source,
                ),
            }
        )
        if not record.get("confidence"):
            record["confidence"] = route.confidence
        return (record,)

    def _objective_complete_extracted_variable_endpoints(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
    ) -> dict[str, Any]:
        completed = dict(record)
        variables = completed.get("changed_variables")
        comparison = completed.get("comparison")
        if (
            not isinstance(variables, list)
            or len(variables) != 1
            or not isinstance(variables[0], Mapping)
            or not isinstance(comparison, Mapping)
        ):
            return completed
        variable = dict(variables[0])
        axis_names = comparison.get("axis_names")
        if (
            not isinstance(axis_names, list)
            or len(axis_names) != 1
            or not self._axis_values_match(
                str(variable.get("name") or ""),
                str(axis_names[0] or ""),
            )
        ):
            return completed
        source_text = self._objective_source_grounding_text(source)
        if not source_text:
            return completed
        endpoints = (
            ("baseline_value", comparison.get("baseline_label")),
            ("target_value", comparison.get("target_label")),
        )
        comparison_labels_are_grounded = all(
            str(label or "").strip()
            and self._axis_label_is_mentioned(source_text, str(label).strip())
            for _field, label in endpoints
        )
        variable_unit = str(variable.get("unit") or "").strip()
        variable_values_are_grounded = all(
            self._objective_value_is_source_grounded(variable.get(field), source_text)
            for field, _label in endpoints
        )
        variable_unit_is_grounded = not variable_unit or (
            self._objective_column_key(variable_unit)
            in self._objective_column_key(source_text)
        )
        if (
            comparison_labels_are_grounded
            and (not variable_values_are_grounded or not variable_unit_is_grounded)
        ):
            for field, label in endpoints:
                variable[field] = str(label).strip()
            variable["unit"] = None
            completed["changed_variables"] = [variable]
            return completed
        for field, label in endpoints:
            label_text = str(label or "").strip()
            if (
                variable.get(field) in (None, "")
                and label_text
                and self._axis_label_is_mentioned(source_text, label_text)
            ):
                variable[field] = label_text
        if variable.get("baseline_value") == variable.get("target_value"):
            return completed
        completed["changed_variables"] = [variable]
        return completed

    def _objective_extracted_result_is_source_grounded(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
    ) -> bool:
        source_text = self._objective_source_grounding_text(source)
        if not source_text:
            return False
        for variable in record.get("changed_variables") or ():
            if not isinstance(variable, Mapping):
                return False
            if not self._objective_axis_is_source_grounded(
                variable.get("name"),
                source=source,
                source_text=source_text,
            ):
                return False
            if any(
                not self._objective_value_is_source_grounded(
                    variable.get(field), source_text
                )
                for field in ("baseline_value", "target_value")
            ):
                return False
            variable_unit = str(variable.get("unit") or "").strip()
            if variable_unit and self._objective_column_key(
                variable_unit
            ) not in self._objective_column_key(source_text):
                return False
        reported_result = record.get("reported_result")
        if not isinstance(reported_result, Mapping):
            return True
        outcome = reported_result.get("outcome")
        if not self._objective_axis_is_source_grounded(
            outcome,
            source=source,
            source_text=source_text,
        ):
            return False
        unit = str(reported_result.get("unit") or "").strip()
        if unit and self._objective_column_key(unit) not in self._objective_column_key(
            source_text
        ):
            return False
        result_value = reported_result.get("value")
        result_text = str(reported_result.get("result_text") or "").strip()
        if result_value not in (None, "") and not self._objective_value_is_source_grounded(
            result_value,
            source_text,
        ):
            return False
        if _NUMBER_PATTERN.search(result_text):
            result_text_is_grounded = self._objective_value_is_source_grounded(
                result_text,
                source_text,
            )
        else:
            result_text_is_grounded = self._axis_label_is_mentioned(
                source_text,
                result_text,
            )
        if not result_text_is_grounded:
            return False
        if source.get("source_kind") == "table" and source.get("table_matrix"):
            return self._objective_extracted_table_result_is_row_grounded(
                record,
                source=source,
            )
        return True

    def _objective_extracted_table_result_is_row_grounded(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
    ) -> bool:
        headers, data_rows = self._objective_table_matrix_rows(dict(source))
        reported_result = record.get("reported_result")
        if not headers or not data_rows or not isinstance(reported_result, Mapping):
            return False
        outcome = str(reported_result.get("outcome") or "").strip()
        result_unit = self._objective_column_key(
            str(reported_result.get("unit") or "")
        )
        outcome_headers: list[str] = []
        for header in headers:
            property_name, header_unit = self._split_property_unit(header)
            if not self._axis_values_match(property_name, outcome):
                continue
            if result_unit and header_unit and (
                self._objective_column_key(header_unit) != result_unit
            ):
                continue
            outcome_headers.append(header)
        if not outcome_headers:
            return False

        variable_headers: dict[str, tuple[str, ...]] = {}
        for variable in record.get("changed_variables") or ():
            if not isinstance(variable, Mapping):
                return False
            name = str(variable.get("name") or "").strip()
            matching_headers = tuple(
                header
                for header in headers
                if self._axis_values_match(
                    self._split_property_unit(header)[0],
                    name,
                )
                or any(
                    self._axis_values_match(axis, name)
                    for axis in self._objective_process_column_axis_keys(header)
                )
            )
            if not matching_headers:
                return False
            variable_headers[name] = matching_headers

        row_values = [
            self._objective_table_row_values(headers=headers, row=row)
            for _row_index, row in data_rows
        ]

        def matching_rows(value_field: str) -> list[dict[str, str]]:
            matches: list[dict[str, str]] = []
            for values in row_values:
                if all(
                    any(
                        self._objective_table_cell_matches_value(
                            values.get(header),
                            variable.get(value_field),
                        )
                        for header in variable_headers[
                            str(variable.get("name") or "").strip()
                        ]
                    )
                    for variable in record.get("changed_variables") or ()
                    if isinstance(variable, Mapping)
                ):
                    matches.append(values)
            return matches

        baseline_rows = matching_rows("baseline_value")
        target_rows = matching_rows("target_value")
        if record.get("changed_variables") and (not baseline_rows or not target_rows):
            return False
        if not target_rows:
            target_rows = row_values
        if not baseline_rows:
            baseline_rows = target_rows
        for baseline in baseline_rows:
            for target in target_rows:
                if not any(
                    self._objective_value_is_source_grounded(
                        reported_result.get("value"),
                        target.get(header, ""),
                    )
                    for header in outcome_headers
                ):
                    continue
                bound_text = "\n".join(
                    str(value) for value in (*baseline.values(), *target.values())
                )
                result_text = str(reported_result.get("result_text") or "")
                if not _NUMBER_PATTERN.search(
                    result_text
                ) or self._objective_value_is_source_grounded(result_text, bound_text):
                    return True
        return False

    def _objective_retain_source_grounded_context(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
    ) -> dict[str, Any]:
        grounded_record = dict(record)
        scientific_context = record.get("scientific_context")
        if not isinstance(scientific_context, Mapping):
            grounded_record["scientific_context"] = {
                "material": [],
                "sample": [],
                "process": [],
                "test": [],
            }
            return grounded_record
        source_text = self._objective_source_grounding_text(source)
        grounded_context: dict[str, list[dict[str, Any]]] = {}
        for group in ("material", "sample", "process", "test"):
            grounded_attributes: list[dict[str, Any]] = []
            for attribute in scientific_context.get(group) or ():
                if not isinstance(attribute, Mapping):
                    continue
                if not self._objective_axis_is_source_grounded(
                    attribute.get("name"),
                    source=source,
                    source_text=source_text,
                ):
                    continue
                value = attribute.get("value")
                if value not in (None, "") and not self._objective_value_is_source_grounded(
                    value,
                    source_text,
                ):
                    continue
                unit = str(attribute.get("unit") or "").strip()
                if unit and self._objective_column_key(
                    unit
                ) not in self._objective_column_key(source_text):
                    continue
                grounded_attributes.append(dict(attribute))
            grounded_context[group] = grounded_attributes
        grounded_record["scientific_context"] = grounded_context
        return grounded_record

    def _objective_table_cell_matches_value(self, cell: Any, value: Any) -> bool:
        if value in (None, ""):
            return True
        cell_text = str(cell or "").strip()
        value_text = str(value).strip()
        if not cell_text:
            return False
        if _NUMBER_PATTERN.search(value_text):
            return self._objective_value_is_source_grounded(
                value_text,
                cell_text,
            )
        cell_key = self._objective_column_key(cell_text)
        value_key = self._objective_column_key(value_text)
        return bool(cell_key and value_key and cell_key == value_key)

    def _objective_axis_is_source_grounded(
        self,
        value: Any,
        *,
        source: Mapping[str, Any],
        source_text: str,
    ) -> bool:
        axis = str(value or "").strip()
        if not axis:
            return False
        if self._axis_label_is_mentioned(source_text, axis):
            return True
        labels = [
            *source.get("column_headers", ()),
            *(cell.get("header_path") for cell in source.get("table_cells", ())
              if isinstance(cell, Mapping)),
        ]
        for label in labels:
            label_text = str(label or "").strip()
            if not label_text:
                continue
            symbol_axes = self._objective_process_column_axis_keys(label_text)
            if any(self._axis_values_match(axis, item) for item in symbol_axes):
                return True
            if (
                self._axis_values_match(label_text, axis)
                or self._axis_label_is_mentioned(label_text, axis)
                or self._axis_label_is_mentioned(axis, label_text)
            ):
                return True
        return any(
            self._axis_values_match(token, axis)
            for token in re.findall(r"[A-Za-z\u0370-\u03ff]+", source_text)
        )

    @staticmethod
    def _objective_source_grounding_text(source: Mapping[str, Any]) -> str:
        values: list[str] = []
        for field in ("text", "caption_text", "heading_path"):
            value = str(source.get(field) or "").strip()
            if value:
                values.append(value)
        values.extend(
            str(value).strip()
            for value in source.get("column_headers", ())
            if str(value).strip()
        )
        values.extend(
            str(cell).strip()
            for row in source.get("table_matrix", ())
            if isinstance(row, (list, tuple))
            for cell in row
            if str(cell).strip()
        )
        values.extend(
            str(cell.get("cell_text") or "").strip()
            for cell in source.get("table_cells", ())
            if isinstance(cell, Mapping) and str(cell.get("cell_text") or "").strip()
        )
        return "\n".join(values)

    def _objective_value_is_source_grounded(self, value: Any, source_text: str) -> bool:
        expected = {
            float(match.group(0))
            for match in _NUMBER_PATTERN.finditer(
                str("" if value is None else value)
                .replace(",", "")
                .replace("\u2212", "-")
            )
        }
        if not expected:
            value_key = self._objective_column_key(
                str("" if value is None else value)
            )
            source_key = self._objective_column_key(source_text)
            return bool(value_key and value_key in source_key)
        actual = {
            float(match.group(0))
            for match in _NUMBER_PATTERN.finditer(
                source_text.replace(",", "").replace("\u2212", "-")
            )
        }
        return expected <= actual


    def _objective_route_result_columns(
        self,
        route: EvidenceCandidate,
        *,
        objective_context: ResearchObjective | None = None,
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
                    objective_context.outcomes,
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
                    for axis in objective_context.outcomes
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
                    target_axes=self._objective_outcomes(
                        objective_context
                    ),
                )
            ):
                result_columns.add(column_text)
        return result_columns

    def _objective_result_column_property_label(
        self,
        *,
        route: EvidenceCandidate,
        result_column: str,
        objective_context: ResearchObjective | None,
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
                target_axes=self._objective_outcomes(objective_context),
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
        objective_context: ResearchObjective | None,
    ) -> bool:
        if objective_context is None or not objective_context.outcomes:
            return True
        property_name, _unit = self._split_property_unit(column_text)
        normalized = self._normalize_property_label(property_name) or property_name
        target_axes = self._objective_outcomes(objective_context)
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
        if normalized in target_axes:
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
                if extra_tokens.issubset(
                    {"archimede", "archimedes", "material", "method", "relative"}
                ):
                    return target_key, extra_tokens
                continue
            if extra_tokens and extra_tokens.issubset(
                _OBJECTIVE_SINGLE_TOKEN_PROPERTY_QUALIFIERS
            ):
                return target_key, extra_tokens
        return None

    def _objective_outcomes(
        self,
        objective_context: ResearchObjective,
    ) -> tuple[str, ...]:
        axes: list[str] = []
        seen: set[str] = set()
        for axis in objective_context.outcomes:
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
        objective_context: ResearchObjective | None,
    ) -> str | None:
        normalized = self._normalize_property_label(value)
        if not normalized:
            return None
        if objective_context is None:
            return normalized
        for target_axis in objective_context.outcomes:
            if self._axis_values_match(normalized, target_axis):
                return self._normalize_property_label(target_axis)
        target_axes = self._objective_outcomes(objective_context)
        if normalized in target_axes:
            return normalized
        variant_match = self._objective_contextual_property_variant_match(
            normalized,
            target_axes=target_axes,
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
        text = re.sub(r"\s*\((?:LCSM|EBSD)\)\s*$", "", text, flags=re.IGNORECASE).strip()
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


    def _objective_route_source_refs(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
        row_index: int | None = None,
        col_index: int | None = None,
        header_path: str | None = None,
        source_excerpt: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        ref = {
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "role": route.role,
            "evidence_role": route.join_plan.get("evidence_role"),
            "page": source.get("page"),
            "row_index": row_index,
            "col_index": col_index,
            "header_path": header_path,
            "source_excerpt": source_excerpt,
        }
        return (
            {
                key: value
                for key, value in ref.items()
                if value not in (None, "", [], {})
            },
        )

    def _objective_evidence_has_payload(
        self,
        unit: ExtractedEvidenceDraft,
    ) -> bool:
        return bool(
            unit.changed_variables
            or unit.comparison is not None
            or unit.reported_result is not None
            or unit.scientific_context.has_content
        )


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
        frame: PaperAnalysisFrame,
        blocks: list[Any],
        tables: list[Any],
        document_tree: SourceDocumentTree | None = None,
    ) -> list[dict[str, Any]]:
        candidates_by_key: dict[tuple[str, str], dict[str, Any]] = {}
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
            candidate = {
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
            candidates_by_key[("table", table_id)] = self._attach_route_tree_position(
                candidate,
                document_tree=document_tree,
            )
        if document_tree is not None:
            text_candidates = self._build_tree_route_text_candidates(
                frame=frame,
                blocks=blocks,
                document_tree=document_tree,
            )
        else:
            text_candidate_limit = max(
                _ROUTE_CANDIDATE_LIMIT - len(candidates_by_key),
                0,
            )
            text_candidates = self._build_ranked_route_text_candidates(
                frame=frame,
                blocks=blocks,
                limit=text_candidate_limit,
            )
        for candidate in text_candidates:
            source_ref = str(candidate.get("source_ref") or "")
            if not source_ref:
                continue
            candidates_by_key[("text_window", source_ref)] = (
                self._attach_route_tree_position(
                    candidate,
                    document_tree=document_tree,
                )
            )
        candidates = self._sort_route_candidates_by_tree(
            candidates_by_key.values(),
            document_tree=document_tree,
        )
        if document_tree is not None:
            return candidates
        return candidates[:_ROUTE_CANDIDATE_LIMIT]

    def _attach_route_tree_position(
        self,
        candidate: dict[str, Any],
        *,
        document_tree: SourceDocumentTree | None,
    ) -> dict[str, Any]:
        tree_position = self._route_candidate_tree_position(
            candidate,
            document_tree=document_tree,
        )
        if not tree_position:
            return candidate
        return {
            **candidate,
            "tree_position": tree_position,
        }

    def _route_candidate_tree_position(
        self,
        candidate: dict[str, Any],
        *,
        document_tree: SourceDocumentTree | None,
    ) -> dict[str, Any]:
        source_kind = str(candidate.get("source_kind") or "")
        source_ref = str(candidate.get("source_ref") or "")
        source_ref_kind = "block" if source_kind == "text_window" else source_kind
        node = (
            self._tree_node_for_route_source(
                document_tree=document_tree,
                source_ref_kind=source_ref_kind,
                source_ref_id=source_ref,
            )
            if document_tree is not None and source_ref and source_ref_kind
            else None
        )
        if node is not None:
            return self._tree_position_payload(
                document_tree=document_tree,
                node=node,
            )
        heading_path = candidate.get("heading_path")
        return {
            "node_id": None,
            "node_type": source_kind or None,
            "section_path": self._heading_path_parts(heading_path),
            "source_ref_kind": source_kind or None,
            "source_ref_id": source_ref or None,
            "order": None,
            "page_start": None,
            "page_end": None,
        }

    def _sort_route_candidates_by_tree(
        self,
        candidates: Iterable[dict[str, Any]],
        *,
        document_tree: SourceDocumentTree | None,
    ) -> list[dict[str, Any]]:
        ordered = list(candidates)
        if document_tree is None:
            return ordered
        return sorted(
            ordered,
            key=lambda candidate: (
                self._route_candidate_order(candidate),
                str(candidate.get("source_kind") or ""),
                str(candidate.get("source_ref") or ""),
            ),
        )

    def _route_candidate_order(self, candidate: dict[str, Any]) -> int:
        tree_position = candidate.get("tree_position")
        if isinstance(tree_position, dict):
            order = tree_position.get("order")
            if order is not None:
                try:
                    return int(order)
                except (TypeError, ValueError):
                    pass
        return 900_000

    def _route_tree_position(self, candidate: dict[str, Any]) -> dict[str, Any]:
        tree_position = candidate.get("tree_position")
        if isinstance(tree_position, dict):
            return dict(tree_position)
        return {
            "node_id": None,
            "node_type": candidate.get("source_kind"),
            "section_path": self._heading_path_parts(candidate.get("heading_path")),
            "source_ref_kind": candidate.get("source_kind"),
            "source_ref_id": candidate.get("source_ref"),
            "order": None,
            "page_start": candidate.get("page"),
            "page_end": candidate.get("page"),
        }

    def _tree_position_payload(
        self,
        *,
        document_tree: SourceDocumentTree,
        node: Any,
    ) -> dict[str, Any]:
        return {
            "node_id": getattr(node, "node_id", None),
            "node_type": str(getattr(node, "node_type", "") or "") or None,
            "section_path": self._tree_node_section_path(
                document_tree=document_tree,
                node=node,
            ),
            "source_ref_kind": getattr(node, "source_ref_kind", None),
            "source_ref_id": getattr(node, "source_ref_id", None),
            "order": getattr(node, "order", None),
            "page_start": getattr(node, "page_start", None),
            "page_end": getattr(node, "page_end", None),
        }

    def _tree_node_section_path(
        self,
        *,
        document_tree: SourceDocumentTree,
        node: Any,
    ) -> list[str]:
        heading_path = tuple(getattr(node, "heading_path", ()) or ())
        if heading_path:
            return [str(part) for part in heading_path if str(part).strip()]
        titles: list[str] = []
        parent_id = getattr(node, "parent_id", None)
        while parent_id:
            parent = document_tree.nodes.get(parent_id)
            if parent is None:
                break
            if parent.node_type in {"section", "references_section"}:
                title = str(getattr(parent, "title", "") or "").strip()
                if title:
                    titles.append(title)
            parent_id = getattr(parent, "parent_id", None)
        return list(reversed(titles))

    def _heading_path_parts(self, heading_path: Any) -> list[str]:
        if isinstance(heading_path, (list, tuple)):
            return [str(part).strip() for part in heading_path if str(part).strip()]
        return [
            part.strip()
            for part in str(heading_path or "").split(">")
            if part.strip()
        ]

    def _tree_order_objective_routes(
        self,
        routes: tuple[EvidenceCandidate, ...],
        *,
        document_trees_by_document_id: dict[str, SourceDocumentTree],
    ) -> tuple[EvidenceCandidate, ...]:
        return tuple(
            sorted(
                routes,
                key=lambda route: (
                    self._route_tree_order(
                        route,
                        document_trees_by_document_id=document_trees_by_document_id,
                    ),
                    route.source_ref,
                ),
            )
        )

    def _route_tree_order(
        self,
        route: EvidenceCandidate,
        *,
        document_trees_by_document_id: dict[str, SourceDocumentTree],
    ) -> int:
        document_tree = document_trees_by_document_id.get(route.document_id)
        if document_tree is None:
            return 900_000
        source_ref_kind = "block" if route.source_kind == "text_window" else route.source_kind
        node = self._tree_node_for_route_source(
            document_tree=document_tree,
            source_ref_kind=source_ref_kind,
            source_ref_id=route.source_ref,
        )
        if node is None:
            return 900_000
        return int(getattr(node, "order", 900_000) or 900_000)

    def _tree_node_for_route_source(
        self,
        *,
        document_tree: SourceDocumentTree,
        source_ref_kind: str,
        source_ref_id: str,
    ) -> Any | None:
        node = document_tree.node_for_source_ref(source_ref_kind, source_ref_id)
        if node is not None:
            return node
        return document_tree.nodes.get(source_ref_id)

    def _source_candidate_from_route(
        self,
        *,
        route: EvidenceCandidate,
        source: dict[str, Any],
        document_tree: SourceDocumentTree | None,
    ) -> dict[str, Any]:
        candidate = {
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "heading_path": source.get("heading_path"),
            "page": source.get("page"),
        }
        return self._attach_route_tree_position(
            candidate,
            document_tree=document_tree,
        )

    def _objective_evidence_prompt_route_record(
        self,
        route: EvidenceCandidate,
    ) -> dict[str, Any]:
        return {
            "objective_id": route.objective_id,
            "document_id": route.document_id,
            "source_kind": route.source_kind,
            "source_ref": route.source_ref,
            "role": route.role,
            "extractable": route.extractable,
            "reason": route.reason,
            "column_roles": dict(route.column_roles),
            "join_plan": dict(route.join_plan),
            "confidence": route.confidence,
        }

    def _objective_evidence_prompt_source(
        self,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        source_kind = str(source.get("source_kind") or "")
        if source_kind == "table":
            compact_cells = self._objective_evidence_prompt_table_cells(source)
            payload = {
                "source_kind": "table",
                "source_ref": str(source.get("source_ref") or ""),
                "document_id": source.get("document_id"),
                "page": source.get("page"),
                "caption_text": str(source.get("caption_text") or "")[
                    :_ROUTE_PROMPT_TEXT_CHARS
                ],
                "heading_path": source.get("heading_path"),
                "column_headers": [
                    str(value)[:_OBJECTIVE_STATE_TEXT_CHARS]
                    for value in source.get("column_headers", []) or []
                    if str(value).strip()
                ],
                "table_cells": compact_cells,
            }
            if not compact_cells:
                payload["table_matrix"] = self._objective_evidence_prompt_table_matrix(
                    source
                )
            return payload
        if source_kind == "text_window":
            return {
                "source_kind": "text_window",
                "source_ref": str(source.get("source_ref") or ""),
                "document_id": source.get("document_id"),
                "page": source.get("page"),
                "block_type": source.get("block_type"),
                "heading_path": source.get("heading_path"),
                "text": str(source.get("text") or "")[
                    :_OBJECTIVE_EVIDENCE_PROMPT_TEXT_CHARS
                ],
            }
        return dict(source)

    def _objective_evidence_prompt_table_matrix(
        self,
        source: dict[str, Any],
    ) -> list[list[str]]:
        matrix = source.get("table_matrix")
        if not isinstance(matrix, list):
            return []
        rows: list[list[str]] = []
        for row in matrix[:_OBJECTIVE_EVIDENCE_PROMPT_TABLE_ROWS]:
            if not isinstance(row, (list, tuple)):
                continue
            rows.append(
                [
                    str(cell)[:_OBJECTIVE_STATE_TEXT_CHARS]
                    for cell in row[:_ROUTE_PROMPT_HEADER_LIMIT]
                ]
            )
        return rows

    def _objective_evidence_prompt_table_cells(
        self,
        source: dict[str, Any],
    ) -> list[dict[str, Any]]:
        cells = source.get("table_cells")
        if not isinstance(cells, list):
            return []
        compact_cells: list[dict[str, Any]] = []
        for cell in cells[:_OBJECTIVE_EVIDENCE_PROMPT_TABLE_CELLS]:
            if not isinstance(cell, dict):
                continue
            compact_cells.append(
                {
                    "row_index": cell.get("row_index"),
                    "col_index": cell.get("col_index"),
                    "header_path": cell.get("header_path"),
                    "cell_text": str(cell.get("cell_text") or "")[
                        :_OBJECTIVE_STATE_TEXT_CHARS
                    ],
                }
            )
        return compact_cells

    def _empty_objective_document_state(self) -> dict[str, Any]:
        return {
            "schema_version": "objective_document_state.v2",
            "evidence_counts_by_role": {},
            "prior_evidence": [],
        }

    def _objective_document_state_payload(
        self,
        units: list[ExtractedEvidenceDraft],
    ) -> dict[str, Any]:
        if not units:
            return self._empty_objective_document_state()
        counts_by_role: dict[str, int] = {}
        for unit in units:
            role = unit.evidence_role or "irrelevant"
            counts_by_role[role] = counts_by_role.get(role, 0) + 1
        prior_evidence: list[dict[str, Any]] = []
        for unit in units[-_OBJECTIVE_STATE_ITEM_LIMIT:]:
            prior_evidence.append(
                {
                    "evidence_role": unit.evidence_role,
                    "outcome": (
                        unit.reported_result.outcome if unit.reported_result else None
                    ),
                    "attribution_scope": unit.attribution_scope,
                    "resolution_status": unit.resolution_status,
                    "source_refs": [dict(ref) for ref in unit.source_refs[:2]],
                }
            )
        return {
            "schema_version": "objective_document_state.v2",
            "evidence_counts_by_role": counts_by_role,
            "prior_evidence": prior_evidence,
        }


    def _build_ranked_route_text_candidates(
        self,
        *,
        frame: PaperAnalysisFrame,
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
                or not any(char.isalpha() for char in text)
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

    def _build_tree_route_text_candidates(
        self,
        *,
        frame: PaperAnalysisFrame,
        blocks: list[Any],
        document_tree: SourceDocumentTree,
    ) -> list[dict[str, Any]]:
        block_by_id = {
            str(getattr(block, "block_id", "") or ""): block
            for block in blocks
            if str(getattr(block, "block_id", "") or "")
        }
        restrict_to_frame_sections = self._route_text_candidates_use_frame_sections(frame)
        scored_candidates: list[tuple[int, int, dict[str, Any]]] = []
        for node in self._document_tree_nodes_in_order(document_tree):
            if self._tree_node_in_reference_branch(document_tree, node):
                continue
            if str(getattr(node, "source_ref_kind", "") or "").strip() != "block":
                continue
            block_type = self._route_text_node_block_type(node)
            if block_type not in {"paragraph", "list_item", "figure_caption"}:
                continue
            source_ref = str(getattr(node, "source_ref_id", "") or "").strip()
            block = block_by_id.get(source_ref)
            if not source_ref:
                source_ref = str(getattr(node, "node_id", "") or "").strip()
            text = (
                str(getattr(block, "text", "") or "").strip()
                if block is not None
                else ""
            )
            if not text:
                text = str(getattr(node, "text", "") or "").strip()
            if not source_ref or not text or not any(char.isalpha() for char in text):
                continue
            section_label = self._tree_section_label_for_route_node(
                document_tree=document_tree,
                node=node,
                block=block,
            )
            if restrict_to_frame_sections and not self._route_section_matches_frame(
                section_label=section_label,
                frame=frame,
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
                    int(getattr(node, "order", 900_000) or 900_000),
                    {
                        "source_kind": "text_window",
                        "source_ref": source_ref,
                        "frame_status": "relevant",
                        "section_label": section_label,
                        "block_type": block_type,
                        "text": text[:_ROUTE_TEXT_CHARS],
                    },
                )
            )
        scored_candidates = self._bounded_tree_route_text_candidates(
            frame=frame,
            scored_candidates=scored_candidates,
        )
        return [
            candidate
            for _, _, candidate in sorted(
                scored_candidates,
                key=lambda item: (
                    item[1],
                    str(item[2].get("source_ref") or ""),
                ),
            )
        ]

    def _bounded_tree_route_text_candidates(
        self,
        *,
        frame: PaperAnalysisFrame,
        scored_candidates: list[tuple[int, int, dict[str, Any]]],
    ) -> list[tuple[int, int, dict[str, Any]]]:
        if len(scored_candidates) <= _ROUTE_TEXT_CANDIDATE_LIMIT:
            return scored_candidates
        if not (
            frame.relevance == "high"
            and frame.paper_role == "primary_experiment"
        ):
            return sorted(scored_candidates)[:_ROUTE_TEXT_CANDIDATE_LIMIT]
        selected: dict[tuple[str, str], tuple[int, int, dict[str, Any]]] = {}
        selected_keys: set[tuple[str, str]] = set()
        section_counts: dict[str, int] = {}
        direct_result_candidates = [
            item
            for item in sorted(scored_candidates)
            if self._route_text_candidate_is_direct_result(
                frame=frame,
                candidate=item[2],
            )
        ]
        for item in direct_result_candidates:
            candidate = item[2]
            source_key = (
                str(candidate.get("source_kind") or ""),
                str(candidate.get("source_ref") or ""),
            )
            selected[source_key] = item
            selected_keys.add(source_key)
            section_key = self._objective_column_key(candidate.get("section_label"))
            section_counts[section_key] = section_counts.get(section_key, 0) + 1
            if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT // 2:
                break
        for item in sorted(scored_candidates):
            candidate = item[2]
            source_key = (
                str(candidate.get("source_kind") or ""),
                str(candidate.get("source_ref") or ""),
            )
            if source_key in selected_keys:
                continue
            section_key = self._objective_column_key(candidate.get("section_label"))
            if section_counts.get(section_key, 0) >= _ROUTE_TREE_TEXT_SECTION_LIMIT:
                continue
            selected[source_key] = item
            selected_keys.add(source_key)
            section_counts[section_key] = section_counts.get(section_key, 0) + 1
            if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT // 2:
                break
        ordered_candidates = sorted(
            scored_candidates,
            key=lambda item: (
                item[1],
                str(item[2].get("source_ref") or ""),
            ),
        )
        for item in self._evenly_spaced_tree_route_candidates(
            ordered_candidates,
            _ROUTE_TEXT_CANDIDATE_LIMIT - len(selected),
        ):
            candidate = item[2]
            source_key = (
                str(candidate.get("source_kind") or ""),
                str(candidate.get("source_ref") or ""),
            )
            if source_key in selected_keys:
                continue
            selected[source_key] = item
            selected_keys.add(source_key)
            if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT:
                break
        for item in sorted(scored_candidates):
            candidate = item[2]
            source_key = (
                str(candidate.get("source_kind") or ""),
                str(candidate.get("source_ref") or ""),
            )
            if source_key in selected_keys:
                continue
            selected[source_key] = item
            selected_keys.add(source_key)
            if len(selected) >= _ROUTE_TEXT_CANDIDATE_LIMIT:
                break
        return list(selected.values())

    def _route_text_candidate_is_direct_result(
        self,
        *,
        frame: PaperAnalysisFrame,
        candidate: Mapping[str, Any],
    ) -> bool:
        text = str(candidate.get("text") or "")
        if not text:
            return False
        mentions_variable = any(
            self._source_text_mentions_axis(text, axis)
            for axis in frame.changed_variables
        )
        mentions_outcome = any(
            self._source_text_mentions_axis(text, axis)
            for axis in frame.measured_property_scope
        )
        if not mentions_outcome:
            return False
        text_haystack = text.casefold()
        has_result_comparison = any(
            phrase in text_haystack
            for phrase in (
                "compared with",
                "compared to",
                "comparing",
                "decreased",
                "exhibited",
                "higher than",
                "increased",
                "lower than",
                "observed",
                "resulted in",
                "resulted into",
            )
        )
        return has_result_comparison and (
            mentions_variable
            or "compared" in text_haystack
            or "comparing" in text_haystack
        )

    def _evenly_spaced_tree_route_candidates(
        self,
        candidates: list[tuple[int, int, dict[str, Any]]],
        limit: int,
    ) -> list[tuple[int, int, dict[str, Any]]]:
        if limit <= 0:
            return []
        if limit >= len(candidates):
            return candidates
        if limit == 1:
            return [candidates[-1]]
        selected: list[tuple[int, int, dict[str, Any]]] = []
        seen_indexes: set[int] = set()
        last_index = len(candidates) - 1
        for position in range(limit):
            index = round(position * last_index / (limit - 1))
            if index in seen_indexes:
                continue
            selected.append(candidates[index])
            seen_indexes.add(index)
        return selected

    def _route_text_candidates_use_frame_sections(
        self,
        frame: PaperAnalysisFrame,
    ) -> bool:
        if not frame.relevant_sections:
            return False
        if frame.relevance == "high" and frame.paper_role == "primary_experiment":
            return False
        return True

    def _route_section_matches_frame(
        self,
        *,
        section_label: str,
        frame: PaperAnalysisFrame,
    ) -> bool:
        section_key = self._objective_column_key(section_label)
        if not section_key:
            return False
        return any(
            section_key == frame_key
            or section_key.endswith(f"_{frame_key}")
            or frame_key.endswith(f"_{section_key}")
            for frame_key in (
                self._objective_column_key(section)
                for section in frame.relevant_sections
            )
            if frame_key
        )

    def _route_text_node_block_type(self, node: Any) -> str:
        node_type = str(getattr(node, "node_type", "") or "")
        if node_type == "caption":
            source_ref_kind = str(getattr(node, "source_ref_kind", "") or "")
            return "figure_caption" if source_ref_kind == "figure" else "paragraph"
        return node_type

    def _tree_section_label_for_route_node(
        self,
        *,
        document_tree: SourceDocumentTree,
        node: Any,
        block: Any | None,
    ) -> str:
        if block is not None:
            section_label = self._block_section_label(block)
            if section_label:
                return section_label
        section_path = self._tree_node_section_path(
            document_tree=document_tree,
            node=node,
        )
        if section_path:
            return " > ".join(section_path)
        return "Unsectioned"

    def _route_text_candidate_score(
        self,
        *,
        frame: PaperAnalysisFrame,
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
        paper_skim: PaperSkim | None,
        document: Any,
        profile: Any,
        blocks: list[Any],
        tables: list[Any],
        document_tree: SourceDocumentTree | None,
    ) -> dict[str, Any]:
        return {
            "collection_id": collection_id,
            "objective": objective.to_record(),
            "paper_skim": paper_skim.to_record() if paper_skim is not None else {},
            "document": {
                "document_id": getattr(document, "document_id", None),
                "title": getattr(document, "title", None),
                "source_filename": self._resolve_source_filename(document),
            },
            "document_profile": profile.to_record() if profile else {},
            "section_snippets": self._build_frame_section_snippets(
                blocks,
                objective=objective,
                paper_skim=paper_skim,
                profile=profile,
                document_tree=document_tree,
            ),
            "table_summaries": self._build_frame_table_summaries(
                tables,
                objective=objective,
                paper_skim=paper_skim,
                profile=profile,
            ),
        }

    def _build_frame_section_snippets(
        self,
        blocks: list[Any],
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
        profile: Any,
        document_tree: SourceDocumentTree | None = None,
    ) -> list[dict[str, Any]]:
        frame_terms = self._frame_relevance_terms(
            objective=objective,
            paper_skim=paper_skim,
            profile=profile,
        )
        if document_tree is not None:
            snippets = self._build_frame_section_snippets_from_tree(document_tree)
            if snippets:
                return self._prioritize_frame_items(snippets, frame_terms=frame_terms)

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
        return self._prioritize_frame_items(snippets, frame_terms=frame_terms)

    def _build_frame_section_snippets_from_tree(
        self,
        document_tree: SourceDocumentTree,
    ) -> list[dict[str, Any]]:
        snippets: list[dict[str, Any]] = []
        nodes = self._document_tree_nodes_in_order(document_tree)
        section_nodes = [
            node
            for node in nodes
            if node.node_type == "section"
            and not self._tree_node_in_reference_branch(document_tree, node)
        ]
        for node in section_nodes:
            text = self._section_text_from_tree_node(document_tree, node)
            if not text and node.title:
                text = node.title
            if not text:
                continue
            snippets.append(
                {
                    "section_label": self._tree_section_label(node),
                    "block_type": "section",
                    "text": text[:_FRAME_SECTION_TEXT_CHARS],
                }
            )

        if snippets:
            return snippets

        unsectioned_texts = [
            str(node.text or "").strip()
            for node in nodes
            if node.node_type in {"paragraph", "list_item"}
            and node.parent_id == document_tree.root_node_id
            and not self._tree_node_in_reference_branch(document_tree, node)
            and str(node.text or "").strip()
        ]
        text = "\n\n".join(unsectioned_texts).strip()
        if not text:
            return []
        return [
            {
                "section_label": "Unsectioned",
                "block_type": "section",
                "text": text[:_FRAME_SECTION_TEXT_CHARS],
            }
        ]

    def _section_text_from_tree_node(
        self,
        document_tree: SourceDocumentTree,
        node: Any,
    ) -> str:
        texts: list[str] = []
        for child_id in node.child_ids:
            child = document_tree.nodes[child_id]
            if child.node_type in {"section", "references_section"}:
                continue
            if child.node_type not in {"paragraph", "list_item"}:
                continue
            text = str(child.text or "").strip()
            if text:
                texts.append(text)
        return "\n\n".join(texts).strip()

    def _tree_section_label(self, node: Any) -> str:
        if getattr(node, "heading_path", ()):
            return " > ".join(str(part) for part in node.heading_path if str(part))
        title = str(getattr(node, "title", "") or "").strip()
        return title or "Unsectioned"

    def _build_frame_table_summaries(
        self,
        tables: list[Any],
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
        profile: Any,
    ) -> list[dict[str, Any]]:
        frame_terms = self._frame_relevance_terms(
            objective=objective,
            paper_skim=paper_skim,
            profile=profile,
        )
        summaries: list[dict[str, Any]] = []
        for table in sorted(
            tables,
            key=lambda item: int(getattr(item, "table_order", 0) or 0),
        ):
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
        return self._prioritize_frame_items(
            summaries,
            frame_terms=frame_terms,
            limit=_FRAME_TABLE_LIMIT,
        )

    def _build_deterministic_objective_paper_frame_record(
        self,
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        frame_terms = self._frame_relevance_terms(
            objective=objective,
            paper_skim=paper_skim,
            profile=None,
        )
        sections = [
            str(item.get("section_label") or "").strip()
            for item in self._frame_relevant_items(
                payload.get("section_snippets"),
                frame_terms=frame_terms,
            )
            if str(item.get("section_label") or "").strip()
        ]
        tables = [
            str(item.get("table_id") or "").strip()
            for item in self._frame_relevant_items(
                payload.get("table_summaries"),
                frame_terms=frame_terms,
            )
            if str(item.get("table_id") or "").strip()
        ]
        visible_table_ids = [
            str(item.get("table_id") or "").strip()
            for item in payload.get("table_summaries") or ()
            if isinstance(item, Mapping) and str(item.get("table_id") or "").strip()
        ]
        excluded_tables = [table_id for table_id in visible_table_ids if table_id not in tables]
        evidence_density = str(getattr(paper_skim, "evidence_density", "") or "")
        has_relevant_content = bool(sections or tables)
        axis_coverage = self._deterministic_frame_axis_coverage(
            objective=objective,
            paper_skim=paper_skim,
            items=[*sections, *tables],
            payload=payload,
        )
        has_axis_coverage = (
            axis_coverage["variable"] and axis_coverage["target_property"]
        )
        is_seed_document = bool(
            getattr(paper_skim, "document_id", None)
            and getattr(paper_skim, "document_id", None)
            in set(objective.seed_document_ids)
        )
        relevance = "medium" if has_relevant_content and has_axis_coverage else "low"
        if has_relevant_content and is_seed_document:
            relevance = "medium"
        if (
            not has_relevant_content
            or (not has_axis_coverage and not is_seed_document)
        ) and evidence_density == "low":
            relevance = "irrelevant"
        if not has_axis_coverage and not is_seed_document:
            sections = []
            tables = []
            excluded_tables = visible_table_ids
        return {
            "relevance": relevance,
            "paper_role": self._deterministic_frame_paper_role(paper_skim),
            "background": "Deterministic frame built after model framing failed.",
            "material_match": list(objective.material_scope),
            "changed_variables": self._deterministic_frame_variables(
                objective=objective,
                paper_skim=paper_skim,
            ),
            "measured_property_scope": self._deterministic_frame_target_properties(
                objective=objective,
                paper_skim=paper_skim,
            ),
            "test_environment_scope": [],
            "relevant_sections": sections[:_FRAME_SECTION_SNIPPET_LIMIT],
            "relevant_tables": tables[:_FRAME_TABLE_LIMIT],
            "excluded_tables": excluded_tables,
        }

    def _deterministic_frame_axis_coverage(
        self,
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
        items: list[str],
        payload: Mapping[str, Any],
    ) -> dict[str, bool]:
        text = self._axis_key(
            " ".join(
                [
                    *items,
                    str(getattr(paper_skim, "doc_role", "") or ""),
                    " ".join(getattr(paper_skim, "changed_variables", ()) or ()),
                    " ".join(getattr(paper_skim, "candidate_properties", ()) or ()),
                    " ".join(getattr(paper_skim, "candidate_processes", ()) or ()),
                    str(payload.get("document") or ""),
                ]
            )
        )
        variable_axes = tuple(objective.variables)
        target_axes = tuple(objective.outcomes)
        return {
            "variable": self._frame_mentions_any_axis(text, variable_axes),
            "target_property": self._frame_mentions_any_axis(text, target_axes),
        }

    def _frame_mentions_any_axis(self, text_key: str, axes: Iterable[Any]) -> bool:
        text_tokens = self._axis_token_set(text_key)
        for axis in axes:
            axis_text = str(axis or "").strip()
            if not axis_text:
                continue
            axis_key = self._axis_key(axis_text)
            axis_tokens = self._axis_token_set(axis_key)
            if not axis_tokens:
                continue
            if axis_key in text_key or self._source_text_mentions_axis(text_key, axis_text):
                return True
            meaningful_tokens = {
                token
                for token in axis_tokens
                if token
                not in {
                    "additive",
                    "affect",
                    "alloy",
                    "laser",
                    "lpbf",
                    "manufacturing",
                    "melting",
                    "powder",
                    "process",
                    "selective",
                    "slm",
                    "steel",
                }
            }
            if meaningful_tokens and meaningful_tokens.issubset(text_tokens):
                return True
        return False

    def _frame_relevant_items(
        self,
        raw_items: Any,
        *,
        frame_terms: tuple[tuple[str, int], ...],
    ) -> list[Mapping[str, Any]]:
        if not isinstance(raw_items, list):
            return []
        scored: list[tuple[int, int, Mapping[str, Any]]] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, Mapping):
                continue
            score = self._frame_item_relevance_score(item, frame_terms=frame_terms)
            if score > 0:
                scored.append((score, index, item))
        return [
            item
            for _score, _index, item in sorted(
                scored,
                key=lambda value: (-value[0], value[1]),
            )
        ]

    def _deterministic_frame_paper_role(self, paper_skim: PaperSkim | None) -> str:
        doc_role = str(getattr(paper_skim, "doc_role", "") or "")
        if doc_role == "experimental":
            return "primary_experiment"
        if doc_role == "review":
            return "review"
        return "uncertain"

    def _deterministic_frame_variables(
        self,
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
    ) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for candidate in (
            *objective.variables,
            *(getattr(paper_skim, "changed_variables", ()) if paper_skim else ()),
        ):
            self._append_unique_axis(values, seen, candidate)
        return values

    def _deterministic_frame_target_properties(
        self,
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
    ) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for candidate in (
            *objective.outcomes,
            *(getattr(paper_skim, "candidate_properties", ()) if paper_skim else ()),
        ):
            self._append_unique_axis(values, seen, candidate)
        return values

    def _frame_relevance_terms(
        self,
        *,
        objective: ResearchObjective,
        paper_skim: PaperSkim | None,
        profile: Any,
    ) -> tuple[tuple[str, int], ...]:
        terms: list[tuple[str, int]] = []

        def append_many(values: Iterable[Any], weight: int) -> None:
            for value in values:
                text = str(value or "").strip()
                if text:
                    terms.append((text, weight))

        append_many(objective.variables, 6)
        append_many(objective.outcomes, 6)
        append_many(objective.mechanisms, 3)
        append_many(objective.constraints, 3)
        append_many(objective.material_scope, 1)
        if paper_skim is not None:
            append_many(paper_skim.changed_variables, 3)
            append_many(paper_skim.candidate_properties, 3)
            append_many(paper_skim.candidate_processes, 2)
        if profile is not None:
            record = profile.to_record() if hasattr(profile, "to_record") else {}
            if isinstance(record, Mapping):
                append_many(record.get("materials") or (), 1)
                append_many(record.get("processes") or (), 2)
                append_many(record.get("properties") or (), 2)

        unique: list[tuple[str, int]] = []
        seen: set[str] = set()
        for term, weight in terms:
            key = self._axis_key(term)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append((term, weight))
        return tuple(unique)

    def _prioritize_frame_items(
        self,
        items: list[dict[str, Any]],
        *,
        frame_terms: tuple[tuple[str, int], ...],
        limit: int = _FRAME_SECTION_SNIPPET_LIMIT,
    ) -> list[dict[str, Any]]:
        scored = [
            (
                self._frame_item_relevance_score(item, frame_terms=frame_terms),
                index,
                item,
            )
            for index, item in enumerate(items)
        ]
        selected_indexes: set[int] = set()
        for score, index, _item in sorted(scored, key=lambda item: (-item[0], item[1])):
            if len(selected_indexes) >= limit:
                break
            if score <= 0:
                continue
            selected_indexes.add(index)
        if selected_indexes:
            return [dict(items[index]) for index in sorted(selected_indexes)]
        if len(selected_indexes) < limit:
            for _score, index, _item in scored:
                selected_indexes.add(index)
                if len(selected_indexes) >= limit:
                    break
        return [dict(items[index]) for index in sorted(selected_indexes)]

    def _frame_item_relevance_score(
        self,
        item: Mapping[str, Any],
        *,
        frame_terms: tuple[tuple[str, int], ...],
    ) -> int:
        text = self._frame_item_search_text(item)
        if not text:
            return 0
        axis_score = 0
        text_tokens = self._axis_token_set(self._axis_key(text))
        for term, weight in frame_terms:
            term_key = self._axis_key(term)
            term_tokens = self._axis_token_set(term_key)
            if not term_tokens:
                continue
            if self._source_text_mentions_axis(text, term):
                axis_score += weight * max(2, len(term_tokens))
                continue
            overlap = text_tokens & term_tokens
            if overlap:
                axis_score += weight * len(overlap)
        if axis_score <= 0:
            return 0
        return axis_score + self._frame_section_kind_score(text)

    def _frame_item_search_text(self, item: Mapping[str, Any]) -> str:
        pieces = [
            str(item.get("section_label") or ""),
            str(item.get("block_type") or ""),
            str(item.get("text") or ""),
            str(item.get("caption_text") or ""),
            str(item.get("heading_path") or ""),
            " ".join(str(value) for value in item.get("column_headers") or ()),
        ]
        for row in item.get("sample_rows") or ():
            if isinstance(row, (list, tuple)):
                pieces.append(" ".join(str(cell) for cell in row))
        return " ".join(piece for piece in pieces if piece.strip())

    def _frame_section_kind_score(self, text: str) -> int:
        lowered = text.casefold()
        if any(term in lowered for term in ("result", "discussion", "conclusion")):
            return 3
        if any(term in lowered for term in ("method", "experiment", "material")):
            return 2
        if "abstract" in lowered:
            return 1
        return 0

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

    def _build_objective_table_routing_hints(
        self,
        objective: ResearchObjective,
        *,
        tables: tuple[Any, ...],
    ) -> tuple[SourceSelectionHint, ...]:
        hints: list[SourceSelectionHint] = []
        excluded_document_ids = set(objective.excluded_document_ids)
        for table in tables:
            document_id = str(getattr(table, "document_id", "") or "")
            if document_id in excluded_document_ids:
                continue
            table_text = self._objective_table_search_text(table)
            property_search_pieces = [
                " ".join(
                    str(value)
                    for value in getattr(table, "column_headers", ()) or ()
                )
            ]
            for row in tuple(getattr(table, "table_matrix", ()) or ())[:6]:
                if isinstance(row, (list, tuple)):
                    property_search_pieces.append(
                        " ".join(str(cell) for cell in row)
                    )
            property_table_text = " ".join(
                piece for piece in property_search_pieces if piece.strip()
            )
            matched_outcomes = [
                axis
                for axis in objective.outcomes
                if self._source_text_mentions_axis(property_table_text, axis)
            ]
            matched_variable_axes = [
                axis
                for axis in objective.variables
                if self._source_text_mentions_axis(table_text, axis)
            ]
            if matched_outcomes:
                role = "result_table"
                strength = (
                    "strong"
                    if matched_variable_axes or len(matched_outcomes) > 1
                    else "medium"
                )
            elif matched_variable_axes:
                role = "condition_context"
                strength = "strong" if len(matched_variable_axes) > 1 else "medium"
            else:
                continue
            hints.append(
                SourceSelectionHint.from_mapping(
                    {
                        "table_id": str(getattr(table, "table_id", "") or ""),
                        "document_id": document_id,
                        "caption_text": getattr(table, "caption_text", None),
                        "role": role,
                        "strength": strength,
                        "matched_outcomes": matched_outcomes,
                        "matched_variables": matched_variable_axes,
                        "reason": self._build_objective_table_routing_reason(
                            role,
                            matched_outcomes=matched_outcomes,
                            matched_variable_axes=matched_variable_axes,
                        ),
                    }
                )
            )
        return tuple(hints)

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
        if self._source_text_mentions_single_axis(text, axis):
            return True
        normalized = self._normalize_property_label(axis)
        if not normalized:
            return False
        return any(
            self._source_text_mentions_single_axis(text, expanded_axis)
            for expanded_axis in _BROAD_PROPERTY_AXIS_EXPANSIONS.get(normalized, ())
        )

    def _source_text_mentions_single_axis(self, text: str, axis: str) -> bool:
        normalized_axis = self._normalize_property_label(axis)
        if normalized_axis in _OBJECTIVE_PAIRWISE_DENSITY_PROPERTIES:
            text = re.sub(
                r"\b(?:(?:laser|volumetric)\s+)?energy\s+densit(?:y|ies)\b",
                "",
                text,
                flags=re.IGNORECASE,
            )
        text_tokens = self._axis_token_set(self._axis_key(text))
        axis_tokens = self._axis_token_set(self._axis_key(axis))
        if not axis_tokens or not text_tokens:
            return False
        if normalized_axis:
            for alias, canonical_axes in _OBJECTIVE_SYMBOL_AXIS_ALIASES.items():
                alias_tokens = self._axis_token_set(alias)
                if alias_tokens and alias_tokens.issubset(text_tokens) and any(
                    self._axis_values_match(normalized_axis, canonical_axis)
                    for canonical_axis in canonical_axes
                ):
                    return True
            for alias, canonical in _OBJECTIVE_PROPERTY_ALIASES.items():
                if canonical != normalized_axis:
                    continue
                alias_tokens = self._axis_token_set(alias)
                if alias_tokens and alias_tokens.issubset(text_tokens):
                    return True
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
        matched_outcomes: list[str],
        matched_variable_axes: list[str],
    ) -> str:
        if role == "result_table":
            if matched_variable_axes:
                return "Table contains target property columns and variable process columns."
            return "Table contains target property columns."
        return "Table contains variable process columns and can provide condition context."

    def _get_objective_extractor(self) -> ObjectiveExtractor:
        if self._objective_extractor is None:
            self._objective_extractor = build_default_objective_extractor()
        return self._objective_extractor

    def _load_source_artifacts(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> SourceArtifactSet:
        artifacts = (
            self.source_artifact_repository.read_collection_artifacts(
                collection_id,
                build_id=build_id,
            )
            if build_id is not None
            else self.source_artifact_repository.read_collection_artifacts(collection_id)
        )
        if not artifacts.documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return SourceArtifactSet(
            documents=artifacts.documents,
            text_units=artifacts.text_units,
            blocks=artifacts.blocks,
            tables=artifacts.tables,
            table_rows=artifacts.table_rows,
            table_cells=artifacts.table_cells,
            figures=artifacts.figures,
        )

    def _build_paper_skim_payload(
        self,
        *,
        collection_id: str,
        document: Any,
        profile: Any,
        blocks: list[Any],
        tables: list[Any],
        figures: list[Any],
        document_tree: SourceDocumentTree | None = None,
    ) -> dict[str, Any]:
        ordered_blocks = sorted(
            blocks,
            key=lambda item: int(getattr(item, "block_order", 0) or 0),
        )
        headings = self._extract_headings_from_tree(document_tree)
        if not headings:
            headings = self._extract_headings(ordered_blocks)
        text_preview = self._build_text_preview_from_tree(document_tree)
        if not text_preview:
            text_preview = self._build_text_preview(document, ordered_blocks)
        return {
            "collection_id": collection_id,
            "document_id": document.document_id,
            "title": str(document.title or "")[:160],
            "document_profile": (
                {
                    "doc_type": profile.doc_type,
                    "parsing_warnings": list(profile.parsing_warnings)[:2],
                    "confidence": profile.confidence,
                }
                if profile
                else {}
            ),
            "text_preview": text_preview[:_SKIM_MODEL_TEXT_PREVIEW_CHARS],
            "headings": headings[:4],
            "table_captions": [
                {
                    "table_id": table.table_id,
                    "caption_text": str(table.caption_text or "")[:160],
                    "heading_path": str(table.heading_path or "")[:120],
                    "column_headers": [
                        str(value)[:80] for value in table.column_headers[:4]
                    ],
                }
                for table in sorted(tables, key=lambda item: item.table_order)[
                    :2
                ]
            ],
            "figure_captions": [
                {
                    "figure_id": figure.figure_id,
                    "caption_text": str(figure.caption_text or "")[:160],
                    "heading_path": str(figure.heading_path or "")[:120],
                }
                for figure in sorted(figures, key=lambda item: item.figure_order)[
                    :2
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

    def _extract_headings_from_tree(
        self,
        document_tree: SourceDocumentTree | None,
    ) -> list[str]:
        if document_tree is None:
            return []
        headings: list[str] = []
        seen: set[str] = set()
        for node in self._document_tree_nodes_in_order(document_tree):
            if node.node_type not in {"section", "references_section"}:
                continue
            heading = self._tree_section_label(node)
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

    def _build_text_preview_from_tree(
        self,
        document_tree: SourceDocumentTree | None,
    ) -> str:
        if document_tree is None:
            return ""
        parts = [
            str(node.text or "").strip()
            for node in self._document_tree_nodes_in_order(document_tree)
            if node.node_type in {"paragraph", "list_item"}
            and not self._tree_node_in_reference_branch(document_tree, node)
            and str(node.text or "").strip()
        ]
        return "\n\n".join(parts).strip()[:_SKIM_TEXT_PREVIEW_CHARS]

    def _document_tree_nodes_in_order(
        self,
        document_tree: SourceDocumentTree,
    ) -> list[Any]:
        return sorted(
            document_tree.nodes.values(),
            key=lambda node: (int(getattr(node, "order", 0) or 0), node.node_id),
        )

    def _tree_node_in_reference_branch(
        self,
        document_tree: SourceDocumentTree,
        node: Any,
    ) -> bool:
        current = node
        while current is not None:
            if current.node_type in {"references_section", "reference_entry"}:
                return True
            if getattr(current, "semantic_role", None) == "references":
                return True
            parent_id = getattr(current, "parent_id", None)
            current = document_tree.nodes.get(parent_id) if parent_id else None
        return False

    def _resolve_source_filename(self, document: Any) -> str | None:
        metadata = getattr(document, "metadata", {}) or {}
        for key in ("source_filename", "original_filename", "stored_filename"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return None

    def _canonicalize_research_objective_axes_with_llm(
        self,
        *,
        collection_id: str,
        extractor: ObjectiveExtractor,
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
        canonicalized = tuple(
            self._apply_axis_canonicalization(objective, axis_mapping)
            for objective in objectives
        )
        try:
            for objective in canonicalized:
                StructuredResearchObjective.model_validate(
                    {
                        key: value
                        for key, value in objective.to_record().items()
                        if key in StructuredResearchObjective.model_fields
                    }
                )
        except ValidationError:
            logger.warning(
                "Research objective axis canonicalization broke question roles; "
                "using original axes collection_id=%s",
                collection_id,
            )
            return objectives
        return canonicalized

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
            "variable": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.variables
            ),
            "outcome": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.outcomes
            ),
            "mechanism": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.mechanisms
            ),
            "constraint": self._unique_axis_values(
                value
                for objective in objectives
                for value in objective.constraints
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
        payload["variables"] = self._canonicalize_axis_values(
            objective.variables,
            axis_type="variable",
            axis_mapping=axis_mapping,
        )
        payload["outcomes"] = self._canonicalize_axis_values(
            objective.outcomes,
            axis_type="outcome",
            axis_mapping=axis_mapping,
        )
        payload["mechanisms"] = self._canonicalize_axis_values(
            objective.mechanisms,
            axis_type="mechanism",
            axis_mapping=axis_mapping,
        )
        payload["constraints"] = self._canonicalize_axis_values(
            objective.constraints,
            axis_type="constraint",
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
        extractor: ObjectiveExtractor,
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
            if len(source_objectives) > 1:
                shared_outcome_keys = set.intersection(
                    *(
                        self._axis_key_set(*objective.outcomes)
                        for objective in source_objectives
                    )
                )
                if not shared_outcome_keys:
                    return None
            material_scope = self._validated_merge_axes(
                tuple(group.material_scope),
                source_objectives=source_objectives,
                source_field="material_scope",
            )
            variables = self._validated_merge_axes(
                tuple(group.variables),
                source_objectives=source_objectives,
                source_field="variables",
            )
            outcomes = self._validated_merge_axes(
                tuple(group.outcomes),
                source_objectives=source_objectives,
                source_field="outcomes",
            )
            mechanisms = self._validated_merge_axes(
                tuple(group.mechanisms),
                source_objectives=source_objectives,
                source_field="mechanisms",
            )
            constraints = self._validated_merge_axes(
                tuple(group.constraints),
                source_objectives=source_objectives,
                source_field="constraints",
            )
            if any(
                values is None
                for values in (
                    material_scope,
                    variables,
                    outcomes,
                    mechanisms,
                    constraints,
                )
            ):
                return None

            if len(source_objectives) == 1:
                source = source_objectives[0]
                if str(group.question or "").strip() != source.question:
                    return None
                if group.requested_comparator != source.requested_comparator:
                    return None
            objective_payload = {
                "question": group.question,
                "material_scope": material_scope,
                "variables": variables,
                "outcomes": outcomes,
                "mechanisms": mechanisms,
                "constraints": constraints,
                "requested_comparator": group.requested_comparator,
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
            try:
                StructuredResearchObjective.model_validate(objective_payload)
            except ValidationError:
                return None
            objective = ResearchObjective.from_mapping(
                {
                    "collection_id": source_objectives[0].collection_id,
                    **objective_payload,
                }
            )
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
        objective_by_id: dict[str, ResearchObjective] = {}
        for objective in objectives:
            existing = objective_by_id.get(objective.objective_id)
            if existing is not None:
                if existing.to_record() != objective.to_record():
                    raise ValueError(
                        "conflicting research objectives share objective_id: "
                        f"{objective.objective_id}"
                    )
                continue
            objective_by_id[objective.objective_id] = objective
            unique_objectives.append(objective)
        return tuple(unique_objectives)

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
        if self._axis_alias_matches_canonical(left, right):
            return True
        left_key = self._normalize_property_label(left) or self._axis_key(left)
        right_key = self._normalize_property_label(right) or self._axis_key(right)
        return right_key in _OBJECTIVE_AXIS_SYNONYMS.get(left_key, ()) or (
            left_key in _OBJECTIVE_AXIS_SYNONYMS.get(right_key, ())
        )

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
            if len(short) < 2 or len(short) > 8 or not short.isalpha():
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
