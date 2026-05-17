from __future__ import annotations

import sys
from hashlib import sha1
from types import SimpleNamespace

from application.derived.graph_projection_service import load_core_graph_payload
from domain.core.document_profile import DocumentProfile
from domain.core.fact_store import CoreFactSet
from domain.core.research_objective import (
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ResearchObjective,
)
from infra.persistence.sqlite import SqliteCoreFactRepository


def _semantic_node_id(prefix: str, label: str) -> str:
    return f"{prefix}:{sha1(label.lower().encode('utf-8')).hexdigest()}"


def _profile(document_id: str = "paper-1") -> dict:
    return {
        "document_id": document_id,
        "collection_id": "col-1",
        "title": "Core Graph Paper",
        "source_filename": "paper.txt",
        "doc_type": "experimental",
        "parsing_warnings": [],
        "confidence": 0.91,
    }


def _objective(objective_id: str = "obj-1") -> dict:
    return {
        "objective_id": objective_id,
        "question": "How does scan speed affect LPBF 316L tensile strength?",
        "material_scope": ["316L stainless steel"],
        "process_axes": ["LPBF", "scan speed"],
        "property_axes": ["tensile strength"],
        "comparison_intent": "compare process variants",
        "seed_document_ids": ["paper-1"],
        "excluded_document_ids": [],
        "confidence": 0.9,
        "reason": "Collection contains tensile data for process variants.",
    }


def _measurement_unit(
    evidence_unit_id: str = "oeu-1",
    *,
    objective_id: str = "obj-1",
    document_id: str = "paper-1",
) -> dict:
    return {
        "evidence_unit_id": evidence_unit_id,
        "objective_id": objective_id,
        "document_id": document_id,
        "unit_kind": "measurement",
        "property_normalized": "yield strength",
        "material_system": {"family": "316L stainless steel"},
        "sample_context": {"Case": "15", "sample_number": "15"},
        "process_context": {"scan speed": "900 mm/s"},
        "resolved_condition": {"energy density": "100 J/mm^3"},
        "test_condition": {"method": "tensile test", "Case": "15"},
        "value_payload": {"source_value_text": "365.6", "value": 365.6},
        "unit": "MPa",
        "baseline_context": {"reference": "Case 1"},
        "interpretation": None,
        "source_refs": [
            {
                "source_kind": "table",
                "source_ref": "table-2",
                "page": 7,
                "role": "current_experimental_evidence",
            }
        ],
        "evidence_anchor_ids": [],
        "join_keys": {"Case": "15"},
        "resolution_status": "resolved",
        "confidence": 0.88,
    }


def _comparison_unit() -> dict:
    return {
        **_measurement_unit("oeu-cmp"),
        "unit_kind": "comparison",
        "property_normalized": "yield strength",
        "value_payload": {"source_value_text": "Case 15 higher than Case 1"},
        "interpretation": "Case 15 improved yield strength over the baseline.",
    }


def _logic_chain() -> dict:
    return {
        "logic_chain_id": "chain-1",
        "objective_id": "obj-1",
        "chain_scope": "objective",
        "document_id": None,
        "question": "How does scan speed affect LPBF 316L tensile strength?",
        "evidence_unit_ids": ["oeu-1", "oeu-cmp"],
        "chain_payload": {},
        "summary": "Scan speed changes yield strength through process variants.",
        "confidence": 0.82,
    }


def _core_graph_fact_set(collection_id: str) -> CoreFactSet:
    return CoreFactSet(
        research_objectives_ready=True,
        document_profiles=(DocumentProfile.from_mapping(_profile()),),
        research_objectives=(ResearchObjective.from_mapping(_objective()),),
        objective_evidence_units=(
            ObjectiveEvidenceUnit.from_mapping(_measurement_unit()),
            ObjectiveEvidenceUnit.from_mapping(_comparison_unit()),
        ),
        objective_logic_chains=(ObjectiveLogicChain.from_mapping(_logic_chain()),),
    )


