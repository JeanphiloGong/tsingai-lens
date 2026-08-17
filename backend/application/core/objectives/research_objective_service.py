from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from hashlib import sha1
from typing import Any, Callable, Iterable, Mapping

from openai import APIConnectionError, APIStatusError

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.objectives import property_matching
from application.core.objectives.analysis.source_screening import (
    PaperAnalysisFrame,
    screen_sources,
)
from application.core.objectives.evidence_extraction import ExtractedEvidenceDraft
from application.core.objectives.evidence_routing import EvidenceCandidate
from application.core.objectives.extraction import (
    ObjectiveExtractor,
    build_default_objective_extractor,
)
from application.core.objectives.finding_synthesis_service import (
    FindingSynthesisService,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.paper_facts.extraction import (
    PaperFactsExtractor,
    build_default_paper_facts_extractor,
)
from application.source.artifact_input_service import load_document_tree
from application.source.collection_service import CollectionService
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperSkim,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    ResearchObjective,
    normalize_objective_terms,
)
from domain.ports import (
    ObjectiveRepository,
    PaperFactRepository,
    SourceArtifactRepository,
)
from domain.source import SourceDocument, SourceDocumentTree

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
def _transient_text(value: Any) -> str:
    return str(value or "").strip()


def _transient_optional_text(value: Any) -> str | None:
    text = _transient_text(value)
    return text or None


