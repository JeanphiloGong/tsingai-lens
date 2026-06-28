from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from application.source.collection_service import CollectionService
from domain.core import CoreFactSet
from domain.evaluation import (
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
)
from domain.ports import CoreFactRepository, EvaluationRepository
from infra.persistence.factory import (
    build_core_fact_repository,
    build_evaluation_repository,
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
        collection_service: CollectionService | None = None,
        core_fact_repository: CoreFactRepository | None = None,
        evaluation_repository: EvaluationRepository | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.core_fact_repository = core_fact_repository or build_core_fact_repository()
        self.evaluation_repository = (
            evaluation_repository or build_evaluation_repository()
        )

    def create_core_snapshot(
        self,
        *,
        collection_id: str,
        fact_source: str = "objective_first",
        snapshot_id: str | None = None,
        system_context: dict[str, Any] | None = None,
    ) -> EvaluationPredictionSnapshot:
        self.collection_service.get_collection(collection_id)
        facts = self.core_fact_repository.read_collection_facts(collection_id)
        items = self._prediction_items(facts, fact_source=fact_source)
        if not items and not self._facts_ready_for_source(
            facts,
            fact_source=fact_source,
        ):
            raise CoreArtifactsNotReadyForEvaluationError(collection_id, fact_source)
        snapshot = EvaluationPredictionSnapshot(
            snapshot_id=snapshot_id
            or f"pred_{collection_id}_{fact_source}_{_timestamp_id()}",
            collection_id=collection_id,
            target_layer="core",
            fact_source=fact_source,
            system_context=system_context or {},
            artifact_counts=self._artifact_counts(facts),
            items=tuple(items),
        )
        self.evaluation_repository.upsert_prediction_snapshot(snapshot)
        return snapshot

    def _prediction_items(
        self,
        facts: CoreFactSet,
        *,
        fact_source: str,
    ) -> list[EvaluationPredictionItem]:
        if fact_source == "objective_first":
            return self._objective_first_items(facts)
        if fact_source == "paper_facts":
            return self._paper_fact_items(facts)
        raise ValueError(f"unsupported fact_source: {fact_source}")

    def _objective_first_items(
        self,
        facts: CoreFactSet,
    ) -> list[EvaluationPredictionItem]:
        items: list[EvaluationPredictionItem] = []
        for unit in facts.objective_evidence_units:
            if unit.unit_kind == "measurement":
                items.append(
                    EvaluationPredictionItem(
                        item_id=unit.evidence_unit_id,
                        document_id=unit.document_id,
                        family="measurement_results",
                        item_key=self._measurement_item_key(
                            document_id=unit.document_id,
                            sample=self._sample_label(unit.sample_context),
                            metric=unit.property_normalized,
                        ),
                        payload={
                            "sample": self._sample_label(unit.sample_context),
                            "metric": unit.property_normalized,
                            "value": self._numeric_value(unit.value_payload),
                            "unit": unit.unit,
                            "value_payload": dict(unit.value_payload),
                        },
                        source_refs=tuple(unit.source_refs),
                        confidence=unit.confidence,
                    )
                )
            if unit.unit_kind == "comparison":
                items.append(
                    EvaluationPredictionItem(
                        item_id=unit.evidence_unit_id,
                        document_id=unit.document_id,
                        family="comparisons",
                        item_key=self._comparison_item_key(
                            document_id=unit.document_id,
                            current_sample=self._sample_label(unit.sample_context),
                            baseline_sample=self._sample_label(unit.baseline_context),
                            metric=unit.property_normalized,
                        ),
                        payload={
                            "current_sample": self._sample_label(unit.sample_context),
                            "baseline_sample": self._sample_label(unit.baseline_context),
                            "metric": unit.property_normalized,
                            "current_value": self._numeric_value(unit.value_payload),
                            "baseline_value": self._baseline_numeric_value(
                                unit.value_payload
                            ),
                            "direction": self._text(unit.value_payload.get("direction")),
                            "value_payload": dict(unit.value_payload),
                            "unit": unit.unit,
                        },
                        source_refs=tuple(unit.source_refs),
                        confidence=unit.confidence,
                    )
                )
        return items

    def _paper_fact_items(self, facts: CoreFactSet) -> list[EvaluationPredictionItem]:
        items: list[EvaluationPredictionItem] = []
        for result in facts.measurement_results:
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
        for relation in facts.pairwise_comparison_relations:
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

    def _facts_ready_for_source(self, facts: CoreFactSet, *, fact_source: str) -> bool:
        if fact_source == "objective_first":
            return bool(facts.research_objectives_ready)
        if fact_source == "paper_facts":
            return bool(facts.paper_facts_ready or facts.comparison_artifacts_ready)
        return False

    def _artifact_counts(self, facts: CoreFactSet) -> dict[str, int]:
        return {
            "document_profiles": len(facts.document_profiles),
            "measurement_results": len(facts.measurement_results),
            "pairwise_comparison_relations": len(facts.pairwise_comparison_relations),
            "objective_evidence_units": len(facts.objective_evidence_units),
            "objective_logic_chains": len(facts.objective_logic_chains),
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
