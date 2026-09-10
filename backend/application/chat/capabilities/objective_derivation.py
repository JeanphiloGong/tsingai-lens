"""Transient follow-up Objective drafts grounded in published research gaps."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.objective_proposal import ObjectiveDraftInput
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


DerivationBasisKind = Literal["finding", "evidence_gap", "paper_contribution"]


class ObjectiveDerivationBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DerivationBasisKind
    reference_id: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=1_000)
    status: str = Field(default="validated", min_length=1, max_length=32)
    snapshot: dict[str, Any] = Field(default_factory=dict)


class DerivedObjectiveDraftInput(ObjectiveDraftInput):
    derivation_basis: list[ObjectiveDerivationBasis] = Field(
        min_length=1,
        max_length=6,
    )


class DeriveObjectiveArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    drafts: list[DerivedObjectiveDraftInput] = Field(min_length=1, max_length=3)


class DeriveObjectiveCapability:
    spec = ToolSpec(
        name="derive_objective",
        description=(
            "Record one to three transient follow-up research-question drafts from "
            "an exact published Finding, scientific Evidence gap, or non-failed paper "
            "contribution. Technical extraction failures cannot serve as scientific "
            "basis. This does not persist or confirm an Objective."
        ),
        risk=ToolRisk.DRAFT,
        input_model=DeriveObjectiveArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        objective_analysis_service: Any,
    ) -> None:
        self.collection_service = collection_service
        self.objective_analysis_service = objective_analysis_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: DeriveObjectiveArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        state = await self.objective_analysis_service.get_analysis_state(
            context.collection_id,
            arguments.objective_id,
        )
        published = state.get("published_analysis")
        version = _field(published, "analysis_version")
        analysis_ref = ChatResourceRef(
            resource_type="objective_analysis",
            resource_id=(
                f"{arguments.objective_id}:{version}"
                if version is not None
                else arguments.objective_id
            ),
            href=(
                f"/collections/{context.collection_id}/objectives/"
                f"{arguments.objective_id}"
            ),
        )
        if published is None:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="succeeded",
                data=_abstained_result(
                    arguments.objective_id,
                    reason="parent_analysis_not_published",
                    rejected_drafts=[],
                ),
                resource_refs=(analysis_ref,),
                warnings=(
                    "The parent research question has no published analysis; inspect or "
                    "analyze it before deriving a follow-up question.",
                ),
            )

        findings = {
            finding_id: item
            for item in state.get("findings") or ()
            if (finding_id := _text(_field(item, "finding_id")))
        }
        omitted_finding_count = int(state.get("omitted_finding_count") or 0)
        evidence_review = state.get("evidence_review")
        evidence_review = (
            dict(evidence_review) if isinstance(evidence_review, Mapping) else {}
        )
        gaps = {
            evidence_id: dict(item)
            for item in evidence_review.get("gaps") or ()
            if isinstance(item, Mapping)
            and (evidence_id := _text(item.get("evidence_id")))
        }
        contributions = {
            document_id: item
            for item in state.get("paper_contributions") or ()
            if (document_id := _text(_field(item, "document_id")))
        }

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        refs: list[ChatResourceRef] = [analysis_ref]
        for position, draft in enumerate(arguments.drafts):
            basis_records: list[dict[str, Any]] = []
            basis_refs: list[ChatResourceRef] = []
            reasons: list[str] = []
            for basis in draft.derivation_basis:
                record, resource_ref, error = self._resolve_basis(
                    context,
                    arguments.objective_id,
                    int(version),
                    basis,
                    findings=findings,
                    omitted_finding_count=omitted_finding_count,
                    gaps=gaps,
                    contributions=contributions,
                )
                if error:
                    reasons.append(error)
                    continue
                basis_records.append(record)
                if resource_ref is not None:
                    basis_refs.append(resource_ref)
            if reasons or not basis_records:
                rejected.append(
                    {
                        "question": draft.question,
                        "reasons": reasons or ["no_valid_scientific_basis"],
                    }
                )
                continue

            draft_id = _draft_id(context.tool_call_id, position, draft)
            draft_payload = draft.model_dump(exclude={"derivation_basis"})
            accepted.append(
                {
                    "draft_id": draft_id,
                    "status": "draft",
                    **draft_payload,
                    "parent_objective_id": arguments.objective_id,
                    "parent_analysis_version": int(version),
                    "derivation_basis": basis_records,
                    "support_is_evidence": False,
                }
            )
            refs.extend(basis_refs)
            refs.append(
                ChatResourceRef(
                    resource_type="objective_draft",
                    resource_id=draft_id,
                )
            )

        if accepted and rejected:
            derivation_status = "partial"
            abstention_reason = None
        elif accepted:
            derivation_status = "proposed"
            abstention_reason = None
        else:
            derivation_status = "abstained"
            abstention_reason = "no_valid_scientific_basis"
        warnings = [
            f"{len(rejected)} follow-up draft(s) were rejected because their basis "
            "was missing, technical, or not part of the published analysis."
        ] if rejected else []
        omitted_gap_count = int(evidence_review.get("omitted_gap_count") or 0)
        if omitted_finding_count:
            warnings.append(
                f"{omitted_finding_count} Finding record(s) were omitted from the "
                "bounded parent analysis view; inspect a narrower or paginated view "
                "before deriving a follow-up question."
            )
        if omitted_gap_count:
            warnings.append(
                f"{omitted_gap_count} scientific or technical gap record(s) were "
                "omitted from the bounded parent analysis view."
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "parent_objective_id": arguments.objective_id,
                "published_analysis_version": int(version),
                "derivation_status": derivation_status,
                "draft_count": len(accepted),
                "drafts": accepted,
                "rejected_drafts": rejected,
                "omitted_finding_count": omitted_finding_count,
                "abstention_reason": abstention_reason,
                "persistence": "transient_chat_result",
                "support_is_evidence": False,
            },
            resource_refs=_deduplicate_refs(refs),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _resolve_basis(
        context: CapabilityExecutionContext,
        objective_id: str,
        analysis_version: int,
        basis: ObjectiveDerivationBasis,
        *,
        findings: Mapping[str, Any],
        omitted_finding_count: int,
        gaps: Mapping[str, Mapping[str, Any]],
        contributions: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ChatResourceRef | None, str | None]:
        reference_id = basis.reference_id
        common = {
            "kind": basis.kind,
            "reference_id": reference_id,
            "rationale": basis.rationale,
            "status": "validated",
        }
        if basis.kind == "finding":
            finding = findings.get(reference_id)
            if finding is None:
                reason = (
                    f"finding_not_in_bounded_analysis_view:{reference_id}"
                    if omitted_finding_count
                    else f"unknown_finding:{reference_id}"
                )
                return {}, None, reason
            return (
                {
                    **common,
                    "snapshot": {
                        "statement": _text(_field(finding, "statement"))[:1_000],
                    },
                },
                ChatResourceRef(
                    resource_type="finding",
                    resource_id=f"{objective_id}:{analysis_version}:{reference_id}",
                    href=(
                        f"/collections/{context.collection_id}/objectives/{objective_id}"
                        f"?finding_id={reference_id}"
                    ),
                ),
                None,
            )
        if basis.kind == "evidence_gap":
            gap = gaps.get(reference_id)
            if gap is None:
                return {}, None, f"unknown_evidence_gap:{reference_id}"
            status = _text(gap.get("evidence_status")) or "unknown"
            if status == "extraction_failed":
                return (
                    {},
                    None,
                    f"technical_failure_is_not_scientific_basis:{reference_id}",
                )
            document_id = _text(gap.get("document_id"))
            source_ref = _text(gap.get("source_ref"))
            resource_ref = None
            if document_id and source_ref:
                resource_ref = ChatResourceRef(
                    resource_type="source",
                    resource_id=(
                        f"{document_id}:{_text(gap.get('source_kind'))}:{source_ref}"
                    ),
                    href=(
                        f"/collections/{context.collection_id}/documents/{document_id}?"
                        + urlencode(
                            {"view": "parsed-paper", "source_ref": source_ref}
                        )
                    ),
                )
            return (
                {
                    **common,
                    "snapshot": {
                        "evidence_status": status,
                        "reason": _text(gap.get("reason"))[:1_000],
                        "document_id": document_id,
                        "source_kind": _text(gap.get("source_kind")),
                        "source_ref": source_ref,
                    },
                },
                resource_ref,
                None,
            )

        contribution = contributions.get(reference_id)
        if contribution is None:
            return {}, None, f"unknown_paper_contribution:{reference_id}"
        disposition = _text(_field(contribution, "evidence_disposition"))
        if disposition in {"extraction_failed", "excluded"}:
            return (
                {},
                None,
                f"technical_or_excluded_paper_is_not_scientific_basis:{reference_id}",
            )
        return (
            {
                **common,
                "snapshot": {
                    "document_id": reference_id,
                    "evidence_disposition": disposition,
                    "reason": _text(
                        _field(contribution, "evidence_disposition_reason")
                    )[:1_000],
                },
            },
            ChatResourceRef(
                resource_type="document",
                resource_id=reference_id,
                href=f"/collections/{context.collection_id}/documents/{reference_id}",
            ),
            None,
        )


def _abstained_result(
    parent_objective_id: str,
    *,
    reason: str,
    rejected_drafts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "parent_objective_id": parent_objective_id,
        "published_analysis_version": None,
        "derivation_status": "abstained",
        "draft_count": 0,
        "drafts": [],
        "rejected_drafts": rejected_drafts,
        "omitted_finding_count": 0,
        "abstention_reason": reason,
        "persistence": "transient_chat_result",
        "support_is_evidence": False,
    }


def _draft_id(
    tool_call_id: str,
    position: int,
    draft: DerivedObjectiveDraftInput,
) -> str:
    identity = json.dumps(
        {
            "tool_call_id": tool_call_id,
            "position": position,
            "draft": draft.model_dump(),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"draft_{sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _deduplicate_refs(refs: list[ChatResourceRef]) -> tuple[ChatResourceRef, ...]:
    result: list[ChatResourceRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        identity = (ref.resource_type, ref.resource_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    return tuple(result)


__all__ = [
    "DerivedObjectiveDraftInput",
    "DeriveObjectiveArguments",
    "DeriveObjectiveCapability",
    "ObjectiveDerivationBasis",
]