def _provider_is_temporarily_unavailable(error: Exception) -> bool:
    if isinstance(error, APIConnectionError):
        return True
    if not isinstance(error, APIStatusError):
        return False
    status_code = int(error.status_code)
    return status_code in {408, 409, 429} or status_code >= 500


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
        paper_skim_service: PaperSkimService,
        objective_candidate_service: ObjectiveCandidateService,
        objective_extractor: ObjectiveExtractor | None = None,
        paper_facts_extractor: PaperFactsExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._objective_extractor = objective_extractor
        self._paper_facts_extractor = paper_facts_extractor
        self.paper_fact_repository = paper_fact_repository
        self.objective_repository = objective_repository
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service
        self.finding_synthesis_service = finding_synthesis_service
        self.paper_skim_service = paper_skim_service
        self.objective_candidate_service = objective_candidate_service

    def discover_and_replace_objective_candidates(
        self,
        collection_id: str,
        progress_callback: ProgressCallback | None = None,
        *,
        build_id: str,
    ) -> ObjectiveFactSet:
        source_inputs = self._load_objective_source_inputs(
            collection_id,
            build_id=build_id,
        )
        documents = source_inputs["documents"]
        extractor = source_inputs["extractor"]
        paper_skims = self.paper_skim_service.build_collection_paper_skims(
            collection_id,
            documents=documents,
            profiles_by_document_id=source_inputs["profiles_by_document_id"],
            document_trees_by_document_id=source_inputs[
                "document_trees_by_document_id"
            ],
            extractor=extractor,
            progress_callback=progress_callback,
        )
        self.objective_repository.replace(
            collection_id,
            build_id,
            ObjectiveFactSet(
                research_objectives_ready=False,
                paper_skims=paper_skims,
                study_dispositions=tuple(
                    PaperStudyDisposition(
                        document_id=skim.document_id,
                        study_id=study.study_id,
                        relationship_id=relationship.relationship_id,
                        status=PaperStudyDispositionStatus.PENDING,
                    )
                    for skim in paper_skims
                    for study in skim.studies
                    for relationship in study.relationships
                ),
            ),
        )
        candidate_facts = self.objective_candidate_service.discover_candidate_facts(
            collection_id,
            paper_skims=paper_skims,
            extractor=extractor,
            progress_callback=progress_callback,
        )
        self.objective_repository.replace(
            collection_id,
            build_id,
            candidate_facts,
        )
        research_objectives = candidate_facts.research_objectives
        logger.info(
            "Research objective candidates finished collection_id=%s paper_skim_count=%s objective_count=%s",
            collection_id,
            len(paper_skims),
            len(research_objectives),
        )
        return candidate_facts

    def generate_objective_analysis_artifacts(
        self,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveAnalysisArtifacts:
        if analysis.collection_id != collection_id:
            raise ValueError("analysis belongs to another collection")
        active_objective = self.objective_repository.read_objective(
            collection_id, analysis.objective_id
        )
        if active_objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        if active_objective.active_analysis_version != analysis.analysis_version:
            raise ValueError("analysis is not the active objective version")
        objective_inputs = self._build_objective_analysis_inputs(
            collection_id,
            build_id=analysis.source_build_id,
        )
        source_objective = next(
            (
                item
                for item in objective_inputs["research_objectives"]
                if item.objective_id == analysis.objective_id
            ),
            None,
        )
        if source_objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        objective = replace(
            source_objective,
            confirmation_status=active_objective.confirmation_status,
            active_analysis_version=active_objective.active_analysis_version,
            published_analysis_version=active_objective.published_analysis_version,
            created_at=active_objective.created_at,
            updated_at=active_objective.updated_at,
        )
        paper_frames = screen_sources(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            objectives=(objective,),
            paper_skims=objective_inputs["paper_skims"],
            documents=objective_inputs["documents"],
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
        evidence_records = self._analysis_evidence_records(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            drafts=evidence_drafts,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            figures_by_document_id=objective_inputs["figures_by_document_id"],
        )
        contributions = self._analysis_contributions(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            frames=paper_frames,
            routes=evidence_candidates,
            evidence_records=evidence_records,
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
        objective: ResearchObjective,
        frames: tuple[PaperAnalysisFrame, ...],
        routes: tuple[EvidenceCandidate, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
    ) -> tuple[PaperContribution, ...]:
        routed_sources_by_document: dict[str, set[tuple[str, str]]] = {}
        for route in routes:
            if not route.extractable or route.role == "low_value_or_irrelevant":
                continue
            routed_sources_by_document.setdefault(route.document_id, set()).add(
                (route.source_kind, route.source_ref)
            )
        evidence_by_document: dict[str, list[ObjectiveEvidence]] = {}
        for evidence in evidence_records:
            evidence_by_document.setdefault(evidence.document_id, []).append(evidence)
            routed_sources_by_document.setdefault(evidence.document_id, set()).add(
                (evidence.source_kind, evidence.source_ref)
            )

        contributions: list[PaperContribution] = []
        for frame in frames:
            excluded = frame.relevance == "irrelevant" or frame.paper_role == "irrelevant"
            document_evidence = tuple(
                evidence_by_document.get(frame.document_id, ())
            )
            routed_sources = routed_sources_by_document.get(frame.document_id, set())
            extracted_sources = {
                (evidence.source_kind, evidence.source_ref)
                for evidence in document_evidence
                if evidence.selection_status == "extracted"
            }
            failed_sources = {
                (evidence.source_kind, evidence.source_ref)
                for evidence in document_evidence
                if evidence.selection_status == "failed"
            }
            comparable_evidence_count = sum(
                self.finding_synthesis_service.is_comparable_result_evidence(
                    objective,
                    evidence,
                )
                for evidence in document_evidence
            )
            if excluded:
                analysis_status = "excluded"
                evidence_disposition = "excluded"
                routed_source_count = 0
                extracted_source_count = 0
                comparable_evidence_count = 0
                failed_source_count = 0
                evidence_reason = frame.background or (
                    "Paper is not relevant to this objective."
                )
            else:
                routed_source_count = len(routed_sources)
                extracted_source_count = len(extracted_sources)
                failed_source_count = len(failed_sources)
                if routed_source_count == 0:
                    analysis_status = "analyzed"
                    evidence_disposition = "no_routable_evidence"
                    evidence_reason = (
                        "No source in this paper was selected for Objective extraction."
                    )
                elif extracted_source_count == 0 and failed_source_count > 0:
                    analysis_status = "failed"
                    evidence_disposition = "extraction_failed"
                    evidence_reason = (
                        f"{failed_source_count} selected source(s) failed extraction."
                    )
                elif comparable_evidence_count == 0:
                    analysis_status = "analyzed"
                    evidence_disposition = "no_comparable_evidence"
                    evidence_reason = (
                        "Selected sources produced no comparable direct result for "
                        "this Objective."
                    )
                else:
                    analysis_status = "analyzed"
                    evidence_disposition = "comparable_evidence"
                    evidence_reason = (
                        f"{failed_source_count} selected source(s) failed extraction; "
                        "comparable Evidence survived."
                        if failed_source_count
                        else None
                    )
            warnings = (
                (f"{failed_source_count} selected source(s) failed extraction.",)
                if failed_source_count
                else ()
            )
            contributions.append(
                PaperContribution(
                    collection_id=collection_id,
                    objective_id=analysis.objective_id,
                    analysis_version=analysis.analysis_version,
                    document_id=frame.document_id,
                    analysis_status=analysis_status,
                    relevance=frame.relevance,
                    paper_role=frame.paper_role,
                    contribution_summary=frame.background,
                    material_match=frame.material_match,
                    changed_variables=frame.changed_variables,
                    measured_property_scope=frame.measured_property_scope,
                    test_environment_scope=frame.test_environment_scope,
                    exclusion_reason=evidence_reason if excluded else None,
                    warnings=warnings,
                    confidence=1.0 if frame.relevance == "high" else 0.7,
                    evidence_disposition=evidence_disposition,
                    routed_source_count=routed_source_count,
                    extracted_source_count=extracted_source_count,
                    comparable_evidence_count=comparable_evidence_count,
                    failed_source_count=failed_source_count,
                    evidence_disposition_reason=evidence_reason,
                )
            )
        return tuple(contributions)

    def _analysis_evidence_records(
        self,
        *,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        objective: ResearchObjective,
        drafts: tuple[ExtractedEvidenceDraft, ...],
        blocks_by_document_id: Mapping[str, list[Any]],
        tables_by_document_id: Mapping[str, list[Any]],
        figures_by_document_id: Mapping[str, list[Any]],
    ) -> tuple[ObjectiveEvidence, ...]:
        records: list[ObjectiveEvidence] = []
        seen_evidence_ids: set[str] = set()
        record_index_by_source: dict[tuple[str, str, str, str], int] = {}
        for source_draft in drafts:
            try:
                draft = self._canonical_objective_evidence_axes(
                    source_draft,
                    objective=objective,
                )
            except ValueError as exc:
                payload = source_draft.to_record()
                payload.update(
                    {
                        "evidence_role": "irrelevant",
                        "selection_status": "failed",
                        "changed_variables": [],
                        "comparison": None,
                        "reported_result": None,
                        "attribution_scope": "not_attributable",
                        "resolution_status": "unknown",
                        "failure_reason": f"ValueError: {exc}"[:1000],
                        "confidence": 0.0,
                    }
                )
                draft = ExtractedEvidenceDraft.from_mapping(payload)
            source = self._canonical_evidence_source(
                draft,
                blocks_by_document_id=blocks_by_document_id,
                tables_by_document_id=tables_by_document_id,
                figures_by_document_id=figures_by_document_id,
            )
            if source is None:
                raise RuntimeError(
                    "Evidence Source cannot be resolved: "
                    f"evidence_id={draft.evidence_id} "
                    f"document_id={draft.document_id} "
                    f"source_kind={draft.source_kind} "
                    f"source_ref={draft.source_ref}"
                )
            if draft.evidence_id in seen_evidence_ids:
                continue
            seen_evidence_ids.add(draft.evidence_id)
            evidence_role = self._canonical_evidence_role(draft)
            candidate = ObjectiveEvidence(
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
                selection_status=draft.selection_status,
                selection_reason=draft.selection_reason,
                changed_variables=draft.changed_variables,
                comparison=draft.comparison,
                reported_result=draft.reported_result,
                attribution_scope=draft.attribution_scope,
                scientific_context=draft.scientific_context,
                anchor_ids=draft.evidence_anchor_ids,
                resolution_status=(
                    draft.resolution_status
                    if draft.selection_status == "failed"
                    else (
                        draft.resolution_status
                        if draft.resolution_status in {"resolved", "partial"}
                        else "partial"
                    )
                ),
                failure_reason=draft.failure_reason,
                confidence=draft.confidence,
            )
            source_key = (
                candidate.objective_id,
                candidate.document_id,
                candidate.source_kind,
                candidate.source_ref,
            )
            existing_index = record_index_by_source.get(source_key)
            if existing_index is None:
                record_index_by_source[source_key] = len(records)
                records.append(candidate)
                continue
            existing = records[existing_index]
            if self._objective_evidence_source_preference(
                candidate
            ) > self._objective_evidence_source_preference(existing):
                records[existing_index] = candidate
                kept, discarded = candidate, existing
            else:
                kept, discarded = existing, candidate
            logger.warning(
                "Duplicate Objective Evidence Source resolved "
                "objective_id=%s document_id=%s source_kind=%s source_ref=%s "
                "kept_evidence_id=%s discarded_evidence_id=%s",
                candidate.objective_id,
                candidate.document_id,
                candidate.source_kind,
                candidate.source_ref,
                kept.evidence_id,
                discarded.evidence_id,
            )
        return tuple(records)

    @staticmethod
    def _objective_evidence_source_preference(
        evidence: ObjectiveEvidence,
    ) -> tuple[int, int, int, int, int, int, int, int, float]:
        role_rank = {
            "direct_result": 6,
            "contradictory_result": 6,
            "mechanism_context": 5,
            "condition_context": 4,
            "characterization_context": 3,
            "background_context": 2,
            "irrelevant": 1,
        }
        context_count = sum(
            len(getattr(evidence.scientific_context, group))
            for group in ("material", "sample", "process", "test")
        )
        resolution_rank = {
            "resolved": 3,
            "partial": 2,
            "unknown": 1,
            "unresolved": 1,
            "skipped": 0,
        }
        return (
            1 if evidence.selection_status == "extracted" else 0,
            role_rank.get(evidence.evidence_role, 0),
            1 if evidence.reported_result is not None else 0,
            1 if evidence.comparison is not None else 0,
            len(evidence.changed_variables),
            context_count,
            resolution_rank.get(evidence.resolution_status, 0),
            len(evidence.failure_reason or ""),
            evidence.confidence,
        )

    @staticmethod
    def _canonical_objective_evidence_axes(
        draft: ExtractedEvidenceDraft,
        *,
        objective: ResearchObjective,
    ) -> ExtractedEvidenceDraft:
        if draft.selection_status == "failed":
            return draft

        payload = draft.to_record()

        def canonical(value: Any, axes: tuple[str, ...]) -> tuple[str, str | None]:
            resolved = property_matching.resolve_objective_axis(value, axes)
            return resolved or str(value or "").strip(), resolved

        canonical_variables: list[dict[str, Any]] = []
        objective_variable_indexes: dict[str, int] = {}
        for variable in payload["changed_variables"]:
            variable = dict(variable)
            variable["name"], resolved = canonical(
                variable.get("name"),
                objective.variables,
            )
            if resolved is None:
                canonical_variables.append(variable)
                continue
            axis_key = property_matching.axis_key(resolved)
            existing_index = objective_variable_indexes.get(axis_key)
            if existing_index is None:
                objective_variable_indexes[axis_key] = len(canonical_variables)
                canonical_variables.append(variable)
                continue
            existing = canonical_variables[existing_index]
            for field in ("baseline_value", "target_value", "unit"):
                current = existing.get(field)
                candidate = variable.get(field)
                if current in (None, ""):
                    if candidate not in (None, ""):
                        existing[field] = candidate
                    continue
                if candidate in (None, ""):
                    continue
                if str(current).strip().casefold() != str(candidate).strip().casefold():
                    raise ValueError(
                        f"conflicting values for Objective axis {resolved}: {field}"
                    )
        payload["changed_variables"] = canonical_variables
        comparison = payload.get("comparison")
        if isinstance(comparison, dict):
            comparison["axis_names"] = list(
                dict.fromkeys(
                    canonical(axis, objective.variables)[0]
                    for axis in comparison.get("axis_names") or ()
                )
            )
        result = payload.get("reported_result")
        if isinstance(result, dict):
            source_outcome = result.get("outcome")
            canonical_outcome = canonical(source_outcome, objective.outcomes)[1]
            if canonical_outcome is None:
                broad_matches = tuple(
                    axis
                    for axis in objective.outcomes
                    if property_matching.property_matches_target_axes(
                        source_outcome,
                        target_axes=(
                            axis,
                            *property_matching.broad_outcome_expansions(axis),
                        ),
                    )
                )
                if len(broad_matches) == 1:
                    canonical_outcome = broad_matches[0]
            result["outcome"] = canonical_outcome or str(source_outcome or "").strip()
        if (
            payload.get("attribution_scope") == "joint_effect"
            and len(canonical_variables) == 1
        ):
            payload["attribution_scope"] = "isolated_effect"
        return ExtractedEvidenceDraft.from_mapping(payload)

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
            documents = self._load_source_documents(
                collection_id, build_id=build_id
            )
            profiles = self.document_profile_service.read_document_profiles(
                collection_id,
                build_id=build_id,
            )
        except (FileNotFoundError, DocumentProfilesNotReadyError) as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

        return {
            "documents": documents,
            "profiles_by_document_id": {
                profile.document_id: profile
                for profile in profiles
            },
            "blocks_by_document_id": {
                document.document_id: list(document.blocks)
                for document in documents
            },
            "tables_by_document_id": {
                document.document_id: list(document.tables)
                for document in documents
            },
            "table_cells_by_document_id": {
                document.document_id: list(document.table_cells)
                for document in documents
            },
            "figures_by_document_id": {
                document.document_id: list(document.figures)
                for document in documents
            },
            "document_trees_by_document_id": {
                document.document_id: load_document_tree(
                    collection_id,
                    document.document_id,
                    self.source_artifact_repository,
                    build_id=build_id,
                )
                for document in documents
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
        target_axes = property_matching.objective_outcomes(objective_context)
        if not target_axes:
            return evidence_items

        failed_units = tuple(
            unit for unit in evidence_items if unit.selection_status == "failed"
        )
        target_units = tuple(
            unit
            for unit in evidence_items
            if unit.selection_status != "failed"
            if self._objective_evidence_matches_target_property(
                unit,
                target_axes=target_axes,
            )
        )
        if not target_units:
            return failed_units

        target_document_ids = {unit.document_id for unit in target_units}
        selected_ids = {
            unit.evidence_id for unit in (*failed_units, *target_units)
        }
        selected = [*failed_units, *target_units]
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
        return property_matching.property_matches_target_axes(
            unit.reported_result.outcome,
            target_axes=target_axes,
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
            objective_context = objective
            source_candidates = self._build_route_source_candidates(
                frame=frame,
                objective_context=objective_context,
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
        if evidence_role == "direct_support":
            updated["role"] = "current_experimental_evidence"
            updated["extractable"] = True
        elif evidence_role == "irrelevant":
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
        return any(
            property_matching.source_text_mentions_axis(text, axis)
            for axis in axes
        )

    def _objective_header_matches_any_axis(
        self,
        header: str,
        axes: tuple[str, ...],
    ) -> bool:
        property_name, _unit = self._split_property_unit(header)
        normalized_property = property_matching.normalize_property_label(
            property_name
        )
        if normalized_property and any(
            property_matching.axis_values_match(normalized_property, axis)
            for axis in axes
        ):
            return True
        if any(property_matching.axis_values_match(header, axis) for axis in axes):
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
        extractable_routes = self._document_round_robin_objective_routes(
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
        llm_evidence_unavailable: dict[tuple[str, str], Exception] = {}
        llm_table_repair_unavailable: dict[tuple[str, str], Exception] = {}
        document_metadata = self._progress_document_metadata(
            document_trees_by_document_id=document_trees_by_document_id,
        )
        for route_position, route in enumerate(extractable_routes, start=1):
            document_key = (route.objective_id, route.document_id)
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
                raise RuntimeError(
                    "selected Evidence Source is missing: "
                    f"objective_id={route.objective_id} "
                    f"document_id={route.document_id} "
                    f"source_kind={route.source_kind} "
                    f"source_ref={route.source_ref}"
                )
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
            source, table_repair_error = self._repair_objective_table_source_if_needed(
                collection_id=collection_id,
                route=route,
                source=source,
                unavailable_error=llm_table_repair_unavailable.get(document_key),
            )
            if (
                table_repair_error is not None
                and _provider_is_temporarily_unavailable(table_repair_error)
            ):
                llm_table_repair_unavailable.setdefault(
                    document_key,
                    table_repair_error,
                )
            payload["source"] = self._objective_evidence_prompt_source(source)
            route_unit_start = len(units)
            if (
                table_repair_error is not None
                and self._objective_table_source_needs_llm_structural_repair(
                    route=route,
                    source=source,
                )
            ):
                failed_unit = self._failed_objective_evidence_draft(
                    route=route,
                    error=table_repair_error,
                )
                if failed_unit.evidence_id not in seen:
                    seen.add(failed_unit.evidence_id)
                    units.append(failed_unit)
                continue
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
            needs_model_extraction = (
                (not route_records or needs_structural_repair)
                and not self._objective_table_route_should_skip_llm_fallback(route)
            )
            if needs_model_extraction:
                extraction_error = llm_evidence_unavailable.get(document_key)
                if extraction_error is None:
                    try:
                        parsed = extractor.extract_objective_evidence(payload)
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
                    except Exception as exc:
                        extraction_error = exc
                        provider_unavailable = _provider_is_temporarily_unavailable(exc)
                        if provider_unavailable:
                            llm_evidence_unavailable[document_key] = exc
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
                            provider_unavailable,
                        )
                    else:
                        route_records = self._objective_merge_table_repair_records(
                            deterministic_records=route_records,
                            llm_records=llm_route_records,
                        )
                if extraction_error is not None:
                    failed_unit = self._failed_objective_evidence_draft(
                        route=route,
                        error=extraction_error,
                    )
                    if failed_unit.evidence_id not in seen:
                        seen.add(failed_unit.evidence_id)
                        units.append(failed_unit)
                    if not route_records:
                        continue
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
    def _failed_objective_evidence_draft(
        *,
        route: EvidenceCandidate,
        error: Exception,
    ) -> ExtractedEvidenceDraft:
        identity = "|".join(
            (
                route.objective_id,
                route.document_id,
                route.source_kind,
                route.source_ref,
                "failed",
            )
        )
        reason = f"{error.__class__.__name__}: {str(error) or 'extraction failed'}"
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": (
                    f"oev_failed_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
                ),
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "source_kind": route.source_kind,
                "source_ref": route.source_ref,
                "evidence_role": "irrelevant",
                "selection_status": "failed",
                "selection_reason": route.reason,
                "attribution_scope": "not_attributable",
                "source_refs": [
                    {
                        "source_kind": route.source_kind,
                        "source_ref": route.source_ref,
                    }
                ],
                "resolution_status": "unknown",
                "failure_reason": reason[:1000],
                "confidence": 0.0,
            }
        )

    @staticmethod
    def _enrich_objective_scope_context(
        units: tuple[ExtractedEvidenceDraft, ...],
        *,
        paper_skims: tuple[PaperSkim, ...],
    ) -> tuple[ExtractedEvidenceDraft, ...]:
        skim_by_document_id = {item.document_id: item for item in paper_skims}
        enriched: list[ExtractedEvidenceDraft] = []
        for unit in units:
            if unit.selection_status == "failed":
                enriched.append(unit)
                continue
            paper_skim = skim_by_document_id.get(unit.document_id)
            context = unit.scientific_context.to_record()
            if not context["material"]:
                material_values = ResearchObjectiveService._paper_skim_study_values(
                    paper_skim,
                    "material_scope",
                )
                context["material"] = [
                    {"name": "material", "value": value, "unit": None}
                    for value in material_values
                ]
            process_values = ResearchObjectiveService._paper_skim_study_values(
                paper_skim,
                "process_context",
            )
            if process_values:
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
                            for value in process_values
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
        route: EvidenceCandidate,
        source: dict[str, Any],
        unavailable_error: Exception | None = None,
    ) -> tuple[dict[str, Any], Exception | None]:
        if not self._objective_table_source_needs_llm_structural_repair(
            route=route,
            source=source,
        ):
            return source, None
        if unavailable_error is not None:
            return source, unavailable_error
        repair_payload = self._build_objective_table_matrix_repair_payload(
            route=route,
            source=source,
        )
        try:
            parsed = self._get_paper_facts_extractor().repair_table_matrix(
                repair_payload
            )
        except Exception as exc:
            logger.exception(
                "Research objective table matrix repair failed collection_id=%s source_ref=%s objective_id=%s document_id=%s source_ref=%s",
                collection_id,
                route.source_ref,
                route.objective_id,
                route.document_id,
                route.source_ref,
            )
            return source, exc
        repaired_matrix = self._validated_objective_repaired_table_matrix(
            source=source,
            repaired_table_matrix=getattr(parsed, "repaired_table_matrix", None),
        )
        if not repaired_matrix:
            return source, ValueError(
                "table matrix repair returned no usable matrix"
            )
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
        if (
            repaired_matrix == original_matrix
            and self._objective_table_matrix_has_structural_fragments(
                original_matrix
            )
        ):
            return source, ValueError(
                "table matrix repair left the fragmented matrix unchanged"
            )
        if self._objective_table_matrix_has_structural_fragments(repaired_matrix):
            return source, ValueError(
                "table matrix repair returned a structurally fragmented matrix"
            )
        repaired_source = dict(source)
        repaired_source["raw_table_matrix"] = source.get("table_matrix", [])
        repaired_source["table_matrix"] = repaired_matrix
        repaired_source["table_matrix_structural_repair_applied"] = True
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
        return repaired_source, None

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
            families = property_matching.objective_method_families(objective_context)
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

    @staticmethod
    def _objective_source_refs_with_supports(
        source_refs: tuple[dict[str, Any], ...],
        *supports: str,
    ) -> tuple[dict[str, Any], ...]:
        annotated: list[dict[str, Any]] = []
        for source_ref in source_refs:
            record = dict(source_ref)
            record["supports"] = list(
                dict.fromkeys(
                    (
                        *(support for support in supports if support),
                        *(
                            str(value)
                            for value in source_ref.get("supports", ())
                            if str(value).strip()
                        ),
                    )
                )
            )
            annotated.append(record)
        return tuple(annotated)


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

    @staticmethod
    def _objective_descriptive_result(
        unit: ExtractedEvidenceDraft,
        *,
        reason: str,
    ) -> ExtractedEvidenceDraft:
        payload = unit.to_record()
        payload["changed_variables"] = []
        payload["comparison"] = None
        payload["attribution_scope"] = "descriptive_only"
        payload["resolution_status"] = "partial"
        payload["selection_reason"] = reason
        payload["source_refs"] = [
            {
                **ref,
                "supports": [
                    value
                    for value in ref.get("supports", ())
                    if not str(value).startswith("comparison")
                    and value != "changed_variables"
                ],
            }
            for ref in unit.source_refs
        ]
        return ExtractedEvidenceDraft.from_mapping(payload)

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
            pending_process_binding = bool(
                unit.source_kind == "text_window"
                and unit.reported_result is not None
                and comparison is not None
                and not unit.changed_variables
            )
            source_claims_effect = bool(
                unit.source_kind == "text_window"
                and unit.reported_result is not None
                and comparison is not None
                and unit.attribution_scope in {"isolated_effect", "joint_effect"}
                and scope in process_context_scopes
            )
            if pending_process_binding or source_claims_effect:
                if scope not in process_context_scopes:
                    bound.append(
                        self._objective_descriptive_result(
                            unit,
                            reason=(
                                "Grounded result has no same-document process "
                                "context for its comparison groups."
                            ),
                        )
                    )
                    continue
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
                    if pending_process_binding:
                        bound.append(
                            self._objective_descriptive_result(
                                unit,
                                reason=(
                                    "Grounded result comparison groups do not bind "
                                    "to unambiguous same-document process conditions."
                                ),
                            )
                        )
                        continue
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
                    property_matching.normalize_property_label(item.name)
                    or self._objective_column_key(item.name): item
                    for item in baseline_context.scientific_context.process
                }
                target_process = {
                    property_matching.normalize_property_label(item.name)
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
                            self._objective_source_refs_with_supports(
                                baseline_context.source_refs,
                                "changed_variables",
                                "comparison.axis_names",
                            ),
                            self._objective_source_refs_with_supports(
                                target_context.source_refs,
                                "changed_variables",
                                "comparison.axis_names",
                            ),
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
                    property_matching.normalize_objective_unit_property(
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
                and property_matching.process_column_axis_keys(column)
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
                for axis in property_matching.process_column_axis_keys(column)
                if any(
                    property_matching.axis_values_match(axis, objective_axis)
                    for objective_axis in objective_context.variables
                )
            }
            if len(symbol_axes) == 1:
                return next(iter(symbol_axes))
        role_label = property_matching.normalize_property_label(role)
        if (
            role_label
            and property_matching.process_role_is_specific(role_label)
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

    def _objective_label_matches_variables(
        self,
        label: Any,
        *,
        objective_context: ResearchObjective,
    ) -> bool:
        label_text = str(label or "").strip()
        if not label_text:
            return False
        label_axis_keys = property_matching.process_column_axis_keys(label_text)
        label_tokens = property_matching.axis_tokens(
            property_matching.axis_key(label_text)
        )
        for axis in objective_context.variables:
            axis_text = str(axis or "").strip()
            if not axis_text:
                continue
            axis_key = property_matching.normalize_property_label(axis_text)
            if axis_key and any(
                label_axis_key == axis_key
                or property_matching.axis_label_is_mentioned(label_axis_key, axis_key)
                for label_axis_key in label_axis_keys
            ):
                return True
            if (
                property_matching.axis_values_match(label_text, axis_text)
                or property_matching.axis_label_is_mentioned(label_text, axis_text)
                or property_matching.axis_label_is_mentioned(axis_text, label_text)
            ):
                return True
            axis_tokens = property_matching.axis_tokens(
                property_matching.axis_key(axis_text)
            )
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
                    "reduce",
                    "reduced",
                    "reduces",
                    "reducing",
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
            source_text = self._objective_source_grounding_text(source)
            result_grounding_errors = self._objective_evidence_result_grounding_errors(
                record,
                source=source,
                source_text=source_text,
            )
            if result_grounding_errors:
                return ()
            variable_grounding_errors = (
                self._objective_evidence_variable_grounding_errors(
                    record,
                    source=source,
                    source_text=source_text,
                )
            )
            comparison_grounding_errors = (
                self._objective_evidence_comparison_grounding_errors(
                    record,
                    source_text=source_text,
                )
            )
            if (
                not variable_grounding_errors
                and not comparison_grounding_errors
                and source.get("source_kind") == "table"
                and source.get("table_matrix")
                and not self._objective_extracted_table_result_is_row_grounded(
                    record,
                    source=source,
                )
            ):
                return ()
            if variable_grounding_errors or comparison_grounding_errors:
                record["changed_variables"] = []
                record["resolution_status"] = "partial"
                if comparison_grounding_errors:
                    record["comparison"] = None
                    record["attribution_scope"] = "descriptive_only"
                    record["selection_reason"] = (
                        "Grounded result retained without a source-grounded "
                        "comparison binding."
                    )
                else:
                    comparison = record.get("comparison")
                    record["attribution_scope"] = (
                        "association_only"
                        if isinstance(comparison, Mapping)
                        and comparison.get("comparable") is True
                        else "not_attributable"
                    )
                    record["selection_reason"] = (
                        "Grounded result retained pending same-study process "
                        "context binding."
                    )
            outcome = property_matching.normalize_objective_unit_property(
                reported_result.get("outcome"),
                objective_context=objective_context,
            )
            if not outcome:
                return ()
            if (
                objective_context is not None
                and objective_context.outcomes
                and not property_matching.property_matches_target_axes(
                    outcome,
                    target_axes=property_matching.objective_outcomes(objective_context),
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
        supported_fields: list[str] = []
        if record.get("changed_variables"):
            supported_fields.extend(("changed_variables", "comparison.axis_names"))
        if isinstance(record.get("comparison"), Mapping):
            supported_fields.append("comparison.labels")
        if isinstance(record.get("reported_result"), Mapping):
            supported_fields.append("reported_result")
        scientific_context = record.get("scientific_context")
        if isinstance(scientific_context, Mapping):
            supported_fields.extend(
                f"scientific_context.{group}"
                for group in ("material", "sample", "process", "test")
                if scientific_context.get(group)
            )
        record.update(
            {
                "objective_id": route.objective_id,
                "document_id": route.document_id,
                "source_refs": self._objective_route_source_refs(
                    route=route,
                    source=source,
                    supports=tuple(supported_fields),
                ),
            }
        )
        if record.get("confidence") is None:
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
            or not property_matching.axis_values_match(
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
            and property_matching.axis_label_is_mentioned(
                source_text,
                str(label).strip(),
            )
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
                and property_matching.axis_label_is_mentioned(source_text, label_text)
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
        return not self._objective_evidence_grounding_errors(record, source=source)

    def _objective_evidence_grounding_errors(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
    ) -> tuple[str, ...]:
        source_text = self._objective_source_grounding_text(source)
        if not source_text:
            return ("source has no text or table content for grounding",)
        errors = [
            *self._objective_evidence_variable_grounding_errors(
                record,
                source=source,
                source_text=source_text,
            ),
            *self._objective_evidence_comparison_grounding_errors(
                record,
                source_text=source_text,
            ),
            *self._objective_evidence_result_grounding_errors(
                record,
                source=source,
                source_text=source_text,
            ),
        ]
        if (
            not errors
            and source.get("source_kind") == "table"
            and source.get("table_matrix")
            and record.get("reported_result") is not None
            and not self._objective_extracted_table_result_is_row_grounded(
                record,
                source=source,
            )
        ):
            errors.append(
                "table_rows do not bind the reported result to the selected "
                "comparison endpoints in SOURCE"
            )
        return tuple(errors)

    def _objective_evidence_variable_grounding_errors(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
        source_text: str,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        for position, variable in enumerate(record.get("changed_variables") or ()):
            path = f"changed_variables[{position}]"
            if not isinstance(variable, Mapping):
                errors.append(f"{path} is not a structured variable")
                continue
            if not self._objective_axis_is_source_grounded(
                variable.get("name"),
                source=source,
                source_text=source_text,
            ):
                errors.append(
                    f"{path}.name={variable.get('name')!r} is not grounded in SOURCE"
                )
            for field in ("baseline_value", "target_value"):
                value = variable.get(field)
                if not self._objective_value_is_source_grounded(value, source_text):
                    errors.append(
                        f"{path}.{field}={value!r} is not grounded in SOURCE"
                    )
            variable_unit = str(variable.get("unit") or "").strip()
            if variable_unit and self._objective_column_key(
                variable_unit
            ) not in self._objective_column_key(source_text):
                errors.append(
                    f"{path}.unit={variable_unit!r} is not grounded in SOURCE"
                )
        return tuple(errors)

    def _objective_evidence_comparison_grounding_errors(
        self,
        record: Mapping[str, Any],
        *,
        source_text: str,
    ) -> tuple[str, ...]:
        comparison = record.get("comparison")
        if not isinstance(comparison, Mapping):
            return ()
        errors: list[str] = []
        for field in ("baseline_label", "target_label"):
            value = comparison.get(field)
            if not self._objective_value_is_source_grounded(value, source_text):
                errors.append(
                    f"comparison.{field}={value!r} is not grounded in SOURCE"
                )
        return tuple(errors)

    def _objective_evidence_result_grounding_errors(
        self,
        record: Mapping[str, Any],
        *,
        source: Mapping[str, Any],
        source_text: str,
    ) -> tuple[str, ...]:
        reported_result = record.get("reported_result")
        if not isinstance(reported_result, Mapping):
            return ()
        errors: list[str] = []
        outcome = reported_result.get("outcome")
        if not self._objective_axis_is_source_grounded(
            outcome,
            source=source,
            source_text=source_text,
        ):
            errors.append(
                f"reported_result.outcome={outcome!r} is not grounded in SOURCE"
            )
        unit = str(reported_result.get("unit") or "").strip()
        if unit and self._objective_column_key(unit) not in self._objective_column_key(
            source_text
        ):
            errors.append(f"reported_result.unit={unit!r} is not grounded in SOURCE")
        result_value = reported_result.get("value")
        result_text = str(reported_result.get("result_text") or "").strip()
        if result_value not in (None, "") and not self._objective_value_is_source_grounded(
            result_value,
            source_text,
        ):
            errors.append(
                f"reported_result.value={result_value!r} is not grounded in SOURCE"
            )
        if _NUMBER_PATTERN.search(result_text):
            result_text_is_grounded = self._objective_value_is_source_grounded(
                result_text,
                source_text,
            )
        else:
            result_text_is_grounded = property_matching.axis_label_is_mentioned(
                source_text,
                result_text,
            )
        if not result_text_is_grounded:
            errors.append(
                "reported_result.result_text="
                f"{result_text!r} is not grounded in SOURCE"
            )
        return tuple(errors)

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
            if not property_matching.axis_values_match(property_name, outcome):
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
                if property_matching.axis_values_match(
                    self._split_property_unit(header)[0],
                    name,
                )
                or any(
                    property_matching.axis_values_match(axis, name)
                    for axis in property_matching.process_column_axis_keys(header)
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
        if property_matching.source_text_mentions_axis(source_text, axis):
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
            symbol_axes = property_matching.process_column_axis_keys(label_text)
            if any(
                property_matching.axis_values_match(axis, item)
                for item in symbol_axes
            ):
                return True
            if (
                property_matching.axis_values_match(label_text, axis)
                or property_matching.axis_label_is_mentioned(label_text, axis)
                or property_matching.axis_label_is_mentioned(axis, label_text)
            ):
                return True
        return any(
            property_matching.axis_values_match(token, axis)
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
            role_label = property_matching.normalize_property_label(role_text)
            if (
                route.role == "current_experimental_evidence"
                and objective_context is not None
                and role_label
                and property_matching.property_label_matches_target(
                    role_label,
                    target_axes=property_matching.objective_outcomes(
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
        role_label = property_matching.normalize_property_label(
            route.column_roles.get(result_column)
        )
        if (
            role_label
            and objective_context is not None
            and property_matching.result_role_is_specific_property(role_label)
            and property_matching.property_label_matches_target(
                role_label,
                target_axes=property_matching.objective_outcomes(objective_context),
            )
        ):
            return role_label
        property_name, _unit = self._split_property_unit(result_column)
        return (
            property_matching.normalize_property_label(property_name)
            or str(property_name or result_column).strip()
        )

    def _objective_result_column_is_specific_metric(self, column_text: str) -> bool:
        property_name, _unit = self._split_property_unit(column_text)
        tokens = property_matching.axis_tokens(property_name)
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
        normalized = (
            property_matching.normalize_property_label(property_name)
            or property_name
        )
        target_axes = property_matching.objective_outcomes(objective_context)
        if property_matching.property_label_matches_target(
            normalized,
            target_axes=target_axes,
        ):
            return True
        if property_matching.density_property_matches_structural_target(
            normalized,
            target_axes=target_axes,
        ):
            return True
        if normalized in target_axes:
            return True
        return any(
            property_matching.axis_label_is_mentioned(normalized, axis)
            or property_matching.axis_label_is_mentioned(column_text, axis)
            for axis in target_axes
        )

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
        supports: tuple[str, ...] = (),
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
            "supports": list(supports),
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
        objective_context: ResearchObjective,
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
                objective_context=objective_context,
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
                objective_context=objective_context,
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

    def _document_round_robin_objective_routes(
        self,
        routes: tuple[EvidenceCandidate, ...],
        *,
        document_trees_by_document_id: dict[str, SourceDocumentTree],
    ) -> tuple[EvidenceCandidate, ...]:
        routes_by_document: dict[tuple[str, str], list[EvidenceCandidate]] = {}
        for route in routes:
            routes_by_document.setdefault(
                (route.objective_id, route.document_id),
                [],
            ).append(route)
        ordered_groups = tuple(
            tuple(
                sorted(
                    document_routes,
                    key=lambda route: (
                        self._route_tree_order(
                            route,
                            document_trees_by_document_id=(
                                document_trees_by_document_id
                            ),
                        ),
                        route.source_ref,
                    ),
                )
            )
            for _key, document_routes in sorted(routes_by_document.items())
        )
        return tuple(
            group[position]
            for position in range(
                max((len(group) for group in ordered_groups), default=0)
            )
            for group in ordered_groups
            if position < len(group)
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
        objective_context: ResearchObjective,
        blocks: list[Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        scored_candidates: list[tuple[int, int, dict[str, Any]]] = []
        selected_source_refs = set(frame.relevant_text_source_refs)
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
            if selected_source_refs and block_id not in selected_source_refs:
                continue
            score = self._route_text_candidate_score(
                frame=frame,
                objective_context=objective_context,
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
        objective_context: ResearchObjective,
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
            if restrict_to_frame_sections:
                if frame.relevant_text_source_refs:
                    if not self._route_tree_source_matches_frame(
                        document_tree=document_tree,
                        node=node,
                        frame=frame,
                    ):
                        continue
                elif not self._route_section_matches_frame(
                    section_label=section_label,
                    frame=frame,
                ):
                    continue
            score = self._route_text_candidate_score(
                frame=frame,
                objective_context=objective_context,
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
            objective_context=objective_context,
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
        objective_context: ResearchObjective,
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
                objective_context=objective_context,
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
        objective_context: ResearchObjective,
        candidate: Mapping[str, Any],
    ) -> bool:
        text = str(candidate.get("text") or "")
        if not text:
            return False
        mentions_variable = any(
            property_matching.source_text_mentions_axis(text, axis)
            for axis in objective_context.variables
        )
        mentions_outcome = any(
            property_matching.source_text_mentions_axis(text, axis)
            for axis in objective_context.outcomes
        )
        if not mentions_outcome:
            return False
        text_haystack = text.casefold()
        if not mentions_variable:
            text_tokens = property_matching.axis_tokens(text_haystack)
            outcome_tokens = set().union(
                *(
                    property_matching.axis_tokens(
                        property_matching.axis_key(axis)
                    )
                    for axis in objective_context.outcomes
                )
            )
            mentions_variable = any(
                any(
                    len(token) >= 4
                    and token not in {"base", "plate"}
                    and token not in outcome_tokens
                    and token in text_tokens
                    for token in property_matching.axis_tokens(
                        property_matching.axis_key(axis)
                    )
                )
                for axis in objective_context.variables
            )
        has_result_comparison = any(
            phrase in text_haystack
            for phrase in (
                "compared with",
                "compared to",
                "comparing",
                "decreased",
                "diminish",
                "exhibited",
                "higher than",
                "increased",
                "lower than",
                "not significantly influence",
                "observed",
                "prevent",
                "prohibit",
                "reduc",
                "resulted in",
                "resulted into",
                "significant effect",
                "unchanged",
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
        if frame.relevant_text_source_refs:
            return True
        if not frame.relevant_sections:
            return False
        if frame.relevance == "high" and frame.paper_role == "primary_experiment":
            return False
        return True

    def _route_tree_source_matches_frame(
        self,
        *,
        document_tree: SourceDocumentTree,
        node: Any,
        frame: PaperAnalysisFrame,
    ) -> bool:
        selected_source_refs = set(frame.relevant_text_source_refs)
        current = node
        while current is not None:
            if any(
                str(value or "").strip() in selected_source_refs
                for value in (
                    getattr(current, "node_id", None),
                    getattr(current, "source_ref_id", None),
                )
            ):
                return True
            parent_id = getattr(current, "parent_id", None)
            current = document_tree.nodes.get(parent_id) if parent_id else None
        return False

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
        objective_context: ResearchObjective,
        block_type: str,
        section_label: str,
        text: str,
    ) -> int:
        text_haystack = text.casefold()
        if "references" in self._objective_column_key(section_label):
            return 0
        score = 0
        for term in (*objective_context.material_scope, *frame.material_match):
            term_text = str(term or "").strip().casefold()
            if term_text and term_text in text_haystack:
                score += 1
        objective_axis_keys = {
            property_matching.axis_key(term)
            for term in (*objective_context.variables, *objective_context.outcomes)
        }
        for term in (*objective_context.variables, *objective_context.outcomes):
            if property_matching.source_text_mentions_axis(text, term):
                score += 4
        for term in (*frame.changed_variables, *frame.measured_property_scope):
            if (
                property_matching.axis_key(term) not in objective_axis_keys
                and property_matching.source_text_mentions_axis(text, term)
            ):
                score += 1
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















    @staticmethod
    def _paper_skim_study_values(
        paper_skim: PaperSkim | None,
        field_name: str,
    ) -> tuple[str, ...]:
        if paper_skim is None:
            return ()
        values: list[str] = []
        seen: set[str] = set()
        for study in paper_skim.studies:
            for value in getattr(study, field_name):
                text = str(value or "").strip()
                key = text.casefold()
                if text and key not in seen:
                    seen.add(key)
                    values.append(text)
        return tuple(values)

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
                if property_matching.source_text_mentions_axis(
                    property_table_text,
                    axis,
                )
            ]
            matched_variable_axes = [
                axis
                for axis in objective.variables
                if property_matching.source_text_mentions_axis(table_text, axis)
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

    def _get_paper_facts_extractor(self) -> PaperFactsExtractor:
        if self._paper_facts_extractor is None:
            self._paper_facts_extractor = build_default_paper_facts_extractor()
        return self._paper_facts_extractor

    def _load_source_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        documents = (
            self.source_artifact_repository.read_collection_documents(
                collection_id,
                build_id=build_id,
            )
            if build_id is not None
            else self.source_artifact_repository.read_collection_documents(collection_id)
        )
        if not documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return documents

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


    def _append_unique_axis(
        self,
        target: list[str],
        seen: set[str],
        value: Any,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = property_matching.axis_key(text)
        if key in seen:
            return
        seen.add(key)
        target.append(text)

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
