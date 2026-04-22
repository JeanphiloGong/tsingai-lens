from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


_CORE_GRAPH_GENERATED_KEYS = (
    "document_profiles_generated",
    "evidence_cards_generated",
    "comparable_results_generated",
    "collection_comparable_results_generated",
)
_CORE_GRAPH_READY_KEYS = (
    "document_profiles_ready",
    "evidence_cards_ready",
    "comparable_results_ready",
    "collection_comparable_results_ready",
)


@dataclass(frozen=True)
class ArtifactStatusRecord:
    collection_id: str
    output_path: str
    documents_generated: bool
    documents_ready: bool
    document_profiles_generated: bool
    document_profiles_ready: bool
    evidence_anchors_generated: bool
    evidence_anchors_ready: bool
    method_facts_generated: bool
    method_facts_ready: bool
    evidence_cards_generated: bool
    evidence_cards_ready: bool
    characterization_observations_generated: bool
    characterization_observations_ready: bool
    structure_features_generated: bool
    structure_features_ready: bool
    test_conditions_generated: bool
    test_conditions_ready: bool
    baseline_references_generated: bool
    baseline_references_ready: bool
    sample_variants_generated: bool
    sample_variants_ready: bool
    measurement_results_generated: bool
    measurement_results_ready: bool
    comparable_results_generated: bool
    comparable_results_ready: bool
    collection_comparable_results_generated: bool
    collection_comparable_results_ready: bool
    collection_comparable_results_stale: bool
    comparison_rows_generated: bool
    comparison_rows_ready: bool
    comparison_rows_stale: bool
    graph_generated: bool
    graph_ready: bool
    graph_stale: bool
    blocks_generated: bool
    blocks_ready: bool
    figures_generated: bool
    figures_ready: bool
    table_rows_generated: bool
    table_rows_ready: bool
    table_cells_generated: bool
    table_cells_ready: bool
    procedure_blocks_generated: bool
    procedure_blocks_ready: bool
    protocol_steps_generated: bool
    protocol_steps_ready: bool
    updated_at: str

    @classmethod
    def empty(
        cls,
        *,
        collection_id: str,
        output_path: str,
        updated_at: str,
    ) -> "ArtifactStatusRecord":
        return cls.build(
            collection_id=collection_id,
            output_path=output_path,
            updated_at=updated_at,
        )

    @classmethod
    def build(
        cls,
        *,
        collection_id: str,
        output_path: str,
        updated_at: str,
        documents_generated: bool = False,
        documents_ready: bool = False,
        document_profiles_generated: bool = False,
        document_profiles_ready: bool = False,
        evidence_anchors_generated: bool = False,
        evidence_anchors_ready: bool = False,
        method_facts_generated: bool = False,
        method_facts_ready: bool = False,
        evidence_cards_generated: bool = False,
        evidence_cards_ready: bool = False,
        characterization_observations_generated: bool = False,
        characterization_observations_ready: bool = False,
        structure_features_generated: bool = False,
        structure_features_ready: bool = False,
        test_conditions_generated: bool = False,
        test_conditions_ready: bool = False,
        baseline_references_generated: bool = False,
        baseline_references_ready: bool = False,
        sample_variants_generated: bool = False,
        sample_variants_ready: bool = False,
        measurement_results_generated: bool = False,
        measurement_results_ready: bool = False,
        comparable_results_generated: bool = False,
        comparable_results_ready: bool = False,
        collection_comparable_results_generated: bool = False,
        collection_comparable_results_ready: bool = False,
        collection_comparable_results_stale: bool = False,
        comparison_rows_generated: bool = False,
        comparison_rows_ready: bool = False,
        comparison_rows_stale: bool = False,
        graph_stale: bool = False,
        blocks_generated: bool = False,
        blocks_ready: bool = False,
        figures_generated: bool = False,
        figures_ready: bool = False,
        table_rows_generated: bool = False,
        table_rows_ready: bool = False,
        table_cells_generated: bool = False,
        table_cells_ready: bool = False,
        procedure_blocks_generated: bool = False,
        procedure_blocks_ready: bool = False,
        protocol_steps_generated: bool = False,
        protocol_steps_ready: bool = False,
    ) -> "ArtifactStatusRecord":
        collection_comparable_results_generated = bool(
            collection_comparable_results_generated
        )
        collection_comparable_results_stale = (
            collection_comparable_results_generated
            and bool(collection_comparable_results_stale)
        )
        collection_comparable_results_ready = bool(
            collection_comparable_results_ready
        ) and not collection_comparable_results_stale
        comparison_rows_generated = bool(comparison_rows_generated)
        comparison_rows_stale = comparison_rows_generated and bool(comparison_rows_stale)
        comparison_rows_ready = bool(comparison_rows_ready) and not comparison_rows_stale

        graph_inputs = {
            "document_profiles_generated": bool(document_profiles_generated),
            "document_profiles_ready": bool(document_profiles_ready),
            "evidence_cards_generated": bool(evidence_cards_generated),
            "evidence_cards_ready": bool(evidence_cards_ready),
            "comparable_results_generated": bool(comparable_results_generated),
            "comparable_results_ready": bool(comparable_results_ready),
            "collection_comparable_results_generated": collection_comparable_results_generated,
            "collection_comparable_results_ready": collection_comparable_results_ready,
        }
        core_graph_generated = all(
            graph_inputs[key] for key in _CORE_GRAPH_GENERATED_KEYS
        )
        derived_graph_stale = core_graph_generated and (
            bool(graph_stale) or collection_comparable_results_stale
        )
        core_graph_ready = (
            core_graph_generated
            and any(
                graph_inputs[key] for key in _CORE_GRAPH_READY_KEYS
            )
            and not derived_graph_stale
        )
        return cls(
            collection_id=str(collection_id),
            output_path=str(output_path),
            documents_generated=bool(documents_generated),
            documents_ready=bool(documents_ready),
            document_profiles_generated=bool(document_profiles_generated),
            document_profiles_ready=bool(document_profiles_ready),
            evidence_anchors_generated=bool(evidence_anchors_generated),
            evidence_anchors_ready=bool(evidence_anchors_ready),
            method_facts_generated=bool(method_facts_generated),
            method_facts_ready=bool(method_facts_ready),
            evidence_cards_generated=bool(evidence_cards_generated),
            evidence_cards_ready=bool(evidence_cards_ready),
            characterization_observations_generated=bool(
                characterization_observations_generated
            ),
            characterization_observations_ready=bool(
                characterization_observations_ready
            ),
            structure_features_generated=bool(structure_features_generated),
            structure_features_ready=bool(structure_features_ready),
            test_conditions_generated=bool(test_conditions_generated),
            test_conditions_ready=bool(test_conditions_ready),
            baseline_references_generated=bool(baseline_references_generated),
            baseline_references_ready=bool(baseline_references_ready),
            sample_variants_generated=bool(sample_variants_generated),
            sample_variants_ready=bool(sample_variants_ready),
            measurement_results_generated=bool(measurement_results_generated),
            measurement_results_ready=bool(measurement_results_ready),
            comparable_results_generated=bool(comparable_results_generated),
            comparable_results_ready=bool(comparable_results_ready),
            collection_comparable_results_generated=collection_comparable_results_generated,
            collection_comparable_results_ready=collection_comparable_results_ready,
            collection_comparable_results_stale=collection_comparable_results_stale,
            comparison_rows_generated=comparison_rows_generated,
            comparison_rows_ready=comparison_rows_ready,
            comparison_rows_stale=comparison_rows_stale,
            graph_generated=core_graph_generated,
            graph_ready=core_graph_ready,
            graph_stale=derived_graph_stale,
            blocks_generated=bool(blocks_generated),
            blocks_ready=bool(blocks_ready),
            figures_generated=bool(figures_generated),
            figures_ready=bool(figures_ready),
            table_rows_generated=bool(table_rows_generated),
            table_rows_ready=bool(table_rows_ready),
            table_cells_generated=bool(table_cells_generated),
            table_cells_ready=bool(table_cells_ready),
            procedure_blocks_generated=bool(procedure_blocks_generated),
            procedure_blocks_ready=bool(procedure_blocks_ready),
            protocol_steps_generated=bool(protocol_steps_generated),
            protocol_steps_ready=bool(protocol_steps_ready),
            updated_at=str(updated_at),
        )

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        collection_id: str,
    ) -> "ArtifactStatusRecord":
        source = dict(payload or {})
        return cls.build(
            collection_id=str(source.get("collection_id") or collection_id),
            output_path=_normalize_text(source.get("output_path")) or "",
            updated_at=_normalize_text(source.get("updated_at")) or "",
            documents_generated=_normalize_bool(source.get("documents_generated")),
            documents_ready=_normalize_bool(source.get("documents_ready")),
            document_profiles_generated=_normalize_bool(
                source.get("document_profiles_generated")
            ),
            document_profiles_ready=_normalize_bool(source.get("document_profiles_ready")),
            evidence_anchors_generated=_normalize_bool(source.get("evidence_anchors_generated")),
            evidence_anchors_ready=_normalize_bool(source.get("evidence_anchors_ready")),
            method_facts_generated=_normalize_bool(source.get("method_facts_generated")),
            method_facts_ready=_normalize_bool(source.get("method_facts_ready")),
            evidence_cards_generated=_normalize_bool(source.get("evidence_cards_generated")),
            evidence_cards_ready=_normalize_bool(source.get("evidence_cards_ready")),
            characterization_observations_generated=_normalize_bool(
                source.get("characterization_observations_generated")
            ),
            characterization_observations_ready=_normalize_bool(
                source.get("characterization_observations_ready")
            ),
            structure_features_generated=_normalize_bool(
                source.get("structure_features_generated")
            ),
            structure_features_ready=_normalize_bool(source.get("structure_features_ready")),
            test_conditions_generated=_normalize_bool(source.get("test_conditions_generated")),
            test_conditions_ready=_normalize_bool(source.get("test_conditions_ready")),
            baseline_references_generated=_normalize_bool(
                source.get("baseline_references_generated")
            ),
            baseline_references_ready=_normalize_bool(
                source.get("baseline_references_ready")
            ),
            sample_variants_generated=_normalize_bool(source.get("sample_variants_generated")),
            sample_variants_ready=_normalize_bool(source.get("sample_variants_ready")),
            measurement_results_generated=_normalize_bool(
                source.get("measurement_results_generated")
            ),
            measurement_results_ready=_normalize_bool(
                source.get("measurement_results_ready")
            ),
            comparable_results_generated=_normalize_bool(
                source.get("comparable_results_generated")
            ),
            comparable_results_ready=_normalize_bool(source.get("comparable_results_ready")),
            collection_comparable_results_generated=_normalize_bool(
                source.get("collection_comparable_results_generated")
            ),
            collection_comparable_results_ready=_normalize_bool(
                source.get("collection_comparable_results_ready")
            ),
            collection_comparable_results_stale=_normalize_bool(
                source.get("collection_comparable_results_stale")
            ),
            comparison_rows_generated=_normalize_bool(
                source.get("comparison_rows_generated")
            ),
            comparison_rows_ready=_normalize_bool(source.get("comparison_rows_ready")),
            comparison_rows_stale=_normalize_bool(source.get("comparison_rows_stale")),
            graph_stale=_normalize_bool(source.get("graph_stale")),
            blocks_generated=_normalize_bool(source.get("blocks_generated")),
            blocks_ready=_normalize_bool(source.get("blocks_ready")),
            figures_generated=_normalize_bool(source.get("figures_generated")),
            figures_ready=_normalize_bool(source.get("figures_ready")),
            table_rows_generated=_normalize_bool(source.get("table_rows_generated")),
            table_rows_ready=_normalize_bool(source.get("table_rows_ready")),
            table_cells_generated=_normalize_bool(source.get("table_cells_generated")),
            table_cells_ready=_normalize_bool(source.get("table_cells_ready")),
            procedure_blocks_generated=_normalize_bool(
                source.get("procedure_blocks_generated")
            ),
            procedure_blocks_ready=_normalize_bool(source.get("procedure_blocks_ready")),
            protocol_steps_generated=_normalize_bool(source.get("protocol_steps_generated")),
            protocol_steps_ready=_normalize_bool(source.get("protocol_steps_ready")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "output_path": self.output_path,
            "documents_generated": self.documents_generated,
            "documents_ready": self.documents_ready,
            "document_profiles_generated": self.document_profiles_generated,
            "document_profiles_ready": self.document_profiles_ready,
            "evidence_anchors_generated": self.evidence_anchors_generated,
            "evidence_anchors_ready": self.evidence_anchors_ready,
            "method_facts_generated": self.method_facts_generated,
            "method_facts_ready": self.method_facts_ready,
            "evidence_cards_generated": self.evidence_cards_generated,
            "evidence_cards_ready": self.evidence_cards_ready,
            "characterization_observations_generated": self.characterization_observations_generated,
            "characterization_observations_ready": self.characterization_observations_ready,
            "structure_features_generated": self.structure_features_generated,
            "structure_features_ready": self.structure_features_ready,
            "test_conditions_generated": self.test_conditions_generated,
            "test_conditions_ready": self.test_conditions_ready,
            "baseline_references_generated": self.baseline_references_generated,
            "baseline_references_ready": self.baseline_references_ready,
            "sample_variants_generated": self.sample_variants_generated,
            "sample_variants_ready": self.sample_variants_ready,
            "measurement_results_generated": self.measurement_results_generated,
            "measurement_results_ready": self.measurement_results_ready,
            "comparable_results_generated": self.comparable_results_generated,
            "comparable_results_ready": self.comparable_results_ready,
            "collection_comparable_results_generated": self.collection_comparable_results_generated,
            "collection_comparable_results_ready": self.collection_comparable_results_ready,
            "collection_comparable_results_stale": self.collection_comparable_results_stale,
            "comparison_rows_generated": self.comparison_rows_generated,
            "comparison_rows_ready": self.comparison_rows_ready,
            "comparison_rows_stale": self.comparison_rows_stale,
            "graph_generated": self.graph_generated,
            "graph_ready": self.graph_ready,
            "graph_stale": self.graph_stale,
            "blocks_generated": self.blocks_generated,
            "blocks_ready": self.blocks_ready,
            "figures_generated": self.figures_generated,
            "figures_ready": self.figures_ready,
            "table_rows_generated": self.table_rows_generated,
            "table_rows_ready": self.table_rows_ready,
            "table_cells_generated": self.table_cells_generated,
            "table_cells_ready": self.table_cells_ready,
            "procedure_blocks_generated": self.procedure_blocks_generated,
            "procedure_blocks_ready": self.procedure_blocks_ready,
            "protocol_steps_generated": self.protocol_steps_generated,
            "protocol_steps_ready": self.protocol_steps_ready,
            "updated_at": self.updated_at,
        }


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return bool(value)


__all__ = [
    "ArtifactStatusRecord",
]
