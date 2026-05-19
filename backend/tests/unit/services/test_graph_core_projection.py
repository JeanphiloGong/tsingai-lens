from __future__ import annotations

import sys
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


def test_core_projection_builds_semantic_logic_chain_graph_payload():
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
    assert nodes_by_id["obj:obj-1"]["type"] == "objective"
    assert {node["type"] for node in nodes} == {
        "objective",
        "material_system",
        "material_scope",
        "process_sample_context",
        "test_conditions",
        "characterization",
        "measurement_results",
        "controlled_comparisons",
        "mechanism_interpretation",
        "limitations",
    }
    assert {node["role"] for node in nodes if node["id"].startswith("step:")} == {
        "material_scope",
        "process_sample_context",
        "test_conditions",
        "characterization",
        "measurement_results",
        "controlled_comparisons",
        "mechanism_interpretation",
        "limitations",
    }
    material_nodes = [node for node in nodes if node["type"] == "material_system"]
    assert len(material_nodes) == 1
    assert material_nodes[0]["label"] == "316L stainless steel"
    assert material_nodes[0]["logic_chain_id"] is None
    assert material_nodes[0]["objective_id"] is None
    assert material_nodes[0]["metrics"]["objective_count"] == 1

    measurement_step = nodes_by_id["step:chain-1:measurement_results"]
    assert measurement_step["type"] == "measurement_results"
    assert measurement_step["metrics"]["row_count"] == 1
    assert measurement_step["detail_rows"] == [
        {
            "label": "yield strength | 365.6 MPa",
            "row_type": "measurement",
            "paper": "Core Graph Paper",
            "document_id": "paper-1",
            "evidence_unit_id": "oeu-1",
            "property": "yield strength",
            "value": "365.6 MPa",
            "unit": "MPa",
            "material": "316L stainless steel",
            "sample": "Case: 15; sample_number: 15",
            "process": "energy density: 100 J/mm^3; scan speed: 900 mm/s",
            "test_condition": "method: tensile test",
            "baseline": "reference: Case 1",
            "source": "table:table-2 p.7",
            "resolution_status": "resolved",
            "confidence": 0.88,
        }
    ]
    comparison_step = nodes_by_id["step:chain-1:controlled_comparisons"]
    assert comparison_step["detail_rows"][0]["evidence_unit_id"] == "oeu-cmp"
    assert comparison_step["detail_rows"][0]["interpretation"] == (
        "Case 15 improved yield strength over the baseline."
    )

    process_step = nodes_by_id["step:chain-1:process_sample_context"]
    assert "Case: 15" in process_step["detail_rows"][0]["sample"]
    assert not any(node["type"] == "measurement" for node in nodes)
    assert not any(node["type"] == "test_condition" for node in nodes)
    assert not any(node["type"] == "controlled_comparison" for node in nodes)
    assert not any(node["type"] == "document" for node in nodes)
    assert not any(node["label"] == "Case: 15" for node in nodes)

    edge_descriptions = {edge["edge_description"] for edge in edges}
    assert {
        "objective_to_material_system",
        "material_system_to_material_scope",
        "semantic_chain_step_to_step",
    }.issubset(edge_descriptions)
    assert any(
        edge["edge_description"] == "semantic_chain_step_to_step"
        and edge["source_role"] == "material_scope"
        and edge["target_role"] == "process_sample_context"
        and edge["objective_id"] == "obj-1"
        and edge["logic_chain_id"] == "chain-1"
        for edge in edges
    )


def test_core_projection_reuses_material_system_across_objectives():
    second_objective = {
        **_objective("obj-2"),
        "question": "How does heat treatment affect LPBF 316L hardness?",
        "process_axes": ["LPBF", "heat treatment"],
        "property_axes": ["hardness"],
    }
    second_unit = {
        **_measurement_unit("oeu-2", objective_id="obj-2"),
        "property_normalized": "hardness",
        "value_payload": {"source_value_text": "198.4", "value": 198.4},
        "unit": "HV",
    }
    second_chain = {
        **_logic_chain(),
        "logic_chain_id": "chain-2",
        "objective_id": "obj-2",
        "question": second_objective["question"],
        "evidence_unit_ids": ["oeu-2"],
    }

    nodes, edges, truncated = load_core_graph_payload(
        profiles=(_profile(),),
        research_objectives=(_objective(), second_objective),
        objective_evidence_units=(_measurement_unit(), second_unit),
        objective_logic_chains=(_logic_chain(), second_chain),
        max_nodes=40,
        min_weight=0.0,
    )

    assert truncated is False
    material_nodes = [node for node in nodes if node["type"] == "material_system"]
    assert len(material_nodes) == 1
    material_node = material_nodes[0]
    assert material_node["label"] == "316L stainless steel"
    assert material_node["metrics"]["objective_count"] == 2
    assert material_node["metrics"]["logic_chain_count"] == 2
    assert {
        row.get("objective_id")
        for row in material_node["detail_rows"]
        if row.get("objective_id")
    } == {"obj-1", "obj-2"}
    assert {
        row.get("logic_chain_id")
        for row in material_node["detail_rows"]
        if row.get("logic_chain_id")
    } == {"chain-1", "chain-2"}

    material_id = material_node["id"]
    assert sum(1 for edge in edges if edge["target"] == material_id) == 2
    assert {
        edge["edge_description"]
        for edge in edges
        if edge["target"] == material_id
    } == {"objective_to_material_system"}
    assert {
        edge["logic_chain_id"]
        for edge in edges
        if edge["target"] == material_id
    } == {"chain-1", "chain-2"}