def test_core_projection_builds_objective_first_graph_payload():
    nodes, edges, truncated = load_core_graph_payload(
        profiles=(_profile(),),
        research_objectives=(_objective(),),
        objective_evidence_units=(_measurement_unit(), _comparison_unit()),
        objective_logic_chains=(_logic_chain(),),
        max_nodes=40,
        min_weight=0.0,
    )

    assert truncated is False
    nodes_by_id = {node["id"]: node for node in nodes}
    assert "obj:obj-1" in nodes_by_id
    assert "doc:paper-1" in nodes_by_id
    assert "evi:oeu-1" in nodes_by_id
    assert "evi:oeu-cmp" in nodes_by_id
    assert "chain:chain-1" in nodes_by_id
    assert not any(node["type"] == "comparison" for node in nodes)

    assert nodes_by_id["obj:obj-1"]["type"] == "objective"
    assert nodes_by_id["evi:oeu-1"]["type"] == "measurement"
    assert nodes_by_id["evi:oeu-cmp"]["type"] == "controlled_comparison"
    assert nodes_by_id["chain:chain-1"]["type"] == "logic_chain"
    assert nodes_by_id[_semantic_node_id("mat", "316L stainless steel")]["type"] == (
        "material"
    )
    assert nodes_by_id[_semantic_node_id("prop", "yield strength")]["type"] == "property"
    assert nodes_by_id[_semantic_node_id("sample", "Case: 15; sample_number: 15")][
        "type"
    ] == "sample"
    assert nodes_by_id[_semantic_node_id("proc", "energy density: 100 J/mm^3; scan speed: 900 mm/s")][
        "type"
    ] == "process"
    assert nodes_by_id[_semantic_node_id("tc", "method: tensile test")]["type"] == (
        "test_condition"
    )

    edge_descriptions = {edge["edge_description"] for edge in edges}
    assert {
        "objective_to_evidence",
        "document_to_evidence",
        "evidence_to_material",
        "evidence_to_property",
        "evidence_to_sample",
        "evidence_to_process",
        "evidence_to_test_condition",
        "objective_to_logic_chain",
        "logic_chain_to_evidence",
    }.issubset(edge_descriptions)


def test_core_projection_keeps_case_out_of_test_condition_nodes():
    unit = {
        **_measurement_unit(),
        "test_condition": {"Case": "15"},
        "sample_context": {"Case": "15"},
        "join_keys": {"Case": "15"},
    }

    nodes, _edges, _truncated = load_core_graph_payload(
        profiles=(_profile(),),
        research_objectives=(_objective(),),
        objective_evidence_units=(unit,),
        objective_logic_chains=(),
        max_nodes=40,
        min_weight=0.0,
    )

    test_condition_labels = {
        node["label"] for node in nodes if node["type"] == "test_condition"
    }
    sample_labels = {node["label"] for node in nodes if node["type"] == "sample"}
    assert test_condition_labels == set()
    assert sample_labels == {"Case: 15"}


def test_core_projection_truncation_reserves_objective_backbone_capacity():
    profiles = tuple(_profile(f"paper-{index}") for index in range(1, 5))
    units = tuple(
        {
            **_measurement_unit(f"oeu-{index}", document_id=f"paper-{index}"),
            "value_payload": {"source_value_text": str(index), "value": float(index)},
        }
        for index in range(1, 9)
    )

    nodes, _edges, truncated = load_core_graph_payload(
        profiles=profiles,
        research_objectives=(_objective(),),
        objective_evidence_units=units,
        objective_logic_chains=(),
        max_nodes=10,
        min_weight=0.0,
    )

    assert truncated is True
    backbone_count = sum(
        1
        for node in nodes
        if node["type"] in {"objective", "document", "measurement", "controlled_comparison"}
    )
    semantic_count = len(nodes) - backbone_count
    assert backbone_count >= 6
    assert semantic_count <= 4


