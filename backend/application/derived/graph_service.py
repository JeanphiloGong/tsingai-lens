from __future__ import annotations

from pathlib import Path
from typing import Any

from application.source.collection_service import CollectionService
from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from application.derived.core_fact_projection import build_core_fact_projection_records
from application.derived.graph_projection_service import (
    load_core_graph_payload,
)
from domain.ports import ObjectiveRepository, PaperFactRepository
from infra.derived.graph.graphml import to_graphml as render_graphml


_NEIGHBORHOOD_MAX_NODES = 2_147_483_647


class GraphNotReadyError(RuntimeError):
    """Raised when a collection exists but Core graph inputs are not ready."""

    def __init__(
        self,
        collection_id: str,
        output_dir: Path,
        missing_artifacts: list[str] | None = None,
    ) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        self.missing_artifacts = missing_artifacts or []
        super().__init__(f"graph not ready: {collection_id}")


class GraphNodeNotFoundError(RuntimeError):
    """Raised when one graph node is missing from the Core-derived projection."""

    def __init__(self, collection_id: str, node_id: str) -> None:
        self.collection_id = collection_id
        self.node_id = node_id
        super().__init__(f"graph node not found: {collection_id}/{node_id}")


def resolve_collection_output_dir(
    collection_id: str,
    *,
    collection_service: CollectionService,
) -> Path:
    collection_service.get_collection(collection_id)

    paths = collection_service.get_paths(collection_id)
    if not paths.output_dir.exists():
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=paths.output_dir.resolve(),
            missing_artifacts=["core_fact_repository.comparison_artifacts"],
        )
    return paths.output_dir.resolve()


def _graph_error_output_dir(
    collection_id: str,
    *,
    collection_service: CollectionService,
) -> Path:
    try:
        return resolve_collection_output_dir(
            collection_id,
            collection_service=collection_service,
        )
    except GraphNotReadyError as exc:
        return exc.output_dir


def load_graph_payload(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
    *,
    collection_service: CollectionService,
    paper_fact_repository: PaperFactRepository,
    objective_repository: ObjectiveRepository,
    comparison_service: ComparisonService,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    collection_service.get_collection(collection_id)
    paper_facts = paper_fact_repository.read(collection_id)
    objective_facts = objective_repository.read(collection_id)
    try:
        comparison_projection = comparison_service.read_comparison_projection(
            collection_id
        )
    except ComparisonRowsNotReadyError:
        comparison_projection = None
    evidence_cards_ready = bool(
        paper_facts.evidence_cards_ready or objective_facts.objective_evidence_units
    )
    graph_ready = bool(
        paper_facts.document_profiles
        and evidence_cards_ready
        and (
            objective_facts.objective_evidence_units
            or objective_facts.objective_logic_chains
            or bool(comparison_projection and comparison_projection.comparison_rows)
        )
    )
    if not graph_ready:
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=_graph_error_output_dir(
                collection_id,
                collection_service=collection_service,
            ),
            missing_artifacts=_missing_core_graph_inputs(
                paper_facts,
                objective_facts,
                comparison_projection,
            ),
        )
    projection = build_core_fact_projection_records(
        paper_facts,
        comparison_projection.comparison_rows if comparison_projection else (),
    )

    return load_core_graph_payload(
        profiles=tuple(
            profile.to_record() for profile in paper_facts.document_profiles
        ),
        research_objectives=tuple(
            objective.to_record() for objective in objective_facts.research_objectives
        ),
        objective_evidence_units=tuple(
            unit.to_record() for unit in objective_facts.objective_evidence_units
        ),
        objective_logic_chains=tuple(
            chain.to_record() for chain in objective_facts.objective_logic_chains
        ),
        max_nodes=max_nodes,
        min_weight=min_weight,
        evidence_cards=projection.evidence_cards,
        comparison_rows=projection.comparison_rows,
    )


def _missing_core_graph_inputs(
    paper_facts: Any,
    objective_facts: Any,
    comparison_projection: Any,
) -> list[str]:
    missing: list[str] = []
    if not paper_facts.document_profiles:
        missing.append("core_fact_repository.document_profiles")
    if not (
        paper_facts.evidence_cards_ready or objective_facts.objective_evidence_units
    ):
        missing.append("core_fact_repository.evidence_cards")
    if not (
        objective_facts.objective_evidence_units
        or objective_facts.objective_logic_chains
        or bool(comparison_projection and comparison_projection.comparison_rows)
    ):
        missing.append("core_fact_repository.comparison_artifacts")
    return missing or ["core_fact_repository.comparison_artifacts"]


def get_collection_graph(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
    *,
    collection_service: CollectionService,
    paper_fact_repository: PaperFactRepository,
    objective_repository: ObjectiveRepository,
    comparison_service: ComparisonService,
) -> dict[str, Any]:
    nodes_payload, edges_payload, truncated = load_graph_payload(
        collection_id=collection_id,
        max_nodes=max_nodes,
        min_weight=min_weight,
        collection_service=collection_service,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        comparison_service=comparison_service,
    )
    return {
        "collection_id": collection_id,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "truncated": truncated,
    }


def build_graphml(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
    *,
    collection_service: CollectionService,
    paper_fact_repository: PaperFactRepository,
    objective_repository: ObjectiveRepository,
    comparison_service: ComparisonService,
) -> tuple[bytes, str]:
    nodes_payload, edges_payload, _ = load_graph_payload(
        collection_id=collection_id,
        max_nodes=max_nodes,
        min_weight=min_weight,
        collection_service=collection_service,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        comparison_service=comparison_service,
    )
    return to_graphml(nodes_payload, edges_payload), f"{collection_id}.graphml"


def get_collection_graph_neighbors(
    collection_id: str,
    node_id: str,
    *,
    collection_service: CollectionService,
    paper_fact_repository: PaperFactRepository,
    objective_repository: ObjectiveRepository,
    comparison_service: ComparisonService,
) -> dict[str, Any]:
    nodes_payload, edges_payload, _ = load_graph_payload(
        collection_id=collection_id,
        max_nodes=_NEIGHBORHOOD_MAX_NODES,
        min_weight=0.0,
        collection_service=collection_service,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        comparison_service=comparison_service,
    )

    node_ids = {str(node.get("id")) for node in nodes_payload}
    if node_id not in node_ids:
        raise GraphNodeNotFoundError(collection_id, node_id)

    neighborhood_edges = [
        edge
        for edge in edges_payload
        if str(edge.get("source")) == node_id or str(edge.get("target")) == node_id
    ]
    neighborhood_node_ids = {node_id}
    for edge in neighborhood_edges:
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        neighborhood_node_ids.add(source)
        neighborhood_node_ids.add(target)
    neighborhood_nodes = [
        node for node in nodes_payload if str(node.get("id")) in neighborhood_node_ids
    ]

    return {
        "collection_id": collection_id,
        "center_node_id": node_id,
        "nodes": neighborhood_nodes,
        "edges": neighborhood_edges,
        "truncated": False,
    }


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    return render_graphml(nodes, edges)


__all__ = [
    "build_graphml",
    "get_collection_graph_neighbors",
    "get_collection_graph",
    "GraphNodeNotFoundError",
    "GraphNotReadyError",
    "load_graph_payload",
    "resolve_collection_output_dir",
    "to_graphml",
]
