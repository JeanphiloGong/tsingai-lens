from __future__ import annotations

import logging
from dataclasses import dataclass, replace
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
from application.core.objectives.analysis.paper_experiment import (
    reconstruct_paper_experiments,
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
        evidence_drafts = reconstruct_paper_experiments(
            collection_id=collection_id,
            source_facts=source_drafts,
            paper_skims=objective_inputs["paper_skims"],
            objectives=(objective,),
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
