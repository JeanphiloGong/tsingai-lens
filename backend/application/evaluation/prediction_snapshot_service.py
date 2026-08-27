from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from application.source.collection_service import CollectionService
from domain.evaluation import (
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
)
from domain.ports import (
    EvaluationRepository,
    ObjectiveRepository,
)


class CoreArtifactsNotReadyForEvaluationError(RuntimeError):
    """Raised when Core artifacts cannot produce an evaluation snapshot."""

    def __init__(self, collection_id: str, fact_source: str) -> None:
        self.collection_id = collection_id
        self.fact_source = fact_source
        super().__init__(
            f"core artifacts not ready for evaluation: {collection_id}/{fact_source}"
        )


class EvaluationPredictionSnapshotService:
    """Freeze existing Core artifacts into collection-bound prediction snapshots."""

    def __init__(
        self,
        collection_service: CollectionService,
        objective_repository: ObjectiveRepository,
        evaluation_repository: EvaluationRepository,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository
        self.evaluation_repository = evaluation_repository

    async def create_core_snapshot(
        self,
        *,
        collection_id: str,
        fact_source: str = "objective_first",
        snapshot_id: str | None = None,
        system_context: dict[str, Any] | None = None,
    ) -> EvaluationPredictionSnapshot:
        await self.collection_service.get_collection(collection_id)
        if fact_source != "objective_first":
            raise ValueError(f"unsupported fact_source: {fact_source}")
        items, objective_counts = await self._objective_first_items(collection_id)
        if not items:
            raise CoreArtifactsNotReadyForEvaluationError(collection_id, fact_source)
        snapshot = EvaluationPredictionSnapshot(
            snapshot_id=snapshot_id
            or f"pred_{collection_id}_{fact_source}_{_timestamp_id()}",
            collection_id=collection_id,
            target_layer="core",
            fact_source=fact_source,
            system_context=system_context or {},
            artifact_counts=objective_counts,
            items=tuple(items),
        )
        await self.evaluation_repository.upsert_prediction_snapshot(snapshot)
        return snapshot

    async def _objective_first_items(
        self,
        collection_id: str,
    ) -> tuple[list[EvaluationPredictionItem], dict[str, int]]:
        items: list[EvaluationPredictionItem] = []
        published_analysis_count = 0
        exported_evidence_keys: set[tuple[str, int, str]] = set()
        for objective in await self.objective_repository.list_objectives(
            collection_id
        ):
            analysis_version = objective.published_analysis_version
            if analysis_version is None:
                continue
            published_analysis_count += 1
            finding_offset = 0
            while True:
                findings, finding_total = await self.objective_repository.list_findings(
                    collection_id,
                    objective.objective_id,
                    analysis_version,
                    offset=finding_offset,
                    limit=200,
                )
                if not findings:
                    break
                for finding in findings:
                    evidence_records: list[Any] = []
                    evidence_offset = 0
                    while True:
                        evidence_page, evidence_total = (
                            await self.objective_repository.list_evidence(
                                collection_id,
                                objective.objective_id,
                                analysis_version,
                                finding_id=finding.finding_id,
                                offset=evidence_offset,
                                limit=500,
                            )
                        )
                        if not evidence_page:
                            break
                        evidence_records.extend(evidence_page)
                        evidence_offset += len(evidence_page)
                        if evidence_offset >= evidence_total:
                            break
                    for evidence in evidence_records:
                        exported_evidence_keys.add(
                            (
                                objective.objective_id,
                                analysis_version,
                                evidence.evidence_id,
                            )
                        )
                    contributing_documents = finding.contributing_document_ids
                    item_key = (
                        f"{objective.objective_id}:v{analysis_version}:"
                        f"{finding.finding_id}"
                    )
                    payload = finding.to_record()
                    payload["evidence"] = [
                        evidence.to_record() for evidence in evidence_records
                    ]
                    source_refs = tuple(
                        {
                            "evidence_id": evidence.evidence_id,
                            "document_id": evidence.document_id,
                            "source_kind": evidence.source_kind,
                            "source_ref": evidence.source_ref,
                            "source_excerpt": evidence.source_excerpt,
                            "page_numbers": list(evidence.page_numbers),
                            "related_source_refs": [
                                dict(locator)
                                for locator in evidence.related_source_refs
                            ],
                        }
                        for evidence in evidence_records
                    )
                    items.append(
                        EvaluationPredictionItem(
                            item_id=item_key,
                            document_id=(
                                contributing_documents[0]
                                if len(contributing_documents) == 1
                                else ""
                            ),
                            family="objective_findings",
                            item_key=item_key,
                            payload=payload,
                            source_refs=source_refs,
                            confidence=finding.certainty,
                        )
                    )
                finding_offset += len(findings)
                if finding_offset >= finding_total:
                    break
        return items, {
            "published_objective_analyses": published_analysis_count,
            "objective_findings": len(items),
            "objective_evidence": len(exported_evidence_keys),
        }

def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
