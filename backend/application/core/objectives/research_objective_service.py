from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from hashlib import sha1
from typing import Any, Callable, Mapping

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_routing import (
    EvidenceCandidate,
    route_sources,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
    extract_source_facts,
)
from application.core.objectives.analysis.source_screening import (
    PaperAnalysisFrame,
    screen_sources,
)
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
from application.core.paper_facts.extraction import PaperFactsExtractor
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
)
from domain.ports import (
    ObjectiveRepository,
    PaperFactRepository,
    SourceArtifactRepository,
)
from domain.source import SourceDocument

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ObjectiveAnalysisArtifacts:
    """Canonical values produced by one versioned Objective analysis run."""

    contributions: tuple[PaperContribution, ...]
    evidence_records: tuple[ObjectiveEvidence, ...]
    findings: tuple[Finding, ...]


def _transient_text(value: Any) -> str:
    return str(value or "").strip()


_OBJECTIVE_PAIRWISE_SCOPE_LIMIT = 48
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
        evidence_candidates = route_sources(
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
        source_drafts = extract_source_facts(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            paper_facts_extractor=self._paper_facts_extractor,
            objectives=(objective,),
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
        enriched_drafts = self._enrich_objective_scope_context(
            source_drafts,
            paper_skims=objective_inputs["paper_skims"],
        )
        bound_drafts = self._bind_objective_result_process_context(enriched_drafts)
        comparison_drafts = self._build_objective_pairwise_comparison_units(
            bound_drafts,
            objectives=(objective,),
        )
        if comparison_drafts:
            logger.info(
                "Research objective pairwise comparison units generated collection_id=%s comparison_unit_count=%s",
                collection_id,
                len(comparison_drafts),
            )
        evidence_drafts = (*bound_drafts, *comparison_drafts)
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


    def _objective_column_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


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


    def _get_objective_extractor(self) -> ObjectiveExtractor:
        if self._objective_extractor is None:
            self._objective_extractor = build_default_objective_extractor()
        return self._objective_extractor


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
