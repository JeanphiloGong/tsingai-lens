from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from application.source.collection_service import CollectionService
from domain.core import ResearchObjective, is_question_shaped_objective
from application.repositories.objective_repository import ObjectiveRepository


class ObjectiveAuthoringService:
    """Create or confirm user-approved research questions."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        objective_repository: ObjectiveRepository,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository

    async def create_chat_assisted_candidate(
        self,
        *,
        collection_id: str,
        user_id: str,
        tool_call_id: str,
        question: str,
        material_scope: list[str],
        variables: list[str],
        outcomes: list[str],
        mechanisms: list[str],
        constraints: list[str],
        requested_comparator: str | None,
        seed_document_ids: list[str],
        excluded_document_ids: list[str],
        parent_objective_id: str | None = None,
        parent_analysis_version: int | None = None,
        derivation_basis: list[dict[str, Any]] | None = None,
    ) -> ResearchObjective:
        """Persist one user-approved, explicitly untested research question."""

        await self.collection_service.get_collection_for_user(collection_id, user_id)
        if len(outcomes) != 1:
            raise ValueError("chat-assisted objective requires exactly one outcome")
        if parent_objective_id is not None:
            if parent_analysis_version is None:
                raise ValueError("derived Objective requires a parent analysis version")
            if not derivation_basis:
                raise ValueError("derived Objective requires a derivation basis")
            parent = await self.objective_repository.read_objective(
                collection_id,
                parent_objective_id,
            )
            if parent is None:
                raise FileNotFoundError(
                    f"parent research objective not found: {collection_id}/{parent_objective_id}"
                )
            if parent.published_analysis_version != parent_analysis_version:
                raise ValueError("parent Objective analysis version is no longer published")
            derivation_basis = await self._canonicalize_derived_objective_basis(
                collection_id=collection_id,
                parent_objective_id=parent_objective_id,
                parent_analysis_version=parent_analysis_version,
                derivation_basis=derivation_basis,
            )

        objective = ResearchObjective.from_mapping(
            {
                "collection_id": collection_id,
                "question": question,
                "material_scope": material_scope,
                "variables": variables,
                "outcomes": outcomes,
                "mechanisms": mechanisms,
                "constraints": constraints,
                "requested_comparator": requested_comparator,
                "seed_document_ids": seed_document_ids,
                "excluded_document_ids": excluded_document_ids,
                "confidence": 0,
                "origin": "chat_assisted",
                "created_by_user_id": user_id,
                "created_by_tool_call_id": tool_call_id,
                "parent_objective_id": parent_objective_id,
                "parent_analysis_version": parent_analysis_version,
                "derivation_basis": derivation_basis or [],
            }
        )
        if not is_question_shaped_objective(objective):
            raise ValueError("chat-assisted objective question is not question-shaped")

        for document_id in dict.fromkeys(
            (*objective.seed_document_ids, *objective.excluded_document_ids)
        ):
            await self.collection_service.get_document(collection_id, document_id)
        objective = replace(
            objective,
            confidence=0,
            reason=(
                "User-approved untested research question with "
                f"{len(objective.seed_document_ids)} question-source paper(s); "
                "question provenance is not Evidence and analysis has not tested support."
                if objective.seed_document_ids
                else "User-approved untested research question; no question-source "
                "paper was recorded and analysis has not tested Evidence support."
            ),
        )
        return await self.objective_repository.create_authored_candidate(
            objective,
            created_by_user_id=user_id,
            created_by_tool_call_id=tool_call_id,
        )

    async def confirm_objective(
        self,
        *,
        collection_id: str,
        user_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        """Record the researcher's confirmation without starting analysis."""

        await self.collection_service.get_collection_for_user(collection_id, user_id)
        return await self.objective_repository.confirm_objective(
            collection_id,
            objective_id,
        )

    async def _canonicalize_derived_objective_basis(
        self,
        *,
        collection_id: str,
        parent_objective_id: str,
        parent_analysis_version: int,
        derivation_basis: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rebuild derived-Objective lineage from the published parent."""

        canonical: list[dict[str, Any]] = []
        for item in derivation_basis:
            if not isinstance(item, Mapping):
                raise ValueError("objective derivation basis entries must be mappings")
            kind = _text(item.get("kind"))
            reference_id = _text(item.get("reference_id"))
            rationale = _text(item.get("rationale"))
            if not kind or not reference_id or not rationale:
                raise ValueError(
                    "objective derivation basis requires reference_id and rationale"
                )

            if kind == "finding":
                record = await self.objective_repository.read_finding(
                    collection_id,
                    parent_objective_id,
                    parent_analysis_version,
                    reference_id,
                )
                if record is None:
                    raise ValueError("Finding is not part of the published parent analysis")
                snapshot = {
                    "statement": (_text(_record_field(record, "statement")) or "")[:1_000],
                }
            elif kind == "evidence_gap":
                record = await self._published_evidence_by_id(
                    collection_id,
                    parent_objective_id,
                    parent_analysis_version,
                    reference_id,
                )
                if record is None:
                    raise ValueError(
                        "Evidence gap is not part of the published parent analysis"
                    )
                selection_status = _text(_record_field(record, "selection_status")) or ""
                evidence_status = _text(_record_field(record, "evidence_status")) or ""
                if selection_status == "failed" or evidence_status == "extraction_failed":
                    raise ValueError("technical extraction failure cannot derive an Objective")
                if selection_status == "rejected":
                    raise ValueError("rejected Evidence cannot derive an Objective")
                snapshot = {
                    "evidence_status": evidence_status,
                    "reason": (
                        _text(_record_field(record, "evidence_status_reason"))
                        or _text(_record_field(record, "selection_reason"))
                        or ""
                    )[:1_000],
                    "document_id": _text(_record_field(record, "document_id")),
                    "source_kind": _text(_record_field(record, "source_kind")),
                    "source_ref": _text(_record_field(record, "source_ref")),
                }
            elif kind == "paper_contribution":
                record = await self._published_paper_contribution_by_id(
                    collection_id,
                    parent_objective_id,
                    parent_analysis_version,
                    reference_id,
                )
                if record is None:
                    raise ValueError(
                        "paper contribution is not part of the published parent analysis"
                    )
                analysis_status = _text(_record_field(record, "analysis_status")) or ""
                disposition = _text(_record_field(record, "evidence_disposition")) or ""
                if analysis_status in {"excluded", "failed"} or disposition in {
                    "excluded",
                    "extraction_failed",
                }:
                    raise ValueError("excluded or failed paper cannot derive an Objective")
                snapshot = {
                    "document_id": _text(_record_field(record, "document_id")) or reference_id,
                    "evidence_disposition": disposition,
                    "reason": (
                        _text(_record_field(record, "evidence_disposition_reason")) or ""
                    )[:1_000],
                }
            else:
                raise ValueError(f"unsupported objective derivation basis kind: {kind}")

            canonical.append(
                {
                    "kind": kind,
                    "reference_id": reference_id,
                    "rationale": rationale,
                    "status": "validated",
                    "snapshot": snapshot,
                }
            )
        return canonical

    async def _published_evidence_by_id(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        evidence_id: str,
    ) -> Any | None:
        offset = 0
        while True:
            records, total = await self.objective_repository.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                offset=offset,
                limit=500,
            )
            for record in records:
                if _text(_record_field(record, "evidence_id")) == evidence_id:
                    return record
            offset += len(records)
            if not records or offset >= total:
                return None

    async def _published_paper_contribution_by_id(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        document_id: str,
    ) -> Any | None:
        records = await self.objective_repository.list_contributions(
            collection_id,
            objective_id,
            analysis_version,
        )
        return next(
            (
                record
                for record in records
                if _text(_record_field(record, "document_id")) == document_id
            ),
            None,
        )


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _record_field(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)