def test_graph_service_serves_objective_projection_without_comparison_rows(
    monkeypatch,
    tmp_path,
):
    try:
        import fastapi  # noqa: F401
    except ImportError:
        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail):  # noqa: ANN001
                self.status_code = status_code
                self.detail = detail
                super().__init__(detail)

        monkeypatch.setitem(
            sys.modules,
            "fastapi",
            SimpleNamespace(HTTPException=_HTTPException),
        )

    import application.derived.graph_service as graph_service

    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    core_fact_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    monkeypatch.setattr(graph_service, "collection_service", collection_service)
    monkeypatch.setattr(graph_service, "core_fact_repository", core_fact_repository)

    collection = collection_service.create_collection("Objective Graph Collection")
    collection_id = collection["collection_id"]

    core_fact_repository.replace_collection_research_objectives(
        collection_id,
        paper_skims=(),
        research_objectives=_core_graph_fact_set(collection_id).research_objectives,
        objective_contexts=(),
        objective_paper_frames=(),
        objective_evidence_routes=(),
        objective_evidence_units=_core_graph_fact_set(collection_id).objective_evidence_units,
        objective_logic_chains=_core_graph_fact_set(collection_id).objective_logic_chains,
    )
    core_fact_repository.replace_collection_document_profiles(
        collection_id,
        _core_graph_fact_set(collection_id).document_profiles,
    )

    payload = graph_service.get_collection_graph(
        collection_id=collection_id,
        max_nodes=40,
        min_weight=0.0,
    )

    assert payload["collection_id"] == collection_id
    assert any(node["type"] == "objective" for node in payload["nodes"])
    assert any(node["type"] == "measurement" for node in payload["nodes"])
    assert not any(node["type"] == "comparison" for node in payload["nodes"])

    graphml_bytes, filename = graph_service.build_graphml(
        collection_id=collection_id,
        max_nodes=40,
        min_weight=0.0,
    )

    assert filename == f"{collection_id}.graphml"
    assert b"<graphml" in graphml_bytes


def test_graph_service_returns_one_hop_neighbors(monkeypatch, tmp_path):
    try:
        import fastapi  # noqa: F401
    except ImportError:
        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail):  # noqa: ANN001
                self.status_code = status_code
                self.detail = detail
                super().__init__(detail)

        monkeypatch.setitem(
            sys.modules,
            "fastapi",
            SimpleNamespace(HTTPException=_HTTPException),
        )

    import application.derived.graph_service as graph_service

    from application.source.collection_service import CollectionService

    collection_service = CollectionService(tmp_path / "collections")
    core_fact_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    monkeypatch.setattr(graph_service, "collection_service", collection_service)
    monkeypatch.setattr(graph_service, "core_fact_repository", core_fact_repository)

    collection = collection_service.create_collection("Graph Neighborhood Collection")
    collection_id = collection["collection_id"]
    fact_set = _core_graph_fact_set(collection_id)
    core_fact_repository.replace_collection_research_objectives(
        collection_id,
        paper_skims=(),
        research_objectives=fact_set.research_objectives,
        objective_contexts=(),
        objective_paper_frames=(),
        objective_evidence_routes=(),
        objective_evidence_units=fact_set.objective_evidence_units,
        objective_logic_chains=fact_set.objective_logic_chains,
    )
    core_fact_repository.replace_collection_document_profiles(
        collection_id,
        fact_set.document_profiles,
    )

    payload = graph_service.get_collection_graph_neighbors(
        collection_id=collection_id,
        node_id="evi:oeu-1",
    )

    assert payload["collection_id"] == collection_id
    assert payload["center_node_id"] == "evi:oeu-1"
    assert payload["truncated"] is False
    assert {node["id"] for node in payload["nodes"]} >= {
        "doc:paper-1",
        "obj:obj-1",
        "evi:oeu-1",
    }
    assert {edge["id"] for edge in payload["edges"]} >= {
        "edge:doc:paper-1:evi:oeu-1",
        "edge:obj:obj-1:evi:oeu-1",
    }
