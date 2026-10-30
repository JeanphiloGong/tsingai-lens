from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from application.core.objectives.analysis import experiment_projection
from application.core.objectives.analysis.experiment_projection import experiment_evidence_disposition
from application.core.objectives.analysis.analysis_record_source import (
    should_read_experiment_projection,
)
from application.source import collection_service
from domain.core import ResearchObjective, is_question_shaped_objective
from domain.core.research_objective import (
    ObjectiveEvidence,
    PaperContribution,
    build_research_objective_id,
)
from repositories.objective_repository import ObjectiveRepo


async def create_chat_assisted_candidate(
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

    await collection_service.get_collection_for_user(collection_id, user_id)
    if len(outcomes) != 1:
        raise ValueError("chat-assisted objective requires exactly one outcome")
    if parent_objective_id is not None:
        if parent_analysis_version is None:
            raise ValueError("derived Objective requires a parent analysis version")
        if not derivation_basis:
            raise ValueError("derived Objective requires a derivation basis")
        parent = await ObjectiveRepo.read_objective(
            collection_id,
            parent_objective_id,
        )
        if parent is None:
            raise FileNotFoundError(
                f"parent research objective not found: {collection_id}/{parent_objective_id}"
            )
        if parent.published_analysis_version != parent_analysis_version:
            raise ValueError("parent Objective analysis version is no longer published")
        derivation_basis = await _canonicalize_derived_objective_basis(
            collection_id=collection_id,
            parent_objective_id=parent_objective_id,
            parent_analysis_version=parent_analysis_version,
            derivation_basis=derivation_basis,
        )

    material_terms = tuple(material_scope)
    variable_terms = tuple(variables)
    outcome_terms = tuple(outcomes)
    mechanism_terms = tuple(mechanisms)
    constraint_terms = tuple(constraints)
    comparator = requested_comparator
    parent_id = parent_objective_id
    objective = ResearchObjective(
        collection_id=collection_id,
        objective_id=build_research_objective_id(
            question=question,
            material_scope=material_terms,
            variables=variable_terms,
            outcomes=outcome_terms,
            mechanisms=mechanism_terms,
            constraints=constraint_terms,
            requested_comparator=comparator,
            parent_objective_id=parent_id,
            parent_analysis_version=parent_analysis_version,
        ),
        question=question,
        material_scope=material_terms,
        variables=variable_terms,
        outcomes=outcome_terms,
        mechanisms=mechanism_terms,
        constraints=constraint_terms,
        requested_comparator=comparator,
        seed_document_ids=tuple(seed_document_ids),
        excluded_document_ids=tuple(excluded_document_ids),
        confidence=0,
        reason=None,
        origin="chat_assisted",
        created_by_user_id=user_id,
        created_by_tool_call_id=tool_call_id,
        parent_objective_id=parent_id,
        parent_analysis_version=parent_analysis_version,
        derivation_basis=tuple(derivation_basis or ()),
    )
    if not is_question_shaped_objective(objective):
        raise ValueError("chat-assisted objective question is not question-shaped")

    for document_id in dict.fromkeys(
        (*objective.seed_document_ids, *objective.excluded_document_ids)
    ):
        await collection_service.get_document(collection_id, document_id)
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
    return await ObjectiveRepo.create_authored_candidate(
        objective,
        created_by_user_id=user_id,
        created_by_tool_call_id=tool_call_id,
    )


async def confirm_objective(
    *,
    collection_id: str,
    user_id: str,
    objective_id: str,
) -> ResearchObjective:
    """Record the researcher's confirmation without starting analysis."""

    await collection_service.get_collection_for_user(collection_id, user_id)
    return await ObjectiveRepo.confirm_objective(
        collection_id,
        objective_id,
    )


async def _canonicalize_derived_objective_basis(
    *,
    collection_id: str,
    parent_objective_id: str,
    parent_analysis_version: int,
    derivation_basis: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild derived-Objective lineage from the published parent."""

    experiment_backed = await should_read_experiment_projection(
        collection_id=collection_id, objective_id=parent_objective_id,
        analysis_version=parent_analysis_version,
    )
    canonical: list[dict[str, Any]] = []
    for item in derivation_basis:
        if not isinstance(item, Mapping):
            raise ValueError("objective derivation basis entries must be mappings")
        kind = item.get("kind")
        reference_id = item.get("reference_id")
        rationale = item.get("rationale")
        if not kind or not reference_id or not rationale:
            raise ValueError(
                "objective derivation basis requires reference_id and rationale"
            )

        if kind == "finding":
            if experiment_backed:
                record = await experiment_projection.read_analysis_finding(
                    collection_id,
                    parent_objective_id,
                    parent_analysis_version,
                    reference_id,
                )
            else:
                record = await ObjectiveRepo.read_finding(
                    collection_id,
                    parent_objective_id,
                    parent_analysis_version,
                    reference_id,
                )
            if record is None:
                raise ValueError("Finding is not part of the published parent analysis")
            snapshot = {
                "statement": (record.statement)[:1_000],
            }
        elif kind == "evidence_gap":
            record = await _published_evidence_by_id(
                collection_id,
                parent_objective_id,
                parent_analysis_version,
                reference_id,
                experiment_backed=experiment_backed,
            )
            if record is None:
                raise ValueError(
                    "Evidence gap is not part of the published parent analysis"
                )
            selection_status = record.selection_status
            evidence_status, reason = (
                experiment_evidence_disposition(record) if experiment_backed
                else (record.evidence_status, record.evidence_status_reason)
            )
            if selection_status == "failed" or evidence_status == "extraction_failed":
                raise ValueError(
                    "technical extraction failure cannot derive an Objective"
                )
            if selection_status == "rejected":
                raise ValueError("rejected Evidence cannot derive an Objective")
            snapshot = {
                "evidence_status": evidence_status,
                "reason": (
                    reason
                    or record.selection_reason
                    or ""
                )[:1_000],
                "document_id": record.document_id,
                "source_kind": record.source_kind,
                "source_ref": record.source_ref,
            }
        elif kind == "paper_contribution":
            record = await _published_paper_contribution_by_id(
                collection_id,
                parent_objective_id,
                parent_analysis_version,
                reference_id,
                experiment_backed=experiment_backed,
            )
            if record is None:
                raise ValueError(
                    "paper contribution is not part of the published parent analysis"
                )
            analysis_status = record.analysis_status
            disposition = record.evidence_disposition
            if analysis_status in {"excluded", "failed"} or disposition in {
                "excluded",
                "extraction_failed",
            }:
                raise ValueError("excluded or failed paper cannot derive an Objective")
            snapshot = {
                "document_id": record.document_id,
                "evidence_disposition": disposition,
                "reason": (record.evidence_disposition_reason or "")[
                    :1_000
                ],
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
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    evidence_id: str,
    *,
    experiment_backed: bool,
) -> ObjectiveEvidence | None:
    offset = 0
    while True:
        if experiment_backed:
            records, total = await experiment_projection.list_analysis_evidence(
                collection_id,
                objective_id,
                analysis_version,
                offset=offset,
                limit=500,
            )
        else:
            records, total = await ObjectiveRepo.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                offset=offset,
                limit=500,
            )
        for record in records:
            if record.evidence_id == evidence_id:
                return record
        offset += len(records)
        if not records or offset >= total:
            return None


async def _published_paper_contribution_by_id(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    document_id: str,
    *,
    experiment_backed: bool,
) -> PaperContribution | None:
    if experiment_backed:
        records = await experiment_projection.list_analysis_contributions(
            collection_id,
            objective_id,
            analysis_version,
        )
    else:
        records = await ObjectiveRepo.list_contributions(
            collection_id,
            objective_id,
            analysis_version,
        )
    return next(
        (
            record
            for record in records
            if record.document_id == document_id
        ),
        None,
    )
