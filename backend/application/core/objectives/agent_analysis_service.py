"""Publish one user-approved Objective analysis authored by the Research Agent."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import math
from typing import Any, Mapping
from uuid import uuid4

from application.core.objectives.evidence_authoring_service import (
    normalize_source_text,
    resolve_canonical_objective_source,
)
from application.core.objectives.analysis.source_validation import (
    authored_source_fact_grounding_warnings,
)
from application.core.objectives import property_matching
from application.source.collection_service import CollectionService
from domain.core import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    EVIDENCE_RESULT_DIRECTIONS,
    EVIDENCE_ROLE_VALUES,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PAPER_RELEVANCE_VALUES,
    PAPER_ROLE_VALUES,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.ports import ObjectiveRepository, SourceArtifactRepository


AGENT_OBJECTIVE_ANALYSIS_PIPELINE_VERSION = "agent-objective-analysis.v1"
_AGENT_OBJECTIVE_RELEVANT_SOURCE_LIMIT = 8


@dataclass(frozen=True)
class AgentObjectiveAnalysisResult:
    analysis: ObjectiveAnalysis
    contributions: tuple[PaperContribution, ...]
    evidence_records: tuple[ObjectiveEvidence, ...]
    findings: tuple[Any, ...] = ()


@dataclass(frozen=True)
class _ValidatedEvidence:
    draft: Mapping[str, Any]
    page: int | None
    warnings: tuple[str, ...] = ()


class AgentObjectiveAnalysisService:
    """Validate Agent-authored record integrity, then publish the analysis."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        objective_repository: ObjectiveRepository,
        source_artifact_repository: SourceArtifactRepository,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository
        self.source_artifact_repository = source_artifact_repository

    async def publish(
        self,
        *,
        collection_id: str,
        objective_id: str,
        document_ids: tuple[str, ...],
        paper_summaries: tuple[Mapping[str, Any], ...],
        evidence_drafts: tuple[Mapping[str, Any], ...],
        model_name: str,
        prompt_version: str,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> AgentObjectiveAnalysisResult:
        await self.collection_service.get_collection_for_user(
            collection_id, created_by_user_id
        )
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        if objective.confirmation_status != "confirmed":
            raise ValueError(
                "research objective must be confirmed before Agent analysis"
            )
        selected_ids = self._ordered_ids(document_ids, field_name="document_ids")
        document_inputs, source_documents = await self._load_documents(
            collection_id, selected_ids
        )
        validated_evidence = self._validate_evidence_sources(
            evidence_drafts,
            selected_ids=selected_ids,
            source_documents=source_documents,
        )
        verified_source_digests_by_document: dict[
            str, dict[tuple[str, str], str]
        ] = {document_id: {} for document_id in selected_ids}
        for item in validated_evidence:
            document_id = str(item.draft.get("document_id") or "").strip()
            source_kind = str(item.draft.get("source_kind") or "").strip()
            source_ref = str(item.draft.get("source_ref") or "").strip()
            source_digest = str(item.draft.get("source_digest") or "").strip().lower()
            verified_source_digests_by_document[document_id][
                (source_kind, source_ref)
            ] = source_digest
        summary_by_document = self._paper_summaries(
            paper_summaries,
            selected_ids=selected_ids,
            source_documents=source_documents,
            verified_source_digests_by_document=(
                verified_source_digests_by_document
            ),
        )
        evidence_by_document = self._evidence_by_document(
            validated_evidence, selected_ids=selected_ids
        )
        self._validate_paper_evidence_outcomes(
            summary_by_document,
            evidence_by_document=evidence_by_document,
        )
        relevant_source_refs_by_document = {
            document_id: self._bounded_objective_source_refs(
                objective,
                source_documents[document_id],
            )
            for document_id in selected_ids
        }

        # Validate the complete record shape before allocating a durable version.
        staged_evidence = self._build_evidence(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=1,
            validated=validated_evidence,
            created_by_user_id=created_by_user_id,
            created_by_tool_call_id=created_by_tool_call_id,
        )
        staged_contributions = self._build_contributions(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=1,
            selected_ids=selected_ids,
            summary_by_document=summary_by_document,
            evidence_by_document=evidence_by_document,
            evidence_records=staged_evidence,
            relevant_source_refs_by_document=relevant_source_refs_by_document,
        )

        _objective, queued = await self.objective_repository.queue_analysis(
            collection_id,
            objective_id,
            document_inputs=document_inputs,
            pipeline_version=AGENT_OBJECTIVE_ANALYSIS_PIPELINE_VERSION,
            model_name=self._required_text(model_name, "model_name"),
            prompt_versions={
                "agent_objective_analysis": self._required_text(
                    prompt_version, "prompt_version"
                )
            },
            origin="agent_authored",
            created_by_user_id=created_by_user_id,
            created_by_tool_call_id=created_by_tool_call_id,
        )
        if queued.status != "queued":
            raise ValueError("the approved Agent analysis is already running")
        running = await self.objective_repository.claim_analysis(
            collection_id,
            objective_id,
            queued.analysis_version,
        )
        if running is None:
            raise RuntimeError("the approved Agent analysis could not be claimed")

        contributions = tuple(
            replace(item, analysis_version=running.analysis_version)
            for item in staged_contributions
        )
        evidence_records = tuple(
            replace(item, analysis_version=running.analysis_version)
            for item in staged_evidence
        )
        if self._all_relevant_papers_failed(contributions):
            failed = await self.objective_repository.fail_analysis(
                collection_id,
                objective_id,
                running.analysis_version,
                error_code="agent_analysis_extraction_failed",
                error_message=(
                    "Agent analysis failed to extract every relevant paper."
                ),
                expected_status="running",
                contributions=contributions,
            )
            return AgentObjectiveAnalysisResult(
                analysis=failed,
                contributions=contributions,
                evidence_records=evidence_records,
            )
        try:
            has_grounded_evidence = bool(evidence_records)
            has_incomplete_coverage = any(
                item.evidence_disposition == "coverage_incomplete"
                for item in contributions
            )
            abstention_reason = None
            abstention_note = None
            if not has_grounded_evidence:
                if has_incomplete_coverage:
                    abstention_reason = "insufficient_evidence"
                    abstention_note = (
                        "The approved Agent review has Objective-relevant Sources "
                        "that remain uninspected."
                    )
                else:
                    abstention_reason = "no_grounded_evidence"
                    abstention_note = (
                        "The approved Agent review inspected the selected papers but "
                        "recorded no Source-backed Evidence for this Objective."
                    )
            _objective, published = await self.objective_repository.publish_analysis(
                collection_id,
                objective_id,
                running.analysis_version,
                contributions=contributions,
                evidence_records=evidence_records,
                findings=(),
                abstention_reason=abstention_reason,
                abstention_note=abstention_note,
            )
        except Exception as exc:
            await self.objective_repository.fail_analysis(
                collection_id,
                objective_id,
                running.analysis_version,
                error_code="agent_analysis_publish_failed",
                error_message=str(exc),
                expected_status="running",
            )
            raise
        return AgentObjectiveAnalysisResult(
            analysis=published,
            contributions=contributions,
            evidence_records=evidence_records,
        )

    async def _load_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[tuple[PreparedDocumentInput, ...], dict[str, Any]]:
        document_inputs: list[PreparedDocumentInput] = []
        source_documents: dict[str, Any] = {}
        for document_id in document_ids:
            document = await self.collection_service.get_document(
                collection_id, document_id
            )
            if document.status != "ready" or not document.preparation_fingerprint:
                raise ValueError(
                    f"selected document is not ready for analysis: {document_id}"
                )
            source_document = await self.source_artifact_repository.read_document(
                collection_id, document_id
            )
            if source_document is None:
                raise FileNotFoundError(
                    f"prepared Source document was not found: {document_id}"
                )
            document_inputs.append(
                PreparedDocumentInput(
                    document_id=document_id,
                    preparation_fingerprint=document.preparation_fingerprint,
                )
            )
            source_documents[document_id] = source_document
        return tuple(document_inputs), source_documents

    def _validate_evidence_sources(
        self,
        evidence_drafts: tuple[Mapping[str, Any], ...],
        *,
        selected_ids: tuple[str, ...],
        source_documents: Mapping[str, Any],
    ) -> tuple[_ValidatedEvidence, ...]:
        selected = set(selected_ids)
        draft_ids: set[str] = set()
        validated: list[_ValidatedEvidence] = []
        for raw in evidence_drafts:
            draft = dict(raw)
            draft_id = self._required_text(draft.get("draft_id"), "draft_id")
            if draft_id in draft_ids:
                raise ValueError(f"duplicate Evidence draft_id: {draft_id}")
            draft_ids.add(draft_id)
            document_id = self._required_text(
                draft.get("document_id"), "evidence document_id"
            )
            if document_id not in selected:
                raise ValueError(
                    f"Evidence document is outside the selected scope: {document_id}"
                )
            source_kind = self._required_text(
                draft.get("source_kind"), "source_kind"
            )
            evidence_role = self._required_text(
                draft.get("evidence_role"), "evidence_role"
            )
            if evidence_role not in EVIDENCE_ROLE_VALUES:
                raise ValueError(f"unsupported Evidence role: {evidence_role}")
            attribution_scope = self._required_text(
                draft.get("attribution_scope"), "attribution_scope"
            )
            if attribution_scope not in EVIDENCE_ATTRIBUTION_SCOPES:
                raise ValueError(
                    f"unsupported Evidence attribution: {attribution_scope}"
                )
            self._confidence(draft.get("confidence"), "Evidence confidence")
            reported_result = draft.get("reported_result")
            if isinstance(reported_result, Mapping):
                direction = self._required_text(
                    reported_result.get("direction"), "reported result direction"
                )
                if direction not in EVIDENCE_RESULT_DIRECTIONS:
                    raise ValueError(
                        f"unsupported Evidence result direction: {direction}"
                    )
            source_ref = self._required_text(draft.get("source_ref"), "source_ref")
            canonical = resolve_canonical_objective_source(
                source_documents[document_id],
                source_kind=source_kind,
                source_ref=source_ref,
            )
            expected_digest = sha256(canonical.content.encode("utf-8")).hexdigest()
            supplied_digest = self._required_text(
                draft.get("source_digest"), "source_digest"
            ).lower()
            if supplied_digest != expected_digest:
                raise ValueError(
                    f"Source digest does not match the canonical Source: {source_ref}"
                )
            excerpt = self._required_text(
                draft.get("source_excerpt"), "source_excerpt"
            )
            if normalize_source_text(excerpt) not in normalize_source_text(
                canonical.content
            ):
                raise ValueError(
                    f"Source excerpt is not contained in the canonical Source: {source_ref}"
                )
            grounding_warnings = authored_source_fact_grounding_warnings(
                draft,
                source=canonical.grounding_source,
            )
            validated.append(
                _ValidatedEvidence(
                    draft=draft,
                    page=canonical.page,
                    warnings=grounding_warnings,
                )
            )
        return tuple(validated)

    @staticmethod
    def _evidence_by_document(
        evidence: tuple[_ValidatedEvidence, ...],
        *,
        selected_ids: tuple[str, ...],
    ) -> dict[str, tuple[_ValidatedEvidence, ...]]:
        grouped = {
            document_id: tuple(
                item
                for item in evidence
                if str(item.draft.get("document_id") or "").strip() == document_id
            )
            for document_id in selected_ids
        }
        return grouped

    @staticmethod
    def _validate_paper_evidence_outcomes(
        summaries: Mapping[str, Mapping[str, Any]],
        *,
        evidence_by_document: Mapping[str, tuple[_ValidatedEvidence, ...]],
    ) -> None:
        for document_id, summary in summaries.items():
            outcome = str(
                summary.get("inspection_outcome") or "evidence_recorded"
            ).strip()
            has_evidence = bool(evidence_by_document.get(document_id))
            if has_evidence and outcome != "evidence_recorded":
                raise ValueError(
                    f"paper {document_id} records Evidence and a no-Evidence outcome"
                )
            if not has_evidence and outcome == "evidence_recorded":
                raise ValueError(
                    f"paper {document_id} requires grounded Evidence or an explicit "
                    "no-Evidence inspection outcome"
                )

    @staticmethod
    def _all_relevant_papers_failed(
        contributions: tuple[PaperContribution, ...],
    ) -> bool:
        relevant = tuple(
            item for item in contributions if item.analysis_status != "excluded"
        )
        return bool(relevant) and all(
            item.analysis_status == "failed" for item in relevant
        )

    @staticmethod
    def _build_evidence(
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        validated: tuple[_ValidatedEvidence, ...],
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> tuple[ObjectiveEvidence, ...]:
        now = datetime.now(timezone.utc)
        records: list[ObjectiveEvidence] = []
        for item in validated:
            draft = item.draft
            records.append(
                ObjectiveEvidence.from_mapping(
                    {
                        "collection_id": collection_id,
                        "objective_id": objective_id,
                        "analysis_version": analysis_version,
                        "evidence_id": f"evidence_agent_{uuid4().hex[:16]}",
                        "document_id": draft.get("document_id"),
                        "source_kind": draft.get("source_kind"),
                        "source_ref": draft.get("source_ref"),
                        "source_excerpt": draft.get("source_excerpt"),
                        "page_numbers": [item.page] if item.page is not None else [],
                        "related_source_refs": [],
                        "evidence_role": draft.get("evidence_role"),
                        "selection_status": "extracted",
                        "selection_reason": draft.get("authoring_note"),
                        "changed_variables": draft.get("changed_variables") or [],
                        "comparison": draft.get("comparison"),
                        "reported_result": draft.get("reported_result"),
                        "attribution_scope": draft.get("attribution_scope"),
                        "scientific_context": draft.get("scientific_context") or {},
                        "anchor_ids": [],
                        "resolution_status": "resolved",
                        "confidence": draft.get("confidence"),
                        "origin": "agent_authored",
                        "source_analysis_version": None,
                        "created_by_user_id": created_by_user_id,
                        "created_by_tool_call_id": created_by_tool_call_id,
                        "created_at": now,
                        "authoring_note": draft.get("authoring_note"),
                        "warnings": list(item.warnings),
                    }
                )
            )
        return tuple(records)

    @classmethod
    def _bounded_objective_source_refs(
        cls,
        objective: ResearchObjective,
        source_document: Any,
    ) -> tuple[tuple[str, str], ...]:
        candidates: list[tuple[int, int, int, str, str]] = []

        def consider(
            *,
            source_kind: str,
            source_ref: str,
            source_order: int,
            page: int | None,
            heading_path: str | None,
            content: str,
        ) -> None:
            if not source_ref or not content.strip():
                return
            section_role = cls._objective_source_section_role(heading_path)
            if section_role == "references":
                return
            searchable = " ".join(
                value for value in (heading_path or "", content) if value
            )
            variable_match = any(
                property_matching.source_text_mentions_objective_variable(
                    searchable,
                    variable,
                )
                for variable in objective.variables
            )
            outcome_match = any(
                property_matching.source_text_mentions_axis(searchable, outcome)
                for outcome in objective.outcomes
            )
            if variable_match and outcome_match:
                priority = 0
            elif outcome_match and section_role in {"results", "conclusion"}:
                priority = 1
            elif outcome_match:
                priority = 2
            elif variable_match and section_role == "methods":
                priority = 3
            elif variable_match:
                priority = 4
            elif section_role == "conclusion":
                priority = 5
            elif section_role == "overview":
                priority = 6
            else:
                return
            candidates.append(
                (
                    priority,
                    page if page is not None else 1_000_000_000,
                    source_order,
                    source_kind,
                    source_ref,
                )
            )

        for block in source_document.blocks:
            if str(block.block_type or "") == "heading":
                continue
            consider(
                source_kind="text_window",
                source_ref=str(block.block_id or "").strip(),
                source_order=int(block.block_order or 0),
                page=block.page,
                heading_path=block.heading_path,
                content=str(block.text or ""),
            )
        for table in source_document.tables:
            table_terms = " ".join(
                [
                    str(table.caption_text or ""),
                    *(str(value) for value in table.column_headers),
                    *(
                        str(row[0])
                        for row in table.table_matrix
                        if isinstance(row, (list, tuple)) and row
                    ),
                ]
            )
            consider(
                source_kind="table",
                source_ref=str(table.table_id or "").strip(),
                source_order=int(table.table_order or 0),
                page=table.page,
                heading_path=table.heading_path,
                content=table_terms,
            )
        for figure in source_document.figures:
            consider(
                source_kind="figure",
                source_ref=str(figure.figure_id or "").strip(),
                source_order=int(figure.figure_order or 0),
                page=figure.page,
                heading_path=figure.heading_path,
                content=" ".join(
                    value
                    for value in (
                        str(figure.figure_label or ""),
                        str(figure.caption_text or ""),
                    )
                    if value
                ),
            )

        ordered: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for _priority, _page, _order, source_kind, source_ref in sorted(candidates):
            identity = (source_kind, source_ref)
            if identity in seen:
                continue
            seen.add(identity)
            ordered.append(identity)
            if len(ordered) >= _AGENT_OBJECTIVE_RELEVANT_SOURCE_LIMIT:
                break
        return tuple(ordered)

    @staticmethod
    def _objective_source_section_role(heading_path: str | None) -> str | None:
        heading = " ".join(str(heading_path or "").casefold().split())
        if any(marker in heading for marker in ("reference", "bibliography")):
            return "references"
        if any(marker in heading for marker in ("conclusion", "summary")):
            return "conclusion"
        if any(marker in heading for marker in ("result", "discussion", "finding")):
            return "results"
        if any(
            marker in heading
            for marker in ("method", "experimental", "procedure", "methodology")
        ):
            return "methods"
        if any(marker in heading for marker in ("abstract", "overview", "introduction")):
            return "overview"
        return None

    @classmethod
    def _build_contributions(
        cls,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        selected_ids: tuple[str, ...],
        summary_by_document: Mapping[str, Mapping[str, Any]],
        evidence_by_document: Mapping[str, tuple[_ValidatedEvidence, ...]],
        evidence_records: tuple[ObjectiveEvidence, ...],
        relevant_source_refs_by_document: Mapping[
            str, tuple[tuple[str, str], ...]
        ],
    ) -> tuple[PaperContribution, ...]:
        records_by_document = {
            document_id: tuple(
                item for item in evidence_records if item.document_id == document_id
            )
            for document_id in selected_ids
        }
        contributions: list[PaperContribution] = []
        for document_id in selected_ids:
            summary = summary_by_document[document_id]
            evidence = records_by_document[document_id]
            extracted_source_identities = {
                (item.source_kind, item.source_ref) for item in evidence
            }
            inspected_source_refs = cls._inspected_source_refs(
                summary,
                validated_evidence=evidence_by_document[document_id],
            )
            inspected_source_identities = {
                (item["source_kind"], item["source_ref"])
                for item in inspected_source_refs
            }
            relevant_source_identities = set(
                relevant_source_refs_by_document[document_id]
            )
            routed_source_identities = (
                relevant_source_identities | inspected_source_identities
            )
            uninspected_source_count = len(
                relevant_source_identities - inspected_source_identities
            )
            coverage_reason = (
                f"{uninspected_source_count} Objective-relevant "
                f"Source{'s' if uninspected_source_count != 1 else ''} "
                f"remain{'s' if uninspected_source_count == 1 else ''} uninspected."
                if uninspected_source_count
                else None
            )
            comparable_count = sum(
                1
                for item in evidence
                if item.reported_result is not None
                and item.comparison is not None
                and item.comparison.comparable
            )
            material_match = tuple(
                dict.fromkeys(
                    str(attribute.value)
                    for item in evidence
                    for attribute in item.scientific_context.material
                )
            )
            changed_variables = tuple(
                dict.fromkeys(
                    variable.name for item in evidence for variable in item.changed_variables
                )
            )
            measured_scope = tuple(
                dict.fromkeys(
                    item.reported_result.outcome
                    for item in evidence
                    if item.reported_result is not None
                )
            )
            test_scope = tuple(
                dict.fromkeys(
                    f"{attribute.name}: {attribute.value}"
                    for item in evidence
                    for attribute in item.scientific_context.test
                )
            )
            inspection_outcome = str(
                summary.get("inspection_outcome") or "evidence_recorded"
            ).strip()
            outcome_reason = cls._required_text(
                summary.get("inspection_outcome_reason"),
                "inspection_outcome_reason",
            ) if inspection_outcome != "evidence_recorded" else None
            if inspection_outcome == "excluded_after_review":
                analysis_status = "excluded"
                disposition = "excluded"
                routed_source_count = 0
                uninspected_source_count = 0
            elif inspection_outcome == "extraction_failed":
                analysis_status = "failed"
                disposition = "extraction_failed"
                routed_source_count = len(routed_source_identities)
            elif uninspected_source_count:
                analysis_status = "analyzed"
                disposition = "coverage_incomplete"
                routed_source_count = len(routed_source_identities)
            elif evidence:
                analysis_status = "analyzed"
                disposition = (
                    "comparable_evidence"
                    if comparable_count
                    else "no_comparable_evidence"
                )
                routed_source_count = len(routed_source_identities)
            else:
                analysis_status = "analyzed"
                disposition = "no_grounded_evidence"
                routed_source_count = len(routed_source_identities)
            warnings: list[str] = []
            for validated_item in evidence_by_document[document_id]:
                source_ref = str(validated_item.draft.get("source_ref") or "").strip()
                for warning in validated_item.warnings:
                    warnings.append(
                        f"{source_ref}: {warning}" if source_ref else warning
                    )
            if inspection_outcome == "extraction_failed":
                warnings.append(
                    "Source extraction failed before Evidence could be recorded."
                )
            if disposition == "coverage_incomplete" and coverage_reason:
                warnings.append(coverage_reason)
            if inspection_outcome != "evidence_recorded":
                disposition_reason = outcome_reason
            elif comparable_count:
                disposition_reason = None
            else:
                disposition_reason = (
                    "The inspected Sources provide context or descriptive results "
                    "but no directly comparable result."
                )
            if disposition == "coverage_incomplete":
                disposition_reason = coverage_reason
            contributions.append(
                PaperContribution.from_mapping(
                    {
                        "collection_id": collection_id,
                        "objective_id": objective_id,
                        "analysis_version": analysis_version,
                        "document_id": document_id,
                        "analysis_status": analysis_status,
                        "relevance": summary.get("relevance"),
                        "paper_role": summary.get("paper_role"),
                        "contribution_summary": summary.get(
                            "contribution_summary"
                        ),
                        "material_match": material_match,
                        "changed_variables": changed_variables,
                        "measured_property_scope": measured_scope,
                        "test_environment_scope": test_scope,
                        "exclusion_reason": (
                            outcome_reason if analysis_status == "excluded" else None
                        ),
                        "warnings": warnings,
                        "confidence": summary.get("confidence"),
                        "evidence_disposition": disposition,
                        "routed_source_count": routed_source_count,
                        "extracted_source_count": (
                            0
                            if inspection_outcome == "extraction_failed"
                            else len(extracted_source_identities)
                        ),
                        "comparable_evidence_count": (
                            0
                            if inspection_outcome == "extraction_failed"
                            else comparable_count
                        ),
                        "failed_source_count": (
                            len(inspected_source_refs)
                            if inspection_outcome == "extraction_failed"
                            else 0
                        ),
                        "uninspected_source_count": uninspected_source_count,
                        "inspected_source_refs": inspected_source_refs,
                        "evidence_disposition_reason": disposition_reason,
                    }
                )
            )
        return tuple(contributions)

    @staticmethod
    def _inspected_source_refs(
        summary: Mapping[str, Any],
        *,
        validated_evidence: tuple[_ValidatedEvidence, ...],
    ) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        raw_refs = [
            *(item.draft for item in validated_evidence),
            *(summary.get("inspected_source_refs") or ()),
        ]
        for raw in raw_refs:
            if not isinstance(raw, Mapping):
                continue
            source_kind = str(raw.get("source_kind") or "").strip()
            source_ref = str(raw.get("source_ref") or "").strip()
            source_digest = str(raw.get("source_digest") or "").strip().lower()
            identity = (source_kind, source_ref)
            if not source_kind or not source_ref or identity in seen:
                continue
            seen.add(identity)
            refs.append(
                {
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "source_digest": source_digest,
                }
            )
        return refs

    @classmethod
    def _paper_summaries(
        cls,
        summaries: tuple[Mapping[str, Any], ...],
        *,
        selected_ids: tuple[str, ...],
        source_documents: Mapping[str, Any],
        verified_source_digests_by_document: Mapping[
            str, Mapping[tuple[str, str], str]
        ],
    ) -> dict[str, Mapping[str, Any]]:
        by_document: dict[str, Mapping[str, Any]] = {}
        for raw in summaries:
            summary = dict(raw)
            document_id = cls._required_text(
                summary.get("document_id"), "paper summary document_id"
            )
            if document_id in by_document:
                raise ValueError(f"duplicate paper summary: {document_id}")
            if document_id not in source_documents:
                raise ValueError(
                    f"paper summary is outside the selected scope: {document_id}"
                )
            cls._required_text(
                summary.get("contribution_summary"), "contribution_summary"
            )
            relevance = cls._required_text(summary.get("relevance"), "relevance")
            if relevance not in PAPER_RELEVANCE_VALUES:
                raise ValueError(f"unsupported paper relevance: {relevance}")
            paper_role = cls._required_text(summary.get("paper_role"), "paper_role")
            if paper_role not in PAPER_ROLE_VALUES:
                raise ValueError(f"unsupported paper role: {paper_role}")
            cls._confidence(summary.get("confidence"), "paper summary confidence")
            inspection_outcome = cls._required_text(
                summary.get("inspection_outcome") or "evidence_recorded",
                "inspection_outcome",
            )
            if inspection_outcome not in {
                "evidence_recorded",
                "no_grounded_evidence",
                "excluded_after_review",
                "extraction_failed",
            }:
                raise ValueError(
                    f"unsupported paper inspection outcome: {inspection_outcome}"
                )
            inspected_source_refs = summary.get("inspected_source_refs") or ()
            if inspected_source_refs:
                cls._validate_inspected_source_refs(
                    inspected_source_refs,
                    source_document=source_documents[document_id],
                    inspection_outcome=inspection_outcome,
                    verified_source_digests=(
                        verified_source_digests_by_document.get(document_id, {})
                    ),
                )
            elif inspection_outcome != "evidence_recorded":
                cls._required_text(
                    summary.get("inspection_outcome_reason"),
                    "inspection_outcome_reason",
                )
                raise ValueError(
                    "a paper without Evidence requires at least one inspected Source"
                )
            by_document[document_id] = summary
        if set(by_document) != set(selected_ids):
            raise ValueError(
                "Agent analysis requires one paper summary for every selected document"
            )
        return by_document

    @classmethod
    def _validate_inspected_source_refs(
        cls,
        values: Any,
        *,
        source_document: Any,
        inspection_outcome: str,
        verified_source_digests: Mapping[tuple[str, str], str],
    ) -> None:
        refs = tuple(item for item in (values or ()) if isinstance(item, Mapping))
        if not refs:
            raise ValueError(
                "a paper without Evidence requires at least one inspected Source"
            )
        identities: set[tuple[str, str]] = set()
        for item in refs:
            source_kind = cls._required_text(item.get("source_kind"), "source_kind")
            source_ref = cls._required_text(item.get("source_ref"), "source_ref")
            identity = (source_kind, source_ref)
            if identity in identities:
                raise ValueError(f"duplicate inspected Source: {source_kind}/{source_ref}")
            identities.add(identity)
            canonical = resolve_canonical_objective_source(
                source_document,
                source_kind=source_kind,
                source_ref=source_ref,
            )
            expected_digest = sha256(canonical.content.encode("utf-8")).hexdigest()
            supplied_digest = str(item.get("source_digest") or "").strip().lower()
            effective_digest = supplied_digest or verified_source_digests.get(
                identity, ""
            )
            if not effective_digest and inspection_outcome != "extraction_failed":
                raise ValueError(
                    "inspected Source digest is required for a scientific outcome"
                )
            if effective_digest and effective_digest != expected_digest:
                raise ValueError(
                    f"inspected Source digest does not match the canonical Source: "
                    f"{source_ref}"
                )

    @classmethod
    def _ordered_ids(
        cls, values: tuple[str, ...], *, field_name: str
    ) -> tuple[str, ...]:
        normalized = tuple(cls._required_text(value, field_name) for value in values)
        if not normalized:
            raise ValueError("Agent analysis requires at least one selected document")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Agent analysis document scope must be unique")
        return normalized

    @staticmethod
    def _required_text(value: Any, field_name: str) -> str:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            raise ValueError(f"Agent analysis requires {field_name}")
        return cleaned

    @staticmethod
    def _confidence(value: Any, field_name: str) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be between 0 and 1") from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f"{field_name} must be between 0 and 1")
        return confidence


__all__ = [
    "AGENT_OBJECTIVE_ANALYSIS_PIPELINE_VERSION",
    "AgentObjectiveAnalysisResult",
    "AgentObjectiveAnalysisService",
]
