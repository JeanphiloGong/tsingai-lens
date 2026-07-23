from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from application.source.collection_service import CollectionService
from domain.core import ComparisonFactSet
from domain.core.paper_fact import PaperFactSet
from domain.evaluation import (
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
)
from domain.ports import (
    ComparisonRepository,
    EvaluationRepository,
    ObjectiveRepository,
    PaperFactRepository,
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
        paper_fact_repository: PaperFactRepository,
        objective_repository: ObjectiveRepository,
        comparison_repository: ComparisonRepository,
        evaluation_repository: EvaluationRepository,
    ) -> None:
        self.collection_service = collection_service
        self.paper_fact_repository = paper_fact_repository
        self.objective_repository = objective_repository
        self.comparison_repository = comparison_repository
        self.evaluation_repository = evaluation_repository

    def create_core_snapshot(
        self,
        *,
        collection_id: str,
        fact_source: str = "objective_first",
        snapshot_id: str | None = None,
        system_context: dict[str, Any] | None = None,
    ) -> EvaluationPredictionSnapshot:
        self.collection_service.get_collection(collection_id)
        paper_facts = self.paper_fact_repository.read(collection_id)
        comparison_facts = self.comparison_repository.read(collection_id)
        objective_counts = {
            "published_objective_analyses": 0,
            "objective_findings": 0,
            "objective_evidence": 0,
        }
        if fact_source == "objective_first":
            items, objective_counts = self._objective_first_items(collection_id)
        elif fact_source == "paper_facts":
            items = self._paper_fact_items(paper_facts, comparison_facts)
        else:
            raise ValueError(f"unsupported fact_source: {fact_source}")
        if not items and not self._facts_ready_for_source(
            paper_facts,
            comparison_facts,
            fact_source=fact_source,
            objective_counts=objective_counts,
        ):
            raise CoreArtifactsNotReadyForEvaluationError(collection_id, fact_source)
        snapshot = EvaluationPredictionSnapshot(
            snapshot_id=snapshot_id
            or f"pred_{collection_id}_{fact_source}_{_timestamp_id()}",
            collection_id=collection_id,
            target_layer="core",
            fact_source=fact_source,
            system_context=system_context or {},
            artifact_counts=self._artifact_counts(
                paper_facts,
                comparison_facts,
                objective_counts=objective_counts,
            ),
            items=tuple(items),
        )
        self.evaluation_repository.upsert_prediction_snapshot(snapshot)
        return snapshot

    def _objective_first_items(
        self,
        collection_id: str,
    ) -> tuple[list[EvaluationPredictionItem], dict[str, int]]:
        items: list[EvaluationPredictionItem] = []
        published_analysis_count = 0
        exported_evidence_keys: set[tuple[str, int, str]] = set()
        for objective in self.objective_repository.list_objectives(collection_id):
            analysis_version = objective.published_analysis_version
            if analysis_version is None:
                continue
            published_analysis_count += 1
            finding_offset = 0
            while True:
                findings, finding_total = self.objective_repository.list_findings(
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
                            self.objective_repository.list_evidence(
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
                    contributing_documents = (
                        finding.derivation.contributing_document_ids
                    )
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
                            confidence=finding.confidence,
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

    def _paper_fact_items(
        self,
        paper_facts: PaperFactSet,
        comparison_facts: ComparisonFactSet,
    ) -> list[EvaluationPredictionItem]:
        items: list[EvaluationPredictionItem] = []
        for result in paper_facts.measurement_results:
            sample = result.variant_id or ""
            items.append(
                EvaluationPredictionItem(
                    item_id=result.result_id,
                    document_id=result.document_id,
                    family="measurement_results",
                    item_key=self._measurement_item_key(
                        document_id=result.document_id,
                        sample=sample,
                        metric=result.property_normalized,
                    ),
                    payload={
                        "sample": sample,
                        "metric": result.property_normalized,
                        "value": self._numeric_value(result.value_payload),
                        "unit": result.unit,
                        "value_payload": dict(result.value_payload),
                    },
                    source_refs=tuple(
                        {"anchor_id": anchor_id}
                        for anchor_id in result.evidence_anchor_ids
                    ),
                    confidence=None,
                )
            )
        for relation in comparison_facts.pairwise_comparison_relations:
            items.append(
                EvaluationPredictionItem(
                    item_id=relation.relation_id,
                    document_id=relation.document_id,
                    family="comparisons",
                    item_key=self._comparison_item_key(
                        document_id=relation.document_id,
                        current_sample=relation.current_variant_id,
                        baseline_sample=relation.reference_variant_id,
                        metric=relation.property_normalized,
                    ),
                    payload={
                        "current_sample": relation.current_variant_id,
                        "baseline_sample": relation.reference_variant_id,
                        "metric": relation.property_normalized,
                        "current_value": relation.current_value,
                        "baseline_value": relation.reference_value,
                        "unit": relation.unit,
                        "direction": relation.direction,
                    },
                    source_refs=tuple(
                        {"anchor_id": anchor_id}
                        for anchor_id in relation.evidence_anchor_ids
                    ),
                    confidence=relation.confidence,
                )
            )
        return items

    def _facts_ready_for_source(
        self,
        paper_facts: PaperFactSet,
        comparison_facts: ComparisonFactSet,
        *,
        fact_source: str,
        objective_counts: dict[str, int],
    ) -> bool:
        if fact_source == "objective_first":
            return objective_counts["objective_findings"] > 0
        if fact_source == "paper_facts":
            return bool(
                paper_facts.paper_facts_ready
                or comparison_facts.comparison_artifacts_ready
            )
        return False

    def _artifact_counts(
        self,
        paper_facts: PaperFactSet,
        comparison_facts: ComparisonFactSet,
        *,
        objective_counts: dict[str, int],
    ) -> dict[str, int]:
        return {
            "document_profiles": len(paper_facts.document_profiles),
            "measurement_results": len(paper_facts.measurement_results),
            "pairwise_comparison_relations": len(
                comparison_facts.pairwise_comparison_relations
            ),
            **objective_counts,
        }

    def _measurement_item_key(
        self,
        *,
        document_id: str,
        sample: str | None,
        metric: str | None,
    ) -> str:
        return ":".join(
            [
                document_id,
                _normalize_key(sample or "unspecified_sample"),
                _normalize_key(metric or "unspecified_metric"),
            ]
        )

    def _comparison_item_key(
        self,
        *,
        document_id: str,
        current_sample: str | None,
        baseline_sample: str | None,
        metric: str | None,
    ) -> str:
        return ":".join(
            [
                document_id,
                _normalize_key(current_sample or "unspecified_current"),
                _normalize_key(baseline_sample or "unspecified_baseline"),
                _normalize_key(metric or "unspecified_metric"),
            ]
        )

    def _sample_label(self, payload: dict[str, Any]) -> str:
        for key in ("sample", "sample_id", "label", "variant_id", "name"):
            value = payload.get(key)
            if value:
                return str(value).strip()
        return ""

    def _numeric_value(self, payload: dict[str, Any]) -> float | None:
        for key in ("numeric_value", "value", "mean", "current_value"):
            value = payload.get(key)
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _baseline_numeric_value(self, payload: dict[str, Any]) -> float | None:
        for key in ("baseline_value", "reference_value", "baseline_numeric_value"):
            value = payload.get(key)
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _normalize_key(value: str) -> str:
    return "_".join(str(value or "").strip().lower().split()) or "unspecified"
