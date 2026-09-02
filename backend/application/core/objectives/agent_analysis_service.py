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
)
from domain.ports import ObjectiveRepository, SourceArtifactRepository


AGENT_OBJECTIVE_ANALYSIS_PIPELINE_VERSION = "agent-objective-analysis.v1"


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


class AgentObjectiveAnalysisService:
    """Validate Agent judgments against canonical Sources, then publish them."""

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
        selected_ids = self._ordered_ids(document_ids, field_name="document_ids")
        summary_by_document = self._paper_summaries(
            paper_summaries, selected_ids=selected_ids
        )
        document_inputs, source_documents = await self._load_documents(
            collection_id, selected_ids
        )
        validated_evidence = self._validate_evidence_sources(
            evidence_drafts,
            selected_ids=selected_ids,
            source_documents=source_documents,
        )
        evidence_by_document = self._evidence_by_document(
            validated_evidence, selected_ids=selected_ids
        )

        # Validate the complete scientific shape before creating a durable version.
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
        try:
            _objective, published = await self.objective_repository.publish_analysis(
                collection_id,
                objective_id,
                running.analysis_version,
                contributions=contributions,
                evidence_records=evidence_records,
                findings=(),
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
        if not evidence_drafts:
            raise ValueError("Agent analysis requires Evidence for every selected document")
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
            validated.append(_ValidatedEvidence(draft=draft, page=canonical.page))
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
        if any(not items for items in grouped.values()):
            raise ValueError(
                "Agent analysis requires grounded Evidence for every selected document"
            )
        return grouped

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
                    }
                )
            )
        return tuple(records)

    @staticmethod
    def _build_contributions(
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        selected_ids: tuple[str, ...],
        summary_by_document: Mapping[str, Mapping[str, Any]],
        evidence_by_document: Mapping[str, tuple[_ValidatedEvidence, ...]],
        evidence_records: tuple[ObjectiveEvidence, ...],
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
            disposition = (
                "comparable_evidence"
                if comparable_count
                else "no_comparable_evidence"
            )
            contributions.append(
                PaperContribution.from_mapping(
                    {
                        "collection_id": collection_id,
                        "objective_id": objective_id,
                        "analysis_version": analysis_version,
                        "document_id": document_id,
                        "analysis_status": "analyzed",
                        "relevance": summary.get("relevance"),
                        "paper_role": summary.get("paper_role"),
                        "contribution_summary": summary.get(
                            "contribution_summary"
                        ),
                        "material_match": material_match,
                        "changed_variables": changed_variables,
                        "measured_property_scope": measured_scope,
                        "test_environment_scope": test_scope,
                        "warnings": [],
                        "confidence": summary.get("confidence"),
                        "evidence_disposition": disposition,
                        "routed_source_count": len(evidence_by_document[document_id]),
                        "extracted_source_count": len(evidence),
                        "comparable_evidence_count": comparable_count,
                        "failed_source_count": 0,
                        "evidence_disposition_reason": (
                            None
                            if comparable_count
                            else (
                                "The inspected Sources provide context or descriptive "
                                "results but no directly comparable result."
                            )
                        ),
                    }
                )
            )
        return tuple(contributions)

    @classmethod
    def _paper_summaries(
        cls,
        summaries: tuple[Mapping[str, Any], ...],
        *,
        selected_ids: tuple[str, ...],
    ) -> dict[str, Mapping[str, Any]]:
        by_document: dict[str, Mapping[str, Any]] = {}
        for raw in summaries:
            summary = dict(raw)
            document_id = cls._required_text(
                summary.get("document_id"), "paper summary document_id"
            )
            if document_id in by_document:
                raise ValueError(f"duplicate paper summary: {document_id}")
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
            by_document[document_id] = summary
        if set(by_document) != set(selected_ids):
            raise ValueError(
                "Agent analysis requires one paper summary for every selected document"
            )
        return by_document

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