def test_core_projection_canonicalizes_material_system_word_order():
    second_objective = {
        **_objective("obj-2"),
        "material_scope": ["stainless steel 316L"],
    }
    second_unit = {
        **_measurement_unit("oeu-2", objective_id="obj-2"),
        "material_system": {"family": "stainless steel 316L"},
    }
    second_chain = {
        **_logic_chain(),
        "logic_chain_id": "chain-2",
        "objective_id": "obj-2",
        "evidence_unit_ids": ["oeu-2"],
    }

    nodes, _edges, _truncated = load_core_graph_payload(
        profiles=(_profile(),),
        research_objectives=(_objective(), second_objective),
        objective_evidence_units=(_measurement_unit(), second_unit),
        objective_logic_chains=(_logic_chain(), second_chain),
        max_nodes=40,
        min_weight=0.0,
    )

    material_nodes = [node for node in nodes if node["type"] == "material_system"]
    assert len(material_nodes) == 1
    assert material_nodes[0]["label"] == "316L stainless steel"
    assert material_nodes[0]["metrics"]["objective_count"] == 2


def test_core_projection_keeps_case_out_of_canvas_nodes():
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

    assert {node["type"] for node in nodes} == {
        "objective",
        "material_system",
        "material_scope",
        "process_sample_context",
        "test_conditions",
        "characterization",
        "measurement_results",
        "controlled_comparisons",
        "mechanism_interpretation",
        "limitations",
    }
    assert not any(node["label"] == "Case: 15" for node in nodes)
    test_step = next(node for node in nodes if node.get("role") == "test_conditions")
    assert test_step["detail_rows"] == []


def test_core_projection_truncates_step_graph_by_objective_and_step_order():
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
        max_nodes=5,
        min_weight=0.0,
    )

    assert truncated is True
    assert len(nodes) == 5
    assert nodes[0]["type"] == "objective"
    assert [node["type"] for node in nodes[1:]] == [
        "material_system",
        "material_scope",
        "process_sample_context",
        "test_conditions",
    ]


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
    assert any(node["type"] == "material_system" for node in payload["nodes"])
    assert any(node["type"] == "measurement_results" for node in payload["nodes"])
    assert any(
        node["role"] == "measurement_results" and node["detail_rows"]
        for node in payload["nodes"]
    )
    assert not any(node["type"] == "measurement" for node in payload["nodes"])
    assert not any(node["type"] == "comparison" for node in payload["nodes"])

    graphml_bytes, filename = graph_service.build_graphml(
        collection_id=collection_id,
        max_nodes=40,
        min_weight=0.0,
    )

    assert filename == f"{collection_id}.graphml"
    assert b"<graphml" in graphml_bytes
    assert b"material_system" in graphml_bytes
    assert b"measurement_results" in graphml_bytes
    assert b"semantic_chain_step_to_step" in graphml_bytes


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
        node_id="step:chain-1:measurement_results",
    )

    assert payload["collection_id"] == collection_id
    assert payload["center_node_id"] == "step:chain-1:measurement_results"
    assert payload["truncated"] is False
    assert {node["id"] for node in payload["nodes"]} >= {
        "step:chain-1:characterization",
        "step:chain-1:measurement_results",
        "step:chain-1:controlled_comparisons",
    }
    assert {edge["id"] for edge in payload["edges"]} >= {
        "edge:step:chain-1:characterization:measurement_results",
        "edge:step:chain-1:measurement_results:controlled_comparisons",
    }
    assert {edge["edge_description"] for edge in payload["edges"]} == {
        "semantic_chain_step_to_step"
    }
